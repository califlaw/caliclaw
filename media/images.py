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


async def describe_with_haiku(path: Path, caption: str = "") -> str:
    """Run an isolated `claude -p --model haiku` to describe an image as text.

    Returns the description (also persisted to <path>.desc.txt for the main
    agent to reference). Empty string on any failure — caller falls back to
    the raw-file path flow.

    Runs in its own one-shot Claude session — no --session-id — so a failure
    here can never poison the main chat's Claude session. If haiku itself
    trips on the image (unlikely: v0.4.13 normalize already produces a safe
    JPEG), we swallow the error and return "".
    """
    from core.agent import AgentConfig, AgentProcess

    prompt = (
        f"Read the image at: {path}\n\n"
        f"User caption: {caption or '(none)'}\n\n"
        "Describe it comprehensively in plain text: subjects, layout, any "
        "visible text (verbatim), colors, mood, distinctive details, and "
        "anything that might matter to a follow-up question. Be specific "
        "enough that a reader who can't see the image could answer most "
        "questions about it. Output plain prose — no markdown, no JSON."
    )

    config = AgentConfig(
        name="image-describer",
        model="haiku",
        system_prompt=(
            "You describe images as text so another agent can reason about "
            "them without needing vision. Be factual and thorough."
        ),
        timeout_seconds=60,
        idle_timeout_seconds=60,
        working_dir=path.parent,
    )

    try:
        proc = AgentProcess(config)
        result = await proc.run(prompt)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Haiku describe failed for %s: %s", path, e)
        return ""

    text = (result.text or "").strip()
    if not text or result.error:
        logger.warning(
            "Haiku describe returned no text for %s (error=%s)",
            path, result.error,
        )
        return ""

    try:
        desc_path = path.with_name(path.name + ".desc.txt")
        desc_path.write_text(text, encoding="utf-8")
    except OSError:
        pass  # non-fatal — description still returned

    return text
