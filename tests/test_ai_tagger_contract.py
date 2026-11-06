"""AI Asset Tagger contract test.

The tagger's category and its descriptive tags are decided by CLIP, and CLIP is shown a
picture, so this suite is about the picture. It exists because of how that picture used to
be made, measured here rather than remembered: trimesh's `save_image` does render on the
main thread of this machine, in 0.58 s, and answers a worker thread in 0.06 s with
`RuntimeError: EventLoop.run() must be called from the same thread that imports pyglet.app`
- and `analyze_model` runs on a worker, so the Open3D `Visualizer` behind the `except` was
the branch always taken. That window answers the first time a process opens one and never
answers again once another GL window has existed: the headless tab suite's tagging row was
still owed after 180 seconds, with the thread's own stack sitting in `poll_events` at
`ai_asset_tagger.py:232`, while the same call in a fresh process took 1.5 seconds. The pane's
progress bar had nothing to report and no verb could stop it, because a worker blocked inside
a native call answers no cancellation. The rendering half is worth recording too: when
`save_image` did answer, it answered with 2 colours over the whole 224x224 frame - a flat
silhouette, which is what CLIP's category was a judgement about.

What it draws with now is `generate_3d_thumbnail`, the software raster the Library and the
Automation already use, so the app has one picture maker instead of three, and a tagging run
started after a preview cannot hang. Two numbers are pinned alongside it: the claim
`ai_powered` is only made when a frame actually reached CLIP, and the preview file is the
app's own temp folder's, written and re-opened and then gone.

Run: python -X utf8 tests/test_ai_tagger_contract.py
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import trimesh
from PIL import Image
from PyQt6.QtWidgets import QApplication

from src.features.ai_asset_tagger import AIAssetTagger
from src.utils import thumbnail_renderer
from src.utils.file_utils import get_temp_directory

app = QApplication.instance() or QApplication([])


def counting_visualizer():
    """Replace `open3d.visualization.Visualizer` with a counter that still builds one.

    The wrapper is a function, not a subclass: Open3D's classes do not all allow deriving,
    and a shim that refused outright would make the test pass for the wrong reason if the
    call ever moved somewhere the shim cannot see. Answers the real class to put back and
    the list a construction is counted into.
    """
    import open3d as o3d
    real = o3d.visualization.Visualizer
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    o3d.visualization.Visualizer = counted
    return real, calls


class TestAITaggerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix='rfx_tagger_contract_')
        cls.tagger = AIAssetTagger()

        cls.asset = os.path.join(cls.temp_dir, 'crate.obj')
        trimesh.creation.box(extents=(2.0, 2.0, 3.0)).export(cls.asset)

        cls.uncached = sorted(
            name for name in os.listdir(get_temp_directory())
            if name.startswith('rfx_tagger_preview_'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        for name in os.listdir(get_temp_directory()):
            if name.startswith('rfx_tagger_preview_'):
                os.remove(os.path.join(get_temp_directory(), name))

    def test_01_the_preview_is_the_picture_the_raster_wrote(self):
        """A file in, a picture of that file out: real pixels, the asked size, nothing left.

        The three facts are the ones a caller cannot infer from a return type. An image that
        is one flat colour is a window that never drew; an image kept open is a file the next
        export cannot overwrite; and a picture that costs minutes is the defect this replaced.
        """
        began = time.time()
        image = self.tagger._render_model_preview(self.asset)
        spent = time.time() - began

        self.assertIsNotNone(image, 'the software raster answered with no picture at all')
        self.assertEqual('RGB', image.mode, 'CLIP was handed a mode it does not take')
        self.assertEqual((224, 224), image.size, 'the frame is not the size that was asked for')
        pixels = np.asarray(image)
        self.assertGreater(len(np.unique(pixels.reshape(-1, 3), axis=0)), 3,
                           f'the frame is one flat colour, so nothing of the model is in it')
        self.assertLess(spent, 20.0,
                        f'the picture took {spent:.1f}s; a draw that hangs is the defect here')
        left = [name for name in os.listdir(get_temp_directory())
                if name.startswith('rfx_tagger_preview_')]
        self.assertEqual(self.uncached, left,
                         f'the preview file was left behind: {left[:4]}')
        print(f'✓ The tagger drew its frame in {spent:.2f}s: '
              f'{image.size[0]}x{image.size[1]}, {len(np.unique(pixels.reshape(-1, 3), axis=0))} colours.')

    def test_02_no_gl_window_is_opened_to_tag_a_model(self):
        """`analyze_model` on a live tagger, with every Open3D window counted.

        The hang this suite exists for was a second GL window in one process, so the pin is
        that the tagger opens none - counted on the real class rather than asserted from the
        source, because a call that moved into a helper would still hang. The analysis still
        has to answer, with CLIP having really run: that is what `ai_powered` claims.
        """
        import open3d as o3d
        real, calls = counting_visualizer()
        try:
            began = time.time()
            analysis = self.tagger.analyze_model(self.asset)
            spent = time.time() - began
        finally:
            o3d.visualization.Visualizer = real

        self.assertEqual([], calls,
                         f'the tagger opened {len(calls)} Open3D window(s); a second one in a '
                         f'process is what never comes back')
        self.assertNotIn('error', analysis, 'the run reported a failure')
        self.assertTrue(analysis.get('tags'), 'the tagger answered with no tags')
        self.assertIn('category', analysis, 'the tagger answered with no category')
        self.assertTrue(analysis.get('ai_powered'),
                        'CLIP ran over a real frame but the verdict does not say so')
        self.assertIn('ai_category', analysis,
                      'ai_powered is made and no category came out of CLIP')
        self.assertLess(spent, 60.0, f'the tagging run took {spent:.1f}s')
        print(f'✓ A tagging run opened no GL window and answered in {spent:.2f}s '
              f'({len(analysis["tags"])} tags, category {analysis["category"]}).')

    def test_03_a_draw_the_raster_refuses_is_reported_as_one(self):
        """No picture is a fact the verdict has to carry, not a silent AI claim.

        The refusal here is the honest shape a refusal takes in this app: the raster does
        leave a file at the path it was handed, and that file is its own empty backdrop -
        pixels of one flat colour, with none of the model in it, which is exactly why it
        answers `rendered: False, faces: 0`. Reading only the file would call that a
        picture of the crate, and CLIP would be shown a square of grey and reported its
        opinion with `ai_powered` next to it. So what is pinned is that the tagger asks the
        raster whether the model arrived before it asks a file.

        Without a frame there is nothing for CLIP to judge, and the verdict has to fall
        back to the geometry alone - with `ai_powered` staying the False it was set to,
        because nothing was powered by anything here.
        """
        real = thumbnail_renderer.generate_3d_thumbnail
        refused = {'success': False, 'rendered': False, 'faces': 0,
                   'error': 'the model has no faces to draw'}

        def refusing(*args, **kwargs):
            out_path = args[1] if len(args) > 1 else kwargs.get('output_path')
            if out_path:
                Image.new('RGB', (224, 224), (128, 128, 128)).save(out_path)
            return refused

        thumbnail_renderer.generate_3d_thumbnail = refusing
        try:
            self.assertIsNone(self.tagger._render_model_preview(self.asset),
                              'a draw the raster refused still handed the caller a picture, '
                              'so the verdict is not what decides what a frame is')
            analysis = self.tagger.analyze_model(self.asset)
        finally:
            thumbnail_renderer.generate_3d_thumbnail = real

        self.assertNotIn('error', analysis, 'the run reported a failure instead of a fallback')
        self.assertIn('category', analysis, 'no category came from the geometry either')
        self.assertFalse(analysis.get('ai_powered'),
                         'the verdict claims CLIP judged a frame of the model, and the only '
                         'file the refusing raster left is one flat colour')
        self.assertNotIn('ai_descriptive_tags', analysis,
                         'descriptive tags are claimed without a frame behind them')
        left = [name for name in os.listdir(get_temp_directory())
                if name.startswith('rfx_tagger_preview_')]
        self.assertEqual(self.uncached, left, f'the refused draw left its file behind: {left[:4]}')
        print('✓ A draw the raster refused is refused even though a file is sitting there, '
              'and the geometry answers alone.')

    def test_04_the_module_keeps_no_second_renderer(self):
        """The Open3D fallback is gone from the file, not merely bypassed by a branch.

        A second copy of the same window a conditional away is the shape this suite started
        in, and it is invisible to any test that only ever exercises the good path - which is
        why the source itself is the thing read here. The names are taken from the syntax
        tree rather than from the text, because this file's own explanation is full of the
        words the code is no longer allowed to contain.
        """
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path('src/features/ai_asset_tagger.py').read_text(encoding='utf-8'))
        names = set()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.alias):
                imported.add(node.name)
        for needle in ('open3d', 'o3d', 'Visualizer', 'save_image', 'capture_screen', 'pyglet'):
            self.assertNotIn(needle, names | imported,
                             f'the tagger still reaches for {needle}; a second raster is still in here')
        self.assertNotIn('io', imported,
                         '`io` was only ever read by the GL bytes this file no longer makes')
        print('✓ The tagger holds one picture maker: no Open3D, no trimesh window, no leftover import.')


if __name__ == '__main__':
    unittest.main()
