"""The Versions pane commits the files a DCC actually hands it, and says what it measured.

This suite exists because `save_version` read its metrics off whatever `trimesh.load` returns
and assumed one answer. Measured on this machine before any of this was written: an `.obj`
carrying `mtllib` and `usemtl` - which is what the app's own `MeshRepairer.auto_repair` writes,
`repaired_model.obj.mtl` beside it - loads as a **Scene**; a file whose faces have been deleted
loads as a **PointCloud**; and an empty or garbled `.obj` loads as a Scene with no geometries.
`len(mesh.faces)` raised `AttributeError` on the first two, `save_version`'s own
`except Exception` logged it and returned None, and the pane told the user "No changes
detected. Version not saved." - a statement about a comparison that never ran. Worse, the copy
of the snapshot happened *before* that raise, so every failed commit left a file on disk that
no row points at, that rollback cannot see and that nothing ever deletes.

What is asked, in order: that a mesh, a multi-material Scene and a point cloud each commit and
record the numbers the app really measured, checked against an oracle read straight off the
file and not through this backend; that the third-party facts the design leans on are measured
here rather than trusted - a `PointCloud` has no `faces`, no `is_watertight` and no `volume`,
and the app's normaliser answers None for it and for an empty Scene; that a file with nothing
to measure is refused *before* it is copied, so it leaves no snapshot, and that a write
interrupted after the copy takes the copy back; that a first version claims no delta against a
parent it does not have, that every later delta equals the two numbers printed above it, and
that a parent snapshot deleted from disk costs the volume and not the counts; that the
timeline's column, its details, its statistics, the comparison dialog and the HTML export all
speak the backend's words for an absent number instead of formatting `None`; that the pane
names which of the four facts stopped a commit; that this vocabulary - and the Scene
normalising behind it - live in one module; and that `tests/test_full_flow.py`, the run that
was green for `Committed version: None`, now exits nonzero unless it can prove its own claim.

Run: python -X utf8 tests/test_version_metrics_contract.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import trimesh
from PyQt6.QtWidgets import QApplication, QDialog, QTableWidget

from src.features.version_control import (AssetVersionControl, NOT_COMPARABLE, describe_metrics,
                                          describe_polygon_count, describe_volume,
                                          describe_watertight)
from src.processing.format_converter import as_trimesh
from src.ui import version_control_ui as vc_ui
from src.ui.version_control_ui import VersionComparisonDialog, VersionControlUI

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

CUBE_HEADER = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nv 1 0 1\nv 1 1 1\nv 0 1 1\n"
CUBE_FACES = ("f 1 2 3\nf 1 3 4\nf 5 7 6\nf 5 8 7\nf 1 5 6\nf 1 6 2\n"
              "f 2 6 7\nf 2 7 3\nf 3 7 8\nf 3 8 4\nf 4 8 5\nf 4 5 1\n")
CUBE = CUBE_HEADER + CUBE_FACES
_FACE_LINES = [line for line in CUBE_FACES.splitlines() if line]

# The same twelve faces split across two materials. Measured here: trimesh answers a Scene of 3
# geometries whose counts sum to 12 faces and 20 vertices - the faces are all there, and the
# corners are copied once per group, so the vertex count is not the eight the file lines out.
MULTI_MATERIAL = ('mtllib two.mtl\n' + CUBE_HEADER
                  + '\n'.join(_FACE_LINES[:4]) + '\nusemtl a\n'
                  + '\n'.join(_FACE_LINES[4:9]) + '\nusemtl b\n'
                  + '\n'.join(_FACE_LINES[9:]) + '\n')
MTLIB = 'newmtl a\nKd 1 0 0\nnewmtl b\nKd 0 1 0\n'

# Three positions and no face: what a DCC hands over when the surface was deleted and the
# points were kept. Measured: a PointCloud of 3 vertices.
POINT_CLOUD = 'v 0 0 0\nv 1 0 0\nv 0 1 0\n'

# A closed-looking pyramid with its base wound the wrong way round: measured 6 faces, 5
# vertices, watertight, and `is_volume` False - which is why it has no volume to have gained.
PYRAMID = ("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0.5 0.5 1\n"
           "f 1 2 5\nf 2 3 5\nf 3 4 5\nf 4 1 5\nf 1 3 2\nf 1 3 4\n")


def read(absolute_path):
    with open(absolute_path, encoding='utf-8') as handle:
        return handle.read()


def geometry_of(path):
    """What the file holds, read straight off trimesh and not through this backend."""
    loaded = trimesh.load(path)
    if isinstance(loaded, trimesh.Scene):
        return (sum(len(g.faces) for g in loaded.geometry.values()),
                sum(len(g.vertices) for g in loaded.geometry.values()))
    if isinstance(loaded, trimesh.Trimesh):
        return len(loaded.faces), len(loaded.vertices)
    return None, len(loaded.vertices)


class VersionMetricsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='vc_metrics_')
        self.write('two.mtl', MTLIB)
        self.engine = self.engine_at()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.home, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def engine_at(self, name='library'):
        return AssetVersionControl(os.path.join(self.home, name))

    def snapshots(self, engine=None):
        return sorted(os.listdir((engine or self.engine).snapshots_dir))

    def thumbnails(self, engine=None):
        return sorted(os.listdir((engine or self.engine).thumbnails_dir))

    def rows(self, path, engine=None):
        return (engine or self.engine).get_version_history(path)

    def row_for(self, path, version_id, engine=None):
        return next(r for r in self.rows(path, engine) if r['id'] == version_id)

    def test_01_a_mesh_a_scene_and_a_point_cloud_each_commit_what_they_are(self):
        cases = [('plain.obj', CUBE), ('multi.obj', MULTI_MATERIAL),
                 ('cloud.obj', POINT_CLOUD)]
        committed = {}
        for name, text in cases:
            path = self.write(name, text)
            version_id = self.engine.save_version(path, commit_message=f'{name} first')
            self.assertIsNotNone(version_id, f'{name} committed as nothing')
            rows = self.rows(path)
            self.assertEqual(1, len(rows), f'{name} wrote {len(rows)} rows for one commit')
            committed[name] = rows[0]
            self.assertTrue(os.path.exists(rows[0]['snapshot_path']),
                            f'{name} records a snapshot that is not on disk')

        for name, _ in cases:
            with self.subTest(file=name):
                faces, vertices = geometry_of(os.path.join(self.home, name))
                row = committed[name]
                self.assertEqual(faces, row['polygon_count'],
                                 f'{name}: the row says {row["polygon_count"]} faces, the file '
                                 f'holds {faces} in the shapes trimesh reads from it')
                self.assertEqual(vertices, row['vertex_count'],
                                 f'{name}: the row says {row["vertex_count"]} vertices, the '
                                 f'file holds {vertices}')

        self.assertEqual((12, 8, 1), (committed['plain.obj']['polygon_count'],
                                      committed['plain.obj']['vertex_count'],
                                      int(committed['plain.obj']['is_watertight'])))
        self.assertEqual((12, 20, 0), (committed['multi.obj']['polygon_count'],
                                       committed['multi.obj']['vertex_count'],
                                       int(committed['multi.obj']['is_watertight'])),
                         'the Scene was recorded with the file eight corners, not the twenty '
                         'the app holds')
        self.assertEqual((None, 3, None), (committed['cloud.obj']['polygon_count'],
                                           committed['cloud.obj']['vertex_count'],
                                           committed['cloud.obj']['is_watertight']),
                         'a point cloud was given a face count and a watertightness claim')

    def test_02_the_third_party_answers_this_design_leans_on_are_measured_not_trusted(self):
        cloud = trimesh.load(self.write('p.obj', POINT_CLOUD))
        self.assertIsInstance(cloud, trimesh.PointCloud)
        for attribute in ('faces', 'is_watertight', 'volume'):
            with self.assertRaises(AttributeError,
                                   msg=f'PointCloud.{attribute} now exists, so the None this '
                                       f'backend records for it is a fact it threw away'):
                getattr(cloud, attribute)

        scene = trimesh.load(self.write('m.obj', MULTI_MATERIAL))
        self.assertIsInstance(scene, trimesh.Scene)
        self.assertEqual(3, len(scene.geometry))
        self.assertEqual(12, len(as_trimesh(scene).faces))

        for name, text in (('empty.obj', ''), ('garbage.obj', 'this is not a model\n')):
            nothing = trimesh.load(self.write(name, text))
            self.assertIsNone(as_trimesh(nothing),
                              f'{name}: the normaliser now answers a file with no geometry, '
                              f'so the backend cannot tell a mesh from nothing')
            self.assertFalse(isinstance(nothing, trimesh.PointCloud),
                             f'{name} now loads as a cloud, so the refusal in test_03 is wrong')

    def test_03_a_file_with_nothing_to_measure_is_refused_before_it_is_copied(self):
        empty = self.write('empty.obj', '')
        with self.assertLogs('src.features.version_control', level='ERROR') as captured:
            self.assertIsNone(self.engine.save_version(empty, commit_message='empty'))
        self.assertTrue(any('holds neither a triangle mesh nor a point cloud' in line
                            for line in captured.output), captured.output)
        self.assertEqual([], self.snapshots(),
                         'a refused commit copied the file into the snapshots folder anyway')
        self.assertEqual([], self.thumbnails(),
                         'a refused commit drew a picture for a row that does not exist')
        self.assertEqual([], self.rows(empty))

        # A file trimesh will not open at all is refused by that fact, with its reason.
        notes = self.write('notes.txt', 'hello\n')
        with self.assertLogs('src.features.version_control', level='ERROR') as captured:
            self.assertIsNone(self.engine.save_version(notes, commit_message='notes'))
        self.assertTrue(any('Could not read notes.txt' in line for line in captured.output),
                        captured.output)
        self.assertEqual([], self.snapshots())

        # `explain_no_commit` is how the pane learns which fact it was, and it asks the same
        # questions the commit asked instead of keeping a note of the last answer.
        self.assertEqual('no_geometry', self.engine.explain_no_commit(empty)['kind'])
        self.assertEqual('unreadable', self.engine.explain_no_commit(notes)['kind'])
        verdict = self.engine.explain_no_commit(os.path.join(self.home, 'gone.obj'))
        self.assertEqual('no_file', verdict['kind'])
        self.assertIn('no file', verdict['reason'])

    def test_04_a_write_interrupted_after_the_copy_takes_the_copy_back(self):
        path = self.write('cube.obj', CUBE)

        def explode(*args, **kwargs):
            raise RuntimeError('the row could not be written')

        with mock.patch.object(AssetVersionControl, '_save_version_to_db', explode):
            with self.assertLogs('src.features.version_control', level='ERROR') as captured:
                self.assertIsNone(self.engine.save_version(path, commit_message='doomed'))
        self.assertIn('Error saving version', ''.join(captured.output))
        self.assertEqual([], self.snapshots(),
                         'a commit that wrote no row left its snapshot on disk')
        self.assertEqual([], self.thumbnails(),
                         'a commit that wrote no row left its picture on disk')

        # The same question one step earlier, with the picture as the step that fails: the
        # snapshot is the file that has to go, and nothing else had been written yet.
        with mock.patch.object(AssetVersionControl, '_generate_thumbnail', explode):
            with self.assertLogs('src.features.version_control', level='ERROR'):
                self.assertIsNone(self.engine.save_version(path, commit_message='no picture'))
        self.assertEqual([], self.snapshots())
        self.assertEqual([], self.thumbnails())
        self.assertEqual([], self.rows(path))

    def test_05_a_first_version_claims_no_delta_and_a_second_its_true_one(self):
        path = self.write('box.obj', '')
        trimesh.creation.box(extents=(1, 1, 1)).export(path)
        first = self.engine.save_version(path, commit_message='one cubic unit')
        row = self.row_for(path, first)
        for field in ('polygons_delta', 'vertices_delta', 'volume_delta'):
            self.assertIsNone(row[field],
                              f'{field} of {row[field]!r}: a first version has no parent to be '
                              f'equal to, and 0 is a claim about a comparison that never ran')
        self.assertEqual((12, 8), (row['polygon_count'], row['vertex_count']))
        self.assertGreater(row['file_size'], 0)

        trimesh.creation.box(extents=(2, 1, 1)).export(path)
        second = self.engine.save_version(path, commit_message='two cubic units')
        row = self.row_for(path, second)
        self.assertEqual(0, row['polygons_delta'], 'the same twelve faces should delta to 0')
        self.assertEqual(0, row['vertices_delta'])
        self.assertEqual(1.0, row['volume_delta'], 'the box doubled its volume and the row says '
                                                   'otherwise')

        self.write('box.obj', PYRAMID)
        third = self.engine.save_version(path, commit_message='six faces, not closed')
        row = self.row_for(path, third)
        self.assertEqual(-6, row['polygons_delta'])
        self.assertEqual(-3, row['vertices_delta'])
        self.assertIsNone(row['volume_delta'], 'an open surface has no volume to have gained')

        # Every delta has to agree with the two rows it is a delta between: those are the
        # numbers the pane prints directly above it.
        rows = {r['id']: r for r in self.rows(path)}
        for newer, older in ((second, first), (third, second)):
            self.assertEqual(rows[newer]['polygon_count'] - rows[older]['polygon_count'],
                             rows[newer]['polygons_delta'])
            self.assertEqual(rows[newer]['vertex_count'] - rows[older]['vertex_count'],
                             rows[newer]['vertices_delta'])

        # A mesh that follows a cloud row has no parent face count to be subtracted from. A `0`
        # read out of that absence would print a gain of twelve faces over a file that never had
        # any, so the row says nothing instead.
        self.write('box.obj', POINT_CLOUD)
        cloud = self.engine.save_version(path, commit_message='points only')
        row = self.row_for(path, cloud)
        self.assertIsNone(row['polygon_count'])
        self.assertEqual(-2, row['vertices_delta'], 'the five corners became three points')

        trimesh.creation.box(extents=(2, 1, 1.5)).export(path)
        fourth = self.engine.save_version(path, commit_message='a mesh again')
        row = self.row_for(path, fourth)
        self.assertEqual(12, row['polygon_count'])
        self.assertEqual(5, row['vertices_delta'])
        self.assertIsNone(row['polygons_delta'],
                          'the row above records no face count, so a difference against it is '
                          'not a number')
        self.assertIsNone(row['volume_delta'],
                          'the parent snapshot is a point cloud, which holds no volume')

        # An open parent costs the volume and only the volume. The pyramid is watertight but its
        # base is wound the wrong way, so trimesh answers `is_volume` False and there is no
        # volume of it for the box above to have gained; the counts still come from its row.
        open_path = self.write('open.obj', PYRAMID)
        self.engine.save_version(open_path, commit_message='open base')
        trimesh.creation.box(extents=(2, 1, 1.5)).export(open_path)
        child = self.engine.save_version(open_path, commit_message='closed on top')
        row = self.row_for(open_path, child)
        self.assertEqual(6, row['polygons_delta'])
        self.assertEqual(3, row['vertices_delta'])
        self.assertIsNone(row['volume_delta'],
                          'the parent surface is open, so the child gained no measurable volume')

    def test_06_a_deleted_parent_snapshot_costs_the_volume_and_not_the_counts(self):
        path = self.write('box.obj', '')
        trimesh.creation.box(extents=(1, 1, 1)).export(path)
        first = self.engine.save_version(path, commit_message='parent')
        os.remove(self.row_for(path, first)['snapshot_path'])

        trimesh.creation.box(extents=(3, 1, 1)).export(path)
        with self.assertLogs('src.features.version_control', level='WARNING') as captured:
            second = self.engine.save_version(path, commit_message='child')
        row = self.row_for(path, second)
        self.assertEqual(0, row['polygons_delta'],
                         'the counts come from the parent row, which is still there')
        self.assertEqual(0, row['vertices_delta'])
        self.assertIsNone(row['volume_delta'],
                          'the parent snapshot is gone and the row still claims a volume change')
        self.assertTrue(any('its snapshot could not be read' in line for line in captured.output),
                        captured.output)
        self.assertEqual(1, len(self.snapshots()),
                         'the child snapshot is the one file this commit should have left')
        self.assertTrue(os.path.exists(self.row_for(path, second)['snapshot_path']))

    def test_07_the_timeline_says_which_number_the_file_does_not_have(self):
        self.assertEqual('P: 12, V: 8',
                         describe_metrics({'polygon_count': 12, 'vertex_count': 8}))
        self.assertEqual('V: 3, no faces',
                         describe_metrics({'polygon_count': None, 'vertex_count': 3}))
        self.assertEqual('P: 12, V: 8 (+4)',
                         describe_metrics({'polygon_count': 12, 'vertex_count': 8,
                                           'polygons_delta': 4}))
        self.assertEqual('V: 3, no faces',
                         describe_metrics({'polygon_count': None, 'vertex_count': 3,
                                           'polygons_delta': None}),
                         'a None delta was printed as a change')
        self.assertEqual('no faces', describe_polygon_count({'polygon_count': None}))
        self.assertEqual('12', describe_polygon_count({'polygon_count': 12}))
        self.assertEqual('no faces to close', describe_watertight({'is_watertight': None}))
        self.assertEqual('Yes', describe_watertight({'is_watertight': 1}))
        self.assertEqual('No', describe_watertight({'is_watertight': 0}))
        self.assertEqual('no faces to close', describe_volume(None))
        self.assertEqual('+1.0000', describe_volume(1.0, signed=True))
        self.assertEqual('not comparable - one version of this file has no faces', NOT_COMPARABLE)

        # Through the pane, because the strings above are nothing until a row shows them.
        model = self.write('shown.obj', '')
        trimesh.creation.box(extents=(1, 1, 1)).export(model)
        self.engine.save_version(model, commit_message='a mesh')
        time.sleep(1.05)
        self.write('shown.obj', POINT_CLOUD)
        self.engine.save_version(model, commit_message='a cloud')
        self.assertEqual(2, len(self.rows(model)))

        pane = VersionControlUI(os.path.join(self.home, 'pane_library'))
        pane.version_control = self.engine
        pane.load_model(model)
        self.app.processEvents()
        self.assertEqual(2, pane.version_tree.topLevelItemCount())

        newest = pane.version_tree.topLevelItem(0)
        self.assertEqual('V: 3, no faces', newest.text(3),
                         'the cloud row was given a face count it does not have')
        self.assertIn('no faces', pane.stats_label.text(),
                      'the statistics line summed across a version that has no faces')
        pane.version_tree.setCurrentItem(newest)
        self.app.processEvents()
        details = pane.details_text.toPlainText()
        self.assertIn('Polygons: no faces', details)
        self.assertIn('no faces to close', details)
        self.assertNotIn('Polygons: 0', details)

        older = pane.version_tree.topLevelItem(1)
        pane.version_tree.setCurrentItem(older)
        self.app.processEvents()
        self.assertEqual('P: 12, V: 8', older.text(3))
        self.assertIn('Polygons: 12', pane.details_text.toPlainText())
        self.assertIn('Watertight: ✓ Yes', pane.details_text.toPlainText())
        pane.deleteLater()

    def test_08_the_pane_names_which_fact_stopped_the_commit(self):
        model = self.write('commit.obj', CUBE)
        pane = VersionControlUI(os.path.join(self.home, 'pane_library'))
        pane.version_control = self.engine
        pane.load_model(model)
        self.app.processEvents()

        spoken = []

        class Mouth:
            @staticmethod
            def warning(parent, title, text, *args):
                spoken.append((title, text))

            @staticmethod
            def information(*args):
                pass

            @staticmethod
            def critical(*args):
                spoken.append(('critical', args[-1]))

        class Accepted:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def get_commit_data(self):
                return {'message': 'clicked commit', 'author': 'Ayush'}

        with mock.patch.object(vc_ui, 'CommitDialog', Accepted), \
                mock.patch.object(vc_ui, 'QMessageBox', Mouth):
            pane.commit_version()
            self.assertEqual([], spoken, 'a commit that worked had something to say')
            self.assertEqual(1, len(self.rows(model)))

            # Same bytes: the one case in which "no changes detected" is a true sentence.
            pane.commit_version()
            self.assertEqual(1, len(self.rows(model)))
            self.assertEqual(1, len(spoken))
            title, reason = spoken[0]
            self.assertEqual('Nothing Committed', title)
            self.assertIn('No changes detected', reason)
            self.assertEqual(self.engine.explain_no_commit(model)['reason'], reason,
                             'the pane rewrote the backend\'s reason instead of showing it')

            spoken.clear()
            self.write('commit.obj', '')   # different bytes now, and nothing in them to measure
            pane.commit_version()
            self.assertEqual(1, len(self.rows(model)), 'a file with no geometry wrote a row')
            self.assertEqual(1, len(spoken))
            self.assertIn('nothing to measure', spoken[0][1])
            self.assertEqual('no_geometry', self.engine.explain_no_commit(model)['kind'])
        pane.deleteLater()

    def test_09_the_comparison_answers_with_the_file_not_with_the_exception(self):
        engine = self.engine_at('library_mesh')
        mesh_path = self.write('cmp_mesh.obj', CUBE)
        a = engine.save_version(mesh_path, commit_message='cube a')
        time.sleep(1.05)
        self.write('cmp_mesh.obj', PYRAMID)
        b = engine.save_version(mesh_path, commit_message='cube b')

        comparison = engine.compare_versions(a, b)
        self.assertNotIn('error', comparison, comparison)
        self.assertEqual({'v1': 12, 'v2': 6, 'delta': -6, 'percent': -50.0},
                         comparison['changes']['polygons'])
        self.assertEqual({'v1': 8, 'v2': 5, 'delta': -3, 'percent': -37.5},
                         comparison['changes']['vertices'])
        # Measured: neither hand-written solid is closed with consistent winding, so trimesh
        # answers `is_volume` False. The 0 this used to record is a volume the file never had.
        self.assertEqual({'v1': None, 'v2': None, 'delta': None},
                         comparison['changes']['volume'])

        cloud_path = self.write('cmp_cloud.obj', POINT_CLOUD)
        first = engine.save_version(cloud_path, commit_message='cloud a')
        time.sleep(1.05)
        self.write('cmp_cloud.obj', POINT_CLOUD + 'v 2 2 2\n')
        second = engine.save_version(cloud_path, commit_message='cloud b')
        error = engine.compare_versions(first, second)['error']
        self.assertIn('hold no triangle mesh', error)
        self.assertNotIn('AttributeError', error)
        self.assertIn('holds no triangle mesh', engine.compare_versions(a, second)['error'])

    def test_10_the_comparison_table_shows_which_cell_is_not_a_number(self):
        data = {
            'version1': {'version_number': 1, 'timestamp': 'x', 'commit_message': 'a'},
            'version2': {'version_number': 2, 'timestamp': 'y', 'commit_message': 'b'},
            'changes': {
                'polygons': {'v1': 12, 'v2': 6, 'delta': -6, 'percent': -50.0},
                'vertices': {'v1': 8, 'v2': 5, 'delta': -3, 'percent': -37.5},
                'volume': {'v1': None, 'v2': 2.0, 'delta': None},
                'bounds': {'v1': [[0, 0, 0], [1, 1, 1]], 'v2': [[0, 0, 0], [2, 1, 1]]},
            },
        }
        # Both paths None keeps this dialog off the Open3D viewers it opens for a real
        # comparison; the table is what is being asked about here.
        dialog = VersionComparisonDialog(data, None, None)
        table = dialog.findChild(QTableWidget)
        self.assertIsNotNone(table, 'the comparison dialog shows no changes table')
        self.assertEqual('no faces to close', table.item(2, 1).text())
        self.assertEqual('2.0000', table.item(2, 2).text())
        self.assertEqual('no faces to close', table.item(2, 3).text())
        self.assertEqual('-6', table.item(0, 3).text())
        self.assertEqual('12', table.item(0, 1).text())
        dialog.deleteLater()

    def test_11_the_html_export_uses_the_same_words_as_the_pane(self):
        model = self.write('export.obj', CUBE)
        self.engine.save_version(model, commit_message='cube')
        time.sleep(1.05)
        self.write('export.obj', POINT_CLOUD)
        self.engine.save_version(model, commit_message='cloud')

        out = os.path.join(self.home, 'timeline.html')
        self.engine.export_version_timeline(model, out)
        with open(out, encoding='utf-8') as handle:
            html = handle.read()
        self.assertIn('<strong>Polygons:</strong> no faces', html)
        self.assertIn('<strong>Polygons:</strong> 12', html)
        self.assertIn('<strong>Vertices:</strong> 3', html)
        self.assertNotIn('<strong>Polygons:</strong> 0', html)
        self.assertNotIn('(+0)', html)

    def test_12_this_vocabulary_and_this_normaliser_live_in_one_module_each(self):
        definitions = []
        for directory in ('src', 'tests'):
            base = os.path.join(ROOT, directory)
            for folder, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for name in files:
                    if name.endswith('.py'):
                        relative = os.path.relpath(os.path.join(folder, name),
                                                   ROOT).replace(os.sep, '/')
                        text = read(os.path.join(folder, name))
                        if re.search(r'^def describe_(polygon_count|watertight|metrics|volume)',
                                     text, re.M):
                            definitions.append(relative)
        self.assertEqual(['src/features/version_control.py'], sorted(set(definitions)),
                         f'a second module has begun writing this vocabulary: {definitions}')

        backend = read(os.path.join(ROOT, 'src', 'features', 'version_control.py'))
        self.assertNotIn('concatenate', backend,
                         'the Versions backend normalises scenes itself again, which is a '
                         'second implementation of the read')
        self.assertIn('import as_trimesh', backend,
                      'the Versions backend no longer uses the app\'s one normaliser')
        self.assertNotIn('_as_trimesh',
                         read(os.path.join(ROOT, 'src', 'processing', 'format_converter.py')),
                         'the shared normaliser went private again')

        pane = read(os.path.join(ROOT, 'src', 'ui', 'version_control_ui.py'))
        for phrasing in ("f\"P: {version['polygon_count']", "{version['polygon_count']:,}",
                         "'✓ Yes' if version['is_watertight']"):
            self.assertNotIn(phrasing, pane,
                             f'the pane formats a count that can be None: {phrasing}')

    def test_13_the_integration_suite_has_to_prove_its_own_commit(self):
        run = subprocess.run(
            [sys.executable, '-X', 'utf8', os.path.join(ROOT, 'tests', 'test_full_flow.py')],
            capture_output=True, text=True, cwd=ROOT, timeout=300,
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'))
        self.assertEqual(0, run.returncode, run.stdout[-1500:] + run.stderr[-1500:])
        self.assertNotIn('❌', run.stdout, run.stdout[-1500:])
        self.assertIsNotNone(
            re.search(r'Committed version \d+: \d+ faces, \d+ vertices, 1 row', run.stdout),
            'the flow run no longer proves the commit it claims: ' + run.stdout[-1500:])
        self.assertNotIn('Committed version: None', run.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
