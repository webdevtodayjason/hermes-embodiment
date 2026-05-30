"""embody.backends.audio — audio output backend.

Plays a synthesized audio file through the configured output. Selected by
``cfg["audio"]["backend"]`` and pinned to ``cfg["audio"]["device"]``:

    auto           pipewire if `paplay` present, else alsa if `aplay`, else hermes-default
    pipewire       paplay --device=<device>   (robust under PipeWire; pin by sink NAME)
    alsa           aplay -D <device>          (raw ALSA; device-busy risk under PipeWire)
    hermes-default Hermes' own player (tools.voice_mode.play_audio_file)
    off            silent (face/LEDs only)

This module exposes ``play(path, cfg)`` (NOT ``on_state``), so the backend
registry treats it as transport, not a state backend. ``core.voice`` calls it.
Best-effort: a missing player or a flaky subprocess never raises into the agent.

Format note: ElevenLabs synth yields mp3; `paplay`/`aplay` want wav, so we
convert with ffmpeg first. If conversion fails (e.g. ffmpeg absent), we fall back
to the Hermes player on the original file.
"""
from __future__ import annotations

import os
import shutil
import subprocess

# tmp workspace for format conversion (extract to config in a later wave)
TMP_DIR = "/tmp/embody"
WAV_PATH = os.path.join(TMP_DIR, "play.wav")

_PLAY_TIMEOUT = 120   # seconds; a hung player must not pin the voice thread forever


def is_available(cfg: dict | None = None) -> bool:
    """Audio is 'available' unless explicitly turned off."""
    method = _method(cfg)
    return method != "off"


def play(path: str, cfg: dict | None = None) -> None:
    """Play ``path`` through the configured audio backend. Best-effort; never raises."""
    try:
        method = _method(cfg)
        if method == "off":
            return
        if method == "hermes-default":
            _play_hermes(path)
            return

        device = _device(cfg)
        wav = _to_wav(path)
        if wav is None:
            _play_hermes(path)         # conversion failed -> let Hermes try the original
            return

        if method == "pipewire":
            cmd = ["paplay"] + (["--device=" + device] if device else []) + [wav]
        elif method == "alsa":
            cmd = ["aplay", "-D", device or "default", wav]
        else:
            _play_hermes(path)
            return

        subprocess.run(
            cmd,
            check=False,
            timeout=_PLAY_TIMEOUT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # never crash the voice thread / hook
        _warn(f"play failed: {exc}")


# --- internals ---------------------------------------------------------------
def _audio_cfg(cfg: dict | None) -> dict:
    if isinstance(cfg, dict):
        section = cfg.get("audio")
        if isinstance(section, dict):
            return section
    return {}


def _device(cfg: dict | None) -> str:
    return (_audio_cfg(cfg).get("device") or "").strip()


def _method(cfg: dict | None) -> str:
    method = (_audio_cfg(cfg).get("backend") or "auto").strip().lower()
    if method == "auto":
        if shutil.which("paplay"):
            return "pipewire"
        if shutil.which("aplay"):
            return "alsa"
        return "hermes-default"
    return method


def _to_wav(path: str) -> str | None:
    """Convert ``path`` (mp3) to 48k stereo wav via ffmpeg. Returns wav path or None."""
    if not shutil.which("ffmpeg"):
        return None
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", "48000", "-ac", "2", WAV_PATH],
            check=True,
            timeout=60,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return WAV_PATH
    except Exception as exc:  # pragma: no cover - defensive
        _warn(f"ffmpeg convert failed: {exc}")
        return None


def _play_hermes(path: str) -> None:
    """Fallback: play via Hermes' own player (lazy import; gateway-only)."""
    try:
        from tools.voice_mode import play_audio_file  # lazy: only resolves in the gateway
        play_audio_file(path)
    except Exception as exc:  # pragma: no cover - off-box / no Hermes
        _warn(f"hermes-default playback unavailable: {exc}")


def _warn(msg: str) -> None:
    import sys
    print(f"[embody.audio] {msg}", file=sys.stderr)
