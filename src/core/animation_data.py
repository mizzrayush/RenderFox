"""
Animation Data Model for RenderFox.
Defines the core structures for storing and manipulating animation data.
"""

import json
import math
from enum import Enum
from typing import List, Dict, Any, Optional, Union

class EasingType(Enum):
    LINEAR = "Linear"
    STEP = "Step"
    BEZIER = "Bezier"
    EASE_IN = "Ease In"
    EASE_OUT = "Ease Out"
    EASE_IN_OUT = "Ease In/Out"

class Keyframe:
    """Represents a single keyframe in an animation track."""
    
    def __init__(self, frame: int, value: Any, easing: EasingType = EasingType.LINEAR):
        self.frame = frame
        self.value = value
        self.easing = easing
        
        # Tangents for Bezier interpolation (control points relative to keyframe)
        # (x, y) where x is frame delta, y is value delta
        self.handle_left = (-1.0, 0.0)
        self.handle_right = (1.0, 0.0)
        
    def to_dict(self) -> Dict[str, Any]:
        """Serialize keyframe to dictionary."""
        return {
            "frame": self.frame,
            "value": self.value,
            "easing": self.easing.value,
            "handle_left": self.handle_left,
            "handle_right": self.handle_right
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Keyframe':
        """Deserialize keyframe from dictionary."""
        kf = cls(
            frame=data["frame"],
            value=data["value"],
            easing=EasingType(data.get("easing", "Linear"))
        )
        kf.handle_left = tuple(data.get("handle_left", (-1.0, 0.0)))
        kf.handle_right = tuple(data.get("handle_right", (1.0, 0.0)))
        return kf
        
    def __lt__(self, other):
        return self.frame < other.frame

class AnimationTrack:
    """Represents a sequence of keyframes for a specific property."""
    
    def __init__(self, name: str, property_path: str):
        self.name = name
        self.property_path = property_path
        self.keyframes: List[Keyframe] = []
        self.color_hex = "#3498DB"
        self.visible = True
        self.locked = False
        
    def add_keyframe(self, frame: int, value: Any, easing: EasingType = EasingType.LINEAR) -> Keyframe:
        """Add or update a keyframe at the specified frame."""
        # Check if keyframe exists
        for kf in self.keyframes:
            if kf.frame == frame:
                kf.value = value
                kf.easing = easing
                return kf
                
        # Create new
        kf = Keyframe(frame, value, easing)
        self.keyframes.append(kf)
        self.keyframes.sort() # Keep sorted by frame
        return kf
        
    def remove_keyframe(self, frame: int) -> bool:
        """Remove keyframe at specified frame."""
        for i, kf in enumerate(self.keyframes):
            if kf.frame == frame:
                self.keyframes.pop(i)
                return True
        return False
        
    def get_value_at_frame(self, frame: float) -> Any:
        """Calculate the interpolated value at a given frame."""
        if not self.keyframes:
            return 0.0 # Default fallback
            
        # Before first keyframe
        if frame <= self.keyframes[0].frame:
            return self.keyframes[0].value
            
        # After last keyframe
        if frame >= self.keyframes[-1].frame:
            return self.keyframes[-1].value
            
        # Find surrounding keyframes
        prev_kf = self.keyframes[0]
        next_kf = self.keyframes[-1]
        
        for i in range(len(self.keyframes) - 1):
            if self.keyframes[i].frame <= frame and self.keyframes[i+1].frame >= frame:
                prev_kf = self.keyframes[i]
                next_kf = self.keyframes[i+1]
                break
                
        # Interpolate
        t = (frame - prev_kf.frame) / (next_kf.frame - prev_kf.frame)
        
        if prev_kf.easing == EasingType.STEP:
            return prev_kf.value
        elif prev_kf.easing == EasingType.LINEAR:
            return self._lerp(prev_kf.value, next_kf.value, t)
        elif prev_kf.easing == EasingType.EASE_IN:
            t = t * t
            return self._lerp(prev_kf.value, next_kf.value, t)
        elif prev_kf.easing == EasingType.EASE_OUT:
            t = t * (2 - t)
            return self._lerp(prev_kf.value, next_kf.value, t)
        elif prev_kf.easing == EasingType.EASE_IN_OUT:
            t = t * t * (3 - 2 * t)
            return self._lerp(prev_kf.value, next_kf.value, t)
            
        return prev_kf.value
        
    def _lerp(self, a, b, t):
        """Linear interpolation."""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a + (b - a) * t
        return a # Fallback for non-numeric types
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "property_path": self.property_path,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
            "color": self.color_hex,
            "visible": self.visible,
            "locked": self.locked
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnimationTrack':
        track = cls(data["name"], data["property_path"])
        track.color_hex = data.get("color", "#3498DB")
        track.visible = data.get("visible", True)
        track.locked = data.get("locked", False)
        track.keyframes = [Keyframe.from_dict(kf_data) for kf_data in data.get("keyframes", [])]
        track.keyframes.sort()
        return track

class AudioTrack:
    """Represents an audio file in the timeline."""
    
    def __init__(self, name: str, file_path: str, start_frame: int = 0):
        self.name = name
        self.file_path = file_path
        self.start_frame = start_frame
        self.volume = 1.0
        self.muted = False
        self.color_hex = "#2ECC71" # Green for audio
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "audio",
            "name": self.name,
            "file_path": self.file_path,
            "start_frame": self.start_frame,
            "volume": self.volume,
            "muted": self.muted,
            "color": self.color_hex
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioTrack':
        track = cls(data["name"], data["file_path"], data.get("start_frame", 0))
        track.volume = data.get("volume", 1.0)
        track.muted = data.get("muted", False)
        track.color_hex = data.get("color", "#2ECC71")
        return track

class AnimationClip:
    """Represents a collection of tracks forming a complete animation."""
    
    def __init__(self, name: str = "New Animation"):
        self.name = name
        self.tracks: List[Union[AnimationTrack, AudioTrack]] = []
        self.duration = 100
        self.fps = 30
        
    def add_track(self, track: Union[AnimationTrack, AudioTrack]):
        self.tracks.append(track)
        
    def get_track(self, property_path: str) -> Optional[AnimationTrack]:
        for track in self.tracks:
            if isinstance(track, AnimationTrack) and track.property_path == property_path:
                return track
        return None
        
    def to_dict(self) -> Dict[str, Any]:
        tracks_data = []
        for track in self.tracks:
            data = track.to_dict()
            # Tag type for polymorphic loading
            if isinstance(track, AnimationTrack):
                data["type"] = "animation"
            elif isinstance(track, AudioTrack):
                data["type"] = "audio"
            tracks_data.append(data)
            
        return {
            "name": self.name,
            "duration": self.duration,
            "fps": self.fps,
            "tracks": tracks_data
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnimationClip':
        clip = cls(data.get("name", "New Animation"))
        clip.duration = data.get("duration", 100)
        clip.fps = data.get("fps", 30)
        
        for t_data in data.get("tracks", []):
            t_type = t_data.get("type", "animation")
            if t_type == "audio":
                clip.tracks.append(AudioTrack.from_dict(t_data))
            else:
                clip.tracks.append(AnimationTrack.from_dict(t_data))
                
        return clip
        
    def save_to_file(self, filepath: str):
        """Save animation clip to JSON file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(self.to_dict(), f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving animation: {e}")
            return False
            
    @classmethod
    def load_from_file(cls, filepath: str) -> Optional['AnimationClip']:
        """Load animation clip from JSON file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception as e:
            print(f"Error loading animation: {e}")
            return None
