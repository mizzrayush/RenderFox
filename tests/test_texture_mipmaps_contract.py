import json
import os
import shutil
import sys
import tempfile
import unittest
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from src.processing.texture_mipmaps import TextureMipmaps


class MipmapContract(unittest.TestCase):
    def setUp(self): self.work = tempfile.mkdtemp(prefix='renderfox_mips_')
    def tearDown(self): shutil.rmtree(self.work, ignore_errors=True)

    def test_png_levels_end_at_one_pixel_and_manifest_reads_back(self):
        source = os.path.join(self.work, 'albedo.png')
        Image.new('RGBA', (8, 4), (12, 34, 56, 255)).save(source)
        result = TextureMipmaps.generate(source, os.path.join(self.work, 'mips'))
        self.assertTrue(result.success, result.message)
        with open(result.manifest_path, encoding='utf-8') as handle: levels = json.load(handle)['levels']
        self.assertEqual([(8, 4), (4, 2), (2, 1), (1, 1)],
                         [(item['width'], item['height']) for item in levels])

    def test_missing_source_is_refused(self):
        self.assertFalse(TextureMipmaps.generate(os.path.join(self.work, 'missing.png'), self.work).success)


if __name__ == '__main__': unittest.main(verbosity=2)
