"""Image normalization so Anthropic API accepts what Telegram delivers.

Anthropic's vision endpoint rejects:
- files over ~5 MB
- dimensions larger than ~8000 px on either side
- non-PNG/JPEG/GIF/WebP formats (HEIC from iPhones sometimes slips through)

We normalize every inbound image to JPEG, max 1568 px long edge, <= 4 MB.
1568 is Anthropic's recommended max before they downscale server-side —
doing it here keeps the upload cheap and the decode deterministic.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_EDGE = 1568
_MAX_BYTES = 4 * 1024 * 1024  # 4 MB — leave headroom under Anthropic's 5 MB cap


def normalize(path: Path) -> Path:
    """Return a path to an image small enough for Anthropic. May be the input
    itself if it's already fine, or a new sibling file with the same stem.

    Never raises — on any failure, returns the original path and logs.
    """
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        return path

    try:
        size = path.stat().st_size
    except OSError:
        return path

    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            needs_resize = max(img.size) > _MAX_EDGE
            needs_reencode = (
                img.format not in ("JPEG", "PNG", "GIF", "WEBP")
                or size > _MAX_BYTES
            )
            if not needs_resize and not needs_reencode:
                return path

            if needs_resize:
                img.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.LANCZOS)

            out = path.with_name(f"{path.stem}_norm.jpg")
            rgb = img.convert("RGB") if img.mode != "RGB" else img
            quality = 85
            while quality >= 50:
                rgb.save(out, format="JPEG", quality=quality, optimize=True)
                if out.stat().st_size <= _MAX_BYTES:
                    break
                quality -= 10
            logger.info(
                "Normalized %s (%.1f MB) -> %s (%.1f MB, q=%d)",
                path.name, size / 1024 / 1024,
                out.name, out.stat().st_size / 1024 / 1024, quality,
            )
            return out
    except (OSError, UnidentifiedImageError, ValueError) as e:
        logger.warning("Image normalize failed for %s: %s", path, e)
        return path
