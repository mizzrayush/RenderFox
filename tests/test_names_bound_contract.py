"""Can the app start at all? A name no line binds says so before a window does.

Phase 38 lifted six files' hand-typed folder answers into `src/utils/app_paths.py` calls. In
`main.py` it replaced the line that bound `base_dir` and left the line two below it reading that
name, so `main.py:132` raises `NameError` on the way up - the splash screen never shows and no
window is ever created. Nothing in the tree could see it: the paths suite reads `main.py` as a
caller (test_20 reads its imports and its calls, and both were correct), the 38-suite chain never
calls `main()`, and `tests/test_clean_exit_contract.py:559` imports the module and stops there.
Measured with that one line put back and the tool off, the app does not start.

So the question is asked with a real scope analyser rather than a rule of mine: pylint's two
messages for a name that resolves to nothing at the moment it is reached, over the same app scope
`tools/check_paths_hygiene.py` walks. The three verdicts below are that gate: the shipped tree
answers zero (and says how many files it was asked about, because a walk that quietly shrinks
answers zero for the wrong reason), both messages are reported on a fixture that carries them,
and a run that cannot start pylint is a finding rather than a clean answer.

    python -X utf8 tests/test_names_bound_contract.py

Cost, measured: about a minute, almost all of it pylint over 74 files. It is one process and no
`QApplication`, so it takes none of the timing risk the pane suites take.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

CHECKER = Path(ROOT) / 'tools' / 'check_names_bound.py'

# Measured off the checker's own walk, which is `check_paths_hygiene.app_files`: the files under
# `src/` plus `main.py`. Re-counted by `tools/check_names_bound.py`'s first line on this tree.
APP_SCOPE_FILES = 74

# The two defects, in the shape the phase made them: an assignment taken out of a function that
# still reads the name, and a name read above the line that binds it.
LEFT_BEHIND = '''"""A pane's start, after somebody lifted the line that bound base_dir out of it."""

import os


def show_window():
    icon = os.path.join(base_dir, "icon.ico")
    return icon
'''

BOUND_LATER = '''"""The same name, read two lines above the line that binds it."""


def start():
    print(read_me_first)
    read_me_first = 3
    return read_me_first
'''


def load_checker():
    spec = importlib.util.spec_from_file_location('check_names_bound', CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNamesBoundContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checker = load_checker()
        # Asked once for the whole class: pylint over app scope is the minute this suite costs.
        cls.shipped = cls.checker.scan(ROOT)

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='renderfox_names_')
        self.root = Path(self.work.name)
        (self.root / 'src').mkdir()
        self.addCleanup(self.work.cleanup)

    def test_01_the_shipped_tree_has_no_name_that_is_not_bound(self):
        """Every file the app ships answers a name for every name it reads - and the walk is counted."""
        count, found = self.shipped
        self.assertEqual(APP_SCOPE_FILES, count,
                         'the app scope this gate walks changed size without the number above it '
                         'being re-measured, which is how a shrink starts reporting clean')
        self.assertEqual([], found, 'a name no line binds is back:\n' + '\n'.join(found))

    def test_02_both_shapes_are_reported(self):
        """The defect this phase made, and its twin, each named by the file and the name."""
        for name, text in (('left_behind.py', LEFT_BEHIND), ('bound_later.py', BOUND_LATER)):
            (self.root / 'src' / name).write_text(text, encoding='utf-8')
        count, found = self.checker.scan(self.root)
        self.assertEqual(2, count, f'both fixture files were not asked: {found}')
        self.assertEqual(2, len(found), f'one of the two shapes is not reported:\n' + '\n'.join(found))
        self.assertTrue(any('base_dir' in one for one in found),
                        f'the name left behind is not named in {found}')
        self.assertTrue(any('read_me_first' in one for one in found),
                        f'the name read above its assignment is not named in {found}')

    def test_03_strict_is_the_exit_code_the_chain_reads(self):
        """Report mode stays readable; `--strict` is what makes it a gate."""
        (self.root / 'src' / 'left_behind.py').write_text(LEFT_BEHIND, encoding='utf-8')
        stdout = subprocess.run([sys.executable, '-X', 'utf8', str(CHECKER), '--root',
                                 str(self.root), '--strict'],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(1, stdout.returncode, stdout.stdout + stdout.stderr)
        self.assertIn('1 names no line binds', stdout.stdout)

    def test_04_a_gate_that_cannot_ask_says_so_instead_of_reporting_clean(self):
        """pylint missing is a finding, not a zero - which is the failure mode this repo has named twice."""
        real = sys.executable
        self.checker.sys.executable = os.path.join(self.work.name, 'no-such-interpreter')
        try:
            count, found = self.checker.scan(self.root)
        finally:
            self.checker.sys.executable = real
        self.assertEqual(0, count, 'a tree with no files in it should not be walked at all')
        self.assertEqual(1, len(found), f'the run that could not start pylint answered {found}')
        self.assertIn('pylint was not run', found[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
