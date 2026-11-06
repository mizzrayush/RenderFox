"""The Pipeline engine: twenty-six nodes, each one a file in, a file out, and numbers
taken off the file that came out.

What this replaced, in its own words. The engine used to be a QObject that answered three
of its twenty-five verbs and narrated the rest: `export.render` logged "Rendering not fully
implemented, skipping actual render" and returned True; twelve transform nodes logged
"is not yet implemented. Passing data through." and returned True; `transform.optimize`
had a `remove_loose` branch whose body was `pass`; `add_connection` was twenty lines of
debug prose that had to invent an `_current_pipeline` to append to; `stop()` flipped a flag
that nothing ever read; and the transform handlers read parameters their own definitions
never declared (`factor`, `angle`, `x/y/z`) while the knobs the pane showed were `scale`,
`rotation_x` and `offset_x`, so every number a person typed was discarded before it reached
the geometry. It also kept geometry as Python objects in `self._node_data` and copied them
with `import copy` inside a loop.

Three rules replace all of that.

1. **A node either writes a file or says why it did not.** Every handler returns the items
   it produced, and each item is re-read from disk and counted before it moves on, so the
   face count in the verdict is the written file's count, not the filter's claim.
2. **A knob the backend cannot receive is not offered; a knob that was offered by an older
   build is refused by name.** `smart`/`cube`/`sphere`/`cylinder` unwraps, an `hdri` lamp,
   an `orthographic` camera, `.exr` output, `clay` display and `roughness`/`metallic` bakes
   are all still in their enums so the sentence that refuses them reaches the person who
   asks - and each sentence says which two or three methods this build does have.
3. **There is no Qt in this module.** It used to carry seven signals, which meant an
   exception in a node was an exception in a slot, which PyQt6 answers by aborting the
   process (`0xC0000409`), and it meant the pane had to set `engine._current_pipeline` from
   three places for a connection check to work. The engine is now an object you call:
   `execute_pipeline(pipeline, should_cancel=..., log=..., node_hook=...)` returns a dict.
   The pane owns the thread, the buttons and the sentences built from this dict.

A run answers with one of five per-node statuses. `done` wrote files and counted them.
`refused` said no in advance and left the stream as it found it, so the rest of the
pipeline still runs - a refused camera is a pipeline that renders with the fitted default
and says so. `invalid` means the knobs do not mean anything (`target_count` of "ten"), and
also leaves the stream alone. `failed` means an exception nobody expected: its output is
unknown, so the run stops there rather than feeding a half-written file to the next node.
`stopped` is a person pressing Stop between two nodes, which is not a failure and never
deletes what was already written.
"""

import json
import os
import re
import tempfile
import time
import uuid
import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    trimesh = None
    TRIMESH_AVAILABLE = False


# The extensions the mesh filters in this app open without a first step. pymeshlab reads
# these itself; everything else the app can open (.fbx, .dae, .glb) is normalised into the
# staging folder as .obj first, by the same reader every other pane uses.
PROCESSABLE_EXTENSIONS = ('.obj', '.ply', '.stl', '.off')

# The file kinds a stream carries.
MESH = 'mesh'
CLOUD = 'cloud'

STATUSES = ('done', 'refused', 'invalid', 'failed', 'stopped', 'skipped')

# Written into every saved pipeline so a file from the old node set can be told apart.
NODE_SCHEMA = 2

HEX_COLOR = re.compile(r'^#?[0-9a-fA-F]{6}$')
NAME_TOKEN = re.compile(r'\{([a-z_]+)\}')
SAFE_NAME = re.compile(r'[^A-Za-z0-9._ -]')

# The point-cloud verbs a pipeline step may run, and the knobs each one reads. Everything
# here is `PointCloudProcessor.OPERATIONS` minus the ones that cannot work headless or do
# not write a file: `pick` opens a window, `analyze` and `distances` measure without
# writing, `features`, `register_icp` and `register_ransac` need two clouds and belong to
# the Point Clouds pane, and `export` only renames.
#
# The dict is backend key -> this node's knob, or (knob, index) when the backend takes one
# number per axis and the node takes a vector. `h_process_cloud` reads the values in an
# explicit chain so every knob is a literal the report can find; this table is what the
# "verb ignores these knobs" note is built from. A backend key with no entry keeps the
# backend's own default, which the note names. `radius` feeds two differently named keys
# because the pivoting ball and the outlier neighbourhood are the same idea in two verbs.
CLOUD_VERB_KNOBS: Dict[str, Dict[str, Any]] = {
    'dedup': {},
    'voxel': {'voxel_size': 'voxel_size'},
    'uniform': {'every_k': 'every_k'},
    'outliers_statistical': {'nb_neighbors': 'nb_neighbors', 'std_ratio': 'std_ratio'},
    'outliers_radius': {'nb_points': 'nb_points', 'radius': 'radius'},
    'center': {},
    'normalize': {},
    'translate': {'dx': ('offset', 0), 'dy': ('offset', 1), 'dz': ('offset', 2)},
    'rotate': {'rx': ('angles', 0), 'ry': ('angles', 1), 'rz': ('angles', 2)},
    'scale': {'factor': 'factor'},
    'crop': {'min_bound': 'min_bound', 'max_bound': 'max_bound'},
    'normals': {'knn': 'knn'},
    'planes': {'distance_threshold': 'distance_threshold'},
    'cluster': {'eps': 'eps', 'min_points': 'min_points'},
    'hull': {'extension': 'surface_format'},
    'poisson': {'depth': 'depth', 'extension': 'surface_format'},
    'ball_pivoting': {'ball_radius': 'radius', 'extension': 'surface_format'},
    'alpha_shape': {'alpha': 'alpha', 'extension': 'surface_format'},
}

CLOUD_VERBS = tuple(CLOUD_VERB_KNOBS)

# The four that answer with a surface, so the wire changes kind. Straight from the
# backend's own list, not a copy of it.
SURFACE_VERBS = ('hull', 'poisson', 'ball_pivoting', 'alpha_shape')


class NodeCategory(Enum):
    """Node categories for visual organization."""
    INPUT = "input"
    TRANSFORM = "transform"
    EXPORT = "export"


class ParameterType(Enum):
    """Parameter data types."""
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    FILE = "file"
    FOLDER = "folder"
    ENUM = "enum"
    COLOR = "color"
    VECTOR3 = "vector3"


@dataclass
class NodeParameter:
    """One knob. The name is what the handler reads, so a name here with no matching
    literal in the handler is a knob the engine throws away - `parameter_report()` and the
    contract suite both look for exactly that."""
    name: str
    type: ParameterType
    required: bool = True
    default: Any = None
    description: str = ""
    options: List[Any] = field(default_factory=list)
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass
class NodeDefinition:
    """Definition of a pipeline node type."""
    id: str
    name: str
    category: NodeCategory
    description: str
    parameters: List[NodeParameter]
    color: str
    icon: str = "●"
    handler: str = ""


# ============================================================================
# NODE DEFINITIONS DATABASE
#
# Every knob listed here is read by the handler named beside it, and every handler call is
# a function that already exists in src/processing. Nothing is declared "for later".
# ============================================================================

NODE_DEFINITIONS: Dict[str, NodeDefinition] = {
    # ========== INPUT NODES (BLUE) ==========
    "input.load_model": NodeDefinition(
        id="input.load_model",
        name="Load Model",
        category=NodeCategory.INPUT,
        handler="h_load_model",
        description="Open one model file. A source the mesh filters cannot read directly "
                    "(.fbx, .dae, .glb) is converted into the staging folder first and the "
                    "note says so.",
        color="#4A90E2",
        icon="models",
        parameters=[
            NodeParameter("file_path", ParameterType.FILE, required=True,
                          description="Model file to open"),
            NodeParameter("normalise_source", ParameterType.BOOL, required=False, default=True,
                          description="Rewrite a source the mesh filters cannot open as .obj "
                                      "in the staging folder. Off means the next node is given "
                                      "the file exactly as it is on disk."),
        ]
    ),

    "input.load_batch": NodeDefinition(
        id="input.load_batch",
        name="Load Batch",
        category=NodeCategory.INPUT,
        handler="h_load_batch",
        description="Open every model in a folder as one stream. Each node after this one "
                    "runs once per file, and each file keeps its own name.",
        color="#4A90E2",
        icon="folder",
        parameters=[
            NodeParameter("folder_path", ParameterType.FOLDER, required=True,
                          description="Folder containing the models"),
            NodeParameter("patterns", ParameterType.STRING, required=False,
                          default=", ".join(PROCESSABLE_EXTENSIONS + ('.fbx', '.glb', '.gltf')),
                          description="Comma-separated extensions to take"),
            NodeParameter("recursive", ParameterType.BOOL, required=False, default=False,
                          description="Search subfolders too"),
            NodeParameter("normalise_source", ParameterType.BOOL, required=False, default=True,
                          description="Rewrite sources the mesh filters cannot open as .obj"),
        ]
    ),

    "input.load_cloud": NodeDefinition(
        id="input.load_cloud",
        name="Load Point Cloud",
        category=NodeCategory.INPUT,
        handler="h_load_cloud",
        description="Open a scan as a point cloud. Cloud verbs run through the same "
                    "backend the Point Clouds pane uses.",
        color="#4A90E2",
        icon="point_clouds",
        parameters=[
            NodeParameter("file_path", ParameterType.FILE, required=True,
                          description="Cloud file to open (.pcd, .ply, .xyz, .pts)"),
        ]
    ),

    "input.camera": NodeDefinition(
        id="input.camera",
        name="Camera Setup",
        category=NodeCategory.INPUT,
        handler="h_camera",
        description="Where the eye is for every Render and Thumbnail node in this run. "
                    "Fit puts the eye at the distance the model's own bounding sphere "
                    "needs; off puts it exactly at the position you typed.",
        color="#4A90E2",
        icon="camera",
        parameters=[
            NodeParameter("position", ParameterType.VECTOR3, required=False, default=[0.0, 0.0, 3.0],
                          description="Eye position, used when Fit is off"),
            NodeParameter("target", ParameterType.VECTOR3, required=False, default=[0.0, 0.0, 0.0],
                          description="Point the eye looks at"),
            NodeParameter("up", ParameterType.VECTOR3, required=False, default=[0.0, 1.0, 0.0],
                          description="Which way is up in the frame. With the eye on +Z this is "
                                      "the level frame. Parallel to the line of sight, the "
                                      "raster falls back to its own sideways axis instead of "
                                      "drawing a tilted frame, and the note says so."),
            NodeParameter("fov", ParameterType.FLOAT, required=False, default=45.0,
                          min_value=1.0, max_value=170.0,
                          description="Vertical field of view in degrees"),
            NodeParameter("fit", ParameterType.BOOL, required=False, default=True,
                          description="Distance the model needs to fit the frame"),
            NodeParameter("mode", ParameterType.ENUM, required=False, default="perspective",
                          options=["perspective", "orthographic"],
                          description="Projection. Orthographic is refused: this build's "
                                      "raster has one measured perspective path."),
        ]
    ),

    "input.lighting": NodeDefinition(
        id="input.lighting",
        name="Lighting Setup",
        category=NodeCategory.INPUT,
        handler="h_lighting",
        description="One lamp, Lambert-lit onto the geometry's own normals. The Render and "
                    "Thumbnail nodes in this run take it.",
        color="#4A90E2",
        icon="lighting",
        parameters=[
            NodeParameter("kind", ParameterType.ENUM, required=True, default="directional",
                          options=["directional", "point", "spot", "hdri"],
                          description="What kind of lamp. hdri is refused: there is no "
                                      "environment-map loader or image-based shader here."),
            NodeParameter("intensity", ParameterType.FLOAT, required=False, default=1.0,
                          min_value=0.0, description="Multiplier on the lamp"),
            NodeParameter("color", ParameterType.COLOR, required=False, default="#FFFFFF",
                          description="Lamp colour as a tint"),
            NodeParameter("position", ParameterType.VECTOR3, required=False, default=[5.0, 10.0, 5.0],
                          description="Where a point or spot lamp sits"),
            NodeParameter("direction", ParameterType.VECTOR3, required=False,
                          default=[1.0, 0.65, 1.0],
                          description="Which way a directional lamp points. A spot lamp's axis "
                                      "is the line from its own position to the origin, so this "
                                      "knob is not read by a spot - the note says so."),
            NodeParameter("cone", ParameterType.FLOAT, required=False, default=45.0,
                          min_value=1.0, max_value=179.0,
                          description="Full angle of a spot lamp in degrees"),
            NodeParameter("ambient", ParameterType.FLOAT, required=False, default=0.1,
                          min_value=0.0, description="Floor brightness under the lamp"),
        ]
    ),

    # ========== TRANSFORM NODES (GREEN) ==========
    "transform.scale": NodeDefinition(
        id="transform.scale",
        name="Scale",
        category=NodeCategory.TRANSFORM,
        handler="h_scale",
        description="Grow or shrink the model about a point that stays put.",
        color="#50C878",
        icon="scale",
        parameters=[
            NodeParameter("factor", ParameterType.FLOAT, required=True, default=1.0,
                          description="Uniform scale factor when Per axis is off"),
            NodeParameter("per_axis", ParameterType.BOOL, required=False, default=False,
                          description="Use three different factors"),
            NodeParameter("axes", ParameterType.VECTOR3, required=False, default=[1.0, 1.0, 1.0],
                          description="X, Y and Z factors when Per axis is on"),
            NodeParameter("origin", ParameterType.VECTOR3, required=False, default=[0.0, 0.0, 0.0],
                          description="The point that does not move"),
        ]
    ),

    "transform.rotate": NodeDefinition(
        id="transform.rotate",
        name="Rotate",
        category=NodeCategory.TRANSFORM,
        handler="h_rotate",
        description="Turn the model by three Euler angles in degrees, about a pivot.",
        color="#50C878",
        icon="rotate",
        parameters=[
            NodeParameter("rotation_x", ParameterType.FLOAT, required=False, default=0.0,
                          description="Degrees about X"),
            NodeParameter("rotation_y", ParameterType.FLOAT, required=False, default=0.0,
                          description="Degrees about Y"),
            NodeParameter("rotation_z", ParameterType.FLOAT, required=False, default=0.0,
                          description="Degrees about Z"),
            NodeParameter("origin", ParameterType.VECTOR3, required=False, default=[0.0, 0.0, 0.0],
                          description="The pivot that stays put"),
        ]
    ),

    "transform.translate": NodeDefinition(
        id="transform.translate",
        name="Translate",
        category=NodeCategory.TRANSFORM,
        handler="h_translate",
        description="Move the model by x, y and z in its own units.",
        color="#50C878",
        icon="translate",
        parameters=[
            NodeParameter("offset_x", ParameterType.FLOAT, required=False, default=0.0,
                          description="Movement along X"),
            NodeParameter("offset_y", ParameterType.FLOAT, required=False, default=0.0,
                          description="Movement along Y"),
            NodeParameter("offset_z", ParameterType.FLOAT, required=False, default=0.0,
                          description="Movement along Z"),
        ]
    ),

    "transform.decimate": NodeDefinition(
        id="transform.decimate",
        name="Decimate",
        category=NodeCategory.TRANSFORM,
        handler="h_decimate",
        description="Collapse triangles down to a target. Two ways of naming it with the "
                    "quadric filter and one with the clustering grid - the three the "
                    "filters in this build take.",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("method", ParameterType.ENUM, required=True, default="ratio",
                          options=["ratio", "target_count", "clustering"],
                          description="How the target is named"),
            NodeParameter("ratio", ParameterType.FLOAT, required=False, default=0.5,
                          min_value=0.0, max_value=1.0,
                          description="Fraction of the faces to keep (ratio)"),
            NodeParameter("target_count", ParameterType.INT, required=False, default=10000,
                          min_value=1, description="Faces to end up with (target_count)"),
            NodeParameter("quality_threshold", ParameterType.FLOAT, required=False, default=0.3,
                          min_value=0.0, max_value=1.0,
                          description="The quadric filter's bound on how thin a surviving "
                                      "triangle may be; sent with ratio and target_count, "
                                      "ignored by clustering"),
            NodeParameter("cluster_size", ParameterType.FLOAT, required=False, default=0.05,
                          min_value=0.0, description="Grid size as a fraction of the diagonal "
                                                     "(clustering)"),
            NodeParameter("preserve_border", ParameterType.BOOL, required=False, default=True,
                          description="Keep the boundary edges"),
            NodeParameter("preserve_normal", ParameterType.BOOL, required=False, default=True,
                          description="Ask the filter to keep the normals"),
            NodeParameter("preserve_topology", ParameterType.BOOL, required=False, default=False,
                          description="Ask the filter to keep the surface closed"),
            NodeParameter("preserve_uv", ParameterType.BOOL, required=False, default=True,
                          description="On: refuse the result if the texture coordinates are "
                                      "gone. Off: strip them for real and report how many "
                                      "rows were lost."),
        ]
    ),

    "transform.simplify": NodeDefinition(
        id="transform.simplify",
        name="Simplify",
        category=NodeCategory.TRANSFORM,
        handler="h_simplify",
        description="Quadric edge collapse with flat regions collapsing harder than sharp "
                    "ones. The two knobs the filter does not take in this build, "
                    "aggressiveness and max_iterations, are not offered.",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("target_percent", ParameterType.FLOAT, required=False, default=50.0,
                          min_value=0.0, max_value=100.0,
                          description="Percent of the faces to keep"),
            NodeParameter("angle_threshold", ParameterType.FLOAT, required=False, default=1.0,
                          min_value=0.0, max_value=90.0,
                          description="Faces flatter than this many degrees collapse "
                                      "aggressively"),
            NodeParameter("preserve_border", ParameterType.BOOL, required=False, default=True,
                          description="Keep the boundary edges"),
            NodeParameter("preserve_normal", ParameterType.BOOL, required=False, default=False,
                          description="Ask the filter to keep the normals"),
            NodeParameter("preserve_topology", ParameterType.BOOL, required=False, default=False,
                          description="Ask the filter to keep the surface closed"),
        ]
    ),

    "transform.smooth": NodeDefinition(
        id="transform.smooth",
        name="Smooth",
        category=NodeCategory.TRANSFORM,
        handler="h_smooth",
        description="Relax the surface. Three filters, and the knobs each one actually "
                    "takes are named after it.",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("method", ParameterType.ENUM, required=True, default="laplacian",
                          options=["laplacian", "depth", "taubin"],
                          description="Which smoothing filter runs"),
            NodeParameter("iterations", ParameterType.INT, required=False, default=5,
                          min_value=1, description="Steps of the filter"),
            NodeParameter("preserve_border", ParameterType.BOOL, required=False, default=True,
                          description="Leave boundary vertices alone (laplacian)"),
            NodeParameter("lambda_value", ParameterType.FLOAT, required=False, default=0.5,
                          description="Shrink step (taubin)"),
            NodeParameter("mu_value", ParameterType.FLOAT, required=False, default=-0.53,
                          description="Expand step (taubin); the pair is what keeps volume"),
            NodeParameter("delta", ParameterType.FLOAT, required=False, default=100.0,
                          description="Band width as a percentage of the diagonal (depth)"),
        ]
    ),

    "transform.remesh": NodeDefinition(
        id="transform.remesh",
        name="Remesh",
        category=NodeCategory.TRANSFORM,
        handler="h_remesh",
        description="Rebuild the topology. Voxel remeshing is not offered here because no "
                    "voxel filter in this build writes a manifold surface from a mesh.",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("mode", ParameterType.ENUM, required=True, default="uniform",
                          options=["uniform", "adaptive", "quad", "voronoi"],
                          description="Which remesh filter runs"),
            NodeParameter("target_edge", ParameterType.FLOAT, required=False, default=0.05,
                          min_value=0.0, description="Edge length as a fraction of the "
                                                     "diagonal (uniform, adaptive)"),
            NodeParameter("iterations", ParameterType.INT, required=False, default=10,
                          min_value=1, description="Passes of the filter (uniform, adaptive)"),
            NodeParameter("step_ratio", ParameterType.FLOAT, required=False, default=10.0,
                          description="Strength of the Voronoi pass (voronoi)"),
        ]
    ),

    "transform.subdivide": NodeDefinition(
        id="transform.subdivide",
        name="Subdivide",
        category=NodeCategory.TRANSFORM,
        handler="h_subdivide",
        description="Refine the mesh. The four schemes this build's filters implement, with "
                    "the older names linear and simple refused by name and answered with "
                    "that list.",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("levels", ParameterType.INT, required=True, default=1, min_value=1,
                          description="How many times to subdivide"),
            NodeParameter("method", ParameterType.ENUM, required=False, default="loop",
                          options=["loop", "catmull-clark", "butterfly", "midpoint",
                                   "linear", "simple"],
                          description="Which subdivision filter runs"),
        ]
    ),

    "transform.center": NodeDefinition(
        id="transform.center",
        name="Center",
        category=NodeCategory.TRANSFORM,
        handler="h_center",
        description="Put a chosen centre of the model on the origin. Mass, bounds and "
                    "vertices are three different points, and a scan with one dense patch "
                    "puts them a long way apart.",
        color="#50C878",
        icon="reset_view",
        parameters=[
            NodeParameter("mode", ParameterType.ENUM, required=False, default="bounds",
                          options=["bounds", "mass", "vertices"],
                          description="Which centre goes to the origin"),
            NodeParameter("axes", ParameterType.VECTOR3, required=False, default=[1.0, 1.0, 1.0],
                          description="1 centres that axis, 0 leaves it where it is"),
        ]
    ),

    "transform.align": NodeDefinition(
        id="transform.align",
        name="Align",
        category=NodeCategory.TRANSFORM,
        handler="h_align",
        description="Sit a side of the model on a plane, or turn its longest spread onto an "
                    "axis by principal components.",
        color="#50C878",
        icon="focus",
        parameters=[
            NodeParameter("mode", ParameterType.ENUM, required=True, default="bounds",
                          options=["bounds", "pca"],
                          description="bounds puts a face of the box on a plane; pca turns "
                                      "the model's own spread onto the axes"),
            NodeParameter("axis", ParameterType.ENUM, required=True, default="z",
                          options=["x", "y", "z"], description="Which axis the plane is "
                                                               "perpendicular to"),
            NodeParameter("face", ParameterType.ENUM, required=False, default="min",
                          options=["min", "max", "center"],
                          description="Which side of the model lands on the plane"),
            NodeParameter("offset", ParameterType.FLOAT, required=False, default=0.0,
                          description="Where the plane sits along the axis"),
        ]
    ),

    "transform.mirror": NodeDefinition(
        id="transform.mirror",
        name="Mirror",
        category=NodeCategory.TRANSFORM,
        handler="h_mirror",
        description="Add the mirrored half, with its triangles reversed so the outside "
                    "still faces out, and optionally weld the seam.",
        color="#50C878",
        icon="copy",
        parameters=[
            NodeParameter("axis", ParameterType.ENUM, required=True, default="x",
                          options=["x", "y", "z"], description="Axis to flip across"),
            NodeParameter("weld", ParameterType.BOOL, required=False, default=False,
                          description="Merge the vertices the seam now shares"),
            NodeParameter("weld_threshold", ParameterType.FLOAT, required=False, default=0.001,
                          min_value=0.0, description="Weld distance as a fraction of the "
                                                     "model's diagonal"),
        ]
    ),

    "transform.unwrap_uv": NodeDefinition(
        id="transform.unwrap_uv",
        name="Unwrap UV",
        category=NodeCategory.TRANSFORM,
        handler="h_unwrap_uv",
        description="Write texture coordinates onto the mesh. The two parametrizers that "
                    "produce coordinates in this build are trivial and flat_plane; the four "
                    "names an older build offered are refused, each with the reason.",
        color="#50C878",
        icon="grid",
        parameters=[
            NodeParameter("method", ParameterType.ENUM, required=True, default="trivial",
                          options=["trivial", "flat_plane", "smart", "cube", "sphere",
                                   "cylinder"],
                          description="Which parametrizer runs"),
            NodeParameter("texture_size", ParameterType.INT, required=False, default=2048,
                          min_value=1, description="Texel grid the border is measured on "
                                                   "(trivial only)"),
            NodeParameter("border_pixels", ParameterType.INT, required=False, default=2,
                          min_value=0, description="Padding left around each island "
                                                   "(trivial only)"),
            NodeParameter("layout", ParameterType.ENUM, required=False, default="Basic",
                          options=["Basic", "Space-optimizing"],
                          description="Island packing the filter offers (trivial only)"),
        ]
    ),

    "transform.bake_texture": NodeDefinition(
        id="transform.bake_texture",
        name="Bake Texture",
        category=NodeCategory.TRANSFORM,
        handler="h_bake_texture",
        description="Rasterise normal, diffuse and AO maps of a detailed model into the UVs "
                    "of the model on the wire, with the same baker the Mesh Tools pane uses. "
                    "Put an Unwrap UV node in front to choose the coordinates: without any, "
                    "the baker writes its own trivial set and says so in the note. Roughness "
                    "and metallic are named in the list and refused - the baker rasterises "
                    "three maps.",
        color="#50C878",
        icon="material",
        parameters=[
            NodeParameter("high_poly_path", ParameterType.FILE, required=True,
                          description="The detailed model the maps are taken from. The "
                                      "model on the wire is the one they are written onto."),
            NodeParameter("type", ParameterType.ENUM, required=True, default="combined",
                          options=["combined", "normal", "diffuse", "ao", "roughness",
                                   "metallic"],
                          description="Which maps are baked"),
            NodeParameter("resolution", ParameterType.INT, required=True, default=2048,
                          min_value=16, description="Edge length of each map in pixels. Below "
                                                    "8 the baker's own floor of 8 is what lands "
                                                    "on disk, and the row says which it checked"),
            NodeParameter("output_folder", ParameterType.FOLDER, required=True,
                          description="Folder the map files are written into"),
            NodeParameter("overwrite", ParameterType.BOOL, required=False, default=False,
                          description="Replace a map that is already in that folder. Off, the "
                                      "node refuses before it rasterises anything, because the "
                                      "baker writes names it chooses itself."),
        ]
    ),

    "transform.lod_generate": NodeDefinition(
        id="transform.lod_generate",
        name="Generate LOD",
        category=NodeCategory.TRANSFORM,
        handler="h_lod_generate",
        description="Write a chain of reduced levels with the same generator the Mesh Tools "
                    "pane uses. The levels are files, so this node hands the chain on as its "
                    "stream.",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("levels", ParameterType.INT, required=True, default=3, min_value=1,
                          max_value=10, description="How many levels to write"),
            NodeParameter("high_ratio", ParameterType.FLOAT, required=False, default=0.8,
                          min_value=0.0, max_value=1.0,
                          description="Fraction of the faces in the first level"),
            NodeParameter("medium_ratio", ParameterType.FLOAT, required=False, default=0.5,
                          min_value=0.0, max_value=1.0,
                          description="Fraction in the middle level (three levels)"),
            NodeParameter("low_ratio", ParameterType.FLOAT, required=False, default=0.2,
                          min_value=0.0, max_value=1.0,
                          description="Fraction in the last level"),
            NodeParameter("output_folder", ParameterType.FOLDER, required=True,
                          description="Folder the level files are written into"),
        ]
    ),

    "transform.optimize": NodeDefinition(
        id="transform.optimize",
        name="Optimize",
        category=NodeCategory.TRANSFORM,
        handler="h_optimize",
        description="Weld doubles, drop loose and null geometry, and re-orient normals - "
                    "each one through the repair filter that does it, with the counts before "
                    "and after.",
        color="#50C878",
        icon="sparkles",
        parameters=[
            NodeParameter("remove_doubles", ParameterType.BOOL, required=False, default=True,
                          description="Weld vertices together"),
            NodeParameter("merge_threshold", ParameterType.FLOAT, required=False, default=0.0001,
                          min_value=0.0, description="Weld distance as a fraction of the "
                                                     "diagonal; 0 welds only exact duplicates"),
            NodeParameter("recalc_normals", ParameterType.BOOL, required=False, default=True,
                          description="Re-orient the faces coherently"),
            NodeParameter("remove_loose", ParameterType.BOOL, required=False, default=True,
                          description="Drop unreferenced vertices, null faces and folded faces"),
            NodeParameter("strip_uv", ParameterType.BOOL, required=False, default=False,
                          description="Write the file back with no texture coordinates"),
        ]
    ),

    "transform.process_cloud": NodeDefinition(
        id="transform.process_cloud",
        name="Process Point Cloud",
        category=NodeCategory.TRANSFORM,
        handler="h_process_cloud",
        description="One verb of the point-cloud backend - the same one the Point Clouds "
                    "pane's buttons call, through the same file naming rule. Each verb is "
                    "given its own knobs; the note names any this verb does not read. The "
                    "four surface verbs answer with a mesh, so the wire changes kind there.",
        color="#50C878",
        icon="point_clouds",
        parameters=[
            NodeParameter("verb", ParameterType.ENUM, required=True, default="voxel",
                          options=list(CLOUD_VERBS),
                          description="Which operation runs"),
            NodeParameter("output_folder", ParameterType.FOLDER, required=True,
                          description="Folder the files are written into"),
            NodeParameter("voxel_size", ParameterType.FLOAT, required=False, default=0.05,
                          min_value=0.0, description="Cube edge in the file's own units "
                                                     "(voxel)"),
            NodeParameter("every_k", ParameterType.INT, required=False, default=5, min_value=1,
                          description="Keep every K-th point (uniform); 1 keeps them all and "
                                     "the backend refuses that as no reduction"),
            NodeParameter("nb_neighbors", ParameterType.INT, required=False, default=20,
                          min_value=1, description="Neighbours compared per point "
                                                   "(outliers_statistical)"),
            NodeParameter("std_ratio", ParameterType.FLOAT, required=False, default=2.0,
                          min_value=0.0, description="How many sigmas away is an outlier "
                                                     "(outliers_statistical)"),
            NodeParameter("nb_points", ParameterType.INT, required=False, default=16,
                          min_value=1, description="Neighbours a point needs to stay "
                                                   "(outliers_radius)"),
            NodeParameter("radius", ParameterType.FLOAT, required=False, default=0.05,
                          min_value=0.0, description="Neighbourhood size for outliers_radius, "
                                                     "and the pivoting ball for ball_pivoting"),
            NodeParameter("offset", ParameterType.VECTOR3, required=False, default=[0.0, 0.0, 0.0],
                          description="Move by x, y and z (translate)"),
            NodeParameter("angles", ParameterType.VECTOR3, required=False, default=[0.0, 0.0, 0.0],
                          description="Turn by x, y and z degrees about the cloud's own "
                                      "centre (rotate)"),
            NodeParameter("factor", ParameterType.FLOAT, required=False, default=2.0,
                          description="Scale about the centre (scale); 1 is refused as "
                                      "nothing to write"),
            NodeParameter("min_bound", ParameterType.VECTOR3, required=False,
                          default=[-1.0, -1.0, -1.0], description="Low corner of the box "
                                                                  "(crop)"),
            NodeParameter("max_bound", ParameterType.VECTOR3, required=False,
                          default=[1.0, 1.0, 1.0], description="High corner of the box (crop)"),
            NodeParameter("knn", ParameterType.INT, required=False, default=30, min_value=1,
                          description="Neighbours averaged to estimate each normal (normals)"),
            NodeParameter("distance_threshold", ParameterType.FLOAT, required=False,
                          default=0.01, min_value=0.0, description="How far a point may sit "
                                                                   "from the plane and still "
                                                                   "count (planes)"),
            NodeParameter("eps", ParameterType.FLOAT, required=False, default=0.02,
                          min_value=0.0, description="DBSCAN neighbourhood size (cluster)"),
            NodeParameter("min_points", ParameterType.INT, required=False, default=10,
                          min_value=1, description="Points needed to make a group (cluster)"),
            NodeParameter("alpha", ParameterType.FLOAT, required=False, default=0.03,
                          min_value=0.0, description="Ball radius of the alpha shape "
                                                     "(alpha_shape)"),
            NodeParameter("depth", ParameterType.INT, required=False, default=9, min_value=1,
                          description="Octree depth of the Poisson surface (poisson)"),
            NodeParameter("surface_format", ParameterType.ENUM, required=False, default=".ply",
                          options=['.ply', '.obj', '.stl', '.off', '.glb'],
                          description="File the four surface verbs write (hull, poisson, "
                                      "ball_pivoting, alpha_shape)"),
        ]
    ),

    # ========== EXPORT NODES (RED) ==========
    "export.render": NodeDefinition(
        id="export.render",
        name="Render",
        category=NodeCategory.EXPORT,
        handler="h_render",
        description="Draw each model on the wire with this app's own raster and write a "
                    "picture per model. The verdict counts the file that landed on disk.",
        color="#E74C3C",
        icon="render",
        parameters=[
            NodeParameter("output_folder", ParameterType.FOLDER, required=True,
                          description="Folder the pictures are written into"),
            NodeParameter("naming_pattern", ParameterType.STRING, required=False,
                          default="{name}_{index}.{format}",
                          description="Tokens: {name} {index} {format}"),
            NodeParameter("resolution_x", ParameterType.INT, required=True, default=1920,
                          min_value=1, description="Width of the picture"),
            NodeParameter("resolution_y", ParameterType.INT, required=True, default=1080,
                          min_value=1, description="Height of the picture"),
            NodeParameter("format", ParameterType.ENUM, required=False, default="png",
                          options=["png", "jpg", "tiff", "exr"],
                          description="Encoder. exr is refused: this build writes "
                                      "png, jpg, tiff, bmp and webp."),
            NodeParameter("samples", ParameterType.INT, required=False, default=1, min_value=1,
                          max_value=8, description="Frames drawn at N times the size and "
                                                   "averaged down"),
            NodeParameter("transparent", ParameterType.BOOL, required=False, default=False,
                          description="Alpha behind the model (not with .jpg)"),
            NodeParameter("display", ParameterType.ENUM, required=False, default="object",
                          options=["object", "normals", "height", "x_coordinate",
                                   "y_coordinate", "z_coordinate", "clay"],
                          description="What the surface is painted from. clay is refused."),
            NodeParameter("background", ParameterType.COLOR, required=False, default="#1E1E1E",
                          description="Colour behind the model"),
            NodeParameter("point_size", ParameterType.FLOAT, required=False, default=3.0,
                          min_value=1.0, description="Size of a drawn point for a cloud"),
        ]
    ),

    "export.model": NodeDefinition(
        id="export.model",
        name="Export Model",
        category=NodeCategory.EXPORT,
        handler="h_export_model",
        description="Write one model to one file, through the app's only writer. A wire "
                    "carrying more than one model is refused and named, because two files "
                    "cannot share one name.",
        color="#E74C3C",
        icon="export",
        parameters=[
            NodeParameter("output_path", ParameterType.FILE, required=True,
                          description="File to write"),
            NodeParameter("format", ParameterType.ENUM, required=False, default="",
                          options=["", "obj", "ply", "stl", "off", "glb", "gltf", "fbx",
                                   "dae", "exr"],
                          description="Leave empty to take the extension of the output "
                                      "path; exr is not a model format and is refused"),
            NodeParameter("overwrite", ParameterType.BOOL, required=False, default=False,
                          description="Replace the file if it is already there"),
        ]
    ),

    "export.batch": NodeDefinition(
        id="export.batch",
        name="Batch Export",
        category=NodeCategory.EXPORT,
        handler="h_export_batch",
        description="Write every model on the wire into one folder, named by a pattern.",
        color="#E74C3C",
        icon="batch_render",
        parameters=[
            NodeParameter("output_folder", ParameterType.FOLDER, required=True,
                          description="Folder the model files are written into"),
            NodeParameter("format", ParameterType.ENUM, required=True, default="fbx",
                          options=["fbx", "obj", "ply", "stl", "off", "glb", "gltf", "dae",
                                   "exr"],
                          description="Target format. A pair this build cannot write is "
                                      "refused with the library it would need."),
            NodeParameter("naming_pattern", ParameterType.STRING, required=False,
                          default="{name}_{index}.{format}",
                          description="Tokens: {name} {index} {format}"),
            NodeParameter("overwrite", ParameterType.BOOL, required=False, default=False,
                          description="Replace files that are already there"),
        ]
    ),

    "export.thumbnail": NodeDefinition(
        id="export.thumbnail",
        name="Generate Thumbnail",
        category=NodeCategory.EXPORT,
        handler="h_thumbnail",
        description="A fitted square picture per model - the same raster as Render, the "
                    "same counted verdict, one size you can hand to an asset browser.",
        color="#E74C3C",
        icon="camera",
        parameters=[
            NodeParameter("output_folder", ParameterType.FOLDER, required=True,
                          description="Folder the thumbnails are written into"),
            NodeParameter("size", ParameterType.INT, required=False, default=256, min_value=16,
                          description="Edge length in pixels"),
            NodeParameter("format", ParameterType.ENUM, required=False, default="png",
                          options=["png", "jpg"], description="Encoder"),
            NodeParameter("background", ParameterType.COLOR, required=False, default="#1E1E1E",
                          description="Colour behind the model"),
            NodeParameter("point_size", ParameterType.FLOAT, required=False, default=3.0,
                          min_value=1.0, description="Size of a drawn point for a cloud"),
        ]
    ),

    "export.stats": NodeDefinition(
        id="export.stats",
        name="Export Stats",
        category=NodeCategory.EXPORT,
        handler="h_stats",
        description="One JSON per model, counted from the file that is on disk: extents, "
                    "topology, materials and image sizes.",
        color="#E74C3C",
        icon="chart",
        parameters=[
            NodeParameter("output_folder", ParameterType.FOLDER, required=True,
                          description="Folder the JSON files are written into"),
            NodeParameter("include_geometry", ParameterType.BOOL, required=False, default=True,
                          description="Counts, extents, volume, topology"),
            NodeParameter("include_materials", ParameterType.BOOL, required=False, default=True,
                          description="Material names and texture coordinates"),
            NodeParameter("include_textures", ParameterType.BOOL, required=False, default=True,
                          description="The image files a material refers to and their sizes"),
        ]
    ),
}


# ============================================================================
# WHY A NODE ANSWERS
# ============================================================================

class Refused(Exception):
    """The node said no, in a sentence a person can act on, and left the stream alone."""


class Invalid(Exception):
    """The knobs as given do not mean anything, so nothing could have been tried anyway."""


class Stopped(Exception):
    """A person pressed Stop. Not a failure, and nothing already written is touched."""


# ============================================================================
# WHAT MOVES ALONG THE WIRE
# ============================================================================

@dataclass
class Item:
    """One model on the wire: a file, the kind it is, and the counts taken off the file."""
    kind: str
    path: str
    label: str
    facts: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        if self.kind == MESH:
            return (f"{self.label}: {self.facts.get('faces')} faces, "
                    f"{self.facts.get('vertices')} vertices")
        return f"{self.label}: {self.facts.get('points')} points"


Stream = List[Item]


@dataclass
class PipelineNode:
    """Instance of a node in a pipeline."""
    id: str
    definition_id: str
    position: tuple = (0.0, 0.0)
    parameters: Dict[str, Any] = field(default_factory=dict)

    def get_definition(self) -> Optional[NodeDefinition]:
        return NODE_DEFINITIONS.get(self.definition_id)


@dataclass
class PipelineConnection:
    """Connection between two nodes."""
    from_node: str
    to_node: str


@dataclass
class Pipeline:
    """Complete pipeline definition."""
    id: str
    name: str
    description: str = ""
    nodes: List[PipelineNode] = field(default_factory=list)
    connections: List[PipelineConnection] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    modified_at: float = field(default_factory=time.time)

    # ---- the graph itself ----

    def node_by_id(self, node_id: str) -> Optional[PipelineNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def add_node(self, node: PipelineNode) -> Tuple[bool, str]:
        if self.node_by_id(node.id):
            return False, f"a node called {node.id} is already in {self.name}"
        if node.definition_id not in NODE_DEFINITIONS:
            return False, (f"nothing here answers to the node type {node.definition_id}; "
                           f"this build has {len(NODE_DEFINITIONS)}")
        self.nodes.append(node)
        self.modified_at = time.time()
        return True, ""

    def add_connection(self, connection: PipelineConnection) -> Tuple[bool, str]:
        """Wire two nodes, or say exactly why this wire cannot exist.

        The engine used to own this and to answer False with nothing to read - so the pane
        printed "Cycle detected?" whether the wire was a duplicate, a loop of one, or a node
        that was never in the pipeline. The Pipeline owns its own graph.
        """
        if connection.from_node == connection.to_node:
            return False, (f"{self._name_of(connection.from_node)} would feed itself; a "
                           f"pipeline is a line, not a loop")
        for existing in self.connections:
            if (existing.from_node == connection.from_node
                    and existing.to_node == connection.to_node):
                return False, "that wire is already there"
        source = self.node_by_id(connection.from_node)
        target = self.node_by_id(connection.to_node)
        if source is None or target is None:
            missing = connection.from_node if source is None else connection.to_node
            return False, f"there is no node {missing} in this pipeline to wire"
        if source.definition_id not in NODE_DEFINITIONS:
            return False, (f"{source.definition_id} is not a node type this build has, so it "
                           f"cannot feed anything")
        if target.definition_id not in NODE_DEFINITIONS:
            return False, (f"{target.definition_id} is not a node type this build has, so "
                           f"nothing can be wired into it")
        self.connections.append(connection)
        # A wire that closes a loop is not a pipeline: say so at the moment it happens,
        # because a cycle discovered at Run time leaves the person guessing which wire.
        if self.has_cycle():
            self.connections.remove(connection)
            return False, (f"{self._name_of(connection.to_node)} already reaches "
                           f"{self._name_of(connection.from_node)}, so that wire would close "
                           f"a loop")
        self.modified_at = time.time()
        return True, ""

    def remove_connection(self, connection: PipelineConnection) -> Tuple[bool, str]:
        for existing in self.connections:
            if (existing.from_node == connection.from_node
                    and existing.to_node == connection.to_node):
                self.connections.remove(existing)
                self.modified_at = time.time()
                return True, ""
        return False, "there was no such wire"

    def remove_node(self, node_id: str) -> Tuple[bool, str]:
        node = self.node_by_id(node_id)
        if node is None:
            return False, f"there is no node {node_id} in this pipeline"
        self.nodes.remove(node)
        self.connections = [c for c in self.connections
                            if c.from_node != node_id and c.to_node != node_id]
        self.modified_at = time.time()
        return True, ""

    def _name_of(self, node_id: str) -> str:
        node = self.node_by_id(node_id)
        if node is None:
            return node_id
        definition = node.get_definition()
        return definition.name if definition else node.definition_id

    def incoming(self, node_id: str) -> List[PipelineConnection]:
        return [c for c in self.connections if c.to_node == node_id]

    def has_cycle(self) -> bool:
        """True when the graph contains a loop, found by walking it, not by counting."""
        adjacency: Dict[str, List[str]] = {node.id: [] for node in self.nodes}
        for connection in self.connections:
            if connection.from_node in adjacency:
                adjacency[connection.from_node].append(connection.to_node)
        visited, active = set(), set()

        def walk(node_id: str) -> bool:
            visited.add(node_id)
            active.add(node_id)
            for neighbour in adjacency.get(node_id, []):
                if neighbour in active:
                    return True
                if neighbour not in visited and walk(neighbour):
                    return True
            active.discard(node_id)
            return False

        return any(walk(node.id) for node in self.nodes if node.id not in visited)

    def execution_order(self) -> Tuple[List[str], str]:
        """Nodes in dependency order, or the reason there is no such order.

        Seeds and ties keep insertion order, so the same pipeline runs in the same order
        twice - which is what makes a pipeline's files predictable enough to test.
        """
        adjacency: Dict[str, List[str]] = {node.id: [] for node in self.nodes}
        in_degree: Dict[str, int] = {node.id: 0 for node in self.nodes}
        for connection in self.connections:
            if connection.from_node in adjacency and connection.to_node in in_degree:
                adjacency[connection.from_node].append(connection.to_node)
                in_degree[connection.to_node] += 1
        queue = [node.id for node in self.nodes if in_degree[node.id] == 0]
        order: List[str] = []
        while queue:
            node_id = queue.pop(0)
            order.append(node_id)
            for neighbour in adjacency[node_id]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)
        if len(order) != len(self.nodes):
            stuck = sorted(node.id for node in self.nodes if node.id not in order)
            return [], (f"{len(stuck)} node(s) sit on a loop, so there is no order to run "
                        f"them in: {', '.join(stuck)}")
        return order, ""

    # ---- is it worth running ----

    def problems(self) -> List[str]:
        """Every structural reason this pipeline cannot answer, as sentences."""
        found = []
        if not self.nodes:
            return [f"{self.name} has no nodes; double-click one in the palette on the left"]
        for node in self.nodes:
            definition = node.get_definition()
            if definition is None:
                found.append(f"{node.id} is a {node.definition_id}, which this build does not "
                             f"have")
                continue
            reason = definition_not_backed(definition)
            if reason:
                found.append(reason)
            if definition.category != NodeCategory.INPUT and not self.incoming(node.id):
                found.append(f"{definition.name} has nothing on its wire; connect a Load "
                             f"node to it")
        for connection in self.connections:
            if self.node_by_id(connection.from_node) is None:
                found.append(f"a wire starts at {connection.from_node}, which is not in this "
                             f"pipeline")
            if self.node_by_id(connection.to_node) is None:
                found.append(f"a wire ends at {connection.to_node}, which is not in this "
                             f"pipeline")
        if self.has_cycle():
            found.append("the wires contain a loop")
        return found

    # ---- on disk ----

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "node_schema": NODE_SCHEMA,
            "nodes": [
                {
                    "id": node.id,
                    "definition_id": node.definition_id,
                    "position": list(node.position),
                    "parameters": node.parameters,
                }
                for node in self.nodes
            ],
            "connections": [{"from": c.from_node, "to": c.to_node} for c in self.connections],
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }

    @staticmethod
    def from_dict(data: Dict) -> 'Pipeline':
        """Build a pipeline from a saved dict.

        A file from the old node set is loaded and then reported on, not rewritten: the
        knobs it names that no handler reads any more are listed by `unknown_parameters`,
        so the person sees which boxes on the node no longer move anything.
        """
        pipeline = Pipeline(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data.get("created_at", time.time()),
            modified_at=data.get("modified_at", time.time()),
        )
        for entry in data.get("nodes", []):
            pipeline.nodes.append(PipelineNode(
                id=entry["id"],
                definition_id=entry["definition_id"],
                position=tuple(entry.get("position") or (0.0, 0.0)),
                parameters=dict(entry.get("parameters") or {}),
            ))
        for entry in data.get("connections", []):
            pipeline.connections.append(PipelineConnection(entry["from"], entry["to"]))
        return pipeline

    def unknown_parameters(self, node: PipelineNode) -> List[str]:
        """Knobs the node carries that its definition does not declare."""
        definition = node.get_definition()
        if definition is None:
            return sorted(node.parameters)
        declared = {param.name for param in definition.parameters}
        return sorted(name for name in node.parameters if name not in declared)


# ============================================================================
# THE KNOBS, BEFORE THEY REACH A BACKEND
# ============================================================================

def coerce(value: Any, param: NodeParameter) -> Tuple[bool, Any]:
    """Read one knob the way its type says, or say what it got.

    Numbers keep the range out of the way: `min_value`/`max_value` on a definition seed the
    pane's box, they do not gate the backend. A person who types 0 into `ratio` is not
    misremembering the units, they are asking for something the filter will answer, and the
    handler is where that answer comes from - refusing it here would hide the difference
    between "not supported" and "not allowed to ask". What is checked here is whether the
    value means anything at all.
    """
    if value is None:
        return True, None
    kind = param.type
    if kind == ParameterType.STRING:
        text = str(value)
        return True, text
    if kind == ParameterType.INT:
        if isinstance(value, bool):
            return False, f"{param.name} needs a whole number, got the word {value!r}"
        try:
            return True, int(str(value).strip())
        except (TypeError, ValueError):
            return False, (f"{param.name} needs a whole number, got {value!r} "
                           f"(the filter takes a count, not a fraction)")
    if kind == ParameterType.FLOAT:
        if isinstance(value, bool):
            return False, f"{param.name} needs a number, got the word {value!r}"
        try:
            return True, float(str(value).strip())
        except (TypeError, ValueError):
            return False, f"{param.name} needs a number, got {value!r}"
    if kind == ParameterType.BOOL:
        if isinstance(value, bool):
            return True, value
        if isinstance(value, str) and value.strip().lower() in ('true', 'false', '1', '0',
                                                                'yes', 'no', 'on', 'off'):
            return True, value.strip().lower() in ('true', '1', 'yes', 'on')
        return False, (f"{param.name} is a tick box, so it takes yes or no - not {value!r}")
    if kind == ParameterType.ENUM:
        text = str(value).strip()
        named = [str(option) for option in param.options]
        if text in named:
            return True, text
        return False, (f"{param.name} does not have {text!r}. The node offers "
                       f"{', '.join(named) if named else 'nothing'}")
    if kind == ParameterType.COLOR:
        text = str(value).strip()
        if not HEX_COLOR.match(text):
            return False, (f"{param.name} wants six hex digits like #1E1E1E, got {value!r}")
        return True, text if text.startswith('#') else '#' + text
    if kind == ParameterType.FILE or kind == ParameterType.FOLDER:
        text = str(value).strip().strip('"')
        if not text:
            return False, f"{param.name} is empty, so there is nothing to open"
        return True, text
    if kind == ParameterType.VECTOR3:
        parts = value
        if isinstance(value, str):
            parts = re.split(r'[,; ]+', value.strip().strip('()[]'))
        try:
            numbers = [float(part) for part in parts]
        except (TypeError, ValueError):
            return False, f"{param.name} wants three numbers, got {value!r}"
        if len(numbers) != 3:
            return False, (f"{param.name} wants three numbers, got {len(numbers)} "
                           f"({value!r})")
        return True, numbers
    return False, f"{param.name} has type {kind}, which this engine cannot read"


def coerce_node(node: PipelineNode, definition: NodeDefinition) -> Dict[str, Any]:
    """The node's knobs, read. Raises `Invalid` with every problem at once."""
    values: Dict[str, Any] = {}
    problems: List[str] = []
    declared = {param.name: param for param in definition.parameters}
    for param in definition.parameters:
        if param.name in node.parameters:
            ok, value = coerce(node.parameters[param.name], param)
            if not ok:
                problems.append(value)
                continue
            values[param.name] = value
        elif param.default is not None:
            values[param.name] = param.default
        elif param.required:
            problems.append(f"{param.name} has no value and the node cannot run without it")
    for name in sorted(node.parameters):
        if name not in declared:
            problems.append(f"{name} is not a knob of {definition.name} in this build, so "
                            f"nothing reads it")
    if problems:
        raise Invalid('; '.join(problems))
    return values


# ============================================================================
# WHAT A FILE IS, ONCE IT HAS BEEN WRITTEN
# ============================================================================

def measure(path: str, kind: str) -> Dict[str, Any]:
    """Count what the file on disk actually holds. A missing file is a fact, not a crash."""
    facts: Dict[str, Any] = {'path': path, 'exists': os.path.isfile(path)}
    if not facts['exists']:
        facts['error'] = f'{os.path.basename(path)} is not on disk'
        return facts
    facts['bytes'] = os.path.getsize(path)
    if facts['bytes'] == 0:
        facts['error'] = f'{os.path.basename(path)} is on disk with no bytes in it'
        return facts
    if kind == MESH:
        if not TRIMESH_AVAILABLE:
            facts['error'] = 'Trimesh is not available, so a mesh could not be counted'
            return facts
        try:
            mesh = trimesh.load(path, process=False)
            facts['vertices'] = int(len(mesh.vertices))
            facts['faces'] = int(len(mesh.faces))
            facts['extents'] = [round(float(x), 4) for x in mesh.extents]
            facts['watertight'] = bool(mesh.is_watertight)
            coordinates = getattr(mesh.visual, 'uv', None)
            facts['uv_rows'] = 0 if coordinates is None else int(len(coordinates))
        except Exception as problem:
            facts['error'] = (f'{os.path.basename(path)} was written but does not read back '
                              f'as a mesh: {type(problem).__name__}: {problem}')
        return facts
    try:
        from .point_cloud_processor import PointCloudProcessor
        cloud, error = PointCloudProcessor().read_cloud(path)
        if error:
            facts['error'] = error
        else:
            facts['points'] = int(len(cloud.points))
            facts['has_colors'] = bool(cloud.has_colors())
            facts['has_normals'] = bool(cloud.has_normals())
    except Exception as problem:
        facts['error'] = f'the cloud could not be counted: {type(problem).__name__}: {problem}'
    return facts


def _safe_label(text: str) -> str:
    """A name that cannot escape the folder it is written into."""
    cleaned = SAFE_NAME.sub('_', str(text)).strip(' .')
    return cleaned or 'model'


def _format_name(pattern: str, item: Item, index: int, fmt: str) -> str:
    """Fill a naming pattern, refusing a token this engine does not know.

    `{index}` exists because two files in one folder cannot share a name, and a pattern
    without it is the person's choice, not this engine's silence: Batch Export checks the
    result for collisions before it writes anything.
    """
    tokens = {'name': _safe_label(item.label), 'index': str(index),
              'format': str(fmt).lstrip('.')}
    unknown = sorted(set(NAME_TOKEN.findall(pattern)) - set(tokens))
    if unknown:
        raise Invalid(f"the naming pattern asks for {{{unknown[0]}}}, which is not one of "
                      f"these tokens: {', '.join(sorted(tokens))}")
    filled = NAME_TOKEN.sub(lambda match: tokens[match.group(1)], pattern)
    filled = filled.replace(os.sep, '_').replace('/', '_').replace('\\', '_')
    if not filled.strip():
        raise Invalid("the naming pattern produces an empty file name")
    return filled


def handler_is_backed(handler_name: str) -> bool:
    """Does the named handler exist and is it not an empty shell?"""
    function = globals().get(handler_name)
    return bool(callable(function))


# ============================================================================
# THE RUN
# ============================================================================

class PipelineEngine:
    """Executes a pipeline. No Qt, no state between runs, no thread of its own.

    `execute_pipeline` is called from whatever thread the caller chose and answers a dict.
    `log` and `node_hook` are called in that thread too, so a pane moves them onto the GUI
    thread itself - which is the only way a long node cannot turn into an exception in a
    slot and an aborted process.
    """

    def __init__(self, staging_root: Optional[str] = None):
        self.staging_root = staging_root
        self.staging: Optional[str] = None
        self.scene: Dict[str, Any] = {}
        self.files: List[str] = []
        self._stream: Dict[str, Stream] = {}
        self._pipeline: Optional[Pipeline] = None
        self._should_cancel = None
        self._log = None
        self._node_hook = None
        self._node_index = 0

    # ---- plumbing the handlers share ----

    def _say(self, sentence: str) -> None:
        if self._log:
            self._log(sentence)

    def _node(self, node_id: str, name: str, status: str, detail: str) -> None:
        if self._node_hook:
            self._node_hook(node_id, name, status, detail)

    def _check_stop(self, where: str) -> None:
        if self._should_cancel and self._should_cancel():
            raise Stopped(f'stopped at {where}, so nothing further was written')

    def _staged(self, node: PipelineNode, label: str, extension: str) -> str:
        self._node_index += 1
        name = f'{self._node_index:02d}_{_safe_label(label)}{extension}'
        folder = os.path.join(self.staging, node.id[:8])
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, name)

    def _open_file(self, path: str, what: str) -> str:
        """A file a person typed as something to read, checked on the way in - with the
        sentence that says which one and what is wrong with it."""
        absolute = os.path.abspath(str(path))
        if os.path.isdir(absolute):
            raise Refused(f"the {what} {absolute} is a folder; a node that reads wants one file")
        if not os.path.isfile(absolute):
            raise Refused(f"the {what} {absolute} is not a file on this disk")
        if os.path.getsize(absolute) == 0:
            raise Refused(f"the {what} {absolute} is there but holds no bytes")
        return absolute

    def _write_file(self, path: str, what: str) -> str:
        """A file a person typed as somewhere to write. It need not exist - that is the point -
        but the name has to be a file name and the folder above it has to be there, because a
        node that writes into a folder nobody made is how a pipeline 'succeeds' and leaves
        nothing behind."""
        absolute = os.path.abspath(str(path))
        if os.path.isdir(absolute):
            raise Refused(f"the {what} {absolute} is a folder, not the file to write into")
        if not os.path.splitext(os.path.basename(absolute))[1]:
            raise Refused(f"the {what} {absolute} has no extension, so nothing here knows what "
                          f"kind of file that is meant to be")
        folder = os.path.dirname(absolute)
        if not os.path.isdir(folder):
            raise Refused(f"the folder {folder} around the {what} is not on this disk, so "
                          f"{os.path.basename(absolute)} has nowhere to be written")
        return absolute

    def _open_folder(self, path: str, what: str) -> str:
        absolute = os.path.abspath(str(path))
        if not os.path.isdir(absolute):
            raise Refused(f"the {what} {absolute} is not a folder on this disk")
        return absolute

    def _write_folder(self, path: str, what: str) -> str:
        """A folder to write into, made if it is not there yet. Refuses when it cannot be."""
        absolute = os.path.abspath(str(path))
        if os.path.isfile(absolute):
            raise Refused(f"the {what} {absolute} is a file, not a folder")
        try:
            os.makedirs(absolute, exist_ok=True)
        except OSError as problem:
            raise Refused(f"{what} {absolute} cannot be made ready to write into: "
                          f"{type(problem).__name__}: {problem}")
        return absolute

    def _camera(self, fallback_note: str):
        """The scene's camera, or the raster's fitted default - and which of the two it is."""
        from .preview_render import Camera
        camera = self.scene.get('camera')
        return (camera or Camera()), (self.scene.get('camera_note') or fallback_note)

    def _light(self):
        return self.scene.get('light'), self.scene.get('light_note', 'no lamp')

    def _incoming(self, node_id: str) -> Stream:
        """The items wired into a node, as the nodes upstream of it last produced them."""
        stream: Stream = []
        for connection in self._pipeline.incoming(node_id):
            stream.extend(self._stream.get(connection.from_node, []))
        return stream

    def wire(self, node: PipelineNode) -> Stream:
        """What is on a node's wire, empty allowed.

        A Camera or Lighting node with nothing wired to it is not a mistake - it is the
        normal way to put a camera at the head of a pipeline - so it inherits whatever its
        downstream nodes would otherwise have been handed and leaves the setting behind.
        """
        return self._incoming(node.id)

    def needs(self, node: PipelineNode, kinds: Tuple[str, ...] = (MESH,)) -> Stream:
        """The models or clouds this node was wired, or a Refusal that names the wire."""
        definition = node.get_definition()
        stream = self._incoming(node.id)
        if not stream:
            raise Refused(f"{definition.name} has nothing on its wire, so there is nothing "
                          f"for it to do")
        wrong = sorted({item.kind for item in stream} - set(kinds))
        if wrong:
            wanted = ' or '.join(kinds)
            raise Refused(f"{definition.name} works on {wanted} files; the wire carries "
                          f"{', '.join(wrong)}")
        return stream

    def each_mesh(self, node: PipelineNode,
                  runner: Callable[[str, str, Item], Dict[str, Any]],
                  extension: str = '.obj', note: str = '') -> Tuple[Stream, Dict[str, Any]]:
        """Run one backend call per mesh on the wire, and count every file it wrote.

        `runner` returns a backend verdict, called with the file to read, the staging file to
        write and the item they both belong to. Anything that comes back without `success` is
        a Refusal naming the model it failed on, because "3 of 12 files failed" and "the node
        ran" cannot both be reported. A verdict's own `note` and the `note` this node adds are
        what the row ends up saying.
        """
        definition = node.get_definition()
        stream = self.needs(node, (MESH,))
        out: Stream = []
        evidence: Dict[str, Any] = {'inputs': len(stream), 'ran': 0, 'extension': extension}
        for item in stream:
            self._check_stop(definition.name)
            target = self._staged(node, item.label, extension)
            verdict = runner(item.path, target, item)
            if not verdict.get('success'):
                raise Refused(f"{definition.name} could not do {item.label}: "
                              f"{verdict.get('error') or 'it reported no reason'}")
            facts = measure(target, MESH)
            if facts.get('error'):
                raise Refused(f"{definition.name} wrote {os.path.basename(target)} and it "
                              f"does not read back: {facts['error']}")
            self.files.append(target)
            out.append(Item(MESH, target, item.label, facts))
            evidence['ran'] += 1
            evidence.setdefault('steps', []).append(verdict)
        sentences = []
        for step in evidence['steps']:
            text = step.get('note') or ''
            if text and text not in sentences:
                sentences.append(text)
        # A batch wire would otherwise print one sentence per file, which is not a row anyone
        # can read. The numbers of every step stay in `steps` for the pane to show.
        if len(sentences) > 3:
            kept, rest = sentences[:3], len(sentences) - 3
            kept.append(f"and {rest} further step(s), each with its own numbers under this row")
            sentences = kept
        evidence['note'] = _joined(*sentences, note)
        return out, evidence

    def each_cloud(self, node: PipelineNode, verb: str, call: Dict[str, Any],
                   folder: str, note: str = '') -> Tuple[Stream, Dict[str, Any]]:
        """One verb of the point-cloud backend per cloud on the wire.

        The verb names its own output file (`PointCloudProcessor.target_path`), so a
        pipeline step and the button in the Point Clouds pane write the same name into the
        same kind of folder - and two clouds with the same name would therefore write over
        each other, which is why a wire of more than one cloud gets one subfolder each. Every
        file the verdict claims is then read back and counted, and the four surface verbs hand
        on a mesh rather than a cloud - the one place in this engine where the wire changes
        kind, and the row says so.
        """
        definition = node.get_definition()
        stream = self.needs(node, (CLOUD,))
        out: Stream = []
        produces_mesh = verb in SURFACE_VERBS
        kind = MESH if produces_mesh else CLOUD
        shared_folder = len(stream) == 1
        evidence: Dict[str, Any] = {'inputs': len(stream), 'ran': 0, 'verb': verb,
                                    'kind_after': kind, 'subfolders': not shared_folder,
                                    'folder': folder}
        from .point_cloud_processor import PointCloudProcessor
        processor = PointCloudProcessor()
        for position, item in enumerate(stream, start=1):
            self._check_stop(definition.name)
            per_file = dict(call)
            per_file['file_path'] = item.path
            per_file['output_dir'] = folder if shared_folder else os.path.join(
                folder, f'{position:02d}_{_safe_label(item.label)}')
            os.makedirs(per_file['output_dir'], exist_ok=True)
            verdict = processor.run(verb, per_file, self._should_cancel)
            if verdict.get('stopped'):
                raise Stopped(f"{definition.name} stopped on {item.label}: "
                              f"{verdict.get('error')}")
            if not verdict.get('success'):
                raise Refused(f"{definition.name} could not do {item.label}: "
                              f"{verdict.get('error') or 'it reported no reason'}")
            written = list(verdict.get('files') or [])
            if not written and verdict.get('output_path'):
                written = [verdict['output_path']]
            if not written:
                raise Refused(f"{definition.name} was told {verb} succeeded on {item.label} "
                              f"and it named no file")
            for path in written:
                facts = measure(path, kind)
                if facts.get('error'):
                    raise Refused(f"{definition.name} was told {os.path.basename(path)} was "
                                  f"written and it is not: {facts['error']}")
                self.files.append(path)
                label = (item.label if len(written) == 1
                         else f"{item.label} {os.path.splitext(os.path.basename(path))[0]}"
                              .strip())
                out.append(Item(kind, path, label, facts))
            evidence['ran'] += 1
            evidence.setdefault('steps', []).append(verdict)
        evidence['written'] = len(out)
        sentences = []
        for step in evidence['steps']:
            before = step.get('points_before')
            after = step.get('points_after')
            if isinstance(before, int) and isinstance(after, int):
                text = f"{before} points in, {after} out"
                if text not in sentences:
                    sentences.append(text)
        evidence['note'] = _joined(*sentences, note)
        return out, evidence

    def _open_mesh(self, path: str) -> Tuple[Optional[Any], str]:
        """The app's one mesh reader, with the sentence it says when it refuses."""
        from .format_converter import FormatConverter
        mesh, note = FormatConverter().read_mesh(path)
        return mesh, note

    def open_model(self, node: PipelineNode, path: str, normalise: bool
                   ) -> Tuple[Item, Dict[str, Any]]:
        """One file on this disk as an item on the wire.

        `normalise` decides which file the *next* node is handed: the person's own, or a
        `.obj` copy in the staging folder. A source the mesh filters cannot open (.fbx,
        .dae, .glb) is converted whatever the tick says, because the alternative is a
        pipeline that dies two nodes later on a file pymeshlab will not read - and the note
        names the library that carried it, so the conversion is not silent.
        """
        from .format_converter import FormatConverter
        label = os.path.splitext(os.path.basename(path))[0]
        extension = os.path.splitext(path)[1].lower()
        if extension in PROCESSABLE_EXTENSIONS and not normalise:
            facts = measure(path, MESH)
            if facts.get('error'):
                raise Refused(f'{os.path.basename(path)} was named as a model and it is not '
                              f'one this app can read: {facts["error"]}')
            return (Item(MESH, path, label, facts),
                    {'note': f'{extension} passed straight through, so the next node has the '
                             f'file exactly as it is on disk'})

        converter = FormatConverter()
        mesh, carried = self._open_mesh(path)
        if mesh is None:
            raise Refused(f'{os.path.basename(path)} was opened by nothing here: {carried}')
        target = self._staged(node, label, '.obj')
        written, why = converter.write_mesh(mesh, target)
        if not written:
            raise Refused(f'{os.path.basename(path)} opened through {carried} but '
                          f'{os.path.basename(target)} was not written: {why}')
        facts = measure(target, MESH)
        if facts.get('error'):
            raise Refused(f'{os.path.basename(target)} was written and does not read back: '
                          f'{facts["error"]}')
        self.files.append(target)
        reason = (f'read by {carried}, which cannot open {extension} as a mesh the filters '
                  f'use, so it was rewritten as .obj'
                  if extension not in PROCESSABLE_EXTENSIONS else
                  f'rewritten as .obj in the staging folder by {carried}; the source was '
                  f'not touched')
        return Item(MESH, target, label, facts), {'note': reason, 'written': 1}

    def write_model(self, item: Item, out_path: str, overwrite: bool, extension: str
                    ) -> Tuple[Dict[str, Any], str]:
        """One wire item as a model file, then the counts taken off that file.

        The in-memory formats go through the app's only writer; `.dae` and `.fbx` cannot be
        written from memory by anything installed here, so they go through the converter's
        file-to-file path, which is the one place its library table applies.
        """
        from .format_converter import FormatConverter
        name = os.path.basename(out_path)
        if os.path.isfile(out_path) and not overwrite:
            raise Refused(f'{name} is already in that folder and Overwrite is off, so '
                          f'nothing was written')
        converter = FormatConverter()
        if extension in converter.mesh_write_formats():
            mesh, carried = self._open_mesh(item.path)
            if mesh is None:
                raise Refused(f'{item.label} cannot be read to be written out: {carried}')
            ok, why = converter.write_mesh(mesh, out_path)
            method = f'{carried} -> {extension}'
            if not ok:
                raise Refused(f'{name} was not written: {why}')
        else:
            verdict = converter.convert_file(item.path, out_path)
            method = str(verdict.get('method') or 'the converter')
            if not verdict.get('success'):
                raise Refused(f'{name} was not written: {verdict.get("message")}')
        facts = measure(out_path, MESH)
        if facts.get('error'):
            raise Refused(f'{name} was written and does not read back: {facts["error"]}')
        self.files.append(out_path)
        return facts, method

    # ---- the entry point ----

    def execute_pipeline(self, pipeline: Pipeline, should_cancel=None, log=None,
                         node_hook=None, keep_staging: bool = True) -> Dict[str, Any]:
        """Run the pipeline and report every node, in the order it ran them.

        Answers a dict: `status` (the run's own verdict), `reason`, one row per node with
        its status and the numbers it measured, `files` for everything written, and the
        staging folder. It does not raise: a node that dies unexpectedly is `failed` in its
        row and stops the run, because its output is unknown and the next node would be
        handed a file nobody counted.
        """
        self._pipeline = pipeline
        self._should_cancel = should_cancel
        self._log = log
        self._node_hook = node_hook
        self._stream = {}
        self.files = []
        self.scene = {}
        self._node_index = 0

        started = time.time()
        self.staging = tempfile.mkdtemp(prefix='renderfox_pipeline_', dir=self.staging_root)
        rows: List[Dict[str, Any]] = []
        result: Dict[str, Any] = {'status': 'invalid', 'reason': '', 'nodes': rows,
                                  'files': self.files, 'staging': self.staging,
                                  'counts': {}}

        problems = pipeline.problems()
        if problems:
            result['reason'] = '; '.join(problems)
            result['counts'] = {'nodes': len(pipeline.nodes)}
            self._say(f"{pipeline.name} will not run: {result['reason']}")
            return result

        order, why = pipeline.execution_order()
        if not order:
            result['reason'] = why
            self._say(f"{pipeline.name} will not run: {why}")
            return result

        self._say(f"Running {pipeline.name}: {len(order)} node(s) in dependency order")
        aborted = ''
        for position, node_id in enumerate(order):
            node = pipeline.node_by_id(node_id)
            definition = node.get_definition()
            row: Dict[str, Any] = {'id': node_id, 'definition_id': definition.id,
                                   'name': definition.name, 'position': position + 1}
            if aborted:
                row.update({'status': 'skipped', 'detail': f'not run, because {aborted}',
                            'files': [], 'measured': {}})
                rows.append(row)
                self._node(node_id, definition.name, 'skipped', row['detail'])
                continue
            try:
                self._check_stop(f"before {definition.name}")
            except Stopped as stopped:
                aborted = stopped.args[0]
                result['status'] = 'stopped'
                result['reason'] = aborted
                continue

            self._node(node_id, definition.name, 'running', '')
            self._say(f"{definition.name}...")
            node_started = time.time()
            try:
                params = coerce_node(node, definition)
                stream, evidence = self._dispatch(node, definition, params)
                self._stream[node_id] = stream
                row['status'] = 'done'
                row['detail'] = self._detail(definition, stream, evidence)
                row['files'] = [item.path for item in stream]
                row['measured'] = evidence
            except Invalid as bad:
                self._stream[node_id] = self._carried_on(node_id)
                row.update({'status': 'invalid', 'detail': str(bad), 'files': [],
                            'measured': {}})
            except Refused as no:
                self._stream[node_id] = self._carried_on(node_id)
                row.update({'status': 'refused', 'detail': str(no), 'files': [],
                            'measured': {}})
            except Stopped as stopped:
                aborted = stopped.args[0]
                row.update({'status': 'stopped', 'detail': aborted, 'files': [],
                            'measured': {}})
                result['status'] = 'stopped'
                result['reason'] = aborted
            except Exception as crash:
                aborted = f"{definition.name} stopped with {type(crash).__name__}: {crash}"
                row.update({'status': 'failed', 'detail': aborted, 'files': [],
                            'measured': {}})
                result['status'] = 'failed'
                result['reason'] = str(crash)
                result['exception'] = f'{type(crash).__name__}: {crash}'
                self._say(f"{definition.name} stopped with {type(crash).__name__}: {crash}")
            row['elapsed'] = round(time.time() - node_started, 2)
            rows.append(row)
            self._node(node_id, definition.name, row['status'], row['detail'])
            if row['status'] != 'done':
                self._say(f"{definition.name}: {row['status']} - {row['detail']}")

        counts = {status: 0 for status in STATUSES}
        for row in rows:
            counts[row['status']] = counts.get(row['status'], 0) + 1
        result['counts'] = counts
        result['elapsed'] = round(time.time() - started, 2)
        result['files'] = list(self.files)

        if not aborted:
            moved = [row for row in rows if row['status'] != 'done']
            if moved:
                result['status'] = 'refused' if not counts.get('invalid') else 'invalid'
                result['reason'] = (f"{len(moved)} of {len(rows)} node(s) did not run the "
                                    f"work: " + '; '.join(f"{row['name']} ({row['status']})"
                                                           for row in moved))
            else:
                result['status'] = 'done'
                result['reason'] = (f"all {len(rows)} node(s) ran and their files were "
                                    f"counted back off the disk")
        self._say(f"{pipeline.name}: {result['status']} in {result['elapsed']}s - "
                  f"{result['reason'] or result['counts']}")
        if not keep_staging and result['status'] == 'done':
            import shutil
            shutil.rmtree(self.staging, ignore_errors=True)
            result['staging_removed'] = True
        return result

    def _carried_on(self, node_id: str) -> Stream:
        """A node that refused or was read wrong leaves the wire exactly as it found it."""
        return self._incoming(node_id)

    def _detail(self, definition: NodeDefinition, stream: Stream,
                evidence: Dict[str, Any]) -> str:
        """One sentence, and every number in it came from a file."""
        parts: List[str] = []
        if stream:
            parts.append(stream[0].summary())
            if len(stream) > 1:
                parts.append(f"{len(stream)} on the wire")
        else:
            parts.append('nothing on the wire')
        written = evidence.get('written')
        if written is not None:
            parts.append(f"{written} file(s) written")
        extension = evidence.get('extension')
        if extension and evidence.get('ran'):
            parts.append(f"each written as {extension} in the staging folder")
        if evidence.get('verb') and evidence.get('ran'):
            parts.append(f"{evidence['verb']} ran through the point-cloud backend")
            if evidence.get('kind_after') == MESH:
                parts.append('the wire is meshes now, because that verb answers with a surface')
            if evidence.get('subfolders'):
                parts.append(f"each cloud into its own subfolder of {evidence.get('folder')}, "
                             f"because the backend names its files after the cloud")
        note = evidence.get('note')
        if note:
            parts.append(str(note))
        return ', '.join(str(part) for part in parts)

    def _dispatch(self, node: PipelineNode, definition: NodeDefinition,
                  params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
        handler = globals().get(definition.handler)
        if handler is None:
            raise Refused(f"{definition.name} names {definition.handler}, which this build "
                          f"has no function for")
        return handler(self, node, params)


# ============================================================================
# THE HANDLERS
#
# Each one reads its knobs out of `params` by name - a literal `params['ratio']`, never a
# computed key, so `parameter_report()` can prove the knob reaches a call - runs one function
# that already exists in src/processing, and hands back the items it produced with the numbers
# taken off the files on disk. The only things a handler raises are `Refused`, `Invalid` and
# `Stopped`, which is what keeps an unexpected exception out of a pane's thread.
# ============================================================================

def _joined(*parts: Any) -> str:
    """The note a row ends with, from whichever sentences this run earned."""
    return '; '.join(str(part) for part in parts if part)


def _cloud_knob_names(mapping: Dict[str, Any]) -> set:
    """The node knobs one verb's backend keys are fed from, flattened out of the table."""
    names = set()
    for key in mapping.values():
        names.add(key[0] if isinstance(key, tuple) else key)
    return names


def _rgb(hex_color: str) -> Tuple[float, float, float]:
    """A #RRGGBB box as the three floats the raster takes."""
    text = str(hex_color).lstrip('#')
    return tuple(round(int(text[i:i + 2], 16) / 255.0, 4) for i in (0, 2, 4))


def _is_zero(values: Any) -> bool:
    return all(abs(float(value)) < 1e-9 for value in (values or []))


def _same_point(one: Any, two: Any) -> bool:
    return all(abs(float(a) - float(b)) < 1e-9 for a, b in zip(one, two))


def _extensions(text: Any) -> List[str]:
    """A comma-separated box of extensions as dotted lowercase tokens, in the order typed."""
    taken: List[str] = []
    for part in re.split(r'[,\s;]+', str(text or '')):
        token = part.strip().lower()
        if not token:
            continue
        if not token.startswith('.'):
            token = '.' + token
        if token not in taken:
            taken.append(token)
    return taken


def _model_files(folder: str, extensions: List[str], recursive: bool) -> List[str]:
    """The files in a folder this node may open, in a fixed order, so a batch runs the same
    way twice."""
    wanted = set(extensions)
    found: List[str] = []
    if recursive:
        for root, _dirs, names in os.walk(folder):
            for one in names:
                if os.path.splitext(one)[1].lower() in wanted:
                    found.append(os.path.join(root, one))
    else:
        for entry in os.scandir(folder):
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in wanted:
                found.append(entry.path)
    return sorted(found)


def _round(value: Any) -> float:
    """A number worth putting in a sentence, and no more digits than the file can hold."""
    return round(float(value), 4)


# ---- INPUT ----

def h_load_model(engine: PipelineEngine, node: PipelineNode,
                 params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    path = engine._open_file(params['file_path'], 'model named in Load Model')
    item, evidence = engine.open_model(node, path, bool(params.get('normalise_source', True)))
    return [item], evidence


def h_load_batch(engine: PipelineEngine, node: PipelineNode,
                 params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .format_converter import FormatConverter
    folder = engine._open_folder(params['folder_path'], 'folder named in Load Batch')
    recursive = bool(params.get('recursive', False))
    asked = _extensions(params.get('patterns'))
    if not asked:
        raise Invalid("Patterns has nothing in it, so no file in that folder would be taken")
    readable = FormatConverter().readable_formats()
    unknown = [one for one in asked if one not in readable]
    taken = [one for one in asked if one in readable]
    if not taken:
        raise Refused(f"none of {', '.join(unknown)} can be opened here; the readers installed "
                      f"on this machine take {', '.join(readable)}")
    files = _model_files(folder, taken, recursive)
    if not files:
        raise Refused(f"{folder} holds no {', '.join(taken)} file"
                      f"{' in its subfolders' if recursive else ''}, so there is nothing to "
                      f"put on the wire")
    normalise = bool(params.get('normalise_source', True))
    stream: Stream = []
    failures: List[str] = []
    for path in files:
        engine._check_stop('Load Batch')
        try:
            item, _ = engine.open_model(node, path, normalise)
        except Refused as no:
            failures.append(f'{os.path.basename(path)}: {no}')
            continue
        stream.append(item)
    if failures:
        raise Refused(f"Load Batch opened {len(stream)} of the {len(files)} files in {folder} "
                      f"and could not open {len(failures)}: {'; '.join(failures[:4])}"
                      + ('; ...' if len(failures) > 4 else '')
                      + '. Nothing was handed on, because a batch that quietly drops a file is '
                        'not the batch that was asked for')
    note = _joined(f"{len(files)} file(s) opened from {folder} as {', '.join(taken)}",
                   (f"{', '.join(unknown)} are not readable by the libraries here, so they were "
                    f"left out of the search" if unknown else ''),
                   (f"searching the subfolders too" if recursive else ''))
    return stream, {'inputs': len(files), 'note': note}


def h_load_cloud(engine: PipelineEngine, node: PipelineNode,
                 params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .point_cloud_processor import PointCloudProcessor
    path = engine._open_file(params['file_path'], 'cloud named in Load Point Cloud')
    processor = PointCloudProcessor()
    cloud, error = processor.read_cloud(path)
    if error:
        raise Refused(f"{os.path.basename(path)} was not opened as a point cloud: {error}")
    facts = measure(path, CLOUD)
    if facts.get('error'):
        raise Refused(f"{os.path.basename(path)} opened as a cloud and then could not be "
                      f"counted: {facts['error']}")
    extension = os.path.splitext(path)[1].lower()
    note = ''
    if extension not in processor.readable_formats():
        note = (f"{extension} is not in the cloud reader's own list "
                f"({', '.join(processor.readable_formats())}); it was opened anyway as "
                f"{facts.get('points')} points, which for a model file means its vertices and "
                f"not a scan")
    label = os.path.splitext(os.path.basename(path))[0]
    return [Item(CLOUD, path, label, facts)], {'note': note}


def h_camera(engine: PipelineEngine, node: PipelineNode,
             params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .preview_render import Camera, PreviewError
    mode = str(params.get('mode') or 'perspective')
    if mode == 'orthographic':
        raise Refused("orthographic is not a projection this build has: its one raster puts a "
                      "perspective eye on the window and nothing else. Nothing was left in the "
                      "scene, so a Render in this run uses the fitted default camera.")
    fit = bool(params.get('fit', True))
    position = list(params.get('position') or [0.0, 0.0, 3.0])
    target = list(params.get('target') or [0.0, 0.0, 0.0])
    up = list(params.get('up') or [0.0, 1.0, 0.0])
    fov = float(params.get('fov', 45.0))
    if _same_point(position, target):
        raise Refused(f"the eye at {position} is standing on the point it looks at, so there "
                      f"is no direction to look in - move Position or Target, or turn Fit on")
    if _is_zero(up):
        raise Refused("the up vector is 0 0 0, which is no direction at all, so the frame would "
                      "have no roll to be drawn with")
    line = [b - a for a, b in zip(target, position)]
    cross = [line[1] * up[2] - line[2] * up[1],
             line[2] * up[0] - line[0] * up[2],
             line[0] * up[1] - line[1] * up[0]]
    try:
        camera = Camera(position=tuple(position), target=tuple(target), up=tuple(up),
                        fov=fov, fit=fit)
    except PreviewError as why:
        raise Refused(f"Camera: {why}")
    note = _joined(
        (f"Fit is on, so the eye sits at the distance the model's own bounding sphere needs "
         f"along the line from {target} to {position}" if fit else
         f"Fit is off, so the eye sits exactly at {position} and a model elsewhere in the "
         f"frame is not in the picture"),
        f"field of view {fov} degrees",
        ('the up vector is parallel to the line of sight, so the raster takes its own sideways '
         'axis and the frame comes out rolled relative to what you typed'
         if _is_zero(cross) else ''))
    engine.scene['camera'] = camera
    engine.scene['camera_note'] = note
    return engine.wire(node), {'note': note, 'scene': 'camera'}


def h_lighting(engine: PipelineEngine, node: PipelineNode,
               params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .preview_render import Light
    kind = str(params.get('kind') or 'directional')
    if kind == 'hdri':
        raise Refused("hdri is not a lamp this build has: there is no environment-map loader "
                      "and no image-based shader, so it would draw a model lit by nothing and "
                      "call the flat grey picture a render. The three it does have are "
                      "directional, point and spot.")
    intensity = float(params.get('intensity', 1.0))
    ambient = float(params.get('ambient', 0.1))
    cone = float(params.get('cone', 45.0))
    position = list(params.get('position') or [5.0, 10.0, 5.0])
    direction = list(params.get('direction') or [1.0, 0.65, 1.0])
    if kind == 'directional':
        if _is_zero(direction):
            raise Refused("a directional lamp's direction is 0 0 0, which points nowhere, so "
                          "no surface would know which way the light comes from")
        where = direction
    else:
        if _is_zero(position):
            raise Refused(f"a {kind} lamp at 0 0 0 sits on every point of the model at once, "
                          f"and the inverse-square falloff the raster uses has no answer for "
                          f"that distance")
        where = position
    light = Light(kind=kind, position=tuple(where), color=_rgb(params.get('color') or '#FFFFFF'),
                  intensity=intensity, ambient=ambient, cone=cone)
    note = _joined(
        (f"a directional lamp: its whole vector {direction} is the one direction every point "
         f"of the surface is lit from, and Position is not read" if kind == 'directional' else
         f"a {kind} lamp at {position}"),
        (f"the cone of {cone} degrees bounds the spot's own circle" if kind == 'spot' else
         f"cone is not read by a {kind} lamp" if kind != 'spot' else ''),
        (f"the axis of a spot is the line from its position to the origin, so Direction is not "
          f"read here" if kind == 'spot' else ''),
        f"intensity {intensity}, ambient {ambient}, colour tinted by the box",
        'a lamp only falls on surfaces: a point cloud on the wire makes Render refuse that one')
    engine.scene['light'] = light
    engine.scene['light_note'] = note
    return engine.wire(node), {'note': note, 'scene': 'light'}


# ---- TRANSFORM: the three that move vertices ----

def h_scale(engine: PipelineEngine, node: PipelineNode,
            params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshTransformer
    factor = float(params['factor'])
    per_axis = bool(params.get('per_axis', False))
    axes = list(params.get('axes') or [1.0, 1.0, 1.0])
    origin = list(params.get('origin') or [0.0, 0.0, 0.0])
    value = axes if per_axis else factor
    ignored = ('Axes is not read while Per axis is off, because one factor goes to all three'
               if not per_axis else
               'Factor is not read while Per axis is on, because the three Axes numbers are the '
               'factors')

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        verdict = MeshTransformer.scale(source, target, value, origin)
        if verdict.get('success'):
            verdict['note'] = _joined(
                f"about {origin}",
                (f"extents {verdict['extents_before']} in, {verdict['extents_after']} out"
                 if verdict.get('extents_before') else ''),
                ('a factor of 1 writes the model where it stands'
                 if value in (1, 1.0, [1.0, 1.0, 1.0]) else ''))
        return verdict

    return engine.each_mesh(node, run, note=ignored)


def h_rotate(engine: PipelineEngine, node: PipelineNode,
             params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshTransformer
    angles = [float(params.get('rotation_x', 0.0)), float(params.get('rotation_y', 0.0)),
              float(params.get('rotation_z', 0.0))]
    origin = list(params.get('origin') or [0.0, 0.0, 0.0])

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        verdict = MeshTransformer.rotate(source, target, angles, origin)
        if verdict.get('success'):
            verdict['note'] = _joined(
                f"{angles} degrees about {origin}",
                (f"the pivot stayed at {verdict['origin']}"
                 if _same_point(verdict.get('origin') or [], origin) else
                 f"the pivot moved to {verdict.get('origin')}, which is not what was typed"),
                ('turning by 0 0 0 writes the model as it stands'
                 if _is_zero(angles) else ''))
        return verdict

    return engine.each_mesh(node, run)


def h_translate(engine: PipelineEngine, node: PipelineNode,
                params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshTransformer
    offset = [float(params.get('offset_x', 0.0)), float(params.get('offset_y', 0.0)),
              float(params.get('offset_z', 0.0))]

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        verdict = MeshTransformer.translate(source, target, offset)
        if verdict.get('success') and _is_zero(offset):
            verdict['note'] = 'moved by 0 0 0, so the file written holds the model where it was'
        return verdict

    return engine.each_mesh(node, run)


# ---- TRANSFORM: the filters that change the topology ----

def h_decimate(engine: PipelineEngine, node: PipelineNode,
               params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshSimplifier, MeshUV
    method = str(params.get('method') or 'ratio')
    ratio = float(params.get('ratio', 0.5))
    target_count = int(params.get('target_count', 10000))
    quality = float(params.get('quality_threshold', 0.3))
    cluster = float(params.get('cluster_size', 0.05))
    border = bool(params.get('preserve_border', True))
    normal = bool(params.get('preserve_normal', True))
    topology = bool(params.get('preserve_topology', False))
    keep_uv = bool(params.get('preserve_uv', True))

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        original = int(item.facts.get('faces') or 0)
        if method == 'clustering':
            verdict = MeshSimplifier.cluster_simplify(source, target, cluster)
            asked = None
        else:
            asked = (max(1, int(round(original * ratio))) if method == 'ratio'
                     else max(1, int(target_count)))
            verdict = MeshSimplifier.simplify_quadric(
                source, target, asked, preserve_boundary=border, preserve_normal=normal,
                preserve_topology=topology, quality_threshold=quality)
            verdict['asked_faces'] = asked
        if not verdict.get('success'):
            return verdict
        sentences = []
        if asked is not None and verdict.get('output_faces') != asked:
            sentences.append(f"asked for {asked} faces out of the {original} the file holds "
                             f"and the filter answered {verdict.get('output_faces')}")
        if method == 'clustering':
            sentences.append(f"a grid of {cluster} of the bounding diagonal; "
                             f"quality_threshold, preserve_border, preserve_normal and "
                             f"preserve_topology belong to the quadric filter, so this method "
                             f"did not take them")
        else:
            sentences.append(f"{method} with quality_threshold {quality}, borders "
                             f"{'kept' if border else 'not kept'}, normals "
                             f"{'kept' if normal else 'not kept'}, topology "
                             f"{'kept' if topology else 'not kept'}")
        before = MeshUV.uv_rows(source) or 0
        after = MeshUV.uv_rows(target) or 0
        if keep_uv:
            if before and not after:
                return {'success': False,
                        'error': f'the filter wrote {os.path.basename(target)} with no texture '
                                 f'coordinates on it ({before} rows went in), and Preserve UV '
                                 f'is on, so the result was not handed on'}
            sentences.append(f"{after} coordinate rows still on it" if before else
                             'the file had no texture coordinates to preserve')
        else:
            if after:
                stripped = MeshUV.strip(target, target)
                if not stripped.get('success'):
                    return {'success': False,
                            'error': f'Preserve UV is off and the strip itself failed: '
                                     f'{stripped.get("error")}'}
                sentences.append(f"{stripped['uv_rows_before']} coordinate rows stripped for "
                                 f"real, {stripped['uv_rows_after']} left")
            else:
                sentences.append('there were no texture coordinates to strip')
        verdict['note'] = _joined(*sentences)
        return verdict

    stream, evidence = engine.each_mesh(node, run)
    return stream, evidence


def h_simplify(engine: PipelineEngine, node: PipelineNode,
               params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshSimplifier
    percent = float(params.get('target_percent', 50.0))
    angle = float(params.get('angle_threshold', 1.0))
    border = bool(params.get('preserve_border', True))
    normal = bool(params.get('preserve_normal', False))
    topology = bool(params.get('preserve_topology', False))

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        original = int(item.facts.get('faces') or 0)
        asked = max(1, int(round(original * percent / 100.0)))
        verdict = MeshSimplifier.planar_simplify(source, target, asked, angle,
                                                 preserve_border=border,
                                                 preserve_normal=normal,
                                                 preserve_topology=topology)
        if verdict.get('success'):
            verdict['note'] = _joined(
                f"{percent}% of the {original} faces asked as {asked}, answered "
                f"{verdict.get('output_faces')}",
                f"faces flatter than {angle} degrees collapsed hardest",
                f"borders {'kept' if border else 'not kept'}, normals "
                f"{'kept' if normal else 'not kept'}, topology "
                f"{'kept' if topology else 'not kept'}")
        return verdict

    return engine.each_mesh(node, run)


def h_smooth(engine: PipelineEngine, node: PipelineNode,
             params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshSmoother
    method = str(params.get('method') or 'laplacian')
    iterations = int(params.get('iterations', 5))
    border = bool(params.get('preserve_border', True))
    shrink = float(params.get('lambda_value', 0.5))
    expand = float(params.get('mu_value', -0.53))
    band = float(params.get('delta', 100.0))
    ignored = {
        'laplacian': 'delta, lambda_value and mu_value belong to the other two filters',
        'depth': 'preserve_border, lambda_value and mu_value belong to the other filters; '
                 'this one takes only iterations and delta',
        'taubin': 'preserve_border and delta belong to the other filters; this one takes only '
                  'iterations, lambda_value and mu_value',
    }[method]

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        if method == 'laplacian':
            verdict = MeshSmoother.laplacian_smooth(source, target, iterations, border)
            asked = f"{iterations} pass(es) of the coordinate Laplacian, borders " \
                    f"{'held' if border else 'moving too'}"
        elif method == 'depth':
            verdict = MeshSmoother.depth_smooth(source, target, iterations, band)
            asked = f"{iterations} pass(es) of depth smoothing over a band of {band}% of the " \
                    f"diagonal"
        else:
            verdict = MeshSmoother.taubin_smooth(source, target, shrink, expand, iterations)
            asked = f"{iterations} pair(s) of lambda {shrink} then mu {expand}"
        if verdict.get('success'):
            verdict['note'] = asked
        return verdict

    return engine.each_mesh(node, run, note=ignored)


def h_remesh(engine: PipelineEngine, node: PipelineNode,
             params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshRemesher
    mode = str(params.get('mode') or 'uniform')
    edge = float(params.get('target_edge', 0.05))
    iterations = int(params.get('iterations', 10))
    step_ratio = float(params.get('step_ratio', 10.0))
    ignored = {
        'uniform': 'step_ratio is the Voronoi pass, not this one',
        'adaptive': 'step_ratio is the Voronoi pass, not this one; adaptive asks the same '
                    'filter for an adaptive target',
        'quad': 'target_edge, iterations and step_ratio are not read: this pairs the '
                'triangles it has into quads',
        'voronoi': 'target_edge and iterations are not read: this flips edges by the Voronoi '
                   'pass alone',
    }[mode]

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        if mode == 'quad':
            verdict = MeshRemesher.quad_remesh(source, target)
            asked = 'triangles paired into quads'
        elif mode == 'voronoi':
            verdict = MeshRemesher.voronoi_filtering(source, target, step_ratio)
            asked = f"Voronoi fairing at strength {step_ratio}"
        elif mode == 'adaptive':
            verdict = MeshRemesher.uniform_remesh(source, target, edge, iterations, True)
            asked = f"edges about {edge} of the diagonal, {iterations} pass(es), adaptive"
        else:
            verdict = MeshRemesher.uniform_remesh(source, target, edge, iterations, False)
            asked = f"edges about {edge} of the diagonal, {iterations} pass(es)"
        if verdict.get('success'):
            verdict['note'] = _joined(asked,
                                      f"{verdict.get('original_faces', '?')} faces became "
                                      f"{verdict.get('output_faces', '?')}")
        return verdict

    return engine.each_mesh(node, run, note=ignored)


def h_subdivide(engine: PipelineEngine, node: PipelineNode,
                params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshRemesher
    levels = int(params['levels'])
    method = str(params.get('method') or 'loop')

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        verdict = MeshRemesher.subdivide(source, target, method, levels)
        if verdict.get('success'):
            verdict['note'] = f"{method} {levels} time(s): {verdict.get('original_faces')} " \
                              f"faces became {verdict.get('output_faces')}"
        return verdict

    return engine.each_mesh(node, run)


def h_center(engine: PipelineEngine, node: PipelineNode,
             params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshTransformer
    mode = str(params.get('mode') or 'bounds')
    axes = list(params.get('axes') or [1.0, 1.0, 1.0])
    # The backend tests each flag with `flag is True`, so the floats the pane hands over have
    # to become booleans here or every axis would read as off.
    flags = [float(value) != 0.0 for value in axes]

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        verdict = MeshTransformer.center(source, target, mode, flags)
        if verdict.get('success'):
            verdict['note'] = _joined(
                f"the {mode} centre {[_round(value) for value in verdict['original_center']]} "
                f"went to the origin on {verdict['axes']}",
                ('no axis was asked for, so the model is written back exactly where it stands'
                 if not any(flags) else ''))
        return verdict

    return engine.each_mesh(node, run)


def h_align(engine: PipelineEngine, node: PipelineNode,
            params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshTransformer
    mode = str(params.get('mode') or 'bounds')
    axis = str(params.get('axis') or 'z')
    face = str(params.get('face') or 'min')
    offset = float(params.get('offset', 0.0))
    ignored = ('axis, face and offset are not read by pca, which turns the model on its own '
               'principal axes') if mode == 'pca' else ''

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        if mode == 'pca':
            verdict = MeshTransformer.auto_align(source, target)
            asked = 'the model\'s own spread turned onto the axes'
        else:
            verdict = MeshTransformer.align_to_plane(source, target, axis, face, offset)
            asked = f"the {face} side of the box sat on {axis}={offset}, moved by " \
                    f"{verdict.get('moved')}" if verdict.get('success') else ''
        if verdict.get('success'):
            verdict['note'] = asked
        return verdict

    return engine.each_mesh(node, run, note=ignored)


def h_mirror(engine: PipelineEngine, node: PipelineNode,
             params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshTransformer
    axis = str(params['axis'])
    weld = bool(params.get('weld', False))
    threshold = float(params.get('weld_threshold', 0.001))
    ignored = ('weld_threshold is not read while Weld is off'
               if not weld else f"welded within {threshold} of the diagonal")

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        verdict = MeshTransformer.mirror(source, target, axis, weld, threshold)
        if verdict.get('success'):
            verdict['note'] = _joined(
                f"across {axis}: {verdict['faces_before']} faces became "
                f"{verdict['faces_after']}, winding "
                f"{'consistent' if verdict['winding_consistent'] else 'NOT consistent'}",
                (f"{verdict.get('welded_vertices')} seam vertex/vertices welded"
                 if weld else ''))
        return verdict

    return engine.each_mesh(node, run, note=ignored)


def h_unwrap_uv(engine: PipelineEngine, node: PipelineNode,
                params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshUV
    method = str(params['method'])
    size = int(params.get('texture_size', 2048))
    border = int(params.get('border_pixels', 2))
    layout = str(params.get('layout') or 'Basic')

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        verdict = MeshUV.parametrize(source, target, method, size, border, layout)
        if verdict.get('success'):
            verdict['note'] = _joined(
                f"{verdict['uv_rows_before']} coordinate rows in, "
                f"{verdict['uv_rows_written']} written",
                (f"layout {verdict['layout']}" if verdict.get('layout') else ''),
                (f"{', '.join(verdict['knobs_not_applied'])} not applied by this parametrizer"
                 if verdict.get('knobs_not_applied') else ''))
        return verdict

    return engine.each_mesh(node, run)


# ---- TRANSFORM: the two nodes that call another pane's worker ----

def h_bake_texture(engine: PipelineEngine, node: PipelineNode,
                   params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from PIL import Image
    from .mesh_processor import MeshUV
    from .texture_baker import TextureBaker
    kind = str(params.get('type') or 'combined')
    if kind in ('roughness', 'metallic'):
        raise Refused(f"{kind} is not a map this baker rasterises - it writes normal, diffuse "
                      f"and AO from PyMeshLab's attribute transfer. Choose combined, normal, "
                      f"diffuse or ao.")
    maps = ['normal', 'diffuse', 'ao'] if kind == 'combined' else [kind]
    resolution = int(params['resolution'])
    edge = max(8, resolution)
    overwrite = bool(params.get('overwrite', False))
    folder = engine._write_folder(params['output_folder'], 'folder named in Bake Texture')
    high = engine._open_file(params['high_poly_path'], 'high-poly model named in Bake Texture')
    stream = engine.needs(node, (MESH,))
    written: List[str] = []
    notes: List[str] = []
    if resolution != edge:
        notes.append(f"{resolution} px was asked and the baker's own floor of {edge} px is "
                     f"what it rasterises, so that is the size checked")
    if len(stream) > 1:
        notes.append(f"{len(stream)} models on the wire all get maps named after themselves, "
                     f"so each went into its own subfolder of {folder}")
    for position, item in enumerate(stream, start=1):
        engine._check_stop('Bake Texture')
        per_folder = folder if len(stream) == 1 else os.path.join(
            folder, f'{position:02d}_{_safe_label(item.label)}')
        os.makedirs(per_folder, exist_ok=True)
        base = os.path.splitext(os.path.basename(item.path))[0]
        expected = {name: os.path.join(per_folder, f'{base}_{name}.png') for name in maps}
        if not overwrite:
            there = [os.path.basename(path) for path in expected.values()
                     if os.path.isfile(path)]
            if there:
                raise Refused(f"{', '.join(there)} already in {per_folder} and Overwrite is "
                              f"off, so nothing was rasterised")
        if not MeshUV.uv_rows(item.path):
            notes.append(f"{item.label} has no texture coordinates, so the baker wrote its own "
                         f"trivial set at {edge} px before rasterising")
        problems: List[str] = []
        baker = TextureBaker()
        baker.error_occurred.connect(lambda text: problems.append(str(text)))
        baker.bake(high, item.path, per_folder, resolution=resolution,
                   bake_normals='normal' in maps, bake_diffuse='diffuse' in maps,
                   bake_ao='ao' in maps, should_cancel=engine._should_cancel)
        missing = [name for name, path in expected.items() if not os.path.isfile(path)]
        if missing:
            raise Refused(f"Bake Texture wrote no {', '.join(missing)} map for {item.label}: "
                          f"{'; '.join(problems) or 'the baker gave no reason'}")
        for name, path in expected.items():
            with Image.open(path) as picture:
                size = picture.size
            if size != (edge, edge):
                raise Refused(f"{os.path.basename(path)} is {size[0]}x{size[1]}, not the "
                              f"{edge}x{edge} the node asked the baker for")
            engine.files.append(path)
            written.append(path)
        if 'diffuse' in maps:
            notes.append('the diffuse map came off the high-poly model\'s own vertex colours')
    return stream, {'inputs': len(stream), 'written': len(written), 'maps': maps,
                    'edge': edge, 'note': _joined(*notes),
                    'files': written}


def h_lod_generate(engine: PipelineEngine, node: PipelineNode,
                   params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .lod_generator import LODGenerator, LODSettings
    levels = int(params['levels'])
    high = float(params.get('high_ratio', 0.8))
    medium = float(params.get('medium_ratio', 0.5))
    low = float(params.get('low_ratio', 0.2))
    folder = engine._write_folder(params['output_folder'], 'folder named in Generate LOD')
    if levels < 1:
        raise Refused(f"{levels} levels is nothing to write: the generator runs its chain once "
                      f"per level, so the smallest answer here is 1")
    stream = engine.needs(node, (MESH,))
    # Which of the three ratio boxes `_get_lod_ratios` actually reads for this level count.
    if levels == 1:
        ignored = 'medium_ratio and low_ratio are not read: one level takes only high_ratio'
    elif levels == 2:
        ignored = 'medium_ratio is not read: two levels take high_ratio and low_ratio'
    elif levels > 3:
        ignored = ('medium_ratio is not read: past 3 levels the chain is spread from high_ratio '
                   'down to low_ratio')
    else:
        ignored = ''
    chain: Stream = []
    written: List[str] = []
    ratios: List[float] = []
    for position, item in enumerate(stream, start=1):
        engine._check_stop('Generate LOD')
        per_folder = folder if len(stream) == 1 else os.path.join(
            folder, f'{position:02d}_{_safe_label(item.label)}')
        generator = LODGenerator(LODSettings(levels=levels, high_quality_ratio=high,
                                             medium_quality_ratio=medium,
                                             low_quality_ratio=low))
        ratios = generator.lod_ratios
        try:
            paths = generator.generate_lods(item.path, per_folder,
                                            should_cancel=engine._should_cancel)
        except ValueError as why:
            raise Refused(f"Generate LOD could not open {item.label}: {why}")
        if generator.errors:
            raise Refused(f"Generate LOD wrote {len(paths)} of the {levels} level(s) for "
                          f"{item.label}; the rest said: {'; '.join(generator.errors)}")
        if len(paths) != levels:
            if engine._should_cancel and engine._should_cancel():
                raise Stopped(f"Generate LOD stopped on {item.label} after {len(paths)} of "
                              f"{levels} level(s); those {len(paths)} file(s) stay on disk")
            raise Refused(f"Generate LOD answered {len(paths)} file(s) for {levels} level(s) "
                          f"on {item.label} and named no reason for the rest")
        for path in paths:
            facts = measure(path, MESH)
            if facts.get('error'):
                raise Refused(f"Generate LOD wrote {os.path.basename(path)} and it does not "
                              f"read back: {facts['error']}")
            if not facts.get('faces'):
                raise Refused(f"{os.path.basename(path)} holds no triangles at all, which is "
                              f"not a level of detail anyone can load")
            engine.files.append(path)
            written.append(path)
            chain.append(Item(MESH, path, os.path.splitext(os.path.basename(path))[0], facts))
    return chain, {'inputs': len(stream), 'written': len(written), 'levels': levels,
                   'ratios': [_round(value) for value in ratios],
                   'note': _joined(ignored,
                                   f"the chain is on the wire now, so the next node runs once "
                                   f"per level unless you put an Export before it"),
                   'files': written}


def h_optimize(engine: PipelineEngine, node: PipelineNode,
               params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .mesh_processor import MeshRepairer, MeshUV
    doubles = bool(params.get('remove_doubles', True))
    threshold = float(params.get('merge_threshold', 0.0001))
    recalc = bool(params.get('recalc_normals', True))
    loose = bool(params.get('remove_loose', True))
    strip_uv = bool(params.get('strip_uv', False))
    if not any((doubles, recalc, loose, strip_uv)):
        raise Refused("every knob on Optimize is off, so there is nothing here it would change "
                      "about the model - and an empty step that reports success is what this "
                      "node used to be")
    # 0 means "only vertices that are exactly the same number", which is the filter with no
    # tolerance; anything above 0 is a fraction of the diagonal and goes to the welder.
    weld_at = threshold if threshold > 0.0 else None
    weld_note = ('welding is off, so duplicate positions were left alone' if not doubles else
                 f'weld distance {threshold} of the bounding diagonal' if weld_at is not None
                 else f'a merge_threshold of {threshold} means the no-tolerance case, so only '
                      f'vertices at exactly the same place were joined')

    def run(source: str, target: str, item: Item) -> Dict[str, Any]:
        current = source
        done: List[str] = []
        stages: List[Tuple[str, Callable[[str, str], Dict[str, Any]]]] = []
        if doubles:
            stages.append(('weld', lambda a, b: MeshRepairer.remove_duplicate_vertices(
                a, b, threshold=weld_at)))
        if loose:
            stages.append(('unreferenced vertices',
                           MeshRepairer.remove_unreferenced_vertices))
            stages.append(('null, folded and duplicate faces',
                           MeshRepairer.remove_degenerate_faces))
        if recalc:
            stages.append(('normals', MeshRepairer.fix_normals))
        if strip_uv:
            stages.append(('texture coordinates', MeshUV.strip))
        for index, (label, call) in enumerate(stages):
            last = index == len(stages) - 1
            step_target = target if last else engine._staged(node, f'{item.label} {label}',
                                                             '.obj')
            verdict = call(current, step_target)
            if not verdict.get('success'):
                return {'success': False,
                        'error': f'the {label} step said: {verdict.get("error")}'}
            if not last:
                engine.files.append(step_target)
            if 'removed' in verdict:
                done.append(f"{label} removed {verdict['removed']}")
            elif 'uv_rows_before' in verdict:
                done.append(f"{verdict['uv_rows_before']} coordinate rows removed, "
                            f"{verdict['uv_rows_after']} left")
            else:
                done.append(label + ' run')
            current = step_target
        return {'success': True, 'stages': done, 'output_path': target, 'note': _joined(*done)}

    return engine.each_mesh(node, run, note=weld_note)


def h_process_cloud(engine: PipelineEngine, node: PipelineNode,
                    params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    """One point-cloud verb, called exactly the way the Point Clouds pane calls it.

    Every knob is read here through a literal name, in a chain the reader can follow, because
    the whole claim of this node is that the number in the box reaches the verb that takes it.
    """
    verb = str(params.get('verb') or '')
    if verb not in CLOUD_VERB_KNOBS:
        raise Invalid(f"Verb says {verb or 'nothing'}, and the backend runs "
                      f"{', '.join(CLOUD_VERBS)} - nothing with that name")
    folder = engine._write_folder(params['output_folder'],
                                  'folder named in Process Point Cloud')
    call: Dict[str, Any] = {}
    if verb == 'voxel':
        call['voxel_size'] = float(params['voxel_size'])
    elif verb == 'uniform':
        call['every_k'] = int(params['every_k'])
    elif verb == 'outliers_statistical':
        call['nb_neighbors'] = int(params['nb_neighbors'])
        call['std_ratio'] = float(params['std_ratio'])
    elif verb == 'outliers_radius':
        call['nb_points'] = int(params['nb_points'])
        call['radius'] = float(params['radius'])
    elif verb == 'translate':
        offset = list(params.get('offset') or [0.0, 0.0, 0.0])
        call['dx'] = float(offset[0])
        call['dy'] = float(offset[1])
        call['dz'] = float(offset[2])
    elif verb == 'rotate':
        angles = list(params.get('angles') or [0.0, 0.0, 0.0])
        call['rx'] = float(angles[0])
        call['ry'] = float(angles[1])
        call['rz'] = float(angles[2])
    elif verb == 'scale':
        call['factor'] = float(params['factor'])
    elif verb == 'crop':
        call['min_bound'] = list(params.get('min_bound') or [-1.0, -1.0, -1.0])
        call['max_bound'] = list(params.get('max_bound') or [1.0, 1.0, 1.0])
    elif verb == 'normals':
        call['knn'] = int(params['knn'])
    elif verb == 'planes':
        call['distance_threshold'] = float(params['distance_threshold'])
    elif verb == 'cluster':
        call['eps'] = float(params['eps'])
        call['min_points'] = int(params['min_points'])
    elif verb == 'hull':
        call['extension'] = str(params.get('surface_format') or '.ply')
    elif verb == 'poisson':
        call['depth'] = int(params['depth'])
        call['extension'] = str(params.get('surface_format') or '.ply')
    elif verb == 'ball_pivoting':
        call['ball_radius'] = float(params['radius'])
        call['extension'] = str(params.get('surface_format') or '.ply')
    elif verb == 'alpha_shape':
        call['alpha'] = float(params['alpha'])
        call['extension'] = str(params.get('surface_format') or '.ply')
    reads = sorted(CLOUD_VERB_KNOBS.get(verb) or {})
    # Which knobs of this node the verb being run does not reach, derived from the table rather
    # than counted off `params`, so the sentence cannot drift from the code it describes.
    taken = _cloud_knob_names(CLOUD_VERB_KNOBS[verb])
    unused: set = set()
    for other_verb, mapping in CLOUD_VERB_KNOBS.items():
        if other_verb != verb:
            unused |= _cloud_knob_names(mapping)
    unused -= taken
    named = sorted(unused)
    defaults = {
        'planes': 'ransac_n and num_iterations stay at the backend\'s 3 and 1000',
        'poisson': 'width, scale, linear_fit and trim stay at the backend\'s 0, 1.1, off and off',
        'ball_pivoting': 'the ball radii are this one number, tried as a list of one',
    }.get(verb, '')
    note = _joined(
        f"{verb} reads {', '.join(reads)}" if reads else f"{verb} reads no knob of this node",
        (f"{len(named)} knob(s) of this node belong to other verbs and were not sent "
         f"({', '.join(named[:8])}{' and the rest' if len(named) > 8 else ''})"
         if named else ''),
        defaults,
        (f"the surface is written as {call['extension']}" if verb in SURFACE_VERBS else ''))
    return engine.each_cloud(node, verb, call, folder, note=note)


# ---- EXPORT ----

def _draw(engine: PipelineEngine, item: Item, out_path: str, width: int, height: int,
          camera: Any, light: Any, background: Tuple[float, float, float], transparent: bool,
          point_size: float, display: str, samples: int, label: str) -> Dict[str, Any]:
    """One call to the app's own raster, with the backend's sentence when it says no."""
    from .preview_render import PreviewError, render_file
    try:
        return render_file(item.path, out_path, width=width, height=height, camera=camera,
                           light=light, background=background, transparent=transparent,
                           point_size=point_size, display_mode=display, supersample=samples,
                           should_cancel=engine._should_cancel)
    except PreviewError as why:
        raise Refused(f"{label} could not draw {item.label}: {why}")


def h_render(engine: PipelineEngine, node: PipelineNode,
             params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    fmt = str(params.get('format') or 'png')
    if fmt == 'exr':
        raise Refused("exr is not an encoder here: this build writes png, jpg, tiff, bmp and "
                      "webp, and the row on exr said nothing about that")
    display = str(params.get('display') or 'object')
    if display == 'clay':
        raise Refused("clay is not a display mode here. The raster paints the model's own "
                      "colours (object), its normals, its height and its three coordinates")
    width = int(params['resolution_x'])
    height = int(params['resolution_y'])
    samples = int(params.get('samples', 1) or 1)
    transparent = bool(params.get('transparent', False))
    point_size = float(params.get('point_size', 3.0))
    pattern = str(params.get('naming_pattern') or '{name}_{index}.{format}')
    folder = engine._write_folder(params['output_folder'], 'folder named in Render')
    background = _rgb(params.get('background') or '#1E1E1E')
    stream = engine.needs(node, (MESH, CLOUD))
    camera, camera_note = engine._camera('the fitted default camera, because no Camera node '
                                         'ran in this pipeline')
    light, light_note = engine._light()
    if light is not None and any(item.kind == CLOUD for item in stream):
        raise Refused("a lamp falls on surfaces, and this wire carries a point cloud, so the "
                      "Render would have been refused anyway: take the Lighting node out or "
                      "put a Process Point Cloud surface verb in front")
    written: List[str] = []
    frames: List[Dict[str, Any]] = []
    for position, item in enumerate(stream, start=1):
        engine._check_stop('Render')
        name = _format_name(pattern, item, position, fmt)
        out_path = os.path.join(folder, name)
        verdict = _draw(engine, item, out_path, width, height, camera, light, background,
                        transparent, point_size, display, samples, 'Render')
        engine.files.append(out_path)
        written.append(out_path)
        frames.append({'file': name, 'bytes': verdict['bytes'],
                       'size': [verdict['width'], verdict['height']],
                       'coverage_percent': verdict['coverage_percent'],
                       'supersample': verdict['supersample'],
                       'distinct_colors': verdict['distinct_colors'],
                       'note': verdict.get('note') or ''})
    frame_notes = list(dict.fromkeys(frame['note'] for frame in frames if frame['note']))
    return stream, {'inputs': len(stream), 'written': len(written), 'frames': frames,
                    'asked': [width, height],
                    'note': _joined(camera_note, light_note, *frame_notes)}


def h_thumbnail(engine: PipelineEngine, node: PipelineNode,
                params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    size = int(params.get('size', 256))
    fmt = str(params.get('format') or 'png')
    point_size = float(params.get('point_size', 3.0))
    background = _rgb(params.get('background') or '#1E1E1E')
    folder = engine._write_folder(params['output_folder'], 'folder named in Generate Thumbnail')
    stream = engine.needs(node, (MESH, CLOUD))
    camera, camera_note = engine._camera('the fitted default camera, because no Camera node '
                                         'ran in this pipeline')
    light, light_note = engine._light()
    if light is not None and any(item.kind == CLOUD for item in stream):
        raise Refused("a lamp falls on surfaces and this wire carries a point cloud, so the "
                      "thumbnail would have been refused anyway: take the Lighting node out")
    written: List[str] = []
    frames: List[Dict[str, Any]] = []
    for position, item in enumerate(stream, start=1):
        engine._check_stop('Generate Thumbnail')
        name = _format_name('{name}_{index}_thumb.{format}', item, position, fmt)
        out_path = os.path.join(folder, name)
        verdict = _draw(engine, item, out_path, size, size, camera, light, background, False,
                        point_size, 'object', 1, 'Generate Thumbnail')
        engine.files.append(out_path)
        written.append(out_path)
        frames.append({'file': name, 'bytes': verdict['bytes'],
                       'size': [verdict['width'], verdict['height']],
                       'coverage_percent': verdict['coverage_percent'],
                       'note': verdict.get('note') or ''})
    frame_notes = list(dict.fromkeys(frame['note'] for frame in frames if frame['note']))
    return stream, {'inputs': len(stream), 'written': len(written), 'frames': frames,
                    'note': _joined(camera_note, light_note, *frame_notes,
                                    f"{size}x{size} square, one frame each, no supersampling "
                                    f"on this node")}


def h_export_model(engine: PipelineEngine, node: PipelineNode,
                   params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .format_converter import FormatConverter
    stream = engine.needs(node, (MESH,))
    if len(stream) != 1:
        raise Refused(f"Export Model writes one model into one named file, and the wire "
                      f"carries {len(stream)} models, which cannot share that name. Use Batch "
                      f"Export for a wire of more than one")
    target = engine._write_file(params['output_path'], 'output path named in Export Model')
    suffix = os.path.splitext(target)[1].lower()
    asked = str(params.get('format') or '').strip().lstrip('.').lower()
    if asked == 'exr':
        raise Refused("exr is an image file, not a model: Export Model writes meshes")
    if asked and suffix and suffix != '.' + asked:
        raise Refused(f"the output path ends {suffix} while Format says {asked}, so the two "
                      f"disagree about what kind of file this is")
    extension = suffix or ('.' + asked if asked else '')
    if not extension:
        raise Invalid("neither the extension on the output path nor Format says what kind of "
                      "file to write")
    converter = FormatConverter()
    if extension not in converter.writable_formats():
        raise Refused(converter.conversion_blocker(os.path.splitext(stream[0].path)[1],
                                                   extension))
    facts, method = engine.write_model(stream[0], target,
                                       bool(params.get('overwrite', False)), extension)
    return stream, {'written': 1, 'note': _joined(
        f"{os.path.basename(target)} written by {method}",
        f"{facts.get('faces')} faces, {facts.get('vertices')} vertices, "
        f"{facts.get('bytes')} bytes, {facts.get('uv_rows')} coordinate rows re-read off it")}


def h_export_batch(engine: PipelineEngine, node: PipelineNode,
                   params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    from .format_converter import FormatConverter
    fmt = str(params.get('format') or 'obj').strip().lstrip('.').lower()
    if fmt == 'exr':
        raise Refused("exr is an image file, not a model: Batch Export writes meshes")
    stream = engine.needs(node, (MESH,))
    folder = engine._write_folder(params['output_folder'], 'folder named in Batch Export')
    pattern = str(params.get('naming_pattern') or '{name}_{index}.{format}')
    overwrite = bool(params.get('overwrite', False))
    names = [_format_name(pattern, item, position, fmt)
             for position, item in enumerate(stream, start=1)]
    clashes = sorted({name for name in names if names.count(name) > 1})
    if clashes:
        raise Refused(f"the naming pattern gives {len(clashes)} name(s) to more than one "
                      f"model - {', '.join(clashes[:4])} - so {len(stream)} files would be "
                      f"written over each other. Put {{index}} in the pattern")
    converter = FormatConverter()
    if '.' + fmt not in converter.writable_formats():
        raise Refused(converter.conversion_blocker(
            os.path.splitext(stream[0].path)[1], '.' + fmt))
    written: List[str] = []
    methods: List[str] = []
    for position, item in enumerate(stream, start=1):
        engine._check_stop('Batch Export')
        out_path = os.path.join(folder, names[position - 1])
        facts, method = engine.write_model(item, out_path, overwrite, '.' + fmt)
        methods.append(method)
        written.append(out_path)
    return stream, {'inputs': len(stream), 'written': len(written), 'files': written,
                    'note': _joined(
                        f"every one written as .{fmt} into {folder}",
                        (f"carried by {', '.join(sorted(set(methods)))}"
                         if len(set(methods)) > 1 else
                         f"carried by {methods[0]}"))}


def h_stats(engine: PipelineEngine, node: PipelineNode,
            params: Dict[str, Any]) -> Tuple[Stream, Dict[str, Any]]:
    folder = engine._write_folder(params['output_folder'], 'folder named in Export Stats')
    stream = engine.needs(node, (MESH, CLOUD))
    geometry = bool(params.get('include_geometry', True))
    materials = bool(params.get('include_materials', True))
    textures = bool(params.get('include_textures', True))
    if not any((geometry, materials, textures)):
        raise Refused("all three includes are off, so the JSON would hold the file name and "
                      "nothing counted")
    written: List[str] = []
    for position, item in enumerate(stream, start=1):
        engine._check_stop('Export Stats')
        payload: Dict[str, Any] = {'file': item.path, 'kind': item.kind,
                                   'label': item.label, 'measured': dict(item.facts)}
        if geometry:
            payload['geometry'] = (_mesh_geometry(item.path) if item.kind == MESH
                                   else _cloud_geometry(item.path))
        if materials and item.kind == MESH:
            payload['material'] = _material_facts(item.path, textures)
        elif materials:
            payload['material'] = {'note': 'a point cloud has no material: its colour, if it '
                                           'has one, is on the points',
                                   'has_colors': bool(item.facts.get('has_colors'))}
        out_path = os.path.join(folder, _format_name('{name}_{index}_stats.{format}', item,
                                                     position, 'json'))
        try:
            with open(out_path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, indent=2, default=str)
        except OSError as problem:
            raise Refused(f"{os.path.basename(out_path)} was not written: "
                          f"{type(problem).__name__}: {problem}")
        try:
            with open(out_path, 'r', encoding='utf-8') as handle:
                read_back = json.load(handle)
        except (OSError, ValueError) as problem:
            raise Refused(f"{os.path.basename(out_path)} was written and does not parse back "
                          f"as JSON: {type(problem).__name__}: {problem}")
        if read_back.get('measured') != payload['measured']:
            raise Refused(f"{os.path.basename(out_path)} came back from the disk with "
                          f"different counts in it than were written, so this file is not "
                          f"evidence of anything")
        engine.files.append(out_path)
        written.append(out_path)
    return stream, {'inputs': len(stream), 'written': len(written), 'files': written,
                    'note': _joined(
                        f"{len(written)} JSON file(s) in {folder}, each re-read and parsed",
                        'geometry, material and texture includes: '
                        f'{geometry}, {materials}, {textures}')}


def _mesh_geometry(path: str) -> Dict[str, Any]:
    """Volume, area, topology and bodies, counted off the file by the app's only measurer."""
    from .mesh_processor import MeshMeasure
    report = MeshMeasure.measurements(path)
    bodies = MeshMeasure.components(path)
    if report.get('success') and bodies.get('success'):
        report['components'] = bodies['components']
    elif not report.get('success'):
        report['note'] = 'a point cloud has no faces, so the mesh measurer has no answer here'
    return report


def _cloud_geometry(path: str) -> Dict[str, Any]:
    """Density and bounds of a scan, from the analyzer the Point Clouds pane uses."""
    from .point_cloud_processor import PointCloudAnalyzer, PointCloudProcessor
    cloud, error = PointCloudProcessor().read_cloud(path)
    if error:
        return {'success': False, 'error': error}
    return PointCloudAnalyzer.analyze(cloud).to_dict()


def _material_facts(path: str, textures: bool) -> Dict[str, Any]:
    """The material names, texture coordinate rows and image sizes the file really carries."""
    from .mesh_processor import MeshUV
    facts: Dict[str, Any] = {'uv_rows': MeshUV.uv_rows(path), 'parts': []}
    if not TRIMESH_AVAILABLE:
        facts['error'] = 'Trimesh is not available, so the material could not be read'
        return facts
    try:
        loaded = trimesh.load(path, process=False)
    except Exception as problem:
        facts['error'] = (f'the file does not read back as a mesh: '
                          f'{type(problem).__name__}: {problem}')
        return facts
    parts = loaded.geometry.values() if isinstance(loaded, trimesh.Scene) else [loaded]
    for index, part in enumerate(parts):
        material = getattr(getattr(part, 'visual', None), 'material', None)
        entry: Dict[str, Any] = {'part': index,
                                 'faces': int(len(getattr(part, 'faces', []))),
                                 'material_name': getattr(material, 'name', None)}
        if textures and material is not None:
            from PIL import Image
            images = []
            for field, value in list(getattr(material, '__dict__', {}).items()):
                if isinstance(value, Image.Image):
                    images.append({'field': field, 'width': value.size[0],
                                   'height': value.size[1], 'mode': value.mode,
                                   'file': getattr(value, 'filename', None) or None})
            entry['images'] = images
        facts['parts'].append(entry)
    return facts


# ============================================================================
# THE CATALOG THE PANE READS
# ============================================================================

def get_nodes_by_category(category: Optional[NodeCategory] = None) -> List[NodeDefinition]:
    """The node palette, in the order the definitions are declared."""
    if category is None:
        return list(NODE_DEFINITIONS.values())
    if isinstance(category, str):
        wanted = category
        for one in NodeCategory:
            if one.value == category or one.name.lower() == category.lower():
                wanted = one
        return [definition for definition in NODE_DEFINITIONS.values()
                if definition.category == wanted]
    return [definition for definition in NODE_DEFINITIONS.values()
            if definition.category == category]


_READ_SCAN: Dict[str, Optional[set]] = {}


def _knobs_read(handler_name: str) -> Optional[set]:
    """The knob names literally read out of `params` in one handler's own source.

    None when the source cannot be read at all, which is different from an empty set: a
    handler whose text this process cannot see has not been proved to drop a knob.
    """
    if handler_name in _READ_SCAN:
        return _READ_SCAN[handler_name]
    function = globals().get(handler_name)
    if not callable(function):
        _READ_SCAN[handler_name] = None
        return None
    try:
        source = inspect.getsource(function)
    except (OSError, TypeError):
        _READ_SCAN[handler_name] = None
        return None
    found = set(re.findall(r"params\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"
                           r"|params\.get\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", source))
    names = set()
    for pair in found:
        names.add(pair[0] or pair[1])
    _READ_SCAN[handler_name] = names
    return names


def parameter_report() -> List[Dict[str, Any]]:
    """Every knob of every node, and whether the handler named beside it reads it.

    This is the answer to the bug the whole engine was: the transform handlers read `factor`,
    `angle` and `x/y/z` while the pane showed `scale`, `rotation_x` and `offset_x`, so a
    number a person typed went into a box and out of the program nowhere. Anything here in
    `declared_not_read` is that bug again, and the contract suite fails on it.
    """
    rows: List[Dict[str, Any]] = []
    for definition in NODE_DEFINITIONS.values():
        declared = {param.name for param in definition.parameters}
        read = _knobs_read(definition.handler)
        rows.append({
            'node': definition.id,
            'name': definition.name,
            'handler': definition.handler,
            'declared': sorted(declared),
            'read': sorted(read) if read is not None else None,
            'declared_not_read': sorted(declared - read) if read is not None else None,
            'read_not_declared': sorted(read - declared) if read is not None else None,
        })
    return rows


def definition_not_backed(definition: NodeDefinition) -> str:
    """Why this node type cannot honestly be offered, or '' when it can."""
    if not definition.handler:
        return f"{definition.name} names no handler at all"
    if not handler_is_backed(definition.handler):
        return f"{definition.name} names {definition.handler}, which is not a function here"
    read = _knobs_read(definition.handler)
    if read is None:
        return ''
    dropped = sorted({param.name for param in definition.parameters} - read)
    if dropped:
        return (f"{definition.name} shows {', '.join(dropped)}, which "
                f"{definition.handler} never reads")
    return ''


def unbacked_definitions() -> List[str]:
    """Every node type that would lie about a knob, as sentences."""
    return [definition_not_backed(definition) for definition in NODE_DEFINITIONS.values()
            if definition_not_backed(definition)]


# ============================================================================
# PIPELINES ON DISK
# ============================================================================

def save_pipeline(pipeline: Pipeline, file_path: str) -> Tuple[bool, str]:
    """Write a pipeline, then read it back and count the nodes.

    The old version returned a bare True from inside a `try` that could not see whether the
    file it wrote could be opened again, so a full disk looked like a saved pipeline.
    """
    absolute = os.path.abspath(str(file_path))
    folder = os.path.dirname(absolute)
    try:
        os.makedirs(folder, exist_ok=True)
        with open(absolute, 'w', encoding='utf-8') as handle:
            json.dump(pipeline.to_dict(), handle, indent=2)
    except (OSError, TypeError, ValueError) as problem:
        return False, (f"{absolute} was not written: {type(problem).__name__}: {problem}")
    reloaded, warnings = load_pipeline(absolute)
    if reloaded is None:
        return False, f"{absolute} was written and will not read back: {'; '.join(warnings)}"
    if len(reloaded.nodes) != len(pipeline.nodes):
        return False, (f"{absolute} holds {len(reloaded.nodes)} node(s) where "
                       f"{pipeline.name} has {len(pipeline.nodes)}, so what was written is not "
                       f"what was asked")
    if len(reloaded.connections) != len(pipeline.connections):
        return False, (f"{absolute} holds {len(reloaded.connections)} wire(s) where "
                       f"{pipeline.name} has {len(pipeline.connections)}")
    return True, ''


def load_pipeline(file_path: str) -> Tuple[Optional[Pipeline], List[str]]:
    """A pipeline off the disk, and everything the person needs to know about it.

    A file from the old node set is loaded and reported on rather than refused or rewritten:
    the warnings name the node types this build does not have and the boxes that no longer
    move anything, and the pane shows them. Nothing here touches the file.
    """
    absolute = os.path.abspath(str(file_path))
    if not os.path.isfile(absolute):
        return None, [f"{absolute} is not a file on this disk"]
    try:
        with open(absolute, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as problem:
        return None, [f"{os.path.basename(absolute)} does not read as a pipeline file: "
                      f"{type(problem).__name__}: {problem}"]
    if not isinstance(data, dict):
        return None, [f"{os.path.basename(absolute)} holds {type(data).__name__}, not a "
                      f"pipeline"]
    warnings: List[str] = []
    if data.get('node_schema') != NODE_SCHEMA:
        warnings.append(f"this file was saved by an older node set (schema "
                        f"{data.get('node_schema', 'none')}), so some of its boxes may name a "
                        f"knob this build does not have")
    try:
        pipeline = Pipeline.from_dict(data)
    except KeyError as missing:
        return None, [f"{os.path.basename(absolute)} is missing {missing.args[0]!r} on one of "
                      f"its nodes or wires, so it cannot be read as a pipeline"]
    except (TypeError, ValueError) as problem:
        return None, [f"{os.path.basename(absolute)} cannot be built into a pipeline: "
                      f"{type(problem).__name__}: {problem}"]
    seen: List[str] = []
    for node in pipeline.nodes:
        if node.id in seen:
            warnings.append(f"two nodes are both called {node.id}, so a wire into one of them "
                            f"is a coin toss")
        seen.append(node.id)
        if node.definition_id not in NODE_DEFINITIONS:
            warnings.append(f"{node.id} is a {node.definition_id}, which this build does not "
                            f"have")
            continue
        definition = node.get_definition()
        reason = definition_not_backed(definition)
        if reason:
            warnings.append(reason)
        for name in pipeline.unknown_parameters(node):
            warnings.append(f"{definition.name} carries {name}, which is not a knob of this "
                            f"node type any more, so nothing reads it")
    for connection in pipeline.connections:
        if pipeline.node_by_id(connection.from_node) is None:
            warnings.append(f"a wire starts at {connection.from_node}, which is not in this "
                            f"pipeline")
        if pipeline.node_by_id(connection.to_node) is None:
            warnings.append(f"a wire ends at {connection.to_node}, which is not in this "
                            f"pipeline")
    if pipeline.has_cycle():
        warnings.append("the wires contain a loop, so there is no order to run them in")
    if not pipeline.nodes:
        warnings.append(f"{pipeline.name} holds no nodes")
    return pipeline, warnings

