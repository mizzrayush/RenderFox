"""KTX2/Basis capability gate; never relabel PNG output as compressed."""

import os
import shutil
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
    def compress_ktx2(cls, source_path: str, output_path: str) -> TextureCompressionResult:
        if not os.path.isfile(source_path):
            return TextureCompressionResult(False, f'texture source does not exist: {source_path}')
        encoder = cls.encoder_path()
        if not encoder:
            return TextureCompressionResult(False,
                'KTX2/Basis compression is unavailable: install the Basis Universal basisu encoder and restart RenderFox')
        # Invocation is intentionally deferred until a supported bundled encoder is
        # selected; different basisu releases use incompatible KTX2 flags.
        return TextureCompressionResult(False,
            'KTX2/Basis encoder was found but this RenderFox build has no verified invocation for it')
