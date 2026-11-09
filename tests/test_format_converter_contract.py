"""
Format converter contract test.

Every pair in FormatConverter's capability table is converted for real here, into a
temp folder, and has to leave a file another library can open. The table used to be a
typed-out wish list: it promised `.obj -> .fbx` and `.obj -> .dae` while the assimp
path that is the only way to write either was calling `pyassimp.load()` as if it
returned a scene, which it does not - so those two conversions had never succeeded,
and `.off`/`.3mf` were listed as formats the app supports but were in no target list
at all.

Seeds are written with the libraries directly, not with the converter, so a test
cannot pass by believing the thing it is checking.

Run: python -X utf8 tests/test_format_converter_contract.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import pymeshlab
import pyassimp
import trimesh
from PyQt6.QtCore import Qt

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.processing.format_converter import FormatConverter, SupportedFormat, _extension
from src.processing.script_engine import ScriptAPI

FORMATS = [fmt.value.lstrip('.') for fmt in SupportedFormat]

# The exporter ids are the DLL's, not the app's - see _ASSIMP_EXPORT_IDS.
ASSIMP_IDS = {'obj': 'obj', 'ply': 'ply', 'stl': 'stl', 'gltf': 'gltf2', 'glb': 'glb2',
              'dae': 'collada', 'fbx': 'fbx', '3mf': '3mf'}


class FormatCase(unittest.TestCase):
    """One temp folder, one set of seed files, one converter."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='format_contract_')
        cls.converter = FormatConverter()
        cls.seeds = {}
        cls.seed_with = {}

        obj = os.path.join(cls.work, 'seed.obj')
        box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
        box.export(obj)
        cls.seeds['obj'] = obj
        cls.seed_with['obj'] = 'trimesh'

        for fmt in FORMATS:
            if fmt == 'obj':
                continue
            path = os.path.join(cls.work, f'seed.{fmt}')
            try:
                mesh_set = pymeshlab.MeshSet()
                mesh_set.load_new_mesh(obj)
                mesh_set.save_current_mesh(path)
            except Exception:
                pass  # pymeshlab has no glTF/glb/FBX writer; assimp is tried next
            if os.path.isfile(path) and os.path.getsize(path):
                cls.seeds[fmt] = path
                cls.seed_with[fmt] = 'pymeshlab'
                continue
            with pyassimp.load(obj) as scene:
                pyassimp.export(scene, path, ASSIMP_IDS[fmt])
            if os.path.isfile(path) and os.path.getsize(path):
                cls.seeds[fmt] = path
                cls.seed_with[fmt] = 'assimp'

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix='out_', dir=self.work)

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def target(self, fmt):
        return os.path.join(self.out, f'result.{fmt}')

    def require_seed(self, fmt):
        if fmt not in self.seeds:
            self.fail(f'no .{fmt} file could be written by any library here, so the '
                      f'app cannot claim .{fmt} as a source either')
        return self.seeds[fmt]


class TestClaimsAreTrue(FormatCase):

    def test_01_every_claimed_target_produces_a_file(self):
        """If the table says a pair can be done, doing it has to write a real file."""
        for source in FORMATS:
            src = self.require_seed(source)
            for target in self.converter.get_supported_targets(source):
                fmt = _extension(target)
                if fmt == source:
                    continue
                result = self.converter.convert_file(src, self.target(fmt))
                path = self.target(fmt)
                self.assertTrue(result['success'],
                                f'{source} -> {fmt}: {result["message"]}')
                self.assertGreater(os.path.getsize(path), 0, f'{source} -> {fmt} is empty')
                self.assertIn(result['method'],
                              self.converter.conversion_libraries(source, fmt),
                              f'{source} -> {fmt} reported a library that cannot do it')

    def test_02_a_converted_file_is_the_mesh_it_came_from(self):
        """A conversion that writes garbage is still a file, so read the geometry back.

        Faces are what is compared: a reader is free to merge the duplicate corners a
        cube carries for its per-face normals, and several do, but it is not free to
        lose triangles.
        """
        src = self.require_seed('obj')
        expected = len(self.converter.read_mesh(src)[0].faces)
        for target in self.converter.get_supported_targets('obj'):
            fmt = _extension(target)
            result = self.converter.convert_file(src, self.target(fmt))
            self.assertTrue(result['success'], f'obj -> {fmt}: {result["message"]}')
            mesh, note = self.converter.read_mesh(self.target(fmt))
            self.assertIsNotNone(mesh, f'obj -> {fmt} cannot be opened again ({note})')
            self.assertEqual(len(mesh.faces), expected, f'obj -> {fmt} changed the face count')
            self.assertGreater(len(mesh.vertices), 0, f'obj -> {fmt} has no vertices')

    def test_02b_each_success_reports_file_backed_coverage(self):
        src = self.require_seed('obj')
        result = self.converter.convert_file(src, self.target('ply'))
        self.assertTrue(result['success'], result['message'])
        coverage = result.get('coverage')
        self.assertIsNotNone(coverage)
        self.assertIn('source', coverage)
        self.assertIn('output', coverage)
        self.assertIn('retained', coverage)
        self.assertIn('not_retained', coverage)

    def test_03_an_unclaimed_pair_refuses_without_crashing(self):
        """Same-format and impossible pairs return a reason instead of an exception."""
        src = self.require_seed('obj')
        same = self.converter.convert_file(src, self.target('obj'))
        self.assertFalse(same['success'])
        self.assertIn('already', same['message'])

        blocked = FormatConverter()
        blocked.libraries_status = dict(blocked.libraries_status, assimp=False, pymeshlab=False)
        result = blocked.convert_file(src, self.target('fbx'))
        self.assertFalse(result['success'])
        self.assertIn('assimp', result['message'])

    def test_04_targets_are_what_the_installed_libraries_can_do(self):
        """Drop a library and the offers have to drop with it - not stay a promise."""
        with_assimp = set(self.converter.get_supported_targets('obj'))
        self.assertIn('.fbx', with_assimp, 'assimp is available, so FBX output should be offered')

        without = FormatConverter()
        without.libraries_status = dict(without.libraries_status, assimp=False)
        narrowed = set(without.get_supported_targets('obj'))
        self.assertNotIn('.fbx', narrowed, 'FBX is only writable by assimp')
        self.assertTrue(with_assimp - narrowed, 'removing a library changed nothing')


class TestTheFormatsThatWereBroken(FormatCase):

    def test_05_fbx_output_is_written_and_readable(self):
        """The assimp path had never succeeded: pyassimp.load() is a context manager."""
        src = self.require_seed('obj')
        path = self.target('fbx')
        result = self.converter.convert_file(src, path)
        self.assertTrue(result['success'], result['message'])
        self.assertEqual(result['method'], 'assimp')
        self.assertGreater(os.path.getsize(path), 1000, 'a real FBX is not a stub')

        mesh_set = pymeshlab.MeshSet()
        mesh_set.load_new_mesh(path)
        self.assertEqual(mesh_set.current_mesh().face_number(), 12,
                         'the FBX does not hold the cube that went in')

    def test_06_dae_output_is_written_and_readable(self):
        src = self.require_seed('obj')
        path = self.target('dae')
        result = self.converter.convert_file(src, path)
        self.assertTrue(result['success'], result['message'])

        mesh, note = self.converter.read_mesh(path)
        self.assertIsNotNone(mesh, f'the .dae cannot be opened again ({note})')
        self.assertEqual(len(mesh.faces), 12)

    def test_07_off_and_3mf_are_reachable_targets(self):
        """Both were in SupportedFormat and in no target list, so neither was offered."""
        src = self.require_seed('obj')
        targets = self.converter.get_supported_targets('obj')
        for fmt in ('off', '3mf'):
            self.assertIn(f'.{fmt}', targets, f'{fmt} is advertised but never offered')
            result = self.converter.convert_file(src, self.target(fmt))
            self.assertTrue(result['success'], f'{fmt}: {result["message"]}')

    def test_08_fbx_and_dae_sources_can_be_previewed(self):
        """The preview asked trimesh, which cannot open either format at all."""
        for fmt in ('fbx', 'dae'):
            src = self.require_seed(fmt)
            preview = self.converter.get_conversion_preview(src)
            self.assertNotIn('error', preview, f'{fmt}: {preview.get("error")}')
            self.assertEqual(preview['faces'], 12, f'{fmt} preview lost geometry')
            self.assertGreater(preview['vertices'], 0)
            self.assertIn(preview['opened_with'], ('pymeshlab', 'assimp'))

    def test_09_a_corrupt_file_fails_as_a_result_not_as_a_crash(self):
        """Run it in a child: MeshLab's FBX reader answers a bad file with an access
        violation, and a test that segfaults the runner reports nothing at all. The
        exit code is the assertion - 0xC0000005 means the guard came loose."""
        script = (
            "import os, sys, json\n"
            "sys.path.insert(0, os.getcwd())\n"
            "from src.processing.format_converter import FormatConverter\n"
            "out = sys.argv[2]\n"
            "for target in ('obj', 'stl'):\n"
            "    path = os.path.join(out, 'bad.' + target)\n"
            "    print('RESULT ' + json.dumps(FormatConverter().convert_file(sys.argv[1], path)))\n"
            "print('SURVIVED')\n"
        )
        bad = os.path.join(self.out, 'bad.fbx')
        with open(bad, 'wb') as handle:
            handle.write(b'not an fbx at all, just bytes with a suffix')

        proc = subprocess.run([sys.executable, '-X', 'utf8', '-c', script, bad, self.out],
                              capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
        self.assertEqual(proc.returncode, 0,
                         f'the converter killed the process (exit {proc.returncode:#x}); '
                         f'a corrupt file has to be a failed row, not a dead app\n{proc.stderr[-300:]}')
        self.assertIn('SURVIVED', proc.stdout)
        # assimp's build prints its own progress to stdout, so only the marked lines count.
        payloads = [line.split(' ', 1)[1] for line in proc.stdout.splitlines()
                    if line.startswith('RESULT ')]
        self.assertEqual(len(payloads), 2, f'expected one line per target, got {payloads}')
        for payload in payloads:
            result = json.loads(payload)
            self.assertFalse(result['success'], f'a corrupt .fbx reported {result}')
            self.assertIn('no FBX header', result['message'])


class TestOptionsAndReports(FormatCase):

    def test_10_scale_is_applied_when_the_library_can_apply_it(self):
        src = self.require_seed('obj')
        path = self.target('stl')
        result = self.converter.convert_file(src, path, {'scale': 2.0})
        self.assertTrue(result['success'], result['message'])
        self.assertEqual(result['options_skipped'], [])
        mesh = trimesh.load(path)
        self.assertTrue(np.allclose(mesh.extents, [4.0, 4.0, 4.0]),
                        f'the file is {mesh.extents}, not twice the 2-unit cube')

    def test_11_a_library_that_cannot_apply_an_option_says_so(self):
        src = self.require_seed('obj')
        result = self.converter.convert_file(src, self.target('fbx'), {'scale': 2.0})
        self.assertTrue(result['success'], result['message'])
        self.assertEqual(result['options_skipped'], ['scale'],
                         'assimp writes the scene it loaded; the scale cannot reach it')

    def test_12_a_default_option_is_not_reported_as_skipped(self):
        """The panels hand every option whether or not the user touched it."""
        src = self.require_seed('obj')
        result = self.converter.convert_file(src, self.target('fbx'),
                                             {'scale': 1.0, 'center': False, 'repair': False})
        self.assertEqual(result['options_skipped'], [],
                         'a warning about a no-op is noise that trains the user to ignore it')

    def test_13_batch_reports_the_library_that_actually_worked(self):
        first = self.require_seed('obj')
        second = self.require_seed('ply')
        results = self.converter.batch_convert([first, second], self.out, SupportedFormat.GLB)
        self.assertEqual(len(results['successful']), 2, results['errors'])
        self.assertEqual(results['library_used'], 'trimesh',
                         'the summary used to name the first installed library')
        for entry in results['successful']:
            self.assertEqual(entry['method'], 'trimesh')

    def test_14_a_batch_that_cannot_be_written_says_none_rather_than_trimesh(self):
        src = self.require_seed('obj')
        starved = FormatConverter()
        starved.libraries_status = dict(starved.libraries_status, assimp=False, pymeshlab=False)
        results = starved.batch_convert([src], self.out, SupportedFormat.FBX)
        self.assertEqual(results['successful'], [])
        self.assertEqual(results['library_used'], 'None')
        self.assertIn('assimp', results['errors'][0])

    def test_15_lod_chain_reaches_a_target_trimesh_cannot_write(self):
        src = self.require_seed('obj')
        files = self.converter.convert_with_lod_generation(src, self.out, SupportedFormat.DAE)
        self.assertEqual(len(files), 4, f'expected an LOD chain, got {files}')
        for path in files:
            self.assertEqual(Path(path).suffix, '.dae', f'{path} is not the target asked for')
            mesh, note = self.converter.read_mesh(path)
            self.assertIsNotNone(mesh, f'{path} cannot be opened ({note})')

    def test_16_a_bare_output_filename_does_not_raise(self):
        """dirname() is '' for 'result.stl', and makedirs('') is a FileNotFoundError."""
        src = self.require_seed('obj')
        previous = os.getcwd()
        os.chdir(self.out)
        try:
            result = self.converter.convert_file(src, 'result.stl')
            self.assertTrue(result['success'], result['message'])
            self.assertTrue(os.path.isfile('result.stl'))
        finally:
            os.chdir(previous)

    def test_17_the_documented_script_api_converts(self):
        """rfx.convert_format() called converter.convert(), which does not exist."""
        src = self.require_seed('obj')
        api = ScriptAPI()
        path = api.convert_format(src, 'stl')
        self.assertTrue(os.path.isfile(path), f'{path} was not written')

        starved = ScriptAPI()
        with self.assertRaises(RuntimeError) as caught:
            converter_target = os.path.join(self.out, 'nope.fbx')
            original = FormatConverter.convert_file
            FormatConverter.convert_file = lambda *a, **k: {
                'success': False, 'message': 'assimp is not installed here', 'method': None}
            try:
                starved.convert_format(src, 'fbx', converter_target)
            finally:
                FormatConverter.convert_file = original
        self.assertIn('assimp is not installed here', str(caught.exception),
                      'a refused conversion has to say why, not just "failed"')


class TestItSurvivesAnotherMachine(FormatCase):
    """The FBX writer is a native DLL, so it can be present here and absent anywhere else.

    Nothing in the app said where that DLL has to be, and a PyInstaller build unpacks
    its data files somewhere that is not three folders above the module's __file__, so
    the released .exe would have lost .fbx and .dae output without a word.
    """

    PROBE = (
        "import os, sys, json\n"
        "sys.path.insert(0, os.getcwd())\n"
        "lib = os.path.join(os.getcwd(), 'lib')\n"
        "norm = lambda p: os.path.normcase(os.path.abspath(p)) if p else ''\n"
        "os.environ['PATH'] = ';'.join(p for p in os.environ['PATH'].split(';')\n"
        "                              if norm(p) != norm(lib))\n"
        "import src.processing.format_converter as fc\n"
        "print('RESULT ' + json.dumps({\n"
        "    'rebuilt': norm(lib) in [norm(p) for p in os.environ['PATH'].split(';')],\n"
        "    'assimp': fc.ASSIMP_AVAILABLE,\n"
        "    'dirs': fc._ASSIMP_LIB_DIRS,\n"
        "    'dll': os.path.isfile(os.path.join(lib, 'assimp-vc143-mt.dll')),\n"
        "    'blocker': fc.FormatConverter().conversion_blocker('.obj', '.fbx'),\n"
        "}))\n"
    )

    def probe(self):
        proc = subprocess.run([sys.executable, '-X', 'utf8', '-c', self.PROBE],
                              capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.dirname(__file__)))
        self.assertEqual(proc.returncode, 0, f'probe died\n{proc.stderr[-400:]}')
        lines = [line.split(' ', 1)[1] for line in proc.stdout.splitlines()
                 if line.startswith('RESULT ')]
        self.assertEqual(len(lines), 1, f'probe said nothing:\n{proc.stdout[-400:]}')
        return json.loads(lines[0])

    def test_18_the_app_finds_its_own_assimp_build(self):
        """Strip lib/ from PATH and import: the bootstrap has to put it back."""
        found = self.probe()
        if not found['dll']:
            # A clone with no binaries is allowed, but only if it says so out loud.
            self.assertFalse(found['assimp'],
                             'assimp loaded with no DLL in lib/, so it came from somewhere '
                             'the release does not control')
            self.assertIn('assimp', found['blocker'])
            self.assertIn('Looked in', found['blocker'],
                          'a missing FBX writer with no hint of where it was searched for')
            return
        self.assertTrue(found['rebuilt'],
                        'the converter does not add its own lib/ to PATH, so on a machine '
                        'that never had assimp the .fbx and .dae targets silently vanish')
        self.assertTrue(found['assimp'],
                        f'lib/ was put on PATH and pyassimp still found nothing: {found["dirs"]}')

    def test_19_the_build_recipe_ships_the_fbx_writer(self):
        """requirements.txt and RenderFox.spec, read the way pip and pyinstaller read them."""
        root = os.path.dirname(os.path.dirname(__file__))
        requirements = open(os.path.join(root, 'requirements.txt'), encoding='utf-8').read()
        declared = set()
        for line in requirements.splitlines():
            line = line.split('#', 1)[0].strip().lower()
            if line:
                declared.add(re.split(r'[<>=!~\[\s]', line, 1)[0])
        self.assertIn('pyassimp', declared,
                      'not a requirement (a comment about it does not install it), so '
                      'pip install -r requirements.txt leaves this app with no FBX writer')

        spec = open(os.path.join(root, 'RenderFox.spec'), encoding='utf-8').read().lower()
        self.assertIn("'pyassimp'", section_of(spec, 'hiddenimports'),
                      'pyassimp is not a hidden import, so the bundle has no binding to '
                      'call the DLL with')
        self.assertIn('assimp-vc143-mt.dll', section_of(spec, 'datas'),
                      'the DLL is not collected, so the packaged app has the binding and '
                      'no library - and the only symptom is that .fbx stops working')


def section_of(text, keyword):
    """The bracketed list a PyInstaller spec assigns to `keyword`, or ''."""
    start = text.find(keyword + '=')
    if start < 0:
        return ''
    open_char = text.find('[', start)
    if open_char < 0:
        return ''
    depth = 0
    for index in range(open_char, len(text)):
        if text[index] == '[':
            depth += 1
        elif text[index] == ']':
            depth -= 1
            if depth == 0:
                return text[open_char:index + 1]
    return ''


class TestThePickerTellsTheTruth(FormatCase):
    """The conversion panel is driven for real, because it used to ignore the converter.

    Its target list was every SupportedFormat whatever was installed, so a machine
    without an assimp build was still offered FBX and the batch came back as failures;
    and its file-open filter left .fbx out, so the flagship format could not even be
    picked.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from src.ui.preprocessing_tab import PreProcessingTab
        cls.tab_class = PreProcessingTab

    def setUp(self):
        super().setUp()
        self.tab = self.tab_class()

    def tearDown(self):
        self.tab.deleteLater()
        super().tearDown()

    def load(self, files):
        """Drive the real Add Files button with the given list."""
        import src.ui.preprocessing_tab as panel
        captured = []

        def fake_dialog(*args, **kwargs):
            captured.append(args[3] if len(args) > 3 else kwargs.get('filter', ''))
            return list(files), captured[-1]

        previous = panel.QFileDialog.getOpenFileNames
        panel.QFileDialog.getOpenFileNames = fake_dialog
        try:
            self.tab.add_conversion_files()
        finally:
            panel.QFileDialog.getOpenFileNames = previous
        return captured

    def item_for(self, fmt):
        for index in range(self.tab.target_format.count()):
            if self.tab.target_format.itemData(index).value == fmt:
                return index
        self.fail(f'{fmt} is not in the target picker at all')

    def test_20_the_batch_picker_can_be_handed_an_fbx(self):
        """The dialog filter left .fbx out, so the game-dev format could not be chosen."""
        src = self.require_seed('fbx')
        filters = self.load([src])
        self.assertTrue(filters, 'the Add Files button never reached a file dialog')
        self.assertIn('*.fbx', filters[0],
                      f'FBX is not in the open filter, so it is hidden from the picker: {filters[0]}')
        self.assertEqual(self.tab.conversion_files_list.count(), 1,
                         'an .fbx the converter accepts was refused by the panel')

    def test_21_a_target_with_no_library_is_not_offered(self):
        src = self.require_seed('obj')
        self.load([src])
        converter = self.tab.format_converter
        self.tab.format_converter = type(converter)()
        self.tab.format_converter.libraries_status = dict(
            converter.libraries_status, assimp=False)
        try:
            self.tab._refresh_target_availability()
            fbx = self.item_for('.fbx')
            model = self.tab.target_format.model()
            self.assertFalse(model.item(fbx).isEnabled(),
                             'FBX stayed selectable with no assimp, so the batch was '
                             'only ever going to fail')
            self.assertIn('assimp', self.tab.target_format.itemData(
                fbx, Qt.ItemDataRole.ToolTipRole))

            self.tab.format_converter.libraries_status = dict(converter.libraries_status)
            self.tab._refresh_target_availability()
            self.assertTrue(model.item(fbx).isEnabled(),
                            'FBX stayed disabled after the library came back')
        finally:
            self.tab.format_converter = converter

    def test_22_the_selected_target_is_one_that_can_actually_run(self):
        """A picker left pointing at a greyed-out row converts nothing and says nothing."""
        src = self.require_seed('obj')
        self.load([src])
        converter = self.tab.format_converter
        starved = type(converter)()
        starved.libraries_status = dict(converter.libraries_status, assimp=False, pymeshlab=False)
        self.tab.format_converter = starved
        try:
            self.tab.target_format.setCurrentIndex(self.item_for('.fbx'))
            self.tab._refresh_target_availability()
            chosen = self.tab.target_format.currentData()
            self.assertNotEqual('.fbx', chosen.value,
                                'FBX was still the current choice with nothing to write it')
            self.assertTrue(starved.can_convert('.obj', chosen.value))
        finally:
            self.tab.format_converter = converter
            self.tab._refresh_target_availability()

    def test_23_the_model_dialog_picks_the_converter_formats(self):
        """The other conversion dialog had its own list, and it disagreed on two counts."""
        import src.ui.model_tab as model_tab
        from src.ui.model_tab import ModelFormatConverter

        dialog = ModelFormatConverter(input_files=[])
        captured = []

        def fake_dialog(*args, **kwargs):
            captured.append(args[3] if len(args) > 3 else kwargs.get('filter', ''))
            return [self.seeds['off'], os.path.join(self.out, 'car.x3d')], ''

        previous = model_tab.QFileDialog.getOpenFileNames
        model_tab.QFileDialog.getOpenFileNames = fake_dialog
        try:
            dialog.add_input_files()
        finally:
            model_tab.QFileDialog.getOpenFileNames = previous

        self.assertTrue(captured and captured[0], 'no filter was passed to the file dialog')
        for fmt in SupportedFormat:
            self.assertIn(f'*{fmt.value}', captured[0],
                          f'{fmt.value} is a format the converter reads but the dialog '
                          f'hides it: {captured[0]}')
        self.assertEqual([os.path.basename(p) for p in dialog.input_files],
                         [os.path.basename(self.seeds['off'])],
                         'the dialog accepted a format the converter refuses')
        dialog.deleteLater()


def gltf_document(path):
    """The JSON inside a .glb or .gltf, counted here rather than by the app under test."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    if path.endswith('.gltf'):
        return json.loads(raw.decode('utf-8', 'replace'))
    return json.loads(raw[20:20 + int.from_bytes(raw[12:16], 'little')].decode('utf-8'))


def textured_box(folder, name, shift, top, bottom):
    """A box wearing one named image, built with trimesh rather than with the converter.

    `top` and `bottom` have to differ between the parts: measured here, two materials
    whose image bytes are identical are written as one `newmtl`, so a fixture that shades
    both the same way holds one material and cannot test preservation of two.
    """
    from PIL import Image
    raw = trimesh.creation.box(extents=(1, 2, 3))
    mesh = trimesh.Trimesh(vertices=raw.vertices, faces=raw.faces, process=False)
    picture = os.path.join(folder, f'{name}.png')
    grid = (np.indices((8, 8)).sum(axis=0) % 2).astype(np.uint8)
    Image.fromarray(np.dstack([grid * top, grid * bottom, 255 - grid * 120])).save(picture)
    material = trimesh.visual.material.SimpleMaterial(image=Image.open(picture).convert('RGB'))
    material.name = name
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.round(np.random.RandomState(1).rand(len(mesh.vertices), 2), 5), material=material)
    mesh.apply_transform(trimesh.transformations.translation_matrix(shift))
    return mesh


def painted_box(shift):
    """A box with colour carried on its vertices, which no material is asked about."""
    raw = trimesh.creation.box(extents=(1, 2, 3))
    mesh = trimesh.Trimesh(vertices=raw.vertices, faces=raw.faces, process=False)
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh, vertex_colors=np.tile(np.array([[10, 200, 30, 255]], dtype=np.uint8),
                                         (len(mesh.vertices), 1)))
    mesh.apply_transform(trimesh.transformations.translation_matrix(shift))
    return mesh


def obj_material_names(path):
    """The `usemtl` names an .obj actually reaches for, read off its own lines."""
    with open(path, 'r', errors='replace') as handle:
        return sorted({line.split()[1] for line in handle if line.startswith('usemtl')})


class TestTheMaterialSwitch(FormatCase):
    """`preserve_materials` has to change the call, and the answer has to come off the file.

    The control sat in the batch pane answering nothing for months. Measured here before
    any of it was wired: a .obj carrying two named materials converted to .glb left ONE
    material in the file however the box was set, because `as_trimesh()` merges the parts
    and a merged mesh can hold only one visual. So every test below counts the material,
    image and attribute records inside the bytes that were written, with `gltf_document`
    above rather than with the app's own reader - and the geometry is compared too, because
    a switch that changes the file by breaking it is not a switch.

    `FormatCase`'s seeds are plain boxes with nothing to keep, so these fixtures are built
    with trimesh directly.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # One folder each: trimesh names an .obj's sidecar 'material.mtl' unless told
        # otherwise, so three .obj fixtures written into one folder share - and the last
        # one overwrites - the materials the first two are read back through. This is the
        # same hazard `write_scene` hands a model named after itself to dodge.
        def folder(name):
            path = os.path.join(cls.work, name)
            os.makedirs(path, exist_ok=True)
            return path

        two = folder('two_materials')
        cls.two_material = os.path.join(two, 'model.obj')
        trimesh.Scene([textured_box(two, 'MatRed', [0, 0, 0], 220, 40),
                       textured_box(two, 'MatBlue', [4, 0, 0], 40, 220)]).export(cls.two_material)

        one = folder('one_material')
        cls.single_material = os.path.join(one, 'model.obj')
        trimesh.Scene([textured_box(one, 'Solo', [0, 0, 0], 220, 40)]).export(cls.single_material)

        mixed = folder('mixed')
        cls.mixed = os.path.join(mixed, 'model.glb')
        trimesh.Scene([textured_box(mixed, 'MatRed', [0, 0, 0], 220, 40),
                       painted_box([4, 0, 0])]).export(cls.mixed)

        pair = folder('pair')
        cls.two_as_glb = os.path.join(pair, 'model.glb')
        trimesh.Scene([textured_box(pair, 'MatRed', [0, 0, 0], 220, 40),
                       textured_box(pair, 'MatBlue', [4, 0, 0], 40, 220)]).export(cls.two_as_glb)

    def named(self, path):
        """(materials, images, attribute names) as the written container itself says them."""
        document = gltf_document(path)
        attributes = {str(key) for mesh in document.get('meshes') or []
                      for prim in mesh.get('primitives') or []
                      for key in (prim.get('attributes') or {})}
        return (len(document.get('materials') or []),
                len(document.get('images') or []), attributes)

    def convert(self, source, name, keep):
        """Write `name` from `source` with the switch at `keep`, and refuse a failure."""
        path = os.path.join(self.out, name)
        options = None if keep is None else {'preserve_materials': keep}
        result = self.converter.convert_file(source, path, options)
        self.assertTrue(result['success'], f'{name}: {result["message"]}')
        return path, result

    def signals(self):
        """The pane's own channel, captured as the conversion emits it."""
        case = self

        class Capture:
            def __init__(self):
                self.messages = []

            def record(self, path, ok, text):
                self.messages.append((path, ok, text))

            def __enter__(self):
                case.converter.conversion_completed.connect(self.record)
                return self

            def __exit__(self, *exc):
                case.converter.conversion_completed.disconnect(self.record)
                return False

        return Capture()

    def test_24_the_switch_changes_which_call_runs(self):
        on, on_result = self.convert(self.two_material, 'kept.glb', True)
        off, off_result = self.convert(self.two_material, 'stripped.glb', False)

        on_materials, on_images, on_attributes = self.named(on)
        off_materials, off_images, off_attributes = self.named(off)
        self.assertEqual((on_materials, on_images), (2, 2),
                         f'the .glb written with the switch on names {on_materials} materials '
                         f'and {on_images} images, read off its own JSON')
        self.assertEqual((off_materials, off_images), (0, 0),
                         f'the .glb written with the switch off still carries '
                         f'{off_materials} materials and {off_images} images, so the two '
                         f'answers made the same call')
        self.assertTrue(any(key.startswith('TEXCOORD') for key in on_attributes),
                        f'no texture coordinates were written with the switch on: {on_attributes}')
        self.assertFalse(any(key.startswith('TEXCOORD') for key in off_attributes),
                         f'texture coordinates survived the switch off: {off_attributes}')

        for path, result in ((on, on_result), (off, off_result)):
            self.assertEqual(result['options_skipped'], [], path)
        on_mesh, on_note = self.converter.read_mesh(on)
        off_mesh, off_note = self.converter.read_mesh(off)
        self.assertIsNotNone(on_mesh, on_note)
        self.assertIsNotNone(off_mesh, off_note)
        self.assertEqual(len(on_mesh.faces), len(off_mesh.faces),
                         'the switch changed the triangle count, which is not what it claims')
        self.assertTrue(np.allclose(on_mesh.bounds, off_mesh.bounds),
                        'the switch moved the model')

    def test_25_a_source_with_one_material_is_left_alone_either_way(self):
        """The route a caller that says nothing takes, and the route on takes, agree here."""
        asked, asked_result = self.convert(self.single_material, 'asked.glb', True)
        silent, _ = self.convert(self.single_material, 'silent.glb', None)
        for path in (asked, silent):
            materials, images, attributes = self.named(path)
            self.assertEqual((materials, images), (1, 1),
                             f'{os.path.basename(path)} lost the material it came in with')
            self.assertTrue(any(key.startswith('TEXCOORD') for key in attributes), path)
        self.assertIn('keeps 1 material, 1 texture', asked_result.get('content') or '',
                      f'the file holds one of each and the answer said: '
                      f'{asked_result.get("content")!r}')
        stripped, _ = self.convert(self.single_material, 'stripped.glb', False)
        self.assertEqual(self.named(stripped)[:2], (0, 0),
                         'off left this file the way on left it, so the switch is not read')

    def test_26_the_switch_is_about_the_texture_not_the_painted_vertices(self):
        """Stripping a material must not quietly take the colours off the vertices too."""
        on, on_result = self.convert(self.mixed, 'kept.gltf', True)
        off, off_result = self.convert(self.mixed, 'stripped.gltf', False)
        on_materials, _, on_attributes = self.named(on)
        off_materials, _, off_attributes = self.named(off)
        self.assertEqual(on_materials, 1, on)
        self.assertEqual(off_materials, 0, off)
        for path, attributes, result in ((on, on_attributes, on_result),
                                         (off, off_attributes, off_result)):
            self.assertTrue(any(key.startswith('COLOR_') for key in attributes),
                            f'{os.path.basename(path)} lost the vertex colours that were '
                            f'never being asked about: {sorted(attributes)}')
            self.assertIn('vertex colours', result['content'] or '',
                          f'{os.path.basename(path)} keeps vertex colours but the answer '
                          f'did not say so: {result["content"]!r}')

    def test_27_a_format_with_no_room_says_that_instead_of_counting_zero(self):
        """.stl and .off are a triangle list; the choice cannot change what they hold."""
        for fmt in ('stl', 'off'):
            on, on_result = self.convert(self.two_material, f'kept.{fmt}', True)
            off, off_result = self.convert(self.two_material, f'stripped.{fmt}', False)
            for path, result in ((on, on_result), (off, off_result)):
                self.assertIn('no place for materials', result['content'] or '',
                              f'{os.path.basename(path)}: {result["content"]!r}')
                self.assertEqual((result['method'], result['options_skipped']),
                                 ('trimesh', []),
                                 f'.{fmt} has a writer here, so the answer must not come from '
                                 f'a library that cannot be told about materials')
            with open(on, 'rb') as kept, open(off, 'rb') as stripped:
                self.assertEqual(kept.read(), stripped.read(),
                                 f'the two answers wrote different .{fmt} files, but .{fmt} '
                                 f'has no field for either one')

    def test_28_a_library_that_cannot_be_told_says_which_one_it_was(self):
        """assimp and pymeshlab have no material parameter at all, so saying off is a no."""
        # Read off the two libraries' own bytes: the .fbx assimp writes names no
        # `Material::` and no `Texture::` record, and the .dae pymeshlab writes carries
        # two materials, an image and texture coordinates. The switch was moot for both,
        # but what each file still holds is a different answer, and the sentence has to
        # say the one that is true.
        holds = {'fbx': 'keeps no materials and no textures',
                 'dae': 'keeps 2 materials, textures and texture coordinates'}
        for fmt, library in (('fbx', 'assimp'), ('dae', 'pymeshlab')):
            path, result = self.convert(self.two_material, f'via.{fmt}', True)
            self.assertEqual(result['method'], library, path)
            self.assertEqual(result['options_skipped'], ['preserve_materials'],
                             f'.{fmt} cannot be told about materials, so the switch has to '
                             f'name itself as not applied')
            self.assertIn(holds[fmt], result.get('content') or '', path)
            with self.signals() as captured:
                self.convert(self.two_material, f'again.{fmt}', True)
            emitted = captured.messages[-1][2]
            self.assertIn('preserve_materials not applied', emitted,
                          f'the pane was told only "{emitted}"')

    def test_29_the_answer_is_read_off_the_bytes_not_out_of_the_reader(self):
        """One merged mesh holds one visual, so the reader cannot count the two it left.

        `read_mesh` concatenates the parts - which is what LOD generation wants, and what
        makes a .glb holding two images look like a file holding one. Measured on this
        build: the merged read-back has 24 faces, one material record, and its
        `PBRMaterial` does not even carry an `image` to read. So the sentence counts the
        container's own records.
        """
        path, result = self.convert(self.two_material, 'twice.glb', True)
        self.assertEqual(self.named(path)[1], 2, path)
        self.assertIn('2 textures', result['content'] or '',
                      f'the file holds two images and the answer said: {result["content"]!r}')
        mesh, note = self.converter.read_mesh(path)
        self.assertIsNotNone(mesh, note)
        self.assertEqual(len(mesh.faces), 24,
                         'this is not the merged single mesh the reader hands back')
        self.assertIsNone(getattr(mesh.visual.material, 'image', None),
                          'if the reader could name both images, counting them there would '
                          'be the simpler answer and this test should say so')

    def test_30_a_file_that_cannot_be_read_back_leaves_the_conversion_won(self):
        """An unreadable answer is no reason to report a written file as a failure."""
        import src.processing.format_converter as product

        def refuse(_path):
            raise zipfile.BadZipFile('these bytes are not the container expected')

        previous = product._content_sentence
        product._content_sentence = refuse
        try:
            path = os.path.join(self.out, 'unreadable.glb')
            result = self.converter.convert_file(self.two_material, path,
                                                 {'preserve_materials': True})
        finally:
            product._content_sentence = previous
        self.assertTrue(result['success'],
                        f'the reader lost a file that was already on disk: {result["message"]}')
        self.assertTrue(os.path.isfile(path), path)
        self.assertIsNone(result['content'],
                          'the sentence was missing but something claimed it anyway')

    def test_31_a_ply_names_its_own_coordinate_columns(self):
        """The .ply header is read for column names; the types beside them say nothing."""
        path, result = self.convert(self.two_material, 'flat.ply', True)
        header = open(path, 'rb').read(4096).decode('ascii', 'ignore').split('end_header')[0]
        names = {line.split()[-1] for line in header.splitlines()
                 if line.startswith('property')}
        self.assertTrue({'s', 't'} <= names,
                        f'this .ply holds no uv columns for the sentence to name: {sorted(names)}')
        self.assertIn('keeps texture coordinates', result['content'] or '',
                      f'the file names s and t and the answer said: {result["content"]!r}')

    def test_32_an_obj_answers_with_the_materials_its_own_sidecar_names(self):
        """A written .obj is answered from `usemtl` and the `map_` lines it points at.

        The .glb and .obj branches are different readers, and the .obj one has to follow
        the `mtllib` the file itself names: measured here, the file written with the
        switch off holds no `mtllib` at all, so the sidecar the switch-on file left in the
        same folder cannot be read into its answer.
        """
        kept, kept_result = self.convert(self.two_as_glb, 'apart.obj', True)
        stripped, stripped_result = self.convert(self.two_as_glb, 'together.obj', False)
        self.assertEqual(obj_material_names(kept), ['material_0', 'material_1'], kept)
        self.assertEqual(obj_material_names(stripped), [], stripped)
        self.assertIn('keeps 2 materials, 2 textures and texture coordinates',
                      kept_result['content'] or '', f'{kept_result["content"]!r}')
        self.assertIn('keeps no materials, no textures and no texture coordinates',
                      stripped_result['content'] or '', f'{stripped_result["content"]!r}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
