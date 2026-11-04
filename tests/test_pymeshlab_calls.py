"""
PyMeshLab call-site validator.

PyMeshLab reports a wrong filter name, a wrong parameter name and a wrong enum
value the same way: a stringly-typed exception raised at call time. That is only
discoverable when the button is pressed, which is how `meshing_tri_to_quad`,
`compute_ambient_occlusion_per_vertex` and `colorize_by_vertex_quality` shipped
as runtime crashes, and how `ms.number_of_meshes()` hid in a fallback branch.

This reads every `apply_filter(...)` call and every pymeshlab object method out
of src/ and checks them against the installed library. It needs no meshes, no
GPU, no DCC and no files. The library itself is interrogated in a child process
(see _pymeshlab_probe.py); this process imports no pymeshlab at all.

Two invariants make the rest possible, and are themselves asserted:
  * every filter name is a string literal at the call site;
  * no call site unpacks a computed kwargs dict.
Without them a bad name could hide inside a variable and this file could not see
it. Keep them.

Run: python tests/test_pymeshlab_calls.py
"""

import ast
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SRC = os.path.join(ROOT, 'src')
PROBE = os.path.join(ROOT, 'tests', '_pymeshlab_probe.py')
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def source_files():
    for directory, _, files in os.walk(SRC):
        for name in sorted(files):
            if name.endswith('.py'):
                yield os.path.join(directory, name)


def _rel(path):
    return os.path.relpath(path, ROOT).replace('\\', '/')


def module_constants(tree):
    """Top-level `NAME = <literal>` bindings, so `colormap=AO_COLORMAP` is checkable.

    Without this the enum values baked into constants — which is how
    AO_COLORMAP is written — would be invisible to the value check, exactly the
    hiding place a wrong enum needs.
    """
    constants = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def collect_call_sites():
    """Every apply_filter call in src/, with its literal name and literal kwargs."""
    sites = []
    for path in source_files():
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        constants = module_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == 'apply_filter'):
                continue
            first = node.args[0] if node.args else None
            literal_name = isinstance(first, ast.Constant) and isinstance(first.value, str)
            params = {}
            unpacks = False
            for keyword in node.keywords:
                if keyword.arg is None:
                    unpacks = True
                elif isinstance(keyword.value, ast.Constant):
                    params[keyword.arg] = keyword.value.value
                elif (isinstance(keyword.value, ast.Name)
                      and keyword.value.id in constants):
                    params[keyword.arg] = constants[keyword.value.id]
                else:
                    params[keyword.arg] = '<<computed>>'
            sites.append({
                'site': f'{_rel(path)}:{node.lineno}',
                'filter': first.value if literal_name else None,
                'params': params,
                'unpacks': unpacks,
            })
    return sites


def run_probe(sites):
    """Ask the installed library one question, in a child process, and get JSON back.

    Returns None when pymeshlab is not installed at all.
    """
    filters = sorted({s['filter'] for s in sites if s['filter']})
    probes = []
    seen = set()
    for site in sites:
        if not site['filter']:
            continue
        for param, value in site['params'].items():
            if isinstance(value, str) and value != '<<computed>>':
                if (site['filter'], param) not in seen:
                    seen.add((site['filter'], param))
                    probes.append({'filter': site['filter'], 'param': param})
    spec = json.dumps({'filters': filters, 'enums': probes})
    proc = subprocess.run([sys.executable, PROBE], input=spec,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', errors='replace')
    if proc.returncode != 0:
        message = (proc.stderr or '').strip().splitlines()
        reason = message[-1] if message else f'probe exited {proc.returncode}'
        if 'No module named' in reason and 'pymeshlab' in reason:
            return None
        raise RuntimeError(f'PyMeshLab probe failed: {reason}')
    return json.loads(proc.stdout)


class TestPyMeshLabCalls(unittest.TestCase):
    """Every filter call and object method in the app has to exist in this build."""

    @classmethod
    def setUpClass(cls):
        cls.sites = collect_call_sites()
        try:
            cls.report = run_probe(cls.sites)
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        if cls.report is None:
            raise unittest.SkipTest('pymeshlab is not installed')
        cls.available = set(cls.report['filters'])

    def parameters_for(self, filter_name):
        value = self.report['params'].get(filter_name)
        if isinstance(value, list):
            return set(value)
        return None

    def test_01_call_sites_exist(self):
        self.assertGreater(len(self.sites), 0, 'No apply_filter calls found in src/')

    def test_02_filter_names_are_literals(self):
        """A computed filter name is invisible to this validator, so it is banned."""
        dynamic = [s['site'] for s in self.sites if s['filter'] is None]
        self.assertEqual([], dynamic,
                         'apply_filter called with a non-literal filter name; give each '
                         'branch its own literal call')

    def test_03_no_kwargs_unpacking(self):
        unpacking = [s['site'] for s in self.sites if s['unpacks']]
        self.assertEqual([], unpacking,
                         'apply_filter called with **kwargs; pass the parameters literally')

    def test_04_every_filter_is_in_this_build(self):
        for site in self.sites:
            if site['filter'] is None:
                continue  # reported by test_02
            if site['filter'] in self.available:
                continue
            close = difflib.get_close_matches(site['filter'], sorted(self.available),
                                              n=3, cutoff=0.55)
            self.fail(f"{site['site']} uses {site['filter']!r}, which is not one of the "
                      f"{len(self.available)} filters in this PyMeshLab build. "
                      f"Closest: {close or 'none'}")

    def test_05_every_parameter_exists(self):
        verified = 0
        for site in self.sites:
            names = self.parameters_for(site['filter']) if site['filter'] else None
            if names is None:
                continue  # reported by test_04, or unreadable by this build
            for param in site['params']:
                verified += 1
                with self.subTest(site=site['site'], filter=site['filter'], param=param):
                    self.assertIn(param, names,
                                  f"{site['site']} passes a parameter {site['filter']} "
                                  f"does not accept; this filter takes {sorted(names)}")
        self.assertGreater(verified, 0, 'No filter parameters were read at all')

    def test_06_enum_values_are_valid(self):
        """The accepted list for each string parameter was read out of the library."""
        verified = 0
        for site in self.sites:
            if not site['filter']:
                continue
            for param, value in site['params'].items():
                if not isinstance(value, str) or value == '<<computed>>':
                    continue
                allowed = self.report['enums'].get(f"{site['filter']}|{param}")
                if not isinstance(allowed, list):
                    continue  # the filter has no enum there, or failed before validating
                verified += 1
                with self.subTest(site=site['site'], filter=site['filter'],
                                  param=param, value=value):
                    self.assertIn(value, allowed,
                                  f"{site['site']} passes {param}={value!r}; this "
                                  f"build accepts {allowed}")
        self.assertGreater(verified, 0, 'No string parameters were checked at all')

    def test_07_meshset_and_mesh_api_names_exist(self):
        """Methods called on pymeshlab objects, not just the filters they run.

        `format_converter.py` called `ms.number_of_meshes()`, which 2025.7 does
        not have. It sits in the fallback branch that only runs when trimesh
        fails, so no suite ever reached it.
        """
        set_members = set(self.report['meshset_members'])
        mesh_members = set(self.report['mesh_members'])
        offenders = []
        tracked = set()

        for path in source_files():
            with open(path, encoding='utf-8') as handle:
                text = handle.read()
            if 'import pymeshlab' not in text:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue

            set_vars, mesh_vars = set(), set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                value = node.value
                if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
                    continue
                holder = _dotted(value.func.value)
                name = _dotted(node.targets[0])
                if name is None:
                    continue
                if holder == 'pymeshlab' and value.func.attr == 'MeshSet':
                    set_vars.add(name)
                elif holder == 'pymeshlab' and value.func.attr == 'Mesh':
                    mesh_vars.add(name)
                elif holder in set_vars and value.func.attr in ('current_mesh', 'mesh'):
                    mesh_vars.add(name)

            tracked |= set_vars | mesh_vars
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                owner = _dotted(node.func.value)
                if owner in set_vars and node.func.attr not in set_members:
                    offenders.append(f"{_rel(path)}:{node.lineno} MeshSet.{node.func.attr}")
                elif owner in mesh_vars and node.func.attr not in mesh_members:
                    offenders.append(f"{_rel(path)}:{node.lineno} Mesh.{node.func.attr}")

        self.assertTrue(tracked, 'no pymeshlab objects were tracked; the check is not running')
        self.assertEqual([], sorted(set(offenders)),
                         'pymeshlab objects were given methods this build does not have')


class TestPyMeshLabFallbackRuns(unittest.TestCase):
    """The pymeshlab conversion branch only runs when trimesh fails, so nothing
    routed a real file through it and a wrong object method sat there unnoticed.
    """

    _TETRA_OBJ = ("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n"
                  "f 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n")

    def test_01_pymeshlab_conversion_writes_a_loadable_mesh(self):
        import pymeshlab
        from src.processing.format_converter import FormatConverter

        work = tempfile.mkdtemp(prefix='renderfox_pmlab_convert_')
        try:
            source = os.path.join(work, 'tetra.obj')
            target = os.path.join(work, 'tetra.ply')
            with open(source, 'w', encoding='utf-8') as handle:
                handle.write(self._TETRA_OBJ)

            result = FormatConverter()._convert_with_pymeshlab(source, target, {})
            self.assertTrue(result['success'], result.get('message'))
            self.assertTrue(os.path.exists(target), 'no file at the promised output path')

            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(target)
            self.assertEqual(4, ms.current_mesh().vertex_number())
            self.assertEqual(4, ms.current_mesh().face_number())
        finally:
            shutil.rmtree(work, ignore_errors=True)


def _dotted(node):
    """'self.ms' / 'ms' for a simple Name or Attribute chain, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f'{node.value.id}.{node.attr}'
    return None


if __name__ == '__main__':
    unittest.main(verbosity=2)
