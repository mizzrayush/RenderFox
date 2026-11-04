"""
Pipeline engine for visual node-based 3D model processing workflows.
"""

import json
import uuid
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
import threading
import os
import logging
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

try:
    import trimesh
    import numpy as np
except ImportError:
    trimesh = None
    np = None

try:
    import open3d as o3d
except ImportError:
    o3d = None


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
    """Parameter definition for a node."""
    name: str
    type: ParameterType
    required: bool = True
    default: Any = None
    description: str = ""
    options: List[Any] = field(default_factory=list)  # For enum types
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
    color: str  # Hex color for visual representation
    icon: str = "●"


# ============================================================================
# NODE DEFINITIONS DATABASE (JSON-like structure)
# ============================================================================

NODE_DEFINITIONS: Dict[str, NodeDefinition] = {
    # ========== INPUT NODES (BLUE) ==========
    "input.load_model": NodeDefinition(
        id="input.load_model",
        name="Load Model",
        category=NodeCategory.INPUT,
        description="Load a 3D model file",
        color="#4A90E2",
        icon="models",
        parameters=[
            NodeParameter("file_path", ParameterType.FILE, required=True, description="Path to model file"),
            NodeParameter("auto_scale", ParameterType.BOOL, required=False, default=True, description="Automatically scale model"),
            NodeParameter("center_origin", ParameterType.BOOL, required=False, default=False, description="Center at origin"),
        ]
    ),
    
    "input.load_batch": NodeDefinition(
        id="input.load_batch",
        name="Load Batch",
        category=NodeCategory.INPUT,
        description="Load multiple models from folder",
        color="#4A90E2",
        icon="folder",
        parameters=[
            NodeParameter("folder_path", ParameterType.FOLDER, required=True, description="Folder containing models"),
            NodeParameter("filter", ParameterType.STRING, required=False, default="*.fbx,*.obj,*.gltf", description="File filter patterns"),
            NodeParameter("recursive", ParameterType.BOOL, required=False, default=False, description="Search subfolders"),
        ]
    ),
    
    "input.point_cloud": NodeDefinition(
        id="input.point_cloud",
        name="Load Point Cloud",
        category=NodeCategory.INPUT,
        description="Load point cloud data",
        color="#4A90E2",
        icon="point_clouds",
        parameters=[
            NodeParameter("file_path", ParameterType.FILE, required=True, description="Path to point cloud file"),
            NodeParameter("point_size", ParameterType.FLOAT, required=False, default=1.0, min_value=0.1, max_value=10.0, description="Display point size"),
            NodeParameter("color_mode", ParameterType.ENUM, required=False, default="rgb", options=["rgb", "intensity", "height"], description="Color display mode"),
        ]
    ),
    
    "input.camera": NodeDefinition(
        id="input.camera",
        name="Camera Setup",
        category=NodeCategory.INPUT,
        description="Configure camera position and settings",
        color="#4A90E2",
        icon="camera",
        parameters=[
            NodeParameter("position", ParameterType.VECTOR3, required=True, default=[0, 5, 10], description="Camera position"),
            NodeParameter("target", ParameterType.VECTOR3, required=False, default=[0, 0, 0], description="Look at target"),
            NodeParameter("fov", ParameterType.FLOAT, required=False, default=45.0, min_value=1.0, max_value=120.0, description="Field of view"),
            NodeParameter("type", ParameterType.ENUM, required=False, default="perspective", options=["perspective", "orthographic"], description="Camera type"),
        ]
    ),
    
    "input.lighting": NodeDefinition(
        id="input.lighting",
        name="Lighting Setup",
        category=NodeCategory.INPUT,
        description="Configure scene lighting",
        color="#4A90E2",
        icon="lighting",
        parameters=[
            NodeParameter("light_type", ParameterType.ENUM, required=True, default="point", options=["point", "directional", "spot", "hdri"], description="Type of light"),
            NodeParameter("intensity", ParameterType.FLOAT, required=False, default=1.0, min_value=0.0, max_value=100.0, description="Light intensity"),
            NodeParameter("color", ParameterType.COLOR, required=False, default="#FFFFFF", description="Light color"),
            NodeParameter("position", ParameterType.VECTOR3, required=False, default=[5, 10, 5], description="Light position"),
        ]
    ),
    
    # ========== TRANSFORM NODES (GREEN) ==========
    "transform.scale": NodeDefinition(
        id="transform.scale",
        name="Scale",
        category=NodeCategory.TRANSFORM,
        description="Scale model uniformly or per-axis",
        color="#50C878",
        icon="scale",
        parameters=[
            NodeParameter("uniform", ParameterType.BOOL, required=False, default=True, description="Uniform scaling"),
            NodeParameter("scale", ParameterType.FLOAT, required=True, default=1.0, min_value=0.001, max_value=1000.0, description="Uniform scale factor"),
            NodeParameter("scale_x", ParameterType.FLOAT, required=False, default=1.0, description="X-axis scale"),
            NodeParameter("scale_y", ParameterType.FLOAT, required=False, default=1.0, description="Y-axis scale"),
            NodeParameter("scale_z", ParameterType.FLOAT, required=False, default=1.0, description="Z-axis scale"),
        ]
    ),
    
    "transform.rotate": NodeDefinition(
        id="transform.rotate",
        name="Rotate",
        category=NodeCategory.TRANSFORM,
        description="Rotate model around axes",
        color="#50C878",
        icon="rotate",
        parameters=[
            NodeParameter("rotation_x", ParameterType.FLOAT, required=False, default=0.0, min_value=-360.0, max_value=360.0, description="X-axis rotation (degrees)"),
            NodeParameter("rotation_y", ParameterType.FLOAT, required=False, default=0.0, min_value=-360.0, max_value=360.0, description="Y-axis rotation (degrees)"),
            NodeParameter("rotation_z", ParameterType.FLOAT, required=False, default=0.0, min_value=-360.0, max_value=360.0, description="Z-axis rotation (degrees)"),
            NodeParameter("pivot", ParameterType.VECTOR3, required=False, default=[0, 0, 0], description="Pivot point"),
        ]
    ),
    
    "transform.translate": NodeDefinition(
        id="transform.translate",
        name="Translate",
        category=NodeCategory.TRANSFORM,
        description="Move model in 3D space",
        color="#50C878",
        icon="translate",
        parameters=[
            NodeParameter("offset_x", ParameterType.FLOAT, required=False, default=0.0, description="X-axis offset"),
            NodeParameter("offset_y", ParameterType.FLOAT, required=False, default=0.0, description="Y-axis offset"),
            NodeParameter("offset_z", ParameterType.FLOAT, required=False, default=0.0, description="Z-axis offset"),
        ]
    ),
    
    "transform.decimate": NodeDefinition(
        id="transform.decimate",
        name="Decimate",
        category=NodeCategory.TRANSFORM,
        description="Reduce polygon count",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("method", ParameterType.ENUM, required=True, default="ratio", options=["ratio", "target_count", "error_threshold"], description="Decimation method"),
            NodeParameter("ratio", ParameterType.FLOAT, required=False, default=0.5, min_value=0.01, max_value=1.0, description="Reduction ratio (0.5 = 50%)"),
            NodeParameter("target_count", ParameterType.INT, required=False, default=10000, min_value=100, description="Target triangle count"),
            NodeParameter("preserve_uv", ParameterType.BOOL, required=False, default=True, description="Preserve UV coordinates"),
            NodeParameter("preserve_normal", ParameterType.BOOL, required=False, default=True, description="Preserve normals"),
        ]
    ),
    
    "transform.simplify": NodeDefinition(
        id="transform.simplify",
        name="Simplify",
        category=NodeCategory.TRANSFORM,
        description="Simplify mesh topology",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("aggressiveness", ParameterType.FLOAT, required=False, default=7.0, min_value=1.0, max_value=10.0, description="Simplification aggressiveness"),
            NodeParameter("preserve_border", ParameterType.BOOL, required=False, default=True, description="Preserve mesh borders"),
            NodeParameter("max_iterations", ParameterType.INT, required=False, default=100, min_value=1, max_value=1000, description="Maximum iterations"),
        ]
    ),
    
    "transform.smooth": NodeDefinition(
        id="transform.smooth",
        name="Smooth",
        category=NodeCategory.TRANSFORM,
        description="Smooth mesh surface",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("iterations", ParameterType.INT, required=False, default=5, min_value=1, max_value=100, description="Smoothing iterations"),
            NodeParameter("factor", ParameterType.FLOAT, required=False, default=0.5, min_value=0.0, max_value=1.0, description="Smoothing factor"),
            NodeParameter("preserve_volume", ParameterType.BOOL, required=False, default=True, description="Preserve mesh volume"),
        ]
    ),
    
    "transform.remesh": NodeDefinition(
        id="transform.remesh",
        name="Remesh",
        category=NodeCategory.TRANSFORM,
        description="Remesh with uniform topology",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("mode", ParameterType.ENUM, required=True, default="voxel", options=["voxel", "quad", "sharp"], description="Remesh mode"),
            NodeParameter("voxel_size", ParameterType.FLOAT, required=False, default=0.1, min_value=0.001, max_value=10.0, description="Voxel size"),
            NodeParameter("adaptivity", ParameterType.FLOAT, required=False, default=0.0, min_value=0.0, max_value=1.0, description="Mesh adaptivity"),
        ]
    ),
    
    "transform.subdivide": NodeDefinition(
        id="transform.subdivide",
        name="Subdivide",
        category=NodeCategory.TRANSFORM,
        description="Subdivide mesh for higher detail",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("levels", ParameterType.INT, required=True, default=1, min_value=1, max_value=6, description="Subdivision levels"),
            NodeParameter("method", ParameterType.ENUM, required=False, default="catmull-clark", options=["catmull-clark", "linear", "simple"], description="Subdivision method"),
        ]
    ),
    
    "transform.center": NodeDefinition(
        id="transform.center",
        name="Center",
        category=NodeCategory.TRANSFORM,
        description="Center model at origin",
        color="#50C878",
        icon="reset_view",
        parameters=[
            NodeParameter("mode", ParameterType.ENUM, required=False, default="bounds", options=["bounds", "mass", "geometry"], description="Centering mode"),
            NodeParameter("axis", ParameterType.ENUM, required=False, default="xyz", options=["xyz", "xy", "xz", "yz", "x", "y", "z"], description="Axes to center"),
        ]
    ),
    
    "transform.align": NodeDefinition(
        id="transform.align",
        name="Align",
        category=NodeCategory.TRANSFORM,
        description="Align model to reference",
        color="#50C878",
        icon="focus",
        parameters=[
            NodeParameter("direction", ParameterType.ENUM, required=True, default="up", options=["up", "down", "left", "right", "forward", "back"], description="Alignment direction"),
            NodeParameter("axis", ParameterType.ENUM, required=True, default="y", options=["x", "y", "z"], description="Axis to align"),
            NodeParameter("offset", ParameterType.FLOAT, required=False, default=0.0, description="Offset from alignment"),
        ]
    ),
    
    "transform.mirror": NodeDefinition(
        id="transform.mirror",
        name="Mirror",
        category=NodeCategory.TRANSFORM,
        description="Mirror geometry across axis",
        color="#50C878",
        icon="copy",
        parameters=[
            NodeParameter("axis", ParameterType.ENUM, required=True, default="x", options=["x", "y", "z"], description="Mirror axis"),
            NodeParameter("merge", ParameterType.BOOL, required=False, default=True, description="Merge with original"),
            NodeParameter("merge_threshold", ParameterType.FLOAT, required=False, default=0.001, min_value=0.0, max_value=1.0, description="Merge distance threshold"),
        ]
    ),
    
    "transform.unwrap_uv": NodeDefinition(
        id="transform.unwrap_uv",
        name="Unwrap UV",
        category=NodeCategory.TRANSFORM,
        description="Generate UV coordinates",
        color="#50C878",
        icon="grid",
        parameters=[
            NodeParameter("method", ParameterType.ENUM, required=True, default="smart", options=["smart", "cube", "sphere", "cylinder"], description="UV unwrap method"),
            NodeParameter("margin", ParameterType.FLOAT, required=False, default=0.001, min_value=0.0, max_value=0.5, description="Island margin"),
            NodeParameter("angle_limit", ParameterType.FLOAT, required=False, default=66.0, min_value=1.0, max_value=89.0, description="Angle limit for seams"),
        ]
    ),
    
    "transform.bake_texture": NodeDefinition(
        id="transform.bake_texture",
        name="Bake Texture",
        category=NodeCategory.TRANSFORM,
        description="Bake textures to UV map",
        color="#50C878",
        icon="material",
        parameters=[
            NodeParameter("type", ParameterType.ENUM, required=True, default="combined", options=["combined", "diffuse", "normal", "ao", "roughness", "metallic"], description="Bake type"),
            NodeParameter("resolution", ParameterType.INT, required=True, default=2048, min_value=256, max_value=8192, description="Texture resolution"),
            NodeParameter("samples", ParameterType.INT, required=False, default=128, min_value=1, max_value=4096, description="Sampling count"),
            NodeParameter("margin", ParameterType.INT, required=False, default=16, min_value=0, max_value=64, description="Margin pixels"),
        ]
    ),
    
    "transform.lod_generate": NodeDefinition(
        id="transform.lod_generate",
        name="Generate LOD",
        category=NodeCategory.TRANSFORM,
        description="Generate Level of Detail variants",
        color="#50C878",
        icon="mesh_tools",
        parameters=[
            NodeParameter("lod_count", ParameterType.INT, required=True, default=3, min_value=1, max_value=10, description="Number of LOD levels"),
            NodeParameter("reduction_factor", ParameterType.FLOAT, required=False, default=0.5, min_value=0.1, max_value=0.9, description="Reduction per level"),
            NodeParameter("screen_size", ParameterType.BOOL, required=False, default=True, description="Use screen-size based LOD"),
        ]
    ),
    
    "transform.optimize": NodeDefinition(
        id="transform.optimize",
        name="Optimize",
        category=NodeCategory.TRANSFORM,
        description="Optimize mesh for performance",
        color="#50C878",
        icon="sparkles",
        parameters=[
            NodeParameter("remove_doubles", ParameterType.BOOL, required=False, default=True, description="Remove duplicate vertices"),
            NodeParameter("merge_threshold", ParameterType.FLOAT, required=False, default=0.0001, min_value=0.0, max_value=1.0, description="Merge distance"),
            NodeParameter("recalc_normals", ParameterType.BOOL, required=False, default=True, description="Recalculate normals"),
            NodeParameter("remove_loose", ParameterType.BOOL, required=False, default=True, description="Remove loose geometry"),
        ]
    ),
    
    # ========== EXPORT NODES (RED) ==========
    "export.render": NodeDefinition(
        id="export.render",
        name="Render",
        category=NodeCategory.EXPORT,
        description="Render final output",
        color="#E74C3C",
        icon="render",
        parameters=[
            NodeParameter("output_path", ParameterType.FILE, required=True, description="Output image path"),
            NodeParameter("resolution_x", ParameterType.INT, required=True, default=1920, min_value=128, max_value=8192, description="Width"),
            NodeParameter("resolution_y", ParameterType.INT, required=True, default=1080, min_value=128, max_value=8192, description="Height"),
            NodeParameter("format", ParameterType.ENUM, required=False, default="png", options=["png", "jpg", "exr", "tiff"], description="Image format"),
            NodeParameter("samples", ParameterType.INT, required=False, default=128, min_value=1, max_value=10000, description="Render samples"),
            NodeParameter("transparent", ParameterType.BOOL, required=False, default=False, description="Transparent background"),
        ]
    ),
    
    "export.model": NodeDefinition(
        id="export.model",
        name="Export Model",
        category=NodeCategory.EXPORT,
        description="Export processed model",
        color="#E74C3C",
        icon="export",
        parameters=[
            NodeParameter("output_path", ParameterType.FILE, required=True, description="Output file path"),
            NodeParameter("format", ParameterType.ENUM, required=True, default="fbx", options=["fbx", "obj", "gltf", "glb", "stl", "ply", "dae"], description="Export format"),
            NodeParameter("apply_transforms", ParameterType.BOOL, required=False, default=True, description="Apply transformations"),
            NodeParameter("export_materials", ParameterType.BOOL, required=False, default=True, description="Export materials"),
            NodeParameter("export_textures", ParameterType.BOOL, required=False, default=True, description="Export textures"),
            NodeParameter("embed_textures", ParameterType.BOOL, required=False, default=False, description="Embed textures in file"),
        ]
    ),
    
    "export.batch": NodeDefinition(
        id="export.batch",
        name="Batch Export",
        category=NodeCategory.EXPORT,
        description="Export multiple outputs",
        color="#E74C3C",
        icon="batch_render",
        parameters=[
            NodeParameter("output_folder", ParameterType.FOLDER, required=True, description="Output folder"),
            NodeParameter("format", ParameterType.ENUM, required=True, default="fbx", options=["fbx", "obj", "gltf", "glb", "stl"], description="Export format"),
            NodeParameter("naming_pattern", ParameterType.STRING, required=False, default="{name}_{index}", description="File naming pattern"),
            NodeParameter("overwrite", ParameterType.BOOL, required=False, default=False, description="Overwrite existing files"),
        ]
    ),
    
    "export.thumbnail": NodeDefinition(
        id="export.thumbnail",
        name="Generate Thumbnail",
        category=NodeCategory.EXPORT,
        description="Create thumbnail image",
        color="#E74C3C",
        icon="camera",
        parameters=[
            NodeParameter("output_path", ParameterType.FILE, required=True, description="Thumbnail output path"),
            NodeParameter("size", ParameterType.INT, required=False, default=256, min_value=64, max_value=2048, description="Thumbnail size (square)"),
            NodeParameter("background", ParameterType.COLOR, required=False, default="#1E1E1E", description="Background color"),
        ]
    ),
    
    "export.stats": NodeDefinition(
        id="export.stats",
        name="Export Stats",
        category=NodeCategory.EXPORT,
        description="Export model statistics",
        color="#E74C3C",
        icon="chart",
        parameters=[
            NodeParameter("output_path", ParameterType.FILE, required=True, description="Stats output path (JSON)"),
            NodeParameter("include_geometry", ParameterType.BOOL, required=False, default=True, description="Include geometry stats"),
            NodeParameter("include_materials", ParameterType.BOOL, required=False, default=True, description="Include material stats"),
            NodeParameter("include_textures", ParameterType.BOOL, required=False, default=True, description="Include texture stats"),
        ]
    ),
}


# ============================================================================
# PIPELINE NODES
# ============================================================================

@dataclass
class PipelineNode:
    """Instance of a node in a pipeline."""
    id: str
    definition_id: str
    position: tuple[float, float]
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def get_definition(self) -> Optional[NodeDefinition]:
        """Get the node definition."""
        return NODE_DEFINITIONS.get(self.definition_id)


@dataclass
class PipelineConnection:
    """Connection between two nodes."""
    from_node: str  # node id
    to_node: str    # node id
    

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
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "nodes": [
                {
                    "id": n.id,
                    "definition_id": n.definition_id,
                    "position": n.position,
                    "parameters": n.parameters
                }
                for n in self.nodes
            ],
            "connections": [
                {"from": c.from_node, "to": c.to_node}
                for c in self.connections
            ],
            "created_at": self.created_at,
            "modified_at": self.modified_at
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'Pipeline':
        """Create from dictionary."""
        pipeline = Pipeline(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data.get("created_at", time.time()),
            modified_at=data.get("modified_at", time.time())
        )
        
        for n in data.get("nodes", []):
            node = PipelineNode(
                id=n["id"],
                definition_id=n["definition_id"],
                position=tuple(n["position"]),
                parameters=n.get("parameters", {})
            )
            pipeline.nodes.append(node)
        
        for c in data.get("connections", []):
            conn = PipelineConnection(
                from_node=c["from"],
                to_node=c["to"]
            )
            pipeline.connections.append(conn)
        
        return pipeline


# ============================================================================
# PIPELINE ENGINE
# ============================================================================

class PipelineEngine(QObject):
    """Engine for executing pipelines using job manager."""
    
    # Signals
    progress_updated = pyqtSignal(str, float)  # node_id, progress
    node_started = pyqtSignal(str)  # node_id
    node_completed = pyqtSignal(str)  # node_id
    node_failed = pyqtSignal(str, str)  # node_id, error
    pipeline_completed = pyqtSignal()
    pipeline_failed = pyqtSignal(str)  # error
    log_message = pyqtSignal(str)  # message
    
    def __init__(self, job_manager=None):
        super().__init__()
        self.job_manager = job_manager
        self._current_pipeline: Optional[Pipeline] = None
        self._is_running = False
        self._node_data: Dict[str, Any] = {}  # Store data passing between nodes
        self._node_locks: Dict[str, threading.Lock] = {} # Lock for thread safety if needed
    
    def add_connection(self, connection: PipelineConnection) -> bool:
        """
        Add a connection to the pipeline.
        
        Args:
            connection: The connection to add
            
        Returns:
            bool: True if connection was added, False if invalid
        """
        if not self._current_pipeline:
            # If no pipeline is running, we might be editing a static one?
            # But PipelineEngine is for execution. 
            # The error comes from PipelineEditorTab calling engine.add_connection.
            # Wait, PipelineEditorTab likely uses PipelineEngine to manage the data?
            # Or maybe it should be adding to the Pipeline object directly?
            # The error says: 'PipelineEngine' object has no attribute 'add_connection'
            # So we must add it here.
            pass
            
        # Actually, looking at the error context, the editor probably holds a reference to the engine
        # and tries to update the pipeline through it.
        # But PipelineEngine seems to be an execution engine, not a data manager.
        # However, to fix the AttributeError, we must add the method.
        # If self._current_pipeline is None, we can't add to it.
        # But maybe the editor sets the pipeline on the engine?
        
        # Let's assume the editor has set a pipeline or we need to handle it.
        # If _current_pipeline is None, we return False.
        if not self._current_pipeline:
            return False
            
        # Check for duplicates
        for conn in self._current_pipeline.connections:
            if (conn.from_node == connection.from_node and 
                conn.to_node == connection.to_node):
                return False
                
        # Check for cycles (simple check)
        if connection.from_node == connection.to_node:
            return False
            
        self._current_pipeline.connections.append(connection)
        return True

    
    def execute_pipeline(self, pipeline: Pipeline) -> bool:
        """Execute a pipeline."""
        if self._is_running:
            self.log_message.emit("Pipeline already running")
            return False
        
        self._current_pipeline = pipeline
        self._is_running = True
        self._node_data.clear()
        
        try:
            self.log_message.emit(f"Starting pipeline: {pipeline.name}")
            
            # Validate pipeline
            if not self._validate_pipeline(pipeline):
                raise Exception("Pipeline validation failed")
            
            # Get execution order (topological sort)
            execution_order = self._get_execution_order(pipeline)
            
            if not execution_order:
                raise Exception("Cannot determine execution order (circular dependency?)")
            
            self.log_message.emit(f"Execution order: {len(execution_order)} nodes")
            
            # Execute nodes in order
            for i, node_id in enumerate(execution_order):
                node = next((n for n in pipeline.nodes if n.id == node_id), None)
                if not node:
                    continue
                
                definition = node.get_definition()
                if not definition:
                    raise Exception(f"Unknown node type: {node.definition_id}")
                
                # Update progress
                progress = (i / len(execution_order)) * 100
                self.progress_updated.emit(node_id, progress)
                
                # Execute node
                self.log_message.emit(f"Executing: {definition.name}")
                self.node_started.emit(node_id)
                
                success = self._execute_node(node, definition)
                
                if success:
                    self.node_completed.emit(node_id)
                    self.log_message.emit(f"Completed: {definition.name}")
                else:
                    raise Exception(f"Node execution failed: {definition.name}")
            
            self.log_message.emit("Pipeline completed successfully.")
            self.pipeline_completed.emit()
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.log_message.emit(f"Pipeline failed: {error_msg}")
            self.pipeline_failed.emit(error_msg)
            return False
        
        finally:
            self._is_running = False
            self._current_pipeline = None
    
    def _validate_pipeline(self, pipeline: Pipeline) -> bool:
        """Validate pipeline structure."""
        if not pipeline.nodes:
            self.log_message.emit("Pipeline has no nodes")
            return False
        
        # Check for required parameters
        for node in pipeline.nodes:
            definition = node.get_definition()
            if not definition:
                self.log_message.emit(f"Unknown node type: {node.definition_id}")
                return False
            
            # Check required parameters
            for param in definition.parameters:
                if param.required and param.name not in node.parameters:
                    self.log_message.emit(f"Missing required parameter '{param.name}' in {definition.name}")
                    return False
        
        # Check for cycles
        if self._has_cycles(pipeline):
            self.log_message.emit("Pipeline contains cycles (circular dependencies)")
            return False
            
        return True
        
    def _has_cycles(self, pipeline: Pipeline) -> bool:
        """Check for cycles in the pipeline graph."""
        # Build adjacency list
        adj = {node.id: [] for node in pipeline.nodes}
        for conn in pipeline.connections:
            if conn.from_node in adj:
                adj[conn.from_node].append(conn.to_node)
        
        visited = set()
        recursion_stack = set()
        
        def dfs(node_id):
            visited.add(node_id)
            recursion_stack.add(node_id)
            
            for neighbor in adj.get(node_id, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in recursion_stack:
                    return True
            
            recursion_stack.remove(node_id)
            return False
            
        for node in pipeline.nodes:
            if node.id not in visited:
                if dfs(node.id):
                    return True
                    
        return False
    
    def _get_execution_order(self, pipeline: Pipeline) -> List[str]:
        """Get topological sort of nodes for execution order."""
        # Build dependency graph (Adjacency list and In-degree)
        adj = {node.id: [] for node in pipeline.nodes}
        in_degree = {node.id: 0 for node in pipeline.nodes}
        
        for conn in pipeline.connections:
            if conn.from_node in adj and conn.to_node in in_degree:
                adj[conn.from_node].append(conn.to_node)
                in_degree[conn.to_node] += 1
        
        # Queue for nodes with 0 in-degree
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            
            for neighbor in adj[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # Check if all nodes were processed (no cycles)
        if len(result) != len(pipeline.nodes):
            return []
        
        return result
    
    def _execute_node(self, node: PipelineNode, definition: NodeDefinition) -> bool:
        """Execute a single node."""
        try:
            # Dispatch based on category
            if definition.category == NodeCategory.INPUT:
                return self._execute_input_node(node, definition)
            elif definition.category == NodeCategory.EXPORT:
                return self._execute_export_node(node, definition)
            elif definition.category == NodeCategory.TRANSFORM:
                # Placeholder for Phase 16
                return self._execute_transform_node(node, definition)
            else:
                # Fallback for unknown categories
                self.log_message.emit(f"Node category {definition.category} not fully implemented yet")
                return True
            
        except Exception as e:
            self.node_failed.emit(node.id, str(e))
            return False

    def _execute_input_node(self, node: PipelineNode, definition: NodeDefinition) -> bool:
        """Execute input node."""
        if definition.id == "input.load_model":
            file_path = node.parameters.get("file_path")
            if not file_path or not os.path.exists(file_path):
                raise FileNotFoundError(f"Model file not found: {file_path}")
            
            if trimesh is None:
                raise ImportError("Trimesh library not available")
            
            mesh = trimesh.load(file_path)
            self._node_data[node.id] = {"geometry": mesh, "type": "mesh"}
            self.log_message.emit(f"Loaded model: {os.path.basename(file_path)}")
            return True
            
        elif definition.id == "input.point_cloud":
            file_path = node.parameters.get("file_path")
            if not file_path or not os.path.exists(file_path):
                raise FileNotFoundError(f"Point cloud file not found: {file_path}")
            
            if o3d is None:
                raise ImportError("Open3D library not available")
            
            pcd = o3d.io.read_point_cloud(file_path)
            self._node_data[node.id] = {"geometry": pcd, "type": "point_cloud"}
            self.log_message.emit(f"Loaded point cloud: {os.path.basename(file_path)}")
            return True
            
        return True

    def _execute_export_node(self, node: PipelineNode, definition: NodeDefinition) -> bool:
        """Execute export node."""
        # Get input geometry
        inputs = self._get_node_inputs(node.id)
        if not inputs:
            raise ValueError("No input data for export node")
        
        # Use first valid input
        input_data = inputs[0]
        geometry = input_data.get("geometry")
        
        if definition.id == "export.model":
            output_path = node.parameters.get("output_path")
            if not output_path:
                raise ValueError("Output path not specified")
            
            # Create directory if needed
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            if isinstance(geometry, trimesh.Trimesh) or isinstance(geometry, trimesh.Scene):
                geometry.export(output_path)
                self.log_message.emit(f"Exported model to: {output_path}")
                return True
            elif o3d and isinstance(geometry, o3d.geometry.PointCloud):
                o3d.io.write_point_cloud(output_path, geometry)
                self.log_message.emit(f"Exported point cloud to: {output_path}")
                return True
            else:
                raise TypeError(f"Unsupported geometry type for export: {type(geometry)}")
                
        elif definition.id == "export.render":
            # Placeholder for actual rendering - for now just save a screenshot if possible or log
            self.log_message.emit("Rendering not fully implemented, skipping actual render")
            return True
            
        return True

    def _execute_transform_node(self, node: PipelineNode, definition: NodeDefinition) -> bool:
        """Execute transform node."""
        # Get input geometry
        inputs = self._get_node_inputs(node.id)
        if not inputs:
            raise ValueError("No input data for transform node")
        
        # Use first valid input (copy to avoid modifying original if needed, but for linear pipeline we usually modify)
        # For efficiency in this linear flow, we might modify in place or copy. 
        # Trimesh objects are mutable.
        input_data = inputs[0]
        geometry = input_data.get("geometry")
        geo_type = input_data.get("type")
        
        # Create a copy to avoid side effects on upstream nodes if branching
        import copy
        geometry = geometry.copy()
        
        if definition.id == "transform.scale":
            factor = float(node.parameters.get("factor", 1.0))
            if geo_type == "mesh":
                geometry.apply_scale(factor)
            elif geo_type == "point_cloud":
                geometry.scale(factor, center=geometry.get_center())
                
        elif definition.id == "transform.rotate":
            angle_deg = float(node.parameters.get("angle", 0.0))
            axis_str = node.parameters.get("axis", "y").lower()
            
            axis = [0, 1, 0]
            if axis_str == "x": axis = [1, 0, 0]
            elif axis_str == "z": axis = [0, 0, 1]
            
            angle_rad = np.radians(angle_deg)
            
            if geo_type == "mesh":
                matrix = trimesh.transformations.rotation_matrix(angle_rad, axis)
                geometry.apply_transform(matrix)
            elif geo_type == "point_cloud":
                # Open3D rotation
                R = geometry.get_rotation_matrix_from_axis_angle(np.array(axis) * angle_rad)
                geometry.rotate(R, center=geometry.get_center())

        elif definition.id == "transform.translate":
            x = float(node.parameters.get("x", 0.0))
            y = float(node.parameters.get("y", 0.0))
            z = float(node.parameters.get("z", 0.0))
            translation = [x, y, z]
            
            if geo_type == "mesh":
                geometry.apply_translation(translation)
            elif geo_type == "point_cloud":
                geometry.translate(translation)

        elif definition.id == "transform.decimate":
            # Mesh simplification
            if geo_type != "mesh":
                self.log_message.emit(f"Decimate only supports meshes, got {geo_type}")
            else:
                ratio = float(node.parameters.get("ratio", 0.5))
                target_faces = int(len(geometry.faces) * ratio)
                geometry = geometry.simplify_quadratic_decimation(target_faces)
                self.log_message.emit(f"Decimated mesh to {len(geometry.faces)} faces")

        elif definition.id == "transform.bake_texture":
            # Texture Baking
            if geo_type != "mesh":
                self.log_message.emit(f"Texture baking only supports meshes, got {geo_type}")
            else:
                try:
                    from .texture_baker import TextureBaker
                    baker = TextureBaker()
                    
                    # Create temporary output directory
                    import tempfile
                    output_dir = os.path.join(tempfile.gettempdir(), "renderfox_bake_" + str(uuid.uuid4()))
                    os.makedirs(output_dir, exist_ok=True)
                    
                    # Save current mesh to temp file as high poly
                    high_poly_path = os.path.join(output_dir, "high_poly.obj")
                    geometry.export(high_poly_path)
                    
                    # Simplified workflow: Bake AO/Normals from self to self (if high detail)
                    low_poly_path = high_poly_path 
                    
                    resolution = int(node.parameters.get("resolution", 2048))
                    bake_type = node.parameters.get("type", "combined")
                    
                    bake_normals = bake_type in ["normal", "combined"]
                    bake_diffuse = bake_type in ["diffuse", "combined"]
                    bake_ao = bake_type in ["ao", "combined"]
                    
                    self.log_message.emit(f"Baking textures ({bake_type}) at {resolution}x{resolution}...")
                    
                    # Run bake
                    baker.bake(high_poly_path, low_poly_path, output_dir, resolution, 
                              bake_normals, bake_diffuse, bake_ao)
                              
                    self.log_message.emit(f"Baking complete. Maps saved to {output_dir}")
                    
                except ImportError:
                    self.log_message.emit("TextureBaker module not found")
                except Exception as e:
                    self.log_message.emit(f"Baking failed: {str(e)}")

        elif definition.id == "transform.lod_generate":
            # LOD Generation
            if geo_type != "mesh":
                self.log_message.emit(f"LOD generation only supports meshes, got {geo_type}")
            else:
                try:
                    from .lod_generator import LODGenerator
                    generator = LODGenerator()
                    
                    count = int(node.parameters.get("lod_count", 3))
                    reduction = float(node.parameters.get("reduction_factor", 0.5))
                    
                    target_faces = int(len(geometry.faces) * reduction)
                    geometry = geometry.simplify_quadratic_decimation(target_faces)
                    self.log_message.emit(f"Generated LOD (reduced to {len(geometry.faces)} faces)")
                    
                except ImportError:
                    self.log_message.emit("LODGenerator module not found")

        elif definition.id == "transform.optimize":
            # Mesh Optimization
            if geo_type != "mesh":
                self.log_message.emit(f"Optimization only supports meshes, got {geo_type}")
            else:
                try:
                    from .mesh_processor import MeshProcessor
                    processor = MeshProcessor()
                    
                    if node.parameters.get("remove_doubles", True):
                        geometry.merge_vertices()
                    
                    if node.parameters.get("recalc_normals", True):
                        geometry.fix_normals()
                        
                    if node.parameters.get("remove_loose", True):
                        pass
                        
                    self.log_message.emit("Mesh optimized successfully")
                    
                except ImportError:
                    self.log_message.emit("MeshProcessor module not found")
                    
        else:
            self.log_message.emit(f"Transform node '{definition.name}' ({definition.id}) is not yet implemented. Passing data through.")

        # Store result
        self._node_data[node.id] = {"geometry": geometry, "type": geo_type}
        return True

    def _get_node_inputs(self, node_id: str) -> List[Any]:
        """Get data from input nodes."""
        inputs = []
        if not self._current_pipeline:
            return inputs
            
        for conn in self._current_pipeline.connections:
            if conn.to_node == node_id:
                if conn.from_node in self._node_data:
                    inputs.append(self._node_data[conn.from_node])
        return inputs
    
    def stop(self):
        """Stop pipeline execution."""
        self._is_running = False
        self.log_message.emit("Pipeline stopped by user")
    
    @property
    def is_running(self) -> bool:
        """Check if pipeline is running."""
        return self._is_running


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_nodes_by_category(category: NodeCategory) -> List[NodeDefinition]:
    """Get all node definitions for a category."""
    return [node for node in NODE_DEFINITIONS.values() if node.category == category]


def save_pipeline(pipeline: Pipeline, file_path: str) -> bool:
    """Save pipeline to JSON file."""
    try:
        with open(file_path, 'w') as f:
            json.dump(pipeline.to_dict(), f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving pipeline: {e}")
        return False


def load_pipeline(file_path: str) -> Optional[Pipeline]:
    """Load pipeline from JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return Pipeline.from_dict(data)
    except Exception as e:
        logger.error(f"Error loading pipeline: {e}")
        return None
