"""Regenerate Mandible's icon files from mandible/branding.py.

Writes:
  Mandible.ico                         app/exe/installer icon (16-64 px as 32-bit BMP, 256 px as PNG)
  assets/icon/mandible-tile.svg        app icon master (graphite tile)
  assets/icon/mandible-mark.svg        bare mark, graphite (for light backgrounds)
  assets/icon/mandible-mark-white.svg  bare mark, off-white (for dark backgrounds)
  assets/icon/png/*.png                raster exports for docs, stores and the website

Run after changing the geometry or colours in mandible/branding.py:
    python tools/make_icons.py
"""
from __future__ import annotations

import os
import pathlib
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from mandible import branding as B  # noqa: E402

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
TILE_PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def dib_bytes(img: QImage) -> bytes:
    """32-bit BMP icon entry: BITMAPINFOHEADER, bottom-up BGRA pixels, empty AND mask."""
    img = img.convertToFormat(QImage.Format_ARGB32)  # straight alpha, BGRA byte order in memory
    w, h = img.width(), img.height()
    rows = [bytes(img.constScanLine(y))[: w * 4] for y in range(h)]
    pixels = b"".join(reversed(rows))
    mask_row = ((w + 31) // 32) * 4
    mask = b"\x00" * (mask_row * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + mask


def write_ico(path: pathlib.Path) -> None:
    entries = []
    for px in ICO_SIZES:
        img = B.render_tile(px)
        entries.append((px, png_bytes(img) if px >= 256 else dib_bytes(img)))
    offset = 6 + 16 * len(entries)
    out = struct.pack("<HHH", 0, 1, len(entries))
    blobs = b""
    for px, blob in entries:
        dim = 0 if px >= 256 else px
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    path.write_bytes(out + blobs)


def svg_tile() -> str:
    s, ox, oy = B._glyph_transform(B.MARK, QRectF(0, 0, 64, 64), B.TILE_GLYPH, snap_px=False)
    r = 64 * B.TILE_RADIUS
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256">\n'
            f'  <title>Mandible</title>\n'
            f'  <rect width="64" height="64" rx="{r:g}" fill="{B.GRAPHITE}"/>\n'
            f'  <path transform="translate({ox:.4f} {oy:.4f}) scale({s:.5f})" fill="{B.OFF_WHITE}" d="{B.to_svg_d(B.MARK)}"/>\n'
            f'</svg>\n')


def svg_mark(color: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="4 4 56 56" width="256" height="256">\n'
            f'  <title>Mandible</title>\n'
            f'  <path fill="{color}" d="{B.to_svg_d(B.MARK)}"/>\n'
            f'</svg>\n')


def main() -> None:
    QGuiApplication.instance() or QGuiApplication([])
    icon_dir = ROOT / "assets" / "icon"
    png_dir = icon_dir / "png"
    png_dir.mkdir(parents=True, exist_ok=True)

    write_ico(ROOT / "Mandible.ico")
    (icon_dir / "mandible-tile.svg").write_text(svg_tile(), encoding="utf-8")
    (icon_dir / "mandible-mark.svg").write_text(svg_mark(B.GRAPHITE), encoding="utf-8")
    (icon_dir / "mandible-mark-white.svg").write_text(svg_mark(B.OFF_WHITE), encoding="utf-8")
    for px in TILE_PNG_SIZES:
        B.render_tile(px).save(str(png_dir / f"mandible-tile-{px}.png"))
    B.render_mark(512, B.GRAPHITE).save(str(png_dir / "mandible-mark-512.png"))
    B.render_mark(512, B.OFF_WHITE).save(str(png_dir / "mandible-mark-white-512.png"))
    print(f"Wrote Mandible.ico and {len(list(icon_dir.rglob('*.*')))} files in assets/icon")


if __name__ == "__main__":
    main()
