"""Tests for media/transcribe.py — focused on the timeout heuristic.

The whisper-cpp call is killed by `asyncio.wait_for(timeout=...)`. Earlier
versions hardcoded 120s, which silently dropped any voice message longer
than ~40s with a slow CPU + base/small model. The dynamic timeout scales
with the actual audio duration so long voice notes get a fair budget.
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest


def _make_wav(path: Path, duration_sec: float, sample_rate: int = 16000) -> None:
    """Write a silent PCM-16 mono WAV of the given duration."""
    n_frames = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_frames)


def test_timeout_short_clip_floors_at_120(tmp_path):
    """A 5-sec clip shouldn't be given less than the 120s floor — model
    warmup alone can take 30-60s on a cold whisper-cpp invocation."""
    from media.transcribe import _compute_timeout

    wav = tmp_path / "short.wav"
    _make_wav(wav, duration_sec=5)
    assert _compute_timeout(wav) == 120


def test_timeout_minute_clip_scales_proportionally(tmp_path):
    """A 60-sec clip → 30 + 3*60 = 210s budget."""
    from media.transcribe import _compute_timeout

    wav = tmp_path / "minute.wav"
    _make_wav(wav, duration_sec=60)
    assert _compute_timeout(wav) == 210


def test_timeout_long_clip_caps_at_30min(tmp_path):
    """A 30-min clip would compute to 30 + 5400 = 5430s. Cap at 1800s
    so a truly hung whisper still gets killed in reasonable time."""
    from media.transcribe import _compute_timeout

    wav = tmp_path / "long.wav"
    _make_wav(wav, duration_sec=30 * 60)
    assert _compute_timeout(wav) == 1800


def test_timeout_unreadable_wav_falls_back(tmp_path):
    """If wave header parsing fails (corrupt file, wrong format), we
    fall back to a sane default (600s) rather than crashing."""
    from media.transcribe import _compute_timeout

    bogus = tmp_path / "bogus.wav"
    bogus.write_bytes(b"not a wav file")
    assert _compute_timeout(bogus) == 600


def test_timeout_missing_file_falls_back(tmp_path):
    from media.transcribe import _compute_timeout
    assert _compute_timeout(tmp_path / "does_not_exist.wav") == 600
