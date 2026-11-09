import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from src.core.animation_importer import AnimationImporter
from src.ui.animation_tab import AnimationTab


class AnimationImporterContract(unittest.TestCase):
    def setUp(self): self.work = tempfile.mkdtemp(prefix='renderfox_animation_')
    def tearDown(self): shutil.rmtree(self.work, ignore_errors=True)

    def test_reads_real_skins_and_animation_channels(self):
        path = os.path.join(self.work, 'rig.gltf')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'skins': [{'joints': [0, 1, 2]}],
                       'animations': [{'name': 'Walk', 'channels': [{}, {}]}]}, handle)
        report = AnimationImporter.inspect(path)
        self.assertTrue(report.success, report.message)
        self.assertEqual((1, 3), (report.skeleton_count, report.joint_count))
        self.assertEqual(('Walk', 2, None), (report.clips[0].name, report.clips[0].channel_count,
                                              report.clips[0].duration_seconds))

    def test_empty_or_unsupported_assets_are_not_called_animated(self):
        path = os.path.join(self.work, 'empty.gltf')
        with open(path, 'w', encoding='utf-8') as handle: json.dump({}, handle)
        self.assertFalse(AnimationImporter.inspect(path).success)
        self.assertIn('no verified reader', AnimationImporter.inspect('scene.fbx').message)

    def test_animation_workspace_shows_the_file_backed_skeleton_report(self):
        app = QApplication.instance() or QApplication([])
        tab = AnimationTab()
        try:
            source = os.path.join(self.work, 'scene.fbx')
            with open(source, 'wb') as handle: handle.write(b'not fbx')
            report = AnimationImporter.inspect
            with mock.patch('src.ui.animation_tab.AnimationImporter.inspect',
                            return_value=report('scene.fbx')):
                with mock.patch.object(tab.viewport, 'load_model', return_value=True):
                    tab.load_model_from_path(source)
            self.assertIn('No playable skeletal data', tab.animation_asset_status.text())
        finally:
            tab.deleteLater()


if __name__ == '__main__': unittest.main(verbosity=2)
