"""Deterministic texture atlas writer with a JSON sidecar read-back."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image


@dataclass(frozen=True)
class AtlasResult:
    success: bool
    message: str
    atlas_path: Optional[str] = None
    manifest_path: Optional[str] = None


class TextureAtlas:
    """Pack equally sized raster sprites into a transparent PNG grid."""

    @staticmethod
    def build(output_path: str, source_paths: Iterable[str], columns: int = 0) -> AtlasResult:
        paths = [str(path) for path in source_paths if path]
        if not paths:
            return AtlasResult(False, 'choose at least one image for the atlas')
        if columns < 0:
            return AtlasResult(False, 'columns cannot be negative')
        images = []
        try:
            for source in paths:
                path = Path(source)
                if not path.is_file():
                    return AtlasResult(False, f'atlas source does not exist: {source}')
                with Image.open(path) as opened:
                    images.append((path.name, opened.convert('RGBA')))
            width, height = images[0][1].size
            if width < 1 or height < 1:
                return AtlasResult(False, 'atlas source has no pixels')
            if any(image.size != (width, height) for _, image in images):
                return AtlasResult(False, 'all atlas images must have the same dimensions')
            columns = columns or int(math.ceil(math.sqrt(len(images))))
            columns = min(columns, len(images))
            rows = int(math.ceil(len(images) / columns))
            atlas = Image.new('RGBA', (columns * width, rows * height), (0, 0, 0, 0))
            sprites = {}
            for index, (name, image) in enumerate(images):
                column, row = index % columns, index // columns
                left, top = column * width, row * height
                atlas.alpha_composite(image, (left, top))
                sprites[name] = {'x': left, 'y': top, 'width': width, 'height': height,
                                 'u0': left / atlas.width, 'v0': top / atlas.height,
                                 'u1': (left + width) / atlas.width, 'v1': (top + height) / atlas.height}
            target = Path(output_path)
            if target.suffix.lower() != '.png':
                target = target.with_suffix('.png')
            target.parent.mkdir(parents=True, exist_ok=True)
            atlas.save(target, 'PNG')
            manifest = target.with_suffix('.json')
            manifest.write_text(json.dumps({'image': target.name, 'width': atlas.width,
                                            'height': atlas.height, 'sprites': sprites}, indent=2),
                                encoding='utf-8')
            with Image.open(target) as written:
                if written.size != atlas.size or written.mode != 'RGBA':
                    return AtlasResult(False, 'written atlas could not be read back as RGBA')
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            if saved.get('sprites') != sprites:
                return AtlasResult(False, 'written atlas manifest did not read back')
            return AtlasResult(True, f'packed {len(images)} image(s) into {target.name}; atlas and JSON read back',
                               str(target), str(manifest))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return AtlasResult(False, f'could not build texture atlas: {error}')
        finally:
            for _, image in images:
                image.close()
