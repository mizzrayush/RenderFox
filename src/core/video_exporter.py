"""
Video Exporter for RenderFox.
Handles capturing frames and stitching them into a video file using ffmpeg.
"""

import os
import shutil
import logging
import subprocess
import tempfile
from typing import Optional, Callable
from PyQt6.QtCore import QObject, pyqtSignal, QSize
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget, QApplication

from ..utils.app_paths import app_root, bundled

# The FFmpeg build the installer copies into `$INSTDIR\ffmpeg` and the spec ships inside
# `resources`; both spellings of the search are the same folder name, so it is written once.
FFMPEG_BUILD = "ffmpeg-2025-12-22-git-c50e5c7778-essentials_build"

# The packaged build has no console (`RenderFox.spec`: console=False), so a render that failed
# has one place to say so: the root logger, which the Diagnostics pane turns into rows.
logger = logging.getLogger(__name__)


def find_ffmpeg_executable() -> str:
    """Locate the ffmpeg executable across bundled paths, resources, and system PATH."""
    # Two roots, both from the reader: the folder the executable lives in, which is where
    # `installer.nsi:107` unpacks the FFmpeg component, and the folder this start keeps the
    # shipped `resources` in - `_internal` for a package, the checkout for a source tree.
    app_dir = app_root()
    installed = os.path.join("ffmpeg", "bin", "ffmpeg.exe")
    shipped = os.path.join("resources", FFMPEG_BUILD, "bin", "ffmpeg.exe")

    candidates = [
        os.path.join(app_dir, installed),
        os.path.join(app_dir, "ffmpeg.exe"),
        os.path.join(app_dir, "bin", "ffmpeg.exe"),
        os.path.join(app_dir, shipped),
        bundled(installed),
        bundled(shipped),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    which_path = shutil.which("ffmpeg")
    if which_path:
        return which_path

    return "ffmpeg"


def _iso_boxes(data: bytes):
    """Top-level ISO-BMFF boxes as (type, payload_start, payload_end).

    A 4-byte big-endian size precedes a 4-byte type. size==1 means the true length
    is the following 8 bytes (a 16-byte header); size==0 means the box runs to the
    end of the data. A header that does not fit, or a size that overruns the data,
    ends the walk - a truncated file is not a container we can vouch for.
    """
    boxes = []
    total = len(data)
    offset = 0
    while offset + 8 <= total:
        size = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8].decode("latin-1")
        header = 8
        if size == 1:
            if offset + 16 > total:
                break
            size = int.from_bytes(data[offset + 8:offset + 16], "big")
            header = 16
        elif size == 0:
            size = total - offset
        if size < header or offset + size > total:
            break
        boxes.append((kind, offset + header, offset + size))
        offset += size
    return boxes


def _container_verdict(path: str):
    """Read the written file back and say what container it really is.

    The extension is not evidence: ffmpeg can exit 0 having written nothing, or a
    file that is not the H.264 MP4 the Animation tab promised. So the bytes are
    asked directly - an ISO-BMFF `ftyp` and `moov`, and an `avc1`/`avc3` sample
    entry inside the movie box, which is what libx264 writes. Returns (ok,
    sentence); a refusal names the missing piece so the dialog can say why.
    """
    if not os.path.isfile(path):
        return False, "no file was written"
    with open(path, "rb") as handle:
        data = handle.read()
    if not data:
        return False, "the file is empty"
    boxes = _iso_boxes(data)
    kinds = {kind for kind, _, _ in boxes}
    if "ftyp" not in kinds:
        return False, "not an MP4 container (no ftyp box)"
    moov = next(((start, end) for kind, start, end in boxes if kind == "moov"), None)
    if moov is None:
        return False, "not a playable MP4 (no moov box)"
    payload = data[moov[0]:moov[1]]
    if b"avc1" not in payload and b"avc3" not in payload:
        return False, "no H.264 track (avc1/avc3) - this ffmpeg could not encode H.264"
    return True, "H.264 MP4, container read back"


class VideoExporter(QObject):
    """
    Handles the export of animations to video files.
    """
    
    progress_changed = pyqtSignal(int) # 0-100
    finished = pyqtSignal(bool, str) # success, message
    
    def __init__(self):
        super().__init__()
        self._cancel_requested = False
        
    def render(self, 
               viewport: QWidget, 
               output_path: str, 
               start_frame: int, 
               end_frame: int, 
               fps: int,
               audio_path: Optional[str] = None,
               audio_offset_frames: int = 0,
               frame_callback: Callable[[int], None] = None):
        """
        Render the animation to a video file.
        
        Args:
            viewport: The widget to capture.
            output_path: The file path to save the MP4 video.
            start_frame: Beginning frame number.
            end_frame: Ending frame number.
            fps: Playback/record frames per second.
            audio_path: Optional path to audio track.
            audio_offset_frames: Audio alignment offset.
            frame_callback: Callback to update scene at each frame.
        """
        temp_dir = None
        try:
            self._cancel_requested = False
            total_frames = (end_frame - start_frame) + 1
            if total_frames <= 0:
                self.finished.emit(False, "Invalid frame range.")
                return
                
            # Create temp directory for frames
            temp_dir = tempfile.mkdtemp(prefix="renderfox_export_")
            
            # 1. Capture Frames
            for i, frame in enumerate(range(start_frame, end_frame + 1)):
                if self._cancel_requested:
                    self.finished.emit(False, "Export cancelled.")
                    return
                    
                # Update frame
                if frame_callback:
                    frame_callback(frame)
                    
                # Force update/repaint
                viewport.repaint()
                QApplication.processEvents() # Keep UI alive
                
                # Capture
                pixmap = viewport.grab()
                
                # Save to temp file
                filename = os.path.join(temp_dir, f"frame_{i:04d}.png")
                pixmap.save(filename, "PNG")
                
                # Emit progress (0-50% for capture)
                progress = int((i / total_frames) * 50)
                self.progress_changed.emit(progress)
                
            # 2. Encode with FFmpeg
            self.progress_changed.emit(50)
            
            ffmpeg_bin = find_ffmpeg_executable()
            
            # Construct command
            # ffmpeg -r 30 -i frame_%04d.png -c:v libx264 -pix_fmt yuv420p output.mp4
            cmd = [
                ffmpeg_bin,
                "-y", # Overwrite
                "-framerate", str(fps),
                "-i", os.path.join(temp_dir, "frame_%04d.png"),
            ]
            
            # Add Audio if present
            if audio_path and os.path.exists(audio_path):
                # Calculate offset in seconds
                offset_sec = audio_offset_frames / fps
                
                # Input audio
                cmd.extend(["-i", audio_path])
                
                # Sync logic:
                # If audio starts later (positive offset), delay audio
                # If audio starts earlier (negative offset), trim audio
                # This is complex in ffmpeg, for now let's assume simple mix
                # or just start at 0 if offset is handled by engine
                
                # Simple implementation: Map audio stream
                cmd.extend(["-c:a", "aac", "-shortest"])
            
            cmd.extend([
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                output_path
            ])
            
            # Run FFmpeg
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW # Windows only, hide console
            )
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                logger.warning("FFmpeg Error: %s", stderr.decode())
                self.finished.emit(False, f"H.264 encode failed: {stderr.decode()[:100]}...")
                return

            ok, sentence = _container_verdict(output_path)
            if not ok:
                self.finished.emit(False, f"H.264 MP4 not written: {sentence}")
                return

            self.progress_changed.emit(100)
            self.finished.emit(True, f"Render saved to {output_path} - {sentence}")
            
        except Exception as e:
            logger.warning("Render Error: %s", e)
            self.finished.emit(False, str(e))
            
        finally:
            # Cleanup
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            
    def cancel(self):
        self._cancel_requested = True
