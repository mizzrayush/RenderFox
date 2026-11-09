"""
Video export contract test (Phase 15c-2).

The Animation tab's "Render Video" promises an MP4, and the exporter used to believe
the promise on the strength of ffmpeg's exit code and the .mp4 extension. Neither is
evidence: ffmpeg can exit 0 having written nothing, or written a container that is not
the H.264 MP4 the dialog claimed. This suite proves the written file is read back for
its real ISO-BMFF boxes - an ftyp, a moov, and an avc1/avc3 sample entry inside the
movie box - and that every shortfall is refused with the reason that reaches the
Animation tab's QMessageBox. Nothing here renders or runs ffmpeg: Popen is mocked and
the containers are hand-built bytes, so the read-back is the only thing under test.

Run: python -X utf8 tests/test_video_export_contract.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from PyQt6.QtWidgets import QApplication, QWidget

from src.core.video_exporter import VideoExporter, _iso_boxes, _container_verdict


def box(kind, payload):
    """One ISO-BMFF box: 4-byte big-endian size, 4-byte type, then the payload."""
    return (8 + len(payload)).to_bytes(4, 'big') + kind.encode('latin-1') + payload


def h264_mp4(codec=b'avc1'):
    """A minimal but real-shaped H.264 MP4: ftyp, a moov carrying the codec, mdat."""
    ftyp = box('ftyp', b'isom\x00\x00\x02\x00isomiso2avc1mp41')
    moov = box('moov', b'\x00\x00\x00\x08trak' + codec + b'\x00\x00\x00\x00')
    mdat = box('mdat', b'\x00' * 16)
    return ftyp + moov + mdat


class VideoCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.work = tempfile.mkdtemp(prefix='renderfox_video_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def verdict(self, data):
        path = os.path.join(self.work, 'verdict.mp4')
        with open(path, 'wb') as handle:
            handle.write(data)
        return _container_verdict(path)

    def run_render(self, output_bytes, returncode=0, stderr=b''):
        """Drive render() with a mocked ffmpeg and a pre-written output file.

        Popen does nothing, so whatever bytes are on disk are what the read-back
        judges - exactly the seam where a returncode-0 encode that wrote garbage
        used to be reported as a saved render.
        """
        output_path = os.path.join(self.work, 'shot.mp4')
        if os.path.exists(output_path):
            os.remove(output_path)
        if output_bytes is not None:
            with open(output_path, 'wb') as handle:
                handle.write(output_bytes)
        process = mock.MagicMock()
        process.returncode = returncode
        process.communicate.return_value = (b'', stderr)
        exporter = VideoExporter()
        results = []
        exporter.finished.connect(lambda ok, msg: results.append((ok, msg)))
        viewport = QWidget()
        viewport.resize(64, 64)
        with mock.patch('src.core.video_exporter.subprocess.Popen', return_value=process):
            exporter.render(viewport=viewport, output_path=output_path,
                            start_frame=0, end_frame=0, fps=30)
        viewport.deleteLater()
        return results


class TestTheBoxWalker(VideoCase):
    def test_01_walks_the_top_level_boxes(self):
        data = box('ftyp', b'isom') + box('moov', b'trak') + box('mdat', b'xyz')
        self.assertEqual([('ftyp', 8, 12), ('moov', 20, 24), ('mdat', 32, 35)],
                         _iso_boxes(data))

    def test_02_reads_a_64_bit_extended_size(self):
        payload = b'abcd'
        true_size = 16 + len(payload)
        data = (1).to_bytes(4, 'big') + b'ftyp' + true_size.to_bytes(8, 'big') + payload
        self.assertEqual([('ftyp', 16, 20)], _iso_boxes(data))

    def test_03_reads_a_box_that_runs_to_the_end(self):
        data = (0).to_bytes(4, 'big') + b'mdat' + b'xyz'
        self.assertEqual([('mdat', 8, 11)], _iso_boxes(data))

    def test_04_stops_at_a_box_that_overruns_the_file(self):
        data = (100).to_bytes(4, 'big') + b'ftyp' + b'isom'
        self.assertEqual([], _iso_boxes(data))


class TestTheContainerVerdict(VideoCase):
    def test_05_a_real_h264_mp4_is_accepted(self):
        ok, sentence = self.verdict(h264_mp4())
        self.assertTrue(ok)
        self.assertIn('H.264', sentence)

    def test_06_a_missing_file_is_refused(self):
        path = os.path.join(self.work, 'never_written.mp4')
        if os.path.exists(path):
            os.remove(path)
        ok, sentence = _container_verdict(path)
        self.assertFalse(ok)
        self.assertIn('no file', sentence)

    def test_07_an_empty_file_is_refused(self):
        ok, sentence = self.verdict(b'')
        self.assertFalse(ok)
        self.assertIn('empty', sentence)

    def test_08_a_file_with_no_ftyp_is_refused(self):
        ok, sentence = self.verdict(box('moov', b'trakavc1') + box('mdat', b'\x00' * 16))
        self.assertFalse(ok)
        self.assertIn('ftyp', sentence)

    def test_09_a_file_with_no_moov_is_refused(self):
        ok, sentence = self.verdict(box('ftyp', b'isom') + box('mdat', b'avc1' + b'\x00' * 12))
        self.assertFalse(ok)
        self.assertIn('moov', sentence)

    def test_10_a_file_with_no_h264_track_is_refused(self):
        ok, sentence = self.verdict(box('ftyp', b'isom') + box('moov', b'trakmp4v')
                                    + box('mdat', b'\x00' * 16))
        self.assertFalse(ok)
        self.assertIn('H.264', sentence)

    def test_11_an_avc1_only_in_the_mdat_is_not_a_track(self):
        ok, sentence = self.verdict(box('ftyp', b'isom') + box('moov', b'trak')
                                    + box('mdat', b'avc1' + b'\x00' * 12))
        self.assertFalse(ok)
        self.assertIn('H.264', sentence)

    def test_12_an_avc3_track_is_accepted_too(self):
        ok, sentence = self.verdict(h264_mp4(codec=b'avc3'))
        self.assertTrue(ok)
        self.assertIn('H.264', sentence)


class TestTheRenderReadsItBack(VideoCase):
    def test_13_a_written_h264_mp4_finishes_true(self):
        results = self.run_render(h264_mp4())
        self.assertEqual(1, len(results))
        self.assertTrue(results[0][0])

    def test_14_a_returncode_zero_with_an_empty_file_finishes_false(self):
        results = self.run_render(b'')
        self.assertEqual(1, len(results))
        self.assertFalse(results[0][0])

    def test_15_a_returncode_zero_with_a_non_mp4_finishes_false_naming_ftyp(self):
        results = self.run_render(box('moov', b'trakavc1') + box('mdat', b'\x00' * 16))
        self.assertEqual(1, len(results))
        self.assertFalse(results[0][0])
        self.assertIn('ftyp', results[0][1])

    def test_16_a_nonzero_returncode_names_h264(self):
        results = self.run_render(None, returncode=1, stderr=b'Unknown encoder libx264')
        self.assertEqual(1, len(results))
        self.assertFalse(results[0][0])
        self.assertIn('H.264', results[0][1])

    def test_17_the_success_message_carries_the_verdict(self):
        results = self.run_render(h264_mp4())
        self.assertTrue(results[0][0])
        self.assertIn('container read back', results[0][1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
