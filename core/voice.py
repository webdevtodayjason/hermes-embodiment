"""embody.core.voice — TTS playback: STREAMING-first, with full-synth fallback.

``speak_async(text, on_start, on_done)`` runs on its OWN daemon thread so the
gateway loop is never blocked by speech. Two paths:

  1. **Streaming (preferred, ElevenLabs):** POST the reply to ElevenLabs'
     ``/v1/text-to-speech/{voice}/stream`` endpoint (flash model, ``pcm_24000``)
     and pipe the audio chunks straight into a player (``paplay --raw`` pinned to
     the configured sink) as they arrive — so she starts talking within a few
     hundred ms instead of after a full synth. Each PCM chunk's RMS is broadcast
     as a ``{"volume": …}`` frame on the state server's ``/events`` SSE, which the
     face already consumes (``app.js`` → ``setVolume``) to move her mouth +
     particles with her REAL voice.

  2. **Fallback (any provider):** the original synth-the-whole-file path —
     ``tools.tts_tool.text_to_speech_tool`` → mp3 → ``backends.audio.play``. Used
     whenever streaming is disabled, the provider isn't ElevenLabs, there's no API
     key / ``paplay``, or the stream errors **before any audio played** (so we
     never double-speak).

`on_start()` fires when audio actually begins (first stream chunk, or right before
the fallback plays). `on_done()` fires in a finally so every turn lands back on
idle even if synth/playback fails. The whole worker is try/except-wrapped so TTS
never crashes the post_llm_call hook.
"""
from __future__ import annotations

import array
import math
import os
import re
import shutil
import subprocess
import threading

# Fallback voice id when config leaves voice.voice_id == "" AND you want a hard
# default. None => let Hermes use its configured voice (full-synth path only).
VOICE_ID = None

# ElevenLabs "Adam" — the streaming path needs a concrete voice id, so this is the
# last-resort default when neither embody nor Hermes config provides one.
DEFAULT_ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"
DEFAULT_STREAMING_MODEL_ID = "eleven_flash_v2_5"   # low-latency model
_DEFAULT_SAMPLE_RATE = 24000                        # pcm_24000 => s16le mono 24 kHz

TMP_DIR = "/tmp/embody"
MP3_PATH = os.path.join(TMP_DIR, "out.mp3")

_PLAY_TIMEOUT = 120        # seconds; a hung player must not pin the voice thread forever
_STREAM_CHUNK = 2048       # bytes per read (~43 ms @ 24 kHz) -> ~23 volume frames/s
_VOL_GAIN = 1.8            # light perceptual boost so quiet speech still moves the mouth

_cfg: dict = {}


def configure(cfg: dict) -> None:
    """Install the loaded config (provides voice.* and audio.* settings)."""
    global _cfg
    _cfg = cfg or {}


def speak_async(text, on_start=None, on_done=None):
    """Synthesize + play `text` on a background daemon thread; returns immediately."""
    t = threading.Thread(
        target=_speak_worker,
        args=(text, on_start, on_done),
        name="embody-tts",
        daemon=True,
    )
    t.start()
    return t


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #
def _speak_worker(text, on_start, on_done):
    try:
        voice_cfg = _cfg.get("voice", {}) if isinstance(_cfg, dict) else {}
        if voice_cfg.get("enabled", True) is False:
            return  # speech disabled; `finally` still resets state to idle

        clean = _strip_markdown(text or "")
        if not clean.strip():
            return

        # 1) try streaming (fast first-audio + live mouth). True => audio played.
        if _stream_enabled(voice_cfg) and _stream_speak(clean, voice_cfg, on_start):
            return

        # 2) fallback: synth the whole file, then play (any provider).
        _full_synth_and_play(clean, voice_cfg, on_start)
    except Exception as exc:  # never crash the hook
        _warn(f"speak failed: {exc}")
    finally:
        _reset_volume()                    # mouth closes even on failure
        if on_done:
            _safe_call(on_done)            # always return to idle


# --------------------------------------------------------------------------- #
# Streaming path (ElevenLabs /stream -> paplay --raw, + live volume)
# --------------------------------------------------------------------------- #
def _stream_speak(text, voice_cfg, on_start) -> bool:
    """Stream ElevenLabs audio progressively to the speaker. Returns True iff any
    audio was actually played (so the caller skips the full-synth fallback).
    Best-effort; never raises."""
    api_key = _eleven_api_key()
    if not api_key:
        return False
    voice_id = _resolve_voice_id(voice_cfg)
    if not voice_id:
        return False
    if not shutil.which("paplay"):
        return False

    stream_cfg = voice_cfg.get("stream", {}) if isinstance(voice_cfg.get("stream"), dict) else {}
    model_id = str(stream_cfg.get("model_id") or DEFAULT_STREAMING_MODEL_ID)
    try:
        sample_rate = int(stream_cfg.get("sample_rate") or _DEFAULT_SAMPLE_RATE)
    except (TypeError, ValueError):
        sample_rate = _DEFAULT_SAMPLE_RATE

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    params = {"output_format": f"pcm_{sample_rate}", "optimize_streaming_latency": "3"}
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    body = {"text": text, "model_id": model_id}

    played = False
    player = None
    try:
        resp = _post_stream(url, params, headers, body)
        status = getattr(resp, "status_code", 0)
        if status != 200:
            _warn(f"stream HTTP {status}: {str(getattr(resp, 'text', ''))[:200]}")
            return False
        player = _spawn_player(sample_rate)
        if player is None or player.stdin is None:
            return False

        for chunk in resp.iter_content(chunk_size=_STREAM_CHUNK):
            if not chunk:
                continue
            if not played:
                played = True
                if on_start:
                    _safe_call(on_start)        # face -> "speaking" on FIRST audio
            try:
                player.stdin.write(chunk)
            except (BrokenPipeError, OSError):
                break                            # player died -> stop feeding it
            _emit_volume(chunk, sample_rate)     # RMS -> {"volume": …} on /events

        try:
            player.stdin.close()
        except Exception:
            pass
        try:
            player.wait(timeout=_PLAY_TIMEOUT)
        except Exception:
            pass
        return played
    except Exception as exc:  # noqa: BLE001 — stream issues fall back (if nothing played yet).
        _warn(f"stream failed: {exc}")
        return played
    finally:
        if player is not None:
            try:
                if player.poll() is None:
                    player.terminate()
            except Exception:
                pass


def _post_stream(url, params, headers, json_body):
    """POST to the ElevenLabs streaming endpoint. Isolated (and mockable) so the
    network call is the only thing tests need to stand in for."""
    import requests  # lazy: a gateway dep; not needed off-box / for the fallback path
    return requests.post(
        url, params=params, headers=headers, json=json_body,
        stream=True, timeout=(10, 60),
    )


def _spawn_player(sample_rate: int):
    """Spawn ``paplay --raw`` reading s16le mono PCM from stdin, pinned to the
    configured sink. None if paplay can't start."""
    cmd = ["paplay", "--raw", "--format=s16le", f"--rate={sample_rate}", "--channels=1"]
    device = _device()
    if device:
        cmd.append(f"--device={device}")
    try:
        return subprocess.Popen(
            cmd, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        _warn("paplay unavailable; streaming disabled (falling back).")
        return None


def _emit_volume(chunk: bytes, sample_rate: int) -> None:
    """Compute the RMS amplitude of a PCM chunk (s16le) and broadcast it 0..1.
    Best-effort; never raises. (Pi is little-endian, so native array('h') matches.)"""
    try:
        n = (len(chunk) // 2) * 2
        if n <= 0:
            return
        samples = array.array("h")
        samples.frombytes(chunk[:n])
        if not samples:
            return
        acc = 0
        for s in samples:
            acc += s * s
        rms = math.sqrt(acc / len(samples)) / 32768.0
        _broadcast_volume(min(1.0, rms * _VOL_GAIN))
    except Exception:  # noqa: BLE001 — envelope math must never break playback.
        pass


def _broadcast_volume(vol: float) -> None:
    try:
        from . import state as _state
        _state.broadcast_volume(vol)
    except Exception:  # noqa: BLE001
        pass


def _reset_volume() -> None:
    _broadcast_volume(0.0)     # mouth + particles settle back to closed/idle


# --------------------------------------------------------------------------- #
# Fallback path (original full-synth -> file -> audio backend)
# --------------------------------------------------------------------------- #
def _full_synth_and_play(clean, voice_cfg, on_start) -> None:
    os.makedirs(TMP_DIR, exist_ok=True)

    # synth -> mp3 (lazy import: tools.tts_tool only resolves in the gateway)
    from tools.tts_tool import text_to_speech_tool  # noqa: WPS433 (lazy by design)

    synth_kwargs = {"text": clean, "output_path": MP3_PATH}
    voice_id = (voice_cfg.get("voice_id") or "").strip() or VOICE_ID
    if voice_id:                       # "" / None => spec-exact call (Hermes default voice)
        synth_kwargs["voice_id"] = voice_id
    text_to_speech_tool(**synth_kwargs)

    # hand off to the audio backend (it converts mp3->wav + plays on the device)
    from ..backends import audio       # lazy: package fully loaded by call time

    if on_start:
        _safe_call(on_start)           # face/LEDs -> "speaking" right before audio
    audio.play(MP3_PATH, _cfg)


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #
def _stream_enabled(voice_cfg) -> bool:
    """Streaming is on by default, but only for the ElevenLabs provider (the
    /stream endpoint is ElevenLabs-specific); other providers use the fallback."""
    stream_cfg = voice_cfg.get("stream", {}) if isinstance(voice_cfg.get("stream"), dict) else {}
    if stream_cfg.get("enabled", True) is False:
        return False
    return _effective_provider(voice_cfg) == "elevenlabs"


def _effective_provider(voice_cfg) -> str:
    prov = (voice_cfg.get("provider") or "").strip().lower()
    if prov:
        return prov
    return str(_hermes_tts_cfg().get("provider") or "").strip().lower()


def _resolve_voice_id(voice_cfg) -> str:
    vid = (voice_cfg.get("voice_id") or "").strip()
    if vid:
        return vid
    el = _hermes_tts_cfg().get("elevenlabs", {})
    if isinstance(el, dict):
        vid = (el.get("voice_id") or "").strip()
    return vid or DEFAULT_ELEVENLABS_VOICE_ID


def _eleven_api_key() -> str:
    key = os.getenv("ELEVENLABS_API_KEY")
    if key:
        return key
    try:                               # Hermes reads ~/.hermes/.env via this helper
        from tools.tts_tool import get_env_value
        return get_env_value("ELEVENLABS_API_KEY") or ""
    except Exception:
        return ""


def _hermes_tts_cfg() -> dict:
    try:
        from hermes_cli.config import load_config
        cfg = load_config().get("tts", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:                  # off-box / no Hermes -> caller picks safe defaults
        return {}


def _device() -> str:
    audio_cfg = _cfg.get("audio", {}) if isinstance(_cfg, dict) else {}
    if isinstance(audio_cfg, dict):
        return (audio_cfg.get("device") or "").strip()
    return ""


# --------------------------------------------------------------------------- #
# Helpers (unchanged)
# --------------------------------------------------------------------------- #
def _strip_markdown(text: str) -> str:
    """Best-effort strip of common markdown so TTS doesn't read syntax aloud."""
    if not text:
        return ""
    t = text
    t = re.sub(r"```.*?```", " ", t, flags=re.DOTALL)          # fenced code blocks
    t = re.sub(r"`([^`]*)`", r"\1", t)                          # inline code
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)             # images -> alt
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)              # links  -> text
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)                 # headers
    t = re.sub(r"(?m)^\s{0,3}>\s?", "", t)                      # blockquotes
    t = re.sub(r"(?m)^\s*[-*+]\s+", "", t)                      # bullet lists
    t = re.sub(r"(?m)^\s*\d+\.\s+", "", t)                      # ordered lists
    t = re.sub(r"(\*\*|__)(.*?)\1", r"\2", t, flags=re.DOTALL)  # bold
    t = re.sub(r"(\*|_)(.*?)\1", r"\2", t, flags=re.DOTALL)     # italic
    t = re.sub(r"~~(.*?)~~", r"\1", t)                          # strikethrough
    t = re.sub(r"(?m)^\s*([-*_])(?:\s*\1){2,}\s*$", "", t)      # horizontal rules
    t = re.sub(r"\n{3,}", "\n\n", t)                            # collapse blank lines
    t = re.sub(r"[ \t]{2,}", " ", t)                            # collapse spaces
    return t.strip()


def _safe_call(fn):
    try:
        fn()
    except Exception as exc:  # pragma: no cover - defensive
        _warn(f"callback failed: {exc}")


def _warn(msg: str) -> None:
    import sys
    print(f"[embody.voice] {msg}", file=sys.stderr)
