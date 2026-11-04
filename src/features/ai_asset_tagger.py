"""
AI Asset Tagger - Automatic 3D Model Analysis and Smart Tagging

This module provides AI-powered analysis of 3D models to automatically generate
intelligent tags based on geometry, complexity, and characteristics.

Features:
- CLIP-based visual understanding of 3D models (NEW!)
- Automatic category detection (furniture, character, vehicle, architecture)
- Complexity analysis (low-poly, high-poly, game-ready)
- Quality detection (watertight, textured, production-ready)
- Symmetry detection
- Natural language search support
- Batch processing with progress tracking

Author: RenderFox Team
Date: October 2025
"""

import os
import sys

# Isolate PyTorch backend for Transformers to prevent TensorFlow/Keras interference
os.environ['USE_TF'] = '0'
os.environ['USE_TORCH'] = '1'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

from PyQt6.QtCore import QSettings
import trimesh
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable
import logging
from PIL import Image
import io

# CLIP Model imports (NEW!)
try:
    from transformers import CLIPProcessor, CLIPModel
    import torch
    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False
    logging.warning("CLIP not available. Install with: pip install transformers torch")

# Open3D import for fallback rendering
try:
    import open3d as o3d
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False
    logging.warning("Open3D not available. Install with: pip install open3d")

logger = logging.getLogger(__name__)


class AIAssetTagger:
    """
    Automatically analyze 3D models and generate smart tags.
    
    This is a revolutionary feature that no other 3D asset management tool has.
    It uses geometric analysis and heuristics to classify models without requiring
    any machine learning libraries.
    """
    
    def __init__(self, library_manager=None, use_clip=True):
        """
        Initialize AI Asset Tagger.
        
        Args:
            library_manager: Optional reference to LibraryManager for database updates
            use_clip: Whether to use CLIP model for AI tagging (requires GPU/good CPU)
        """
        self.library_manager = library_manager
        self.tag_rules = self._load_tag_rules()
        self.category_keywords = self._load_category_keywords()
        
        # Initialize CLIP model (NEW!)
        self.use_clip = use_clip and CLIP_AVAILABLE
        self.clip_model = None
        self.clip_processor = None
        self.device = None
        
        if self.use_clip:
            self._initialize_clip_model()

    
    def _initialize_clip_model(self):
        """Initialize CLIP model for AI-powered tagging."""
        try:
            logger.info("🤖 Loading CLIP model (this may take a minute)...")
            
            # Use GPU if available, else CPU
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
            logger.info(f"Using device: {self.device}")
            
            # Determine base application directory
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(os.path.abspath(sys.executable))
                meipass_dir = getattr(sys, '_MEIPASS', app_dir)
            else:
                app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                meipass_dir = app_dir

            # Check for local model path in settings
            settings = QSettings("RenderFox", "RenderFox")
            custom_path = settings.value("Advanced/local_ai_model_path", "")
            
            # Search candidate paths for offline OpenAI CLIP model
            candidate_paths = [
                custom_path,
                os.path.join(app_dir, "OPENai Clip"),
                os.path.join(meipass_dir, "OPENai Clip"),
                os.path.join(os.getcwd(), "OPENai Clip"),
                os.path.join(app_dir, "ai_models", "clip"),
                os.path.join(app_dir, "resources", "OPENai Clip"),
            ]
            
            local_path = None
            for p in candidate_paths:
                if p and os.path.exists(p) and os.path.exists(os.path.join(p, "config.json")):
                    local_path = p
                    break
            
            model_name = "openai/clip-vit-base-patch32"
            
            if local_path:
                logger.info(f"📂 Loading local CLIP model from: {local_path}")
                try:
                    # Try loading from local path
                    self.clip_model = CLIPModel.from_pretrained(local_path).to(self.device)
                    self.clip_processor = CLIPProcessor.from_pretrained(local_path)
                    logger.info("✅ Local CLIP model loaded successfully!")
                except Exception as local_e:
                    logger.error(f"Failed to load local model: {local_e}")
                    logger.info("⬇️ Falling back to downloading from Hugging Face...")
                    self.clip_model = CLIPModel.from_pretrained(model_name).to(self.device)
                    self.clip_processor = CLIPProcessor.from_pretrained(model_name)
            else:
                # Download from Hub
                logger.info(f"⬇️ Downloading CLIP model: {model_name}")
                self.clip_model = CLIPModel.from_pretrained(model_name).to(self.device)
                self.clip_processor = CLIPProcessor.from_pretrained(model_name)
            
            # Set to evaluation mode
            self.clip_model.eval()
            
            logger.info("✅ CLIP model loaded successfully!")
            
        except Exception as e:
            logger.error(f"Failed to load CLIP model: {e}")
            self.use_clip = False
            logger.warning("⚠️ Falling back to geometric analysis only")
    
    def _render_model_preview(self, mesh, resolution=(224, 224)):
        """
        Render a preview image of the 3D model for CLIP analysis.
        
        Args:
            mesh: Trimesh object
            resolution: Image resolution (width, height)
            
        Returns:
            PIL Image object
        """
        # Try Trimesh (pyglet) rendering first
        try:
            # Render the mesh to an image
            if isinstance(mesh, trimesh.Scene):
                scene = mesh
            else:
                scene = mesh.scene()
            
            # Set up camera to view the entire model
            scene.camera.fov = [60, 60]
            
            # Render to PNG bytes
            png_data = scene.save_image(resolution=resolution, visible=True)
            
            # Convert to PIL Image
            image = Image.open(io.BytesIO(png_data))
            
            return image
            
        except Exception as e:
            logger.warning(f"Trimesh rendering failed (likely missing pyglet): {e}")
            
            # Fallback to Open3D if available
            if OPEN3D_AVAILABLE:
                logger.info("🔄 Attempting fallback rendering with Open3D...")
                return self._render_with_open3d(mesh, resolution)
            
            return None

    def _render_with_open3d(self, mesh, resolution=(224, 224)):
        """
        Render mesh using Open3D as fallback.
        """
        try:
            # Convert Trimesh to Open3D mesh
            o3d_mesh = o3d.geometry.TriangleMesh()
            
            # Handle Scene objects by concatenating geometry first (already done in analyze_model via _as_trimesh)
            # But if we got here with a Scene object that wasn't converted (unlikely due to _as_trimesh usage), handle it.
            if isinstance(mesh, trimesh.Scene):
                # We need a single mesh for simple Open3D rendering here
                # Re-use _as_trimesh logic or assume it's already a Trimesh if passed from analyze_model
                # For safety, just use the first geometry or merge
                dump = mesh.dump(concatenate=True)
                if isinstance(dump, list):
                    # If multiple, just take first for preview
                    vertices = dump[0].vertices
                    faces = dump[0].faces
                else:
                    vertices = dump.vertices
                    faces = dump.faces
            else:
                vertices = mesh.vertices
                faces = mesh.faces
            
            o3d_mesh.vertices = o3d.utility.Vector3dVector(vertices)
            o3d_mesh.triangles = o3d.utility.Vector3iVector(faces)
            o3d_mesh.compute_vertex_normals()
            o3d_mesh.paint_uniform_color([0.7, 0.7, 0.7])  # Grey color
            
            # Create visualizer
            vis = o3d.visualization.Visualizer()
            vis.create_window(visible=False, width=resolution[0], height=resolution[1])
            vis.add_geometry(o3d_mesh)
            
            # Update view
            vis.poll_events()
            vis.update_renderer()
            
            # Capture image
            image_float = vis.capture_screen_float_buffer()
            image_np = (np.asarray(image_float) * 255).astype(np.uint8)
            
            # Convert to PIL
            image = Image.fromarray(image_np)
            
            vis.destroy_window()
            return image
            
        except Exception as e:
            logger.error(f"Open3D fallback rendering failed: {e}")
            return None
    
    def _clip_classify_category(self, image: Image.Image) -> Dict[str, float]:
        """
        Use CLIP to classify model category from rendered image.
        
        Args:
            image: PIL Image of rendered model
            
        Returns:
            Dictionary of category -> confidence score
        """
        if not self.use_clip or image is None:
            return {}
        
        try:
            # Category prompts for CLIP
            categories = [
                "a 3D model of furniture",
                "a 3D model of a character or person",
                "a 3D model of a vehicle or car",
                "a 3D model of architecture or building",
                "a 3D model of a weapon",
                "a 3D model of an animal or creature",
                "a 3D model of electronics or technology",
                "a 3D model of nature or organic object",
                "a 3D model of a prop or decorative item"
            ]
            
            # Process image and text
            inputs = self.clip_processor(
                text=categories,
                images=image,
                return_tensors="pt",
                padding=True
            )
            
            # Move to device
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # Get predictions
            with torch.no_grad():
                outputs = self.clip_model(**inputs)
                logits_per_image = outputs.logits_per_image
                probs = logits_per_image.softmax(dim=1)[0]
            
            # Map to simplified categories
            category_map = {
                0: "furniture",
                1: "character",
                2: "vehicle",
                3: "architecture",
                4: "weapon",
                5: "creature",
                6: "electronics",
                7: "nature",
                8: "prop"
            }
            
            # Create results dictionary
            results = {}
            for idx, prob in enumerate(probs.cpu().numpy()):
                category = category_map.get(idx, "unknown")
                results[category] = float(prob)
            
            return results
            
        except Exception as e:
            logger.error(f"CLIP classification failed: {e}")
            return {}
    
    def _clip_generate_descriptive_tags(self, image: Image.Image) -> List[str]:
        """
        Use CLIP to generate descriptive tags from rendered image.
        
        Args:
            image: PIL Image of rendered model
            
        Returns:
            List of descriptive tags
        """
        if not self.use_clip or image is None:
            return []
        
        try:
            # Descriptive prompts
            descriptions = [
                "organic shape",
                "geometric shape",
                "realistic style",
                "stylized design",
                "simple design",
                "complex design",
                "modern style",
                "medieval style",
                "futuristic design",
                "natural object",
                "artificial object",
                "mechanical parts",
                "wooden material",
                "metal material",
                "colorful",
                "monochrome"
            ]
            
            # Process
            inputs = self.clip_processor(
                text=descriptions,
                images=image,
                return_tensors="pt",
                padding=True
            )
            
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.clip_model(**inputs)
                probs = outputs.logits_per_image.softmax(dim=1)[0]
            
            # Get tags with confidence > 0.2
            tags = []
            for idx, prob in enumerate(probs.cpu().numpy()):
                if prob > 0.2:  # Threshold
                    tag = descriptions[idx].replace(" ", "-")
                    tags.append(tag)
            
            return tags
            
        except Exception as e:
            logger.error(f"CLIP tag generation failed: {e}")
            return []

    def _as_trimesh(self, obj):
        """
        Convert a trimesh object (Scene or Trimesh) to a single Trimesh object.
        """
        if isinstance(obj, trimesh.Trimesh):
            return obj
        if isinstance(obj, trimesh.Scene):
            try:
                # Concatenate all geometries in the scene
                geoms = []
                for g in obj.geometry.values():
                    if isinstance(g, trimesh.Trimesh):
                        geoms.append(g)
                
                if geoms:
                    return trimesh.util.concatenate(geoms)
            except Exception as e:
                logger.warning(f"Failed to convert Scene to Trimesh: {e}")
        return None

    def analyze_model(self, model_path: str) -> Dict[str, any]:
        """
        Analyze a 3D model and extract features for tagging.
        
        Args:
            model_path: Path to 3D model file
            
        Returns:
            Dictionary containing:
                - polygon_count: Number of faces
                - vertex_count: Number of vertices
                - bounds: Bounding box [min, max]
                - volume: Model volume (if watertight)
                - is_watertight: Boolean
                - has_textures: Boolean
                - symmetry: "symmetrical" or "asymmetric"
                - category: Detected category
                - complexity: Complexity level
                - tags: List of generated tags
                - confidence: Confidence scores for tags
                - ai_powered: Whether CLIP AI was used
                - ai_category: AI-detected category (if available)
                - ai_descriptive_tags: AI-generated descriptive tags (if available)
        """
        try:
            logger.info(f"Analyzing model: {model_path}")
            loaded_obj = trimesh.load(model_path)
            mesh = self._as_trimesh(loaded_obj)
            
            if mesh is None:
                raise ValueError(f"Could not load valid geometry from {model_path}")
            
            # Basic geometric analysis
            analysis = {
                'polygon_count': len(mesh.faces),
                'vertex_count': len(mesh.vertices),
                'bounds': mesh.bounds.tolist() if hasattr(mesh.bounds, 'tolist') else mesh.bounds,
                'volume': float(mesh.volume) if getattr(mesh, 'is_volume', False) else 0.0,
                'is_watertight': bool(mesh.is_watertight),
                'has_textures': self._detect_textures(mesh),
                'has_materials': self._detect_materials(mesh),
                'symmetry': self._detect_symmetry(mesh),
                'complexity': self._calculate_complexity(mesh),
                'aspect_ratio': self._calculate_aspect_ratio(mesh),
                'bounding_box_type': self._classify_bounding_box(mesh),
                'tags': [],
                'confidence': {},
                'ai_powered': self.use_clip
            }
            
            # AI-powered analysis using CLIP (NEW!)
            if self.use_clip:
                logger.info("🤖 Running AI analysis with CLIP...")
                
                # Render model preview for CLIP
                # Note: _render_model_preview handles Scene objects internally if needed, 
                # but we pass the single mesh here for consistency unless we want full scene rendering.
                # For now, passing the mesh is safer as _render_model_preview expects a mesh or scene.
                # If we passed the original loaded_obj (Scene), it might render better materials.
                # Let's try to use the original object for rendering if it was a Scene, else the mesh.
                render_obj = loaded_obj if isinstance(loaded_obj, trimesh.Scene) else mesh
                preview_image = self._render_model_preview(render_obj)
                
                if preview_image:
                    # Get AI category classification
                    ai_categories = self._clip_classify_category(preview_image)
                    
                    # Get best category from AI
                    if ai_categories:
                        best_ai_category = max(ai_categories.items(), key=lambda x: x[1])
                        analysis['ai_category'] = best_ai_category[0]
                        analysis['ai_category_confidence'] = best_ai_category[1]
                        analysis['ai_category_scores'] = ai_categories
                        
                        # Use AI category if confidence > 0.5, else use geometric
                        if best_ai_category[1] > 0.5:
                            analysis['category'] = best_ai_category[0]
                            logger.info(f"✨ AI detected category: {best_ai_category[0]} ({best_ai_category[1]:.2%} confidence)")
                        else:
                            # Fallback to geometric analysis
                            analysis['category'] = self._classify_category(mesh)
                            logger.info(f"📐 Using geometric category (AI confidence too low): {analysis['category']}")
                    else:
                        # No AI results, use geometric
                        analysis['category'] = self._classify_category(mesh)
                    
                    # Get descriptive tags from AI
                    ai_tags = self._clip_generate_descriptive_tags(preview_image)
                    analysis['ai_descriptive_tags'] = ai_tags
                    logger.info(f"✨ AI generated {len(ai_tags)} descriptive tags")
                else:
                    # Rendering failed, fallback to geometric category
                    analysis['category'] = self._classify_category(mesh)
                    logger.warning("Model rendering failed, using geometric analysis only")
            else:
                # Pure geometric analysis (CLIP not available)
                analysis['category'] = self._classify_category(mesh)
            
            # Advanced analysis
            analysis['quality_metrics'] = self._analyze_quality(mesh)
            analysis['topology_info'] = self._analyze_topology(mesh)
            
            # Generate tags based on analysis (combines AI + geometric)
            analysis['tags'] = self._generate_tags(analysis)
            analysis['confidence'] = self._calculate_confidence(analysis)
            
            logger.info(f"✅ Analysis complete: {len(analysis['tags'])} tags generated")
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing {model_path}: {e}")
            return {'error': str(e), 'tags': [], 'model_path': model_path}
    
    def _detect_textures(self, mesh) -> bool:
        """Check if model has UV coordinates."""
        if hasattr(mesh.visual, 'uv'):
            return mesh.visual.uv is not None and len(mesh.visual.uv) > 0
        return False
    
    def _detect_materials(self, mesh) -> bool:
        """Check if model has materials."""
        if hasattr(mesh.visual, 'material'):
            return mesh.visual.material is not None
        return False
    
    def _detect_symmetry(self, mesh) -> str:
        """
        Detect if model is symmetrical along X, Y, or Z axis.
        
        Returns:
            "x-symmetrical", "y-symmetrical", "z-symmetrical", or "asymmetric"
        """
        vertices = mesh.vertices
        
        # Check X-axis symmetry (most common for characters, furniture)
        left_side = vertices[vertices[:, 0] < -0.01]
        right_side = vertices[vertices[:, 0] > 0.01]
        
        if len(left_side) > 10 and len(right_side) > 10:
            ratio = len(left_side) / len(right_side)
            if 0.9 < ratio < 1.1:  # Within 10% tolerance
                return "x-symmetrical"
        
        # Check Y-axis symmetry (common for vehicles viewed from top)
        front = vertices[vertices[:, 1] < -0.01]
        back = vertices[vertices[:, 1] > 0.01]
        
        if len(front) > 10 and len(back) > 10:
            ratio = len(front) / len(back)
            if 0.9 < ratio < 1.1:
                return "y-symmetrical"
        
        return "asymmetric"
    
    def _classify_category(self, mesh) -> str:
        """
        Classify model into category based on geometric features.
        
        Uses heuristic rules based on bounding box proportions and topology.
        """
        bounds = mesh.bounds
        dimensions = bounds[1] - bounds[0]  # [width, depth, height]
        
        width, depth, height = dimensions
        max_dim = max(dimensions)
        
        # Avoid division by zero
        if max_dim < 0.001:
            return "prop"
        
        # Normalize dimensions
        w_ratio = width / max_dim
        d_ratio = depth / max_dim
        h_ratio = height / max_dim
        
        # Character detection (tall and narrow)
        if h_ratio > 0.8 and w_ratio < 0.4 and d_ratio < 0.4:
            return "character"
        
        # Vehicle detection (wide, elongated, low)
        if h_ratio < 0.3 and (w_ratio > 0.6 or d_ratio > 0.6):
            if d_ratio > w_ratio * 1.5 or w_ratio > d_ratio * 1.5:
                return "vehicle"
        
        # Floor/Ground plane (very flat)
        if h_ratio < 0.1 and w_ratio > 0.5 and d_ratio > 0.5:
            return "floor"
        
        # Wall (tall and thin)
        if h_ratio > 0.6 and (w_ratio < 0.2 or d_ratio < 0.2):
            return "wall"
        
        # Furniture (roughly cubic, moderate proportions)
        if 0.3 < h_ratio < 0.8 and w_ratio > 0.3 and d_ratio > 0.3:
            return "furniture"
        
        # Building/Architecture (large and tall)
        if h_ratio > 0.5 and w_ratio > 0.5 and d_ratio > 0.5:
            poly_density = len(mesh.faces) / mesh.volume if mesh.volume > 0 else 0
            if poly_density < 100:  # Low poly density suggests large structure
                return "architecture"
        
        # Default
        return "prop"
    
    def _calculate_complexity(self, mesh) -> str:
        """Determine model complexity based on polygon count."""
        face_count = len(mesh.faces)
        
        if face_count < 500:
            return "ultra-low-poly"
        elif face_count < 2000:
            return "low-poly"
        elif face_count < 10000:
            return "medium-poly"
        elif face_count < 50000:
            return "high-poly"
        elif face_count < 200000:
            return "ultra-high-poly"
        else:
            return "extreme-poly"
    
    def _calculate_aspect_ratio(self, mesh) -> Dict[str, float]:
        """Calculate aspect ratios of bounding box."""
        bounds = mesh.bounds
        dimensions = bounds[1] - bounds[0]
        width, depth, height = dimensions
        
        return {
            'width_to_height': width / height if height > 0.001 else 0,
            'depth_to_height': depth / height if height > 0.001 else 0,
            'width_to_depth': width / depth if depth > 0.001 else 0
        }
    
    def _classify_bounding_box(self, mesh) -> str:
        """Classify the shape of the bounding box."""
        bounds = mesh.bounds
        dimensions = bounds[1] - bounds[0]
        width, depth, height = dimensions
        
        max_dim = max(dimensions)
        if max_dim < 0.001:
            return "point"
        
        w = width / max_dim
        d = depth / max_dim
        h = height / max_dim
        
        tolerance = 0.2
        
        # Check for cubic shape
        if abs(w - d) < tolerance and abs(d - h) < tolerance:
            return "cubic"
        
        # Check for flat shapes
        if h < 0.15:
            return "flat"
        
        # Check for elongated shapes
        if w > 0.7 and d < 0.3:
            return "elongated-x"
        if d > 0.7 and w < 0.3:
            return "elongated-z"
        
        # Check for tall shapes
        if h > 0.7 and w < 0.4 and d < 0.4:
            return "tall"
        
        return "irregular"
    
    def _analyze_quality(self, mesh) -> Dict[str, any]:
        """Analyze mesh quality metrics."""
        quality = {
            'is_watertight': mesh.is_watertight,
            'has_degenerate_faces': False,
            'has_duplicate_faces': False,
            'triangle_quality': 'unknown'
        }
        
        try:
            # Check for degenerate faces (very small area)
            if hasattr(mesh, 'area_faces'):
                areas = mesh.area_faces
                degenerate_count = np.sum(areas < 1e-10)
                quality['has_degenerate_faces'] = degenerate_count > 0
                quality['degenerate_face_count'] = int(degenerate_count)
            
            # Estimate triangle quality
            if len(mesh.faces) > 0:
                # Simple heuristic: check vertex distribution
                vertex_density = len(mesh.vertices) / len(mesh.faces)
                if vertex_density > 2.5:
                    quality['triangle_quality'] = 'poor'  # Too many vertices for faces
                elif 1.5 < vertex_density < 2.5:
                    quality['triangle_quality'] = 'good'
                else:
                    quality['triangle_quality'] = 'excellent'
        
        except Exception as e:
            logger.warning(f"Quality analysis failed: {e}")
        
        return quality
    
    def _analyze_topology(self, mesh) -> Dict[str, any]:
        """Analyze mesh topology."""
        topology = {
            'euler_number': 0,
            'genus': 0,
            'is_single_body': True
        }
        
        try:
            if hasattr(mesh, 'euler_number'):
                topology['euler_number'] = mesh.euler_number
            
            # Estimate genus (number of holes) using Euler characteristic
            # For closed surface: V - E + F = 2 - 2g (g = genus)
            if mesh.is_watertight:
                V = len(mesh.vertices)
                F = len(mesh.faces)
                E = len(mesh.edges) if hasattr(mesh, 'edges') else int(1.5 * F)
                euler = V - E + F
                genus = (2 - euler) // 2
                topology['genus'] = max(0, genus)
        
        except Exception as e:
            logger.warning(f"Topology analysis failed: {e}")
        
        return topology
    
    def _generate_tags(self, analysis: Dict) -> List[str]:
        """
        Generate smart tags based on analysis results.
        
        This is the core "AI" functionality - uses rules and heuristics
        to generate meaningful tags without ML.
        """
        tags = set()
        
        # Complexity tags
        tags.add(analysis['complexity'])
        
        # Category tags
        category = analysis['category']
        tags.add(category)
        
        # Add related category tags
        if category in self.category_keywords:
            tags.update(self.category_keywords[category])
        
        # Geometry quality tags
        if analysis['is_watertight']:
            tags.add("watertight")
            tags.add("closed-mesh")
        else:
            tags.add("non-manifold")
            tags.add("open-mesh")
        
        # Texture tags
        if analysis['has_textures']:
            tags.add("textured")
            tags.add("uv-mapped")
        else:
            tags.add("untextured")
            tags.add("needs-uvs")
        
        # Material tags
        if analysis['has_materials']:
            tags.add("has-materials")
        
        # Symmetry tags
        tags.add(analysis['symmetry'])
        
        # Production readiness tags
        poly_count = analysis['polygon_count']
        
        if poly_count < 5000:
            tags.add("mobile-friendly")
            tags.add("vr-ready")
        
        if poly_count < 10000 and analysis['is_watertight']:
            tags.add("game-ready")
        
        if poly_count < 50000 and analysis['is_watertight'] and analysis['has_textures']:
            tags.add("production-ready")
        
        # Platform-specific tags
        if poly_count < 2000:
            tags.add("mobile-game")
            tags.add("ar-ready")
        
        if poly_count < 100000:
            tags.add("real-time")
            tags.add("unity-ready")
            tags.add("unreal-ready")
        
        # Bounding box shape tags
        bbox_type = analysis['bounding_box_type']
        if bbox_type == "flat":
            tags.add("flat-object")
        elif bbox_type == "tall":
            tags.add("vertical-object")
        elif bbox_type == "cubic":
            tags.add("cubic-object")
        
        # Quality tags based on metrics
        quality = analysis.get('quality_metrics', {})
        if quality.get('triangle_quality') == 'excellent':
            tags.add("high-quality-mesh")
        elif quality.get('triangle_quality') == 'poor':
            tags.add("needs-optimization")
        
        if quality.get('has_degenerate_faces'):
            tags.add("needs-cleanup")
        
        # Topology tags
        topology = analysis.get('topology_info', {})
        if topology.get('genus', 0) > 0:
            tags.add("has-holes")
        
        return sorted(list(tags))
    
    def _calculate_confidence(self, analysis: Dict) -> Dict[str, float]:
        """
        Calculate confidence scores for generated tags.
        
        Returns confidence (0-1) for each tag based on analysis certainty.
        """
        confidence = {}
        
        # High confidence tags (direct measurements)
        confidence[analysis['complexity']] = 1.0
        confidence['polygon-count'] = 1.0
        
        # Medium confidence (geometric heuristics)
        confidence[analysis['category']] = 0.7
        
        # Lower confidence for inferred tags
        if analysis['polygon_count'] < 5000:
            confidence['game-ready'] = 0.8
        
        if analysis['is_watertight']:
            confidence['production-ready'] = 0.9
        
        return confidence
    
    def batch_tag_models(self, model_paths: List[str], 
                         progress_callback: Optional[Callable] = None) -> Dict[str, Dict]:
        """
        Batch analyze and tag multiple models.
        
        Args:
            model_paths: List of model file paths
            progress_callback: Optional callback(current, total, filename)
            
        Returns:
            Dictionary mapping model_path -> analysis results
        """
        results = {}
        total = len(model_paths)
        
        logger.info(f"Starting batch tagging of {total} models")
        
        for i, model_path in enumerate(model_paths):
            try:
                analysis = self.analyze_model(model_path)
                results[model_path] = analysis
                
                # Update progress
                if progress_callback:
                    progress_callback(i + 1, total, Path(model_path).name)
                
            except Exception as e:
                logger.error(f"Failed to analyze {model_path}: {e}")
                results[model_path] = {'error': str(e), 'tags': []}
        
        logger.info(f"Batch tagging complete: {len(results)} models processed")
        return results
    
    def search_by_natural_language(self, query: str, all_models: List[Dict]) -> List[Dict]:
        """
        Search models using natural language queries.
        
        Examples:
            - "low poly wooden furniture"
            - "game ready characters under 10k polygons"
            - "models with more than 5000 faces"
            - "high detail models over 20000 vertices"
        
        Args:
            query: Natural language search query
            all_models: List of model dictionaries with 'tags' field
            
        Returns:
            Filtered list of matching models
        """
        import re
        query_lower = query.lower()
        results = []
        
        # Parse numeric constraints
        min_val = 0
        max_val = float('inf')
        target_attr = 'faces'  # Default to faces
        
        # Check if user specifically asked for vertices or edges
        if any(w in query_lower for w in ['vertices', 'verts', 'vertex']):
            target_attr = 'vertices'
        elif any(w in query_lower for w in ['edges', 'edge']):
            target_attr = 'edges'
        
        # Regex for "more than X" or "over X"
        more_than_match = re.search(r'(?:more than|over|above|>)[\s]*(\d+(?:k)?)', query_lower)
        if more_than_match:
            val_str = more_than_match.group(1)
            if 'k' in val_str:
                min_val = int(float(val_str.replace('k', '')) * 1000)
            else:
                min_val = int(val_str)
        
        # Regex for "less than X" or "under X"
        less_than_match = re.search(r'(?:less than|under|below|<)[\s]*(\d+(?:k)?)', query_lower)
        if less_than_match:
            val_str = less_than_match.group(1)
            if 'k' in val_str:
                max_val = int(float(val_str.replace('k', '')) * 1000)
            else:
                max_val = int(val_str)
                
        # Remove the numeric parts from query for text matching
        # Removes things like "more than 5k faces", "under 1000 verts", etc.
        text_query = re.sub(r'(?:more than|over|above|less than|under|below|[<>])[\s]*\d+(?:k)?(?:[\s]*(?:faces|polys|polygons|triangles|vertices|verts|vertex|edges|edge))?', '', query_lower).strip()
        query_words = text_query.split()
        
        for model in all_models:
            # Check numeric constraints
            # Get the value based on target attribute (faces, vertices, or edges)
            # Fallback to 0 if not found
            if target_attr == 'vertices':
                count = model.get('vertices', 0)
            elif target_attr == 'edges':
                count = model.get('edges', 0)
            else:
                count = model.get('faces', model.get('polygon_count', 0))
            
            # Handle None values safely
            if count is None: 
                count = 0
                
            if count < min_val or count > max_val:
                continue
                
            # If query was only numeric, add all matching models
            if not query_words:
                model['_search_score'] = 1.0
                results.append(model)
                continue
            
            # Text matching
            tags = model.get('tags', [])
            # Handle tags being a string (comma-separated) or list
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',')]
                
            name = str(model.get('name', '')) or Path(model.get('path', '')).stem
            category = str(model.get('category', ''))
            
            # Combine all text fields
            search_text = f"{name.lower()} {' '.join(tags).lower()} {category.lower()}"
            
            # Simple matching: check if query words appear in search text
            matches = sum(1 for word in query_words if word in search_text)
            
            if matches > 0:
                model['_search_score'] = matches / len(query_words)
                results.append(model)
        
        # Sort by relevance
        results.sort(key=lambda x: x.get('_search_score', 0), reverse=True)
        
        return results

    
    def _load_tag_rules(self) -> Dict:
        """Load custom tagging rules (can be extended by users)."""
        return {
            'min_poly_game_ready': 10000,
            'min_poly_mobile': 5000,
            'min_poly_vr': 5000,
            'symmetry_tolerance': 0.1,
            'quality_threshold': 0.7
        }
    
    def _load_category_keywords(self) -> Dict[str, List[str]]:
        """Load category-related keywords for enhanced tagging."""
        return {
            'furniture': ['indoor', 'home', 'office', 'chair', 'table', 'desk', 
                         'shelf', 'cabinet', 'seating'],
            'character': ['human', 'creature', 'animal', 'hero', 'npc', 
                         'humanoid', 'biped', 'organic'],
            'vehicle': ['car', 'truck', 'plane', 'ship', 'bike', 'transport', 
                       'automobile', 'aircraft', 'vessel'],
            'architecture': ['building', 'structure', 'construction', 'house', 
                           'tower', 'bridge', 'urban', 'skyscraper', 'ruins', 'wall', 'floor', 'stairs'],
            'weapon': ['gun', 'sword', 'shield', 'knife', 'axe', 'bow', 
                      'ammo', 'projectile', 'blade'],
            'nature': ['tree', 'plant', 'rock', 'stone', 'grass', 'flower', 
                      'terrain', 'landscape', 'water'],
            'electronics': ['computer', 'phone', 'screen', 'device', 'tech', 
                           'robot', 'machine', 'circuit'],
            'prop': ['object', 'item', 'asset', 'decoration', 'detail'],
            'floor': ['ground', 'terrain', 'surface', 'plane', 'platform'],
            'wall': ['barrier', 'partition', 'divider', 'fence']
        }

    # =========================================================================
    # PERSISTENCE & MANAGEMENT METHODS (NEW)
    # =========================================================================

    def _get_tags_db_path(self) -> str:
        """Get path to tags database file."""
        # Use a local JSON file for tag storage
        root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(root, "config", "asset_tags.json")

    def _load_tags_db(self) -> Dict:
        """Load tags database."""
        path = self._get_tags_db_path()
        if os.path.exists(path):
            try:
                import json
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load tags DB: {e}")
        return {}

    def _save_tags_db(self, db: Dict):
        """Save tags database."""
        path = self._get_tags_db_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            import json
            with open(path, 'w') as f:
                json.dump(db, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save tags DB: {e}")

    def get_tags(self, model_path: str) -> List[str]:
        """Get tags for a specific model."""
        db = self._load_tags_db()
        # Normalize path
        norm_path = os.path.normpath(model_path)
        return db.get(norm_path, [])

    def add_tag(self, model_path: str, tag: str):
        """Add a tag to a model."""
        db = self._load_tags_db()
        norm_path = os.path.normpath(model_path)
        
        if norm_path not in db:
            db[norm_path] = []
        
        if tag not in db[norm_path]:
            db[norm_path].append(tag)
            self._save_tags_db(db)
            logger.info(f"Added tag '{tag}' to {os.path.basename(model_path)}")

    def remove_tag(self, model_path: str, tag: str):
        """Remove a tag from a model."""
        db = self._load_tags_db()
        norm_path = os.path.normpath(model_path)
        
        if norm_path in db and tag in db[norm_path]:
            db[norm_path].remove(tag)
            self._save_tags_db(db)
            logger.info(f"Removed tag '{tag}' from {os.path.basename(model_path)}")

    def generate_tags(self, model_path: str):
        """Generate and save tags for a model."""
        analysis = self.analyze_model(model_path)
        new_tags = analysis.get('tags', [])
        
        if new_tags:
            db = self._load_tags_db()
            norm_path = os.path.normpath(model_path)
            
            current_tags = set(db.get(norm_path, []))
            current_tags.update(new_tags)
            
            db[norm_path] = list(current_tags)
            self._save_tags_db(db)
            logger.info(f"Generated {len(new_tags)} tags for {os.path.basename(model_path)}")

    def get_popular_tags(self, limit: int = 20) -> List[Tuple[str, int]]:
        """Get most popular tags across all models."""
        db = self._load_tags_db()
        tag_counts = {}
        
        for tags in db.values():
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        # Sort by count desc
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_tags[:limit]

    def search_assets(self, query: str) -> List[Dict]:
        """
        Search for assets matching the query (tags, filename, or natural language).
        Returns list of model dictionaries.
        """
        # If we have the library manager, use it to get full model data (including poly counts)
        if self.library_manager:
            try:
                # Get all models as dicts
                all_models = self.library_manager.get_models()
                # Use the advanced natural language search
                return self.search_by_natural_language(query, all_models)
            except Exception as e:
                logger.error(f"Failed to search via library manager: {e}")
        
        # Fallback to local tags DB if library manager is not available
        db = self._load_tags_db()
        query_lower = query.lower()
        query_parts = query_lower.split()
        
        results = []
        
        for path, tags in db.items():
            # Check filename
            filename = os.path.basename(path).lower()
            
            # Check tags
            tag_string = " ".join(tags).lower()
            
            # Score match
            match_score = 0
            for part in query_parts:
                if part in filename or part in tag_string:
                    match_score += 1
            
            if match_score > 0:
                results.append({
                    'path': path,
                    'name': os.path.basename(path),
                    'tags': tags,
                    '_search_score': match_score / len(query_parts)
                })
        
        # Sort by score
        results.sort(key=lambda x: x.get('_search_score', 0), reverse=True)
        
        return results
    
    def export_tag_report(self, results: Dict[str, Dict], output_path: str):
        """
        Export tagging results to HTML report.
        
        Args:
            results: Results from batch_tag_models()
            output_path: Path to save HTML report
        """
        html_parts = []
        html_parts.append("<!DOCTYPE html>")
        html_parts.append("<html>")
        html_parts.append("<head>")
        html_parts.append("    <title>AI Tagging Report</title>")
        html_parts.append("    <style>")
        html_parts.append("        body { font-family: Arial, sans-serif; margin: 20px; }")
        html_parts.append("        table { border-collapse: collapse; width: 100%; }")
        html_parts.append("        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }")
        html_parts.append("        th { background-color: #4CAF50; color: white; }")
        html_parts.append("        .tag { display: inline-block; background: #e0e0e0; ")
        html_parts.append("               padding: 3px 8px; margin: 2px; border-radius: 3px; }")
        html_parts.append("        .category { background: #2196F3; color: white; }")
        html_parts.append("        .complexity { background: #FF9800; color: white; }")
        html_parts.append("    </style>")
        html_parts.append("</head>")
        html_parts.append("<body>")
        html_parts.append("    <h1>AI Asset Tagging Report</h1>")
        html_parts.append(f"    <p>Total models analyzed: {len(results)}</p>")
        html_parts.append("    <table>")
        html_parts.append("        <tr>")
        html_parts.append("            <th>Model</th>")
        html_parts.append("            <th>Category</th>")
        html_parts.append("            <th>Complexity</th>")
        html_parts.append("            <th>Polygons</th>")
        html_parts.append("            <th>Generated Tags</th>")
        html_parts.append("        </tr>")
        
        for model_path, analysis in results.items():
            if 'error' in analysis:
                continue
            
            model_name = Path(model_path).name
            category = analysis.get('category', 'unknown')
            complexity = analysis.get('complexity', 'unknown')
            poly_count = analysis.get('polygon_count', 0)
            tags = analysis.get('tags', [])
            
            tags_html = ''.join([f'<span class="tag">{tag}</span>' for tag in tags])
            
            html_parts.append("        <tr>")
            html_parts.append(f"            <td>{model_name}</td>")
            html_parts.append(f"            <td><span class=\"tag category\">{category}</span></td>")
            html_parts.append(f"            <td><span class=\"tag complexity\">{complexity}</span></td>")
            html_parts.append(f"            <td>{poly_count:,}</td>")
            html_parts.append(f"            <td>{tags_html}</td>")
            html_parts.append("        </tr>")
        
        html_parts.append("    </table>")
        html_parts.append("</body>")
        html_parts.append("</html>")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(html_parts))
        
        logger.info(f"Tag report exported to: {output_path}")


if __name__ == "__main__":
    # Demo usage
    tagger = AIAssetTagger()
    
    # Example: Analyze single model
    result = tagger.analyze_model("path/to/model.obj")
    print(f"Generated tags: {result.get('tags', [])}")
    
    # Example: Batch tagging
    models = ["model1.obj", "model2.fbx", "model3.stl"]
    results = tagger.batch_tag_models(models, 
                                      progress_callback=lambda c, t, n: print(f"{c}/{t}: {n}"))
    
    # Example: Natural language search
    # matching_models = tagger.search_by_natural_language(
    #     "low poly game ready furniture", 
    #     all_models_from_library
    # )
