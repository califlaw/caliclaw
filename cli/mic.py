"""Microphone recorder for caliclaw TUI — F2 push-to-talk toggle.

Synchronous, blocking, single-recording. Spawns ffmpeg as a subprocess
to capture from system default mic (PulseAudio on Linux, AVFoundation on
macOS), then transcribes via local whisper-cpp.

Why ffmpeg + sync: prompt_toolkit keybindings run in the prompt thread,
not the asyncio loop. Easier to keep this whole module sync (subprocess
+ subprocess.run) than to bridge to the bot's asyncio loop. Recording is
short (seconds), transcription is short (seconds on tiny model), so the
brief UI freeze on stop is acceptable.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


class MicRecorder:
    """Single-instance recorder. Call start(), then stop_and_transcribe()."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._wav_path: Optional[Path] = None
        self._started_at: float = 0.0
        self._error: Optional[str] = None

    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def elapsed(self) -> float:
        if not self._started_at:
            return 0.0
        return time.time() - self._started_at

    def last_error(self) -> Optional[str]:
        return self._error

    def start(self) -> bool:
        """Spawn ffmpeg recording subprocess. Returns True on launch."""
        if self.is_recording():
            return True
        self._error = None
        ts = int(time.time())
        self._wav_path = Path(tempfile.gettempdir()) / f"caliclaw_mic_{ts}.wav"
        cmd = self._ffmpeg_cmd(self._wav_path)
        try:
            # stdin=PIPE so we can send 'q' for clean shutdown later.
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._error = "ffmpeg not installed"
            self._proc = None
            return False
        # Brief sanity check — if ffmpeg dies immediately (no mic, bad device),
        # surface the error before the user thinks they're recording.
        time.sleep(0.15)
        if self._proc.poll() is not None:
            self._error = "ffmpeg failed to start (mic device unavailable?)"
            self._proc = None
            return False
        self._started_at = time.time()
        return True

    def stop_and_transcribe(self, language: str = "ru") -> Optional[str]:
        """Stop recording and run whisper-cpp synchronously. Returns text."""
        if not self._proc or not self._wav_path:
            return None
        # 'q' over stdin tells ffmpeg to flush and exit cleanly so the WAV
        # has a valid header. Fallback to terminate() if it ignores us.
        try:
            self._proc.communicate(input=b"q", timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()

        wav = self._wav_path
        self._proc = None
        self._wav_path = None
        self._started_at = 0.0

        if not wav.exists() or wav.stat().st_size < 2000:
            self._error = "recording empty (too short or mic silent)"
            return None

        text = self._transcribe(wav, language)
        try:
            wav.unlink()
        except OSError:
            pass
        return text

    def cancel(self) -> None:
        """Drop the recording without transcribing."""
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._wav_path and self._wav_path.exists():
            try:
                self._wav_path.unlink()
            except OSError:
                pass
        self._proc = None
        self._wav_path = None
        self._started_at = 0.0

    # ── internals ──

    def _ffmpeg_cmd(self, out: Path) -> list[str]:
        if sys.platform == "darwin":
            # AVFoundation: ":0" = default audio input. User can override
            # via CALICLAW_MIC_INPUT env (e.g. ":1" for second mic).
            inp = os.environ.get("CALICLAW_MIC_INPUT", ":0")
            return [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "avfoundation", "-i", inp,
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(out),
            ]
        # Linux: pulse first (works on most desktops + pipewire-pulse shim).
        # Override via CALICLAW_MIC_INPUT (e.g. "alsa:default" or "pulse:hw").
        backend = os.environ.get("CALICLAW_MIC_BACKEND", "pulse")
        device = os.environ.get("CALICLAW_MIC_INPUT", "default")
        return [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", backend, "-i", device,
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(out),
        ]

    def _transcribe(self, wav: Path, language: str) -> Optional[str]:
        from core.config import get_settings
        s = get_settings()
        whisper = s.whisper_cpp_path
        model = s.whisper_model_path
        if not Path(model).exists():
            self._error = f"whisper model missing: {model}"
            return None
        # Match the bot's flag set: greedy decode, capped threads, silent.
        cpu = os.cpu_count() or 4
        cmd = [
            whisper, "-m", model, "-l", language,
            "-t", str(max(1, cpu - 1)),
            "-bs", "1", "-bo", "1",
            "-np", "-nt",
            "-f", str(wav),
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
            )
        except FileNotFoundError:
            self._error = f"whisper binary missing: {whisper}"
            return None
        except subprocess.TimeoutExpired:
            self._error = "whisper timed out"
            return None
        if result.returncode != 0:
            self._error = f"whisper failed: {result.stderr.decode(errors='ignore')[:120]}"
            return None
        text = result.stdout.decode("utf-8", errors="ignore").strip()
        lines = [
            l.strip() for l in text.splitlines()
            if l.strip() and "[BLANK_AUDIO]" not in l
        ]
        out = " ".join(lines).strip()
        return out or None
