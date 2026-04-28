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


def _compute_timeout(wav_path: Path) -> int:
    """Pick a per-call timeout that scales with audio length.

    Heuristic: 30s startup overhead + 3x audio duration. Floor at 120s
    (short clips with model warmup), ceiling at 30min (long-running guard
    so a truly hung whisper still dies). Falls back to 600s if we can't
    read the WAV header.
    """
    import wave
    try:
        with wave.open(str(wav_path), "rb") as w:
            duration = w.getnframes() / max(1, w.getframerate())
    except (wave.Error, OSError, EOFError):
        return 600
    return min(1800, max(120, int(30 + duration * 3)))


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

    # -bs 1 -bo 1: greedy decode (no beam search). On CPU this is ~3-5x
    # faster than the default 5-beam search and quality drop on conversational
    # voice notes is negligible. Lost-Tor incident (2026-04-27) showed base
    # model + 5-beam was 5+ minutes on a 60-sec clip, blowing past the 120s
    # asyncio timeout and silently dropping every voice message.
    #
    # Threads: cap at cpu_count - 1 so the asyncio loop, claude subprocess,
    # and (when voice-mode is on) edge_tts have a core to breathe. Pinning
    # whisper to all cores while the bot is also running haiku scheduled
    # tasks + TTS pipeline triggers timeouts under load (Tor incident
    # 2026-04-28: tiny model timed out on a 46-sec clip with voice-mode on).
    import os
    cpu = os.cpu_count() or 4
    threads = str(max(1, cpu - 1))
    cmd = [
        whisper_bin,
        "-m", model,
        "-l", language,
        "-t", threads,
        "-bs", "1",
        "-bo", "1",
        "-np",  # silence whisper's progress chatter — keeps stderr small
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

    # Scale timeout to actual audio length — whisper-cpp on CPU runs roughly
    # at 1-3x realtime with greedy decode (depends on model size + threads).
    # 30s base + 3x duration covers slow-CPU + base/small models on long
    # voice notes. Floor at 120s for tiny clips, ceiling at 30min so a
    # truly hung process eventually gets killed.
    # Idle-timeout would be cleaner but whisper-cpp buffers stdout until
    # the entire transcript is ready — no streaming progress to reset on.
    timeout = _compute_timeout(wav_path)
    logger.info("whisper-cpp timeout: %ds (audio duration determines budget)", timeout)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

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
