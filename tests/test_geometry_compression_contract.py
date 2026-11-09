import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from src.processing.geometry_compression import GeometryCompressor


class GeometryCompressionContract(unittest.TestCase):
    def test_missing_encoder_is_a_named_refusal(self):
        with tempfile.TemporaryDirectory() as work, \
             mock.patch.object(GeometryCompressor, 'encoder_path', return_value=None):
            source = os.path.join(work, 'asset.glb')
            with open(source, 'wb') as handle:
                handle.write(b'glTF')
            result = GeometryCompressor.compress_meshopt(source, os.path.join(work, 'out.glb'))
        self.assertFalse(result.success)
        self.assertIn('gltfpack', result.message)

    def test_wrong_format_is_refused_before_an_encoder_is_called(self):
        result = GeometryCompressor.compress_meshopt('asset.obj', 'out.glb')
        self.assertFalse(result.success)
        self.assertIn('.gltf or .glb', result.message)


if __name__ == '__main__':
    unittest.main(verbosity=2)
