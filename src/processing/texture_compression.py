"""KTX2/Basis capability gate; never relabel PNG output as compressed."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class TextureCompressionResult:
    success: bool
    message: str
    output_path: Optional[str] = None


class TextureCompressor:
    @staticmethod
    def encoder_path() -> Optional[str]:
        return shutil.which('basisu')

    @classmethod
    def compress_ktx2(cls, source_path: str, output_path: str,
                      generate_mipmaps: bool = True) -> TextureCompressionResult:
        if not os.path.isfile(source_path):
            return TextureCompressionResult(False, f'texture source does not exist: {source_path}')
        encoder = cls.encoder_path()
        if not encoder:
            return TextureCompressionResult(False,
                'KTX2/Basis compression is unavailable: install the Basis Universal basisu encoder and restart RenderFox')
        output = Path(output_path)
        if output.suffix.lower() != '.ktx2':
            return TextureCompressionResult(False, 'KTX2 output must use the .ktx2 extension')
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            command = [encoder, '-ktx2', '-file', source_path,
                       '-output_file', str(output), '-validate_output', '-quiet']
            if generate_mipmaps:
                command.append('-mipmap')
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=600, check=False)
        except subprocess.TimeoutExpired:
            return TextureCompressionResult(False, 'KTX2/Basis compression timed out after 10 minutes')
        except OSError as error:
            return TextureCompressionResult(False, f'Could not start the Basis Universal encoder: {error}')
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or 'the encoder gave no details').strip()
            return TextureCompressionResult(False, f'KTX2/Basis compression failed: {detail}')
        if not output.is_file() or output.stat().st_size == 0:
            return TextureCompressionResult(False,
                'KTX2/Basis encoder reported success but did not write a readable .ktx2 file')
        return TextureCompressionResult(True,
            f'Wrote verified KTX2/Basis texture: {output.name}', str(output))
