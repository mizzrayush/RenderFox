"""Read glTF animation and skin metadata without inventing playback support."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class ImportedAnimation:
    name: str
    channel_count: int
    duration_seconds: Optional[float]


@dataclass(frozen=True)
class AnimationImportReport:
    success: bool
    message: str
    skeleton_count: int = 0
    joint_count: int = 0
    clips: List[ImportedAnimation] = None


def _document(path: str):
    raw = Path(path).read_bytes()
    if raw[:4] == b'glTF':
        if len(raw) < 20:
            raise ValueError('truncated GLB header')
        size = int.from_bytes(raw[12:16], 'little')
        return json.loads(raw[20:20 + size].decode('utf-8'))
    return json.loads(raw.decode('utf-8'))


class AnimationImporter:
    @staticmethod
    def inspect(path: str) -> AnimationImportReport:
        ext = Path(path).suffix.lower()
        if ext not in ('.gltf', '.glb'):
            return AnimationImportReport(False,
                'skeletal inspection currently accepts glTF (.gltf/.glb); this format has no verified reader')
        if not os.path.isfile(path):
            return AnimationImportReport(False, f'animation source does not exist: {path}')
        try:
            document = _document(path)
            skins = document.get('skins') or []
            animations = document.get('animations') or []
            joints = sum(len(skin.get('joints') or []) for skin in skins)
            clips = []
            for index, animation in enumerate(animations):
                # glTF timing lives in binary accessors.  This importer deliberately
                # does not guess a duration from channel count.
                clips.append(ImportedAnimation(animation.get('name') or f'Animation {index + 1}',
                                                len(animation.get('channels') or []), None))
            if not skins and not clips:
                return AnimationImportReport(False, 'the glTF contains no skins or animation clips')
            return AnimationImportReport(True,
                f'read {len(skins)} skin(s), {joints} joint(s), and {len(clips)} animation clip(s) from the file',
                len(skins), joints, clips)
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return AnimationImportReport(False, f'could not read glTF animation data: {error}')
