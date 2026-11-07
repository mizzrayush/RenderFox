"""Three questions asked of the syntax tree, each answered on a sample that shows the shape and
on the real files that must not contain it.

This suite exists because two defect classes reached the app that no runtime check could see. A
block of UI written as its own string statement is valid Python that builds nothing - the Model
pane's Presets group shipped that way, its buttons described in a paragraph - and a `def` whose
name the same scope already bound is a function that never exists, which is how the viewer came to
carry two `set_render_mode` methods, two `set_use_vertex_colors`, and a `check_integrity` that
scanned the database under an alias that answered it. Both compile, both import, and neither does
anything, so the only honest reader is the syntax tree.

`tools/check_unreachable_code.py` already answered one question (a body that continues past the
statement that ends it) and now answers these two as well, so the three are tested side by side:
each on a sample that has the shape, each on a sample that looks like it but is not the defect
(a docstring in its slot, a property and its setter, an exit that is the last line), and each on
the whole tree, where the answer has to be nothing - with the file count printed beside it,
because a walk that silently reads no files answers 'clean' as loudly as one that reads the app.
The command's own handoff is pinned as well: the first defect this suite found was in the checker,
whose `main` read the single target it was given as the program name and answered for the app.

Nothing here runs the app: the checker parses text, so these tests import only `ast` and the
checker itself, loaded from its path the way `tests/test_dead_modules_contract.py` loads its own.
The product files are read, never imported, so a planted defect in one of them is reported rather
than executed.

Run: python -X utf8 tests/test_unreachable_code_checker.py
"""

import ast
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
CHECKER = ROOT / 'tools' / 'check_unreachable_code.py'

_spec = importlib.util.spec_from_file_location('unreachable_code_checker', CHECKER)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def tree(source: str) -> ast.AST:
    return ast.parse(source, filename='<sample>')


class DeadTails(unittest.TestCase):
    """Question one: does a body continue past the statement that ends it?"""

    def test_01_a_statement_after_a_return_is_reported_with_the_function_that_lost_it(self):
        found = checker.dead_tails(tree(
            'class Pane:\n'
            '    def build(self):\n'
            '        return 1\n'
            '        self.add_widgets()\n'
        ))
        self.assertEqual(1, len(found), str(found))
        line, _col, name, kind = found[0]
        self.assertEqual(4, line)
        self.assertEqual('build', name)
        self.assertEqual('Expr', kind)

    def test_02_an_exit_that_ends_the_body_and_a_return_inside_a_branch_are_clean(self):
        clean = (
            'def pick(row):\n'
            '    if row == 0:\n'
            '        return "a"\n'
            '    return "b"\n'
        )
        self.assertEqual([], checker.dead_tails(tree(clean)))
        # The same shape one statement later: the exit is the last thing the body does.
        self.assertEqual([], checker.dead_tails(tree(
            'def only():\n'
            '    raise ValueError("no")\n'
        )))


class ParkedStrings(unittest.TestCase):
    """Question two: is a string statement something Python was meant to build?"""

    def test_03_a_string_below_the_first_line_of_a_body_is_parked(self):
        found = checker.parked_strings(tree(
            'class Pane:\n'
            '    """The pane."""\n'
            '    def build(self):\n'
            '        self.group = QGroupBox("Presets")\n'
            '        "Wireframe, Solid and Debug View sit in this row"\n'
            '        layout.addWidget(self.group)\n'
        ))
        self.assertEqual(1, len(found), str(found))
        self.assertEqual(5, found[0][0])
        self.assertIn('Wireframe, Solid', found[0][2])

    def test_04_a_string_in_the_docstring_slot_is_a_docstring(self):
        for source in (
            '"""The module says what it does."""\n'
            'x = 1\n',
            'class Pane:\n'
            '    """The class says what it does."""\n',
            'def build():\n'
            '    """The function says what it does."""\n'
            '    return 1\n',
        ):
            self.assertEqual([], checker.parked_strings(tree(source)), source)

    def test_05_a_string_that_is_an_argument_or_a_value_is_not_a_statement(self):
        found = checker.parked_strings(tree(
            'def build():\n'
            '    label = "a value"\n'
            '    log("an argument")\n'
            '    return "a value handed back"\n'
        ))
        self.assertEqual([], found)

    def test_06_a_parked_f_string_is_parked_in_the_docstring_slot_too(self):
        """An f-string statement is not a docstring: `__doc__` stays None and nothing is built."""
        found = checker.parked_strings(tree(
            'def build():\n'
            '    f"""Buttons for the {name} row."""\n'
            '    return 1\n'
        ))
        self.assertEqual(1, len(found), str(found))
        self.assertIn('Buttons for the', found[0][2])


class ShadowedBindings(unittest.TestCase):
    """Question three: did the same scope already bind this name?"""

    def test_07_a_second_plain_def_or_class_names_the_binding_it_destroyed(self):
        found = checker.shadowed_bindings(tree(
            'class Viewer:\n'
            '    def set_mode(self, mode):\n'
            '        self.mode = mode\n'
            '    def redraw(self):\n'
            '        pass\n'
            '    def set_mode(self, mode):\n'
            '        self.mode = mode\n'
        ))
        self.assertEqual(1, len(found), str(found))
        line, earlier, kind, name = found[0]
        self.assertEqual((6, 2, 'FunctionDef', 'set_mode'), (line, earlier, kind, name))
        found = checker.shadowed_bindings(tree(
            'class Pane:\n'
            '    pass\n'
            'class Pane:\n'
            '    def build(self):\n'
            '        pass\n'
        ))
        self.assertEqual(1, len(found), str(found))
        self.assertEqual('ClassDef', found[0][2])

    def test_08_a_property_and_its_setter_share_a_name_on_purpose(self):
        found = checker.shadowed_bindings(tree(
            'class Engine:\n'
            '    @property\n'
            '    def fps(self):\n'
            '        return 60\n'
            '    @fps.setter\n'
            '    def fps(self, value):\n'
            '        self._fps = value\n'
        ))
        self.assertEqual([], found)

    def test_09_the_same_name_in_two_scopes_is_two_things_not_one_shadow(self):
        found = checker.shadowed_bindings(tree(
            'def load():\n'
            '    return 1\n'
            'class A:\n'
            '    def load(self):\n'
            '        pass\n'
            'class B:\n'
            '    def load(self):\n'
            '        pass\n'
        ))
        self.assertEqual([], found)


class TheRealTree(unittest.TestCase):
    """The three questions asked of the app, with the size of the reading printed beside them."""

    def walk(self):
        """The same reading counted with os.walk, so a short walk shows up as a difference.

        Neither walk skips `__pycache__`: this tree holds no `.py` under it - counted with
        `find src tools tests -path '*__pycache__*' -name '*.py'`, which answered zero - and a
        filter one side only is a difference that has nothing to do with the checker.
        """
        paths = []
        for folder in checker.DEFAULT_ROOTS:
            found = []
            for dirpath, _dirnames, names in os.walk(ROOT / folder):
                found += [Path(dirpath, name) for name in names if name.endswith('.py')]
            paths += sorted(found)
        return paths

    def test_10_the_roots_are_named_here_and_the_walk_that_reads_them_is_the_checker_s_own(self):
        self.assertEqual(('src', 'tools', 'tests'), tuple(checker.DEFAULT_ROOTS))
        walked = checker.files_in([ROOT / name for name in checker.DEFAULT_ROOTS])
        self.assertEqual(self.walk(), walked)
        self.assertGreater(len(walked), 100)
        for name in ('src/ui/model_tab.py', 'src/ui/model_viewer.py', 'src/ui/scripting_tab.py',
                     'src/ui/library_tab.py', 'src/processing/script_engine.py',
                     'src/core/library_manager.py', 'src/features/version_control.py',
                     'src/ui/pipeline_editor_tab.py'):
            self.assertIn(ROOT / name, walked, f'{name} is outside what the checker reads')

    def test_11_the_app_answers_none_of_the_three_questions(self):
        offenders = checker.scan(checker.files_in(
            [ROOT / name for name in checker.DEFAULT_ROOTS]))
        self.assertEqual([], offenders, '\n'.join(f'{p}:{l}: {m}' for p, l, m in offenders))

    def test_12_a_file_the_tree_cannot_read_is_named_rather_than_skipped(self):
        out = Path(tempfile.mkdtemp(prefix='renderfox_checker_'))
        try:
            (out / 'broken.py').write_text('def build(:\n', encoding='utf-8')
            offenders = checker.scan(checker.files_in([out]))
        finally:
            shutil.rmtree(out, ignore_errors=True)
        self.assertEqual(1, len(offenders), str(offenders))
        self.assertIn('unreadable', offenders[0][2])

    def test_13_the_command_reports_each_shape_in_words_and_exits_non_zero_for_all_three(self):
        out = Path(tempfile.mkdtemp(prefix='renderfox_checkercli_'))
        try:
            (out / 'shapes.py').write_text(
                'class Pane:\n'
                '    def build(self):\n'
                '        return 1\n'
                '        self.add_widgets()\n'
                '    def other(self):\n'
                '        """A real docstring."""\n'
                '        "a parked block"\n'
                '    def build(self):\n'
                '        pass\n',
                encoding='utf-8')
            printed = io.StringIO()
            with redirect_stdout(printed):
                code = checker.main([str(out)])
            lines = [one for one in printed.getvalue().splitlines() if one]
        finally:
            shutil.rmtree(out, ignore_errors=True)
        self.assertEqual(1, code, printed.getvalue())
        self.assertEqual(4, len(lines), printed.getvalue())
        self.assertIn('continues after its exit', lines[0])
        self.assertIn('parked string, not a docstring: "a parked block"', lines[1])
        self.assertIn('rebinds :2', lines[2])
        self.assertIn('build nothing', lines[3])
        clean = io.StringIO()
        with redirect_stdout(clean):
            self.assertEqual(0, checker.main([str(CHECKER)]))
        self.assertIn('No body continues past its exit, no string is parked below the '
                      'docstring slot, and no name is bound twice in one scope.',
                      ' '.join(clean.getvalue().split()))

    def test_14_the_command_line_hands_main_the_targets_not_the_program_name(self):
        """The defect the suite found in the checker itself: one target was read as `argv[0]`.

        `main(sys.argv)` with an internal `argv[1:]` means a caller that passes a single directory
        asks for the default roots instead, so the command reports the whole app when it was told
        to look at one folder. The handoff is the last two lines of the file and lives nowhere else.
        """
        lines = CHECKER.read_text(encoding='utf-8').splitlines()
        self.assertEqual(["if __name__ == '__main__':", '    sys.exit(main(sys.argv[1:]))'],
                         lines[-2:], '\n'.join(lines[-4:]))
        printed = io.StringIO()
        with redirect_stdout(printed):
            self.assertEqual(0, checker.main([str(ROOT / 'src' / 'core' / 'library_manager.py')]))
        self.assertIn('No body continues past its exit', ' '.join(printed.getvalue().split()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
