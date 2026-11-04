"""
Texture bake tests.

The bake path used to raise on its very first filter ("Mesh has no associated
texture to overwrite"), so no map was ever written and the UI only showed a
generic failure. These tests assert the three maps exist, are real images at the
requested size, and carry the expected content - plus that a high poly without
vertex colors costs the diffuse map and nothing else.

Run: python -X utf8 tests/test_texture_bake.py
"""

import os
import shutil
import sys
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import numpy as np
import trimesh
from PIL import Image

from src.processing.texture_baker import TextureBaker

SOURCE_COLOR = (200, 90, 40)


def _sphere(subdivisions, dimple=False, colored=False):
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)
    if dimple:
        vertices = np.array(mesh.vertices)
        vertices[vertices[:, 1] > 0.9] *= 0.4  # push the pole in, so AO has a cavity
        mesh = trimesh.Trimesh(vertices=vertices, faces=mesh.faces)
    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh)
    if colored:
        mesh.visual.vertex_colors = np.tile(
            np.array([*SOURCE_COLOR, 255], dtype=np.uint8), (len(mesh.vertices), 1))
    return mesh


class TestTextureBake(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not trimesh:
            raise unittest.SkipTest('trimesh is not installed')
        cls.work = tempfile.mkdtemp(prefix='renderfox_bake_')
        cls.low = os.path.join(cls.work, 'lo.obj')
        _sphere(2).export(cls.low)
        cls.out = os.path.join(cls.work, 'out')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if os.path.isdir(self.out):
            shutil.rmtree(self.out)
        self.events = []
        self.baker = TextureBaker()
        self.baker.progress_update.connect(
            lambda value, message: self.events.append((value, message)))
        self.baker.error_occurred.connect(lambda message: self.events.append(('error', message)))

    def bake(self, high_poly, **kwargs):
        """Run a bake and capture the success flag the UI would receive."""
        flags = {}
        self.baker.baking_complete.connect(lambda ok, results: flags.setdefault('ok', ok))
        results = self.baker.bake(high_poly, self.low, self.out, resolution=128, **kwargs)
        return flags.get('ok', False), results

    def test_01_all_three_maps_are_written(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        success, results = self.bake(high)
        self.assertTrue(success, f'bake reported failure: {self.events}')
        self.assertEqual({'normal', 'diffuse', 'ao'}, set(results))
        for kind, path in results.items():
            with self.subTest(map=kind):
                self.assertTrue(os.path.exists(path), path)
                self.assertGreater(os.path.getsize(path), 100, 'suspiciously small image')
                with Image.open(path) as image:
                    self.assertEqual((128, 128), (image.width, image.height))

    def test_02_diffuse_carries_the_source_colour(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        _, results = self.bake(high)
        pixels = np.asarray(Image.open(results['diffuse']).convert('RGB'))
        # Only the rasterised texels are meaningful; the atlas margin is padding.
        core = pixels[24:104, 24:104].reshape(-1, 3)
        painted = core[core.sum(axis=1) > 30]
        self.assertGreater(len(painted), 100, 'diffuse map is blank')
        mean = painted.mean(axis=0)
        for channel in range(3):
            self.assertAlmostEqual(float(mean[channel]), float(SOURCE_COLOR[channel]), delta=45)

    def test_03_ao_is_greyscale_and_spans_the_byte_range(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        _, results = self.bake(high)
        pixels = np.asarray(Image.open(results['ao']).convert('RGB'))
        self.assertTrue(np.array_equal(pixels[:, :, 0], pixels[:, :, 1]), 'AO is not greyscale')
        self.assertTrue(np.array_equal(pixels[:, :, 1], pixels[:, :, 2]), 'AO is not greyscale')
        grey = pixels[:, :, 0]
        self.assertGreater(int(grey.max()) - int(grey.min()), 32,
                           'AO map is almost flat - the levels stretch did not run')

    def test_04_normals_are_not_a_flat_colour(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        _, results = self.bake(high)
        pixels = np.asarray(Image.open(results['normal']).convert('RGB'))
        self.assertGreater(float(pixels.std()), 10.0, 'normal map carries no detail')

    def test_05_missing_source_colour_only_costs_the_diffuse_map(self):
        high = os.path.join(self.work, 'hi_plain.obj')
        _sphere(3, dimple=True).export(high)
        success, results = self.bake(high)
        self.assertFalse(success, 'a bake that could not produce diffuse must not report success')
        self.assertEqual({'normal', 'ao'}, set(results))
        text = ' '.join(str(event) for event in self.events)
        self.assertIn('diffuse', text)
        self.assertIn('vertex colors', text)

    def test_06_progress_reaches_100(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        self.bake(high)
        values = [value for value, _ in self.events if isinstance(value, int)]
        self.assertEqual(100, max(values), 'the progress bar never completes')
        self.assertEqual(values, sorted(values), 'progress went backwards')

    def test_07_output_directory_is_created(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        nested = os.path.join(self.out, 'a', 'b')
        self.baker.bake(high, self.low, nested, resolution=64,
                        bake_normals=True, bake_diffuse=False, bake_ao=False)
        self.assertTrue(os.path.isdir(nested))

    def test_08_single_map_selection_is_respected(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        success, results = self.bake(high, bake_normals=False, bake_diffuse=False, bake_ao=True)
        self.assertTrue(success)
        self.assertEqual(['ao'], sorted(results))

    def test_09_nothing_selected_reports_instead_of_lying(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        success, results = self.bake(high, bake_normals=False, bake_diffuse=False, bake_ao=False)
        self.assertFalse(success)
        self.assertEqual({}, results)
        self.assertTrue(any(event[0] == 'error' for event in self.events))


    def test_10_nothing_is_written_outside_the_output_directory(self):
        """A dummy-texture bake drops checkerboard.png in the launch directory.

        The app is started from wherever the user's shell happens to be, so that
        file lands in a project folder with no warning. The baker supplies its
        own blank raster instead, and this asserts the working directory is
        untouched.
        """
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        sandbox = os.path.join(self.work, 'cwd')
        os.makedirs(sandbox, exist_ok=True)
        before = sorted(os.listdir(sandbox))
        previous = os.getcwd()
        os.chdir(sandbox)
        try:
            _, results = self.bake(high)
        finally:
            os.chdir(previous)
        self.assertEqual(before, sorted(os.listdir(sandbox)),
                         'the bake wrote stray files into the working directory')
        stray = sorted(name for name in os.listdir(self.out)
                       if os.path.join(self.out, name) not in set(results.values()))
        self.assertEqual([], stray, 'a temporary raster was left in the output folder')

    def test_11_requested_resolution_is_the_image_size(self):
        high = os.path.join(self.work, 'hi_colored.obj')
        _sphere(3, dimple=True, colored=True).export(high)
        flags = {}
        self.baker.baking_complete.connect(lambda ok, _r: flags.setdefault('ok', ok))
        results = self.baker.bake(high, self.low, self.out, resolution=64,
                                  bake_normals=True, bake_diffuse=False, bake_ao=False)
        self.assertTrue(flags.get('ok'), f'bake reported failure: {self.events}')
        with Image.open(results['normal']) as image:
            self.assertEqual((64, 64), (image.width, image.height))


if __name__ == '__main__':
    unittest.main(verbosity=2)
