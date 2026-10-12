#!/usr/bin/env python3
"""Turn ``packaging/icons/guzzionboard-source.png`` into the icon files each
platform needs.

Run once (the outputs are committed, so nobody needs Pillow to build the app):

    python3 packaging/make_icons.py

Produces, next to the source image:

    guzzionboard.ico    Windows: exe, installer, shortcuts (16-256 px)
    guzzionboard.icns   macOS: .app bundle
    guzzionboard.png    Linux/GTK/Qt windows, .desktop entries
    guzzionboard-512.png

The source is a square badge on a plain background; this script finds the
badge, crops to it, and masks the corners so the icon is transparent outside
its rounded square rather than a white block on a dark taskbar.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:                       # pragma: no cover - build-time only
    raise SystemExit(
        "Pillow is needed only to regenerate icons: pip install pillow"
    )

HERE = Path(__file__).resolve().parent
ICONS = HERE / "icons"
SOURCE = ICONS / "guzzionboard-source.png"

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = {          # chunk type: pixels
    "ic11": 32, "ic12": 64, "ic07": 128, "ic08": 256,
    "ic13": 256, "ic09": 512, "ic14": 512, "ic10": 1024,
}
#: How round the badge corners are, as a fraction of the side.
CORNER = 0.22


def badge(image: Image.Image) -> Image.Image:
    """Crop to the badge and give it transparent rounded corners."""
    rgba = image.convert("RGBA")
    grey = rgba.convert("L")
    # The badge is dark on a light page: anything clearly darker than the
    # background belongs to it.
    mask = grey.point(lambda value: 255 if value < 200 else 0)
    box = mask.getbbox()
    if box:
        rgba = rgba.crop(box)
    side = min(rgba.size)
    left = (rgba.width - side) // 2
    top = (rgba.height - side) // 2
    rgba = rgba.crop((left, top, left + side, top + side))

    rounded = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    corner_mask = Image.new("L", rgba.size, 0)
    ImageDraw.Draw(corner_mask).rounded_rectangle(
        (0, 0, rgba.size[0] - 1, rgba.size[1] - 1),
        radius=int(side * CORNER),
        fill=255,
    )
    rounded.paste(rgba, (0, 0), corner_mask)
    return rounded


def write_icns(icon: Image.Image, path: Path) -> None:
    """A minimal PNG-based .icns (what macOS 10.7+ reads)."""
    import struct

    chunks = b""
    for kind, size in ICNS_SIZES.items():
        import io

        buffer = io.BytesIO()
        scaled = icon.resize((size, size), Image.LANCZOS)
        # Flat colours: paletting the small sizes keeps the bundle small
        # without a visible difference at icon scale.
        if size <= 256:
            scaled = scaled.quantize(colors=64, method=Image.FASTOCTREE)
        scaled.save(buffer, format="PNG", optimize=True)
        payload = buffer.getvalue()
        chunks += kind.encode("ascii") + struct.pack(">I", len(payload) + 8) + payload
    path.write_bytes(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(
            f"no master image at {SOURCE} (a square PNG, 512px or larger)"
        )
    icon = badge(Image.open(SOURCE))
    base = icon.resize((1024, 1024), Image.LANCZOS)

    ico = ICONS / "guzzionboard.ico"
    base.save(ico, sizes=[(size, size) for size in ICO_SIZES])
    base.resize((256, 256), Image.LANCZOS).save(ICONS / "guzzionboard.png", optimize=True)
    base.resize((512, 512), Image.LANCZOS).save(
        ICONS / "guzzionboard-512.png", optimize=True)
    write_icns(base, ICONS / "guzzionboard.icns")

    for path in sorted(ICONS.glob("guzzionboard*")):
        print(f"  {path.name:26} {path.stat().st_size:>8} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
