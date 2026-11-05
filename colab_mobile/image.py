"""Question image preparation shared by the Colab presentation layer."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.config import DEFAULT_MASK_REGION


def question_image(path: Path) -> bytes:
    """Hide the answer strip using the desktop viewer's default mask."""
    with Image.open(path) as original:
        image = original.convert("RGB")
        bottom = (
            max(1, min(image.height, round(image.height * DEFAULT_MASK_REGION[1])))
            if DEFAULT_MASK_REGION[3] > 0 else image.height
        )
        output = io.BytesIO()
        image.crop((0, 0, image.width, bottom)).save(output, format="PNG")
        return output.getvalue()
