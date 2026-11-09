import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from src.processing.texture_compression import TextureCompressor
from src.features.automation_engine import ActionRegistry


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

    def test_encoder_command_writes_and_verifies_ktx2(self):
        with tempfile.TemporaryDirectory() as work:
            source = os.path.join(work, 'map.png')
            output = os.path.join(work, 'map.ktx2')
            with open(source, 'wb') as handle: handle.write(b'png')

            def write_ktx2(command, **kwargs):
                self.assertIn('-ktx2', command)
                self.assertIn('-validate_output', command)
                self.assertIn('-mipmap', command)
                with open(output, 'wb') as handle: handle.write(b'KTX 20')
                return mock.Mock(returncode=0, stdout='', stderr='')

            with mock.patch.object(TextureCompressor, 'encoder_path', return_value='basisu'), \
                 mock.patch('src.processing.texture_compression.subprocess.run', side_effect=write_ktx2):
                result = TextureCompressor.compress_ktx2(source, output)
        self.assertTrue(result.success)
        self.assertEqual(output, result.output_path)

    def test_encoder_failure_is_not_reported_as_an_asset(self):
        with tempfile.TemporaryDirectory() as work:
            source = os.path.join(work, 'map.png')
            with open(source, 'wb') as handle: handle.write(b'png')
            with mock.patch.object(TextureCompressor, 'encoder_path', return_value='basisu'), \
                 mock.patch('src.processing.texture_compression.subprocess.run',
                            return_value=mock.Mock(returncode=2, stdout='', stderr='bad input')):
                result = TextureCompressor.compress_ktx2(source, os.path.join(work, 'map.ktx2'))
        self.assertFalse(result.success)
        self.assertIn('bad input', result.message)

    def test_texture_dialog_exposes_the_verified_ktx2_action(self):
        with open(os.path.join(ROOT, 'src', 'ui', 'texture_generator.py'), encoding='utf-8') as source_file:
            source = source_file.read()
        self.assertIn('Compress KTX2 / Basis', source)
        self.assertIn('TextureCompressor.compress_ktx2(source, output)', source)

    def test_shared_automation_returns_the_same_encoder_verdict(self):
        ActionRegistry.register_default_actions()
        with tempfile.TemporaryDirectory() as work:
            source = os.path.join(work, 'map.png')
            output = os.path.join(work, 'map.ktx2')
            with open(source, 'wb') as handle: handle.write(b'png')
            with mock.patch.object(TextureCompressor, 'encoder_path', return_value='basisu'), \
                 mock.patch('src.processing.texture_compression.subprocess.run',
                            return_value=mock.Mock(returncode=1, stdout='', stderr='unsupported')):
                result = ActionRegistry.execute('processing.compress_texture_ktx2',
                                                input_path=source, output_path=output)
        self.assertFalse(result['success'])
        self.assertIn('unsupported', result['error'])


if __name__ == '__main__': unittest.main(verbosity=2)
