"""Contract for channel-packed texture output."""

import os
import shutil
import sys
import tempfile
import unittest

from PIL import Image
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.processing.texture_packer import ChannelPacker
from src.ui.texture_generator import TextureGeneratorDialog


class TexturePackerCase(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.work = tempfile.mkdtemp(prefix='renderfox_channel_pack_')

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def mask(self, name, value, size=(3, 2)):
        path = os.path.join(self.work, name)
        Image.new('L', size, value).save(path)
        return path

    def test_orm_bands_are_written_and_read_back(self):
        output = os.path.join(self.work, 'crate_orm.png')
        result = ChannelPacker.pack(output, {'red': self.mask('ao.png', 31),
                                             'green': self.mask('rough.png', 127),
                                             'blue': self.mask('metal.png', 219)})
        self.assertTrue(result.success, result.message)
        self.assertEqual((3, 2), result.size)
        with Image.open(output) as written:
            self.assertEqual('RGBA', written.mode)
            self.assertEqual((31, 127, 219, 255), written.getpixel((1, 1)))

    def test_missing_bands_get_documented_defaults(self):
        output = os.path.join(self.work, 'roughness.png')
        result = ChannelPacker.pack(output, {'green': self.mask('rough.png', 64)})
        self.assertTrue(result.success, result.message)
        with Image.open(output) as written:
            self.assertEqual((0, 64, 0, 255), written.getpixel((0, 0)))

    def test_mismatched_masks_are_refused_without_an_output(self):
        output = os.path.join(self.work, 'bad.png')
        result = ChannelPacker.pack(output, {'red': self.mask('a.png', 1),
                                             'green': self.mask('b.png', 2, (2, 2))})
        self.assertFalse(result.success)
        self.assertIn('resize masks', result.message)
        self.assertFalse(os.path.exists(output))

    def test_no_source_and_unknown_channel_are_refused(self):
        self.assertIn('at least one', ChannelPacker.pack(os.path.join(self.work, 'x.png'), {}).message)
        self.assertIn('unknown', ChannelPacker.pack(os.path.join(self.work, 'x.png'),
                                                     {'depth': 'nope.png'}).message)

    def test_texture_dialog_exposes_and_runs_the_same_packer(self):
        dialog = TextureGeneratorDialog()
        try:
            output = os.path.join(self.work, 'dialog_orm.png')
            dialog.channel_inputs['red'].setText(self.mask('ao.png', 12))
            dialog.channel_inputs['green'].setText(self.mask('rough.png', 34))
            with mock.patch('src.ui.texture_generator.QFileDialog.getSaveFileName',
                            return_value=(output, 'PNG Image (*.png)')), \
                 mock.patch('src.ui.texture_generator.QMessageBox.information') as shown:
                dialog.pack_channels()
            self.assertEqual(output, dialog.generated_image_path)
            self.assertTrue(os.path.isfile(output))
            self.assertIn('PNG read back', shown.call_args.args[2])
        finally:
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
