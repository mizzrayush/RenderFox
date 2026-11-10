"""
Animation Engine for RenderFox.
Handles the playback loop, time management, and frame updates.
"""

import os
import sys

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QUrl

if sys.platform.startswith('win') and 'QT_MEDIA_BACKEND' not in os.environ:
    os.environ['QT_MEDIA_BACKEND'] = 'windows'

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False

from .animation_data import AnimationClip, AudioTrack

class AnimationEngine(QObject):
    """
    Core engine for driving animation playback.
    Decouples time management from the UI.
    """
    
    frame_changed = pyqtSignal(int)
    playback_started = pyqtSignal()
    playback_stopped = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        
        # State
        self._current_frame = 0
        self._is_playing = False
        self._fps = 30
        self._start_frame = 0
        self._end_frame = 100
        self._loop = True
        
        # Timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_tick)
        
        # Audio (Graceful fallback if QtMultimedia backend is missing)
        self._player = None
        self._audio_output = None
        if HAS_MULTIMEDIA:
            try:
                self._player = QMediaPlayer()
                self._audio_output = QAudioOutput()
                self._player.setAudioOutput(self._audio_output)
            except Exception:
                self._player = None
                self._audio_output = None
                
        self._has_audio = False
        self._audio_start_frame = 0
        
        # Data
        self._clip: AnimationClip = None
        
    @property
    def current_frame(self):
        return self._current_frame
        
    @property
    def is_playing(self):
        return self._is_playing
        
    @property
    def fps(self):
        return self._fps
        
    @fps.setter
    def fps(self, value):
        self._fps = value
        if self._is_playing:
            self._timer.setInterval(int(1000 / value))
            
    def set_clip(self, clip: AnimationClip):
        """Set the animation clip to play."""
        self._clip = clip
        self._end_frame = clip.duration
        self._fps = clip.fps
        
        # Check for audio tracks
        self._has_audio = False
        if self._player:
            for track in clip.tracks:
                if isinstance(track, AudioTrack):
                    self._has_audio = True
                    self._audio_start_frame = track.start_frame
                    self._player.setSource(QUrl.fromLocalFile(track.file_path))
                    self.update_audio_settings()
                    break # Support single audio track for now
                
    def update_audio_settings(self):
        """Update volume/mute state from current clip."""
        if not self._clip or not self._audio_output: return
        
        for track in self._clip.tracks:
            if isinstance(track, AudioTrack):
                vol = track.volume if not track.muted else 0.0
                self._audio_output.setVolume(vol)
                break
        
    def play(self):
        """Start playback."""
        if not self._is_playing:
            self._is_playing = True
            
            # Sync audio
            if self._has_audio and self._player:
                # Calculate position in ms
                # (Current Frame - Audio Start Frame) / FPS * 1000
                frame_offset = self._current_frame - self._audio_start_frame
                ms_pos = int((frame_offset / self._fps) * 1000)
                
                if ms_pos >= 0:
                    self._player.setPosition(ms_pos)
                    self._player.play()
            
            self._timer.start(int(1000 / self._fps))
            self.playback_started.emit()
            
    def pause(self):
        """Pause playback."""
        if self._is_playing:
            self._is_playing = False
            self._timer.stop()
            if self._has_audio and self._player:
                self._player.pause()
            self.playback_stopped.emit()
            
    def stop(self):
        """Stop playback and reset to start."""
        self.pause()
        if self._has_audio and self._player:
            self._player.stop()
        self.set_frame(self._start_frame)
        
    def set_frame(self, frame: int):
        """Jump to a specific frame."""
        self._current_frame = frame
        self.frame_changed.emit(frame)
        
        # If playing, audio handles itself mostly, but if scrubbing we might want to preview?
        # For now, only sync audio on Play
        
    def next_frame(self):
        """Move to next frame."""
        self.set_frame(self._current_frame + 1)
        
    def prev_frame(self):
        """Move to previous frame."""
        self.set_frame(self._current_frame - 1)
        
    def _on_tick(self):
        """Internal timer tick."""
        next_f = self._current_frame + 1
        
        if next_f > self._end_frame:
            if self._loop:
                next_f = self._start_frame
                # Restart audio loop
                if self._has_audio and self._player:
                    # Calculate if we are past audio start
                    if next_f >= self._audio_start_frame:
                        self._player.setPosition(0)
                        self._player.play()
                    else:
                        self._player.stop() # Wait for start frame
            else:
                self.pause()
                return
        
        # Check if we just hit audio start frame
        if self._has_audio and self._is_playing and self._player:
            if next_f == self._audio_start_frame:
                self._player.setPosition(0)
                self._player.play()
                
        self.set_frame(next_f)
