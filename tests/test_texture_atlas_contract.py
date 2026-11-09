import json
import os
import shutil
import sys
import tempfile
import unittest

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from src.processing.texture_atlas import TextureAtlas


class TextureAtlasCase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='renderfox_atlas_')

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def image(self, name, colour, size=(4, 3)):
        path = os.path.join(self.work, name)
        Image.new('RGBA', size, colour).save(path)
        return path

    def test_writes_grid_and_manifest_that_both_read_back(self):
        output = os.path.join(self.work, 'tiles.png')
        result = TextureAtlas.build(output, [self.image('red.png', (255, 0, 0, 255)),
                                             self.image('blue.png', (0, 0, 255, 255)),
                                             self.image('green.png', (0, 255, 0, 255))], columns=2)
        self.assertTrue(result.success, result.message)
        with Image.open(result.atlas_path) as atlas:
            self.assertEqual((8, 6), atlas.size)
            self.assertEqual((255, 0, 0, 255), atlas.getpixel((1, 1)))
            self.assertEqual((0, 0, 255, 255), atlas.getpixel((5, 1)))
        with open(result.manifest_path, encoding='utf-8') as handle:
            manifest = json.load(handle)
        self.assertEqual({'red.png', 'blue.png', 'green.png'}, set(manifest['sprites']))
        self.assertEqual(3, manifest['sprites']['green.png']['y'])

    def test_refuses_different_sizes_and_empty_input(self):
        self.assertFalse(TextureAtlas.build(os.path.join(self.work, 'none.png'), []).success)
        result = TextureAtlas.build(os.path.join(self.work, 'bad.png'),
                                    [self.image('one.png', (0, 0, 0, 0)),
                                     self.image('two.png', (0, 0, 0, 0), (5, 5))])
        self.assertFalse(result.success)
        self.assertIn('same dimensions', result.message)


if __name__ == '__main__':
    unittest.main(verbosity=2)
