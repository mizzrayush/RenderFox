"""Contract test for Texel Density and Engine LOD group workflows."""

import os
import sys
import shutil
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.processing.texel_density import calculate_texel_density, TexelDensityReport
from src.processing.lod_generator import generate_engine_lod_group
from src.features.automation_engine import ActionRegistry


class TestTexelDensityContract(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cube_obj = os.path.join(self.temp_dir, "test_cube.obj")
        # Standard textured cube with UVs
        cube_data = (
            "v 0.0 0.0 0.0\n"
            "v 1.0 0.0 0.0\n"
            "v 1.0 1.0 0.0\n"
            "v 0.0 1.0 0.0\n"
            "vt 0.0 0.0\n"
            "vt 1.0 0.0\n"
            "vt 1.0 1.0\n"
            "vt 0.0 1.0\n"
            "vn 0.0 0.0 1.0\n"
            "f 1/1/1 2/2/1 3/3/1\n"
            "f 1/1/1 3/3/1 4/4/1\n"
        )
        with open(self.cube_obj, "w", encoding="utf-8") as f:
            f.write(cube_data)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_calculate_texel_density_returns_verified_metrics(self):
        report = calculate_texel_density(self.cube_obj, texture_size=2048, target_density_px_per_m=1024.0)
        self.assertIsInstance(report, TexelDensityReport)
        self.assertGreater(report.surface_area_3d, 0.0)
        self.assertGreater(report.uv_area, 0.0)
        self.assertEqual(report.texture_size, 2048)
        self.assertGreater(report.texel_density_px_per_m, 0.0)
        self.assertIn(report.rating, ("Optimal", "Acceptable", "Uneven"))
        self.assertIn("Texel Density", report.summary)

    def test_missing_file_reports_error_cleanly(self):
        report = calculate_texel_density(os.path.join(self.temp_dir, "non_existent.obj"))
        self.assertEqual(report.rating, "Error")
        self.assertTrue(report.missing_uvs)

    def test_registered_action_is_callable(self):
        ActionRegistry.register_default_actions()
        action = ActionRegistry.get_action("processing.analyze_texel_density")
        self.assertIsNotNone(action)
        result = action(model_path=self.cube_obj, texture_size=1024)
        self.assertTrue(result.get("success"))
        self.assertIn("metrics", result)
        self.assertIn("texel_density_px_per_m", result["metrics"])

    def test_generate_engine_lod_group_produces_files_and_manifest(self):
        out_lod_dir = os.path.join(self.temp_dir, "lods")
        res = generate_engine_lod_group(self.cube_obj, out_lod_dir, lod_levels=3, engine="unreal")
        self.assertTrue(res.get("success"))
        self.assertGreaterEqual(res.get("levels_created"), 1)
        self.assertTrue(os.path.isfile(res["manifest_path"]))
        for path in res["output_files"]:
            self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
