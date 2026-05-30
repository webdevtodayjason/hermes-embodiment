"""embody.core.controls — touch-panel control surface (backlight, volume, PTT seam).

The hardware/exec adapter behind the ``POST /control/*`` endpoints in
``core.state``. ALL device access lives here so the HTTP handler stays clean. Every
call is best-effort and **degrades to a no-op off-Pi** (no backlight sysfs / no
``wpctl`` on PATH) — nothing here ever raises, so a control request can't crash the
state server.

Surfaces
--------
  set_brightness(pct: 0-100) -> int    write the panel backlight (returns applied pct)
  get_brightness() -> int              current backlight as 0-100
  set_volume(pct: 0-150) -> int        wpctl set-volume on the default sink (returns applied pct)
  get_volume() -> int                  current sink volume as 0-150
  read_state() -> dict                 {"brightness": pct, "volume": pct}
  ptt(action) -> None                  fire the optional PTT callback seam
  set_ptt_callback(fn) -> None         install the seam (future streaming-voice loop)

Hardware notes (verified on the live Pi 5 as the ``jason`` user — no sudo):
  * Backlight: first WRITABLE ``/sys/class/backlight/*/brightness``. On the Pi the
    DSI panel is ``/sys/class/backlight/10-0045`` with ``max_brightness=255``. pct
    0-100 maps linearly onto 0-max.
  * Volume: ``wpctl set-volume @DEFAULT_AUDIO_SINK@ <pct/100>`` with
    ``XDG_RUNTIME_DIR=/run/user/1000`` so wpctl reaches the user PipeWire bus. The
    default sink is HDMI. pct is clamped 0-150 (150% = wpctl 1.50).
  * PTT: a no-op callback seam only. The "listening"/"idle" state transitions
    themselves are driven by core.state's handler (kept out of here to avoid a
    state<->controls import cycle).
"""
from __future__ import annotations

import glob
import logging
import os
import subprocess
import threading

logger = logging.getLogger("embody.core.controls")

_BACKLIGHT_GLOB = "/sys/class/backlight/*"
_XDG_RUNTIME_DIR = "/run/user/1000"
_DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"
_WPCTL = "wpctl"

_BRIGHT_MAX_PCT = 100
_VOL_MAX_PCT = 150          # wpctl allows boosting past 100%; cap the panel at 150

# Graceful poweroff (panel shutdown button). `jason` has NOPASSWD: ALL, so no tty.
_POWEROFF_CMD = ["sudo", "systemctl", "poweroff"]
_POWEROFF_FALLBACK = ["sudo", "/usr/sbin/poweroff"]
_SHUTDOWN_DELAY = 1.5       # seconds — lets the HTTP response flush before the box goes down

# Optional callback fired on every PTT action ("start" | "stop"); installed by a
# future streaming-voice loop via set_ptt_callback(). Default: an inert seam.
_ptt_callback = None


# --------------------------------------------------------------------------- #
# Brightness (sysfs backlight)
# --------------------------------------------------------------------------- #
def set_brightness(pct) -> int:
    """Set the panel backlight to ``pct`` (0-100). Returns the clamped pct applied.

    No-ops (still returns the clamped pct) when no writable backlight exists, e.g.
    off-Pi. Never raises.
    """
    pct = _clamp(pct, 0, _BRIGHT_MAX_PCT)
    base = _find_backlight(require_write=True)
    if base is None:
        logger.debug("no writable backlight; set_brightness(%s) is a no-op.", pct)
        return pct
    try:
        max_val = _read_int(os.path.join(base, "max_brightness")) or 255
        raw = max(0, min(max_val, int(round(pct * max_val / 100.0))))
        with open(os.path.join(base, "brightness"), "w") as fh:
            fh.write(str(raw))
    except OSError:
        logger.debug("backlight write failed (ignored).", exc_info=True)
    return pct


def get_brightness() -> int:
    """Current backlight as 0-100 (cur/max). 0 when no backlight is present."""
    base = _find_backlight(require_write=False)
    if base is None:
        return 0
    cur = _read_int(os.path.join(base, "brightness"))
    max_val = _read_int(os.path.join(base, "max_brightness")) or 0
    if cur is None or max_val <= 0:
        return 0
    return max(0, min(100, int(round(cur * 100.0 / max_val))))


def _find_backlight(require_write: bool = True) -> str | None:
    """First ``/sys/class/backlight/*`` whose ``brightness`` exists (and, if
    ``require_write``, is writable by us). None if none match / off-Pi."""
    try:
        for base in sorted(glob.glob(_BACKLIGHT_GLOB)):
            bright = os.path.join(base, "brightness")
            if not os.path.exists(bright):
                continue
            if require_write and not os.access(bright, os.W_OK):
                continue
            return base
    except OSError:  # pragma: no cover - defensive
        pass
    return None


def _read_int(path: str) -> int | None:
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Volume (wpctl / PipeWire)
# --------------------------------------------------------------------------- #
def set_volume(pct) -> int:
    """Set the default sink volume to ``pct`` (0-150). Returns the clamped pct.

    No-ops (still returns the clamped pct) when ``wpctl`` is absent. Never raises.
    """
    pct = _clamp(pct, 0, _VOL_MAX_PCT)
    _run_wpctl(["set-volume", _DEFAULT_SINK, f"{pct / 100.0:.2f}"])
    return pct


def get_volume() -> int:
    """Current default-sink volume as 0-150. 0 when wpctl is absent/unreadable.

    Parses ``wpctl get-volume`` output, e.g. ``"Volume: 0.55"`` or
    ``"Volume: 0.55 [MUTED]"`` -> 55.
    """
    cp = _run_wpctl(["get-volume", _DEFAULT_SINK])
    if cp is None or cp.returncode != 0 or not cp.stdout:
        return 0
    for token in cp.stdout.strip().split():
        try:
            frac = float(token)
        except ValueError:
            continue
        return max(0, min(_VOL_MAX_PCT, int(round(frac * 100))))
    return 0


def _run_wpctl(args: list) -> "subprocess.CompletedProcess | None":
    """Run ``wpctl <args>`` on the user PipeWire bus. Returns the completed process,
    or None if wpctl is absent / the call errored. Never raises."""
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = _XDG_RUNTIME_DIR   # reach the user (uid 1000) bus
    try:
        return subprocess.run(
            [_WPCTL, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("wpctl %s failed/absent (ignored).", args, exc_info=True)
        return None


# --------------------------------------------------------------------------- #
# Read-back + PTT seam
# --------------------------------------------------------------------------- #
def read_state() -> dict:
    """{"brightness": pct, "volume": pct} for GET /control/state. Never raises.

    (Liveness of "listening" is owned by core.state, which adds it to the response.)
    """
    return {"brightness": get_brightness(), "volume": get_volume()}


def set_ptt_callback(fn) -> None:
    """Install the optional PTT seam callback (or None to clear)."""
    global _ptt_callback
    _ptt_callback = fn


def ptt(action: str) -> None:
    """Fire the optional PTT callback with ``action`` ("start"|"stop"). Best-effort;
    a None callback is a no-op and a raising callback is swallowed. The actual
    state transition is performed by core.state's handler, not here."""
    cb = _ptt_callback
    if cb is None:
        return
    try:
        cb(action)
    except Exception:  # noqa: BLE001 — a seam callback must never crash a control POST.
        logger.debug("ptt callback failed (ignored).", exc_info=True)


# --------------------------------------------------------------------------- #
# Power (graceful shutdown)
# --------------------------------------------------------------------------- #
def shutdown(delay: float = _SHUTDOWN_DELAY) -> None:
    """Schedule a graceful poweroff after ``delay`` seconds (so the HTTP response
    flushes to the panel before the box goes down). Runs the exec on a detached
    daemon timer thread and returns immediately. Best-effort; never raises.

    The actual command exec is isolated in ``_poweroff_exec`` so tests can
    monkeypatch it (or ``subprocess.Popen``) with ZERO risk of powering off the
    host. Caller (the HTTP handler) has already validated ``confirm:true``.
    """
    try:
        timer = threading.Timer(max(0.0, float(delay)), _poweroff_exec)
        timer.daemon = True
        timer.start()
    except Exception:  # noqa: BLE001 — scheduling failure must never crash the request.
        logger.debug("failed to schedule poweroff (ignored).", exc_info=True)


def _poweroff_exec() -> None:
    """Run the poweroff command detached (new session). Tries ``systemctl``, falls
    back to ``/usr/sbin/poweroff`` only if the first spawn raises (binary absent).
    Never raises."""
    for cmd in (_POWEROFF_CMD, _POWEROFF_FALLBACK):
        try:
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.SubprocessError):
            logger.debug("poweroff via %s failed; trying fallback.", cmd, exc_info=True)
    logger.warning("poweroff: all commands failed; box stays up.")


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _clamp(value, lo: int, hi: int, default: int = 0) -> int:
    """Coerce ``value`` to an int in [lo, hi]; ``default`` on non-numeric input."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


__all__ = [
    "set_brightness", "get_brightness",
    "set_volume", "get_volume",
    "read_state", "ptt", "set_ptt_callback",
    "shutdown",
]
