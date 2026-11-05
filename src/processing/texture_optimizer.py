"""Re-encodes the textures a model carries, and measures what that saved.

The Advanced sub-tab of Pre-Processing had Optimize Textures, a Quality slider and a
Convert-to picker with nothing behind them: the controls were read by the preview dialog,
printed as "Yes" and went nowhere. This module is that backend.

Every figure a report quotes is measured from bytes written to disk. `bytes_from` is the
same pixels pushed through the same encoder at its default settings, because a decoded
image held in memory has no file size of its own - so the report names that baseline
instead of quoting a number the source file never contained.
"""

import io
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, features

from .format_converter import FormatConverter
from .texture_rewriter import (EncodedTexture, pixels_key, rewrite_glb, rewrite_gltf,
                                rewrite_mtl)

# The slots trimesh's two material classes expose textures through. PBRMaterial names
# them after glTF; SimpleMaterial calls the one it has `image`. Both are read here, so an
# .obj with a hand-written .mtl gets the same treatment as a .glb.
TEXTURE_SLOTS = ('baseColorTexture', 'metallicRoughnessTexture', 'normalTexture',
                 'emissiveTexture', 'occlusionTexture', 'image')

# Re-encoding these as JPEG or WEBP loses values a shader reads as numbers, not as
# colour, so the report says which textures were data textures.
DATA_SLOTS = ('normalTexture', 'metallicRoughnessTexture', 'occlusionTexture')

FORMAT_CHOICES = ('PNG', 'JPEG', 'WEBP', 'Original')

# What the file an engine looks for is actually called: a JPEG texture ships as .jpg, not
# as .jpeg, and a Pillow format name is not a file extension.
_EXTENSION_FOR_FORMAT = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}


def available_formats() -> Dict[str, Optional[str]]:
    """Each choice and the reason it cannot be used here, or None if it can.

    Asking the installed Pillow build is what makes "Convert to: WEBP" an honest offer.
    A build without libwebp used to accept the choice and fail inside save().
    """
    needs = {'PNG': None, 'JPEG': 'jpg', 'WEBP': 'webp', 'Original': None}
    out: Dict[str, Optional[str]] = {}
    for choice, capability in needs.items():
        if capability is None or features.check(capability):
            out[choice] = None
        elif choice == 'Original':
            out[choice] = f'this Pillow build cannot read {capability} textures'
        else:
            out[choice] = f'this Pillow build has no {capability} support, ' \
                          f'so it cannot write {choice}'
    return out


def _safe_name(*parts: str) -> str:
    """A filename from material and slot names, with anything a path cannot hold removed."""
    text = '_'.join(p for p in parts if p)
    text = re.sub(r'[^A-Za-z0-9_.-]+', '_', text).strip('_')
    return (text or 'texture')[:80]


@dataclass
class TextureResult:
    """One texture: what it measured before, what was written, and what changed."""
    name: str
    part: str
    slot: str
    format_from: str
    format_to: str
    size_from: Tuple[int, int]
    size_to: Tuple[int, int]
    bytes_from: int
    bytes_to: int
    path: Optional[str]
    note: str = ''

    def line(self) -> str:
        saving = self.bytes_from - self.bytes_to
        word = 'saved' if saving >= 0 else 'grew'
        text = (f'{self.part} / {self.slot}: {self.size_from[0]}x{self.size_from[1]} '
                f'{self.format_from} {self.bytes_from:,} -> {self.format_to} '
                f'{self.bytes_to:,} bytes ({word} {abs(saving):,})')
        if self.size_to != self.size_from:
            text += f', written at {self.size_to[0]}x{self.size_to[1]}'
        if self.note:
            text += f' - {self.note}'
        return text


@dataclass
class TextureReport:
    results: List[TextureResult] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    model_output: Optional[str] = None
    model_note: str = ''
    source_bytes: int = 0
    model_bytes: int = 0
    stopped: bool = False
    target: str = 'Original'
    quality: int = 80
    baseline_note: str = ('before-size is the same pixels re-encoded by this Pillow '
                          'build at its defaults')

    @property
    def bytes_from(self) -> int:
        return sum(r.bytes_from for r in self.results)

    @property
    def bytes_to(self) -> int:
        return sum(r.bytes_to for r in self.results)

    def lines(self) -> List[str]:
        rows = [r.line() for r in self.results]
        rows += [f'skipped {name}: {why}' for name, why in self.skipped]
        rows += list(self.notes)
        rows += [f'failed: {why}' for why in self.errors]
        if self.model_output:
            rows.append(f'model written: {os.path.basename(self.model_output)}'
                        + (f' {self.model_note}' if self.model_note else ''))
            rows.append(f'model file: {self.source_bytes:,} -> {self.model_bytes:,} bytes '
                        f'({self.model_bytes - self.source_bytes:+,})')
        elif self.model_note:
            rows.append(f'model not written: {self.model_note}')
        return rows


class TextureOptimizer:
    """Writes a model's textures smaller and reports the byte counts it got."""

    def __init__(self, converter: Optional[FormatConverter] = None):
        self.converter = converter or FormatConverter()

    @staticmethod
    def find_textures(scene) -> List[Dict]:
        """Every texture the scene's materials hold, with the part and slot it came from.

        Deduplicated by pixels. A scene that points four parts at the same 2K map yields
        one entry, because encoding it four times would be a count of writes, not of work.
        """
        found: List[Dict] = []
        seen: Dict[Tuple, Dict] = {}
        for part_name, geometry in scene.geometry.items():
            material = getattr(getattr(geometry, 'visual', None), 'material', None)
            if material is None:
                continue
            for slot in TEXTURE_SLOTS:
                image = getattr(material, slot, None)
                if not isinstance(image, Image.Image):
                    continue
                key = (image.mode, image.size, image.tobytes())
                if key in seen:
                    seen[key]['shared_by'] += 1
                    seen[key]['parts'].append(part_name)
                    continue
                entry = {'part': part_name, 'parts': [part_name], 'slot': slot,
                         'image': image, 'material': material,
                         'name': getattr(material, 'name', None) or part_name,
                         'shared_by': 1}
                seen[key] = entry
                found.append(entry)
        return found

    def baseline_bytes(self, image: Image.Image) -> int:
        """What the same pixels cost through the encoder they arrived from, at defaults."""
        buffer = io.BytesIO()
        image.save(buffer, format=image.format or 'PNG')
        return len(buffer.getvalue())

    def _encode(self, image: Image.Image, target: str, quality: int,
                max_size: Optional[int], slot: str) -> Tuple[bytes, Image.Image, str, List[str]]:
        """Bytes to write, the image the model should now carry, format used, and notes."""
        notes: List[str] = []
        out = image
        fmt = target if target != 'Original' else (image.format or 'PNG')

        if max_size and max(out.size) > max_size:
            scale = max_size / max(out.size)
            new_size = (max(1, round(out.width * scale)), max(1, round(out.height * scale)))
            out = out.resize(new_size, Image.Resampling.LANCZOS)
            notes.append(f'rescaled {image.size[0]}x{image.size[1]} -> '
                         f'{new_size[0]}x{new_size[1]}')

        if fmt == 'JPEG':
            out, alpha_note = _flatten(out, 'JPEG')
            if alpha_note:
                notes.append(alpha_note)
        elif fmt == 'WEBP' and out.mode not in ('RGB', 'RGBA'):
            was_transparent = out.mode in ('RGBA', 'LA') or 'transparency' in out.info
            out = out.convert('RGBA' if was_transparent else 'RGB')
            notes.append('converted for WEBP')

        if fmt in ('JPEG', 'WEBP') and slot in DATA_SLOTS:
            notes.append(f'data texture re-encoded lossily at quality {quality}')

        buffer = io.BytesIO()
        if fmt == 'PNG':
            out.save(buffer, format='PNG', optimize=True)
        elif fmt == 'JPEG':
            out.save(buffer, format='JPEG', quality=quality, optimize=True)
        elif fmt == 'WEBP':
            out.save(buffer, format='WEBP', quality=quality, method=6)
        else:
            out.save(buffer, format=fmt)
        return buffer.getvalue(), out, fmt, notes

    def optimize(self, model_path: str, output_dir: str, quality: int = 80,
                 target: str = 'Original', max_size: Optional[int] = None,
                 write_model: bool = True,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None) -> TextureReport:
        """Rewrite this model's textures, and the model that points at them.

        A texture that cannot be encoded is a reported failure; the rest still get
        written and the model is saved with the textures that worked.
        """
        report = TextureReport(target=target, quality=quality)
        blocker = available_formats().get(target)
        if blocker:
            report.errors.append(f'{target}: {blocker}')
            return report

        # The value box takes whatever was typed; the JPEG and WEBP encoders take 1-100.
        # The request is applied at the nearest legal setting and said out loud in the
        # report, rather than the box refusing the number or the encoder raising inside a
        # worker thread - which would take the whole window down with it.
        applied = min(max(int(quality), 1), 100)
        if applied != quality:
            report.notes.append(f'quality {quality} applied as {applied}, '
                                f'the band the encoders accept')
        quality = applied
        report.quality = applied

        scene, carried = self.converter.read_scene(model_path)
        if scene is None:
            report.errors.append(f'cannot read {os.path.basename(model_path)}: {carried}')
            return report

        textures = self.find_textures(scene)
        if not textures:
            report.skipped.append((os.path.basename(model_path),
                                   'no material in this file references an image'))
            return report

        os.makedirs(output_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(model_path))[0]
        extension = os.path.splitext(model_path)[1].lower().lstrip('.')
        # A .glb holds its textures inside itself, so the encoded bytes go into the file
        # and nowhere else. .gltf and .obj name their textures by file, so those files are
        # what the model copy points at, and each is written once, beside the model.
        writes_sidecars = extension in ('gltf', 'obj')

        total = len(textures)
        used = set()
        # Pixels of the texture as it was, to the bytes as they will be shipped: the
        # rewriter matches a file's images by what they show, since nothing in a model
        # file remembers which material slot it was drawn from.
        mapping = {}
        for index, entry in enumerate(textures, start=1):
            if should_cancel is not None and should_cancel():
                report.stopped = True
                break
            image = entry['image']
            name = _safe_name(stem, entry['name'], entry['slot'])
            if name in used:
                # Two materials can be named the same thing; the second one has to land
                # somewhere else, or the first file is quietly overwritten.
                name = f'{name}_{index}'
            used.add(name)
            path = None
            try:
                before = self.baseline_bytes(image)
                data, replacement, written, notes = self._encode(
                    image, target, quality, max_size, entry['slot'])
                file_name = f'{name}.{_EXTENSION_FOR_FORMAT.get(written, written.lower())}'
                if writes_sidecars:
                    path = os.path.join(output_dir, file_name)
                    with open(path, 'wb') as handle:
                        handle.write(data)
            except Exception as error:
                report.errors.append(f'{name}: {type(error).__name__}: {str(error)[:120]}')
                continue

            notes = list(notes)
            if entry['shared_by'] > 1:
                notes.append(f'{entry["shared_by"]} parts shared these pixels')
            if path is None:
                notes.append(f'stored inside the .{extension} copy')
            setattr(entry['material'], entry['slot'], replacement)
            mapping[pixels_key(image)] = EncodedTexture(data=data, fmt=written,
                                                         name=file_name)
            report.results.append(TextureResult(
                name=name, part=entry['part'], slot=entry['slot'],
                format_from=image.format or 'PNG', format_to=written,
                size_from=image.size, size_to=replacement.size,
                bytes_from=before, bytes_to=len(data), path=path,
                note='; '.join(notes)))
            if progress is not None:
                progress(index, total, f'{name} written')

        if write_model and report.results and not report.stopped:
            report.model_output, report.model_note = self._write_model(
                scene, model_path, output_dir, mapping)
            report.source_bytes = os.path.getsize(model_path)
            if report.model_output:
                report.model_bytes = os.path.getsize(report.model_output)

        if not report.results and not report.errors and not report.stopped:
            report.skipped.append((os.path.basename(model_path), 'nothing was written'))
        return report

    def _write_model(self, scene, model_path: str, output_dir: str,
                     mapping: Dict[str, EncodedTexture]) -> Tuple[Optional[str], str]:
        """Save the model so the textures this run encoded are the ones it points at.

        A .glb and a .gltf are edited rather than re-exported: their mesh bytes are copied
        through and only the image entries change, which is the difference between a
        smaller asset and a re-export that quietly encodes every texture back to PNG.
        Anything else goes through the converter, and the note says what that cost.
        """
        output_file, note = self.converter.optimized_target(model_path, output_dir)
        extension = os.path.splitext(model_path)[1].lower().lstrip('.')
        folder = os.path.dirname(output_file) or '.'

        if extension in ('glb', 'gltf'):
            rewrite = rewrite_glb if extension == 'glb' else rewrite_gltf
            ok, message = rewrite(model_path, output_file, mapping)
            if ok:
                return output_file, f'{note} {message}'.strip()
            note = (f'{note} {message}, so the model was written from memory instead, '
                    f'which re-encodes its own textures')
        elif extension == 'obj':
            ok, message = self.converter.write_scene(scene, output_file)
            if not ok:
                return None, message
            rewrote, why = rewrite_mtl(folder, mapping)
            return output_file, f'{note} {why}'.strip()

        ok, message = self.converter.write_scene(scene, output_file)
        if not ok:
            return None, message
        return output_file, (f'{note} the optimized files are in the folder beside it, '
                             f'which is as far as a .{extension} can point')


def _flatten(image: Image.Image, fmt: str) -> Tuple[Image.Image, str]:
    """RGB for a format that has no alpha, compositing transparency over white."""
    if image.mode == 'RGB':
        return image, ''
    had_alpha = image.mode in ('RGBA', 'LA') or 'transparency' in image.info
    rgba = image.convert('RGBA')
    flat = Image.new('RGB', image.size, (255, 255, 255))
    flat.paste(rgba, (0, 0), rgba)
    if had_alpha:
        return flat, f'alpha dropped over white - {fmt} has no transparency'
    return flat, f'converted to RGB for {fmt}'
