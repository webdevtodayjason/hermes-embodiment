"""null.py — no-op backend for hermes-embody.

The auto-detect fallback used on hosts with no matching hardware (e.g. no
Pironman). It implements the shared backend interface (see
``backends/__init__.py``) but does nothing, so the rest of the plugin (face web
UI + TTS) runs unchanged on a bare Hermes box.

    is_available() -> bool        # always True (it's the universal fallback)
    setup(cfg: dict) -> None      # no-op
    on_state(state, cfg) -> None  # no-op
    on_mood(mood, cfg) -> None    # no-op

Pure adapter — no HTTP, no TTS, no agent imports. Never raises.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("embody.backends.null")

# Log the "using null backend" notice at most once per process.
_setup_logged = False


def is_available() -> bool:
    """Always available — this is the universal no-op fallback backend."""
    return True


def setup(cfg: dict | None = None) -> None:
    """No-op. The null backend has nothing to configure."""
    global _setup_logged
    if not _setup_logged:
        logger.debug("null backend active (no hardware).")
        _setup_logged = True


def on_state(state: str, cfg: dict | None = None) -> None:
    """No-op. The null backend has no hardware to drive."""
    return None


def on_mood(mood: str, cfg: dict | None = None) -> None:
    """No-op. The null backend has no hardware to tint."""
    return None


__all__ = ["is_available", "setup", "on_state", "on_mood"]
