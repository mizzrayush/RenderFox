"""
Mesh Tools contract test.

Every visible Mesh Tools control is driven through the real UI path, and each one
has to leave a file or a report behind. This exists because the headless tab suite
passes while the buttons themselves raise: it guards the UI-to-backend contract,
not the backend alone.

Run: python tests/test_mesh_tools_contract.py
"""

import os
import sys
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import trimesh

from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.fixtures.mesh_factory import MeshFactory
from src.ui.mesh_tools_tab import MeshToolsTab

MUTATING_OPERATIONS = [
    'simplify_quadric', 'simplify_cluster', 'simplify_planar',
    'close_holes', 'close_small_holes', 'make_manifold',
    'remove_non_manifold_edges', 'remove_non_manifold_vertices',
    'remove_duplicate_vertices', 'remove_degenerate_faces',
    'remove_unreferenced_vertices', 'fix_face_normals', 'invert_normals',
    'smooth_laplacian', 'smooth_taubin', 'smooth_depth',
    'remesh_uniform', 'remesh_voronoi', 'apply_subdivision',
]

MEASURING_OPERATIONS = [
    'show_quality_histogram', 'compute_volume', 'compute_surface_area',
    'compute_curvature', 'show_geometric_info', 'check_watertight',
    'count_components', 'find_holes',
]


class RecordingDialogs:
    """Replace the modal dialogs so a failure becomes data the test can assert on."""

    def __init__(self):
        self.messages = []

    def install(self):
        recorder = self

        def make(kind):
            def show(parent, title, text, *args, **kwargs):
                recorder.messages.append((kind, title, str(text)))
                return QMessageBox.StandardButton.Ok
            return show

        QMessageBox.information = make('information')
        QMessageBox.warning = make('warning')
        QMessageBox.critical = make('critical')
        QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok


class TestMeshToolsContract(unittest.TestCase):
    """Drive every Mesh Tools control and require a real artefact from each."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.dialogs = RecordingDialogs()
        cls.dialogs.install()

        cls.work_dir = tempfile.mkdtemp()
        cls.source_mesh = os.path.join(cls.work_dir, 'source.ply')
        mesh = MeshFactory.create_mesh_with_holes()
        mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh)
        mesh.visual.vertex_colors = np.tile(
            np.array([200, 80, 40, 255], dtype=np.uint8), (len(mesh.vertices), 1))
        mesh.export(cls.source_mesh)

        cls.tab = MeshToolsTab()
        cls.tab.load_mesh_file(cls.source_mesh, notify=False)
        cls.tab.output_folder_combo.setCurrentIndex(0)
        cls.app.processEvents()

    def setUp(self):
        self.dialogs.messages.clear()
        self.tab.clear_history()
        self.tab.load_mesh_file(self.source_mesh, notify=False)
        self.app.processEvents()

    def drain(self, timeout_ms=120000):
        """Wait for the tab's worker pool and let the result slots run."""
        self.tab.threadpool.waitForDone(timeout_ms)
        for _ in range(200):
            self.app.processEvents()

    def error_dialogs(self):
        return [m for kind, title, m in self.dialogs.messages if kind in ('warning', 'critical')]

    def test_01_each_operation_writes_a_mesh(self):
        for name in MUTATING_OPERATIONS:
            with self.subTest(operation=name):
                self.tab.load_mesh_file(self.source_mesh, notify=False)
                self.app.processEvents()
                before = self.tab.current_model_path
                getattr(self.tab, name)()
                self.drain()

                label = self.tab.operation_label.text()
                self.assertFalse(
                    label.startswith('Error'), f'{name} reported: {label}')
                self.assertFalse(
                    self.error_dialogs(), f'{name} raised a dialog: {self.error_dialogs()}')
                self.assertNotEqual(before, self.tab.current_model_path,
                                    f'{name} did not move on to an output mesh')
                self.assertTrue(os.path.exists(self.tab.current_model_path),
                                f'{name} pointed at a missing file')
                self.assertGreater(os.path.getsize(self.tab.current_model_path), 0,
                                   f'{name} wrote an empty file')

    def test_02_measurements_produce_a_report(self):
        for name in MEASURING_OPERATIONS:
            with self.subTest(operation=name):
                getattr(self.tab, name)()
                self.drain()

                report = self.tab.detailed_analysis.toPlainText()
                self.assertTrue(report.strip(), f'{name} produced no report')
                self.assertNotIn('Measurement failed', report)
                self.assertFalse(
                    self.tab.operation_label.text().startswith('Error'),
                    f'{name} reported {self.tab.operation_label.text()}')

    def test_03_summary_and_issue_scan_fill_their_panels(self):
        self.tab.compute_mesh_quality()
        self.drain()
        self.assertIn('Vertices', self.tab.quality_results.toPlainText())

        self.tab.check_manifold()
        self.drain()
        self.assertTrue(self.tab.detailed_analysis.toPlainText().strip())

    def test_04_save_and_export_write_the_chosen_format(self):
        targets = {
            '.obj': os.path.join(self.work_dir, 'export.obj'),
            '.ply': os.path.join(self.work_dir, 'export.ply'),
            '.stl': os.path.join(self.work_dir, 'export.stl'),
            '.off': os.path.join(self.work_dir, 'export.off'),
        }
        for extension, path in targets.items():
            with self.subTest(format=extension):
                QFileDialog.getSaveFileName = staticmethod(lambda *a, **kw: (path, ''))
                self.tab.export_to_format(extension)
                self.drain()
                self.assertTrue(os.path.exists(path), f'{extension} was never written')
                self.assertGreater(os.path.getsize(path), 0, f'{extension} is empty')

    def test_05_export_options_remove_attributes(self):
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **kw: (os.path.join(self.work_dir, 'plain.ply'), ''))
        self.tab.export_colors_cb.setChecked(False)
        self.tab.export_to_format('.ply')
        self.drain()

        stripped = trimesh.load(os.path.join(self.work_dir, 'plain.ply'))
        self.assertIsNone(stripped.visual.kind,
                          'Unchecking "Include Vertex Colors" still wrote colours')

        self.tab.export_colors_cb.setChecked(True)
        self.tab.export_to_format('.ply')
        self.drain()
        kept = trimesh.load(os.path.join(self.work_dir, 'plain.ply'))
        self.assertEqual(kept.visual.kind, 'vertex', 'Vertex colours were not exported')

    def _obj_text(self, path):
        with open(path, encoding='utf-8', errors='replace') as handle:
            return handle.read()

    def test_11_obj_export_toggle_writes_normals(self):
        path = os.path.join(self.work_dir, 'normals.obj')
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **kw: (path, ''))

        self.tab.export_normals_cb.setChecked(True)
        self.tab.export_to_format('.obj')
        self.drain()
        self.assertIn('vn ', self._obj_text(path), 'Normals toggle did nothing')

        self.tab.export_normals_cb.setChecked(False)
        self.tab.export_to_format('.obj')
        self.drain()
        self.assertNotIn('vn ', self._obj_text(path), 'Unchecking normals still wrote vn lines')

    def test_06_undo_returns_to_the_previous_mesh(self):
        before = self.tab.current_model_path
        self.tab.close_holes()
        self.drain()
        after = self.tab.current_model_path
        self.assertNotEqual(before, after)

        self.tab.undo_last()
        self.drain()
        self.assertEqual(self.tab.current_model_path, before,
                         'Undo did not restore the pre-operation mesh')

    def test_07_history_records_completed_operations(self):
        self.tab.smooth_laplacian()
        self.drain()
        self.assertEqual(len(self.tab.processing_history), 1)
        self.assertIn('Laplacian', self.tab.processing_history[0])
        self.assertEqual(self.tab.history_list.count(), 1)

        self.tab.clear_history()
        self.assertEqual(self.tab.history_list.count(), 0)
        self.assertEqual(self.tab.undo_steps, [])

    def test_08_screenshot_saves_the_preview_image(self):
        path = os.path.join(self.work_dir, 'preview.png')
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **kw: (path, ''))

        worker = getattr(self.tab.viewer, 'preview_worker', None)
        if worker is not None:
            worker.wait(60000)
        for _ in range(50):
            self.app.processEvents()

        pixmap = self.tab.viewer.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            self.skipTest('Open3D preview unavailable, nothing to capture')
        self.tab.take_screenshot()
        self.drain()
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 0)

    def test_09_simplify_honours_percentage_target(self):
        original_faces = len(trimesh.load(self.tab.current_model_path).faces)

        self.tab.target_percentage_spin.setValue(50.0)
        self.tab.percentage_target_cb.setChecked(True)
        self.assertFalse(self.tab.target_faces_spin.isEnabled(),
                         'Face-count target stayed live while percentage was chosen')

        self.tab.simplify_quadric()
        self.drain()
        reduced = len(trimesh.load(self.tab.current_model_path).faces)
        self.assertLess(reduced, original_faces,
                        f'{original_faces} faces did not reduce to 50%')
        self.assertLessEqual(reduced, int(original_faces * 0.75))

    def test_10_planar_needs_no_extra_target(self):
        original_faces = len(trimesh.load(self.tab.current_model_path).faces)
        self.tab.planar_target_faces_spin.setValue(max(100, original_faces // 2))
        self.tab.simplify_planar()
        self.drain()
        self.assertLess(len(trimesh.load(self.tab.current_model_path).faces), original_faces)


if __name__ == '__main__':
    unittest.main(verbosity=2)
