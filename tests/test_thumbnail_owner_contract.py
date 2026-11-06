"""One picture maker, and the two files that opened a window to make one are gone.

This suite exists because the app had **three** ways to draw a model into a small image and
two of them opened an Open3D window to do it. `src/core/thumbnail_generator.py` built an
`o3d.visualization.Visualizer` in a `QThread` per file, and `src/features/version_control.py`
built one on the caller's thread - which for the Versions pane's Commit button is the
interface thread, so the whole window waited on a GL context and its `destroy_window` sat
after the capture, meaning any raise in between left the window alive. Phase 6m measured what
the same shape costs in another pane: 392 s with the progress bar still spinning, and a
`cancel()` flag a thread blocked inside a native call never reads. Both of those files drew
with the QPainter raster the Library, the Automation and the tagger already use, and the grid
module that started the first one is now deleted - `src/ui/library_grid.py` was constructed by
nothing in the app, so the thread never ran and the claim that it was live was wrong until
this file made it checkable.

What is asked, in order: that the deleted pair stays deleted and no module names it; that
every function which writes a model picture calls `generate_3d_thumbnail` and holds no Open3D
node - and that it is still exactly those five functions, so a sixth way of drawing a model
has to be measured before it can ship; that the Open3D window survives only where it is the
product (the viewer, the Pipeline's tested capture, the point picker) and in no `src/features/`
or `src/core/` module; that a committed version records a picture **of the snapshot the row
points at**, named for it and byte-identical to what the raster draws for it, so two versions
of one model cannot share a picture and a version cannot be shown the other model's; that a
file with nothing to draw is refused with the raster's own reason and leaves no badge sitting
in the thumbnails folder - a wireframe crate standing in for a model that was never drawn is
the lie this phase exists to stop; that the Versions pane paints the recorded picture, updates
it when the selection moves, and names which kind of nothing a row has - never selected, never
drawn, or drawn and now unreadable - and that the sentence a refusal speaks is itself what
takes the previous picture down, a QLabel answer the pane now leans on and so measured here
instead of trusted; and that a model file which is not on disk is refused by
that fact rather than by an exception the pane swallows.

Run: python -X utf8 tests/test_thumbnail_owner_contract.py
"""

import ast
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel

from src.features.version_control import AssetVersionControl
from src.ui.version_control_ui import VersionControlUI
from src.utils.thumbnail_renderer import generate_3d_thumbnail

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

DELETED = ('src/core/thumbnail_generator.py', 'src/ui/library_grid.py')

# Measured 2026-11-07 by walking every `src/` file's syntax tree for a call whose target
# names the raster. A sixth entry is allowed only after the new picture maker has been
# measured - which is the point of the assertion, not an obstacle to it.
PICTURE_MAKERS = (
    ('src/core/library_manager.py', '_ensure_thumbnail_placeholder'),
    ('src/features/automation_engine.py', 'make_thumbnail'),
    ('src/features/ai_asset_tagger.py', '_render_model_preview'),
    ('src/features/version_control.py', '_generate_thumbnail'),
    ('src/ui/library_tab.py', 'load_thumbnail'),
)

# The windows that stay, each because it is the product rather than a stand-in for a
# thumbnail: the viewer the Mesh Tools, Point Clouds, Quality and Version panes show, the
# Pipeline Render node's own capture with its contract suite, the click-to-select point
# picker, and one dead viewer module #10 has scheduled for deletion.
WINDOWS_THAT_STAY = {
    'src/processing/point_cloud_processor.py',
    'src/processing/preview_render.py',
    'src/ui/model_viewer_open3d.py',
    'src/ui/unified_viewer.py',
}

CUBE = (
    "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nv 1 0 1\nv 1 1 1\nv 0 1 1\n"
    "f 1 2 3\nf 1 3 4\nf 5 7 6\nf 5 8 7\nf 1 5 6\nf 1 6 2\n"
    "f 2 6 7\nf 2 7 3\nf 3 7 8\nf 3 8 4\nf 4 8 5\nf 4 5 1\n"
)


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, '/')


def source_text(relative):
    with open(os.path.join(ROOT, *relative.split('/')), encoding='utf-8') as handle:
        return handle.read()


def source_tree(relative):
    return ast.parse(source_text(relative))


def python_files(directory):
    base = os.path.join(ROOT, directory)
    for folder, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            if name.endswith('.py'):
                yield rel(os.path.join(folder, name))


def find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def call_targets(node):
    return [ast.unparse(child.func) for child in ast.walk(node) if isinstance(child, ast.Call)]


def fingerprint(image, samples=16):
    """One brightness sample per cell of a grid over the whole image.

    Relative coordinates, because the picture on screen is scaled and the file it came from
    is not; a fixed step would sample different parts of the two.
    """
    cells = []
    for row in range(samples):
        y = (row * 2 + 1) * image.height() // (samples * 2)
        for column in range(samples):
            x = (column * 2 + 1) * image.width() // (samples * 2)
            pixel = image.pixel(x, y)
            cells.append(((pixel >> 16 & 255) + (pixel >> 8 & 255) + (pixel & 255)) // 3)
    return cells


def distance(left, right):
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


class TestThumbnailOwnerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='renderfox_6p_')

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def write(self, name, text=''):
        path = os.path.join(self.home, name)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def engine_at(self, name='library'):
        return AssetVersionControl(os.path.join(self.home, name))

    def window_openers(self):
        openers = set()
        for relative in python_files('src'):
            for node in ast.walk(source_tree(relative)):
                if not isinstance(node, ast.Call):
                    continue
                target = ast.unparse(node.func)
                if ('visualization.Visualizer' in target
                        or 'OffscreenRenderer' in target
                        or 'capture_screen' in target):
                    openers.add(relative)
                    break
        return openers

    def test_01_the_deleted_pair_stays_deleted_and_no_module_names_it(self):
        for relative in DELETED:
            self.assertFalse(os.path.exists(os.path.join(ROOT, *relative.split('/'))),
                             f'{relative} is back on disk')

        importers = []
        for directory in ('src', 'tests', 'tools'):
            for relative in python_files(directory):
                for node in ast.walk(source_tree(relative)):
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or '']
                    else:
                        continue
                    for name in names:
                        if name.endswith('thumbnail_generator') or name.endswith('library_grid'):
                            importers.append((relative, name))
        self.assertEqual([], importers,
                         'a module imports the deleted pair, so the Open3D thumbnail thread '
                         'is one import away from running again')

        # A lazy `importlib` or a string entry point would be invisible to the walk above, so
        # no file that ships inside the app may even name the pair.
        named = [relative for relative in python_files('src')
                 if 'thumbnail_generator' in source_text(relative)
                 or 'library_grid' in source_text(relative)]
        self.assertEqual([], named, 'the app still carries a reference to the deleted pair')

    def test_02_every_picture_the_app_writes_comes_from_the_one_raster(self):
        callers = set()
        for relative in python_files('src'):
            for node in ast.walk(source_tree(relative)):
                if isinstance(node, ast.Call) and ast.unparse(node.func) == 'generate_3d_thumbnail':
                    callers.add(relative)
                    break
        self.assertEqual({maker[0] for maker in PICTURE_MAKERS}, callers,
                         'the set of files that draw a model picture changed without being '
                         'measured')

        for relative, function_name in PICTURE_MAKERS:
            with self.subTest(picture_maker=f'{relative}::{function_name}'):
                function = find_function(source_tree(relative), function_name)
                self.assertIsNotNone(function, f'{relative} no longer defines {function_name}')
                targets = call_targets(function)
                self.assertIn('generate_3d_thumbnail', targets,
                              f'{function_name} no longer asks the raster for the picture')
                windows = [target for target in targets if 'o3d' in target or 'open3d' in target]
                self.assertEqual([], windows,
                                 f'{function_name} opens an Open3D window again: {windows}')

    def test_03_no_open3d_window_survives_in_a_backend_or_a_pane(self):
        openers = self.window_openers()
        self.assertEqual(WINDOWS_THAT_STAY, openers,
                         'the files that open an Open3D window are not the measured four')
        self.assertNotIn('src/features/version_control.py', openers,
                         'the Versions pane commits on the interface thread, so a window '
                         'opened there freezes the whole app')
        for relative in sorted(openers):
            self.assertFalse(relative.startswith(('src/features/', 'src/core/')),
                             f'{relative} opens a window in the layer the app runs its '
                             'workers in')

    def test_04_a_committed_version_records_a_picture_of_its_own_snapshot(self):
        model = self.write('cube.obj', CUBE)
        engine = self.engine_at()

        first = engine.save_version(model, commit_message='first')
        self.assertIsNotNone(first, 'a real cube committed as nothing')
        # Snapshot names carry a timestamp to the second, so two commits inside one second
        # would share a snapshot file; the wait is what makes the second row a different
        # picture rather than the same bytes under a second name.
        time.sleep(1.05)
        self.write('cube.obj', CUBE.replace(' 1 1 1', ' 2 2 2').replace(' 0 0 1', ' 0 0 4'))
        second = engine.save_version(model, commit_message='second')
        self.assertIsNotNone(second, 'the changed cube committed as nothing')

        rows = {row['id']: row for row in engine.get_version_history(model)}
        newest, older = rows[second], rows[first]
        for row in (newest, older):
            with self.subTest(commit=row['commit_message']):
                path = row['thumbnail_path']
                self.assertTrue(path and os.path.exists(path),
                                f"v{row['version_number']} recorded no picture of a cube the "
                                f"raster can read")
                self.assertEqual(
                    os.path.splitext(os.path.basename(row['snapshot_path']))[0] + '.png',
                    os.path.basename(path),
                    'the picture is not named for the snapshot its row points at')
                image = QImage(path)
                self.assertFalse(image.isNull(), f'{path} is not a readable image')
                self.assertEqual((256, 256), (image.width(), image.height()))
                expected = os.path.join(self.home, f"verify_{row['version_number']}.png")
                outcome = generate_3d_thumbnail(row['snapshot_path'], expected, size=256)
                self.assertTrue(outcome['rendered'], outcome['error'])
                with open(expected, 'rb') as drawn, open(path, 'rb') as recorded:
                    self.assertEqual(drawn.read(), recorded.read(),
                                     'the recorded picture is not what the raster draws for '
                                     'this snapshot')
        self.assertNotEqual(newest['thumbnail_path'], older['thumbnail_path'],
                            'two versions of one model were given the same picture')

    def test_05_a_file_with_nothing_to_draw_is_refused_with_its_reason(self):
        engine = self.engine_at()
        # Two vertices and no face: the model loads, and there is no surface to picture.
        faceless = self.write('faceless.obj', 'v 0 0 0\nv 1 0 0\n')

        with self.assertLogs('src.features.version_control', level='WARNING') as captured:
            answer = engine._generate_thumbnail(faceless)
        self.assertIsNone(answer, 'a model that was never drawn recorded a picture anyway')
        self.assertTrue(any('holds no triangle mesh' in line for line in captured.output),
                        f'the refusal reached the log without the raster\'s reason: '
                        f'{captured.output}')

        # The premise the refusal is worth acting on: a refused draw still leaves a file, a
        # wireframe badge that looks like a crate. Without that the deletion below would be
        # guarding nothing, so it is measured rather than assumed.
        badge = os.path.join(self.home, 'badge.png')
        outcome = generate_3d_thumbnail(faceless, badge, size=64)
        self.assertFalse(outcome['rendered'], outcome['error'])
        self.assertTrue(os.path.exists(badge),
                        'the fixture is wrong: a refused draw leaves no badge file to delete')

        engine._generate_thumbnail(faceless)
        leftovers = sorted(os.listdir(engine.thumbnails_dir))
        self.assertEqual([], leftovers,
                         f'a refused draw left {leftovers} in the thumbnails folder, where a '
                         f'later row could pick one up')

    def test_06_the_versions_pane_paints_the_picture_its_row_records(self):
        model = self.write('cube.obj', CUBE)
        engine = self.engine_at()
        first = engine.save_version(model, commit_message='first')
        time.sleep(1.05)
        self.write('cube.obj', CUBE.replace(' 1 1 1', ' 3 3 3'))
        second = engine.save_version(model, commit_message='second')
        self.assertTrue(first and second, 'the fixture did not produce two versions')

        # `model_tab.py:513` hands the pane the engine it already owns, the same way.
        pane = VersionControlUI(os.path.join(self.home, 'pane_library'))
        pane.version_control = engine
        pane.load_model(model)
        self.app.processEvents()

        self.assertEqual(2, pane.version_tree.topLevelItemCount(),
                         'the pane listed something other than the two committed versions')

        # The picture has to be *in* the pane and beside the numbers it belongs to, or
        # everything below only proves that a label object somewhere can be painted.
        def ancestors(widget):
            chain = []
            node = widget
            while node is not None:
                chain.append(node)
                node = node.parentWidget()
            return chain

        self.assertIn(pane, ancestors(pane.version_picture),
                      'the picture the pane paints is not in the pane, so no one sees it')
        self.assertIs(pane.version_picture.parentWidget(), pane.details_text.parentWidget(),
                      "the row's picture is not shown beside its numbers")

        def select(row):
            pane.version_tree.setCurrentItem(pane.version_tree.topLevelItem(row))
            self.app.processEvents()
            return pane.version_picture

        newest = select(0)
        self.assertIsNotNone(newest.pixmap(), 'the newest row shows no picture at all')
        self.assertEqual((148, 148), (newest.pixmap().width(), newest.pixmap().height()))
        self.assertEqual('', newest.text())

        on_screen = fingerprint(newest.pixmap().toImage())
        own = fingerprint(QImage(pane.version_history[0]['thumbnail_path']))
        the_other_row = fingerprint(QImage(pane.version_history[1]['thumbnail_path']))
        # Measured here: the picture on screen sits 1.2 mean away from the file its row names
        # and 54.6 away from the other row's. The 1.2 is not sloppiness - `QPixmap` and
        # `QImage` scale through different paths, so a few edge pixels answer differently.
        self.assertLessEqual(distance(on_screen, own), 5,
                             'the pane painted something other than the picture its row names')
        self.assertLess(distance(on_screen, own), distance(on_screen, the_other_row),
                        'the pane is showing a row other than the selected one')

        older = select(1)
        self.assertIsNotNone(older.pixmap(), 'the older row shows no picture at all')
        self.assertNotEqual(fingerprint(older.pixmap().toImage()), on_screen,
                            'moving the selection left the previous row\'s picture on screen')

        # A row whose picture was never drawn says so, and does not keep the last one up.
        # `setCurrentItem` on the row that is already current fires nothing, so the selection
        # has to move for the pane to be asked again - and it has to have been showing a
        # picture first, or the clearing this asserts would have nothing to clear.
        #
        # The pane never calls `setPixmap` to take a picture down, so the answer it relies on
        # is Qt's own, and that answer is measured here rather than assumed: a sentence clears
        # the label's picture, an empty string does not, and painting a picture clears the
        # label's text. Were the first of these false, every refusal below would be showing
        # the newest row's picture under its words.
        probe = QLabel()
        probe.setPixmap(QPixmap(8, 8))
        probe.setText('a sentence')
        self.assertTrue(probe.pixmap().isNull(),
                        'QLabel no longer withdraws its picture when it is given a sentence, '
                        'so the refusals here would need their own clear')
        probe.setPixmap(QPixmap(8, 8))
        probe.setText('')
        self.assertFalse(probe.pixmap().isNull(),
                         'QLabel now clears its picture on an empty string, which is the one '
                         'path the picture branch takes')
        probe.setText('a sentence')
        probe.setPixmap(QPixmap(8, 8))
        self.assertEqual('', probe.text(),
                         'painting a picture no longer takes the old sentence off the label')

        pane.version_history[1]['thumbnail_path'] = None
        select(0)
        older = select(1)
        shown = older.pixmap()
        self.assertTrue(shown is None or shown.isNull(), 'a row with no picture still shows one')
        self.assertEqual('This version has no picture', older.text())

        # A row that names a file which is no longer there says *that*, not the same sentence.
        os.remove(pane.version_history[0]['thumbnail_path'])
        newest = select(0)
        shown = newest.pixmap()
        self.assertTrue(shown is None or shown.isNull(),
                        'a picture file that is gone still shows a picture')
        self.assertEqual('Its picture file could not be read', newest.text())

        pane.version_tree.clearSelection()
        self.app.processEvents()
        self.assertEqual('No version selected', pane.version_picture.text(),
                         'an empty selection spoke about a version that was not selected')

    def test_07_a_model_that_is_not_on_disk_is_refused_by_that_fact(self):
        engine = self.engine_at()
        missing = os.path.join(self.home, 'gone.obj')
        with self.assertLogs('src.features.version_control', level='ERROR') as captured:
            answer = engine.save_version(missing, commit_message='ghost')
        self.assertIsNone(answer)
        self.assertEqual([], engine.get_version_history(missing),
                         'a model that is not on disk still got a version row')
        self.assertTrue(any('Model not found' in line for line in captured.output),
                        f'the refusal reached the pane as an exception instead of as the fact '
                        f'it is: {captured.output}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
