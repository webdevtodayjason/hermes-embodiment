"""embody.core.voice — async TTS synth + playback via the audio backend.

``speak_async(text, on_start, on_done)`` runs on its OWN daemon thread so the
gateway conversation loop is never blocked by speech. It:

  1. strips markdown from `text`,
  2. synthesizes via Hermes' configured TTS provider
     (``tools.tts_tool.text_to_speech_tool`` -> ElevenLabs) to an mp3,
  3. hands the mp3 to the audio backend (``embody.backends.audio.play``), which
     converts + plays it on the configured device (HDMI sink, etc.).

`on_start()` is called right before playback; `on_done()` is called in a finally
block so every turn lands back on idle even if synth/playback fails or the text
is empty. The whole worker is try/except-wrapped so a TTS failure never crashes
the post_llm_call hook.
"""
from __future__ import annotations

import os
import re
import threading

# Fallback voice id when config leaves voice.voice_id == "" AND you want a hard
# default. None => let Hermes use its configured voice. The text_to_speech_tool
# `voice_id` kwarg name is UNVERIFIED against the spec (only text=/output_path=
# are documented) — it's only ever passed when a non-empty id is configured.
VOICE_ID = None

TMP_DIR = "/tmp/embody"
MP3_PATH = os.path.join(TMP_DIR, "out.mp3")

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


def _speak_worker(text, on_start, on_done):
    try:
        voice_cfg = _cfg.get("voice", {}) if isinstance(_cfg, dict) else {}
        if voice_cfg.get("enabled", True) is False:
            return  # speech disabled; `finally` still resets state to idle

        clean = _strip_markdown(text or "")
        if not clean.strip():
            return

        os.makedirs(TMP_DIR, exist_ok=True)

        # 1) synth -> mp3 (lazy import: tools.tts_tool only resolves in the gateway)
        from tools.tts_tool import text_to_speech_tool  # noqa: WPS433 (lazy by design)

        synth_kwargs = {"text": clean, "output_path": MP3_PATH}
        voice_id = (voice_cfg.get("voice_id") or "").strip() or VOICE_ID
        if voice_id:                       # "" / None at first-light => spec-exact call
            synth_kwargs["voice_id"] = voice_id
        text_to_speech_tool(**synth_kwargs)

        # 2) hand off to the audio backend (it converts mp3->wav + plays on the device)
        from ..backends import audio      # lazy: package fully loaded by call time

        if on_start:
            _safe_call(on_start)           # face/LEDs -> "speaking" right before audio
        audio.play(MP3_PATH, _cfg)
    except Exception as exc:  # never crash the hook
        _warn(f"speak failed: {exc}")
    finally:
        if on_done:
            _safe_call(on_done)            # always return to idle


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
