"""
Pre-Processing pane contract test.

Every control in the pane is driven through the real widget path and has to leave a
file, a count or an honest sentence behind. This suite exists because the pane used to
answer with a Yes/No list of which boxes were ticked, four Cancel buttons wired to
nothing, and an extraction run that raised TypeError on any textured part - all of
which the older headless suite passed, since it wrapped each call in `if hasattr(...)`
and asserted nothing about the result.

Run: python -X utf8 tests/test_preprocessing_contract.py
"""

import os
import re
import shutil
import sys
import tempfile
import time
import traceback
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import trimesh
from PIL import Image

from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.processing import texture_baker as BAKER_MODULE
from src.processing import format_converter as CONVERTER
from src.processing.format_converter import FormatConverter, SupportedFormat
from src.processing.model_extractor import ModelExtractor, get_extraction_methods_info
from src.processing.scene_optimizer import SceneReport
from src.processing.texture_baker import TextureBaker
from src.processing.texture_optimizer import (FORMAT_CHOICES, TextureOptimizer,
                                              available_formats)
from src.ui import preprocessing_tab as PANE
from src.ui.preprocessing_tab import (FormatConversionThread, OptimizationThread,
                                      PreProcessingTab)

PANE_SOURCE = open(os.path.join(ROOT, 'src', 'ui', 'preprocessing_tab.py'),
                   encoding='utf-8').read()

CORNER = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
TWO_FACES = np.array([[0, 1, 2], [1, 2, 3]], dtype=np.int64)
NO_FACES = np.zeros((0, 3), dtype=np.int64)
REAL_OBJ = os.path.join(ROOT, 'tests', 'test_data', 'test_sphere.obj')

APP = QApplication.instance() or QApplication(sys.argv)

SLOT_FAULTS = []


def _keep_slot_fault(kind, value, trace):
    """PyQt6 aborts the process on an exception raised inside a slot, so a defect that
    bites there would kill the run before unittest printed a single FAIL line. Keep the
    fault and let the test that was running name it."""
    SLOT_FAULTS.append(''.join(traceback.format_exception(kind, value, trace)))


sys.excepthook = _keep_slot_fault

RNG = np.random.default_rng(7)


def photo(size):
    return Image.fromarray(RNG.integers(0, 255, (size, size, 3), dtype=np.uint8))


def textured_box(size, name, offset):
    box = trimesh.creation.box(extents=(1, 1, 1))
    box.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=photo(size),
                                                     name=name))
    box.apply_translation(offset)
    return box


def write_textured_scene(folder, name='hero.glb'):
    """Two parts, two distinct textures, one .glb - the asset shape the pane is fed."""
    path = os.path.join(folder, name)
    trimesh.Scene([textured_box(256, 'skin', (0, 0, 0)),
                   textured_box(192, 'metal', (4, 0, 0))]).export(path)
    return path


def write_mesh_only_file(folder):
    """A mesh a reader here opens as one lump: PyMeshLab reads .ctm, trimesh has no
    scene reader for it, so extraction is handed a Trimesh instead of a Scene."""
    import pymeshlab
    path = os.path.join(folder, 'lump.ctm')
    mesh_set = pymeshlab.MeshSet()
    mesh_set.load_new_mesh(os.path.join(ROOT, 'tests', 'test_data', 'test_sphere.obj'))
    mesh_set.save_current_mesh(path)
    return path


def write_tetrahedron(folder):
    """Four faces, the coarsest part a scene can hold - what a clustering parameter has to
    keep whole. `min_samples=5` makes every one of the four a noise point, because a face
    centre has three neighbours and not five."""
    path = os.path.join(folder, 'tetra.stl')
    trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                   faces=[[0, 1, 2], [1, 2, 3], [0, 2, 3], [0, 1, 3]],
                   process=False).export(path)
    return path


class StubTrimesh:
    """The `trimesh` the reader's first branch sees: only `load` is replaced.

    The same function builds its fallback meshes with `trimesh.Trimesh` a few lines later,
    so the rest of the module has to stay the real one.
    """

    def __init__(self, loaded=None, error=None):
        self._real = trimesh
        self.loaded, self.error = loaded, error

    def load(self, path):
        if self.error is not None:
            raise self.error
        return self.loaded

    def __getattr__(self, name):
        return getattr(self._real, name)


class StubMeshSet:
    """PyMeshLab's mesh set, answering with the arrays it was given."""

    def __init__(self, vertices, faces):
        self.vertices, self.faces = vertices, faces

    def load_new_mesh(self, path):
        pass

    def mesh_number(self):
        return 1

    def current_mesh(self):
        return self

    def face_number(self):
        return len(self.faces)

    def vertex_matrix(self):
        return self.vertices

    def face_matrix(self):
        return self.faces


class StubPyMeshLab:
    def __init__(self, vertices, faces):
        self.args = (vertices, faces)

    def MeshSet(self):
        return StubMeshSet(*self.args)


class StubAssimpMesh:
    def __init__(self, vertices, faces):
        self.vertices, self.faces = vertices, faces


class StubAssimpScene:
    def __init__(self, meshes):
        self.meshes = meshes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StubAssimp:
    def __init__(self, meshes):
        self.meshes = meshes

    def load(self, path):
        return StubAssimpScene(self.meshes)


class OnlyReader:
    """Leave one branch of `read_mesh` as the only reader that can answer, reading through
    a stub that hands back the arrays it is given.

    The branches are tried in order, so no real file can reach the second or the third -
    a stub is the only way to ask each of them whether it checks its own result.
    """

    NAMES = ('trimesh', 'pymeshlab', 'pyassimp', 'TRIMESH_AVAILABLE',
             'PYMESHLAB_AVAILABLE', 'ASSIMP_AVAILABLE')

    def __init__(self, library, vertices, faces):
        self.library, self.vertices, self.faces = library, vertices, faces
        self.saved = {}

    def _settings(self):
        passed_on = StubTrimesh(error=ValueError('stubbed away'))
        if self.library == 'trimesh':
            return {'trimesh': StubTrimesh(loaded=trimesh.Trimesh(
                vertices=self.vertices, faces=self.faces, process=False)),
                'PYMESHLAB_AVAILABLE': False, 'ASSIMP_AVAILABLE': False}
        if self.library == 'pymeshlab':
            return {'trimesh': passed_on, 'pymeshlab': StubPyMeshLab(
                self.vertices, self.faces), 'ASSIMP_AVAILABLE': False}
        return {'trimesh': passed_on, 'PYMESHLAB_AVAILABLE': False,
                'pyassimp': StubAssimp([StubAssimpMesh(self.vertices, self.faces)])}

    def __enter__(self):
        for name in self.NAMES:
            self.saved[name] = getattr(CONVERTER, name)
        for name, value in self._settings().items():
            setattr(CONVERTER, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(CONVERTER, name, value)
        return False


def wipe(folder):
    shutil.rmtree(folder, ignore_errors=True)


class RecordingDialogs:
    """Modal dialogs become data, so a refusal can be asserted instead of clicked away."""

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

    def texts(self):
        return ' | '.join(text for _, _, text in self.messages)


DIALOGS = RecordingDialogs()
DIALOGS.install()


class StalledWorkers:
    """Replace real workers with subclasses whose run() does nothing.

    Used to pull a dialog's Cancel and see whether it reached the thread. The stub keeps
    every signal, constructor argument and `request_stop` of the class it stands in for,
    so a missing connection shows up as a flag that never set - not as a missing method.
    """

    def __init__(self, names):
        self.names = names
        self.originals = {}

    def __enter__(self):
        for name in self.names:
            original = getattr(PANE, name)
            self.originals[name] = original

            def build(base=original):
                class Stalled(base):
                    def run(self):
                        pass
                return Stalled

            setattr(PANE, name, build())
        return self

    def __exit__(self, *exc):
        for name, original in self.originals.items():
            setattr(PANE, name, original)
        return False


class ExtractionBackend(unittest.TestCase):
    """The extractor is the pane's only route into a file, so it is settled first."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='pre_contract_')
        cls.scene = write_textured_scene(cls.work)
        cls.lump = write_mesh_only_file(cls.work)
        # What each fixture holds, counted straight from the reader the app uses, so the
        # face-conservation test below compares against the file rather than a guess.
        cls.scene_faces = sum(len(mesh.faces)
                              for mesh in trimesh.load(cls.scene).geometry.values())
        cls.lump_faces = len(FormatConverter().read_mesh(cls.lump)[0].faces)
        cls.tetra = write_tetrahedron(cls.work)
        cls.tetra_faces = 4

    @classmethod
    def tearDownClass(cls):
        wipe(cls.work)

    def setUp(self):
        self.extractor = ModelExtractor()
        del SLOT_FAULTS[:]

    def tearDown(self):
        self.assertEqual(SLOT_FAULTS, [], f'a slot raised: {SLOT_FAULTS}')

    def extract(self, path, min_faces, method, **kwargs):
        """The pane's own call, with the counts it publishes beside the models."""
        models = self.extractor.extract_from_scene(path, min_faces, method, **kwargs)
        return models, self.extractor.summary

    def test_one_reader_and_a_named_refusal_for_the_rest(self):
        blocker = os.path.join(self.work, 'thing.xyz')
        with open(blocker, 'w', encoding='utf-8') as handle:
            handle.write('not a model\n')
        with self.assertRaises(ValueError) as caught:
            self.extractor.read_source(blocker)
        reason = str(caught.exception)
        self.assertIn('thing.xyz', reason)
        self.assertIn('as a scene', reason)
        self.assertIn('as one mesh', reason)
        # A text file stopped being a mesh because PyMeshLab can hand back one vertex
        # and no faces; that read has to be a refusal, not an empty pipeline run.
        mesh, note = FormatConverter().read_mesh(blocker)
        self.assertIsNone(mesh, note)

    def test_no_reader_branch_calls_a_faceless_read_a_mesh(self):
        """A mesh here means faces, in every branch, not only in the one that bit it.

        PyMeshLab reads a text file as one vertex and no faces and a point cloud is exactly
        that; a branch returning it reports a successful read and the pipeline writes an
        empty file.
        """
        for library in ('trimesh', 'pymeshlab', 'assimp'):
            with OnlyReader(library, CORNER, NO_FACES):
                mesh, note = FormatConverter().read_mesh(REAL_OBJ)
            self.assertIsNone(mesh, f'{library} read a faceless result as a mesh: {note}')
            self.assertIn('no faces', note, f'{library}: {note}')

    def test_a_reader_branch_still_accepts_the_faces_it_was_given(self):
        """The control for the test above: the stub is not simply refusing everything."""
        for library in ('trimesh', 'pymeshlab', 'assimp'):
            with OnlyReader(library, CORNER, TWO_FACES):
                mesh, note = FormatConverter().read_mesh(REAL_OBJ)
            self.assertIsNotNone(mesh, f'{library} refused the faces it was given: {note}')
            self.assertEqual(note, library, f'{library}: {note}')

    def test_a_textured_scene_survives_extraction(self):
        # The defect this guards: `len(mesh.visual.material)` raised TypeError for any
        # textured part, so a real asset returned no rows at all.
        models, stats = self.extract(self.scene, 10, 'connected_components')
        self.assertEqual(len(models), 2, [model.name for model in models])
        self.assertEqual((stats['parts'], stats['kept'], stats['dropped']), (2, 2, 0), stats)
        self.assertTrue(all(model.face_count == 12 for model in models),
                        [model.face_count for model in models])
        for model in models:
            self.assertTrue(model.material_info['has_materials'], model.material_info)

    def test_the_face_filter_counts_what_it_drops(self):
        models, stats = self.extract(self.scene, 13, 'connected_components')
        self.assertEqual(models, [])
        self.assertEqual((stats['parts'], stats['kept'], stats['dropped']), (2, 0, 2), stats)

    def test_an_unknown_method_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            self.extractor.extract_from_scene(self.scene, 10, 'teleport')
        self.assertIn('teleport', str(caught.exception))

    def test_the_two_grouping_methods_refuse_a_file_that_reads_as_one_lump(self):
        for method in ('size_based', 'material_based'):
            with self.assertRaises(ValueError) as caught:
                self.extractor.extract_from_scene(self.lump, 1, method)
            self.assertIn(method, str(caught.exception))

    def test_a_lump_is_still_split_and_says_it_was_read_as_one_mesh(self):
        models, stats = self.extract(self.lump, 10, 'connected_components')
        self.assertIn('as one mesh', stats['read_with'], stats['read_with'])
        self.assertEqual((stats['parts'], stats['kept'], stats['dropped']), (2, 1, 1), stats)
        self.assertEqual(sum(model.face_count for model in models) + 1, self.lump_faces,
                         f'the 1-face stray is the dropped part: {stats}')

    def test_every_method_returns_every_face_it_was_given(self):
        """No method may hand back less geometry than the file holds.

        `spatial_clustering` used to: with `min_samples=5` DBSCAN labelled a whole low-poly
        part noise and `continue` skipped it, so two boxes gave no models and the sphere
        gave 7 of its 321 faces - a 2% result shown as a finished extraction.
        """
        for method in get_extraction_methods_info():
            # The .ctm comes back as one mesh, so the two grouping methods have nothing to
            # group and refuse it by name; the .stl is one geometry *of a scene*, so they run.
            fixtures = [(self.scene, self.scene_faces, False),
                        (self.lump, self.lump_faces, True),
                        (self.tetra, self.tetra_faces, False)]
            for path, faces, one_mesh in fixtures:
                if one_mesh and method in ('size_based', 'material_based'):
                    continue  # refused by name in the test above
                models, stats = self.extract(path, 1, method)
                where = f'{method} on {os.path.basename(path)}'
                self.assertTrue(models, f'{where} returned nothing: {stats}')
                self.assertEqual(stats['method'], method, stats)
                self.assertEqual(stats['kept'], len(models), stats)
                self.assertEqual(sum(model.face_count for model in models), faces,
                                 f'{where} lost faces: {stats}')

    def test_a_group_of_faces_is_a_group_and_not_a_fragment(self):
        """One object is one spatial group; an eps read off the bounding box said otherwise.

        A tenth of the extents is smaller than the gap between the four face centres of a
        tetrahedron, so the old parameter cut one closed solid into four models and reported
        four parts as four objects.
        """
        for path, want in ((self.scene, 2), (self.tetra, 1), (self.lump, 1)):
            models, stats = self.extract(path, 1, 'spatial_clustering')
            self.assertEqual(len(models), want,
                             f'{os.path.basename(path)}: {stats}')

    def test_a_method_that_could_not_run_names_the_one_that_did(self):
        components, _ = self.extract(self.lump, 1, 'connected_components')
        models, stats = self.extract(self.lump, 1, 'geometric_analysis')
        if [model.face_count for model in models] == [c.face_count for c in components]:
            # Same pieces as the connectivity split, so decomposition did not run here -
            # the summary has to say which method actually produced the answer.
            self.assertIn('connectivity', ' '.join(stats['notes']),
                          f'silent fallback: {stats}')

    def test_a_stop_leaves_the_parts_it_saw_and_says_it_stopped(self):
        models, stats = self.extract(self.scene, 1, 'connected_components',
                                     should_cancel=lambda: True)
        self.assertEqual(models, [])
        self.assertTrue(stats['stopped'], stats)

    def test_export_gives_each_part_its_own_material_file(self):
        models, _ = self.extract(self.scene, 10, 'connected_components')
        out = os.path.join(self.work, 'exported')
        verdict = ModelExtractor().export_selected_models(models, out, '.obj')
        self.assertEqual(len(verdict['exported']), 2, verdict)
        self.assertEqual(verdict['failed'], [], verdict)
        names = sorted(os.listdir(out))
        self.assertEqual(len([n for n in names if n.endswith('.mtl')]), 2, names)
        self.assertEqual(len([n for n in names if n.endswith('.obj')]), 2, names)
        for path in verdict['exported']:
            self.assertGreater(os.path.getsize(path), 0, path)

    def test_export_refuses_a_format_no_writer_here_can_hold(self):
        models, _ = self.extract(self.scene, 10, 'connected_components')
        out = os.path.join(self.work, 'refused')
        verdict = ModelExtractor().export_selected_models(models, out, '.psd')
        self.assertEqual(verdict['exported'], [], verdict)
        self.assertEqual(len(verdict['failed']), 2, verdict)
        self.assertIn('psd', verdict['failed'][0][1].lower())

    def test_a_part_name_cannot_escape_the_output_folder(self):
        models, _ = self.extract(self.scene, 10, 'connected_components')
        models[0].name = '../../escaped'
        out = os.path.join(self.work, 'jail')
        verdict = ModelExtractor().export_selected_models(models, out, '.glb')
        self.assertEqual(len(verdict['exported']), 2, verdict)
        for path in verdict['exported']:
            self.assertEqual(os.path.dirname(os.path.abspath(path)),
                             os.path.abspath(out), path)


class OptimizationBackend(unittest.TestCase):
    """What the Advanced pane's two groups really do, away from the widget."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='pre_opt_')
        cls.scene = write_textured_scene(cls.work)

    @classmethod
    def tearDownClass(cls):
        wipe(cls.work)

    def test_a_quality_the_encoders_reject_is_applied_and_said(self):
        for requested, applied in ((500, 100), (0, 1), (-5, 1)):
            report = TextureOptimizer().optimize(
                self.scene, os.path.join(self.work, f'q{requested}'),
                quality=requested, target='JPEG')
            self.assertEqual(report.quality, applied, report.lines())
            self.assertTrue(any(f'applied as {applied}' in note for note in report.notes),
                            report.notes)
            self.assertTrue(report.results, report.lines())

    def test_the_format_choices_are_the_installed_pillow_builds_choices(self):
        self.assertEqual(list(available_formats()), list(FORMAT_CHOICES))

    def test_a_texture_run_hands_its_model_to_the_scene_run(self):
        """Both switches armed is one pipeline, not two competing copies of one file."""
        seen = []
        real_optimize = PANE.SceneOptimizer.optimize

        def spy(self, model_path, *args, **kwargs):
            seen.append(model_path)
            report = SceneReport()
            report.notes.append('spied')
            return report

        settings = {'textures': True, 'quality': 70, 'target': 'JPEG', 'max_size': None,
                    'scene': True, 'remove_hidden': True, 'merge_static': True,
                    'simplify_materials': False}
        out = os.path.join(self.work, 'chain')
        PANE.SceneOptimizer.optimize = spy
        try:
            thread = OptimizationThread('both', self.scene, out, settings)
            payloads = []
            thread.finished_with.connect(lambda op, payload: payloads.append((op, payload)))
            thread.error.connect(lambda message: payloads.append(('error', message)))
            thread.run()
        finally:
            PANE.SceneOptimizer.optimize = real_optimize

        self.assertEqual(len(payloads), 1, payloads)
        operation, reports = payloads[0]
        self.assertEqual(operation, 'both')
        self.assertEqual([kind for kind, _ in reports], ['textures', 'scene'], reports)
        texture_output = reports[0][1].model_output
        self.assertTrue(texture_output and os.path.isfile(texture_output), texture_output)
        self.assertEqual([os.path.abspath(path) for path in seen],
                         [os.path.abspath(texture_output)],
                         'the scene run read a different file than the texture run wrote')

    def test_a_stopped_conversion_batch_names_the_files_that_never_ran(self):
        files = []
        for index in range(3):
            path = os.path.join(self.work, f'batch{index}.obj')
            trimesh.creation.box(extents=(1, 1, 1)).export(path)
            files.append(path)
        target = next(fmt for fmt in SupportedFormat if fmt.value == '.glb')
        thread = FormatConversionThread(files, os.path.join(self.work, 'batch_out'),
                                       target, {}, 0)
        results = []
        thread.conversion_complete.connect(
            lambda converted, failed, stopped: results.append((converted, failed, stopped)))
        thread.request_stop()
        thread.run()

        self.assertEqual(len(results), 1, results)
        converted, failed, stopped = results[0]
        self.assertTrue(stopped, results[0])
        self.assertEqual(converted, [], results[0])
        self.assertEqual([entry['input'] for entry in failed], files, failed)
        for entry in failed:
            self.assertIsNone(entry['output'], entry)
            self.assertIn('not run', entry['error'], entry)
            self.assertIn('stopped', entry['error'], entry)


class BakingBackend(unittest.TestCase):
    """Verdicts and cancel on the baker, with the rasteriser stubbed so it is fast."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='pre_bake_')
        cls.mesh = os.path.join(cls.work, 'low.obj')
        trimesh.creation.box(extents=(1, 1, 1)).export(cls.mesh)

    @classmethod
    def tearDownClass(cls):
        wipe(cls.work)

    def setUp(self):
        self.baker = TextureBaker()
        del SLOT_FAULTS[:]

    def tearDown(self):
        self.assertEqual(SLOT_FAULTS, [], f'a slot raised: {SLOT_FAULTS}')

    def _bake(self, out, **kwargs):
        got = {}
        self.baker.baking_complete.connect(
            lambda success, results: got.__setitem__('verdict', (success, results)))
        self.baker.error_occurred.connect(lambda message: got.__setitem__('error', message))
        params = {'high_poly_path': self.mesh, 'low_poly_path': self.mesh,
                  'output_dir': out, 'resolution': 16}
        params.update(kwargs)
        self.baker.bake(**params)
        return got

    def test_every_refusal_still_ends_in_a_verdict(self):
        # A `return` without a verdict leaves the pane's progress dialog open forever.
        original = BAKER_MODULE.PYMESHLAB_AVAILABLE
        BAKER_MODULE.PYMESHLAB_AVAILABLE = False
        try:
            got = self._bake(os.path.join(self.work, 'no_pymeshlab'))
        finally:
            BAKER_MODULE.PYMESHLAB_AVAILABLE = original
        self.assertIn('verdict', got, got)
        self.assertFalse(got['verdict'][0], got)
        self.assertIn('PyMeshLab', got['error'], got)

        got = self._bake(os.path.join(self.work, 'nothing_asked'),
                         bake_normals=False, bake_diffuse=False, bake_ao=False)
        self.assertIn('verdict', got, got)
        self.assertFalse(got['verdict'][0], got)
        self.assertIn('turned off', got['error'], got)

    def test_a_stop_keeps_the_landed_map_and_names_the_rest(self):
        calls = []

        def fake_bake_one(kind, path, resolution):
            calls.append(kind)
            Image.new('RGB', (4, 4), (0, 0, 0)).save(path)

        self.baker._bake_one = fake_bake_one
        got = self._bake(os.path.join(self.work, 'stopped'),
                         should_cancel=lambda: len(calls) >= 1)

        self.assertEqual(calls, ['normal'], calls)
        self.assertFalse(got['verdict'][0], got)
        landed = got['verdict'][1]
        self.assertEqual(list(landed), ['normal'], landed)
        self.assertTrue(os.path.isfile(landed['normal']), landed)
        self.assertIn('Diffuse', got['error'], got)
        self.assertIn('Ao', got['error'], got)
        self.assertIn('1 map(s) already on disk', got['error'], got)

    def test_a_map_that_fails_is_named_and_the_others_still_land(self):
        written = []

        def fake_bake_one(kind, path, resolution):
            if kind == 'ao':
                raise RuntimeError('PyMeshLab refused the AO transfer')
            written.append(kind)
            Image.new('RGB', (4, 4), (0, 0, 0)).save(path)

        self.baker._bake_one = fake_bake_one
        got = self._bake(os.path.join(self.work, 'partial'))

        self.assertEqual(written, ['normal', 'diffuse'], written)
        self.assertFalse(got['verdict'][0], got)
        self.assertEqual(sorted(got['verdict'][1]), ['diffuse', 'normal'], got)
        self.assertIn('ao', got['error'], got)
        self.assertIn('refused the AO transfer', got['error'], got)

    def test_a_full_bake_reports_success_and_every_map(self):
        def fake_bake_one(kind, path, resolution):
            Image.new('RGB', (4, 4), (0, 0, 0)).save(path)

        self.baker._bake_one = fake_bake_one
        got = self._bake(os.path.join(self.work, 'whole'))
        self.assertTrue(got['verdict'][0], got)
        self.assertEqual(sorted(got['verdict'][1]), ['ao', 'diffuse', 'normal'], got)


class PreProcessingPane(unittest.TestCase):
    """Clicks the pane. Each control has to change something the test can read."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='pre_pane_')
        cls.scene = write_textured_scene(cls.work)
        cls.tab = PreProcessingTab()
        cls.dialogs = DIALOGS

    @classmethod
    def tearDownClass(cls):
        wipe(cls.work)

    def setUp(self):
        del SLOT_FAULTS[:]
        del self.dialogs.messages[:]
        # One pane is shared by the whole class, so a run a failing test left in flight
        # would answer the next test's click. Nothing may be running when a test starts.
        for worker in list(self.tab._workers):
            self.assertTrue(worker.wait(30000), f'{worker} never finished')
        self.tab.load_model(self.scene)
        self.tab.enable_texture_opt.setChecked(False)
        self.tab.enable_scene_opt.setChecked(False)
        self.tab.remove_hidden.setChecked(True)
        self.tab.merge_static.setChecked(True)
        self.tab.simplify_materials.setChecked(False)
        self.tab.texture_quality_value.setValue(80)
        self.tab.texture_max_size.setValue(0)

    def tearDown(self):
        self.assertEqual(SLOT_FAULTS, [], f'a slot raised: {SLOT_FAULTS}')

    def spin_until(self, want, label, timeout=90.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            APP.processEvents()
            if want():
                return
            time.sleep(0.02)
        self.fail(f'the pane never produced: {label}')

    def extracted(self, min_faces=10, method='connected_components'):
        self.tab.min_faces_spin.setValue(min_faces)
        index = next(i for i in range(self.tab.extraction_method.count())
                     if self.tab.extraction_method.itemData(i) == method)
        self.tab.extraction_method.setCurrentIndex(index)
        self.tab.extract_btn.click()
        self.spin_until(lambda: bool(self.tab.extraction_summary_label.text()),
                        'an extraction summary')

    def in_folder(self, scene):
        """Swap in a fixture copy so a run's output cannot be another run's input."""
        folder = tempfile.mkdtemp(prefix='pre_case_')
        path = write_textured_scene(folder)
        self.tab.load_model(path)
        return folder, path

    def test_browse_filters_are_the_readers_own_list(self):
        filter_text = self.tab.readable_filter()
        for extension in self.tab.format_converter.readable_formats():
            self.assertIn(f'*{extension}', filter_text)
        self.assertNotIn('*.xyz', filter_text)
        self.assertIn('All Files', filter_text)

    def test_extraction_combo_offers_exactly_the_backend_methods(self):
        ids = [self.tab.extraction_method.itemData(i)
               for i in range(self.tab.extraction_method.count())]
        self.assertEqual(ids, list(get_extraction_methods_info()))

    def test_extract_fills_the_table_and_says_what_it_counted(self):
        self.extracted(10)
        self.assertEqual(self.tab.models_table.rowCount(), 2)
        self.assertEqual(len(self.tab.extracted_models), 2)
        sentence = self.tab.extraction_summary_label.text()
        self.assertIn('2 piece(s) produced', sentence, sentence)
        self.assertIn('2 kept', sentence, sentence)
        self.assertIn('0 below the 10-face minimum', sentence, sentence)
        self.assertIn('read with', sentence, sentence)
        self.assertTrue(self.tab.extract_btn.isEnabled())

    def test_a_minimum_above_every_part_reports_the_empty_result(self):
        self.extracted(999)
        self.assertEqual(self.tab.models_table.rowCount(), 0)
        sentence = self.tab.extraction_summary_label.text()
        self.assertIn('0 kept', sentence, sentence)
        self.assertIn('2 below the 999-face minimum', sentence, sentence)

    def test_loading_a_file_forgets_the_one_it_replaced(self):
        """A report about the previous file is a false claim about the current one."""
        self.extracted(10)
        self.tab.opt_results.setPlainText('Texture optimization: 1 image replaced')
        self.assertTrue(self.tab.extraction_summary_label.text())

        other = tempfile.mkdtemp(prefix='pre_second_')
        try:
            self.tab.load_model(write_textured_scene(other, name='second.glb'))
            self.assertEqual(self.tab.models_table.rowCount(), 0,
                             'the rows of the file before this one are still listed')
            self.assertEqual(self.tab.extracted_models, [],
                             'Export would write the previous files parts into this one')
            self.assertEqual(self.tab.extraction_summary_label.text(), '')
            self.assertEqual(self.tab.opt_results.toPlainText(), '')
        finally:
            wipe(other)

    def test_export_offers_only_formats_a_writer_here_can_hold(self):
        folder, _ = self.in_folder(self.scene)
        self.extracted(10)
        captured = {}
        real_get_item = PANE.QInputDialog.getItem

        def fake_get_item(parent, title, label, items, current=0, *args, **kwargs):
            captured['items'] = list(items)
            return 'GLB', True

        PANE.QInputDialog.getItem = fake_get_item
        try:
            self.tab.export_selected_models()
            self.spin_until(
                lambda: 'written to' in self.tab.extraction_summary_label.text(),
                'an export sentence')
            written = [name for name in os.listdir(folder) if name != 'hero.glb']
            self.assertEqual(len(written), 2, sorted(os.listdir(folder)))
            for name in written:
                self.assertTrue(name.endswith('.glb'), name)
                self.assertGreater(os.path.getsize(os.path.join(folder, name)), 0, name)
        finally:
            PANE.QInputDialog.getItem = real_get_item
            wipe(folder)

        offered = [name.lower() for name in captured['items']]
        self.assertEqual(sorted(offered),
                         sorted(ext.lstrip('.')
                                for ext in self.tab.format_converter.mesh_write_formats()),
                         captured['items'])
        self.assertNotIn('dae', offered)
        self.assertNotIn('fbx', offered)

    def test_apply_is_disabled_until_a_switch_is_armed(self):
        self.assertFalse(self.tab.opt_apply_btn.isEnabled())
        self.assertTrue(self.tab.opt_preview_btn.isEnabled())
        self.tab.enable_scene_opt.setChecked(True)
        self.assertTrue(self.tab.opt_apply_btn.isEnabled())
        self.tab.enable_scene_opt.setChecked(False)
        self.assertFalse(self.tab.opt_apply_btn.isEnabled())
        self.tab.enable_texture_opt.setChecked(True)
        self.assertTrue(self.tab.opt_apply_btn.isEnabled())

    def test_the_apply_button_follows_the_loaded_file(self):
        loaded = self.tab.current_file
        self.tab.enable_texture_opt.setChecked(True)
        self.tab.current_file = None
        self.tab._refresh_optimization_buttons()
        self.assertFalse(self.tab.opt_apply_btn.isEnabled())
        self.assertFalse(self.tab.opt_preview_btn.isEnabled())
        self.tab.current_file = loaded
        self.tab._refresh_optimization_buttons()
        self.assertTrue(self.tab.opt_apply_btn.isEnabled())

    def test_the_convert_to_combo_offers_only_what_this_pillow_build_encodes(self):
        choices = [self.tab.texture_format.itemText(i)
                   for i in range(self.tab.texture_format.count())]
        self.assertEqual(choices, list(FORMAT_CHOICES))
        reasons = available_formats()
        model = self.tab.texture_format.model()
        for index, choice in enumerate(choices):
            self.assertEqual(model.item(index).isEnabled(), reasons[choice] is None,
                             f'{choice}: enabled, but the build says {reasons[choice]!r}')
        self.assertIsNone(reasons[self.tab.texture_format.currentText()])

    def test_quality_has_a_typable_box_that_outlives_the_slider(self):
        self.tab.texture_quality_value.setValue(500)
        self.assertEqual(self.tab.texture_quality.value(), 100)
        self.assertEqual(self.tab._advanced_settings()['quality'], 500)
        self.tab.texture_quality.setValue(35)
        self.assertEqual(self.tab.texture_quality_value.value(), 35)
        self.assertEqual(self.tab._advanced_settings()['max_size'], None)
        self.tab.texture_max_size.setValue(1024)
        self.assertEqual(self.tab._advanced_settings()['max_size'], 1024)

    def test_preview_counts_both_groups_and_writes_nothing(self):
        folder, _ = self.in_folder(self.scene)
        before = sorted(os.listdir(folder))

        self.tab.opt_preview_btn.click()
        self.spin_until(lambda: bool(self.tab.opt_results.toPlainText()), 'a preview')
        text = self.tab.opt_results.toPlainText()

        self.assertIn('Preview of hero.glb', text, text)
        self.assertIn('2 distinct image(s)', text, text)
        self.assertIn('2 placed part(s)', text, text)
        self.assertIn('24 faces', text, text)
        self.assertIn('no two parts share a material', text, text)
        self.assertEqual(sorted(os.listdir(folder)), before,
                         'the preview wrote into the asset folder')
        wipe(folder)

    def test_a_file_nothing_here_opens_is_refused_by_name(self):
        folder = tempfile.mkdtemp(prefix='pre_unreadable_')
        bogus = os.path.join(folder, 'broken.glb')
        with open(bogus, 'wb') as handle:
            handle.write(b'glTF not really\n')
        self.tab.load_model(bogus)

        self.tab.opt_preview_btn.click()
        self.spin_until(lambda: bool(self.tab.opt_results.toPlainText()), 'a refusal')
        text = self.tab.opt_results.toPlainText()
        self.assertIn('failed', text.lower(), text)
        self.assertIn('cannot read broken.glb', text, text)
        self.assertEqual(sorted(os.listdir(folder)), ['broken.glb'],
                         'a refused file still produced output')
        self.tab.load_model(self.scene)
        wipe(folder)

    def test_apply_textures_writes_the_model_and_reports_the_bytes(self):
        folder, _ = self.in_folder(self.scene)
        self.tab.enable_texture_opt.setChecked(True)
        self.tab.texture_format.setCurrentText('JPEG')
        self.tab.texture_quality_value.setValue(60)

        self.tab.opt_apply_btn.click()
        self.spin_until(lambda: 'Texture optimization' in self.tab.opt_results.toPlainText(),
                        'a texture report')
        text = self.tab.opt_results.toPlainText()

        written = os.path.join(folder, 'hero_optimized.glb')
        self.assertTrue(os.path.isfile(written), sorted(os.listdir(folder)))
        self.assertIn('image(s) replaced inside the file', text, text)
        self.assertIn('bytes', text, text)
        back = trimesh.load(written)
        self.assertEqual(len(back.geometry), 2, sorted(back.geometry))
        self.assertTrue(self.tab.opt_apply_btn.isEnabled())
        wipe(folder)

    def test_apply_with_nothing_armed_says_so_and_writes_nothing(self):
        folder, _ = self.in_folder(self.scene)
        self.assertFalse(self.tab.opt_apply_btn.isEnabled())
        self.tab.apply_optimizations()
        self.assertIn('Neither', self.dialogs.texts(), self.dialogs.messages)
        self.assertEqual(sorted(os.listdir(folder)), ['hero.glb'], os.listdir(folder))
        self.tab.load_model(self.scene)
        wipe(folder)

    def test_a_stopped_texture_run_says_it_was_stopped(self):
        """Cancel on the dialog has to reach the worker and be reported as a stop."""
        folder, _ = self.in_folder(self.scene)
        self.tab.enable_texture_opt.setChecked(True)
        self.tab.texture_format.setCurrentText('PNG')

        self.tab.opt_apply_btn.click()
        worker = self.tab.optimization_thread
        self.assertIsNotNone(worker, 'Apply started no worker')
        worker.request_stop()
        self.spin_until(lambda: bool(self.tab.opt_results.toPlainText()), 'a stopped run')
        text = self.tab.opt_results.toPlainText()
        self.assertIn('Stopped by Cancel', text, text)
        self.assertTrue(self.tab.opt_apply_btn.isEnabled())
        wipe(folder)

    def test_every_progress_dialog_cancel_reaches_its_worker(self):
        pairs = [
            ('lod_progress', 'lod_thread', self._start_lod),
            ('extraction_progress', 'extraction_thread',
             lambda: self.tab.extract_btn.click()),
            ('conversion_progress', 'conversion_thread',
             lambda: self.tab.convert_batch_files()),
            ('progress_dialog', 'baking_thread', lambda: self.tab.start_baking()),
            ('optimization_progress', 'optimization_thread',
             lambda: self.tab.opt_preview_btn.click()),
        ]
        self.tab.conversion_files_list.addItem(self.scene)
        self.tab.high_poly_path.setText(self.scene)
        self.tab.low_poly_path.setText(self.scene)
        with StalledWorkers(['LodGenerationThread', 'ModelExtractionThread',
                            'FormatConversionThread', 'TextureBakerThread',
                            'OptimizationThread']):
            for dialog_attr, thread_attr, start in pairs:
                start()
                dialog = getattr(self.tab, dialog_attr)
                worker = getattr(self.tab, thread_attr)
                self.assertIsNotNone(dialog, f'{dialog_attr}: no dialog was opened')
                self.assertIsNotNone(worker, f'{thread_attr}: no worker was started')
                self.assertFalse(worker._stop_requested, f'{dialog_attr} pre-set the stop')
                dialog.canceled.emit()
                self.assertTrue(worker._stop_requested,
                                f'the {dialog_attr} Cancel button reached nobody')
                setattr(self.tab, dialog_attr, None)
                setattr(self.tab, thread_attr, None)
                dialog.close()
        self.tab.conversion_files_list.clear()
        # A stalled worker never answers, so no terminal handler runs to put the buttons
        # back the way a real run would. The next test starts from an idle pane.
        for button in (self.tab.generate_lods_btn, self.tab.extract_btn,
                       self.tab.convert_batch_btn, self.tab.bake_btn):
            button.setEnabled(True)
        self.tab._refresh_optimization_buttons()

    def _start_lod(self):
        self.tab.enable_lod.setChecked(True)
        self.tab.lod_levels.setValue(2)
        self.tab.generate_lods()


class PaneSourceContract(unittest.TestCase):
    """Source-level guards for the two failures that made this pane untrustworthy."""

    def test_the_pane_has_no_reader_of_its_own(self):
        self.assertNotIn('import trimesh', PANE_SOURCE)
        self.assertNotIn('trimesh.load(', PANE_SOURCE)
        self.assertNotIn('pyassimp', PANE_SOURCE)
        for backend in ('FormatConverter', 'ModelExtractor', 'TextureOptimizer',
                        'SceneOptimizer', 'TextureBakerThread'):
            self.assertIn(backend, PANE_SOURCE, f'{backend} is not reached from the pane')

    def test_the_advanced_pane_no_longer_answers_with_yes_and_no(self):
        self.assertNotIn('Optimizations Enabled', PANE_SOURCE)
        self.assertNotIn("'Yes' if self.enable", PANE_SOURCE)
        start = PANE_SOURCE.index('def preview_optimizations')
        body = PANE_SOURCE[start:start + 1200]
        self.assertIn('_run_optimization', body, 'preview does not hand work to a thread')

    def test_every_worker_the_pane_defines_is_started(self):
        for name in ('LODPreviewThread', 'LodGenerationThread', 'ModelExtractionThread',
                     'FormatConversionThread', 'TextureBakerThread', '_ExportThread',
                     'OptimizationThread'):
            self.assertIn(f'{name}(', PANE_SOURCE, f'{name} is defined and never started')

    def test_cancel_is_wired_to_a_worker_at_every_long_run(self):
        self.assertEqual(PANE_SOURCE.count('canceled.connect'),
                         PANE_SOURCE.count('QProgressDialog('),
                         'a progress dialog is open whose Cancel reaches nothing')

    def test_the_pane_offers_no_browse_filter_the_reader_cannot_honour(self):
        for quoted in ('*.fbx *.glb *.gltf",', '*.xyz'):
            self.assertNotIn(quoted, PANE_SOURCE, f'a typed-out filter list is back: {quoted}')

    def test_no_worker_can_be_dropped_while_it_still_runs(self):
        """Every worker is started through `_keep_worker`.

        Reassigning `self.<run>_thread` over a worker that is still running discards that
        thread's last Python reference, and Qt answers a destroyed running QThread by
        terminating the process - the app vanishes with no error to read. The registry is
        the only shape in which a lost reference is harmless.
        """
        lines = PANE_SOURCE.splitlines()
        for name in ('LODPreviewThread', 'LodGenerationThread', 'ModelExtractionThread',
                     'FormatConversionThread', 'TextureBakerThread', '_ExportThread',
                     'OptimizationThread'):
            starts = [index for index, line in enumerate(lines)
                      if f'{name}(' in line and not line.strip().startswith('class ')]
            self.assertEqual(len(starts), 1, f'{name}: {len(starts)} start sites, want one')
            window = ''.join(lines[starts[0] - 1:starts[0] + 1])
            self.assertIn('self._keep_worker(', window,
                          f'{name} is started without _keep_worker')

    def test_a_stage_handler_never_asks_the_dialog_from_the_attribute(self):
        """`QProgressDialog.setValue` runs an event loop, so the worker's terminal signal
        can be delivered - and the handler that nulls the attribute run - between two lines
        of a stage handler. Each handler reads the dialog once and works from that object.
        """
        for match in re.finditer(r'self\.\w*progress\w*\.(setValue|setMaximum|setLabelText)\(',
                                 PANE_SOURCE):
            self.fail(f'a stage handler re-reads the attribute after the pump: {match.group(0)}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
