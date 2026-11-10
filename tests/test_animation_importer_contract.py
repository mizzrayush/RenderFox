import json
import base64
import os
import shutil
import struct
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

    def test_samples_file_backed_translation_curve(self):
        path = os.path.join(self.work, 'translate.gltf')
        payload = struct.pack('<2f6f', 0.0, 2.0, 0.0, 0.0, 0.0, 8.0, 4.0, 2.0)
        encoded = base64.b64encode(payload).decode('ascii')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({
                'buffers': [{'uri': f'data:application/octet-stream;base64,{encoded}', 'byteLength': len(payload)}],
                'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 8},
                                {'buffer': 0, 'byteOffset': 8, 'byteLength': 24}],
                'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 2, 'type': 'SCALAR'},
                              {'bufferView': 1, 'componentType': 5126, 'count': 2, 'type': 'VEC3'}],
                'animations': [{'name': 'Move', 'samplers': [{'input': 0, 'output': 1}],
                                'channels': [{'sampler': 0, 'target': {'node': 3, 'path': 'translation'}}]}]
            }, handle)
        report = AnimationImporter.load(path)
        self.assertTrue(report.success, report.message)
        self.assertEqual(2.0, report.clips[0].duration_seconds)
        self.assertEqual((4.0, 2.0, 1.0), AnimationImporter.sample(report.clips[0], 1.0)[3]['translation'])

    def test_workspace_applies_a_file_backed_transform_curve(self):
        app = QApplication.instance() or QApplication([])
        tab = AnimationTab()
        try:
            clip = AnimationImporter.load(self._translation_fixture()).clips[0]
            tab.imported_animation_clip = clip
            tab.clip.fps = 30
            tab.update_viewport_from_frame(30)
            self.assertEqual((4.0, 2.0, 1.0),
                             (tab.viewport.model_translation_x, tab.viewport.model_translation_y,
                              tab.viewport.model_translation_z))
        finally:
            tab.deleteLater()

    def test_workspace_starts_without_fabricated_animation_tracks(self):
        app = QApplication.instance() or QApplication([])
        tab = AnimationTab()
        try:
            self.assertEqual([], tab.tracks)
            self.assertIn('No animation loaded', tab.animation_asset_status.text())
        finally:
            tab.deleteLater()

    def _translation_fixture(self):
        path = os.path.join(self.work, 'workspace_translate.gltf')
        payload = struct.pack('<2f6f', 0.0, 2.0, 0.0, 0.0, 0.0, 8.0, 4.0, 2.0)
        encoded = base64.b64encode(payload).decode('ascii')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'buffers': [{'uri': f'data:application/octet-stream;base64,{encoded}', 'byteLength': len(payload)}],
                       'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 8},
                                       {'buffer': 0, 'byteOffset': 8, 'byteLength': 24}],
                       'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 2, 'type': 'SCALAR'},
                                     {'bufferView': 1, 'componentType': 5126, 'count': 2, 'type': 'VEC3'}],
                       'animations': [{'samplers': [{'input': 0, 'output': 1}],
                                       'channels': [{'sampler': 0, 'target': {'node': 3, 'path': 'translation'}}]}]}, handle)
        return path

    def test_animation_workspace_shows_the_file_backed_skeleton_report(self):
        app = QApplication.instance() or QApplication([])
        tab = AnimationTab()
        try:
            source = os.path.join(self.work, 'scene.fbx')
            with open(source, 'wb') as handle: handle.write(b'not fbx')
            report = AnimationImporter.inspect
            with mock.patch('src.ui.animation_tab.AnimationImporter.load',
                            return_value=report('scene.fbx')):
                with mock.patch.object(tab.viewport, 'load_model', return_value=True):
                    tab.load_model_from_path(source)
            self.assertIn('No playable skeletal data', tab.animation_asset_status.text())
        finally:
            tab.deleteLater()


    def test_rig_inspector_populates_bones_and_turntable_generates_keys(self):
        app = QApplication.instance() or QApplication([])
        tab = AnimationTab()
        try:
            path = os.path.join(self.work, 'test_rig.gltf')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump({
                    'nodes': [
                        {'name': 'Hips', 'children': [1], 'translation': [0.0, 1.0, 0.0]},
                        {'name': 'Spine', 'translation': [0.0, 1.5, 0.0]}
                    ],
                    'skins': [{'name': 'CharacterRig', 'joints': [0, 1]}]
                }, handle)
            with mock.patch.object(tab.viewport, 'load_model', return_value=True):
                tab.load_model_from_path(path)
            self.assertIsNotNone(tab.skeleton_report)
            self.assertEqual(2, len(tab.rig_inspector.joint_items))
            tab.rig_inspector.joint_selected.emit(1)
            self.assertEqual(1, tab.viewport.selected_joint)

            tab.generate_turntable()
            rot_track = next((t for t in tab.clip.tracks if t.property_path == 'rotation_y'), None)
            self.assertIsNotNone(rot_track)
            self.assertEqual(2, len(rot_track.keyframes))
            self.assertEqual(0.0, rot_track.keyframes[0].value)
            self.assertEqual(360.0, rot_track.keyframes[1].value)

            export_path = os.path.join(self.work, "rig_export.json")
            with mock.patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName', return_value=(export_path, 'JSON Files (*.json)')), \
                 mock.patch('PyQt6.QtWidgets.QMessageBox.information'):
                tab.rig_inspector.export_rig_json()
            self.assertTrue(os.path.isfile(export_path))
            with open(export_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.assertIn("skeletons", data)
            self.assertEqual(1, len(data["skeletons"]))
            self.assertEqual(2, len(data["skeletons"][0]["joints"]))
            self.assertEqual("Hips", data["skeletons"][0]["joints"][0]["name"])
            self.assertEqual("Spine", data["skeletons"][0]["joints"][1]["name"])
        finally:
            tab.deleteLater()


if __name__ == '__main__': unittest.main(verbosity=2)
