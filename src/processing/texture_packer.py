"""Texture channel packing with byte-level verification.

Game engines commonly expect masks such as an ORM map (occlusion in red,
roughness in green, metallic in blue).  This module writes that map without
pretending differently-sized source images line up: callers must provide maps
with identical dimensions or receive a named refusal.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image


@dataclass(frozen=True)
class ChannelPackResult:
    success: bool
    message: str
    output_path: Optional[str] = None
    size: Optional[Tuple[int, int]] = None


class ChannelPacker:
    """Combine single-channel image data into one RGBA PNG."""

    CHANNELS = ("red", "green", "blue", "alpha")
    DEFAULTS = {"red": 0, "green": 0, "blue": 0, "alpha": 255}

    @classmethod
    def pack(cls, output_path: str, channels: Dict[str, Optional[str]]) -> ChannelPackResult:
        """Write ``channels`` to RGBA PNG and read every requested byte back.

        ``channels`` maps red/green/blue/alpha to an image path or ``None``.
        The first band of each source is used, which makes greyscale masks and
        colour masks equally unambiguous.  At least one source is required.
        """
        unknown = set(channels) - set(cls.CHANNELS)
        if unknown:
            return ChannelPackResult(False, f"unknown output channel(s): {', '.join(sorted(unknown))}")
        supplied = {name: path for name, path in channels.items() if path}
        if not supplied:
            return ChannelPackResult(False, "choose at least one source mask to pack")

        images = {}
        size = None
        try:
            for name, source in supplied.items():
                path = Path(source)
                if not path.is_file():
                    return ChannelPackResult(False, f"{name} source does not exist: {source}")
                with Image.open(path) as opened:
                    image = opened.convert("L")
                if size is None:
                    size = image.size
                elif image.size != size:
                    return ChannelPackResult(False,
                                             f"{name} is {image.size[0]}x{image.size[1]}, expected "
                                             f"{size[0]}x{size[1]}; resize masks before packing")
                images[name] = image

            bands = [images.get(name, Image.new("L", size, cls.DEFAULTS[name]))
                     for name in cls.CHANNELS]
            packed = Image.merge("RGBA", bands)
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            packed.save(target, "PNG")
            packed.close()

            with Image.open(target) as written:
                if written.mode != "RGBA" or written.size != size:
                    return ChannelPackResult(False, "written PNG could not be read back as RGBA")
                for index, name in enumerate(cls.CHANNELS):
                    if name in images and written.getchannel(index).getextrema() != images[name].getextrema():
                        return ChannelPackResult(False, f"written PNG changed the {name} mask")
            return ChannelPackResult(True, f"packed {len(supplied)} mask(s) into {target.name}; PNG read back",
                                     str(target), size)
        except (OSError, ValueError) as error:
            return ChannelPackResult(False, f"could not pack texture channels: {error}")
        finally:
            for image in images.values():
                image.close()
