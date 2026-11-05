"""Puts the images a texture run produced back into the model file that referenced them.

A texture optimizer that only writes .png and .jpg files next to the asset has not
shortened anything a game engine loads: a .glb carries its textures inside itself, and an
.obj points at them by name through its .mtl. This module edits those references, so the
file a user hands over is the one that got smaller.

Nothing here re-encodes geometry. For glTF and GLB only the image entries, the buffer
views and the buffer length change; the mesh bytes are copied through, which is what lets
the report promise the shape is the same.
"""

import glob
import hashlib
import io
import json
import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PIL import Image

MIME_FOR_FORMAT = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}
EXTENSION_FOR_FORMAT = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}

# The maps a .mtl can carry. Each is a different texture, and each is worth repointing
# when the pixels match something this run encoded.
_MTL_MAPS = ('map_Kd', 'map_Bump', 'map_Ks', 'map_Ns', 'map_d', 'map_Pm', 'map_Ke')

# Files packed with these extensions hold their buffer views in a form this module cannot
# rearrange safely, so they are refused rather than quietly corrupted.
_UNREPACKABLE = ('KHR_draco_mesh_compression', 'EXT_meshopt_compression',
                 'KHR_texture_basisu', 'EXT_texture_webp')


@dataclass
class EncodedTexture:
    """The bytes a texture was encoded to, the format, and the name it ships under."""
    data: bytes
    fmt: str
    name: str


Mapping = Dict[str, EncodedTexture]


def pixels_key(image: Image.Image) -> str:
    """Identity of an image by what it shows, not by what it is called."""
    digest = hashlib.md5()
    digest.update(f'{image.mode}:{image.size}'.encode('ascii'))
    digest.update(image.tobytes())
    return digest.hexdigest()


def key_of_bytes(data: bytes) -> Optional[str]:
    """The same identity for encoded bytes, or None when they are not an image."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            return pixels_key(image)
    except Exception:
        return None


def _glb_chunks(blob: bytes) -> Tuple[Optional[dict], bytes, str]:
    """The JSON header and BIN chunk of a .glb, or a reason it is not one."""
    if len(blob) < 20 or blob[:4] != b'glTF':
        return None, b'', 'not a glTF binary file'
    offset, header, bin_bytes = 12, None, b''
    while offset + 8 <= len(blob):
        length = struct.unpack('<I', blob[offset:offset + 4])[0]
        kind = blob[offset + 4:offset + 8]
        payload = blob[offset + 8:offset + 8 + length]
        if len(payload) < length:
            return None, b'', 'the file ends inside a chunk'
        if kind == b'JSON':
            try:
                header = json.loads(payload.decode('utf-8', errors='replace').strip())
            except ValueError:
                return None, b'', 'the JSON chunk of the file is not readable'
        elif kind == b'BIN\x00':
            bin_bytes = payload
        offset += 8 + length
    if header is None:
        return None, b'', 'the file has no JSON chunk'
    return header, bin_bytes, ''


def _glb_bytes(header: dict, bin_bytes: bytes) -> bytes:
    """A whole .glb from a header and its buffer, padded the way the spec demands."""
    json_blob = json.dumps(header, separators=(',', ':')).encode('utf-8')
    json_blob += b' ' * ((-len(json_blob)) % 4)
    padded_bin = bin_bytes + b'\x00' * ((-len(bin_bytes)) % 4)
    total = 12 + 8 + len(json_blob) + 8 + len(padded_bin)
    out = b'glTF' + struct.pack('<II', 2, total)
    out += struct.pack('<I', len(json_blob)) + b'JSON' + json_blob
    out += struct.pack('<I', len(padded_bin)) + b'BIN\x00' + padded_bin
    return out


def _refusable(header: dict) -> str:
    """Why this file must not be repacked, or '' when it can.

    A draco- or meshopt-compressed file keeps its geometry in buffer views that only the
    extension's decoder understands the layout of. Rearranging those from here would
    corrupt the mesh, so the file is refused and the user is told why.
    """
    used = set(header.get('extensionsUsed') or []) | set(header.get('extensionsRequired') or [])
    for name in sorted(used):
        if name in _UNREPACKABLE:
            return (f'this file uses {name}, whose buffers this app does not rearrange; '
                    f'nothing was written')
    return ''


def _repack(header: dict, bin_bytes: bytes,
            mapping: Mapping) -> Tuple[Optional[bytes], str, int]:
    """Rebuild the buffer so only the bytes still referenced are in it.

    Keeping the original buffer and appending the new images - the obvious way to do this
    - leaves every replaced texture in the file as an orphan, which measured 135 kB of
    dead weight on a two-texture test model. So the buffer is written from scratch: each
    view an accessor still needs is copied whole at an aligned offset, which is why the
    accessors keep their own byte offsets and interleaved vertex data still lands where it
    did, and each image gets the bytes this run encoded.
    """
    views = header.get('bufferViews') or []
    accessors = header.get('accessors') or []
    images = header.get('images') or []
    buffers = header.get('buffers') or [{'byteLength': len(bin_bytes)}]
    replaced = 0
    if len(buffers) > 1:
        return None, ('this file spreads its data over '
                      f'{len(buffers)} buffers, which this app does not rewrite'), 0

    needed_by_accessors: Dict[int, List[int]] = {}
    for accessor_index, accessor in enumerate(accessors):
        view = accessor.get('bufferView')
        if view is not None:
            needed_by_accessors.setdefault(view, []).append(accessor_index)

    new_bin = bytearray()
    new_views: List[dict] = []

    def add_view(data: bytes, source: Optional[dict] = None, align: int = 8) -> int:
        pad = (-len(new_bin)) % align
        new_bin.extend(b'\x00' * pad)
        record = {'buffer': 0, 'byteOffset': len(new_bin), 'byteLength': len(data)}
        if source and source.get('byteStride') is not None:
            record['byteStride'] = source['byteStride']
        if source and source.get('target') is not None:
            record['target'] = source['target']
        index = len(new_views)
        new_views.append(record)
        new_bin.extend(data)
        return index

    for view_index in sorted(needed_by_accessors):
        if not (0 <= view_index < len(views)):
            return None, f'accessor points at buffer view {view_index}, which the file does not have', 0
        view = views[view_index]
        start = int(view.get('byteOffset', 0))
        length = int(view.get('byteLength', 0))
        data = bytes(bin_bytes[start:start + length])
        if len(data) != length:
            return None, 'the file ends inside a buffer view', 0
        new_index = add_view(data, source=view)
        for accessor_index in needed_by_accessors[view_index]:
            accessors[accessor_index]['bufferView'] = new_index

    for image in images:
        view_index = image.get('bufferView')
        data = None
        if view_index is not None and 0 <= view_index < len(views):
            view = views[view_index]
            start = int(view.get('byteOffset', 0))
            data = bytes(bin_bytes[start:start + int(view.get('byteLength', 0))])
        if data is None:
            continue
        found = mapping.get(key_of_bytes(data) or '')
        if found is None:
            # Untouched textures still have to travel with the file: their bytes become
            # their own view, since the view they shared is gone now.
            image['bufferView'] = add_view(data, align=4)
            continue
        image['bufferView'] = add_view(found.data, align=4)
        image['mimeType'] = MIME_FOR_FORMAT.get(found.fmt, 'image/png')
        image.pop('uri', None)
        replaced += 1

    if not replaced:
        return None, 'none of the images in the file matched a texture this run encoded', 0

    header['bufferViews'] = new_views
    buffers[0]['byteLength'] = len(new_bin)
    buffers[0].pop('uri', None)
    header['buffers'] = buffers
    return bytes(new_bin), '', replaced


def rewrite_glb(source: str, output: str, mapping: Mapping) -> Tuple[bool, str]:
    """Swap the images inside a .glb for the bytes in mapping, keeping the geometry."""
    reason = ''
    with open(source, 'rb') as handle:
        blob = handle.read()
    header, bin_bytes, why = _glb_chunks(blob)
    if header is None:
        return False, why
    reason = _refusable(header)
    if reason:
        return False, reason

    new_bin, why, replaced = _repack(header, bin_bytes, mapping)
    if new_bin is None:
        return False, why

    before = len(blob)
    with open(output, 'wb') as handle:
        payload = _glb_bytes(header, new_bin)
        handle.write(payload)
    delta = len(payload) - before
    return True, (f'{replaced} image(s) replaced inside the file; geometry copied as is; '
                  f'file {before:,} -> {len(payload):,} bytes ({delta:+,})')


def _ensure_sidecar(directory: str, texture: EncodedTexture) -> str:
    """Make sure an encoded texture exists beside the model, and return its name."""
    target = os.path.join(directory, texture.name)
    if not os.path.isfile(target):
        with open(target, 'wb') as handle:
            handle.write(texture.data)
    return texture.name


def rewrite_gltf(source: str, output: str, mapping: Mapping) -> Tuple[bool, str]:
    """Point a .gltf at the optimized images, keeping every other reference working.

    Images this run did not touch are copied into the output folder (or kept as views of
    the .bin that is copied with it), because a .gltf that loads nothing after being moved
    is a broken asset, not an optimized one.
    """
    try:
        with open(source, 'r', encoding='utf-8') as handle:
            header = json.load(handle)
    except (OSError, ValueError) as error:
        return False, f'the .gltf could not be read ({type(error).__name__})'

    reason = _refusable(header)
    if reason:
        return False, reason

    base = os.path.dirname(os.path.abspath(source))
    out_dir = os.path.dirname(os.path.abspath(output)) or '.'
    os.makedirs(out_dir, exist_ok=True)

    buffers = {}
    for index, buffer in enumerate(header.get('buffers') or []):
        uri = buffer.get('uri')
        if not uri:
            continue
        origin = os.path.join(base, uri)
        if os.path.isfile(origin):
            _copy_sidecar(origin, os.path.join(out_dir, os.path.basename(uri)))
            buffer['uri'] = os.path.basename(uri)
            with open(origin, 'rb') as handle:
                buffers[index] = handle.read()

    views = header.get('bufferViews') or []
    replaced, kept = 0, 0
    for index, image in enumerate(header.get('images') or []):
        data = None
        view_index = image.get('bufferView')
        if view_index is not None and 0 <= view_index < len(views):
            view = views[view_index]
            start = int(view.get('byteOffset', 0))
            source_bytes = buffers.get(view.get('buffer', 0), b'')
            data = source_bytes[start:start + int(view.get('byteLength', 0))]
        elif image.get('uri'):
            candidate = os.path.join(base, image['uri'])
            if os.path.isfile(candidate):
                with open(candidate, 'rb') as handle:
                    data = handle.read()
        if data is None:
            continue

        found = mapping.get(key_of_bytes(data) or '')
        if found is None:
            if image.get('uri'):
                origin = os.path.join(base, image['uri'])
                if os.path.isfile(origin):
                    _copy_sidecar(origin, os.path.join(out_dir, os.path.basename(image['uri'])))
                    image['uri'] = os.path.basename(image['uri'])
                    kept += 1
            continue

        name = _ensure_sidecar(out_dir, found)
        image['uri'] = name
        image.pop('bufferView', None)
        # A .png or .jpg sidecar must not carry a mimeType; a .webp one must.
        if found.fmt == 'WEBP':
            image['mimeType'] = MIME_FOR_FORMAT['WEBP']
        else:
            image.pop('mimeType', None)
        replaced += 1

    if not replaced:
        return False, 'none of the images in the file matched a texture this run encoded'

    with open(output, 'w', encoding='utf-8') as handle:
        json.dump(header, handle, separators=(',', ':'))
    return True, (f'{replaced} image(s) replaced; {kept} sidecar(s) copied so the '
                  f'untouched textures still load')


def rewrite_mtl(directory: str, mapping: Mapping) -> Tuple[bool, str]:
    """Repoint every texture an exported .mtl references at its optimized file.

    The .mtl and its images are files this app just wrote in `directory`, so the copies it
    made are replaced rather than left beside them - and a reference that resolves outside
    the directory is never touched, so an asset folder that shares .png files by name
    cannot be damaged from here.
    """
    written, touched, skipped = 0, [], 0
    for mtl_path in glob.glob(os.path.join(directory, '*.mtl')):
        folder = os.path.abspath(os.path.dirname(mtl_path))
        with open(mtl_path, 'r', encoding='utf-8', errors='replace') as handle:
            lines = handle.read().splitlines()
        changed = False
        for position, line in enumerate(lines):
            token = line.split(None, 1)
            if len(token) != 2 or token[0] not in _MTL_MAPS:
                continue
            reference = token[1].strip().strip('"')
            target = os.path.abspath(os.path.join(folder, reference))
            if not (target.startswith(folder + os.sep) and os.path.isfile(target)):
                skipped += 1
                continue
            try:
                with open(target, 'rb') as handle:
                    data = handle.read()
            except OSError:
                continue
            found = mapping.get(key_of_bytes(data) or '')
            if found is None:
                continue
            name = _ensure_sidecar(folder, found)
            lines[position] = f'{token[0]} {name}'
            if os.path.abspath(os.path.join(folder, name)) != target:
                os.remove(target)
            changed = True
            written += 1
            touched.append(name)
        if changed:
            with open(mtl_path, 'w', encoding='utf-8') as handle:
                handle.write('\n'.join(lines) + '\n')

    if not written:
        return False, 'the material file referenced no texture this run encoded'
    note = f'{written} reference(s) repointed to {", ".join(sorted(set(touched)))}'
    if skipped:
        note += f'; {skipped} reference(s) pointed outside the folder and were left alone'
    return True, note


def _copy_sidecar(origin: str, destination: str) -> None:
    """Copy one sidecar file, and never onto itself."""
    if os.path.abspath(origin) == os.path.abspath(destination):
        return
    with open(origin, 'rb') as source_handle, open(destination, 'wb') as target_handle:
        target_handle.write(source_handle.read())
