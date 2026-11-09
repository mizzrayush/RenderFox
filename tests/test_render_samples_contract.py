"""
Render samples contract test (Phase 15c-1).

"Samples: 128" was deleted from the Rendering tab in 3ccd6ab because that tab is a
lookdev preview with no sampling renderer behind it. The count belongs to the DCC
queue: a RenderJob carries it, the Dashboard's job form and preset set it, and each
engine emits its own flag for it. This suite proves the number reaches the command
surface every engine actually reads - Blender's python-expr, Maya's MEL, Unreal's
pipeline config - and that Cinema 4D, whose command line has no sample parameter,
is not handed an invented one. Nothing here renders; the command line is the claim.

Run: python -X utf8 tests/test_render_samples_contract.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from src.core.models import RenderJob, SoftwareType
from src.processing.render_engines import create_render_engine
from src.ui import dashboard_tab
from src.ui.dashboard_tab import AddJobDialog, DashboardTab, RenderPresetDialog


class SamplesCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Unreal writes its pipeline config beside the project file, so the working
        # directory and the project paths are this suite's own temp folder.
        cls.work = tempfile.mkdtemp(prefix='renderfox_samples_')
        cls.previous_cwd = os.getcwd()
        os.chdir(cls.work)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous_cwd)
        shutil.rmtree(cls.work, ignore_errors=True)

    def project(self, suffix):
        path = os.path.join(self.work, 'shot' + suffix)
        with open(path, 'w') as handle:
            handle.close()
        return path

    def job(self, software_type, samples, suffix):
        return RenderJob(name='Hero Shot', project_file=self.project(suffix),
                         software_type=software_type, output_path=self.work,
                         resolution=(1920, 1080), samples=samples, frame_range=(1, 10))

    def command(self, software_type, samples, suffix):
        job = self.job(software_type, samples, suffix)
        return ' '.join(create_render_engine(software_type, software_type.value)
                        .get_render_command(job))


class TestTheCountReachesTheCommand(SamplesCase):
    def test_01_a_job_carries_a_default_of_128(self):
        self.assertEqual(128, RenderJob().samples)

    def test_02_blender_sets_cycles_samples_in_the_python_expr(self):
        command = self.command(SoftwareType.BLENDER, 256, '.blend')
        self.assertIn('bpy.context.scene.cycles.samples = 256', command)

    def test_03_maya_sets_arnold_aa_samples_in_the_mel(self):
        command = self.command(SoftwareType.MAYA, 256, '.ma')
        self.assertIn('setAttr defaultArnoldRenderOptions.AASamples 256;', command)

    def test_04_unreal_writes_the_sample_count_into_the_config(self):
        import json
        job = self.job(SoftwareType.UNREAL, 256, '.uproject')
        command = create_render_engine(SoftwareType.UNREAL, 'unreal').get_render_command(job)
        config_arg = [c for c in command if c.startswith('-MoviePipelineConfig=')][0]
        with open(config_arg.split('=', 1)[1]) as handle:
            config = json.load(handle)
        self.assertEqual(256, config['SpatialSampleCount'])

    def test_05_cinema4d_invents_no_samples_flag(self):
        command = self.command(SoftwareType.CINEMA4D, 256, '.c4d')
        self.assertNotIn('-samples', command)
        self.assertNotIn('256', command)

    def test_06_a_zero_or_negative_is_made_safe_not_emitted_raw(self):
        for asked in (0, -5):
            command = self.command(SoftwareType.BLENDER, asked, '.blend')
            self.assertIn('bpy.context.scene.cycles.samples = 1', command)
            self.assertNotIn(f'cycles.samples = {asked}', command)


class TestTheControlReachesTheJob(SamplesCase):
    def setUp(self):
        self.panel = DashboardTab()

    def tearDown(self):
        self.panel.deleteLater()

    def test_07_the_dialog_offers_a_typable_samples_box_defaulting_to_128(self):
        dialog = AddJobDialog(self.panel)
        self.assertEqual(128, dialog.samples_spin.value())
        self.assertEqual(1, dialog.samples_spin.minimum())
        self.assertEqual(4096, dialog.samples_spin.maximum())
        self.assertFalse(dialog.samples_spin.isReadOnly())
        dialog.deleteLater()

    def test_08_the_dialogs_answer_carries_the_samples_it_shows(self):
        dialog = AddJobDialog(self.panel)
        dialog.samples_spin.setValue(321)
        self.assertEqual(321, dialog.get_job_data()['samples'])
        dialog.deleteLater()

    def test_09_add_new_job_builds_a_job_with_the_samples_chosen(self):
        added = []
        data = {'name': 'shot', 'project_file': 'shot.blend',
                'software_type': SoftwareType.BLENDER, 'resolution': (1920, 1080),
                'samples': 321, 'output_format': 'png', 'output_path': 'out'}
        self.panel.job_manager.add_job = lambda job: added.append(job)
        with mock.patch.object(AddJobDialog, 'exec',
                               return_value=QDialog.DialogCode.Accepted), \
             mock.patch.object(AddJobDialog, 'get_job_data', return_value=data):
            self.panel.add_new_job()
        self.assertEqual(1, len(added))
        self.assertEqual(321, added[0].samples)

    def test_10_the_preset_writes_the_sample_count_onto_the_job(self):
        job = RenderJob(name='shot', project_file='shot.blend', samples=128)
        self.panel.get_selected_jobs = lambda: [job]
        preset = {'preset_name': '4K Ultra',
                  'config': {'resolution': (3840, 2160), 'samples': 256, 'quality': 100},
                  'override_resolution': False, 'override_quality': True}
        with mock.patch.object(RenderPresetDialog, 'exec',
                               return_value=QDialog.DialogCode.Accepted), \
             mock.patch.object(RenderPresetDialog, 'get_preset_data', return_value=preset), \
             mock.patch.object(dashboard_tab.QMessageBox, 'information'):
            self.panel.apply_render_preset_to_selected()
        self.assertEqual(256, job.samples)

    def test_11_export_and_import_round_trip_the_samples(self):
        import json
        job = RenderJob(name='shot', project_file='shot.blend', samples=321,
                        software_type=SoftwareType.BLENDER)
        self.panel.get_selected_jobs = lambda: [job]
        path = os.path.join(self.work, 'jobs.json')
        with mock.patch.object(dashboard_tab.QFileDialog, 'getSaveFileName',
                               return_value=(path, '')), \
             mock.patch.object(dashboard_tab.QMessageBox, 'information'):
            self.panel.export_selected_jobs()
        with open(path) as handle:
            exported = json.load(handle)
        self.assertEqual(321, exported['jobs'][0]['samples'])
        added = []
        self.panel.job_manager.add_job = lambda j: added.append(j)
        with mock.patch.object(dashboard_tab.QFileDialog, 'getOpenFileName',
                               return_value=(path, '')), \
             mock.patch.object(dashboard_tab.QMessageBox, 'information'):
            self.panel.import_jobs()
        self.assertEqual(1, len(added))
        self.assertEqual(321, added[0].samples)


if __name__ == '__main__':
    unittest.main(verbosity=2)