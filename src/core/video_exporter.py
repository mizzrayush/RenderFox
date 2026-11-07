"""
Video Exporter for RenderFox.
Handles capturing frames and stitching them into a video file using ffmpeg.
"""

import os
import sys
import shutil
import logging
import subprocess
import tempfile
from typing import Optional, Callable
from PyQt6.QtCore import QObject, pyqtSignal, QSize
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget, QApplication

# The packaged build has no console (`RenderFox.spec`: console=False), so a render that failed
# has one place to say so: the root logger, which the Diagnostics pane turns into rows.
logger = logging.getLogger(__name__)


def find_ffmpeg_executable() -> str:
    """Locate the ffmpeg executable across bundled paths, resources, and system PATH."""
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass_dir = getattr(sys, '_MEIPASS', app_dir)
    else:
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        meipass_dir = app_dir

    candidates = [
        os.path.join(app_dir, "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(app_dir, "ffmpeg.exe"),
        os.path.join(app_dir, "bin", "ffmpeg.exe"),
        os.path.join(app_dir, "resources", "ffmpeg-2025-12-22-git-c50e5c7778-essentials_build", "bin", "ffmpeg.exe"),
        os.path.join(meipass_dir, "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(meipass_dir, "resources", "ffmpeg-2025-12-22-git-c50e5c7778-essentials_build", "bin", "ffmpeg.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    which_path = shutil.which("ffmpeg")
    if which_path:
        return which_path

    return "ffmpeg"


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
                self.finished.emit(False, f"FFmpeg failed: {stderr.decode()[:100]}...")
                return
                
            self.progress_changed.emit(100)
            self.finished.emit(True, f"Render saved to {output_path}")
            
        except Exception as e:
            logger.warning("Render Error: %s", e)
            self.finished.emit(False, str(e))
            
        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    def cancel(self):
        self._cancel_requested = True
