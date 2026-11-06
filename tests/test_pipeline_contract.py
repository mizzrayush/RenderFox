"""
Pipeline contract test - the graph on screen and the work behind it are one thing.

This suite exists because the pane used to be a drawing tool with a second engine inside it.
`PipelineEditorTab` built `PipelineEngine(job_manager)`, which is the constructor of a
different class in a different file: the pane was constructing the *old* engine, connecting
five signals that file does not emit, and pressing Run handed the graph to a scheduler that
knew nothing about nodes. Nothing on the canvas had ever run. The engine itself was worse
than unused - two of its node definitions were written with a comma where a colon belongs, so
importing the module raised SyntaxError, and its handlers called backend functions by names
that do not exist (`mesh_processor.remove_duplicate_vertices`, `pipeline.thumbnail`), so even
a correct pane would have died on the first node.

What is pinned here, in order:

* no knob is offered that its handler does not read, and no handler discards a knob
  (`unbacked_definitions`, and the pane builds a control for every one);
* every file a run reports is on disk with bytes in it, and every number in a row was
  measured back off that file;
* the four refusal kinds a person can type - folder where a file belongs, missing file,
  zero-byte file, and the three ways a *destination* can be wrong - are refused by name, and
  an extreme value is passed to the backend rather than clamped by the widget;
* the status vocabulary is the engine's (`STATUSES`), a stopped run says where it stopped and
  the nodes after it are `skipped`, and the pane's table cannot show a status that is not in
  that vocabulary;
* the graph's own rules - self-wire, duplicate wire, loop, wire to a node that is not there -
  are refused when the wire is drawn, with the names of the nodes on it;
* a pipeline file is loaded as it stands and reported on, never rewritten, and a saved
  pipeline is counted back off the disk before the pane says it was saved;
* the pane runs on a worker thread it holds by reference, refuses to start a second run, and
  hands the stop request to the node that is running.

Run: python -X utf8 tests/test_pipeline_contract.py
"""

import ast
import hashlib
import json
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

import open3d as o3d
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QDoubleSpinBox, QLineEdit, QMessageBox,
                             QComboBox, QCheckBox, QSpinBox, QLabel)

o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)

from src.processing import pipeline_engine as ENGINE
from src.processing.pipeline_engine import (
    NODE_DEFINITIONS, STATUSES, ParameterType, Pipeline, PipelineConnection,
    PipelineEngine, PipelineNode, definition_not_backed, load_pipeline,
    unbacked_definitions
)
from src.ui import pipeline_editor_tab as PANE
from src.ui.pipeline_editor_tab import (
    PipelineEditorTab, PipelineRunThread, PropertiesPanel, STATUS_COLORS
)
from src.utils.file_utils import get_temp_directory

# A modal dialog would stop a headless run forever: keep the words, drop the block.
MODALS = []


def _record_modal(kind):
    def show(*args, **kwargs):
        text = ' | '.join(str(argument) for argument in args[1:3])
        MODALS.append((kind, text))
        return 0
    return staticmethod(show)


QMessageBox.warning = _record_modal('warning')
QMessageBox.information = _record_modal('information')
QMessageBox.critical = _record_modal('critical')

TETRA = ('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n'
         'f 1 2 4\nf 1 2 3\nf 1 3 4\nf 2 3 4\n')

# Twelve faces, because a suite that only ever counts four cannot tell a measured number
# from a constant that happens to be right.
CUBE = ('v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nv 1 0 1\nv 1 1 1\nv 0 1 1\n'
        'f 1 2 3\nf 1 3 4\nf 5 7 6\nf 5 8 7\nf 1 5 6\nf 1 6 2\nf 2 6 7\nf 2 7 3\n'
        'f 3 7 8\nf 3 8 4\nf 4 8 5\nf 4 5 1\n')


def tetra(scale=1.0):
    """The same four faces at a different size, so a batch row has one sentence each."""
    return (f'v 0 0 0\nv {scale} 0 0\nv 0 {scale} 0\nv 0 0 {scale}\n'
            'f 1 2 4\nf 1 2 3\nf 1 3 4\nf 2 3 4\n')


def write_mesh(path, text=TETRA):
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return path


def write_cloud(path, count=400, seed=7):
    import numpy as np
    rng = np.random.default_rng(seed)
    cloud = o3d.utility.Vector3dVector(rng.random((count, 3)) * 2.0 - 1.0)
    o3d.io.write_point_cloud(path, o3d.geometry.PointCloud(cloud))
    return path


class Workspace:
    """One temp folder per test class, with the files the nodes are pointed at."""

    def __init__(self, name):
        self.root = tempfile.mkdtemp(prefix=f'renderfox_pipeline_{name}_')
        self.mesh = write_mesh(os.path.join(self.root, 'tetra.obj'))
        self.cube = write_mesh(os.path.join(self.root, 'cube.obj'), CUBE)
        self.cloud = write_cloud(os.path.join(self.root, 'scan.ply'))
        self.out = os.path.join(self.root, 'out')
        os.makedirs(self.out, exist_ok=True)

    def path(self, *parts):
        return os.path.join(self.root, *parts).replace('\\', '/')

    def batch(self, name, count):
        """A folder of `count` meshes that no other test has touched.

        Batch nodes report one step per file found, so a shared folder would make the
        count depend on which tests ran first. Each piece is a different size, because
        the note a batch row prints drops steps whose sentence is identical to one it
        already printed - six copies of one mesh is one sentence, not six.
        """
        folder = self.path(name)
        os.makedirs(folder, exist_ok=True)
        for index in range(count):
            write_mesh(os.path.join(folder, f'piece{index}.obj'), tetra(1.0 + index))
        return folder

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def build(workspace, spec):
    """`[(definition_id, knobs), ...]` plus `[(index, index), ...]` into a Pipeline."""
    pipeline = Pipeline(id='contract', name='Contract pipeline')
    nodes = []
    for position, (definition_id, knobs) in enumerate(spec['nodes']):
        node = PipelineNode(id=f'n{position}', definition_id=definition_id,
                            position=(position * 260.0, 0.0),
                            parameters=dict(knobs))
        ok, why = pipeline.add_node(node)
        assert ok, why
        nodes.append(node)
    for from_index, to_index in spec['wires']:
        ok, why = pipeline.add_connection(
            PipelineConnection(nodes[from_index].id, nodes[to_index].id))
        assert ok, why
    return pipeline


def run(workspace, spec, **kwargs):
    return PipelineEngine(staging_root=workspace.root).execute_pipeline(
        build(workspace, spec), **kwargs)


def rows_by_name(result):
    return {row['name']: row for row in result['nodes']}


def wait_for_tab(tab, limit=240.0):
    """Spin the Qt loop until the pane says its run answered, or say that it did not."""
    app = QApplication.instance()
    started = time.time()
    while tab._active_thread is not None and time.time() - started < limit:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return tab._active_thread is None


class EngineContract(unittest.TestCase):
    """The engine's own promises, run on the real backends."""

    @classmethod
    def setUpClass(cls):
        cls.ws = Workspace('engine')

    @classmethod
    def tearDownClass(cls):
        cls.ws.close()

    # ---- the knob vocabulary ----

    def test_01_no_definition_offers_a_knob_its_handler_does_not_read(self):
        found = unbacked_definitions()
        self.assertEqual([], found, 'nodes that would lie about a knob: ' + '; '.join(found))

    def test_02_every_definition_names_a_handler_that_exists(self):
        for definition in NODE_DEFINITIONS.values():
            with self.subTest(node=definition.id):
                self.assertTrue(ENGINE.handler_is_backed(definition.handler),
                                f'{definition.name} names {definition.handler}')

    def test_03_knob_types_are_all_read_by_the_engine(self):
        types = {param.type for definition in NODE_DEFINITIONS.values()
                 for param in definition.parameters}
        self.assertEqual(set(ParameterType), types,
                         f'a declared knob type no node uses: {set(ParameterType) - types}')

    # ---- what a run reports is on disk ----

    def test_04_a_done_run_reports_files_that_exist_and_measure_back(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('cube.obj')}),
                          ('transform.scale', {'factor': 2.0}),
                          ('export.model', {'output_path': self.ws.path('out', 'chain.obj'),
                                            'overwrite': True})],
                'wires': [(0, 1), (1, 2)]}
        result = run(self.ws, spec)
        self.assertEqual('done', result['status'], result['reason'])
        for row in result['nodes']:
            self.assertTrue(row['files'], f"{row['name']} said done and named no file")
            for path in row['files']:
                with self.subTest(file=os.path.basename(path)):
                    self.assertTrue(os.path.isfile(path), f'{path} is not on the disk')
                    self.assertGreater(os.path.getsize(path), 0, f'{path} holds no bytes')
        exported = self.ws.path('out', 'chain.obj')
        self.assertTrue(os.path.isfile(exported))
        measured = ENGINE.measure(exported, ENGINE.MESH)
        self.assertEqual(12, measured['faces'], str(measured))
        self.assertIn(f"{measured['faces']} faces", rows_by_name(result)['Export Model']['detail'])

    def test_05_row_status_words_are_the_ones_the_engine_declares(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('missing.obj')}),
                          ('export.model', {'output_path': self.ws.path('out', 'x.obj')})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        for row in result['nodes']:
            self.assertIn(row['status'], STATUSES, str(row))
        self.assertEqual(set(STATUSES), set(result['counts']),
                         f"counts missed a status: {set(STATUSES) ^ set(result['counts'])}")

    def test_06_status_colors_cover_the_whole_vocabulary(self):
        missing = [status for status in STATUSES if status not in STATUS_COLORS]
        self.assertEqual([], missing, f'statuses the pane has no colour for: {missing}')

    # ---- the four ways a source can be wrong ----

    def test_07_missing_file_is_refused_by_its_own_name(self):
        result = run(self.ws, {'nodes': [('input.load_model',
                                          {'file_path': self.ws.path('gone.obj')})],
                               'wires': []})
        row = result['nodes'][0]
        self.assertEqual('refused', row['status'], row['detail'])
        self.assertIn('is not a file on this disk', row['detail'])
        self.assertEqual([], result['files'], 'a refused load still reported files')

    def test_08_a_folder_where_a_file_belongs_is_refused_as_a_folder(self):
        result = run(self.ws, {'nodes': [('input.load_model',
                                          {'file_path': self.ws.path('out')})], 'wires': []})
        self.assertIn('is a folder', result['nodes'][0]['detail'])

    def test_09_a_zero_byte_file_is_refused_as_holding_no_bytes(self):
        empty = self.ws.path('empty.obj')
        with open(empty, 'w', encoding='utf-8') as handle:
            handle.write('')
        result = run(self.ws, {'nodes': [('input.load_model', {'file_path': empty})],
                               'wires': []})
        self.assertIn('holds no bytes', result['nodes'][0]['detail'])

    # ---- the three ways a destination can be wrong ----

    def test_10_destination_that_is_a_folder_is_refused(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('export.model', {'output_path': self.ws.path('out')})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        self.assertIn('is a folder, not the file to write into',
                      rows_by_name(result)['Export Model']['detail'])

    def test_11_destination_without_an_extension_is_refused(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('export.model', {'output_path': self.ws.path('out', 'noextension')})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        self.assertIn('has no extension', rows_by_name(result)['Export Model']['detail'])

    def test_12_destination_in_a_folder_that_is_not_there_is_refused(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('export.model',
                           {'output_path': self.ws.path('nowhere', 'deep.obj')})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        self.assertIn('has nowhere to be written', rows_by_name(result)['Export Model']['detail'])

    def test_13_extension_and_format_that_disagree_are_refused(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('export.model', {'output_path': self.ws.path('out', 'mixed.obj'),
                                            'format': 'stl', 'overwrite': True})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        self.assertIn('the two disagree', rows_by_name(result)['Export Model']['detail'])

    def test_14_an_image_format_on_a_mesh_node_is_refused_not_tried(self):
        for definition_id, knob, folder in (('export.model', 'output_path', 'out/impossible.exr'),
                                            ('export.batch', 'output_folder', 'out'),
                                            ('export.render', 'output_folder', 'out')):
            with self.subTest(node=definition_id):
                spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                                  (definition_id, {knob: self.ws.path(*folder.split('/')),
                                                   'format': 'exr'})],
                        'wires': [(0, 1)]}
                result = run(self.ws, spec)
                row = result['nodes'][-1]
                self.assertIn('exr', row['detail'].lower(), row['detail'])
                self.assertNotEqual('done', row['status'])

    # ---- extremes reach the backend, the widget does not gate them ----

    def test_15_a_factor_of_zero_is_answered_by_the_backend_not_clamped(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('transform.scale', {'factor': 0.0})], 'wires': [(0, 1)]}
        result = run(self.ws, spec)
        row = rows_by_name(result)['Scale']
        self.assertEqual('done', row['status'], row['detail'])
        measured = ENGINE.measure(row['files'][0], ENGINE.MESH)
        self.assertEqual([0.0, 0.0, 0.0], [round(value, 6) for value in measured['extents']],
                         str(measured))

    def test_16_a_ratio_the_filter_cannot_answer_is_refused_with_its_own_words(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('transform.decimate', {'method': 'ratio', 'ratio': 0.0})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        row = rows_by_name(result)['Decimate']
        self.assertNotIn('pane', row['detail'])
        self.assertIn(row['status'], ('refused', 'invalid', 'done'), row['detail'])

    # ---- the graph's own rules ----

    def test_17_self_wire_duplicate_wire_and_loop_are_named(self):
        pipeline = build(self.ws, {'nodes': [('input.load_model',
                                              {'file_path': self.ws.path('tetra.obj')}),
                                             ('export.stats',
                                              {'output_folder': self.ws.path('out')})],
                                   'wires': [(0, 1)]})
        first = pipeline.add_connection(PipelineConnection('n0', 'n0'))
        self.assertFalse(first[0])
        self.assertIn('feed itself', first[1])
        again = pipeline.add_connection(PipelineConnection('n0', 'n1'))
        self.assertEqual((False, 'that wire is already there'), again)
        loop = pipeline.add_connection(PipelineConnection('n1', 'n0'))
        self.assertFalse(loop[0])
        self.assertIn('close a loop', loop[1])
        self.assertEqual(1, len(pipeline.connections), 'a refused wire stayed in the graph')
        ghost = pipeline.add_connection(PipelineConnection('n0', 'nope'))
        self.assertIn('no node nope', ghost[1])

    def test_18_problems_names_everything_that_cannot_run(self):
        pipeline = Pipeline(id='p', name='Broken')
        accepted, why = pipeline.add_node(PipelineNode(id='a', definition_id='transform.scale'))
        self.assertTrue(accepted, why)
        self.assertFalse(pipeline.add_node(PipelineNode(id='b',
                                                        definition_id='not.a.real.node'))[0],
                         'the graph took a node type this build does not have')
        self.assertEqual(1, len(pipeline.nodes), 'a refused node stayed in the graph')
        problems = pipeline.problems()
        self.assertTrue(any('Scale has nothing on its wire' in text for text in problems),
                        str(problems))
        empty = Pipeline(id='e', name='Empty')
        self.assertEqual(['Empty has no nodes; double-click one in the palette on the left'],
                         empty.problems())

    def test_19_a_refusal_carries_the_wire_on_and_the_run_says_refused(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('transform.scale', {'factor': 2.0}),
                          ('export.model', {'output_path': self.ws.path('out', 'after.obj')})],
                'wires': [(0, 1), (1, 2)]}
        pipeline = build(self.ws, spec)
        pipeline.node_by_id('n2').parameters['output_path'] = self.ws.path('out')
        result = PipelineEngine(staging_root=self.ws.root).execute_pipeline(pipeline)
        self.assertEqual('refused', result['status'], result['reason'])
        self.assertIn('Export Model (refused)', result['reason'])
        self.assertEqual('done', rows_by_name(result)['Scale']['status'],
                         'a later refusal rewrote an earlier verdict')

    def test_20_stopping_names_where_it_stopped_and_skips_the_rest(self):
        folder = self.ws.batch('stop_batch', 10)
        spec = {'nodes': [('input.load_batch', {'folder_path': folder, 'patterns': '.obj'}),
                          ('transform.scale', {'factor': 1.5}),
                          ('export.batch', {'output_folder': self.ws.path('out'),
                                            'overwrite': True})],
                'wires': [(0, 1), (1, 2)]}
        seen = []

        def stop_now():
            seen.append(1)
            return len(seen) > 4

        result = run(self.ws, spec, should_cancel=stop_now)
        self.assertEqual('stopped', result['status'], result['reason'])
        self.assertIn('stopped at', result['reason'])
        statuses = [row['status'] for row in result['nodes']]
        self.assertIn('skipped', statuses, str(statuses))
        for row in result['nodes']:
            if row['status'] in ('stopped', 'skipped'):
                self.assertEqual([], row['files'], f"{row['name']} reported files it did not run")

    def test_21_the_same_pipeline_runs_in_the_same_order_twice(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('transform.scale', {'factor': 2.0}),
                          ('transform.center', {'mode': 'bounds'}),
                          ('export.model', {'output_path': self.ws.path('out', 'order.obj'),
                                            'overwrite': True})],
                'wires': [(0, 1), (1, 2), (2, 3)]}
        first = run(self.ws, spec)
        second = run(self.ws, spec)
        self.assertEqual('done', first['status'], first['reason'])
        self.assertEqual('done', second['status'], second['reason'])
        self.assertEqual([row['name'] for row in first['nodes']],
                         [row['name'] for row in second['nodes']])
        self.assertEqual([os.path.basename(path) for path in first['files']],
                         [os.path.basename(path) for path in second['files']],
                         'the same run produced differently named files the second time')

    def test_22_a_batch_note_stays_readable_and_keeps_every_step(self):
        folder = self.ws.batch('six', 6)
        spec = {'nodes': [('input.load_batch', {'folder_path': folder, 'patterns': '.obj'}),
                          ('transform.scale', {'factor': 3.0})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        row = rows_by_name(result)['Scale']
        self.assertEqual('done', row['status'], row['detail'])
        self.assertEqual(6, len(row['measured']['steps']),
                         'a step lost its own numbers')
        self.assertIn('further step(s)', row['detail'], row['detail'])
        self.assertLessEqual(row['detail'].count('extents'), 3, row['detail'])

    # ---- clouds, surfaces and the raster ----

    def test_23_a_cloud_verb_sends_only_its_own_knobs_and_says_so(self):
        spec = {'nodes': [('input.load_cloud', {'file_path': self.ws.path('scan.ply')}),
                          ('transform.process_cloud',
                           {'verb': 'outliers_statistical', 'nb_neighbors': 20,
                            'std_ratio': 2.0, 'output_folder': self.ws.path('out')})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        row = rows_by_name(result)['Process Point Cloud']
        self.assertEqual('done', row['status'], row['detail'])
        self.assertIn('outliers_statistical reads nb_neighbors, std_ratio', row['detail'])
        # The count of knobs it did NOT send is worked out from the backend's own table, so
        # the sentence cannot fall behind a verb that gains a knob.
        verb = 'outliers_statistical'
        taken = {value[0] if isinstance(value, tuple) else value
                 for value in ENGINE.CLOUD_VERB_KNOBS[verb].values()}
        other = set()
        for name, mapping in ENGINE.CLOUD_VERB_KNOBS.items():
            if name != verb:
                other |= {value[0] if isinstance(value, tuple) else value
                          for value in mapping.values()}
        expected = len(other - taken)
        self.assertIn(f'{expected} knob(s) of this node belong to other verbs and were not '
                      f'sent', row['detail'], row['detail'])
        named = row['detail'].split('were not sent (')[-1].rstrip(')')
        for knob in taken:
            self.assertNotIn(knob, named,
                             f'{knob} is read by {verb}, yet the note listed it as not sent')

    def test_24_a_surface_verb_hands_a_mesh_to_the_next_node(self):
        spec = {'nodes': [('input.load_cloud', {'file_path': self.ws.path('scan.ply')}),
                          ('transform.process_cloud',
                           {'verb': 'hull', 'output_folder': self.ws.path('out'),
                            'surface_format': '.obj'}),
                          ('export.model', {'output_path': self.ws.path('out', 'hull.obj'),
                                            'overwrite': True})],
                'wires': [(0, 1), (1, 2)]}
        result = run(self.ws, spec)
        self.assertEqual('done', result['status'], result['reason'])
        hull = rows_by_name(result)['Process Point Cloud']
        self.assertEqual('.obj', os.path.splitext(hull['files'][0])[1].lower(),
                         f"the surface verb was told .obj and handed on {hull['files'][0]}")
        self.assertEqual(ENGINE.MESH, hull['measured']['kind_after'],
                         'a surface verb left the wire a point cloud')
        exported = ENGINE.measure(self.ws.path('out', 'hull.obj'), ENGINE.MESH)
        self.assertGreater(exported['faces'], 0, str(exported))

    def test_25_the_render_writes_the_picture_it_counts(self):
        from PIL import Image
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('export.render', {'output_folder': self.ws.path('out', 'frames'),
                                             'resolution_x': 320, 'resolution_y': 240,
                                             'samples': 1})],
                'wires': [(0, 1)]}
        result = run(self.ws, spec)
        row = rows_by_name(result)['Render']
        self.assertEqual('done', row['status'], row['detail'])
        frame = row['measured']['frames'][0]
        picture = os.path.join(self.ws.path('out', 'frames'), frame['file'])
        self.assertTrue(os.path.isfile(picture), picture)
        with Image.open(picture) as opened:
            self.assertEqual([320, 240], [opened.width, opened.height], str(frame['size']))
        self.assertEqual([320, 240], frame['size'], 'the row reported a size the file is not')
        self.assertGreater(frame['coverage_percent'], 0, 'nothing was drawn on the picture')
        self.assertIn('the fitted default camera, because no Camera node ran', row['detail'])

    def test_26_the_default_camera_is_not_the_roll_fallback(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('input.camera', {'position': [0.0, 0.0, 4.0],
                                            'target': [0.0, 0.0, 0.0]}),
                          ('export.render', {'output_folder': self.ws.path('out', 'cam'),
                                             'resolution_x': 200, 'resolution_y': 200})],
                'wires': [(0, 2), (1, 2)]}
        result = run(self.ws, spec)
        row = rows_by_name(result)['Render']
        self.assertEqual('done', row['status'], row['detail'])
        self.assertNotIn('rolled', row['detail'], row['detail'])
        self.assertIn('Camera Setup', [node['name'] for node in result['nodes']])

    def test_27_a_camera_parallel_to_its_own_sight_says_the_frame_is_rolled(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('input.camera', {'position': [0.0, 0.0, 4.0],
                                            'target': [0.0, 0.0, 0.0],
                                            'up': [0.0, 0.0, 1.0]}),
                          ('export.render', {'output_folder': self.ws.path('out', 'roll'),
                                             'resolution_x': 200, 'resolution_y': 200})],
                'wires': [(0, 2), (1, 2)]}
        result = run(self.ws, spec)
        self.assertIn('rolled', rows_by_name(result)['Render']['detail'])

    def test_28_stats_writes_json_that_parses_back_with_the_same_counts(self):
        for spec_knob, file_key in (({'file_path': self.ws.path('tetra.obj')}, ENGINE.MESH),
                                    ({'file_path': self.ws.path('scan.ply')}, ENGINE.CLOUD)):
            definition = 'input.load_model' if file_key == ENGINE.MESH else 'input.load_cloud'
            spec = {'nodes': [(definition, spec_knob),
                              ('export.stats',
                               {'output_folder': self.ws.path('out', 'stats')})],
                    'wires': [(0, 1)]}
            result = run(self.ws, spec)
            row = rows_by_name(result)['Export Stats']
            self.assertEqual('done', row['status'], row['detail'])
            # The node keeps the incoming file on the wire, so the JSON it wrote is named in
            # its own numbers, not in the stream it passed on.
            written = row['measured']['files'][0]
            self.assertTrue(os.path.isfile(written), written)
            self.assertEqual('_stats.json', os.path.basename(written)[-11:], written)
            self.assertTrue(os.path.isfile(row['files'][0]),
                            'the model on the wire was swapped for the JSON')
            self.assertEqual(row['files'], result['nodes'][0]['files'],
                             'Export Stats changed the wire instead of reading it')
            with open(written, encoding='utf-8') as handle:
                payload = json.load(handle)
            self.assertEqual(file_key, payload['kind'], written)
            self.assertTrue(payload['geometry'], 'geometry was asked for and not counted')
            self.assertEqual(dict(payload['measured']),
                             ENGINE.measure(payload['file'], file_key),
                             'the JSON carried numbers that are not the file it names')

    def test_29_staging_survives_a_done_run_because_the_files_are_the_report(self):
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('transform.scale', {'factor': 2.0})], 'wires': [(0, 1)]}
        result = run(self.ws, spec)
        self.assertTrue(os.path.isdir(result['staging']), result['staging'])
        for path in result['files']:
            self.assertTrue(path.startswith(result['staging']) or os.path.isfile(path), path)
        self.assertNotIn('staging_removed', result)

    def test_29b_a_refusal_in_the_middle_leaves_the_next_node_s_work_intact(self):
        """A node that says no hands on what it was given, not an empty wire.

        Export Model is refused (its destination is a folder) and Export Stats after it
        still has the scaled mesh to count, so the row that says no is the only one blamed.
        """
        spec = {'nodes': [('input.load_model', {'file_path': self.ws.path('tetra.obj')}),
                          ('transform.scale', {'factor': 4.0}),
                          ('export.model', {'output_path': self.ws.path('out')}),
                          ('export.stats', {'output_folder': self.ws.path('out', 'carry')})],
                'wires': [(0, 1), (1, 2), (2, 3)]}
        result = run(self.ws, spec)
        rows = rows_by_name(result)
        self.assertEqual('refused', rows['Export Model']['status'],
                         rows['Export Model']['detail'])
        self.assertEqual([], rows['Export Model']['files'],
                         'a refused node reported files')
        self.assertEqual('done', rows['Export Stats']['status'], rows['Export Stats']['detail'])
        self.assertEqual(rows['Scale']['files'], rows['Export Stats']['files'],
                         'the mesh after the refusal is not the one Scale wrote')
        self.assertEqual(4.0, round(ENGINE.measure(rows['Export Stats']['files'][0],
                                                   ENGINE.MESH)['extents'][0], 4),
                         'the carried-on file is not the scaled one')
        self.assertEqual('refused', result['status'], result['reason'])
        self.assertIn('Export Model (refused)', result['reason'])
        self.assertEqual(1, result['counts']['refused'], str(result['counts']))
        self.assertEqual(0, result['counts']['failed'], str(result['counts']))

    # ---- pipelines on disk ----

    def test_30_a_saved_pipeline_is_counted_back_off_the_file(self):
        pipeline = build(self.ws, {'nodes': [('input.load_model',
                                              {'file_path': self.ws.path('tetra.obj')}),
                                             ('transform.scale', {'factor': 1.5})],
                                   'wires': [(0, 1)]})
        saved = self.ws.path('out', 'saved.json')
        ok, why = ENGINE.save_pipeline(pipeline, saved)
        self.assertTrue(ok, why)
        loaded, warnings = load_pipeline(saved)
        self.assertEqual([], warnings, str(warnings))
        self.assertEqual(2, len(loaded.nodes))
        self.assertEqual(1.5, loaded.nodes[1].parameters['factor'])

    def test_31_saving_into_a_folder_that_is_not_there_is_reported_not_claimed(self):
        pipeline = build(self.ws, {'nodes': [('input.load_model',
                                              {'file_path': self.ws.path('tetra.obj')})],
                                   'wires': []})
        ok, why = ENGINE.save_pipeline(pipeline, self.ws.path('no_such_folder', 'p.json'))
        self.assertTrue(ok, 'a missing parent folder is creatable, so this should save')
        ok2, why2 = ENGINE.save_pipeline(pipeline, self.ws.path('out'))
        self.assertFalse(ok2, why2)
        self.assertIn('was not written', why2)

    def test_32_a_damaged_file_is_loaded_as_it_stands_and_every_damage_is_named(self):
        saved = self.ws.path('out', 'damaged_src.json')
        pipeline = build(self.ws, {'nodes': [('input.load_model',
                                              {'file_path': self.ws.path('tetra.obj')}),
                                             ('transform.scale', {'factor': 2.0})],
                                   'wires': [(0, 1)]})
        ENGINE.save_pipeline(pipeline, saved)
        with open(saved, encoding='utf-8') as handle:
            data = json.load(handle)
        data['node_schema'] = 'old-1'
        data['nodes'].append({'id': 'n1', 'definition_id': 'transform.scale',
                              'position': [0, 0],
                              'parameters': {'legacy_strength': 3, 'factor': 2.0}})
        data['nodes'].append({'id': 'n9', 'definition_id': 'transform.longlost',
                              'position': [0, 0], 'parameters': {}})
        data['connections'].append({'from': 'n9', 'to': 'n0'})
        data['connections'].append({'from': 'ghost', 'to': 'n0'})
        broken = self.ws.path('out', 'damaged.json')
        with open(broken, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)

        def digest():
            with open(broken, 'rb') as handle:
                return hashlib.sha256(handle.read()).hexdigest()

        before = digest()
        loaded, warnings = load_pipeline(broken)
        self.assertIsNotNone(loaded)
        self.assertEqual(before, digest(), 'loading rewrote the file')
        kinds = ' || '.join(warnings)
        self.assertIn('older node set', kinds)
        self.assertIn('two nodes are both called n1', kinds)
        self.assertIn('transform.longlost', kinds)
        self.assertIn('legacy_strength', kinds)
        self.assertIn('a wire starts at ghost, which is not in this pipeline', kinds)
        self.assertEqual(2.0, loaded.nodes[1].parameters['factor'],
                         'a loaded knob was adjusted on the way in')
        self.assertIn('n9', [node.id for node in loaded.nodes],
                       'a node this build does not know was dropped on the way in')

    def test_33_a_file_that_is_not_a_pipeline_says_which_key_it_lost(self):
        damaged = self.ws.path('out', 'half.json')
        with open(damaged, 'w', encoding='utf-8') as handle:
            json.dump({'id': 'x', 'name': 'x', 'nodes': [{'id': 'a', 'definition_id':
                                                          'transform.scale'}],
                       'connections': [{'from': 'a'}]}, handle)
        pipeline, warnings = load_pipeline(damaged)
        self.assertIsNone(pipeline)
        self.assertIn('missing', warnings[0])
        self.assertIn("'to'", warnings[0], warnings[0])
        notjson = self.ws.path('out', 'notjson.json')
        with open(notjson, 'w', encoding='utf-8') as handle:
            handle.write('this is not json at all')
        pipeline, warnings = load_pipeline(notjson)
        self.assertIsNone(pipeline)
        self.assertIn('does not read as a pipeline file', warnings[0])


class PaneContract(unittest.TestCase):
    """The pane: a control for every knob, and the engine's own answers on screen."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.ws = Workspace('pane')

    @classmethod
    def tearDownClass(cls):
        cls.ws.close()

    def setUp(self):
        MODALS.clear()
        self.tab = PipelineEditorTab()
        self.tab.resize(1280, 800)
        self.tab.show()
        self.app.processEvents()

    def tearDown(self):
        deadline = time.time() + 60
        while self.tab._workers and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.tab.close()
        self.app.processEvents()

    def add(self, definition_id, knobs=None):
        node_id = self.tab.add_node_from_palette(definition_id, knobs or {})
        self.assertIsNotNone(node_id, f'{definition_id} refused to be added')
        return node_id

    def wire(self, from_id, to_id):
        self.tab.on_connection_created(from_id, to_id)

    def run_and_wait(self, limit=240.0):
        started = len(self.tab._workers)
        self.tab.run_pipeline()
        self.assertTrue(wait_for_tab(self.tab, limit), 'the run never answered')
        deadline = time.time() + 30
        while len(self.tab._workers) > started and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.005)

    def table(self):
        return {self.tab.results_table.item(row, 1).text():
                (self.tab.results_table.item(row, 2).text(),
                 self.tab.results_table.item(row, 3).text())
                for row in range(self.tab.results_table.rowCount())}

    # ---- controls ----

    def test_40_every_knob_of_every_node_type_gets_a_widget(self):
        self.tab.new_pipeline()
        missing = []
        for definition_id, definition in NODE_DEFINITIONS.items():
            node_id = self.add(definition_id)
            for param in definition.parameters:
                if param.name not in self.tab.properties.widgets:
                    missing.append(f'{definition.name}.{param.name}')
        self.assertEqual([], missing, 'knobs with no control: ' + ', '.join(missing))

    def test_41_the_palette_lists_every_definition_exactly_once(self):
        listed = []
        for group, listing in self.tab.palette.groups:
            for row in range(listing.count()):
                listed.append(listing.item(row).data(Qt.ItemDataRole.UserRole))
        self.assertEqual(len(listed), len(NODE_DEFINITIONS),
                         f'{len(listed)} rows for {len(NODE_DEFINITIONS)} nodes')
        self.assertEqual(sorted(str(item) for item in listed),
                         sorted(NODE_DEFINITIONS), 'the palette and the engine disagree')

    def test_42_a_number_box_passes_the_extreme_it_was_given(self):
        node_id = self.add('transform.scale', {'factor': 2.0})
        self.tab.on_node_selected(node_id)
        box = self.tab.properties.widgets['factor']
        self.assertIsInstance(box, QDoubleSpinBox)
        self.assertGreaterEqual(box.maximum(), 1e12, 'the box caps what the backend can answer')
        box.setValue(1e9)
        self.assertEqual(1e9, self.tab.pipeline.node_by_id(node_id).parameters['factor'])
        box.setValue(-1e9)
        self.assertEqual(-1e9, self.tab.pipeline.node_by_id(node_id).parameters['factor'])

    def test_43_a_count_box_takes_a_number_far_beyond_its_node_s_hint(self):
        node_id = self.add('transform.decimate', {'method': 'count', 'target_count': 100})
        self.tab.on_node_selected(node_id)
        box = self.tab.properties.widgets['target_count']
        self.assertIsInstance(box, QSpinBox)
        box.setValue(2_000_000_000)
        self.assertEqual(2_000_000_000,
                         self.tab.pipeline.node_by_id(node_id).parameters['target_count'])

    def test_44_vector_and_colour_knobs_round_trip_their_own_types(self):
        camera = self.add('input.camera')
        self.tab.on_node_selected(camera)
        host = self.tab.properties.widgets['position']
        boxes = host.findChildren(QDoubleSpinBox)
        self.assertEqual(3, len(boxes), 'a vector knob is not three boxes')
        boxes[0].setValue(-1234.5)
        boxes[2].setValue(7.0)
        self.app.processEvents()
        self.assertEqual([-1234.5, 0.0, 7.0],
                          self.tab.pipeline.node_by_id(camera).parameters['position'])

        render = self.add('export.render')
        self.tab.on_node_selected(render)
        line = self.tab.properties.widgets['background'].findChild(QLineEdit)
        line.setText('#00FF00')
        self.assertEqual('#00FF00',
                         self.tab.pipeline.node_by_id(render).parameters['background'])
        line.setText('not a colour')
        self.assertEqual('not a colour',
                         self.tab.pipeline.node_by_id(render).parameters['background'],
                         'the widget fixed the value instead of letting the run refuse it')

    def test_45_an_enum_box_only_offers_what_the_node_has(self):
        node_id = self.add('transform.process_cloud', {'verb': 'voxel'})
        self.tab.on_node_selected(node_id)
        box = self.tab.properties.widgets['verb']
        self.assertIsInstance(box, QComboBox)
        self.assertEqual(list(ENGINE.CLOUD_VERBS),
                         [box.itemText(index) for index in range(box.count())])

    def test_46_a_knob_no_handler_reads_is_shown_and_reachable(self):
        node_id = self.add('transform.scale', {'factor': 2.0})
        node = self.tab.pipeline.node_by_id(node_id)
        node.parameters['legacy_strength'] = 3
        self.tab.on_node_selected(node_id)
        labels = [label.text() for label in
                  self.tab.properties.form_host.findChildren(QLabel)]
        self.assertTrue(any('legacy_strength' in text for text in labels), str(labels)[:400])
        self.tab.properties.remove_stale('legacy_strength')
        self.assertNotIn('legacy_strength', node.parameters)

    def test_47_the_pane_builds_no_work_of_its_own(self):
        path = os.path.join(ROOT, 'src', 'ui', 'pipeline_editor_tab.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        for banned in ('open3d', 'pymeshlab', 'trimesh', 'PIL', 'numpy'):
            self.assertFalse([name for name in imports if name.split('.')[0] == banned],
                             f'the pane imports {banned}, so it can compute something the '
                             f'engine never reported')
        self.assertTrue([name for name in imports if name.endswith('pipeline_engine')],
                        f'the pane does not import the engine it shows: {sorted(imports)}')

    def test_48_the_pane_paints_flat_and_uses_no_emoji(self):
        path = os.path.join(ROOT, 'src', 'ui', 'pipeline_editor_tab.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        for banned in ('QLinearGradient', 'QRadialGradient', 'setGraphicsEffect',
                       'QGraphicsDropShadowEffect'):
            self.assertNotIn(banned, source, f'{banned} is still in the pane')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for character in node.value:
                    self.assertFalse(0x1F000 <= ord(character) <= 0x1FAFF,
                                     f'emoji in a string: {node.value[:40]!r}')

    # ---- the run, on screen ----

    def test_50_a_real_run_fills_the_table_with_the_engine_s_rows(self):
        self.add('input.load_model', {'file_path': self.ws.path('tetra.obj')})
        scale = self.add('transform.scale', {'factor': 2.0})
        self.add('export.model', {'output_path': self.ws.path('out', 'pane.obj'),
                                  'overwrite': True})
        nodes = self.tab.pipeline.nodes
        self.wire(nodes[0].id, nodes[1].id)
        self.wire(nodes[1].id, nodes[2].id)
        direct = PipelineEngine(staging_root=self.ws.root).execute_pipeline(
            self.tab.pipeline, keep_staging=True)
        self.run_and_wait()
        table = self.table()
        self.assertEqual({'Load Model', 'Scale', 'Export Model'}, set(table), str(table))
        for row in direct['nodes']:
            self.assertEqual(row['status'], table[row['name']][0],
                             f"{row['name']}: the table said {table[row['name']][0]!r}, the "
                             f"engine said {row['status']!r}")
        self.assertTrue(os.path.isfile(self.ws.path('out', 'pane.obj')))
        self.assertTrue(self.tab.summary_label.text().startswith('done'),
                        self.tab.summary_label.text())

    def test_51_node_borders_take_the_status_the_run_reported(self):
        self.add('input.load_model', {'file_path': self.ws.path('nothing_here.obj')})
        self.add('export.stats', {'output_folder': self.ws.path('out', 's1')})
        nodes = self.tab.pipeline.nodes
        self.wire(nodes[0].id, nodes[1].id)
        self.run_and_wait()
        self.assertEqual('refused', self.tab.view.node_items[nodes[0].id].status)
        self.assertEqual('refused', self.table()['Load Model'][0])
        self.assertIn('is not a file on this disk', self.table()['Load Model'][1])
        self.assertTrue(self.tab.summary_label.text().startswith('refused'),
                        self.tab.summary_label.text())
        self.assertEqual([], MODALS, 'a refusal is not a crash, so no crash dialog is owed')

    def test_52_the_pane_refuses_a_graph_it_cannot_run_before_starting_a_thread(self):
        self.add('transform.scale')
        self.tab.run_pipeline()
        self.assertIsNone(self.tab._active_thread)
        self.assertIn('Scale has nothing on its wire', self.tab.summary_label.text())
        self.assertEqual(0, self.tab.results_table.rowCount(), 'a refused start wrote rows')

    def test_53_a_second_run_is_refused_while_one_is_running(self):
        folder = self.ws.batch('guard_batch', 12)
        self.add('input.load_batch', {'folder_path': folder, 'patterns': '.obj'})
        self.add('export.batch', {'output_folder': self.ws.path('out', 'guard'),
                                  'overwrite': True})
        nodes = self.tab.pipeline.nodes
        self.wire(nodes[0].id, nodes[1].id)
        self.tab.run_pipeline()
        self.assertIsNotNone(self.tab._active_thread)
        first = self.tab._active_thread
        self.tab.run_pipeline()
        self.assertIs(first, self.tab._active_thread, 'a second worker replaced the first')
        self.assertIn('already in progress', self.tab.log_output.toPlainText())
        self.tab.stop_pipeline()
        self.assertTrue(wait_for_tab(self.tab, 180.0))

    def test_54_stop_lands_on_the_running_node_and_the_pane_opens_again(self):
        folder = self.ws.batch('stop_batch', 12)
        self.add('input.load_batch', {'folder_path': folder, 'patterns': '.obj'})
        self.add('export.batch', {'output_folder': self.ws.path('out', 'stopped'),
                                  'overwrite': True})
        nodes = self.tab.pipeline.nodes
        self.wire(nodes[0].id, nodes[1].id)
        self.tab.run_pipeline()
        thread = self.tab._active_thread
        deadline = time.time() + 60
        while thread is not None and len(thread.engine.files) < 1 and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.tab.stop_pipeline()
        self.assertTrue(wait_for_tab(self.tab, 180.0), 'the stopped run never answered')
        statuses = [value[0] for value in self.table().values()]
        self.assertTrue('stopped' in statuses or 'skipped' in statuses, str(statuses))
        self.assertTrue(self.tab.run_btn.isEnabled(), 'Run stayed greyed after the stop')
        self.assertFalse(self.tab.stop_btn.isEnabled())
        self.app.processEvents()

    def test_55_a_worker_is_held_until_it_says_it_finished(self):
        self.add('input.load_model', {'file_path': self.ws.path('tetra.obj')})
        self.add('export.stats', {'output_folder': self.ws.path('out', 'held')})
        nodes = self.tab.pipeline.nodes
        self.wire(nodes[0].id, nodes[1].id)
        self.tab.run_pipeline()
        held = list(self.tab._workers)
        self.assertEqual(1, len(held), str(held))
        self.assertTrue(wait_for_tab(self.tab, 120.0))
        deadline = time.time() + 30
        while self.tab._workers and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertEqual([], [thread for thread in held if thread.isRunning()],
                          'a released thread was still running')

    def test_56_the_table_flags_a_status_the_engine_does_not_report(self):
        row = self.tab._row_for('x1', 'Imaginary Node')
        self.tab._write_row(row, 'wonderful', 'pretended it ran')
        shown = self.tab.results_table.item(row, 2).text()
        self.assertIn('not a status the engine reports', shown, shown)

    def test_57_positions_and_wires_survive_a_save_and_reload(self):
        from src.ui.pipeline_editor_tab import PipelineEditorTab as Pane
        first = self.add('input.load_model', {'file_path': self.ws.path('tetra.obj')})
        second = self.add('transform.scale', {'factor': 2.5})
        self.wire(first, second)
        self.tab.view.node_items[first].setPos(412.0, 233.0)
        self.app.processEvents()
        saved = self.ws.path('out', 'layout.json')
        self.assertTrue(self.tab.save_pipeline_to_file(saved), 'the pane claimed a failed save')
        reloaded, warnings = load_pipeline(saved)
        self.assertEqual([], warnings, str(warnings))
        moved = reloaded.node_by_id(first)
        self.assertEqual((412.0, 233.0), tuple(moved.position), str(moved.position))
        self.assertEqual(1, len(reloaded.connections))
        other = Pane()
        other.show()
        other.pipeline = reloaded
        other.file_path = saved
        other.refresh_view()
        self.app.processEvents()
        self.assertEqual(412.0, other.view.node_items[first].pos().x())
        self.assertEqual(2.5, other.pipeline.node_by_id(second).parameters['factor'])
        other.close()

    def test_58_a_file_handed_over_by_the_library_becomes_a_load_node(self):
        self.tab.accept_model_file(self.ws.path('tetra.obj'))
        node = self.tab.pipeline.nodes[-1]
        self.assertEqual('input.load_model', node.definition_id)
        self.assertEqual(self.ws.path('tetra.obj'), node.parameters['file_path'])
        self.tab.accept_model_file(self.ws.path('scan.ply'))
        self.assertEqual('input.load_model', self.tab.pipeline.nodes[-1].definition_id,
                         'a .ply was routed to the cloud node; the Library holds meshes')

    def test_59_the_run_thread_carries_the_engine_and_its_own_staging(self):
        thread = PipelineRunThread(self.tab.pipeline)
        self.assertIsInstance(thread.engine, PipelineEngine)
        self.assertEqual(os.path.abspath(get_temp_directory()),
                         os.path.abspath(thread.engine.staging_root),
                         f"staging is at {thread.engine.staging_root}, not the app's temp folder")

    def test_60_the_pane_hands_no_dialog_a_verdict_it_cannot_back(self):
        """A crash row is the only case allowed to open a modal, and it names the file."""
        node_id = self.add('input.load_model', {'file_path': self.ws.path('tetra.obj')})
        export = self.add('export.model', {'output_path': self.ws.path('out', 'knob.obj'),
                                           'overwrite': True})
        self.wire(node_id, export)
        self.tab.pipeline.node_by_id(export).parameters['format'] = 'tifff'
        self.run_and_wait(120.0)
        statuses = {name: value[0] for name, value in self.table().items()}
        self.assertEqual('invalid', statuses['Export Model'], str(statuses))
        self.assertIn('tifff', self.table()['Export Model'][1], self.table()['Export Model'][1])
        self.assertEqual([], [kind for kind, _ in MODALS],
                         'a knob read wrong opened a dialog as if the run had crashed')

    def test_60b_a_destination_that_cannot_be_written_is_refused_not_dialogued(self):
        node_id = self.add('input.load_model', {'file_path': self.ws.path('tetra.obj')})
        export = self.add('export.model', {'output_path': self.ws.path('out', 'digits.obj')})
        self.wire(node_id, export)
        self.tab.pipeline.node_by_id(export).parameters['output_path'] = 3
        self.run_and_wait(120.0)
        row = self.table()['Export Model']
        self.assertEqual('refused', row[0], str(row))
        self.assertIn('extension', row[1], row[1])
        self.assertEqual([], [kind for kind, _ in MODALS],
                         'the pane turned the engine\'s no into a dialog')


if __name__ == '__main__':
    unittest.main(verbosity=2)
