"""Write a portable PNG mip chain and read its manifest back."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image


@dataclass(frozen=True)
class MipmapResult:
    success: bool
    message: str
    manifest_path: Optional[str] = None


class TextureMipmaps:
    @staticmethod
    def generate(source_path: str, output_dir: str, prefix: str = '') -> MipmapResult:
        if not os.path.isfile(source_path):
            return MipmapResult(False, f'texture source does not exist: {source_path}')
        try:
            with Image.open(source_path) as opened:
                image = opened.convert('RGBA')
            root = Path(output_dir)
            root.mkdir(parents=True, exist_ok=True)
            stem = prefix or Path(source_path).stem
            levels, current, index = [], image, 0
            while True:
                path = root / f'{stem}_mip{index}.png'
                current.save(path, 'PNG')
                levels.append({'file': path.name, 'width': current.width, 'height': current.height})
                if current.width == 1 and current.height == 1:
                    break
                next_size = (max(1, current.width // 2), max(1, current.height // 2))
                next_image = current.resize(next_size, Image.Resampling.LANCZOS)
                if current is not image:
                    current.close()
                current = next_image
                index += 1
            if current is not image:
                current.close()
            image.close()
            manifest = root / f'{stem}_mipmaps.json'
            manifest.write_text(json.dumps({'source': os.path.basename(source_path), 'levels': levels}, indent=2),
                                encoding='utf-8')
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            for level in saved.get('levels', []):
                with Image.open(root / level['file']) as written:
                    if written.size != (level['width'], level['height']):
                        return MipmapResult(False, f'{level["file"]} did not read back at its recorded size')
            return MipmapResult(True, f'wrote and read back {len(levels)} PNG mip levels', str(manifest))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return MipmapResult(False, f'could not generate mipmaps: {error}')
