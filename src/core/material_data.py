"""
Material Data Model for RenderFox.
Defines the structure for Materials, Textures, and Shader Nodes.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from enum import Enum

class ShaderNodeType(Enum):
    OUTPUT = "Output"
    BSDF_PRINCIPLED = "Principled BSDF"
    TEXTURE_IMAGE = "Image Texture"
    MIX_SHADER = "Mix Shader"
    MATH = "Math"
    COLOR_RAMP = "Color Ramp"
    NORMAL_MAP = "Normal Map"

@dataclass
class NodeSocket:
    """A socket (input or output) on a node."""
    name: str
    type: str  # "float", "vec3", "shader"
    value: Any = None  # Default value if not connected
    is_output: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class ShaderNode:
    """A node in the shader graph."""
    type: ShaderNodeType
    name: str
    position: List[float] = field(default_factory=lambda: [0.0, 0.0])
    inputs: List[NodeSocket] = field(default_factory=list)
    outputs: List[NodeSocket] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)  # Internal node data (e.g. file path)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def create(cls, node_type: ShaderNodeType, name: str = None):
        """Factory to create nodes with default sockets."""
        if name is None:
            name = node_type.value
            
        node = cls(type=node_type, name=name)
        
        # Setup default sockets based on type
        if node_type == ShaderNodeType.OUTPUT:
            node.inputs.append(NodeSocket("Surface", "shader"))
            
        elif node_type == ShaderNodeType.BSDF_PRINCIPLED:
            node.inputs.append(NodeSocket("Base Color", "vec3", [0.8, 0.8, 0.8]))
            node.inputs.append(NodeSocket("Metallic", "float", 0.0))
            node.inputs.append(NodeSocket("Roughness", "float", 0.5))
            node.inputs.append(NodeSocket("IOR", "float", 1.45))
            node.inputs.append(NodeSocket("Specular", "float", 0.5))
            node.inputs.append(NodeSocket("Transmission", "float", 0.0))
            node.inputs.append(NodeSocket("Emission", "vec3", [0.0, 0.0, 0.0]))
            node.inputs.append(NodeSocket("Emission Strength", "float", 1.0))
            node.inputs.append(NodeSocket("Alpha", "float", 1.0))
            node.inputs.append(NodeSocket("Normal", "vec3", [0.0, 0.0, 1.0]))
            node.outputs.append(NodeSocket("BSDF", "shader", is_output=True))
            
        elif node_type == ShaderNodeType.TEXTURE_IMAGE:
            node.inputs.append(NodeSocket("Vector", "vec3"))
            node.outputs.append(NodeSocket("Color", "vec3", is_output=True))
            node.outputs.append(NodeSocket("Alpha", "float", is_output=True))
            node.properties["image_path"] = ""
            
        elif node_type == ShaderNodeType.NORMAL_MAP:
            node.inputs.append(NodeSocket("Strength", "float", 1.0))
            node.inputs.append(NodeSocket("Color", "vec3", [0.5, 0.5, 1.0]))
            node.outputs.append(NodeSocket("Normal", "vec3", is_output=True))
            
        return node

@dataclass
class NodeLink:
    """A connection between two sockets."""
    from_node_id: str
    from_socket_id: str
    to_node_id: str
    to_socket_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class Material:
    """A material defined by a graph of nodes."""
    name: str
    nodes: List[ShaderNode] = field(default_factory=list)
    links: List[NodeLink] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    def to_json(self) -> str:
        """Serialize material to JSON."""
        # Custom encoder needed for Enum
        return json.dumps(asdict(self), default=str, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str):
        """Deserialize material from JSON."""
        data = json.loads(json_str)
        # Reconstruct logic would go here (parsing Enums, etc.)
        # For now, simplistic return
        return cls(**data)
        
    @classmethod
    def create_default(cls, name="New Material"):
        """Create a default material with Output and Principled BSDF."""
        mat = cls(name=name)
        
        output = ShaderNode.create(ShaderNodeType.OUTPUT)
        output.position = [300.0, 0.0]
        
        bsdf = ShaderNode.create(ShaderNodeType.BSDF_PRINCIPLED)
        bsdf.position = [0.0, 0.0]
        
        mat.nodes = [output, bsdf]
        
        # Link BSDF to Output
        link = NodeLink(
            from_node_id=bsdf.id,
            from_socket_id=bsdf.outputs[0].id,
            to_node_id=output.id,
            to_socket_id=output.inputs[0].id
        )
        mat.links.append(link)
        
        return mat
