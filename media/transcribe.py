from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from core.config import get_settings

logger = logging.getLogger(__name__)


async def transcribe_audio(
    audio_path: str,
    model_path: Optional[str] = None,
    language: str = "ru",
) -> Optional[str]:
    """Transcribe audio file. Tries whisper-cpp first, then claude as fallback."""
    audio = Path(audio_path)
    if not audio.exists():
        logger.error("Audio file not found: %s", audio_path)
        return None

    # Convert to WAV first (needed for whisper-cpp)
    wav_path = audio.with_suffix(".wav")
    if audio.suffix != ".wav":
        if not shutil.which("ffmpeg"):
            logger.error("ffmpeg not found. Required for audio conversion.")
            return None

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(audio),
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(wav_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("ffmpeg conversion failed: %s", stderr.decode())
            return None

    # Try whisper-cpp
    result = await _try_whisper_cpp(wav_path, model_path, language)

    # Fallback: use claude to describe the audio context
    if result is None:
        result = await _try_claude_transcribe(audio_path)

    # Cleanup temp wav
    if audio.suffix != ".wav" and wav_path.exists():
        wav_path.unlink()

    return result


async def _try_whisper_cpp(
    wav_path: Path, model_path: Optional[str], language: str
) -> Optional[str]:
    """Try whisper-cpp binary."""
    settings = get_settings()
    whisper_bin = settings.whisper_cpp_path

    # Find whisper binary
    if not shutil.which(whisper_bin) and not Path(whisper_bin).exists():
        for fallback in ("whisper-cpp", "whisper", "main", "/usr/local/bin/whisper-cpp"):
            if shutil.which(fallback):
                whisper_bin = fallback
                break
        else:
            logger.info("whisper-cpp not found, will use fallback.")
            return None

    model = model_path or settings.whisper_model_path
    if not Path(model).exists():
        logger.info("Whisper model not found at %s, will use fallback.", model)
        return None

    cmd = [
        whisper_bin,
        "-m", model,
        "-l", language,
        "-f", str(wav_path),
        "--no-timestamps",
        "-nt",
    ]

    logger.info("Running whisper-cpp: %s", " ".join(cmd[:4]))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

    if proc.returncode != 0:
        logger.error("whisper-cpp failed: %s", stderr.decode())
        return None

    text = stdout.decode("utf-8").strip()
    lines = [l.strip() for l in text.split("\n") if l.strip() and "[BLANK_AUDIO]" not in l]
    result = " ".join(lines).strip()

    logger.info("Transcribed %d chars from %s", len(result), wav_path.name)
    return result if result else None


async def _try_claude_transcribe(audio_path: str) -> Optional[str]:
    """Fallback: use claude to transcribe via reading the audio file."""
    settings = get_settings()
    claude_bin = settings.claude_binary

    if not shutil.which(claude_bin):
        logger.error("claude CLI not found for fallback transcription.")
        return None

    logger.info("Using claude for audio transcription fallback")

    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p",
        f"The user sent a voice message. The audio file is at {audio_path}. "
        f"Please read/process it and provide the transcription. "
        f"If you cannot read audio files, just say CANNOT_TRANSCRIBE.",
        "--model", "haiku",
        "--max-turns", "1",
        "--output-format", "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path(audio_path).parent),
    )

    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)

    if proc.returncode != 0:
        return None

    import json
    try:
        data = json.loads(stdout.decode())
        text = data.get("result", "")
        if "CANNOT_TRANSCRIBE" in text:
            logger.info("Claude cannot transcribe audio directly.")
            return None
        return text if text else None
    except (json.JSONDecodeError, KeyError):
        return stdout.decode().strip() or None
