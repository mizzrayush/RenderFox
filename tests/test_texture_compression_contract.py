import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from src.processing.texture_compression import TextureCompressor


class TextureCompressionContract(unittest.TestCase):
    def test_missing_basis_encoder_is_named(self):
        with tempfile.TemporaryDirectory() as work:
            source = os.path.join(work, 'map.png')
            with open(source, 'wb') as handle: handle.write(b'png')
            with mock.patch.object(TextureCompressor, 'encoder_path', return_value=None):
                result = TextureCompressor.compress_ktx2(source, os.path.join(work, 'map.ktx2'))
        self.assertFalse(result.success)
        self.assertIn('Basis Universal', result.message)

    def test_missing_source_is_refused_first(self):
        result = TextureCompressor.compress_ktx2('missing.png', 'map.ktx2')
        self.assertFalse(result.success)
        self.assertIn('does not exist', result.message)


if __name__ == '__main__': unittest.main(verbosity=2)
