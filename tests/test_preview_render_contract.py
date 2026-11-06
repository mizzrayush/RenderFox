"""
Preview raster contract test - `src/processing/preview_render.py`.

The Pipeline pane's Render and Thumbnail nodes are the last surface in Phase 6 that reports
work it does not do (`pipeline_engine.py:843-845` logs "Rendering not fully implemented,
skipping" and returns `True`). Before that engine can be rewritten, the picture it would
produce has to be measured on this machine rather than assumed, because four of this
module's rules are things Open3D 0.19 on Windows does differently from its own docs:

- `OffscreenRenderer` does not start here (`EGL Headless is not supported`), so the Filament
  path is out and the legacy invisible `Visualizer` is the only raster.
- The `extrinsic` the Visualizer wants is not the plain look-at basis. Its own baseline is
  `diag(1,-1,-1)`, so the rows are `[right, -vertical, forward]`; the textbook basis puts the
  camera behind the model looking away and every frame comes back as nothing but background.
- A field of view survives only when `parameters.intrinsic.intrinsic_matrix` is written in
  place. Building a fresh `PinholeCameraIntrinsic` measured a degenerate projection: the model
  filled every pixel with one flat colour and no fov changed the picture at all.
- `options.light_on` must stay off. With the engine's own head light on, lit faces clip to 255
  and a dim lamp and a bright one print identical pixels - the lamp node would be decoration.

And three things about the file, not the frame: the window will not open narrower than 148 px
nor larger than the desktop, `o3d.geometry.Image` cannot write a PNG here so the encoders are
Pillow's, and every number in the verdict is counted from the written file re-opened from disk.

Four of these rules cannot be proven through a window at all, because when the line is wrong
Open3D kills the process and a dead process reports no failing test: a mesh painted with the
point-cloud channel, an extrinsic that puts the eye behind the model, a fitted eye that sits
inside the geometry, and a camera whose position is the point it looks at. `SeamCase` reaches
them through the module's own seams - four pure helpers and `_place` driven by a control that
only records what the product writes - and `WrittenFileCase` reaches the two verdict rules that
a real frame never produces by accident: a file that re-reads as nothing but background, and a
silhouette one pixel wide.

Run: python -X utf8 tests/test_preview_render_contract.py
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import open3d as o3d
import trimesh
from PIL import Image

# open3d warns on every faceless .ply its mesh reader is handed, which this suite does on
# purpose (a scan has vertices and no triangles, and drawing it is the point).
o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.processing import preview_render as pr

SOURCE = open(os.path.join(ROOT, 'src', 'processing', 'preview_render.py'),
              encoding='utf-8').read()

TMP = None
BOX = TALL = WIDE = PLAIN_CLOUD = RGB_CLOUD = EMPTY = None
_CACHE = {}


def setUpModule():
    global TMP, BOX, TALL, WIDE, PLAIN_CLOUD, RGB_CLOUD, EMPTY
    TMP = tempfile.mkdtemp(prefix='rf_preview_contract_')
    BOX = _box('box.obj', (1.0, 1.0, 0.6))
    TALL = _box('tall.obj', (0.2, 0.2, 6.0))
    WIDE = _box('wide.obj', (8.0, 0.5, 0.5))
    PLAIN_CLOUD = os.path.join(TMP, 'plain.ply')
    trimesh.PointCloud(np.random.default_rng(4).normal(size=(4000, 3))).export(PLAIN_CLOUD)
    RGB_CLOUD = os.path.join(TMP, 'rgbc.ply')
    cloud = trimesh.PointCloud(np.random.default_rng(3).normal(size=(6000, 3)) * 2)
    cloud.colors = np.random.default_rng(7).integers(0, 256, size=(6000, 3), dtype=np.uint8)
    cloud.export(RGB_CLOUD)
    EMPTY = os.path.join(TMP, 'empty.obj')
    with open(EMPTY, 'w', encoding='utf-8') as handle:
        handle.write('# nothing\n')


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def _box(name, extents):
    path = os.path.join(TMP, name)
    trimesh.creation.box(extents=list(extents)).export(path)
    return path


def render(geometry=None, width=400, height=400, name=None, reuse=True, out_path=None,
           **kwargs):
    """One frame, and one file per distinct ask.

    The output name carries a hash of the settings on purpose: when it did not, two tests that
    asked for the same file at different sizes overwrote each other, and the verdict read back
    from disk stopped matching the picture its own numbers described.
    """
    geometry = geometry or BOX
    label = name or (os.path.splitext(os.path.basename(geometry))[0] + '.png')
    stem = os.path.splitext(label)[0]
    extension = os.path.splitext(label)[1].lstrip('.') or 'png'
    settings = repr((geometry, width, height,
                     sorted((key, str(value)) for key, value in kwargs.items())))
    if out_path is None:
        tag = hashlib.sha1(settings.encode('utf-8')).hexdigest()[:10]
        out_path = os.path.join(TMP, f'{stem}_{tag}.{extension}')
    key = (out_path, settings)
    if reuse and key in _CACHE:
        return _CACHE[key]
    verdict = pr.render_file(geometry, out_path, width, height, **kwargs)
    _CACHE[key] = verdict
    return verdict


def pixels(verdict):
    return np.asarray(Image.open(verdict['path']).convert('RGB'))


def changed(verdict, other):
    a, b = pixels(verdict), pixels(other)
    if a.shape != b.shape:
        b = np.asarray(Image.open(other['path']).convert('RGB').resize(
            (a.shape[1], a.shape[0])))
    return int((np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 12).sum())


def refusals(label, expected_substrings=()):
    """Assert the call raises PreviewError, and that the sentence names what it is about."""
    def decorator(test):
        def wrapped(self, *args, **kwargs):
            with self.subTest(label=label):
                try:
                    answer = test(self, *args, **kwargs)
                except pr.PreviewError as problem:
                    text = str(problem)
                    for piece in expected_substrings:
                        self.assertIn(piece, text, f'{label}: "{text}" did not say "{piece}"')
                    return
                self.fail(f'{label}: no refusal, got {answer}')
        wrapped.__name__ = test.__name__
        return wrapped
    return decorator


class FramingCase(unittest.TestCase):
    """A fitted camera shows the model, and the numbers describe the file that exists."""

    base = None

    @classmethod
    def setUpClass(cls):
        cls.base = render(width=640, height=480, name='base.png')

    def test_a_fitted_frame_shows_the_model_and_not_a_fill_or_a_background(self):
        verdict = type(self).base
        self.assertGreater(verdict['coverage_percent'], 1.0, 'nothing was drawn')
        self.assertLess(verdict['coverage_percent'], 95.0, 'the model filled every pixel')

    def test_the_size_and_bytes_reported_are_the_ones_on_disk(self):
        verdict = type(self).base
        with Image.open(verdict['path']) as written:
            self.assertEqual(written.size, (verdict['width'], verdict['height']))
            self.assertEqual(written.mode, verdict['mode'])
        self.assertEqual(verdict['bytes'], os.path.getsize(verdict['path']))
        self.assertGreater(verdict['bytes'], 0)

    def test_an_exact_ask_carries_no_apology_in_the_note(self):
        self.assertEqual(type(self).base['note'], '')

    def test_the_engine_light_stays_off_so_the_albedo_prints_its_own_value(self):
        # A vertex painted 0.72 must print 184; if the engine head light comes back on, the
        # lit faces clip to 255 and the lamp node stops being visible in the picture.
        verdict = type(self).base
        self.assertFalse(verdict['lit'])
        for value in verdict['mean_rgb']:
            self.assertAlmostEqual(value, 184, delta=4)
        self.assertLessEqual(verdict['distinct_colors'], 12, 'one flat shade is one flat colour')

    def test_the_raster_is_stable_so_two_runs_of_the_same_node_agree(self):
        first = render(width=320, height=320, name='stable_a.png', reuse=False)
        second = render(width=320, height=320, name='stable_b.png', reuse=False)
        with open(first['path'], 'rb') as handle:
            a = hashlib.sha256(handle.read()).hexdigest()
        with open(second['path'], 'rb') as handle:
            b = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(a, b, 'the same node drew two different pictures')

    def test_the_silhouette_is_measured_from_the_pixels_not_from_the_bounds(self):
        verdict = render(TALL, width=480, height=480, name='tall_frame.png')
        self.assertLessEqual(verdict['silhouette_height'], 480)
        self.assertGreater(verdict['silhouette_width'], 1)
        self.assertGreater(verdict['silhouette_height'], verdict['silhouette_width'],
                           'a 6-unit tall box came back wide')


class CameraCase(unittest.TestCase):
    """Every knob the camera node has to move the picture, or refuse to."""

    def test_moving_the_eye_changes_the_frame(self):
        base = render(width=640, height=480, name='base.png')
        for position in ((6, 0, 0), (4, 4, 4)):
            with self.subTest(position=position):
                other = render(width=640, height=480, name=f'cam_{position[0]}{position[1]}.png',
                               camera=pr.Camera(position=position))
                self.assertGreater(changed(base, other), 1000)

    def test_a_wide_lens_shrinks_the_model_and_a_tight_one_grows_it(self):
        base = render(width=640, height=480, name='base.png')
        wide = render(width=640, height=480, name='wide_lens.png', camera=pr.Camera(fov=90.0))
        tight = render(width=640, height=480, name='tight_lens.png', camera=pr.Camera(fov=15.0))
        self.assertLess(wide['silhouette_width'], base['silhouette_width'])
        self.assertGreater(tight['silhouette_width'], base['silhouette_width'])
        self.assertLess(tight['coverage_percent'], 95.0, 'fitting stopped working at fov 15')

    def test_fit_works_at_any_scale_the_pipeline_can_hand_it(self):
        for label, path in (('tall 6-unit box', TALL), ('wide 8-unit box', WIDE),
                            ('small box', BOX)):
            with self.subTest(model=label):
                verdict = render(path, 480, 480, name=f'fit_{os.path.basename(path)}.png')
                self.assertGreater(verdict['coverage_percent'], 1.0)
                self.assertLess(verdict['coverage_percent'], 92.0)
                self.assertLessEqual(verdict['silhouette_width'], 480)
                self.assertLessEqual(verdict['silhouette_height'], 480)

    def test_a_camera_aimed_away_from_the_model_is_a_refusal_not_an_empty_picture(self):
        # This is the sentence that catches the sign convention: hand the Visualizer the plain
        # look-at basis and it looks backwards, so every frame would be background only.
        verdict = None
        try:
            verdict = render(name='away.png', width=200, height=200, reuse=False,
                             camera=pr.Camera(position=(0, 0, 4000), target=(600, 0, 0),
                                              fit=False))
        except pr.PreviewError as problem:
            self.assertIn('nothing in it but the background', str(problem))
            return
        self.fail(f'an empty frame was reported as a render: {verdict}')

    @refusals('eye sitting on the point it looks at', ('stands on the point',))
    def test_an_eye_on_its_target_refuses(self):
        return render(name='on_target.png', width=200, height=200, reuse=False,
                      camera=pr.Camera(position=(0, 0, 0), target=(0, 0, 0), fit=False))

    @refusals('eye inside the model aimed at nothing', ('nothing in it but the background',))
    def test_an_eye_inside_the_model_refuses(self):
        return render(name='inside.png', width=200, height=200, reuse=False,
                      camera=pr.Camera(position=(0, 0, 0.01), fit=False))

    @refusals('unfitted camera with no position', ('has to say where its eye is',))
    def test_an_unfitted_camera_must_say_where_the_eye_is(self):
        return render(name='no_eye.png', width=200, height=200, reuse=False,
                      camera=pr.Camera(fit=False))

    @refusals('field of view below the drawable range', ('not a usable camera angle',))
    def test_a_field_of_view_too_tight_refuses(self):
        return render(name='fov_low.png', width=200, height=200, reuse=False,
                      camera=pr.Camera(fov=0.1))

    @refusals('field of view above the drawable range', ('not a usable camera angle',))
    def test_a_field_of_view_too_wide_refuses(self):
        return render(name='fov_high.png', width=200, height=200, reuse=False,
                      camera=pr.Camera(fov=171.0))

    def test_both_ends_of_the_usable_range_still_draw(self):
        for fov in (1.0, 170.0):
            with self.subTest(fov=fov):
                verdict = render(name=f'fov_{fov}.png', width=300, height=300,
                                 camera=pr.Camera(fov=fov))
                self.assertGreater(verdict['covered_pixels'], 0)


class LightCase(unittest.TestCase):
    """The lamp node is only real if its numbers move the pixels, in order."""

    def test_more_intensity_is_a_brighter_picture_and_never_a_clipped_one(self):
        totals = []
        for intensity in (0.0, 0.25, 0.5, 1.0, 2.0):
            verdict = render(name=f'intensity_{intensity}.png',
                             light=pr.Light(kind='directional', position=(0, 0, 5),
                                            intensity=intensity, ambient=0.0))
            totals.append(sum(verdict['mean_rgb']))
        self.assertEqual(len(totals), 5)
        for low, high in zip(totals, totals[1:]):
            self.assertLess(low, high, f'intensity did not move the picture: {totals}')

    def test_a_lamp_behind_the_model_is_darker_than_one_in_front(self):
        front = render(name='lamp_front.png',
                       light=pr.Light(kind='directional', position=(0, 0, 5), intensity=1.0,
                                      ambient=0.0))
        back = render(name='lamp_back.png',
                      light=pr.Light(kind='directional', position=(0, 0, -5), intensity=1.0,
                                     ambient=0.0))
        self.assertLess(sum(back['mean_rgb']), sum(front['mean_rgb']) * 0.5)

    def test_the_lamp_colour_lands_in_the_pixels(self):
        red = render(name='lamp_red.png', light=pr.Light(color=(1.0, 0.1, 0.1)))
        self.assertGreater(red['mean_rgb'][0], red['mean_rgb'][1] * 4)

    def test_a_point_lamp_gets_brighter_as_it_gets_closer(self):
        far = render(name='point_far.png',
                     light=pr.Light(kind='point', position=(0, 0, 6), intensity=6.0,
                                    ambient=0.0))
        near = render(name='point_near.png',
                      light=pr.Light(kind='point', position=(0, 0, 2), intensity=6.0,
                                     ambient=0.0))
        self.assertGreater(sum(near['mean_rgb']), sum(far['mean_rgb']))

    def test_a_wider_cone_lights_more_of_the_picture_than_a_tight_one(self):
        tight = render(name='spot_tight.png',
                       light=pr.Light(kind='spot', position=(2.2, 0, 0), cone=8.0,
                                      intensity=4.0, ambient=0.0))
        wide = render(name='spot_wide.png',
                      light=pr.Light(kind='spot', position=(2.2, 0, 0), cone=70.0,
                                     intensity=4.0, ambient=0.0))
        self.assertGreater(sum(wide['mean_rgb']), sum(tight['mean_rgb']))

    def test_ambient_carries_the_picture_when_the_lamp_is_off(self):
        only = render(name='ambient.png',
                      light=pr.Light(kind='directional', intensity=0.0, ambient=0.4))
        for value in only['mean_rgb']:
            self.assertAlmostEqual(value, 102, delta=8)

    @refusals('a lamp kind this build cannot draw', ('directional, point and spot',))
    def test_an_hdri_lamp_refuses_by_name(self):
        return render(name='hdri.png', width=200, height=200, reuse=False,
                      light=pr.Light(kind='hdri'))

    @refusals('a lamp aimed at a cloud', ('the file is points',))
    def test_a_lamp_on_a_cloud_refuses_because_there_is_no_surface_to_light(self):
        return render(PLAIN_CLOUD, name='lamp_on_cloud.png', width=200, height=200,
                      reuse=False, light=pr.Light())


class DisplayCase(unittest.TestCase):
    """Each display mode draws, and the verdict says what reached the file."""

    def test_every_display_mode_draws_something(self):
        for mode in pr.DISPLAY_MODES:
            with self.subTest(mode=mode):
                verdict = render(name=f'mode_{mode}.png', width=320, height=320,
                                display_mode=mode)
                self.assertEqual(verdict['display_mode'], mode)
                self.assertGreater(verdict['covered_pixels'], 0)

    def test_a_normals_map_separates_the_faces_a_flat_shade_cannot(self):
        flat = render(name='base.png', width=320, height=320)
        normals = render(name='normals.png', width=320, height=320, display_mode='normals')
        self.assertGreater(normals['distinct_colors'], flat['distinct_colors'] * 4)

    def test_a_height_map_is_a_ramp(self):
        height = render(TALL, name='height.png', width=320, height=320, display_mode='height')
        self.assertGreater(height['distinct_colors'], 100)

    @refusals('a display mode this build does not draw', ('is not a display mode',))
    def test_an_unknown_display_mode_refuses_with_the_list(self):
        return render(name='clay.png', width=200, height=200, reuse=False,
                      display_mode='clay')

    @refusals('normals asked of a cloud', ('no faces to take a normal from',))
    def test_normals_mode_refuses_a_faceless_file(self):
        return render(PLAIN_CLOUD, name='cloud_normals.png', width=200, height=200,
                      reuse=False, display_mode='normals')


class PointCloudCase(unittest.TestCase):
    """A scan has vertices and no triangles, and is still a picture."""

    def test_a_faceless_ply_is_drawn_as_points(self):
        verdict = render(PLAIN_CLOUD, name='cloud.png', width=400, height=400)
        self.assertEqual(verdict['kind'], 'points')

    def test_a_coloured_cloud_keeps_its_own_colours(self):
        verdict = render(RGB_CLOUD, name='rgb_cloud.png', width=400, height=400)
        self.assertGreater(verdict['distinct_colors'], 200)

    def test_a_cloud_can_be_shown_by_height(self):
        verdict = render(PLAIN_CLOUD, name='cloud_height.png', width=400, height=400,
                         display_mode='height')
        self.assertGreater(verdict['distinct_colors'], 100)

    def test_an_uncoloured_cloud_in_object_mode_still_draws(self):
        verdict = render(PLAIN_CLOUD, name='cloud_plain_object.png', width=400, height=400,
                         display_mode='object')
        self.assertGreater(verdict['covered_pixels'], 0)

    def test_the_point_size_reaches_the_frame(self):
        small = render(PLAIN_CLOUD, name='points_small.png', width=400, height=400,
                       point_size=1.0)
        large = render(PLAIN_CLOUD, name='points_large.png', width=400, height=400,
                       point_size=9.0)
        self.assertGreater(large['covered_pixels'], small['covered_pixels'])


class FormatAndSizeCase(unittest.TestCase):
    """The file the caller asked for is the file that exists, or the reason it does not."""

    def test_every_format_this_build_encodes_round_trips_at_the_asked_size(self):
        for extension in ('png', 'jpg', 'tif', 'bmp', 'webp'):
            with self.subTest(format=extension):
                verdict = render(name=f'format.{extension}', width=300, height=240)
                self.assertEqual((verdict['width'], verdict['height']), (300, 240))
                self.assertGreater(verdict['bytes'], 0)

    def test_a_window_this_machine_will_not_open_is_resampled_and_said(self):
        tiny = render(name='tiny.png', width=32, height=16)
        self.assertEqual((tiny['width'], tiny['height']), (32, 16))
        self.assertEqual(tiny['window_opened'][0], pr.MIN_WINDOW_WIDTH)
        self.assertIn('window at 148x16', tiny['note'])

    def test_an_ask_beyond_the_desktop_yields_the_ask_and_names_the_window(self):
        huge = render(name='huge.png', width=4000, height=2400)
        self.assertEqual((huge['width'], huge['height']), (4000, 2400))
        self.assertGreater(huge['bytes'], 1000)
        self.assertIn('window at', huge['note'])

    def test_an_absurd_ask_is_capped_and_says_what_the_cap_is(self):
        # Drawing 8192x8192 to prove the cap costs more than the rule is worth: the ceiling is
        # patched to 900 so the same branch is the one under test, and the sentence names it.
        ceiling = pr.MAX_WINDOW
        pr.MAX_WINDOW = 900
        try:
            verdict = render(name='capped.png', width=99999, height=99999, reuse=False)
        finally:
            pr.MAX_WINDOW = ceiling
        self.assertEqual((verdict['width'], verdict['height']), (900, 900))
        self.assertEqual(verdict['asked_width'], 99999)
        self.assertIn('capped at 900 px', verdict['note'])

    def test_supersample_draws_one_frame_at_the_multiple_and_reports_it(self):
        """The multiple is a bigger window folded down, and the verdict says which one ran."""
        verdict = render(name='ss2.png', width=200, height=200, supersample=2)
        self.assertEqual((verdict['width'], verdict['height']), (200, 200))
        self.assertEqual([400, 400], verdict['window_opened'],
                         'the frame was not drawn at twice the edge')
        self.assertEqual(2, verdict['supersample'])
        self.assertEqual(2, verdict['supersample_asked'])
        self.assertIn('one frame was drawn at 2x the edge', verdict['note'])

    def test_a_supersample_that_will_not_fit_is_cut_and_says_so(self):
        ceiling = pr.MAX_WINDOW
        pr.MAX_WINDOW = 900
        try:
            verdict = render(name='sscut.png', width=300, height=300, supersample=4,
                             reuse=False)
        finally:
            pr.MAX_WINDOW = ceiling
        self.assertEqual(3, verdict['supersample'], 'the multiple that could not open is '
                                                    'reported as though it did')
        self.assertEqual(4, verdict['supersample_asked'])
        self.assertEqual((verdict['width'], verdict['height']), (300, 300))
        self.assertIn('supersample was cut from 4x to 3x', verdict['note'])

    def test_transparency_accounts_for_every_pixel_in_the_file(self):
        verdict = render(name='transparent.png', width=400, height=400, light=pr.Light(),
                         transparent=True)
        self.assertEqual(verdict['mode'], 'RGBA')
        self.assertEqual(verdict['transparent_pixels'] + verdict['covered_pixels'], 400 * 400)
        self.assertGreater(verdict['transparent_pixels'], 400 * 400 * 0.3)

    def test_an_exr_is_refused_and_the_refusal_lists_what_this_build_can_write(self):
        self.assertNotIn('exr', pr.IMAGE_FORMATS)
        out = os.path.join(TMP, 'want.exr')
        with self.assertRaises(pr.PreviewError) as caught:
            render(width=200, height=200, reuse=False, out_path=out)
        sentence = str(caught.exception)
        self.assertIn('.exr', sentence)
        for extension in pr.IMAGE_FORMATS:
            self.assertIn(extension, sentence)
        self.assertFalse(os.path.exists(out), 'a refusal must not leave a file behind')

    @refusals('transparency asked of a jpg', ('no alpha channel',))
    def test_a_jpg_refuses_transparency_instead_of_losing_it_silently(self):
        return render(name='trans.jpg', width=200, height=200, reuse=False, transparent=True)

    @refusals('a folder that is not there', ('is not a folder on this disk',))
    def test_a_missing_folder_refuses_before_anything_is_drawn(self):
        return render(name='missing_folder.png', width=200, height=200, reuse=False,
                      out_path=os.path.join(TMP, 'no', 'y.png'))

    @refusals('a geometry file that is not there', ('is not a file on this disk',))
    def test_a_missing_model_refuses(self):
        return render(os.path.join(TMP, 'gone.obj'), name='gone.png', width=200, height=200,
                      reuse=False)

    @refusals('a file with neither triangles nor points',
              ('neither triangles nor points',))
    def test_an_empty_geometry_file_refuses(self):
        return render(EMPTY, name='empty_frame.png', width=200, height=200, reuse=False)


class StopCase(unittest.TestCase):
    """A pipeline that is stopped says which picture is the last one, not none at all."""

    def test_a_stop_before_the_frame_writes_nothing(self):
        out = os.path.join(TMP, 'stopped_before.png')
        with self.assertRaises(pr.PreviewError) as caught:
            pr.render_file(BOX, out, 200, 200, should_cancel=lambda: True)
        self.assertIn('stopped before a frame', str(caught.exception))
        self.assertFalse(os.path.exists(out))

    def test_a_stop_after_the_write_reports_the_file_that_is_on_disk(self):
        out = os.path.join(TMP, 'stopped_after.png')
        asked = []

        def stop_second_time():
            asked.append(1)
            return len(asked) > 1

        with self.assertRaises(pr.PreviewError) as caught:
            pr.render_file(BOX, out, 200, 200, should_cancel=stop_second_time)
        self.assertIn('was written and then the run was stopped', str(caught.exception))
        self.assertGreaterEqual(len(asked), 2, 'the frame was never asked for')
        self.assertTrue(os.path.isfile(out))


class SeamCase(unittest.TestCase):
    """The five rules a window would take the process down before it could report them.

    Each of these is the answer to a mutation that the sweep could only detect by killing
    the suite - the Open3D window segfaults on a nan camera and on a mesh painted as points,
    so no `FAIL:` line is ever printed and no test owns the defect. The lines below are the
    same code paths through the seams the module already has: `_extrinsic`, `_fit_distance`,
    `_display_colors` and `_paint` are pure, and `_place` is driven by a stand-in that keeps
    whatever the product writes into the camera parameters. Nothing here tests a stand-in's
    behaviour; each asserts what the product produced, and reverting any of these lines makes
    the named test go red inside a process that finishes.
    """

    class _Intrinsic:
        def __init__(self):
            self.intrinsic_matrix = np.eye(3)

    class _Parameters:
        def __init__(self):
            self.extrinsic = np.eye(4)
            self.intrinsic = SeamCase._Intrinsic()

    class _Control:
        """The two methods `_place` calls on the view control, keeping what it hands back."""

        def __init__(self):
            self.received = None

        def convert_to_pinhole_camera_parameters(self):
            return SeamCase._Parameters()

        def convert_from_pinhole_camera_parameters(self, parameters, allow_arbitrary=False):
            self.received = parameters

    class _Window:
        def __init__(self):
            self.control = SeamCase._Control()

        def get_view_control(self):
            return self.control

    class _Bounds:
        def __init__(self, low, high):
            self._low = np.asarray(low, dtype=float)
            self._high = np.asarray(high, dtype=float)

        def get_min_bound(self):
            return self._low

        def get_max_bound(self):
            return self._high

    def place(self, camera, low=(-1.0, -1.0, -0.6), high=(1.0, 1.0, 0.6), width=400, height=300):
        window = SeamCase._Window()
        pr._place(window, SeamCase._Bounds(low, high), camera, width, height)
        return window.control.received

    def test_the_extrinsic_puts_the_eye_at_the_camera_origin_and_its_target_in_front(self):
        """The eye is the origin of its own frame, and what it looks at sits at positive z."""
        for eye, target, up in (((0.0, 0.0, 3.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
                                ((2.0, -1.0, 0.5), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
                                ((0.0, 0.0, 0.0), (4.0, 4.0, 4.0), (0.0, 0.0, 1.0))):
            with self.subTest(eye=eye):
                matrix = pr._extrinsic(np.asarray(eye), np.asarray(target), np.asarray(up))
                eye_in_its_own_frame = matrix @ np.append(np.asarray(eye, float), 1.0)
                self.assertEqual(np.round(eye_in_its_own_frame, 9).tolist(), [0.0, 0.0, 0.0, 1.0],
                                 'the extrinsic does not travel with the eye')
                ahead = matrix @ np.append(np.asarray(target, float), 1.0)
                self.assertGreater(ahead[2], 0.0, 'the point looked at sits behind the camera')

    def test_the_fitted_distance_projects_the_whole_bounding_sphere_inside_the_frame(self):
        for fov in (15.0, 45.0, 90.0):
            for width, height in ((400, 400), (640, 480)):
                with self.subTest(fov=fov, size=(width, height)):
                    radius = 1.0
                    distance = pr._fit_distance(radius, fov, width, height)
                    self.assertGreater(distance, radius, 'the fitted eye is inside the model')
                    focal = (height / 2.0) / np.tan(np.radians(fov) / 2.0)
                    projected = focal * radius / distance
                    self.assertLessEqual(projected, height / 2.0,
                                         'the sphere leaves the frame top and bottom')
                    self.assertLessEqual(projected, width / 2.0, 'the sphere leaves the sides')

    def test_the_coordinate_maps_ramp_on_the_axis_their_names_promise(self):
        expected = {'x_coordinate': 0, 'y_coordinate': 1, 'z_coordinate': 2, 'height': 2}
        for mode, axis in expected.items():
            with self.subTest(mode=mode):
                points = np.zeros((24, 3))
                points[:, axis] = np.linspace(0.0, 5.0, 24)
                ramp = pr._display_colors(None, mode, points, None)[:, 0]
                self.assertGreater(ramp[-1] - ramp[0], 0.9,
                                   f'{mode} did not ramp along axis {axis}')
                self.assertTrue(bool(np.all(np.diff(ramp) > 0.0)), f'{mode} ramp is not ordered')
        # `height` means the vertical extent, so a column that varies only in x is flat.
        sideways = np.zeros((24, 3))
        sideways[:, 0] = np.linspace(0.0, 5.0, 24)
        colors = pr._display_colors(None, 'height', sideways, None)
        self.assertAlmostEqual(float(colors[:, 0].max() - colors[:, 0].min()), 0.0,
                               msg='the height map ramped along an axis that is not the height')

    def test_a_surface_is_painted_with_vertex_colours_and_not_point_colours(self):
        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices = o3d.utility.Vector3dVector(
            np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]]))
        mesh.triangles = o3d.utility.Vector3iVector([[0, 1, 2], [1, 3, 2]])
        pr._paint(mesh, 'surface', np.full((4, 3), 0.25))
        self.assertTrue(mesh.has_vertex_colors(), 'a mesh was handed the point-cloud channel')
        self.assertEqual(np.round(np.asarray(mesh.vertex_colors), 6).tolist(),
                         [[0.25, 0.25, 0.25]] * 4)

    def test_the_pinhole_matrix_puts_the_principal_point_at_the_centre_of_the_frame(self):
        for width, height, fov in ((640, 480, 45.0), (320, 200, 60.0)):
            with self.subTest(size=(width, height)):
                written = self.place(pr.Camera(fov=fov), width=width, height=height)
                intrinsic = written.intrinsic.intrinsic_matrix
                self.assertEqual(float(intrinsic[0, 2]), width / 2.0,
                                 'the model is drawn off to one side of its own picture')
                self.assertEqual(float(intrinsic[1, 2]), height / 2.0,
                                 'the model is drawn off the middle, vertically')
                focal = (height / 2.0) / np.tan(np.radians(fov) / 2.0)
                self.assertAlmostEqual(float(intrinsic[0, 0]), float(focal), places=6)
                self.assertAlmostEqual(float(intrinsic[1, 1]), float(focal), places=6)

    def test_a_fitted_camera_placed_on_the_point_it_looks_at_refuses(self):
        with self.assertRaises(pr.PreviewError) as caught:
            self.place(pr.Camera(position=(0.0, 0.0, 0.0), target=(0.0, 0.0, 0.0), fit=True))
        self.assertIn('no direction to look in', str(caught.exception))

    def test_an_unfitted_camera_on_the_point_it_looks_at_refuses(self):
        with self.assertRaises(pr.PreviewError) as caught:
            self.place(pr.Camera(position=(0.0, 0.0, 0.0), target=(0.0, 0.0, 0.0), fit=False))
        self.assertIn('no direction to look in', str(caught.exception))


class WrittenFileCase(unittest.TestCase):
    """The two verdict rules that only the file on disk can show, forced without a window."""

    def test_a_file_that_rereads_as_only_background_refuses(self):
        """What the encoder actually wrote is the answer, not the buffer it was handed."""
        from PIL import Image as PilImage
        original = pr._write

        def write_flat_background(image, alpha, out_path):
            flat = np.full(image.shape, np.round(np.asarray([0.12, 0.12, 0.14]) * 255),
                           dtype=np.uint8)
            PilImage.fromarray(flat).save(out_path)

        out = os.path.join(TMP, 'flat_background.png')
        pr._write = write_flat_background
        try:
            with self.assertRaises(pr.PreviewError) as caught:
                pr.render_file(BOX, out, 200, 200)
        finally:
            pr._write = original
        self.assertIn('nothing but the background', str(caught.exception))
        self.assertIn('re-read from disk', str(caught.exception))

    def test_a_one_column_wide_silhouette_is_one_pixel_wide(self):
        """A bounds inclusive of both ends: one lit column is one pixel, not zero."""
        original = pr._capture
        frame = np.tile(np.round(np.asarray([0.12, 0.12, 0.14]) * 255).astype(np.uint8),
                        (200, 200, 1))
        frame[:, 77] = (200, 120, 40)
        pr._capture = lambda geometry, width, height, camera, background, point_size: (
            frame.copy(), (width, height))
        out = os.path.join(TMP, 'one_column.png')
        try:
            verdict = pr.render_file(BOX, out, 200, 200)
        finally:
            pr._capture = original
        self.assertEqual(verdict['silhouette_width'], 1,
                         'a single lit column measured as nothing wide')
        self.assertEqual(verdict['silhouette_height'], 200)
        self.assertEqual(verdict['covered_pixels'], 200)


class SourceContractCase(unittest.TestCase):
    """Four rules a green run cannot show, because Open3D answers them silently.

    Each one was found by the picture going wrong, not by reading: revert any of them and the
    frames above come back empty, flat, or full-size-and-wrong.
    """

    def test_the_engine_head_light_is_never_turned_on(self):
        self.assertIn('options.light_on = False', SOURCE)
        self.assertNotIn('light_on = True', SOURCE)

    def test_the_field_of_view_is_written_into_the_matrix_that_is_live(self):
        self.assertIn('parameters.intrinsic.intrinsic_matrix = intrinsic', SOURCE)
        self.assertNotIn('parameters.intrinsic = o3d.camera.PinholeCameraIntrinsic', SOURCE,
                         'a fresh PinholeCameraIntrinsic measures a degenerate projection')

    def test_the_extrinsic_rows_keep_the_sign_the_visualizer_expects(self):
        self.assertIn('np.vstack([right, -vertical, forward])', SOURCE,
                      'the plain look-at basis makes the camera look backwards')

    def test_the_window_is_always_destroyed_even_when_the_frame_raises(self):
        self.assertIn('finally:', SOURCE)
        self.assertIn('visualizer.destroy_window()', SOURCE)
        self.assertLess(SOURCE.index('finally:'), SOURCE.index('visualizer.destroy_window()'))

    def test_the_verdict_is_measured_from_the_written_file_and_not_the_buffer(self):
        self.assertIn("'width': measured_width", SOURCE)
        self.assertIn("'bytes': os.path.getsize(out_path)", SOURCE)
        self.assertIn("Image.open(out_path)", SOURCE)
        self.assertNotIn("'width': final_width", SOURCE)

    def test_the_module_never_claims_a_capability_it_does_not_have(self):
        for word in ('ray trace', 'path tracing', 'global illumination', 'shadow map'):
            self.assertNotIn(word, SOURCE.lower(), f'{word}: this raster does not do that')


if __name__ == '__main__':
    unittest.main(verbosity=2)
