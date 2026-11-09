"""Meshopt geometry compression, with an honest capability gate."""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class GeometryCompressionResult:
    success: bool
    message: str
    output_path: Optional[str] = None


def _gltf_document(path: str):
    raw = Path(path).read_bytes()
    if raw[:4] == b'glTF' and len(raw) >= 20:
        length = int.from_bytes(raw[12:16], 'little')
        return json.loads(raw[20:20 + length].decode('utf-8'))
    return json.loads(raw.decode('utf-8'))


class GeometryCompressor:
    """Call gltfpack when present; never claim an ordinary GLB is compressed."""

    @staticmethod
    def encoder_path() -> Optional[str]:
        return shutil.which('gltfpack')

    @classmethod
    def compress_meshopt(cls, input_path: str, output_path: str) -> GeometryCompressionResult:
        if Path(input_path).suffix.lower() not in ('.gltf', '.glb'):
            return GeometryCompressionResult(False, 'Meshopt compression accepts .gltf or .glb input only')
        if not os.path.isfile(input_path):
            return GeometryCompressionResult(False, f'geometry source does not exist: {input_path}')
        encoder = cls.encoder_path()
        if not encoder:
            return GeometryCompressionResult(False,
                'Meshopt geometry compression is unavailable: install meshoptimizer gltfpack and restart RenderFox')
        target = str(Path(output_path).with_suffix('.glb'))
        os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
        run = subprocess.run([encoder, '-i', input_path, '-o', target, '-cc'],
                             capture_output=True, text=True, timeout=120)
        if run.returncode or not os.path.isfile(target) or not os.path.getsize(target):
            detail = (run.stderr or run.stdout or f'exit code {run.returncode}').strip()
            return GeometryCompressionResult(False, f'gltfpack did not write a compressed GLB: {detail}')
        try:
            document = _gltf_document(target)
        except (OSError, ValueError, UnicodeDecodeError) as error:
            return GeometryCompressionResult(False, f'compressed output could not be read back: {error}')
        extensions = set(document.get('extensionsUsed') or [])
        if 'EXT_meshopt_compression' not in extensions:
            return GeometryCompressionResult(False,
                'gltfpack wrote a GLB without EXT_meshopt_compression; it is not reported as compressed')
        return GeometryCompressionResult(True, f'Meshopt-compressed GLB written and extension read back: {Path(target).name}', target)
