"""
Core data models for RenderFox.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime

class JobStatus(Enum):
    """Status of a render job."""
    PENDING = "pending"
    PROCESSING = "processing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"

class SoftwareType(Enum):
    """Supported 3D software types."""
    BLENDER = "blender"
    MAYA = "maya"
    UNREAL = "unreal"
    CINEMA4D = "cinema4d"

class Priority(Enum):
    """Job priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

@dataclass
class RenderJob:
    """Represents a single render job."""
    id: str = ""
    name: str = ""
    project_file: str = ""
    software_type: SoftwareType = SoftwareType.BLENDER
    output_path: str = ""
    resolution: tuple[int, int] = (1920, 1080)
    frame_range: Optional[tuple[int, int]] = None
    output_format: str = "png"
    # Quality: the sample count each engine emits its own flag for (Cycles, Arnold, MRQ).
    samples: int = 128
    status: JobStatus = JobStatus.PENDING
    priority: Priority = Priority.NORMAL
    created_at: Optional[datetime] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    progress: float = 0.0
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Pre-processing options
    generate_lods: bool = False
    optimize_textures: bool = False
    optimize_scene: bool = False
    extract_models: bool = False
    
    # Post-processing options
    apply_denoising: bool = False
    add_watermark: bool = False
    watermark_text: str = ""
    auto_organize: bool = True
    
    # Additional metadata
    estimated_duration: Optional[float] = None
    actual_duration: Optional[float] = None
    file_size_mb: Optional[float] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

@dataclass
class PreProcessingSettings:
    """Settings for pre-processing operations."""
    # LOD Generation
    generate_lods: bool = False
    lod_levels: int = 3
    lod_ratios: List[float] = field(default_factory=lambda: [0.8, 0.5, 0.2])
    preserve_topology: bool = True
    preserve_boundaries: bool = True
    
    # Texture Optimization
    optimize_textures: bool = False
    texture_quality: float = 0.8
    texture_format: str = "png"
    max_texture_size: int = 2048
    compress_textures: bool = True
    
    # Scene Optimization
    optimize_scene: bool = False
    remove_hidden: bool = True
    merge_static: bool = True
    simplify_materials: bool = False
    cull_backfaces: bool = True
    
    # Model Extraction
    extract_models: bool = False
    min_face_count: int = 100
    extract_separate_objects: bool = True
    
    # Format Conversion
    convert_format: bool = False
    target_format: str = "obj"
    scale_factor: float = 1.0
    center_model: bool = False
    normalize_size: bool = False

@dataclass
class PostProcessingSettings:
    """Settings for post-processing operations.
    Note: preserve_details acts as a non-destructive flag across all steps.
    """
    # Denoising
    apply_denoising: bool = False
    denoise_strength: float = 0.5
    denoise_method: str = "OpenImageDenoise (OIDN)"
    preserve_details: bool = True
    process_alpha: bool = False
    
    # Watermarking
    add_watermark: bool = False
    watermark_text: str = ""
    watermark_logo: str = ""
    watermark_position: str = "bottom-right"
    watermark_opacity: float = 0.7
    watermark_font_size: int = 12
    watermark_color: str = "#FFFFFF"
    watermark_padding: int = 10
    
    # File Organization
    auto_organize: bool = True
    create_subfolders: bool = True
    organize_by_date: bool = False
    organize_by_format: bool = False
    organization_pattern: str = "{job_name}_{timestamp}_{frame:04d}"
    
    # Archive Management
    archive_old_jobs: bool = False
    archive_after_days: int = 30
    compress_archives: bool = True
    
    # Cleanup
    cleanup_temp_files: bool = True
    cleanup_failed_jobs: bool = False
    max_log_size_mb: int = 100

    # Performance
    parallel_processing: bool = True
    max_threads: int = 4

@dataclass
class TextureOptimizationSettings:
    """Settings specifically for texture optimization."""
    enabled: bool = False
    quality: float = 0.8
    max_resolution: int = 2048
    format_preference: str = "png"  # png, jpg, webp
    compress_normal_maps: bool = False
    compress_diffuse_maps: bool = True
    preserve_alpha: bool = True
    mipmap_generation: bool = True

@dataclass
class ModelExtractorSettings:
    """Settings for model extraction from scenes."""
    enabled: bool = False
    min_faces: int = 100
    min_vertices: int = 50
    extract_by_material: bool = False
    extract_by_object: bool = True
    combine_small_objects: bool = True
    preserve_hierarchy: bool = False
    export_textures: bool = True

@dataclass
class RenderSettings:
    """Advanced render settings."""
    # Quality settings
    samples: int = 128
    render_engine: str = "cycles"  # cycles, eevee, arnold, etc.
    use_gpu: bool = True
    tile_size: int = 256
    
    # Output settings
    color_depth: str = "8"  # 8, 16, 32
    color_space: str = "sRGB"
    file_format: str = "PNG"
    compression: float = 15.0
    
    # Performance settings
    max_memory_mb: int = 4096
    thread_count: int = 0  # 0 = auto
    timeout_minutes: int = 60

@dataclass
class ProjectSettings:
    """Overall project settings."""
    name: str = "Untitled Project"
    description: str = ""
    output_directory: str = ""
    temp_directory: str = ""
    
    # Default settings
    default_resolution: tuple[int, int] = (1920, 1080)
    default_format: str = "png"
    default_software: SoftwareType = SoftwareType.BLENDER
    
    # Workflow settings
    auto_save_interval: int = 300  # seconds
    backup_count: int = 5
    confirm_deletions: bool = True
    
    # Performance settings
    max_concurrent_jobs: int = 1
    enable_job_prioritization: bool = True
    auto_cleanup_temp: bool = True

@dataclass
class SoftwareConfiguration:
    """Configuration for specific 3D software."""
    software_type: SoftwareType
    executable_path: str = ""
    version: str = ""
    is_available: bool = False
    
    # Software-specific settings
    additional_args: List[str] = field(default_factory=list)
    environment_variables: Dict[str, str] = field(default_factory=dict)
    
    # Performance settings
    memory_limit_mb: int = 0  # 0 = no limit
    cpu_priority: str = "normal"  # low, normal, high
    
    # Plugin/addon settings
    required_plugins: List[str] = field(default_factory=list)
    plugin_paths: List[str] = field(default_factory=list)

@dataclass
class JobStatistics:
    """Statistics for render jobs."""
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    cancelled_jobs: int = 0
    
    total_render_time: float = 0.0
    average_render_time: float = 0.0
    
    total_files_processed: int = 0
    total_size_mb: float = 0.0
    
    # Performance metrics
    cpu_usage_avg: float = 0.0
    memory_usage_peak_mb: float = 0.0
    gpu_usage_avg: float = 0.0
    
    # Error tracking
    common_errors: Dict[str, int] = field(default_factory=dict)
    error_rate: float = 0.0

@dataclass
class AppSettings:
    """Application-wide settings."""
    # UI Settings
    theme: str = "dark"
    language: str = "en"
    auto_save_workspace: bool = True
    remember_window_state: bool = True
    
    # Logging
    log_level: str = "INFO"
    log_to_file: bool = True
    max_log_files: int = 10
    
    # Updates
    check_for_updates: bool = True
    auto_update: bool = False
    
    # Performance
    ui_update_interval_ms: int = 1000
    progress_update_interval_ms: int = 500
    
    # Network
    proxy_enabled: bool = False
    proxy_host: str = ""
    proxy_port: int = 8080
    
    # Advanced
    debug_mode: bool = False
    experimental_features: bool = False
    telemetry_enabled: bool = True

# Enums for various settings
class ColorSpace(Enum):
    """Color space options."""
    SRGB = "sRGB"
    REC709 = "Rec.709"
    ACES = "ACES"
    LINEAR = "Linear"

class FileFormat(Enum):
    """Supported output file formats."""
    PNG = "PNG"
    JPEG = "JPEG"
    EXR = "OpenEXR"
    TIFF = "TIFF"
    BMP = "BMP"
    TGA = "Targa"

class RenderEngine(Enum):
    """Supported render engines."""
    CYCLES = "cycles"
    EEVEE = "eevee"
    ARNOLD = "arnold"
    VRAY = "vray"
    OCTANE = "octane"
    REDSHIFT = "redshift"

class ThemeType(Enum):
    """UI theme types."""
    DARK = "dark"
    LIGHT = "light"
    AUTO = "auto"

# Utility functions for models
def create_default_render_job(name: str = "New Job") -> RenderJob:
    """Create a render job with default settings."""
    import uuid
    return RenderJob(
        id=str(uuid.uuid4()),
        name=name,
        project_file="",
        software_type=SoftwareType.BLENDER,
        output_path="",
        resolution=(1920, 1080)
    )

def get_default_preprocessing_settings() -> PreProcessingSettings:
    """Get default pre-processing settings."""
    return PreProcessingSettings()

def get_default_postprocessing_settings() -> PostProcessingSettings:
    """Get default post-processing settings."""
    return PostProcessingSettings()

def get_default_project_settings() -> ProjectSettings:
    """Get default project settings."""
    return ProjectSettings()

def validate_job(job: RenderJob) -> List[str]:
    """Validate a render job and return list of errors."""
    errors = []
    
    if not job.name or job.name.strip() == "":
        errors.append("Job name is required")
    
    if not job.project_file or not job.project_file.strip():
        errors.append("Project file is required")
    
    if not job.output_path or not job.output_path.strip():
        errors.append("Output path is required")
    
    if job.resolution[0] <= 0 or job.resolution[1] <= 0:
        errors.append("Resolution must be positive")
    
    if job.frame_range:
        start, end = job.frame_range
        if start > end:
            errors.append("Frame range start must be less than or equal to end")
        if start < 1:
            errors.append("Frame range start must be at least 1")
    
    return errors