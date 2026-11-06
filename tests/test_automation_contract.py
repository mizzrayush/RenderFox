"""
Automation tab file-watcher contract test.

The Automation tab's watcher pane is four buttons, a table, a filter row, an Auto Actions
group and a log. Before this pass the log
could only be filled by `simulate_file_event`, which a QTimer called every five seconds
with an invented filename; the table was pre-filled with three folders that were never
watched; `stop watching`, `remove watch` and the Auto Actions pane were connected to
nothing; and `FileWatcher._watch_loop` called only python callbacks, so the
`file_created` / `file_modified` / `file_deleted` signals the tab connects to had no
emitter anywhere in the class. Every timestamp line in this tab also raised
AttributeError, because the module says `import datetime` and the slots call
`datetime.now()`.

Run: python -X utf8 tests/test_automation_contract.py
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from src.core.library_manager import LibraryManager
from src.features import automation_engine as engine_module
from src.features.automation_engine import (
    FileWatcher, _event_set, _glob_list, _is_excluded, _name_matches)
from src.ui import automation_tab as tab_module
from src.ui.automation_tab import AutomationTab

CUBE = ("# a real cube so the library can read it\n"
        "v -0.5 -0.5 -0.5\nv 0.5 -0.5 -0.5\nv 0.5 0.5 -0.5\nv -0.5 0.5 -0.5\n"
        "v -0.5 -0.5 0.5\nv 0.5 -0.5 0.5\nv 0.5 0.5 0.5\nv -0.5 0.5 0.5\n"
        "f 1 2 3\nf 1 3 4\nf 5 6 7\nf 5 7 8\nf 1 5 8\nf 1 8 4\n"
        "f 2 6 7\nf 2 7 3\nf 3 7 8\nf 3 8 4\nf 1 2 6\nf 1 6 5\n"
        "f 4 5 6\nf 4 6 3\nf 1 4 8\nf 1 8 5\nf 2 3 7\nf 2 7 6\n")
PAD = "\n" + ("# padding so this file clears the watcher's 1 KB floor\n" * 40)


class WatcherEngineCase(unittest.TestCase):
    """The polling loop itself, one folder, driven a pass at a time."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_watch_')

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def manual(self, directory=None, **kwargs):
        """A watcher whose thread stays off, so the test drives each pass itself."""
        watcher = FileWatcher(poll_seconds=0.05)
        watcher.is_watching = True          # watch_directory() then skips start_watching()
        path = watcher.watch_directory(directory or self.work, **kwargs)
        watcher.is_watching = False
        self.seen = []
        watcher.file_created.connect(lambda p: self.seen.append(('created', os.path.basename(p))))
        watcher.file_modified.connect(lambda p: self.seen.append(('modified', os.path.basename(p))))
        watcher.file_deleted.connect(lambda p: self.seen.append(('deleted', os.path.basename(p))))
        watcher.file_moved.connect(lambda a, b: self.seen.append(
            ('moved', os.path.basename(a), os.path.basename(b))))
        return watcher, path

    def drive(self, watcher, path, current=None):
        """One polling pass. `current` overrides what the folder is said to hold, which is
        the only way to reproduce a listing taken mid-rename."""
        info = watcher.watched_directories[path]
        if current is None:
            current = watcher._snapshot(path, info)
        for event, target, other in watcher._diff(info, current):
            watcher._report(target, event, other)

    def touch(self, name, text=None):
        target = os.path.join(self.work, name)
        with open(target, 'w', encoding='utf-8') as handle:
            handle.write(text if text is not None else CUBE + PAD)
        return target

    def test_01_typed_filters_become_globs(self):
        """Whatever a user types in File Extensions means the same thing."""
        self.assertEqual(_glob_list('*.obj, *.fbx'), ['*.obj', '*.fbx'])
        self.assertEqual(_glob_list('obj,fbx'), ['*.obj', '*.fbx'])
        self.assertEqual(_glob_list('.obj .fbx'), ['*.obj', '*.fbx'])
        self.assertEqual(_glob_list('*'), [], 'no filter must not become a pattern')
        self.assertEqual(_glob_list(''), [])
        self.assertTrue(_name_matches('hero.obj', ['*.obj']))
        self.assertFalse(_name_matches('hero.txt', ['*.obj']))
        self.assertTrue(_name_matches('anything', []), 'an empty filter matches everything')

    def test_02_exclude_field_asks_the_opposite_question(self):
        self.assertFalse(_is_excluded('hero.obj', []), 'no excludes must exclude nothing')
        self.assertTrue(_is_excluded('hero_temp.obj', _glob_list('*_temp*')))
        self.assertFalse(_is_excluded('hero.obj', _glob_list('*_temp*')))

    def test_03_watching_a_folder_that_is_not_there_fails_loudly(self):
        watcher = FileWatcher()
        missing = os.path.join(self.work, 'gone')
        with self.assertRaises(ValueError):
            watcher.watch_directory(missing)
        with self.assertRaises(ValueError):
            watcher.watch_directory('')
        with self.assertRaises(ValueError):
            watcher.watch_directory(self.touch('cube.obj'))
        watcher.stop_watching()

    def test_04_what_was_already_on_disk_is_not_announced(self):
        """500 existing models must not arrive as 500 'created' events."""
        self.touch('a.obj')
        self.touch('b.obj')
        watcher, path = self.manual()
        self.drive(watcher, path)
        self.assertEqual(self.seen, [], 'the folders already on disk are the baseline')

    def test_05_new_file_is_created_for_both_apis(self):
        watcher, path = self.manual()
        self.drive(watcher, path)
        calls = []
        info = watcher.watched_directories[path]
        info['callbacks'].append(lambda p, e: calls.append((e, os.path.basename(p))))
        self.touch('new.obj')
        self.drive(watcher, path)
        self.assertEqual(self.seen, [('created', 'new.obj')])
        self.assertEqual(calls, [('created', 'new.obj')])

    def test_06_writing_an_existing_file_is_modified(self):
        self.touch('keep.obj')
        watcher, path = self.manual(event_type='modified')
        self.drive(watcher, path)
        stamp = os.stat(os.path.join(self.work, 'keep.obj'))
        os.utime(os.path.join(self.work, 'keep.obj'),
                 (stamp.st_atime, stamp.st_mtime + 10))
        self.drive(watcher, path)
        self.assertEqual(self.seen, [('modified', 'keep.obj')])

    def test_07_a_rename_is_one_move_not_a_delete_and_a_create(self):
        self.touch('before.obj')
        watcher, path = self.manual(event_type='any')
        self.drive(watcher, path)
        os.rename(os.path.join(self.work, 'before.obj'), os.path.join(self.work, 'after.obj'))
        self.drive(watcher, path)
        self.assertEqual(self.seen, [('moved', 'before.obj', 'after.obj')])

    def test_08_removal_is_deleted(self):
        """A loss is confirmed on the pass after it is seen, never on the first hint."""
        self.touch('doomed.obj')
        watcher, path = self.manual(event_type='any')
        self.drive(watcher, path)
        os.remove(os.path.join(self.work, 'doomed.obj'))
        self.drive(watcher, path)
        self.assertEqual(self.seen, [], 'the first pass only holds the vanishing')
        self.drive(watcher, path)
        self.assertEqual(self.seen, [('deleted', 'doomed.obj')])

    def test_09_a_folder_only_reports_the_events_it_asked_for(self):
        watcher, path = self.manual(event_type='created')
        self.drive(watcher, path)
        self.touch('one.obj')
        self.drive(watcher, path)
        self.assertEqual(self.seen, [('created', 'one.obj')])
        os.remove(os.path.join(self.work, 'one.obj'))
        self.drive(watcher, path)
        self.drive(watcher, path)
        self.assertEqual(self.seen, [('created', 'one.obj')], 'deleted was never asked for')
        self.assertEqual(_event_set('created'), {'created'})
        self.assertEqual(_event_set('any'), set(('created', 'modified', 'deleted', 'moved')))
        self.assertEqual(_event_set(['created', 'moved']), {'created', 'moved'})

    def test_10_filters_and_size_keep_files_out_of_the_record(self):
        self.touch('model.obj')
        self.touch('draft_temp.obj')
        small = os.path.join(self.work, 'tiny.obj')
        with open(small, 'w', encoding='utf-8') as handle:
            handle.write('v 0 0 0\n')
        watcher, path = self.manual(file_pattern='*.obj',
                                    exclude_patterns='*_temp*',
                                    min_size_kb=1,
                                    event_type='any')
        info = watcher.watched_directories[path]
        found = watcher._snapshot(path, info)
        self.assertEqual([os.path.basename(p) for p in found], ['model.obj'])

    def test_11_a_broken_callback_cannot_swallow_the_signal(self):
        watcher, path = self.manual()
        self.drive(watcher, path)

        def explode(file_path, event):
            raise RuntimeError('this callback is broken')

        watcher.watched_directories[path]['callbacks'].append(explode)
        second = []
        watcher.file_created.connect(lambda p: second.append(os.path.basename(p)))
        self.touch('after.obj')
        self.drive(watcher, path)
        self.assertIn('after.obj', second)

    def test_12_the_same_folder_written_two_ways_is_one_watch(self):
        watcher = FileWatcher()
        watcher.is_watching = True
        first = watcher.watch_directory(self.work.replace('\\', '/'))
        second = watcher.watch_directory(self.work + os.sep + '.')
        self.assertEqual(first, second)
        self.assertEqual(len(watcher.watched_directories), 1)
        self.assertTrue(watcher.is_watched(self.work))
        watcher.unwatch_directory(self.work)
        self.assertEqual(watcher.watched_directories, {})
        self.assertFalse(watcher.is_watched(self.work))

    def test_13_the_baseline_is_written_at_registration(self):
        """A file that lands before the thread's first pass is still an event."""
        watcher, path = self.manual(event_type='any')
        self.touch('immediate.obj')
        self.drive(watcher, path)
        self.assertEqual(self.seen, [('created', 'immediate.obj')])

    def test_14_the_thread_actually_stops(self):
        watcher = FileWatcher(poll_seconds=0.05)
        watcher.watch_directory(self.work)
        self.assertTrue(watcher.is_watching)
        self.assertIsNotNone(watcher._watcher_thread)
        watcher.stop_watching()
        self.assertFalse(watcher.is_watching)
        self.assertIsNone(watcher._watcher_thread)

    def test_15_a_rename_split_across_two_passes_is_still_one_move(self):
        """os.listdir can catch a rename with the old name gone and the new one missing.

        Before the hold that was one rename logged twice: 'File deleted: from.obj', then
        a poll later 'File created: to.obj'. A user reading the log would look for a file
        that was never lost.
        """
        gone = self.touch('from.obj')
        watcher, path = self.manual(event_type='any')
        self.drive(watcher, path)
        stamp = dict(watcher.watched_directories[path]['last_modified'])[gone]
        arrived = os.path.join(self.work, 'to.obj')

        self.drive(watcher, path, {})
        self.assertEqual(self.seen, [], 'one half of a rename is not a deletion')
        self.drive(watcher, path, {arrived: stamp})
        self.assertEqual(self.seen, [('moved', 'from.obj', 'to.obj')])

    def test_16_re_registering_a_folder_forgets_its_open_holds(self):
        """A folder re-added with new filters starts from what is on disk now."""
        held = os.path.join(self.work, 'gone.obj')
        self.touch('gone.obj')
        watcher, path = self.manual(event_type='any')
        self.drive(watcher, path)
        os.remove(held)
        self.drive(watcher, path)
        self.assertEqual(list(watcher.watched_directories[path]['pending_gone']), [held])

        watcher.is_watching = True
        try:
            watcher.watch_directory(path, event_type='any')
        finally:
            watcher.is_watching = False
        self.assertEqual(watcher.watched_directories[path]['pending_gone'], {},
                         'a re-baselined folder must not carry stale losses')
        self.drive(watcher, path)
        self.assertEqual(self.seen, [], 'the re-baseline owns the truth now')


class AutomationTabCase(unittest.TestCase):
    """The pane the user clicks, with the folder dialog pointed at a temp directory."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.previous_dialog = QFileDialog.getExistingDirectory
        # Constructing the tab starts the engine, and the engine reads and writes its task
        # file; that file must be in a temp dir, not in the user's real ~/.renderfox.
        cls.home = tempfile.mkdtemp(prefix='renderfox_home_')
        cls.previous_data_dir = engine_module.app_data_dir
        engine_module.app_data_dir = lambda: cls.home
        # Some of these slots end in a modal box; a modal box cannot be clicked headlessly.
        cls.previous_boxes = (QMessageBox.information, QMessageBox.critical,
                              QMessageBox.warning)
        cls.popups = []
        QMessageBox.information = lambda *a, **k: cls.popups.append(('information', a))
        QMessageBox.critical = lambda *a, **k: cls.popups.append(('critical', a))
        QMessageBox.warning = lambda *a, **k: cls.popups.append(('warning', a))

    @classmethod
    def tearDownClass(cls):
        QFileDialog.getExistingDirectory = cls.previous_dialog
        engine_module.app_data_dir = cls.previous_data_dir
        QMessageBox.information, QMessageBox.critical, QMessageBox.warning = cls.previous_boxes
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_atab_')
        self.watched = os.path.join(self.work, 'incoming')
        os.makedirs(self.watched)
        self.library_db = os.path.join(self.work, 'library.db')
        self.thumbs = os.path.join(self.work, 'thumbs')
        self.tab = AutomationTab()
        # A library in this temp folder: the tests must never touch the user's real one.
        self.tab._library = LibraryManager(db_path=self.library_db, thumbnails_dir=self.thumbs)
        self.tab.file_watcher.poll_seconds = 0.05
        self.tab.watch_created_cb.setChecked(True)
        self.tab.watch_modified_cb.setChecked(True)
        self.tab.watch_deleted_cb.setChecked(True)
        self.tab.watch_moved_cb.setChecked(True)
        self.tab.min_file_size_spin.setValue(0)
        self.tab.file_extensions_edit.setText('*')
        # The action pane defaults to "Auto Import" on; watcher tests must not inherit
        # a library write, and the action tests switch on exactly what they check.
        for box in (self.tab.auto_import_cb, self.tab.auto_validate_cb,
                    self.tab.auto_thumbnail_cb, self.tab.auto_backup_cb,
                    self.tab.run_script_cb):
            box.setChecked(False)
        self.tab.script_path_edit.setText('')
        self.picked = self.watched
        QFileDialog.getExistingDirectory = lambda *args, **kwargs: self.picked

    def tearDown(self):
        self.tab.file_watcher.stop_watching()
        self.tab.automation_engine.stop()
        self.tab._library.close()
        self.tab.deleteLater()
        shutil.rmtree(self.work, ignore_errors=True)

    # --- helpers ---------------------------------------------------------------
    def add(self, folder):
        self.picked = folder
        self.tab.add_watch_folder()

    def log(self):
        return self.tab.file_events_log.toPlainText()

    def activity(self):
        return [self.tab.activity_list.item(i).text()
                for i in range(self.tab.activity_list.count())]

    def spin(self, want, timeout=8.0):
        """Run the event loop until the watcher's thread has had its say."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.processEvents()
            if want(self.log()):
                return True
            time.sleep(0.02)
        return False

    def write(self, name, text=None):
        target = os.path.join(self.watched, name)
        with open(target, 'w', encoding='utf-8') as handle:
            handle.write(text if text is not None else CUBE + PAD)
        return target

    # --- the pane's own wiring -------------------------------------------------
    def test_01_every_watcher_control_is_connected(self):
        for name in ('add_watch_btn', 'remove_watch_btn', 'start_watching_btn',
                     'stop_watching_btn'):
            button = getattr(self.tab, name)
            self.assertNotEqual(button.receivers(button.clicked), 0, f'{name} is drawn but dead')
        watcher = self.tab.file_watcher
        self.assertNotEqual(watcher.receivers(watcher.file_moved), 0)
        self.assertNotEqual(watcher.receivers(watcher.file_created), 0)
        self.assertNotEqual(self.tab.receivers(self.tab.auto_actions_finished), 0)

    def test_02_the_watch_list_starts_empty(self):
        """Three invented folders claimed to be Active and Paused."""
        self.assertEqual(self.tab.watch_folders_table.rowCount(), 0)
        self.assertEqual(self.tab.watch_requests, {})
        with open(os.path.join(ROOT, 'src', 'ui', 'automation_tab.py'),
                  encoding='utf-8') as handle:
            text = handle.read()
        for stale in ('populate_sample_watches', 'simulate_file_event', 'D:/Dropbox/Shared'):
            self.assertNotIn(stale, text, f'{stale} is still in the tab')

    def test_03_starting_with_nothing_says_so(self):
        self.tab.start_file_watching()
        self.assertIn('Nothing to watch', self.log())
        self.assertFalse(self.tab.file_watcher.is_watching)

    def test_04_starting_with_no_events_selected_says_so(self):
        self.add(self.watched)
        for box in (self.tab.watch_created_cb, self.tab.watch_modified_cb,
                    self.tab.watch_deleted_cb, self.tab.watch_moved_cb):
            box.setChecked(False)
        self.tab.start_file_watching()
        self.assertIn('No watch events selected', self.log())
        self.assertFalse(self.tab.file_watcher.is_watching)
        self.assertEqual(self.tab.file_watcher.watched_directories, {})

    def test_05_adding_a_folder_records_its_filter_and_does_not_duplicate(self):
        self.add(self.watched)
        self.assertEqual(self.tab.watch_folders_table.rowCount(), 1)
        self.assertEqual(list(self.tab.watch_requests), [self.watched])
        self.assertEqual(self.tab.watch_folders_table.item(0, 1).text(), '*')
        self.add(self.watched)
        self.assertEqual(self.tab.watch_folders_table.rowCount(), 1, 'a folder listed twice')
        self.assertEqual(len(self.tab.watch_requests), 1)

    def test_06_the_pane_settings_reach_the_engine(self):
        self.tab.file_extensions_edit.setText('*.obj, *.fbx')
        self.tab.exclude_patterns_edit.setText('*_temp*')
        self.tab.min_file_size_spin.setValue(5)
        self.tab.watch_deleted_cb.setChecked(False)
        self.tab.watch_moved_cb.setChecked(False)
        self.add(self.watched)
        self.tab.start_file_watching()

        path = os.path.abspath(self.watched)
        self.assertIn(path, self.tab.file_watcher.watched_directories)
        info = self.tab.file_watcher.watched_directories[path]
        self.assertEqual(info['file_pattern'], ['*.obj', '*.fbx'])
        self.assertEqual(info['exclude_patterns'], ['*_temp*'])
        self.assertEqual(info['min_size_kb'], 5.0)
        self.assertEqual(info['events'], {'created', 'modified'})
        self.assertEqual(self.tab.watch_folders_table.item(0, 3).text(), 'Watching')

    def test_07_a_folder_that_is_not_there_is_not_claimed_as_watched(self):
        self.picked = os.path.join(self.work, 'missing')
        self.tab.add_watch_folder()
        self.tab.start_file_watching()
        self.assertIn('Not watching', self.log())
        self.assertEqual(self.tab.file_watcher.watched_directories, {})
        self.assertEqual(self.tab.watch_folders_table.item(0, 3).text(), 'Missing folder')
        self.assertNotIn('Watching 1 folder', self.log())

    def test_08_stop_and_start_flip_both_buttons_and_the_rows(self):
        self.add(self.watched)
        self.tab.start_file_watching()
        self.assertFalse(self.tab.start_watching_btn.isEnabled())
        self.assertTrue(self.tab.stop_watching_btn.isEnabled())
        self.tab.stop_file_watching()
        self.assertTrue(self.tab.start_watching_btn.isEnabled())
        self.assertFalse(self.tab.stop_watching_btn.isEnabled())
        self.assertFalse(self.tab.file_watcher.is_watching)
        self.assertEqual(self.tab.watch_folders_table.item(0, 3).text(), 'Stopped')
        self.tab.start_file_watching()
        self.assertTrue(self.tab.file_watcher.is_watching)

    def test_09_removing_a_folder_takes_it_out_of_the_watcher(self):
        self.add(self.watched)
        self.tab.start_file_watching()
        self.tab.watch_folders_table.setCurrentCell(0, 0)
        self.tab.remove_watch_folder()
        self.assertEqual(self.tab.watch_folders_table.rowCount(), 0)
        self.assertEqual(self.tab.file_watcher.watched_directories, {})
        self.assertEqual(self.tab.watch_requests, {})
        self.assertIn('Removed', self.log())

    def test_10_removing_needs_a_selection_first(self):
        self.tab.remove_watch_folder()
        self.assertIn('Select a folder', self.log())

    # --- the real thread, end to end -------------------------------------------
    def test_11_a_file_that_lands_is_logged_as_created(self):
        self.add(self.watched)
        self.tab.start_file_watching()
        self.write('hero.obj')
        self.assertTrue(self.spin(lambda log: 'File created' in log and 'hero.obj' in log),
                        msg=self.log())

    def test_12_an_unchecked_event_leaves_no_line(self):
        self.tab.watch_created_cb.setChecked(False)
        self.tab.watch_modified_cb.setChecked(False)
        self.add(self.watched)
        self.tab.start_file_watching()
        self.write('quiet.obj')
        self.assertFalse(self.spin(lambda log: 'quiet.obj' in log, timeout=1.5),
                         'created was unchecked, so nothing should be reported')

    def test_13_a_rename_reaches_the_moved_line(self):
        self.write('first.obj')
        self.add(self.watched)
        self.tab.start_file_watching()
        self.spin(lambda log: 'Watching' in log)
        os.rename(os.path.join(self.watched, 'first.obj'),
                  os.path.join(self.watched, 'second.obj'))
        self.assertTrue(self.spin(lambda log: 'File moved' in log), msg=self.log())

    def test_14_the_dashboard_counts_the_folders_that_are_watched(self):
        self.add(self.watched)
        self.tab.start_file_watching()
        self.assertEqual(self.tab.file_watchers_label.text(), '1')
        self.tab.stop_file_watching()
        self.assertEqual(self.tab.file_watchers_label.text(), '1')
        self.tab.watch_folders_table.setCurrentCell(0, 0)
        self.tab.remove_watch_folder()
        self.assertEqual(self.tab.file_watchers_label.text(), '0')

    # --- the auto actions pane does its named job -------------------------------
    def settings(self, **overrides):
        base = {'import': False, 'validate': False, 'thumbnail': False,
                'backup': False, 'script': ''}
        base.update(overrides)
        return base

    def test_15_the_settings_snapshot_reads_the_pane(self):
        self.tab.auto_import_cb.setChecked(True)
        self.tab.run_script_cb.setChecked(True)
        self.tab.script_path_edit.setText('C:/tools/notify.py')
        got = self.tab._auto_action_settings()
        self.assertTrue(got['import'])
        self.assertEqual(got['script'], 'C:/tools/notify.py')
        self.tab.run_script_cb.setChecked(False)
        self.assertEqual(self.tab._auto_action_settings()['script'], '',
                         'an unchecked script box must not run anything')
        self.assertEqual(self.tab._auto_action_summary(), 'Import')

    def test_16_nothing_checked_means_nothing_happens(self):
        for box in (self.tab.auto_import_cb, self.tab.auto_validate_cb,
                    self.tab.auto_thumbnail_cb, self.tab.auto_backup_cb,
                    self.tab.run_script_cb):
            box.setChecked(False)
        self.tab.script_path_edit.setText('')
        self.assertEqual(self.tab._auto_action_settings(), self.settings())
        self.assertEqual(self.tab._perform_auto_actions(self.write('x.obj'), self.settings()),
                         [])

    def test_17_auto_backup_copies_the_bytes(self):
        source = self.write('backup_me.obj')
        line = self.tab._perform_auto_actions(source, self.settings(backup=True))[0]
        target = os.path.join(self.watched, tab_module.BACKUP_SUBFOLDER, 'backup_me.obj')
        self.assertTrue(os.path.isfile(target), line)
        with open(target, encoding='utf-8') as copied, open(source, encoding='utf-8') as original:
            self.assertEqual(copied.read(), original.read())
        self.assertIn('copied', line)

    def test_18_auto_import_writes_to_the_library_it_was_given(self):
        source = self.write('library_me.obj')
        line = self.tab._perform_auto_actions(source, self.settings(**{'import': True}))[0]
        self.assertIn('added to library', line)
        paths = [row['path'] for row in self.tab._library.get_models()]
        self.assertIn(os.path.abspath(source), paths)
        again = self.tab._perform_auto_actions(source, self.settings(**{'import': True}))[0]
        self.assertIn('updated in library', again)

    def test_19_auto_import_refuses_a_non_model_file(self):
        note = self.write('notes.txt', 'not a mesh at all\n')
        line = self.tab._perform_auto_actions(note, self.settings(**{'import': True}))[0]
        self.assertIn('not a model format', line)
        self.assertEqual(self.tab._library.get_models(), [])

    def test_20_auto_validate_reports_a_score_it_can_back(self):
        source = self.write('scored.obj')
        line = self.tab._perform_auto_actions(source, self.settings(validate=True))[0]
        self.assertTrue(line.startswith('auto validate'), line)
        if 'failed' in line or 'no report' in line:
            self.fail(f'the analyser could not score a cube that trimesh can read: {line}')
        self.assertIn('/100', line)
        self.assertIn('grade', line)

    def test_21_auto_thumbnail_only_claims_a_file_it_wrote(self):
        source = self.write('thumb.obj')
        line = self.tab._perform_auto_actions(source, self.settings(thumbnail=True))[0]
        if 'bytes' in line:
            name = line.split(':')[1].split('(')[0].strip()
            written = os.path.join(self.thumbs, name)
            self.assertTrue(os.path.isfile(written) and os.path.getsize(written) > 0,
                            f'{line} claims a file that is not there')
        else:
            self.assertIn('nothing rendered', line, line)

    def test_22_a_script_is_run_and_its_exit_code_is_the_verdict(self):
        ok = os.path.join(self.work, 'ok.py')
        with open(ok, 'w', encoding='utf-8') as handle:
            handle.write('print("seen by the script")\n')
        bad = os.path.join(self.work, 'bad.py')
        with open(bad, 'w', encoding='utf-8') as handle:
            handle.write('import sys\nsys.exit(3)\n')
        source = self.write('scripted.obj')

        self.assertIn('custom script: ok',
                       self.tab._perform_auto_actions(source, self.settings(script=ok))[0])
        self.assertIn('exited 3',
                       self.tab._perform_auto_actions(source, self.settings(script=bad))[0])
        missing = self.tab._perform_auto_actions(
            source, self.settings(script=os.path.join(self.work, 'gone.py')))[0]
        self.assertIn('is not a file', missing)

    def test_23_results_from_the_worker_land_in_the_log(self):
        """The worker may not touch the log; it emits, and the slot writes.

        The run is also filed in the list the pane's own close waits on: a thread started
        beside it is a run no close can ever join, and its action would keep copying files
        after the window was gone.
        """
        self.tab.auto_import_cb.setChecked(False)
        self.tab.auto_backup_cb.setChecked(True)
        source = self.write('threaded.obj')
        self.tab._run_auto_actions(source)
        self.assertEqual(1, len(self.tab._action_threads),
                         'the Auto Actions worker was started where no list holds it')
        self.assertTrue(self.spin(lambda log: 'auto backup' in log), msg=self.log())

    def test_24_timestamped_lines_survive_the_datetime_import(self):
        """`import datetime` plus `datetime.now()` raised AttributeError on every slot."""
        self.tab.on_task_started('task_1')
        self.tab.on_task_completed('task_2', False, {'error': 'boom'})
        self.tab.on_workflow_started('wf_1')
        self.tab.on_workflow_failed('wf_1', 'nope')
        self.tab.on_file_created(os.path.join(self.watched, 'cube.obj'))
        lines = self.activity() + self.log().splitlines()
        for needle in ("Task 'task_1' started", "Task 'task_2' FAILED: boom",
                       "Workflow 'wf_1' started", 'File created'):
            matched = [line for line in lines if needle in line]
            self.assertTrue(matched, f'{needle} never logged: {lines}')
            self.assertRegex(matched[0], r'^\[\d\d:\d\d:\d\d\]', 'no timestamp on the line')


if __name__ == '__main__':
    unittest.main(verbosity=2)
