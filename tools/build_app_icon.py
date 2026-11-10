"""Build reproducible SRC Learning PNG, Windows ICO, and macOS ICNS icons."""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageChops, ImageFilter
from PyQt5.QtGui import QGuiApplication

from app.ui.brand_icon import render_brand_icon

DESTINATION = Path(__file__).resolve().parents[1] / "app" / "resources" / "brand"
PNG_SIZES = (32, 64, 128, 256, 512, 1024)
ICONSET_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def build_mark_masks(destination: Path) -> None:
    """Retain the referenced SRC silhouette and derive a thin glass rim."""
    with Image.open(destination / "src-logo-source.png") as source:
        alpha = source.convert("RGBA").getchannel("A")
    alpha = alpha.point(lambda value: 0 if value < 8 else value)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("The SRC source logo has no visible pixels")
    trimmed = alpha.crop(bounds)
    width = 420
    height = round(width * trimmed.height / trimmed.width)
    resized = trimmed.resize((width, height), Image.Resampling.LANCZOS)
    mark = Image.new("L", (512, 512), 0)
    mark.paste(resized, ((512 - width) // 2, (512 - height) // 2))
    interior = mark.filter(ImageFilter.MinFilter(7))
    rim = ImageChops.subtract(mark, interior)
    glow = mark.filter(ImageFilter.MaxFilter(19)).filter(ImageFilter.GaussianBlur(11))
    small = mark.filter(ImageFilter.MaxFilter(13))
    for name, channel in (
        ("src-logo-mask.png", mark),
        ("src-logo-interior.png", interior),
        ("src-logo-rim.png", rim),
        ("src-logo-glow.png", glow),
        ("src-logo-small.png", small),
    ):
        image = Image.new("RGBA", (512, 512), (255, 255, 255, 0))
        image.putalpha(channel)
        image.save(destination / name)


def build_icons(destination: Path = DESTINATION) -> list[Path]:
    application = QGuiApplication.instance() or QGuiApplication([])
    destination.mkdir(parents=True, exist_ok=True)
    build_mark_masks(destination)
    outputs: list[Path] = []
    for size in PNG_SIZES:
        target = destination / f"src-learning-{size}.png"
        if not render_brand_icon(size).save(str(target), "PNG"):
            raise OSError(f"Unable to write {target}")
        outputs.append(target)

    with Image.open(destination / "src-learning-1024.png") as original:
        ico = destination / "src-learning.ico"
        ico_sizes = (16, 32, 48, 64, 128, 256)
        with tempfile.TemporaryDirectory(prefix="src-learning-ico-") as temp:
            frames = []
            for size in ico_sizes:
                path = destination / f"src-learning-{size}.png"
                if size in (16, 48):
                    path = Path(temp) / f"src-learning-{size}.png"
                    render_brand_icon(size).save(str(path), "PNG")
                with Image.open(path) as frame:
                    frames.append(frame.convert("RGBA"))
            original.save(
                ico, format="ICO", sizes=[(size, size) for size in ico_sizes],
                append_images=frames,
            )
        outputs.append(ico)

    if platform.system() == "Darwin":
        with tempfile.TemporaryDirectory(prefix="src-learning-icon-") as temp:
            iconset = Path(temp) / "src-learning.iconset"
            iconset.mkdir()
            for size in ICONSET_SIZES:
                if size == 16:
                    names = ("icon_16x16.png",)
                elif size == 1024:
                    names = ("icon_512x512@2x.png",)
                else:
                    names = (f"icon_{size}x{size}.png", f"icon_{size // 2}x{size // 2}@2x.png")
                image = render_brand_icon(size)
                for name in names:
                    image.save(str(iconset / name), "PNG")
            icns = destination / "src-learning.icns"
            subprocess.run(["iconutil", "-c", "icns", "-o", str(icns), str(iconset)], check=True)
            outputs.append(icns)
    del application
    return outputs


if __name__ == "__main__":
    for path in build_icons():
        print(path)
