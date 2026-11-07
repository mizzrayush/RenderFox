"""Nothing the app ships is unreachable, and the one door the dead files guarded is answered once.

Nine names sat in this log's **Dead files** paragraph with line counts next to them,
and the nine counts added up to the header's own 6,075. Two of them had already been deleted by 6p,
so seven files were still on disk - and **two of those seven are live and always were**. Measured by
walking every import statement in the tree and following the edges out of `main.py` - the walk
`tools/check_dead_modules.py` runs, and which this suite re-runs - `src/utils/file_utils.py` is
imported by four modules and `src/ui/feedback_dialog.py` by `main_window.py:27`, so calling them dead
was a grep's guess about a file the app reads. All five of those imports are the relative kind
(`from ..utils.file_utils import ...`, `from .feedback_dialog import ...`), and a search for either
module's dotted name returns nothing in `src/` at all - only the test files spell it out. The other
five are genuinely unreachable, were on the list, and are deleted: the walk
at `92a5961` saw 74 modules under `src/` and reached 69 of them. A claim this blunt needed an
instrument rather than a reading, so the instrument lives in `tools/` and this suite runs it.

What is asked here, in order: that the five unreachable files are absent and no import node names
them, and that no file under `src/` still spells their words; that the walk reports no unreachable
module and that its two counts are the same number - and that it still reports one when a module
nothing imports is planted in the tree, because a checker that prints nothing would pass every
other claim in this file; that its second question, the word search that decides named-versus-dead,
reads the files it lists and skips the file it was asked about; that the walk really reaches the
panes the app shows - an instrument that silently reached nothing would otherwise pass everything
after it; that its resolver answers absolute, one-dot and two-dot imports the way the interpreter
does; that `get_temp_directory` creates the folder it names and is idempotent, because four modules
now lean on one answer instead of each keeping a copy; that `src/utils/file_utils.py` has exactly
one public name and the 22 functions and one class it carried are gone; that the Painting feature
the deleted `weight_painting_tab.py` was a second copy of is still on screen, tab label and all,
from the module the window really constructs; that Help -> Send Feedback reaches the dialog - the
window has had an `open_feedback` no control called since the first commit; that a saved record is
a real JSON file carrying exactly the fields the dialog showed, since its own tooltip promised an
app version this app does not keep anywhere, and is written to the log at INFO; that a report with
nothing in it is refused before a file is made; that two records saved against the same stopped
clock do not overwrite each other; and that a write which failed is said out loud at ERROR with the
dialog left open and the text still in it, instead of the old "Feedback Sent" thanking the user for
a record that does not exist.

Run: python -X utf8 tests/test_dead_modules_contract.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import importlib.util
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QTabWidget, QWidget

from src.ui import feedback_dialog as feedback_module
from src.ui import main_window as main_window_module
from src.ui.feedback_dialog import FeedbackDialog
from src.utils import file_utils

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CHECKER = os.path.join(ROOT, 'tools', 'check_dead_modules.py')

# The two unreachable modules test_15 plants. The first name is never written as one word in
# this file - see the comment there - and the second always is, which is the only difference
# between what the checker calls dead and what it calls named.
DEAD_TAIL = '_probe' + '_dead_module'
NAMED_TAIL = '_probe_named_module'

# The five modules the walk found unreachable and nothing named. `library_grid.py` and
# `thumbnail_generator.py` went in Phase 6p, which is why they are not here.
UNREACHABLE = (
    'src/ui/model_tab_open3d.py',
    'src/ui/model_viewer_open3d.py',
    'src/utils/system_utils.py',
    'src/ui/weight_painting_tab.py',
    'src/features/mesh_processor.py',
)
UNREACHABLE_MODULES = (
    'src.ui.model_tab_open3d',
    'src.ui.model_viewer_open3d',
    'src.utils.system_utils',
    'src.ui.weight_painting_tab',
    'src.features.mesh_processor',
)

# The words a file could use to reach each one again. `mesh_processor` is not on this list because
# the live `src/processing/mesh_processor.py` is named by ten files; only the `features.` prefix
# would resurrect the shim.
WORDS_THAT_MEAN_THEM = (
    'model_tab_open3d', 'model_viewer_open3d', 'system_utils', 'weight_painting_tab',
    'features.mesh_processor', 'features import mesh_processor',
)

# Every name `src/utils/file_utils.py` held besides the one the app calls.
DEAD_HELPERS = (
    'ensure_directory', 'get_file_size', 'get_file_hash', 'is_image_file', 'is_video_file',
    'is_3d_file', 'get_safe_filename', 'get_unique_filename', 'copy_file_with_progress',
    'move_file', 'delete_file_safe', 'cleanup_directory', 'get_directory_size',
    'find_files_by_pattern', 'create_archive', 'extract_archive', 'cleanup_temp_files',
    'format_file_size', 'get_file_metadata', 'validate_file_path', 'backup_file',
    'restore_backup', 'FileWatcher',
)

_spec = importlib.util.spec_from_file_location('dead_module_checker', CHECKER)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def source_files():
    paths = [os.path.join(ROOT, 'main.py')]
    for folder in ('src', 'tests', 'tools'):
        for dirpath, dirnames, names in os.walk(os.path.join(ROOT, folder)):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            paths += [os.path.join(dirpath, name) for name in sorted(names)
                      if name.endswith('.py')]
    return paths


class WalkAndDeletionContract(unittest.TestCase):
    """The five files are gone, the walk says so, and the walk is not blind."""

    def test_01_the_unreachable_files_are_absent_and_no_import_names_them(self):
        for relative in UNREACHABLE:
            self.assertFalse(os.path.exists(os.path.join(ROOT, *relative.split('/'))),
                             f'{relative} is still in the tree')

        for path in source_files():
            for dotted in checker.imports_of(Path(path)):
                self.assertNotIn(dotted, UNREACHABLE_MODULES,
                                 f'{os.path.relpath(path, ROOT)} still imports {dotted}')

    def test_02_no_file_under_src_still_spells_their_names(self):
        # A lazy `importlib.import_module('src.ui.model_tab_open3d')` is invisible to the walk
        # above, so the words themselves are the second question.
        for path in source_files():
            if not path.startswith(os.path.join(ROOT, 'src')):
                continue
            with open(path, encoding='utf-8', errors='replace') as handle:
                text = handle.read()
            for word in WORDS_THAT_MEAN_THEM:
                self.assertNotIn(word, text,
                                 f'{os.path.relpath(path, ROOT)} still mentions {word}')

    def test_03_the_walk_reports_every_module_under_src_as_reachable(self):
        run = subprocess.run([sys.executable, '-X', 'utf8', CHECKER, '--strict'],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                             errors='replace')
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        total = re.search(r'modules under src/: (\d+)', run.stdout)
        reached = re.search(r'reachable from \d+ root\(s\): (\d+) of them', run.stdout)
        self.assertIsNotNone(total, run.stdout)
        self.assertIsNotNone(reached, run.stdout)
        self.assertEqual(total.group(1), reached.group(1),
                         f'the walk reaches {reached.group(1)} of {total.group(1)} modules')
        self.assertIn('every module under src/ is reachable', run.stdout)

    def test_04_the_walk_reaches_the_panes_the_app_shows(self):
        # Without this, an instrument that reached nothing and reported the difference as zero
        # would pass every assertion in the class above.
        src_modules, reachable, walked = checker.collect([Path(ROOT) / 'main.py'])
        for live in ('src.ui.main_window', 'src.ui.model_tab', 'src.ui.painting_tab',
                     'src.ui.unified_viewer', 'src.ui.feedback_dialog', 'src.utils.file_utils',
                     'src.features.version_control', 'src.processing.mesh_processor'):
            self.assertIn(live, src_modules, f'{live} is not among the modules the walk can see')
            self.assertIn(live, reachable, f'{live} is not reached from main.py')
        self.assertEqual(sorted(src_modules), sorted(reachable & set(src_modules)),
                         'the walk left a module unreachable that --strict did not report')
        self.assertGreater(len(walked), 100, 'the walk read almost no file')

    def test_05_the_resolver_answers_the_three_import_forms(self):
        self.assertEqual('src.utils.worker', checker.resolve('worker', 'src.utils', 1))
        self.assertEqual('src.features.version_control',
                         checker.resolve('features.version_control', 'src.ui', 2))
        self.assertEqual('src.ui.styles', checker.resolve('src.ui.styles', 'src.features', 0))

    def test_15_the_walk_reports_a_module_nothing_imports(self):
        # Every claim before this is satisfied by a checker that prints nothing, so two
        # unreachable modules are planted for the length of the test and the report is asked
        # about them. One of the two names is spelled in pieces on purpose: the checker's second
        # question is "does this word appear anywhere in the tree", and if this file wrote the
        # whole word it would be the thing that made the probe look reachable.
        dead = os.path.join(ROOT, 'src', 'utils', DEAD_TAIL + '.py')
        named = os.path.join(ROOT, 'src', 'utils', NAMED_TAIL + '.py')
        for path in (dead, named):
            self.assertFalse(os.path.exists(path), f'an earlier run left {path} behind')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('MARKER = 1\n')
            self.addCleanup(os.remove, path)

        src_modules, reachable, _ = checker.collect([Path(ROOT) / 'main.py'])
        for tail in (DEAD_TAIL, NAMED_TAIL):
            self.assertIn(f'src.utils.{tail}', src_modules, 'the walk cannot see a file on disk')
            self.assertNotIn(f'src.utils.{tail}', reachable,
                             'the walk reached a module no import names')

        run = subprocess.run([sys.executable, '-X', 'utf8', CHECKER, '--strict'],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                             errors='replace')
        self.assertEqual(1, run.returncode, run.stdout + run.stderr)
        out = run.stdout.replace('\\', '/')
        self.assertIn(f'src/utils/{DEAD_TAIL}.py', out, run.stdout)
        self.assertIn('dead:', out, 'the checker hid the one file it was asked to find')
        self.assertIn('unreached but named elsewhere', out,
                      'a module this file spells was not asked its second question')
        self.assertNotIn('every module under src/ is reachable', out,
                         'the all-clear printed over a tree that is not clear')
        total = re.search(r'modules under src/: (\d+)', out)
        reached = re.search(r'reachable from \d+ root\(s\): (\d+) of them', out)
        self.assertEqual(int(total.group(1)) - 2, int(reached.group(1)),
                         f'the report counted {reached.group(1)} of {total.group(1)} with two '
                         'probes planted; it is not counting what it walked')

    def test_18_the_walk_reads_the_source_and_not_the_build_output(self):
        # `dist/` holds a frozen copy of this very tree. Reading it makes every module look
        # "named elsewhere" and hides the fact that nothing in the app imports it.
        tops = {p.relative_to(ROOT).parts[0] for p in checker._walked_files()}
        for folder in ('dist', 'build', 'patch_script'):
            self.assertNotIn(folder, tops, f'the walk read {folder}/, which is a copy of the tree')
        self.assertIn('src', tops, 'the walk read no source file at all')

    def test_17_the_second_question_reads_the_files_it_claims_to(self):
        # `mentions` is the reason an unreachable file is reported as named rather than dead;
        # a stub that returned no hits would silently promote every such file to the dead list.
        hits = checker.mentions('get_temp_directory', Path(ROOT) / 'src' / 'utils' /
                                'file_utils.py')
        for caller in ('src/features/ai_asset_tagger.py', 'src/features/diagnostic_engine.py',
                       'src/features/performance_analyzer.py', 'src/ui/pipeline_editor_tab.py'):
            self.assertIn(caller, hits, f'the word search missed {caller}: {hits}')
        self.assertNotIn('src/utils/file_utils.py', hits,
                         'a file was credited with naming the definition it holds')


class TempFolderContract(unittest.TestCase):
    """The one helper the reduced utility file still contributes creates what it names."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_6r_temp_')
        self.addCleanup(shutil.rmtree, self.work, True)
        patcher = mock.patch.object(file_utils.tempfile, 'gettempdir', return_value=self.work)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_06_the_temp_helper_creates_the_folder_it_names(self):
        folder = file_utils.get_temp_directory()
        self.assertEqual(os.path.join(self.work, 'renderfox'), folder)
        self.assertTrue(os.path.isdir(folder), 'the helper named a folder it did not create')

    def test_07_a_folder_that_already_exists_is_not_an_error(self):
        # Four modules ask, and `exist_ok` is the whole reason two of them asking in the same
        # moment cannot make one of them fail.
        first = file_utils.get_temp_directory()
        second = file_utils.get_temp_directory()
        self.assertEqual(first, second)
        self.assertTrue(os.path.isdir(second))

    def test_08_the_file_has_one_public_name(self):
        public = [name for name in dir(file_utils)
                  if not name.startswith('_')
                  and not isinstance(getattr(file_utils, name), types.ModuleType)]
        self.assertEqual(['get_temp_directory'], public,
                         'a second answer to a question the app already settled is back')
        for gone in DEAD_HELPERS:
            self.assertFalse(hasattr(file_utils, gone), f'{gone} is importable again')


class TheWindowContract(unittest.TestCase):
    """The features the deleted copies claimed are still on screen, from the live module."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from src.ui.main_window import MainWindow
        cls.window = MainWindow()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.app.processEvents()

    def test_09_the_painting_tab_the_user_sees_is_the_one_still_in_the_tree(self):
        names = [type(widget).__name__ for widget in self.window.findChildren(QWidget)]
        self.assertIn('PaintingTab', names,
                      'the pane the Models tab builds is no longer the live painting one')
        for gone in ('WeightPaintingTab', 'ModelTab_Open3D', 'ModelViewerWidget_Open3D'):
            self.assertNotIn(gone, names, f'{gone} is constructed again')
        labels = []
        for tabs in self.window.findChildren(QTabWidget):
            labels += [tabs.tabText(index) for index in range(tabs.count())]
        self.assertIn('Painting', labels,
                      'the Painting tab the deleted file was a copy of is not shown any more')

    def test_10_the_help_menu_reaches_the_feedback_dialog(self):
        menus = {action.menu().title(): action.menu()
                 for action in self.window.menuBar().actions() if action.menu()}
        self.assertIn('Help', menus, sorted(menus))
        entries = [action.text() for action in menus['Help'].actions()]
        self.assertIn('Send Feedback', entries,
                      f'Help has no feedback entry; it holds {entries}')

        # The real dialog's writing is the class below; here the facts are that the menu entry
        # builds a dialog owned by the window and then shows it - `open_feedback` had no control
        # reaching it, and either half on its own is a menu item that does nothing.
        opened = []
        shown = []

        class RecordingDialog(FeedbackDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                opened.append(self)

            def exec(self):
                shown.append(self)
                return 0

        with mock.patch.object(main_window_module, 'FeedbackDialog', RecordingDialog):
            [action for action in menus['Help'].actions()
             if action.text() == 'Send Feedback'][0].trigger()

        self.assertEqual(1, len(opened), 'the menu entry opened no dialog')
        self.assertEqual(opened, shown, 'the dialog was built and never shown')
        self.assertIs(self.window, opened[0].parent(),
                      'the dialog was opened without the window as its parent')


class FeedbackRecordContract(unittest.TestCase):
    """The dialog writes a file, says which one, and says so when it could not."""

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.work = tempfile.mkdtemp(prefix='renderfox_6r_home_')
        self.addCleanup(shutil.rmtree, self.work, True)
        patcher = mock.patch.object(feedback_module.os.path, 'expanduser',
                                    return_value=self.work)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.popups = []
        for kind in ('information', 'critical', 'warning'):
            original = getattr(QMessageBox, kind)
            self.addCleanup(setattr, QMessageBox, kind, original)
            setattr(QMessageBox, kind,
                    lambda *a, _k=kind, **k: self.popups.append((_k, a)))

        self.dialog = FeedbackDialog()
        self.dialog.type_combo.setCurrentText('Bug Report')
        self.dialog.email_edit.setText('reporter@example.com')
        self.dialog.description_edit.setPlainText('The viewer blinked on a 4k texture.')

    def folder(self):
        return os.path.join(self.work, '.renderfox', 'feedback')

    def records(self):
        return sorted(os.listdir(self.folder())) if os.path.isdir(self.folder()) else []

    def test_11_a_saved_record_is_the_file_and_says_where_it_is(self):
        self.dialog.sys_info_cb.setChecked(False)
        with self.assertLogs(feedback_module.logger, level='INFO'):
            self.dialog.submit_feedback()
        names = self.records()
        self.assertEqual(1, len(names), f'the save wrote {names}')
        with open(os.path.join(self.folder(), names[0]), encoding='utf-8') as handle:
            record = json.load(handle)
        self.assertEqual({'timestamp', 'type', 'email', 'description'}, set(record),
                         'the record carries a field the dialog never showed')
        self.assertEqual('Bug Report', record['type'])
        self.assertEqual('The viewer blinked on a 4k texture.', record['description'])
        self.assertNotIn('system_info', record,
                         'the checkbox was off and the record carries machine details anyway')

        kind, args = self.popups[-1]
        self.assertEqual('information', kind, self.popups)
        self.assertIn(names[0], args[2], 'the sentence on screen does not name the file it wrote')
        self.assertEqual(int(QDialog.DialogCode.Accepted), self.dialog.result(),
                         'a save the user was thanked for has to be a dialog that closed')

    def test_12_the_system_block_carries_the_fields_the_tooltip_names(self):
        # `submit_feedback` is the only place that reads the checkbox, so it is the only way to
        # ask what the tick actually puts in the record.
        self.dialog.sys_info_cb.setChecked(True)
        self.dialog.submit_feedback()
        names = self.records()
        self.assertEqual(1, len(names), f'the save wrote {names}')
        with open(os.path.join(self.folder(), names[0]), encoding='utf-8') as handle:
            record = json.load(handle)
        self.assertEqual({'os', 'os_release', 'os_version', 'python_version', 'platform',
                          'processor'}, set(record['system_info']),
                         'the tooltip and the record disagree about what is included')

    def test_13_two_records_in_the_same_second_are_two_files(self):
        class FrozenClock:
            now = staticmethod(lambda: datetime(2026, 11, 7, 12, 0, 0))

        # The clock is stopped so that both saves really do want the same name; asking the
        # second one to differ without this would pass on any run that happened to cross a
        # second between the two writes.
        with mock.patch.object(feedback_module, 'datetime', FrozenClock):
            first, _ = self.dialog.save_feedback({'description': 'one'})
            second, _ = self.dialog.save_feedback({'description': 'two'})
        self.assertNotEqual(first, second, "the second save had the first save's name")
        self.assertEqual(2, len(self.records()), 'one of the two records is not on disk')
        with open(first, encoding='utf-8') as handle:
            self.assertEqual('one', json.load(handle)['description'],
                             'the second save overwrote the record it collided with')

    def test_16_an_empty_report_is_refused_before_it_is_written(self):
        self.dialog.description_edit.setPlainText('   ')
        self.dialog.submit_feedback()
        self.assertEqual([], self.records(), 'a record with nothing in it was written anyway')
        kinds = [kind for kind, _args in self.popups]
        self.assertEqual(['warning'], kinds, f'the refusal was announced as {self.popups}')
        self.assertNotEqual(int(QDialog.DialogCode.Accepted), self.dialog.result(),
                            'an empty report closed the dialog as if it had been saved')

    def test_14_a_write_that_failed_is_said_and_the_text_survives(self):
        blocked = os.path.join(self.work, 'not-a-folder')
        with open(blocked, 'w', encoding='utf-8') as handle:
            handle.write('')
        nowhere = os.path.join(blocked, 'nested')

        with mock.patch.object(feedback_module.os.path, 'expanduser', return_value=nowhere):
            with self.assertLogs(feedback_module.logger, level='ERROR'):
                saved, reason = self.dialog.save_feedback({'description': 'x'})
        self.assertIsNone(saved, 'a write into a path that is a file answered with a path')
        self.assertTrue(reason and 'could not be saved' in reason, reason)

        self.popups.clear()
        with mock.patch.object(feedback_module.os.path, 'expanduser', return_value=nowhere):
            with self.assertLogs(feedback_module.logger, level='ERROR'):
                self.dialog.submit_feedback()
        kinds = [kind for kind, _args in self.popups]
        self.assertIn('critical', kinds, f'the refusal was announced as {self.popups}')
        self.assertNotIn('information', kinds,
                         'the dialog thanked the user for a record that was never written')
        self.assertNotEqual(int(QDialog.DialogCode.Accepted), self.dialog.result(),
                            'a refused save closed the dialog with the text still unsaved')
        self.assertEqual('The viewer blinked on a 4k texture.',
                         self.dialog.description_edit.toPlainText(),
                         'a refused save took the text with it')


if __name__ == '__main__':
    unittest.main(verbosity=2)
