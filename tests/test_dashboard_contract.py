"""
Dashboard contract test.

The queue panel is driven through its real widgets - buttons clicked, signals
emitted, table rows selected - and each control has to move the thing its label
promises. This exists because the headless tab suite builds every tab and clicks
nothing that could fail: the Pause and Resume buttons here threw AttributeError on
every click for as long as the audit has been green, and the queue progress bar
sat at 0 through complete renders because it was connected to nothing.

Run: python -X utf8 tests/test_dashboard_contract.py
"""

import os
import shutil
import sys
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from PyQt6.QtWidgets import QApplication

from mock_dcc import mock_dcc as dcc
from src.core.job_manager import JobManager
from src.core.models import JobStatus, RenderJob, SoftwareType
from src.processing.render_engines import (create_render_engine, image_format_choices,
                                           image_format_value)
from src.ui.dashboard_tab import AddJobDialog, DashboardTab

# The command line is what a real renderer reads, so the format names the dialog
# offers are checked against the mock's own list of what Blender accepts rather
# than against another copy of the app's table.
BLENDER_ACCEPTS = set(dcc.BLENDER_FORMAT_NAMES)


def make_job(name, software_type=SoftwareType.BLENDER, fmt='png'):
    return RenderJob(id='', name=name, project_file=f'{name}.blend',
                     software_type=software_type, output_path='out',
                     output_format=fmt)


class SpyManager(JobManager):
    """The queue half of the contract: what the panel asks for, and whether it worked."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.answer = True

    def pause_job(self, job_id):
        self.calls.append(('pause', job_id))
        return self.answer

    def resume_job(self, job_id):
        self.calls.append(('resume', job_id))
        return self.answer

    def start_processing(self):
        self.calls.append(('start', None))

    def stop_processing(self):
        self.calls.append(('stop', None))

    def asked(self, action):
        return [job_id for name, job_id in self.calls if name == action]


class DashboardCase(unittest.TestCase):
    """One dashboard wired to one queue whose answers are recorded."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Unreal's engine writes its pipeline config beside the project file, and
        # these tests hand it a bare name, so the working directory is theirs.
        cls.work = tempfile.mkdtemp(prefix='renderfox_dashboard_')
        cls.previous_cwd = os.getcwd()
        os.chdir(cls.work)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous_cwd)
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.manager = SpyManager()
        self.panel = DashboardTab(self.manager)

    def tearDown(self):
        self.manager.stop_processing()
        self.panel.deleteLater()

    def fill(self, *names):
        jobs = [make_job(name) for name in names]
        for job in jobs:
            self.manager.add_job(job)
        return jobs

    def row_of(self, job):
        for row in range(self.panel.job_table.rowCount()):
            item = self.panel.job_table.item(row, 1)
            if item and item.text() == job.name:
                return row
        self.fail(f'{job.name} is not in the job table')


class TestFormatChoices(DashboardCase):
    """The Add Job dialog may only offer what the chosen engine can be told."""

    def dialog_for(self, software_type):
        dialog = AddJobDialog(self.panel)
        for index in range(dialog.software_combo.count()):
            if dialog.software_combo.itemData(index) == software_type:
                dialog.software_combo.setCurrentIndex(index)
                break
        else:
            self.fail(f'the dialog does not list {software_type.value}')
        return dialog

    def test_01_every_offered_format_builds_a_command_the_engine_accepts(self):
        for software_type in SoftwareType:
            dialog = self.dialog_for(software_type)
            offered = [dialog.format_combo.itemText(index)
                       for index in range(dialog.format_combo.count())]
            self.assertEqual(image_format_choices(software_type), offered,
                             f'the {software_type.value} list is not the engine\'s')
            engine = create_render_engine(software_type, software_type.value)
            for fmt in offered:
                with self.subTest(engine=software_type.value, format=fmt):
                    job = make_job('shot', software_type, fmt)
                    command = engine.get_render_command(job)
                    if software_type == SoftwareType.BLENDER:
                        token = command[command.index('--render-format') + 1]
                        self.assertIn(token, BLENDER_ACCEPTS,
                                      f'Blender was told {token!r}, which is not one '
                                      f'of its format names')
                    elif software_type == SoftwareType.MAYA:
                        mel = command[command.index('-command') + 1]
                        self.assertIn(f'imageFormat {image_format_value(software_type, fmt, "Maya")};',
                                      mel, f'the maya command lost {fmt}: {mel}')

    def test_02_a_format_one_engine_lacks_is_not_offered_for_it(self):
        """Blender renders BMP; Maya's numeric id for it is not in this app's table.

        Offering it anyway used to write PNG files under a `.bmp` expectation, which
        is the silent half of the format bug: the render succeeds, and the frames
        the queue looks for are not there.
        """
        blender = self.dialog_for(SoftwareType.BLENDER)
        maya = self.dialog_for(SoftwareType.MAYA)
        blender_formats = {blender.format_combo.itemText(i)
                           for i in range(blender.format_combo.count())}
        maya_formats = {maya.format_combo.itemText(i)
                        for i in range(maya.format_combo.count())}
        self.assertIn('bmp', blender_formats)
        self.assertNotIn('bmp', maya_formats)
        self.assertEqual({'png', 'jpg', 'exr', 'tiff'}, maya_formats)

    def test_03_the_choice_survives_a_second_engine(self):
        """Switching engines must not silently move the user off the format they set."""
        dialog = self.dialog_for(SoftwareType.BLENDER)
        dialog.format_combo.setCurrentText('tiff')
        dialog.software_combo.setCurrentIndex(
            [index for index in range(dialog.software_combo.count())
             if dialog.software_combo.itemData(index) == SoftwareType.MAYA][0])
        self.assertEqual('tiff', dialog.format_combo.currentText())
        dialog.software_combo.setCurrentIndex(
            [index for index in range(dialog.software_combo.count())
             if dialog.software_combo.itemData(index) == SoftwareType.BLENDER][0])
        self.assertEqual('tiff', dialog.format_combo.currentText())
        dialog.format_combo.setCurrentText('hdr')
        dialog.software_combo.setCurrentIndex(
            [index for index in range(dialog.software_combo.count())
             if dialog.software_combo.itemData(index) == SoftwareType.MAYA][0])
        self.assertEqual('png', dialog.format_combo.currentText(),
                         'a format Maya cannot be told about stayed selected')

    def test_04_the_dialogs_answer_reaches_the_job_it_is_premised_on(self):
        dialog = self.dialog_for(SoftwareType.MAYA)
        dialog.name_edit.setText('mayashot')
        dialog.format_combo.setCurrentText('exr')
        data = dialog.get_job_data()
        self.assertEqual(SoftwareType.MAYA, data['software_type'])
        self.assertEqual('exr', data['output_format'])
        job = make_job('mayashot', SoftwareType.MAYA, data['output_format'])
        command = ' '.join(create_render_engine(SoftwareType.MAYA, 'maya')
                           .get_render_command(job))
        self.assertIn('imageFormat 51', command)


class TestQueueControls(DashboardCase):
    """Every button on the panel has to reach the queue with the right job."""

    def test_05_pause_and_resume_pass_the_id_of_the_row_on_the_cursor(self):
        first, second = self.fill('alpha', 'bravo')
        for job in (first, second):
            self.panel.job_table.setCurrentCell(self.row_of(job), 1)
            self.panel.pause_btn.click()
            self.panel.resume_btn.click()
        self.assertEqual([first.id, second.id], self.manager.asked('pause'))
        self.assertEqual([first.id, second.id], self.manager.asked('resume'))

    def test_06_the_id_is_read_from_the_row_not_the_checkbox(self):
        """Column 0 holds a QCheckBox cell widget, so item(row, 0) is None.

        That is where both buttons used to look, which is why they raised on every
        click: an id taken from a widget is either nothing or somebody else's job.
        """
        job = self.fill('charlie')[0]
        self.panel.job_table.setCurrentCell(self.row_of(job), 1)
        self.assertIsNone(self.panel.job_table.item(self.row_of(job), 0))
        self.assertEqual(job.id, self.panel.selected_job_id())

    def test_07_a_button_without_a_row_says_so_instead_of_raising(self):
        self.fill('delta')
        self.panel.job_table.clearSelection()
        self.panel.job_table.setCurrentCell(-1, -1)
        self.panel.pause_btn.click()
        self.panel.resume_btn.click()
        self.assertEqual([], self.manager.asked('pause'))
        self.assertEqual([], self.manager.asked('resume'))
        self.assertIn('Select', self.panel.status_label.text())

    def test_08_a_refusal_from_the_queue_is_reported_instead_of_swallowed(self):
        job = self.fill('echo')[0]
        self.panel.job_table.setCurrentCell(self.row_of(job), 1)
        self.manager.answer = False
        self.panel.pause_btn.click()
        self.assertIn('Only a job that is rendering', self.panel.status_label.text())
        self.panel.resume_btn.click()
        self.assertIn('Only a paused job', self.panel.status_label.text())

    def test_09_start_and_stop_buttons_reach_the_queue(self):
        self.panel.start_btn.click()
        self.panel.stop_btn.click()
        self.assertEqual([None], self.manager.asked('start'))
        self.assertEqual([None], self.manager.asked('stop'))

    def test_10_multi_select_returns_the_jobs_it_marks(self):
        first, second = self.fill('foxtrot', 'golf')
        for row in range(self.panel.job_table.rowCount()):
            box = self.panel.job_table.cellWidget(row, 0)
            if self.panel.job_table.item(row, 1).text() in (first.name, second.name):
                box.setChecked(True)
        self.assertEqual({first.id, second.id},
                         {job.id for job in self.panel.get_selected_jobs()})


class TestQueueReadout(DashboardCase):
    """The bar and the status line describe the queue as it actually is."""

    def start(self, *names):
        jobs = self.fill(*names)
        for job in jobs:
            job.status = JobStatus.RENDERING
            self.manager._running[job.id] = (job, None)
        self.manager._is_processing = True
        return jobs

    def test_11_a_frame_reported_by_a_renderer_moves_the_bar(self):
        """`update_progress` was defined and connected to nothing.

        Nothing else moved the bar, so a job that reached 100% still showed 0 while
        the Settings tab's own bar filled from the same signal.
        """
        job = self.start('hotel')[0]
        job.progress = 42.0
        self.manager.job_updated.emit(job)
        self.assertEqual(42, self.panel.queue_progress.value())
        job.progress = 100.0
        self.manager.job_updated.emit(job)
        self.assertEqual(100, self.panel.queue_progress.value())

    def test_12_the_bar_reads_the_oldest_live_job_when_two_are_running(self):
        first, second = self.start('india', 'juliet')
        first.progress, second.progress = 30.0, 90.0
        self.manager.job_updated.emit(second)
        self.assertEqual(30, self.panel.queue_progress.value())
        self.manager._running.pop(first.id)
        self.manager.job_updated.emit(second)
        self.assertEqual(90, self.panel.queue_progress.value())

    def test_13_the_status_line_counts_every_live_job(self):
        first, second = self.start('kilo', 'lima')
        self.manager.job_updated.emit(first)
        self.assertEqual('Processing: kilo (+1 more)', self.panel.status_label.text())
        self.manager._running.pop(second.id)
        self.manager.job_updated.emit(first)
        self.assertEqual('Processing: kilo', self.panel.status_label.text())

    def test_14_a_queue_with_nothing_in_flight_says_ready(self):
        self.panel.update_status()
        self.assertEqual('Ready', self.panel.status_label.text())
        self.manager._is_processing = True
        self.panel.update_status()
        self.assertEqual('Processing queue...', self.panel.status_label.text())

    def test_15_a_queue_that_stops_itself_hides_its_bar(self):
        """`stop_queue` hid the bar because the user clicked Stop.

        "Pause queue on error" ends a run with no click at all, so the panel kept
        showing a bar stuck at the last frame of a render that had already ended.
        The job has failed and left its slot here, exactly as it does when the real
        queue breaks - and the line still said "Processing", because nothing asked
        it to look again.
        """
        job = self.start('mike')[0]
        self.panel.queue_progress.setVisible(True)
        self.panel.queue_progress.setValue(55)
        self.manager._running.pop(job.id)
        self.manager._is_processing = False
        job.status = JobStatus.FAILED
        self.manager.processing_stopped.emit()
        self.assertFalse(self.panel.queue_progress.isVisibleTo(self.panel))
        self.assertEqual('Ready', self.panel.status_label.text())

    def test_16_the_bar_is_shown_on_start_and_hidden_on_stop(self):
        self.panel.start_btn.click()
        self.panel.queue_progress.setVisible(True)
        self.panel.stop_btn.click()
        self.assertFalse(self.panel.queue_progress.isVisibleTo(self.panel))


if __name__ == '__main__':
    unittest.main(verbosity=2)
