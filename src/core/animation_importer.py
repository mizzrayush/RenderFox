"""Read and sample glTF animation data without fabricating unsupported skinning."""

import base64
import json
import math
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class AnimationChannel:
    node: int
    path: str
    times: Tuple[float, ...]
    values: Tuple[Tuple[float, ...], ...]
    interpolation: str = 'LINEAR'


@dataclass(frozen=True)
class ImportedAnimation:
    name: str
    channel_count: int
    duration_seconds: Optional[float]
    channels: Tuple[AnimationChannel, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AnimationImportReport:
    success: bool
    message: str
    skeleton_count: int = 0
    joint_count: int = 0
    clips: List[ImportedAnimation] = None


def _document_and_buffers(path: str):
    raw = Path(path).read_bytes()
    binary_chunk = b''
    if raw[:4] == b'glTF':
        if len(raw) < 20:
            raise ValueError('truncated GLB header')
        offset, document = 12, None
        while offset + 8 <= len(raw):
            size, kind = struct.unpack_from('<II', raw, offset)
            offset += 8
            chunk = raw[offset:offset + size]
            offset += size
            if len(chunk) != size:
                raise ValueError('truncated GLB chunk')
            if kind == 0x4E4F534A:
                document = json.loads(chunk.decode('utf-8').rstrip(' \t\r\n\0'))
            elif kind == 0x004E4942:
                binary_chunk = chunk
        if document is None:
            raise ValueError('GLB has no JSON document')
    else:
        document = json.loads(raw.decode('utf-8'))
    buffers = []
    for index, descriptor in enumerate(document.get('buffers') or []):
        uri = descriptor.get('uri')
        if uri is None:
            if index != 0 or not binary_chunk:
                raise ValueError(f'buffer {index} has no accessible data')
            buffers.append(binary_chunk)
        elif uri.startswith('data:'):
            try:
                buffers.append(base64.b64decode(uri.split(',', 1)[1]))
            except (IndexError, ValueError) as error:
                raise ValueError(f'buffer {index} has invalid data URI: {error}') from error
        else:
            buffers.append((Path(path).parent / uri).read_bytes())
    return document, buffers


_COMPONENTS = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2),
               5125: ('I', 4), 5126: ('f', 4)}
_ARITY = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def _accessor(document: dict, buffers: Sequence[bytes], index: int) -> Tuple[Tuple[float, ...], ...]:
    accessors, views = document.get('accessors') or [], document.get('bufferViews') or []
    if not 0 <= index < len(accessors):
        raise ValueError(f'animation accessor {index} is missing')
    accessor = accessors[index]
    if 'bufferView' not in accessor:
        raise ValueError('sparse animation accessors are not supported')
    view = views[accessor['bufferView']]
    component = accessor.get('componentType')
    if component not in _COMPONENTS or accessor.get('type') not in _ARITY:
        raise ValueError('animation accessor uses an unsupported component or shape')
    code, width = _COMPONENTS[component]
    arity = _ARITY[accessor['type']]
    item_size = width * arity
    stride = int(view.get('byteStride') or item_size)
    start = int(view.get('byteOffset') or 0) + int(accessor.get('byteOffset') or 0)
    payload, count = buffers[view['buffer']], int(accessor.get('count') or 0)
    if start + max(0, count - 1) * stride + item_size > len(payload):
        raise ValueError('animation accessor runs past its buffer')
    fmt = '<' + code * arity
    return tuple(tuple(float(v) for v in struct.unpack_from(fmt, payload, start + row * stride))
                 for row in range(count))


def _sample(channel: AnimationChannel, seconds: float) -> Tuple[float, ...]:
    if not channel.times:
        return ()
    if seconds <= channel.times[0]: return channel.values[0]
    if seconds >= channel.times[-1]: return channel.values[-1]
    for index in range(len(channel.times) - 1):
        left, right = channel.times[index:index + 2]
        if left <= seconds <= right:
            if channel.interpolation == 'STEP': return channel.values[index]
            ratio = (seconds - left) / (right - left)
            values = tuple(a + (b - a) * ratio
                           for a, b in zip(channel.values[index], channel.values[index + 1]))
            if channel.path == 'rotation':
                length = math.sqrt(sum(value * value for value in values))
                return tuple(value / length for value in values) if length else (0.0, 0.0, 0.0, 1.0)
            return values
    return channel.values[-1]


class AnimationImporter:
    @staticmethod
    def inspect(path: str) -> AnimationImportReport:
        ext = Path(path).suffix.lower()
        if ext not in ('.gltf', '.glb'):
            return AnimationImportReport(False, 'skeletal inspection currently accepts glTF (.gltf/.glb); this format has no verified reader')
        if not os.path.isfile(path):
            return AnimationImportReport(False, f'animation source does not exist: {path}')
        try:
            document, _ = _document_and_buffers(path)
            skins, animations = document.get('skins') or [], document.get('animations') or []
            joints = sum(len(skin.get('joints') or []) for skin in skins)
            clips = [ImportedAnimation(animation.get('name') or f'Animation {index + 1}',
                                       len(animation.get('channels') or []), None)
                     for index, animation in enumerate(animations)]
            if not skins and not clips:
                return AnimationImportReport(False, 'the glTF contains no skins or animation clips')
            return AnimationImportReport(True, f'read {len(skins)} skin(s), {joints} joint(s), and {len(clips)} animation clip(s) from the file', len(skins), joints, clips)
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return AnimationImportReport(False, f'could not read glTF animation data: {error}')

    @staticmethod
    def load(path: str) -> AnimationImportReport:
        """Load transform curves. Cubic spline and skin deformation are refused."""
        report = AnimationImporter.inspect(path)
        if not report.success: return report
        try:
            document, buffers = _document_and_buffers(path)
            clips = []
            for clip_index, animation in enumerate(document.get('animations') or []):
                samplers, channels = animation.get('samplers') or [], []
                for channel in animation.get('channels') or []:
                    target, sampler_index = channel.get('target') or {}, channel.get('sampler')
                    path_name = target.get('path')
                    if path_name not in ('translation', 'rotation', 'scale') or not isinstance(sampler_index, int): continue
                    sampler = samplers[sampler_index]
                    interpolation = sampler.get('interpolation', 'LINEAR')
                    if interpolation == 'CUBICSPLINE': raise ValueError('CUBICSPLINE animation interpolation is not yet supported')
                    times = tuple(row[0] for row in _accessor(document, buffers, sampler['input']))
                    values = _accessor(document, buffers, sampler['output'])
                    if len(times) != len(values): raise ValueError('animation sampler has different input and output counts')
                    channels.append(AnimationChannel(int(target.get('node', 0)), path_name, times, values, interpolation))
                duration = max((channel.times[-1] for channel in channels if channel.times), default=None)
                clips.append(ImportedAnimation(animation.get('name') or f'Animation {clip_index + 1}', len(animation.get('channels') or []), duration, tuple(channels)))
            return AnimationImportReport(True, report.message, report.skeleton_count, report.joint_count, clips)
        except (KeyError, OSError, ValueError, IndexError, struct.error) as error:
            return AnimationImportReport(False, f'could not load glTF animation curves: {error}')

    @staticmethod
    def sample(clip: ImportedAnimation, seconds: float) -> Dict[int, Dict[str, Tuple[float, ...]]]:
        result: Dict[int, Dict[str, Tuple[float, ...]]] = {}
        for channel in clip.channels:
            result.setdefault(channel.node, {})[channel.path] = _sample(channel, seconds)
        return result
