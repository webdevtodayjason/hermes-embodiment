"""embody.core.voice_input — push-to-talk voice INPUT (record -> STT -> inject).

The capture side of the loop (the reply side is core.voice TTS). Holding the kiosk
PTT button records the user; releasing it transcribes locally and feeds the text to
the gateway so Minnie runs a normal agent turn and **replies aloud** (her existing
post_llm_call hook fires her TTS + mouth + LEDs).

Pipeline (all best-effort; NOTHING here raises into a hook/handler):

    PTT "start"  -> _start():  spawn ``pw-record`` (16 kHz mono s16 wav) + arm a
                               hard ``max_seconds`` cap so a stuck button can't
                               record forever.
    PTT "stop"   -> _stop():   stop recording and hand off to a background worker
                               (so the /control/ptt handler returns immediately):
                                 _finish(): terminate pw-record -> transcribe via
                                 the isolated STT venv (SUBPROCESS) -> inject.

INJECTION = the webhook platform (Option B), chosen because in-process injection
is unavailable to a GATEWAY plugin: ``PluginContext.inject_message`` returns False
in gateway mode by design (hermes_cli/plugins.py), and no gateway-runner ref is
exposed to plugins. The webhook is the supported, gateway-native path: a POST to
``/webhooks/<route>`` runs a real agent turn whose ``post_llm_call`` drives speech.
We POST to ``127.0.0.1`` (loopback, same process) with an ``X-Webhook-Signature``
HMAC-SHA256 over the body when a secret is configured.

STT runs in the isolated ``~/.embody-stt`` venv via SUBPROCESS — faster_whisper is
deliberately NOT imported into the gateway venv. Off-Pi (no ``pw-record`` / no STT
venv / webhook not enabled) every step degrades to an inert no-op.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request

logger = logging.getLogger("embody.core.voice_input")

_TMP_DIR = "/tmp/embody-voice"
_INSECURE_NO_AUTH = "INSECURE_NO_AUTH"   # mirrors the gateway webhook's loopback escape hatch

_cfg: dict = {}

# Recording state — guarded by _lock (never held across the heavy transcribe/inject,
# which run on a background thread). Only one recording at a time.
_lock = threading.Lock()
_proc: "subprocess.Popen | None" = None
_wav: "str | None" = None
_cap_timer: "threading.Timer | None" = None
_recording = False


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def configure(cfg: dict) -> None:
    """Install the loaded config (provides the ``voice_input.*`` settings)."""
    global _cfg
    _cfg = cfg or {}


def on_ptt(action: str) -> None:
    """PTT seam callback (registered via controls.set_ptt_callback). ``start`` on
    press barges in (stops any current speech) then begins recording; ``stop`` on
    release ends it -> transcribe -> inject.

    Barge-in fires on EVERY press, even when recording is disabled, so the mic
    button always interrupts her. Recording itself is gated on
    ``voice_input.enabled``. Never raises.
    """
    try:
        action = str(action).strip().lower()
        if action == "start":
            _barge_in()              # ALWAYS stop her current speech on a mic press
        if not _opt("enabled", False):
            return
        if action == "start":
            _start()
        elif action == "stop":
            _stop(reason="ptt")
    except Exception as exc:  # noqa: BLE001 — a PTT callback must never crash the request.
        _warn(f"on_ptt({action!r}) failed: {exc}")


def _barge_in() -> None:
    """Stop any in-progress TTS so the user can jump in. Best-effort; never raises."""
    try:
        from . import voice as _voice
        _voice.interrupt()
    except Exception:  # noqa: BLE001
        logger.debug("barge-in interrupt failed (ignored).", exc_info=True)


# --------------------------------------------------------------------------- #
# Record (pw-record)
# --------------------------------------------------------------------------- #
def _start() -> None:
    global _proc, _wav, _cap_timer, _recording
    with _lock:
        if _recording:
            return  # already recording — ignore a re-entrant press (keep the first)
        wav = os.path.join(_TMP_DIR, f"voice_{int(time.time() * 1000)}.wav")
        proc = _spawn_pw_record(wav)
        if proc is None:
            return  # no mic / pw-record absent -> inert
        _proc, _wav, _recording = proc, wav, True
        try:
            max_seconds = float(_opt("max_seconds", 30) or 30)
        except (TypeError, ValueError):
            max_seconds = 30.0
        timer = threading.Timer(max(1.0, max_seconds), lambda: _stop(reason="cap"))
        timer.daemon = True
        _cap_timer = timer
        timer.start()
    logger.debug("voice_input: recording -> %s (cap %ss)", wav, max_seconds)


def _stop(reason: str) -> None:
    """Stop recording and hand off to the background finisher. ``reason`` is
    ``"ptt"`` (button released) or ``"cap"`` (max_seconds watchdog fired)."""
    global _proc, _wav, _cap_timer, _recording
    with _lock:
        if not _recording:
            return  # nothing in flight (e.g. stop without a start, or double-stop)
        proc, wav, timer = _proc, _wav, _cap_timer
        _proc = _wav = _cap_timer = None
        _recording = False
    if timer is not None and reason != "cap":
        timer.cancel()   # the cap watchdog is what fired when reason == "cap"
    # Transcribe + inject OFF the caller thread so the PTT/cap path returns at once.
    threading.Thread(
        target=_finish, args=(proc, wav, reason),
        name="embody-voice-finish", daemon=True,
    ).start()


def _spawn_pw_record(wav: str) -> "subprocess.Popen | None":
    """Start ``pw-record`` writing 16 kHz mono s16 WAV. None if pw-record is absent."""
    try:
        os.makedirs(_TMP_DIR, exist_ok=True)
    except OSError:
        return None
    cmd = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16"]
    source = (_opt("mic_source", "") or "").strip()
    if source:                       # "" => default PipeWire source (the Samson Go Mic)
        cmd += ["--target", source]
    cmd.append(wav)
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        logger.debug("pw-record unavailable; voice capture inert.", exc_info=True)
        return None


def _terminate(proc) -> None:
    """Stop pw-record so it finalizes the WAV header. Best-effort; never raises."""
    if proc is None:
        return
    try:
        proc.terminate()           # SIGTERM -> pw-record flushes + closes the wav
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:  # noqa: BLE001 — teardown must never raise.
        logger.debug("pw-record terminate failed (ignored).", exc_info=True)


# --------------------------------------------------------------------------- #
# Finish: transcribe -> inject (background thread)
# --------------------------------------------------------------------------- #
def _finish(proc, wav: "str | None", reason: str) -> None:
    try:
        _set_thinking()            # tint the face while we transcribe (best-effort)
        _terminate(proc)
        text = _transcribe(wav) if wav else ""
        if text:
            logger.info("voice_input: transcript (%s) -> %r", reason, text)
            _inject(text)
        else:
            logger.debug("voice_input: empty transcript (%s); nothing injected.", reason)
    except Exception as exc:  # noqa: BLE001 — the worker thread must never crash.
        _warn(f"voice finish failed: {exc}")
    finally:
        _cleanup(wav)


def _transcribe(wav: str) -> str:
    """Transcribe ``wav`` via faster-whisper in the isolated STT venv (SUBPROCESS —
    never imported into the gateway venv). "" on any failure / no venv. Never raises."""
    venv = os.path.expanduser(_opt("stt_venv", "~/.embody-stt") or "~/.embody-stt")
    py = os.path.join(venv, "bin", "python")
    if not os.path.exists(py):
        logger.debug("STT venv python missing (%s); transcription inert.", py)
        return ""
    if not (wav and os.path.exists(wav)):
        return ""
    model = _opt("stt_model", "base") or "base"
    code = (
        "from faster_whisper import WhisperModel;"
        f"m=WhisperModel({model!r},device='cpu',compute_type='int8');"
        f"segs,_=m.transcribe({wav!r});"
        "print(' '.join(s.text for s in segs).strip())"
    )
    try:
        cp = subprocess.run(
            [py, "-c", code], capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("STT subprocess failed/absent (ignored).", exc_info=True)
        return ""
    if cp.returncode != 0:
        _warn(f"STT exit {cp.returncode}: {(cp.stderr or '').strip()[:300]}")
        return ""
    return (cp.stdout or "").strip()


def _inject(text: str) -> None:
    """POST the transcript to the gateway webhook -> a real agent turn (whose
    post_llm_call drives Minnie's reply). Best-effort; never raises.

    Loopback POST to ``http://<host>:<port>/webhooks/<route>`` with an
    ``X-Webhook-Signature`` HMAC-SHA256 over the body when a real secret is set.
    """
    wh = _opt("webhook", {}) or {}
    host = wh.get("host", "127.0.0.1")
    port = int(wh.get("port", 8644) or 8644)
    route = wh.get("route", "voice") or "voice"
    secret = str(wh.get("secret", "") or "")

    body = json.dumps({"transcript": text, "type": "voice"}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret and secret != _INSECURE_NO_AUTH:
        headers["X-Webhook-Signature"] = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

    url = f"http://{host}:{port}/webhooks/{route}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001 — webhook down/not-enabled is non-fatal.
        _warn(f"inject POST {url} failed (webhook enabled?): {exc}")


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _set_thinking() -> None:
    """Tint the face "thinking" during transcription (lazy import avoids any cycle)."""
    try:
        from . import state as _state
        _state.set_state("thinking", status="listening…")
    except Exception:  # noqa: BLE001
        logger.debug("set_thinking failed (ignored).", exc_info=True)


def _cleanup(wav: "str | None") -> None:
    if not wav:
        return
    try:
        os.remove(wav)
    except OSError:
        pass


def _opt(key: str, default):
    vi = _cfg.get("voice_input", {}) if isinstance(_cfg, dict) else {}
    if not isinstance(vi, dict):
        return default
    val = vi.get(key, default)
    return default if val is None else val


def _warn(msg: str) -> None:
    import sys
    print(f"[embody.voice_input] {msg}", file=sys.stderr)


__all__ = ["configure", "on_ptt"]
