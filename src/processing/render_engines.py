"""
Render engines for different 3D software integration.
"""

import os
import shutil
import subprocess
import json
import logging
import re
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Callable

from ..core.models import RenderJob, SoftwareType, JobStatus

# The packaged build has no console (`RenderFox.spec`: console=False), so the root logger is the
# only reader of a DCC process-control failure - the row a user gets when `stop` raises after the
# pane already reported the job stopped.
logger = logging.getLogger(__name__)

# Check for optional dependencies
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import platform
    PLATFORM_AVAILABLE = True
except ImportError:
    PLATFORM_AVAILABLE = False

# Optional advanced simplification library
FAST_SIMPLIFICATION_AVAILABLE = False
try:
    import fast_simplification
    FAST_SIMPLIFICATION_AVAILABLE = True
except ImportError:
    FAST_SIMPLIFICATION_AVAILABLE = False

_STEM_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def frame_stem(value: str) -> str:
    """A job name turned into something safe to put inside a frame's filename.

    `job.name` is free text from the Batch Render dialog, and it becomes part of
    every path handed to a renderer: `Hero/Shot 1` would otherwise write frames
    into a folder nobody asked for, and `:` is not legal in a Windows filename
    at all. A trailing dot or space is dropped because Windows refuses to store
    either.
    """
    return _STEM_UNSAFE.sub('_', (value or '').strip()).rstrip(' .') or 'render'


def output_spec(job: RenderJob) -> Tuple[str, str]:
    """(absolute directory, frame-name stem) for a job.

    `job.output_path` means two different things depending on who made the job,
    and getting it wrong is silent: the Batch Render dialog's Browse button uses
    `getExistingDirectory`, so `output_path` is a *folder* for nearly every job
    the UI creates and for every job imported from JSON, while the scripting API
    passes a file name (`output_path="render.png"`). Reading a folder as a file
    name takes its `dirname`, which is the folder above it, and the frames
    appear there instead.

    Absolute, because a renderer resolves a relative path against *its own*
    working directory, which this app does not control, and because an empty
    directory ("right here") is what `abspath('')` already gives.
    """
    raw = (job.output_path or '').strip()
    if os.path.isdir(raw) or raw.endswith(('/', '\\')):
        directory, stem = raw, job.name
    else:
        directory = os.path.dirname(raw)
        stem = os.path.splitext(os.path.basename(raw))[0] or job.name
    return os.path.abspath(directory), frame_stem(stem)


# Each renderer's own spelling of an image file format, as (what the user picks,
# what the command line wants).
#
# `job.output_format` stores the *extension* - that is what the post-processor
# looks for on disk afterwards, and what a saved queue JSON carries. A renderer
# wants a different thing again: Blender's `--render-format` takes a format name,
# and `JPG` is not one of them (it reports an unknown format and renders nothing);
# Maya's `imageFormat` takes a number, and a number it does not know writes a
# different file type without saying so. Either way the wrong token does not fail
# where it is written, it fails several minutes later in someone else's software.
_BLENDER_IMAGE_FORMATS = [('png', 'PNG'), ('jpg', 'JPEG'), ('exr', 'OPEN_EXR'),
                          ('tiff', 'TIFF'), ('bmp', 'BMP'), ('webp', 'WEBP'),
                          ('tga', 'TARGA'), ('dpx', 'DPX'), ('hdr', 'HDR')]
_MAYA_IMAGE_FORMATS = [('png', 32), ('jpg', 8), ('tiff', 3), ('exr', 51)]

# The formats a job may carry when nothing else constrains it. Neither of the two
# remaining engines is given a format *name*: Unreal's config JSON carries the
# extension as the app wrote it (the Movie Render Pipeline's own output settings
# live in a settings asset this app does not touch), and Cinema 4D's command line
# has no output-format switch at all, so the scene decides. Both keep this list so
# the dialog matches what a job can carry, and neither translates.
DEFAULT_IMAGE_FORMATS = ['png', 'jpg', 'exr', 'tiff', 'bmp']

_IMAGE_FORMATS: Dict[SoftwareType, List[Tuple[str, object]]] = {
    SoftwareType.BLENDER: _BLENDER_IMAGE_FORMATS,
    SoftwareType.MAYA: _MAYA_IMAGE_FORMATS,
}


def _format_choice(value: str) -> str:
    """A stored format string as a key of the tables above.

    `jpeg` is accepted as a synonym of `jpg` because both spellings are already
    in circulation: job JSON written by earlier builds, and the scripting API.
    """
    key = (value or '').strip().lower()
    return 'jpg' if key == 'jpeg' else key


def image_format_choices(software_type: SoftwareType) -> List[str]:
    """The formats worth offering for one engine.

    The dialog has to ask this instead of keeping its own list: an option that
    only one of the four renderers understands is an option that fails a click
    later, and the user cannot tell which.
    """
    pairs = _IMAGE_FORMATS.get(software_type)
    if pairs is None:
        return list(DEFAULT_IMAGE_FORMATS)
    return [choice for choice, _ in pairs]


def image_format_value(software_type: SoftwareType, output_format: str,
                       engine_name: str) -> object:
    """`output_format` translated for one engine, or a refusal naming the options.

    An engine with no table is not given the format, so the string passes through
    unchanged - the caller's scene settings decide.
    """
    pairs = _IMAGE_FORMATS.get(software_type)
    if pairs is None:
        return output_format
    table = dict(pairs)
    value = table.get(_format_choice(output_format))
    if value is None:
        raise ValueError(
            f"{engine_name} cannot be told to render '{output_format}'. "
            f"Use one of: {', '.join(sorted(table))}.")
    return value


class RenderEngine(ABC):
    """Abstract base class for render engines."""
    
    def __init__(self, executable_path: str):
        self.executable_path = executable_path
        self.name = "Unknown"
        self.version = "Unknown"
        self.supported_formats = []
        self.current_process = None
        self.should_stop = False
        self.progress_callback: Optional[Callable[[float], None]] = None
        self._progress = 0.0
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the render engine is available and functional."""
        pass
    
    @abstractmethod
    def get_version(self) -> str:
        """Get the version of the render engine."""
        pass
    
    @abstractmethod
    def render_job(self, job: RenderJob) -> bool:
        """Execute a render job."""
        pass
    
    @abstractmethod
    def get_render_command(self, job: RenderJob) -> List[str]:
        """Generate the command line for rendering."""
        pass
    
    def validate_project_file(self, file_path: str) -> bool:
        """Validate if the project file is compatible."""
        if not os.path.exists(file_path):
            return False
        
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self.supported_formats
    
    def set_progress_callback(self, callback: Callable[[float], None]):
        """Set the progress callback function."""
        self.progress_callback = callback
    
    def get_progress(self) -> float:
        """Current render progress (0-100), taken from the renderer's own output."""
        return self._progress

    def parse_progress(self, line: str) -> Optional[float]:
        """Turn one output line into a percentage, or None if it carries no progress.

        Subclasses implement this against the syntax their package really
        prints; `tests/test_mock_dcc.py` records those lines.
        """
        return None

    @staticmethod
    def _percent(done: float, total: float) -> Optional[float]:
        if total and total > 0:
            return max(0.0, min(100.0, done / total * 100.0))
        return None

    def _drain(self, stream, sink: List[str], on_line: Optional[Callable[[str], None]] = None):
        """Copy one pipe to a list, calling on_line as each line arrives.

        Both stdout and stderr need their own reader: a renderer that writes
        plenty to both fills one 4 KB buffer and blocks forever in the other.
        """
        try:
            for line in iter(stream.readline, ''):
                text = line.rstrip('\n')
                sink.append(text)
                if on_line:
                    on_line(text)
        except (ValueError, OSError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _observe(self, line: str):
        progress = self.parse_progress(line)
        if progress is not None:
            self._progress = progress
            if self.progress_callback:
                self.progress_callback(progress)

    @staticmethod
    def _files_in(directory: str) -> Dict[str, Tuple[int, int]]:
        """Size and modified-time of every file in a directory.

        The frame counters below are written against the progress syntax the
        mock DCC packages record; a real build could word its lines differently.
        The exit code plus the files left behind are the evidence that does not
        depend on parsing anything.
        """
        try:
            with os.scandir(directory) as entries:
                found: Dict[str, Tuple[int, int]] = {}
                for entry in entries:
                    try:
                        if entry.is_file():
                            stat = entry.stat()
                            found[entry.name] = (stat.st_size, stat.st_mtime_ns)
                    except OSError:
                        continue
                return found
        except OSError:
            return {}

    def execute(self, cmd: List[str], job: RenderJob) -> bool:
        """Run one render, reporting progress from live output."""
        # The queue can hand this engine a Stop click between its registration and
        # the launch. Clearing `should_stop` unconditionally here would render
        # straight over that request, so a pending stop is answered instead - and
        # then consumed, so a later render asked for is not cancelled by an old click.
        if self.should_stop:
            self.should_stop = False
            job.error_message = f"{self.name} render cancelled by user"
            return False
        self.should_stop = False
        self._progress = 0.0
        output_dir = output_spec(job)[0]
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as error:
            job.error_message = f"Cannot create output directory: {error}"
            return False

        before = self._files_in(output_dir)
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='replace')
        except OSError as error:
            job.error_message = f"Failed to start {self.name}: {error}"
            return False

        self.current_process = process
        if self.should_stop:
            # The Stop click landed in the window between the check above and this
            # launch, so the queue's snapshot of running engines never saw a process
            # it could kill - this is the only place that can.
            self.stop()
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        # Both streams are watched for progress: which one a given build reports
        # frames on is not this app's choice, and a `Fra:` line on stderr is
        # still a frame line.
        readers = [
            threading.Thread(target=self._drain, args=(process.stdout, stdout_lines, self._observe)),
            threading.Thread(target=self._drain, args=(process.stderr, stderr_lines, self._observe)),
        ]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join()
        return_code = process.wait()
        self.current_process = None

        if self.should_stop:
            job.error_message = f"{self.name} render cancelled by user"
            return False

        if return_code != 0:
            detail = "\n".join(stderr_lines).strip() or "\n".join(stdout_lines).strip()
            job.error_message = detail or f"{self.name} exited with code {return_code}"
            return False

        if self._progress <= 0.0 and self._files_in(output_dir) == before:
            job.error_message = (f"{self.name} exited cleanly without reporting a frame or "
                                 f"writing anything to {output_dir}")
            return False

        job.error_message = None
        self._progress = 100.0
        return True

    def stop(self):
        """Stop the current render process."""
        self.should_stop = True
        if self.current_process:
            try:
                if PSUTIL_AVAILABLE:
                    # Use psutil for better process management
                    parent = psutil.Process(self.current_process.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        child.terminate()
                    parent.terminate()
                else:
                    # Fallback to basic termination
                    self.current_process.terminate()
            except Exception as e:
                logger.warning("Error stopping process: %s", e)
                try:
                    if PSUTIL_AVAILABLE:
                        parent = psutil.Process(self.current_process.pid)
                        parent.kill()
                    else:
                        self.current_process.kill()
                except Exception:
                    pass
    
    def pause(self):
        """Pause the current render process."""
        if self.current_process and PSUTIL_AVAILABLE:
            try:
                parent = psutil.Process(self.current_process.pid)
                parent.suspend()
                children = parent.children(recursive=True)
                for child in children:
                    child.suspend()
            except Exception as e:
                logger.warning("Error pausing process: %s", e)
    
    def resume(self):
        """Resume the current render process."""
        if self.current_process and PSUTIL_AVAILABLE:
            try:
                parent = psutil.Process(self.current_process.pid)
                parent.resume()
                children = parent.children(recursive=True)
                for child in children:
                    child.resume()
            except Exception as e:
                logger.warning("Error resuming process: %s", e)
    
    def cleanup(self):
        """Cleanup after render completion."""
        if self.current_process:
            self.current_process = None
        self.should_stop = False

class BlenderEngine(RenderEngine):
    """Blender render engine implementation."""
    
    def __init__(self, executable_path: str):
        super().__init__(executable_path)
        self.name = "Blender"
        self.supported_formats = ['.blend']
    
    def is_available(self) -> bool:
        """Check if Blender is available."""
        try:
            if not os.path.exists(self.executable_path):
                return False
            
            # Quick version check to verify it's working
            result = subprocess.run([
                self.executable_path, "--version"
            ], capture_output=True, text=True, timeout=15)
            
            success = result.returncode == 0 and "Blender" in result.stdout
            if success:
                self.get_version()  # Cache version
            return success
            
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, Exception) as e:
            logger.warning("Blender availability check failed: %s", e)
            return False
    
    def get_version(self) -> str:
        """Get Blender version."""
        try:
            result = subprocess.run([
                self.executable_path, "--version"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Blender' in line and ('.' in line):
                        # Extract version from line like "Blender 4.0.2"
                        parts = line.split()
                        for part in parts:
                            if '.' in part and part[0].isdigit():
                                self.version = part
                                return part
                return "Unknown"
            return "Unknown"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, Exception):
            return "Unknown"
    
    def _output_template(self, job: RenderJob) -> str:
        """Blender's `-o` value: the chosen folder, the job's name, a `#` run.

        Without `#`, Blender appends the frame number to whatever string it was
        handed, so a folder used as the output path yields `<folder>0001.png` -
        one level above where the frames belong. The run also sets the padding,
        so it has to be wide enough for the last frame number or a long shot
        loses its leading zeros and the frames no longer sort in order.
        """
        directory, stem = output_spec(job)
        last = job.frame_range[1] if job.frame_range else 1
        digits = max(4, len(str(abs(last))))
        return os.path.join(directory, f'{stem}_' + '#' * digits)

    def get_render_command(self, job: RenderJob) -> List[str]:
        """Generate Blender render command."""
        cmd = [
            self.executable_path,
            "--background",  # Run in background mode
            job.project_file,  # Blend file
            "--render-output", self._output_template(job),  # <dir>/<stem>_####
            "--render-format", str(image_format_value(
                SoftwareType.BLENDER, job.output_format, self.name)),  # PNG/JPEG/OPEN_EXR
        ]
        
        # Add resolution
        cmd.extend([
            "--python-expr",
            f"import bpy; bpy.context.scene.render.resolution_x = {job.resolution[0]}; bpy.context.scene.render.resolution_y = {job.resolution[1]}"
        ])

        # Add frame range if specified
        if job.frame_range:
            start_frame, end_frame = job.frame_range
            cmd.extend([
                "--frame-start", str(start_frame),
                "--frame-end", str(end_frame),
                "--render-anim"  # Render animation
            ])
        else:
            cmd.append("--render-frame")
            cmd.append("1")  # Render single frame
        
        return cmd
    
    def parse_progress(self, line: str) -> Optional[float]:
        """Blender counts frames as `Fra:<this>/<total> Rendered ...`."""
        match = re.match(r'^Fra:(\d+)(?:/(\d+))?', line)
        if not match:
            return None
        done = int(match.group(1))
        total = int(match.group(2)) if match.group(2) else done
        return self._percent(done, total)

    def render_job(self, job: RenderJob) -> bool:
        """Execute Blender render job."""
        return self.execute(self.get_render_command(job), job)


class MayaEngine(RenderEngine):
    """Maya render engine implementation."""
    
    def __init__(self, executable_path: str):
        super().__init__(executable_path)
        self.name = "Maya"
        self.supported_formats = ['.ma', '.mb']
    
    def is_available(self) -> bool:
        """Check if Maya is available."""
        try:
            # Maya doesn't have a simple --version flag, so check if executable exists
            return os.path.exists(self.executable_path)
        except Exception:
            return False
    
    def get_version(self) -> str:
        """Get Maya version from executable path."""
        try:
            # Extract version from path like "Maya2024"
            path_parts = self.executable_path.split(os.sep)
            for part in path_parts:
                if 'Maya' in part and any(c.isdigit() for c in part):
                    # Extract year/version
                    version = ''.join(c for c in part if c.isdigit())
                    if version:
                        self.version = version
                        return version
            return "Unknown"
        except Exception:
            return "Unknown"
    
    def get_render_command(self, job: RenderJob) -> List[str]:
        """Generate Maya render command."""
        cmd = [
            self.executable_path,
            "-batch",  # Batch mode
            "-file", job.project_file,  # Maya file
            "-command", self._get_maya_mel_script(job)
        ]
        return cmd
    
    @staticmethod
    def _mel_string(value: str) -> str:
        """One path as a MEL quoted string wants it.

        Forward slashes instead of backslashes: Windows accepts them in API
        paths, they survive a MEL string literal untouched, and an odd number of
        backslashes before the closing quote would eat the quote and break the
        command.
        """
        return value.replace('\\', '/').replace('"', '\\"')

    def _get_maya_mel_script(self, job: RenderJob) -> str:
        """Generate MEL script for Maya rendering."""
        mel_commands = []
        
        # Set resolution
        mel_commands.extend([
            f"setAttr defaultResolution.width {job.resolution[0]};",
            f"setAttr defaultResolution.height {job.resolution[1]};"
        ])
        
        # Set output path and format
        output_dir = self._mel_string(output_spec(job)[0])
        output_name = self._mel_string(output_spec(job)[1])
        
        mel_commands.extend([
            f"workspace -fr \"images\" \"{output_dir}\";",
            f"setAttr -type \"string\" defaultRenderGlobals.imageFilePrefix \"{output_name}\";"
        ])
        
        # Set format
        format_id = image_format_value(SoftwareType.MAYA, job.output_format, self.name)
        mel_commands.append(f"setAttr defaultRenderGlobals.imageFormat {format_id};")
        
        # Frame range
        if job.frame_range:
            start_frame, end_frame = job.frame_range
            mel_commands.extend([
                f"setAttr defaultRenderGlobals.startFrame {start_frame};",
                f"setAttr defaultRenderGlobals.endFrame {end_frame};",
                "render -batch;"
            ])
        else:
            mel_commands.append("render -batch -frame 1;")
        
        return " ".join(mel_commands)
    
    def parse_progress(self, line: str) -> Optional[float]:
        """Maya counts frames as `// Rendering frame <this> of <total> //`."""
        match = re.search(r'Rendering frame (\d+) of (\d+)', line)
        if not match:
            return None
        return self._percent(int(match.group(1)), int(match.group(2)))

    def render_job(self, job: RenderJob) -> bool:
        """Execute Maya render job."""
        return self.execute(self.get_render_command(job), job)


class UnrealEngine(RenderEngine):
    """Unreal Engine render implementation."""
    
    def __init__(self, executable_path: str):
        super().__init__(executable_path)
        self.name = "Unreal Engine"
        self.supported_formats = ['.uproject']
    
    def is_available(self) -> bool:
        """Check if Unreal Engine is available."""
        try:
            return os.path.exists(self.executable_path)
        except Exception:
            return False
    
    def get_version(self) -> str:
        """Get Unreal Engine version."""
        try:
            # Extract version from path like "UE_5.3"
            path_parts = self.executable_path.split(os.sep)
            for part in path_parts:
                if 'UE_' in part:
                    version = part.replace('UE_', '')
                    self.version = version
                    return version
            return "Unknown"
        except Exception:
            return "Unknown"
    
    def get_render_command(self, job: RenderJob) -> List[str]:
        """Generate Unreal Engine render command."""
        cmd = [
            self.executable_path,
            job.project_file,  # .uproject file
            "-game",  # Game mode
            "-MoviePipelineConfig=" + self._create_movie_pipeline_config(job),
            "-windowed",
            "-ResX=" + str(job.resolution[0]),
            "-ResY=" + str(job.resolution[1])
        ]
        return cmd
    
    def _create_movie_pipeline_config(self, job: RenderJob) -> str:
        """Create Movie Render Pipeline configuration."""
        # This would create a JSON config for UE's Movie Render Pipeline
        # Simplified implementation
        config = {
            "OutputDirectory": output_spec(job)[0],
            "OutputFormat": job.output_format,
            "Resolution": job.resolution,
            # The command line carries no frame range for Unreal, so the config
            # file has to or an animation job renders exactly one frame.
            "StartFrame": job.frame_range[0] if job.frame_range else 1,
            "EndFrame": job.frame_range[1] if job.frame_range else 1
        }
        
        config_path = os.path.join(
            os.path.dirname(job.project_file), 
            "MoviePipelineConfig.json"
        )
        
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        return config_path
    
    def parse_progress(self, line: str) -> Optional[float]:
        """Unreal's Movie Render Queue prints both a frame tally and a percent.

        `Frame 2 ( 2/3 )` carries the real tally; the leading `[ 100.0%]` is the
        completion of the *current* frame, so the fraction has to win when both
        are present.
        """
        match = re.search(r'Frame \d+ \( *(\d+)/(\d+) *\)', line)
        if match:
            return self._percent(int(match.group(1)), int(match.group(2)))
        match = re.search(r'\[\s*(\d+(?:\.\d+)?)%\]', line)
        if match:
            return self._percent(float(match.group(1)), 100.0)
        return None

    def render_job(self, job: RenderJob) -> bool:
        """Execute Unreal Engine render job."""
        return self.execute(self.get_render_command(job), job)


class Cinema4DEngine(RenderEngine):
    """Cinema 4D render engine implementation."""
    
    def __init__(self, executable_path: str):
        super().__init__(executable_path)
        self.name = "Cinema 4D"
        self.supported_formats = ['.c4d']
    
    def is_available(self) -> bool:
        """Check if Cinema 4D is available."""
        try:
            return os.path.exists(self.executable_path)
        except Exception:
            return False
    
    def get_version(self) -> str:
        """Get Cinema 4D version."""
        try:
            path_parts = self.executable_path.split(os.sep)
            for part in path_parts:
                if 'Cinema 4D' in part and any(c.isdigit() for c in part):
                    # Extract version like "R25" or "2024"
                    version_match = re.search(r'(R\d+|\d{4})', part)
                    if version_match:
                        self.version = version_match.group(1)
                        return self.version
            return "Unknown"
        except Exception:
            return "Unknown"
    
    def get_render_command(self, job: RenderJob) -> List[str]:
        """Generate Cinema 4D render command."""
        cmd = [
            self.executable_path,
            "-nogui",  # No GUI
            "-render", job.project_file  # C4D file
        ]
        
        # Add render settings
        if job.frame_range:
            start_frame, end_frame = job.frame_range
            cmd.extend([
                "-frame", f"{start_frame}..{end_frame}"
            ])
        
        return cmd
    
    def parse_progress(self, line: str) -> Optional[float]:
        """Cinema 4D counts frames as `Frame <this> rendered (<this>/<total>)`."""
        match = re.search(r'Frame \d+ rendered \((\d+)/(\d+)\)', line)
        if not match:
            return None
        return self._percent(int(match.group(1)), int(match.group(2)))

    def render_job(self, job: RenderJob) -> bool:
        """Execute Cinema 4D render job."""
        return self.execute(self.get_render_command(job), job)


# Factory function for creating render engines
def create_render_engine(software_type: SoftwareType, executable_path: str) -> Optional[RenderEngine]:
    """Create a render engine instance based on software type."""
    engine_map = {
        SoftwareType.BLENDER: BlenderEngine,
        SoftwareType.MAYA: MayaEngine,
        SoftwareType.UNREAL: UnrealEngine,
        SoftwareType.CINEMA4D: Cinema4DEngine
    }
    
    engine_class = engine_map.get(software_type)
    if engine_class:
        return engine_class(executable_path)
    return None


def _get_user_configured_path(software_key: str) -> Optional[str]:
    """Retrieve software path from config.json if configured."""
    try:
        config_path = os.path.join(os.getcwd(), 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                software_data = data.get('software', {})
                val = software_data.get(software_key, '').strip()
                if val and os.path.exists(val):
                    return val
    except Exception:
        pass
    return None


def detect_available_software() -> Dict[SoftwareType, str]:
    """Detect available 3D software installations with robust error handling."""
    available_software = {}
    
    # Get platform info for better path detection
    system = "unknown"
    if PLATFORM_AVAILABLE:
        system = platform.system().lower()
    
    # Comprehensive installation paths for each software
    software_paths = {
        SoftwareType.BLENDER: _get_blender_paths(system),
        SoftwareType.MAYA: _get_maya_paths(system),
        SoftwareType.UNREAL: _get_unreal_paths(system),
        SoftwareType.CINEMA4D: _get_cinema4d_paths(system)
    }
    
    for software_type, paths in software_paths.items():
        for path in paths:
            try:
                if path and os.path.exists(path):
                    # Create engine instance to test availability
                    engine = create_render_engine(software_type, path)
                    if engine and engine.is_available():
                        version = engine.get_version()
                        available_software[software_type] = version
                        break
            except Exception:
                continue
    
    return available_software

def _preferred_paths(config_key: str, commands: List[str]) -> List[str]:
    """Where the user's own configuration and PATH say a package lives.

    The Settings tab stores an absolute executable path in `config.json`, and
    that is the only mechanism that works for a non-default install - the
    hardcoded version folders below are a guess that has to stay behind it, in
    the order the list is built. Every engine has to ask, not just Blender:
    `JobManager` refuses any job whose software is missing from
    `detect_available_software()`.
    """
    paths = []
    user_path = _get_user_configured_path(config_key)
    if user_path:
        paths.append(user_path)
    for command in commands:
        found = shutil.which(command)
        if found and found not in paths:
            paths.append(found)
    return paths

def _get_blender_paths(system: str) -> List[str]:
    """Get comprehensive Blender installation paths."""
    paths = _preferred_paths("blender", ["blender"])
    
    if system == "windows":
        # Windows paths
        base_paths = [
            r"C:\Program Files\Blender Foundation",
            r"C:\Program Files (x86)\Blender Foundation",
            r"C:\Program Files\Steam\steamapps\common\Blender",
            r"C:\Program Files (x86)\Steam\steamapps\common\Blender",
            os.path.expanduser(r"~\AppData\Local\Programs\Blender Foundation"),
            os.path.expanduser(r"~\Documents\Blender Foundation")
        ]
        
        for base in base_paths:
            if os.path.exists(base):
                try:
                    if os.path.exists(os.path.join(base, "blender.exe")):
                        paths.append(os.path.join(base, "blender.exe"))
                    for item in os.listdir(base):
                        if "Blender" in item:
                            blender_exe = os.path.join(base, item, "blender.exe")
                            if os.path.exists(blender_exe):
                                paths.append(blender_exe)
                except (OSError, PermissionError):
                    continue
        
        # Common specific versions (including modern 4.x+)
        paths.extend([
            r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
        ])
    
    elif system == "linux":
        paths.extend([
            "/usr/bin/blender",
            "/usr/local/bin/blender",
            "/snap/bin/blender",
            "/opt/blender/blender",
            os.path.expanduser("~/Applications/Blender/blender"),
        ])
    
    elif system == "darwin":  # macOS
        paths.extend([
            "/Applications/Blender.app/Contents/MacOS/Blender",
            os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
        ])
    
    return paths

def _get_maya_paths(system: str) -> List[str]:
    """Get comprehensive Maya installation paths."""
    paths = _preferred_paths("maya", ["maya"])
    
    if system == "windows":
        base_paths = [
            r"C:\Program Files\Autodesk",
            r"C:\Program Files (x86)\Autodesk"
        ]
        
        for base in base_paths:
            if os.path.exists(base):
                try:
                    for item in os.listdir(base):
                        if "Maya" in item:
                            maya_exe = os.path.join(base, item, "bin", "maya.exe")
                            if os.path.exists(maya_exe):
                                paths.append(maya_exe)
                except (OSError, PermissionError):
                    continue
        
        # Common specific versions
        paths.extend([
            r"C:\Program Files\Autodesk\Maya2024\bin\maya.exe",
            r"C:\Program Files\Autodesk\Maya2023\bin\maya.exe",
            r"C:\Program Files\Autodesk\Maya2022\bin\maya.exe",
        ])
    
    elif system == "linux":
        paths.extend([
            "/usr/autodesk/maya2024/bin/maya",
            "/usr/autodesk/maya2023/bin/maya",
            "/opt/Autodesk/Maya2024/bin/maya",
        ])
    
    elif system == "darwin":  # macOS
        paths.extend([
            "/Applications/Autodesk/maya2024/Maya.app/Contents/bin/maya",
            "/Applications/Autodesk/maya2023/Maya.app/Contents/bin/maya",
        ])
    
    return paths

def _get_unreal_paths(system: str) -> List[str]:
    """Get comprehensive Unreal Engine installation paths."""
    paths = _preferred_paths("unreal", ["UnrealEditor", "UnrealEditor-Cmd"])
    
    if system == "windows":
        base_paths = [
            r"C:\Program Files\Epic Games",
            r"D:\Epic Games",
            r"E:\Epic Games"
        ]
        
        for base in base_paths:
            if os.path.exists(base):
                try:
                    for item in os.listdir(base):
                        if "UE_" in item or "UnrealEngine" in item:
                            ue_exe = os.path.join(base, item, "Engine", "Binaries", "Win64", "UnrealEditor.exe")
                            if os.path.exists(ue_exe):
                                paths.append(ue_exe)
                except (OSError, PermissionError):
                    continue
        
        # Common specific versions
        paths.extend([
            r"C:\Program Files\Epic Games\UE_5.3\Engine\Binaries\Win64\UnrealEditor.exe",
            r"C:\Program Files\Epic Games\UE_5.2\Engine\Binaries\Win64\UnrealEditor.exe",
            r"C:\Program Files\Epic Games\UE_5.1\Engine\Binaries\Win64\UnrealEditor.exe"
        ])
    
    return paths

def _get_cinema4d_paths(system: str) -> List[str]:
    """Get comprehensive Cinema 4D installation paths."""
    paths = _preferred_paths("cinema4d", ["cinema4d", "Cinema 4D"])
    
    if system == "windows":
        base_paths = [
            r"C:\Program Files\Maxon",
            r"C:\Program Files\MAXON"
        ]
        
        for base in base_paths:
            if os.path.exists(base):
                try:
                    for item in os.listdir(base):
                        if "Cinema 4D" in item:
                            c4d_exe = os.path.join(base, item, "cinema4d.exe")
                            if os.path.exists(c4d_exe):
                                paths.append(c4d_exe)
                except (OSError, PermissionError):
                    continue
        
        # Common specific versions
        paths.extend([
            r"C:\Program Files\Maxon Cinema 4D 2024\cinema4d.exe",
            r"C:\Program Files\Maxon Cinema 4D R25\cinema4d.exe",
            r"C:\Program Files\MAXON\Cinema 4D R23\cinema4d.exe"
        ])
    
    return paths


class RenderJobExecutor:
    """Manages execution of render jobs across different engines."""
    
    def __init__(self):
        self.engines = {}
        self.active_processes = {}
    
    def register_engine(self, software_type: SoftwareType, executable_path: str):
        """Register a render engine."""
        engine = create_render_engine(software_type, executable_path)
        if engine and engine.is_available():
            self.engines[software_type] = engine
            return True
        return False
    
    def execute_job(self, job: RenderJob) -> bool:
        """Execute a render job using the appropriate engine."""
        engine = self.engines.get(job.software_type)
        if not engine:
            job.error_message = f"No engine available for {job.software_type.value}"
            return False
        
        if not engine.validate_project_file(job.project_file):
            job.error_message = f"Invalid project file: {job.project_file}"
            return False
        
        try:
            job.status = JobStatus.RENDERING
            success = engine.render_job(job)
            
            if success:
                job.status = JobStatus.COMPLETED
            else:
                job.status = JobStatus.FAILED
            
            return success
            
        except Exception as e:
            job.error_message = f"Execution error: {str(e)}"
            job.status = JobStatus.FAILED
            return False
    
    def get_available_engines(self) -> List[SoftwareType]:
        """Get list of available render engines."""
        return list(self.engines.keys())
    
    def get_engine_info(self, software_type: SoftwareType) -> Optional[Dict]:
        """Get information about a specific engine."""
        engine = self.engines.get(software_type)
        if engine:
            return {
                "name": engine.name,
                "version": engine.get_version(),
                "supported_formats": engine.supported_formats,
                "executable_path": engine.executable_path
            }
        return None


# Utility functions
def validate_render_setup() -> Dict[str, bool]:
    """Validate the render setup and return status."""
    validation_results = {}
    
    # Check for available software
    available_software = detect_available_software()
    validation_results["software_detected"] = len(available_software) > 0
    validation_results["available_software"] = list(available_software.keys())
    
    # Check system requirements
    if PSUTIL_AVAILABLE:
        try:
            validation_results["sufficient_memory"] = psutil.virtual_memory().total >= 2 * 1024**3  # 2GB
            
            # Platform-appropriate disk usage check
            if PLATFORM_AVAILABLE and platform.system().lower() == "windows":
                disk_path = "C:\\"
            else:
                disk_path = "/"
            
            try:
                disk_usage = psutil.disk_usage(disk_path)
                validation_results["sufficient_disk"] = disk_usage.free >= 10 * 1024**3  # 10GB
            except Exception:
                validation_results["sufficient_disk"] = True  # Assume sufficient if check fails
                
        except Exception:
            validation_results["sufficient_memory"] = True
            validation_results["sufficient_disk"] = True
    else:
        validation_results["sufficient_memory"] = True  # Assume sufficient if psutil is not available
        validation_results["sufficient_disk"] = True  # Assume sufficient if psutil is not available
    
    return validation_results


def get_render_presets() -> Dict[str, Dict]:
    """Get predefined render presets for common use cases."""
    return {
        "draft": {
            "description": "Low quality for previews",
            "resolution": (640, 480),
            "quality": 50,
            "samples": 32
        },
        "preview": {
            "description": "Medium quality for review",
            "resolution": (1280, 720),
            "quality": 75,
            "samples": 64
        },
        "production": {
            "description": "High quality for final output",
            "resolution": (1920, 1080),
            "quality": 95,
            "samples": 128
        },
        "4k": {
            "description": "Ultra high quality 4K",
            "resolution": (3840, 2160),
            "quality": 100,
            "samples": 256
        }
    }


def estimate_render_time(job: RenderJob) -> float:
    """Estimate render time in minutes based on job parameters."""
    # Simple estimation based on resolution and frame count
    base_time = 0.5  # Base time per frame in minutes
    
    # Resolution factor
    pixel_count = job.resolution[0] * job.resolution[1]
    resolution_factor = pixel_count / (1920 * 1080)  # Relative to 1080p
    
    # Frame count
    frame_count = 1
    if job.frame_range:
        frame_count = job.frame_range[1] - job.frame_range[0] + 1
    
    # Software factor (some are slower/faster)
    software_factors = {
        SoftwareType.BLENDER: 1.0,
        SoftwareType.MAYA: 1.2,
        SoftwareType.UNREAL: 0.8,
        SoftwareType.CINEMA4D: 1.1
    }
    
    software_factor = software_factors.get(job.software_type, 1.0)
    
    estimated_time = base_time * resolution_factor * frame_count * software_factor
    
    return max(0.1, estimated_time)  # Minimum 6 seconds