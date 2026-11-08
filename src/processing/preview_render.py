"""The app's own raster: a model file in, a picture of that file out.

Blender, Unreal and Cinema4D are what make final images, and the render queue talks to those.
This is for the pictures RenderFox makes for itself: the preview the Pipeline's Render node
writes, and any thumbnail that has to exist without a DCC running. Nothing here is a lighting
engine - the frame is the geometry file's own triangles, shaded per vertex against the light
the camera node was given, drawn by the Open3D window that this machine can actually open
(no EGL headless here, so the Filament offscreen engine does not start on Windows).

Every number in the verdict is counted in the image file after it has been written and
re-opened from disk, so the picture the caller is told about is the picture that is there.
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

# Measured on this build with the Pillow that requirements.txt pins. Anything outside this
# list is refused by name rather than written and hoped for.
IMAGE_FORMATS = ('png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp')

# A window narrower than this is silently widened by the GLFW window class on this machine:
# asking for 32x16 measured 148x16. Rendering at the floor and saying so is honest; asking
# the caller to trust a width it never got is not.
MIN_WINDOW_WIDTH = 148
MIN_WINDOW_HEIGHT = 16
MAX_WINDOW = 8192

# How the surface is handed to the raster. Measured: with `light_on` left True the engine
# adds its own head light on top of whatever colour is in the vertices and clips the lit
# faces to 255, so a dim lamp and a bright one can print the same pixels. With the engine
# light off and the vertex colour chosen as the colour source, a vertex painted 0.9 prints
# 229 and one painted 0.15 prints 38 - the shade this module asked for, one flat colour per
# flat shade. That is the only pair that makes the lamp node's numbers visible.
SURFACE_SHADE = 'Color'
SURFACE_COLOR = 'Color'

DISPLAY_MODES = ('object', 'normals', 'height', 'x_coordinate', 'y_coordinate', 'z_coordinate')


class PreviewError(Exception):
    """No picture, and a sentence that says why - never a half-written file and a claim."""


@dataclass
class Camera:
    """Where the eye is.

    `fit=True` is the normal setting: the model's own bounding sphere decides how far back
    the eye sits for the requested field of view, so a 2 mm scan and a 2 km terrain both
    arrive whole in the frame. The direction, the up vector and the field of view stay the
    caller's. `fit=False` puts the eye exactly at `position`, which is how a saved camera is
    reproduced - and how a camera that misses the model entirely is drawn, so the verdict's
    coverage number can expose it.
    """
    position: Optional[Tuple[float, float, float]] = None
    target: Optional[Tuple[float, float, float]] = None
    up: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    fov: float = 45.0
    fit: bool = True
    direction: Tuple[float, float, float] = (1.0, 0.65, 1.0)

    def __post_init__(self):
        if not (1.0 <= float(self.fov) <= 170.0):
            raise PreviewError(f'a field of view of {self.fov} is not a usable camera angle; '
                               f'this build draws between 1 and 170 degrees')


@dataclass
class Light:
    """One lamp, Lambert-lit onto the geometry's own vertex normals."""
    kind: str = 'directional'
    position: Tuple[float, float, float] = (5.0, 10.0, 5.0)
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    ambient: float = 0.1
    cone: float = 45.0

    @property
    def direction(self) -> np.ndarray:
        vector = np.asarray(self.position, dtype=float)
        length = float(np.linalg.norm(vector))
        return vector / length if length > 1e-9 else np.array([0.0, 0.0, 1.0])


def renderer_blocker() -> Optional[str]:
    """Why this machine cannot draw a preview, or None when it can."""
    try:
        import open3d  # noqa: F401
    except Exception as problem:
        return f'Open3D is not usable here, and it is the only raster this build has: {problem}'
    try:
        from PIL import Image  # noqa: F401
    except Exception as problem:
        return f'Pillow is not usable here, so no image file could be written: {problem}'
    return None


def _luminance(normals: np.ndarray, points: np.ndarray, light: Light) -> np.ndarray:
    """How much of the lamp each vertex sees, in the light's own kind.

    A directional lamp is one vector for the whole mesh; a point lamp is a different vector
    per vertex, with the falloff the inverse-square law gives; a spot is a point lamp whose
    ray only counts inside the cone. All three clamp at zero, so the far side of the model
    goes to ambient and not to negative colour.
    """
    vector = np.asarray(light.position, dtype=float)
    if light.kind == 'directional':
        direction = light.direction
        return np.clip(normals @ direction, 0.0, 1.0) * float(light.intensity)
    if light.kind == 'point':
        to_light = vector[None, :] - points
        distance = np.linalg.norm(to_light, axis=1)
        safe = np.where(distance < 1e-6, 1e-6, distance)
        direction = to_light / safe[:, None]
        cosine = np.clip((normals * direction).sum(axis=1), 0.0, 1.0)
        return cosine * (light.intensity / (safe * safe))
    if light.kind == 'spot':
        axis = -vector / max(1e-9, float(np.linalg.norm(vector)))
        to_light = points - vector[None, :]
        distance = np.linalg.norm(to_light, axis=1)
        safe = np.where(distance < 1e-6, 1e-6, distance)
        from_lamp = to_light / safe[:, None]
        spread = np.clip(from_lamp @ axis, 0.0, 1.0)
        cone = np.cos(np.radians(max(1.0, float(light.cone))))
        inside = (spread >= cone).astype(float)
        cosine = np.clip((normals * -from_lamp).sum(axis=1), 0.0, 1.0)
        return cosine * inside * (light.intensity / (safe * safe))
    raise PreviewError(f'the preview renderer knows directional, point and spot lamps, '
                       f'not {light.kind}')


def _ramp(values: np.ndarray) -> np.ndarray:
    """One channel stretched across its own min..max, so a flat field is a flat picture."""
    low = float(values.min())
    high = float(values.max())
    if high - low < 1e-12:
        return np.full_like(values, 0.5)
    return (values - low) / (high - low)


def _display_colors(geometry, mode: str, points: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """The per-vertex colour a display mode asks for, in 0..1."""
    count = len(points)
    if mode == 'object':
        if normals is not None:
            if geometry.has_vertex_colors():
                return np.clip(np.asarray(geometry.vertex_colors, dtype=float), 0.0, 1.0)
        elif geometry.has_colors():
            return np.clip(np.asarray(geometry.colors, dtype=float), 0.0, 1.0)
        return np.full((count, 3), 0.72)
    if mode == 'normals':
        if normals is None:
            raise PreviewError('normals are only a display mode for a surface; the file the '
                               'preview was given has no faces to take a normal from')
        return np.clip(normals * 0.5 + 0.5, 0.0, 1.0)
    if mode in ('x_coordinate', 'y_coordinate', 'z_coordinate', 'height'):
        axis = {'x_coordinate': 0, 'y_coordinate': 1, 'z_coordinate': 2, 'height': 2}[mode]
        ramp = _ramp(points[:, axis])
        return np.stack([ramp, 1.0 - ramp, np.full(count, 0.45)], axis=1)
    raise PreviewError(f'{mode} is not a display mode this build draws; the modes are '
                       f'{", ".join(DISPLAY_MODES)}')


def _paint(geometry, kind: str, colors: np.ndarray) -> None:
    import open3d as o3d
    vectors = o3d.utility.Vector3dVector(np.clip(colors, 0.0, 1.0))
    if kind == 'surface':
        geometry.vertex_colors = vectors
    else:
        geometry.colors = vectors


def _read_geometry(path: str):
    import open3d as o3d
    mesh = o3d.io.read_triangle_mesh(path)
    if mesh.has_triangles():
        mesh.compute_vertex_normals()
        return mesh, 'surface'
    cloud = o3d.io.read_point_cloud(path)
    if cloud.has_points():
        return cloud, 'points'
    return None, None


def _fit_distance(radius: float, fov: float, width: int, height: int) -> float:
    """How far back the eye sits so the whole bounding sphere is inside the frame."""
    vertical = np.radians(float(fov))
    horizontal = 2.0 * np.arctan(np.tan(vertical / 2.0) * (width / float(height)))
    limiting = min(vertical, horizontal)
    return radius / max(1e-6, np.sin(limiting / 2.0)) * 1.05


def _extrinsic(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    """The 4x4 the Visualizer calls `extrinsic`.

    Measured, not assumed: the baseline that `reset_view_point` leaves behind, with the eye on
    +Z looking at the origin and world up +Y, is diag(1, -1, -1). So the rows are
    [right, -up, forward] - the image y axis points down the screen and the camera looks down
    +z of its own frame. Handing it the plain look-at basis instead puts the camera looking
    away from the model and every frame comes back as nothing but background.
    """
    forward = target - eye
    forward = forward / float(np.linalg.norm(forward))
    right = np.cross(forward, up)
    if float(np.linalg.norm(right)) < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    right = right / float(np.linalg.norm(right))
    vertical = np.cross(right, forward)
    rotation = np.vstack([right, -vertical, forward])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = rotation @ (-eye)
    return matrix


def _place(visualizer, geometry, camera: Camera, width: int, height: int):
    """Point the window's camera exactly where the Camera says, at the exact field of view."""
    import open3d as o3d
    points = np.asarray(geometry.get_min_bound(), dtype=float)
    extents = np.asarray(geometry.get_max_bound(), dtype=float) - points
    center = points + extents / 2.0
    radius = float(np.linalg.norm(extents)) / 2.0
    target = np.asarray(camera.target, float) if camera.target is not None else center
    if camera.fit:
        if camera.position is not None:
            direction = np.asarray(camera.position, float) - target
        else:
            direction = np.asarray(camera.direction, float)
        length = float(np.linalg.norm(direction))
        if length < 1e-9:
            raise PreviewError('the camera gives a position on top of the point it looks at, '
                               'so there is no direction to look in')
        eye = target + direction / length * _fit_distance(radius, camera.fov, width, height)
    else:
        if camera.position is None:
            raise PreviewError('a camera that is not fitted to the model has to say where its '
                               'eye is')
        eye = np.asarray(camera.position, float)
        if float(np.linalg.norm(eye - target)) < 1e-9:
            raise PreviewError('the camera stands on the point it looks at, so there is no '
                               'direction to look in')
    control = visualizer.get_view_control()
    parameters = control.convert_to_pinhole_camera_parameters()
    parameters.extrinsic = _extrinsic(eye, target, np.asarray(camera.up, float))
    focal = (height / 2.0) / np.tan(np.radians(camera.fov) / 2.0)
    # The matrix is edited where it lies. Building a fresh `PinholeCameraIntrinsic` and handing
    # that back measured a degenerate projection: the model filled every pixel with one flat
    # colour, and no field of view changed the picture at all.
    intrinsic = np.array(parameters.intrinsic.intrinsic_matrix, dtype=float, copy=True)
    intrinsic[0, 0] = intrinsic[1, 1] = focal
    intrinsic[0, 2] = width / 2.0
    intrinsic[1, 2] = height / 2.0
    parameters.intrinsic.intrinsic_matrix = intrinsic
    control.convert_from_pinhole_camera_parameters(parameters, allow_arbitrary=True)
    return eye, target, radius


def _capture(geometry, width: int, height: int, camera: Camera, background_rgb,
             point_size: float) -> Tuple[np.ndarray, Tuple[int, int]]:
    """One frame of one geometry, through a window that exists only for this call.

    Answers the pixels and the size the window really opened at, which on this machine is not
    always the size that was asked: it will not open narrower than 148, and it will not open
    larger than the desktop. A size it will not open at all is a `PreviewError` naming it, not
    an option write on a renderer that was never made.
    """
    import open3d as o3d
    visualizer = o3d.visualization.Visualizer()
    opened = visualizer.create_window(visible=False, width=int(width), height=int(height))
    try:
        if not opened:
            # `get_render_option()` answers None until a window exists, so without this line a
            # machine that will not open one reaches `options.light_on` and raises
            # AttributeError - a crash leaving no picture and no sentence about it, which is
            # the one thing this module's own rule refuses.
            raise PreviewError(f'this machine would not open the {int(width)}x{int(height)} '
                               'window this raster draws into, so there is no picture and '
                               'nothing was written')
        visualizer.add_geometry(geometry)
        options = visualizer.get_render_option()
        options.light_on = False
        options.background_color = np.asarray(background_rgb, dtype=float)
        options.point_size = float(point_size)
        if isinstance(geometry, o3d.geometry.TriangleMesh):
            options.mesh_shade_option = getattr(o3d.visualization.MeshShadeOption, SURFACE_SHADE)
            options.mesh_color_option = getattr(o3d.visualization.MeshColorOption, SURFACE_COLOR)
        else:
            options.point_color_option = getattr(o3d.visualization.PointColorOption,
                                                 'Color' if geometry.has_colors() else 'Default')
        visualizer.reset_view_point(True)
        visualizer.poll_events()
        visualizer.update_renderer()
        _place(visualizer, geometry, camera, width, height)
        visualizer.poll_events()
        visualizer.update_renderer()
        frame = np.asarray(visualizer.capture_screen_float_buffer(do_render=True))
        pixels = np.clip(frame[:, :, :3] * 255.0, 0.0, 255.0).astype(np.uint8)
        return pixels, (int(pixels.shape[1]), int(pixels.shape[0]))
    finally:
        visualizer.destroy_window()


def _resample(pixels: np.ndarray, width: int, height: int) -> np.ndarray:
    """Stretch the frame the window did open to the size that was asked for."""
    from PIL import Image
    # No `mode=` argument: Pillow deprecates passing it, and an uint8 (h, w, 3) array already
    # infers RGB.
    picture = Image.fromarray(pixels)
    return np.asarray(picture.resize((int(width), int(height)), Image.Resampling.LANCZOS))


def _write(image: np.ndarray, alpha: Optional[np.ndarray], out_path: str) -> None:
    from PIL import Image
    if alpha is None:
        picture = Image.fromarray(image.astype(np.uint8))
    else:
        rgba = np.dstack([image.astype(np.uint8), alpha.astype(np.uint8)])
        picture = Image.fromarray(rgba)
    folder = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(folder):
        raise PreviewError(f'{folder} is not a folder on this disk, so no picture can be '
                           f'written into it')
    try:
        picture.save(out_path)
    except Exception as problem:
        raise PreviewError(f'{os.path.basename(out_path)} was not written: '
                           f'{type(problem).__name__}: {problem}')
    # `Image.save` answers None whether it worked or not, so the file itself decides.
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise PreviewError(f'{os.path.basename(out_path)} is not on disk after the write')


def render_file(geometry_path: str, out_path: str, width: int = 1920, height: int = 1080,
                camera: Optional[Camera] = None, light: Optional[Light] = None,
                background: Tuple[float, float, float] = (0.12, 0.12, 0.14),
                transparent: bool = False, point_size: float = 3.0,
                display_mode: str = 'object', should_cancel=None,
                supersample: int = 1) -> Dict[str, Any]:
    """Draw `geometry_path` into `out_path` and report what the written file says about itself.

    Raises `PreviewError` with the reason instead of returning a picture that was never
    drawn: a file that is the wrong size, or one whose every pixel is the background colour,
    is not a render of anything.

    `supersample` is how many times the size of the picture the frame is drawn at before it
    is filtered back down. There is one raster here and it draws one frame per call, so the
    samples are not N exposures averaged together - the geometry is drawn once at N times the
    edge and a Lanczos filter folds N x N pixels into one, which is what removes the staircase
    on a diagonal edge. The verdict says which multiple actually ran, because this machine
    will not open a window past the ceiling.
    """
    blocked = renderer_blocker()
    if blocked:
        raise PreviewError(blocked)
    if not os.path.isfile(geometry_path):
        raise PreviewError(f'{os.path.basename(geometry_path)} is not a file on this disk')
    if should_cancel is not None and should_cancel():
        raise PreviewError('stopped before a frame was drawn, so no picture was written')

    extension = os.path.splitext(out_path)[1].lower().lstrip('.')
    if extension not in IMAGE_FORMATS:
        returnable = ', '.join(IMAGE_FORMATS)
        raise PreviewError(f'a preview cannot be written as .{extension} here - this build '
                           f'encodes {returnable}')

    asked_width, asked_height = int(width), int(height)
    # The file the caller asked for is the file they get, so long as it is inside the ceiling.
    # The *window* is a separate matter: this machine will not open one narrower than 148, and
    # will not open one larger than the desktop, so the frame is drawn at the size the window
    # realises and then resampled to the size that was asked for.
    final_width = int(min(MAX_WINDOW, max(1, asked_width)))
    final_height = int(min(MAX_WINDOW, max(1, asked_height)))
    samples_asked = max(1, int(supersample))
    # The enlarged frame is the thing that has to fit under the ceiling, so the multiple is
    # cut to the largest one that does rather than opened short and reported as if it ran.
    ceiling = MAX_WINDOW // max(1, final_width, final_height)
    samples = max(1, min(samples_asked, ceiling))
    draw_width, draw_height = final_width * samples, final_height * samples
    window_width = int(min(MAX_WINDOW, max(MIN_WINDOW_WIDTH, draw_width)))
    window_height = int(min(MAX_WINDOW, max(MIN_WINDOW_HEIGHT, draw_height)))
    camera = camera or Camera()

    geometry, kind = _read_geometry(geometry_path)
    if geometry is None:
        raise PreviewError(f'{os.path.basename(geometry_path)} gave the reader neither '
                           f'triangles nor points, so there is nothing to draw')

    points = np.asarray(geometry.points if kind == 'points' else geometry.vertices, dtype=float)
    normals = np.asarray(geometry.vertex_normals, dtype=float) if kind == 'surface' else None
    colors = _display_colors(geometry, display_mode, points, normals)
    if light is not None and kind == 'surface':
        lit = _luminance(normals, points, light)
        tint = np.asarray(light.color, dtype=float)
        colors = np.clip(tint[None, :] * (lit[:, None] + float(light.ambient)), 0.0, 1.0)
    elif light is not None and kind == 'points':
        raise PreviewError('a lamp has no surface to fall on here: the file is points, so the '
                           'preview lights surfaces and this has none')
    _paint(geometry, kind, colors)

    background_rgb = tuple(float(value) for value in background)
    frame, (open_width, open_height) = _capture(geometry, window_width, window_height, camera,
                                                background_rgb, point_size)
    reasons = []
    if (open_width, open_height) != (draw_width, draw_height):
        reasons.append(f'this machine opened its window at {open_width}x{open_height} rather '
                       f'than the {draw_width}x{draw_height} this picture needed (it will not '
                       f'go below {MIN_WINDOW_WIDTH}x{MIN_WINDOW_HEIGHT} or above the '
                       f'desktop), so the frame was drawn at the size it did open')
    if (open_width, open_height) != (final_width, final_height):
        frame = _resample(frame, final_width, final_height)
    if samples > 1:
        reasons.append(f'one frame was drawn at {samples}x the edge and filtered back down '
                       f'to {final_width}x{final_height}')
    if (final_width, final_height) != (asked_width, asked_height):
        reasons.append(f'the picture is capped at {MAX_WINDOW} px, not the {asked_width}x'
                       f'{asked_height} asked for')
    if samples_asked != samples:
        reasons.append(f'supersample was cut from {samples_asked}x to {samples}x so the frame '
                       f'still fits under the {MAX_WINDOW} px ceiling')
    note = ' '.join(reasons)

    background_pixel = np.round(np.asarray(background_rgb) * 255).astype(np.uint8)
    differs = (frame != background_pixel).any(axis=2)
    if int(differs.sum()) == 0:
        raise PreviewError(f'the frame for {os.path.basename(geometry_path)} came back with '
                           f'nothing in it but the background colour - the camera is not '
                           f'looking at the model')

    alpha = None
    if transparent:
        if extension in ('jpg', 'jpeg'):
            raise PreviewError(f'.{extension} has no alpha channel in any encoder this build '
                               f'has, so a transparent picture cannot be written to it')
        alpha = np.where(differs, 255, 0).astype(np.uint8)

    _write(frame, alpha, out_path)

    # Everything below is counted in the file on disk, not in the buffer that was handed to the
    # encoder: a JPEG that drops the alpha it was given, or a PNG that re-quantises the frame,
    # has to be reported as the file it is.
    from PIL import Image
    with Image.open(out_path) as written:
        written.load()
        measured_width, measured_height = written.size
        mode = written.mode
        pixels = np.asarray(written.convert('RGB' if alpha is None else 'RGBA'))
    final = pixels[:, :, :3]
    differs = (final != background_pixel).any(axis=2)
    covered = int(differs.sum())
    if covered == 0:
        raise PreviewError(f'{os.path.basename(out_path)} holds nothing but the background '
                           f'colour once it is re-read from disk')
    distinct = int(len(np.unique(pixels.reshape(-1, pixels.shape[-1]), axis=0)))
    transparent_pixels = 0
    if alpha is not None:
        seen_alpha = pixels[:, :, 3]
        opaque = int((seen_alpha > 0).sum())
        transparent_pixels = int((seen_alpha == 0).sum())
        if opaque != covered:
            raise PreviewError(f'{os.path.basename(out_path)} carries {opaque} pixels with '
                               f'an alpha on them, not the {covered} that are not the '
                               f'background colour')
    if (measured_width, measured_height) != (final_width, final_height):
        raise PreviewError(f'{os.path.basename(out_path)} is {measured_width}x{measured_height}, '
                           f'not the {final_width}x{final_height} it was drawn to be')

    rows = np.where(differs.any(axis=1))[0]
    columns = np.where(differs.any(axis=0))[0]
    mean_rgb = np.round(final[differs].mean(axis=0)).astype(int)

    if should_cancel is not None and should_cancel():
        raise PreviewError(f'{os.path.basename(out_path)} was written and then the run was '
                           f'stopped, so treat it as the last picture of this pipeline')

    return {
        'path': out_path,
        'bytes': os.path.getsize(out_path),
        'width': measured_width,
        'height': measured_height,
        'asked_width': asked_width,
        'asked_height': asked_height,
        'window_opened': [open_width, open_height],
        'supersample': samples,
        'supersample_asked': samples_asked,
        'note': note,
        'mode': mode,
        'kind': kind,
        'geometry': os.path.basename(geometry_path),
        'display_mode': display_mode,
        'lit': light is not None,
        'covered_pixels': covered,
        'coverage_percent': round(100.0 * covered / float(measured_width * measured_height), 2),
        'silhouette_width': int(columns[-1] - columns[0] + 1),
        'silhouette_height': int(rows[-1] - rows[0] + 1),
        'mean_rgb': [int(value) for value in mean_rgb],
        'transparent_pixels': transparent_pixels,
        'distinct_colors': distinct,
    }
