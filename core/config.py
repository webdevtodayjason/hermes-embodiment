"""embody.core.config — load + validate the plugin config, with defaults for every key.

Search order (first existing file wins; its values are deep-merged over DEFAULTS):
  1. ``$EMBODY_CONFIG``                                  (explicit override; handy for tests)
  2. ``<hermes_home>/plugins/embody/config.yaml``        (canonical installed location)
  3. ``<plugin_root>/config.yaml``                       (repo-root == plugin package)
  4. ``<plugin_root>/config.yaml.example``               (dev fallback before install copies it)

A missing/empty/broken file is non-fatal: the built-in DEFAULTS make the plugin
run on a bare box as "animated face in a browser + TTS on the default sink".
PyYAML is imported defensively so this module also imports on a host without it
(DEFAULTS are returned in that case).
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

try:
    import yaml  # PyYAML (a Hermes dependency); optional off-box
except Exception:  # pragma: no cover - defensive
    yaml = None


# --- defaults for EVERY key (mirrors config.yaml.example) --------------------
DEFAULTS = {
    "persona": {
        "name": "Assistant",
        "wake_word": "hey assistant",
    },
    "voice": {
        "enabled": True,
        "provider": "",            # "" => inherit Hermes tts.provider
        "voice_id": "",            # "" => inherit Hermes voice
        "speak_on": "post_llm_call",
    },
    "audio": {
        "backend": "auto",         # auto | pipewire | alsa | hermes-default | off
        "device": "",              # "" => system default sink
    },
    "voice_input": {
        "enabled": False,          # opt-in: needs the ~/.embody-stt venv + a mic + the webhook platform
        "max_seconds": 30,         # hard cap so a stuck PTT can't record forever
        "stt_venv": "~/.embody-stt",  # isolated faster-whisper venv (run by SUBPROCESS, never imported)
        "stt_model": "base",       # whisper model cached in the venv
        "mic_source": "",          # "" => default PipeWire source (Samson Go Mic)
        "webhook": {               # where to POST the transcript (the gateway webhook platform)
            "host": "127.0.0.1",
            "port": 8644,
            "route": "voice",
            "secret": "",          # HMAC secret; MUST match platforms.webhook route secret
        },
    },
    "face": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8830,
        "theme": "default",
        "mood_hold": 8,            # seconds a non-neutral mood lingers before decaying to neutral
        "kiosk": {
            "enabled": False,
            "user_data_dir": "~/.embody-kiosk",
            "command": "",
        },
    },
    "leds": {
        "backend": "auto",         # auto (iff pironman5 on PATH) | pironman | off
        "brightness": 60,
        "states": {
            "idle":     {"color": "1E3A5F", "style": "breathing"},
            "thinking": {"color": "FFB000", "style": "flow"},
            "working":  {"color": "8000FF", "style": "solid"},
            "speaking": {"color": "00C853", "style": "flow"},
        },
        "moods": {                 # emotional tints (independent of state); color = 6-hex no '#'
            "neutral":   {"color": "1E3A5F"},
            "happy":     {"color": "FFC107"},
            "excited":   {"color": "FF6D00"},
            "loving":    {"color": "FF2D78"},
            "playful":   {"color": "00E5FF"},
            "curious":   {"color": "7C4DFF"},
            "sad":       {"color": "2962FF"},
            "surprised": {"color": "EAEAEA"},
            "concerned": {"color": "FF7043"},
        },
    },
    "oled": {
        "backend": "auto",         # auto | pironman | off
    },
}


def plugin_root() -> Path:
    """Repo root == the plugin package dir (parent of this ``core/`` package)."""
    return Path(__file__).resolve().parent.parent


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("EMBODY_CONFIG")
    if override:
        paths.append(Path(override).expanduser())
    paths.append(_hermes_home() / "plugins" / "embody" / "config.yaml")
    root = plugin_root()
    paths.append(root / "config.yaml")
    paths.append(root / "config.yaml.example")
    return paths


def load_config() -> dict:
    """Return the merged config dict (DEFAULTS overlaid with the first config file found)."""
    cfg = copy.deepcopy(DEFAULTS)
    if yaml is None:
        _warn("PyYAML unavailable; using built-in defaults.")
        return cfg

    for path in _candidate_paths():
        try:
            if not path.is_file():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # pragma: no cover - defensive
            _warn(f"failed reading {path}: {exc}")
            continue
        if isinstance(data, dict):
            _deep_merge(cfg, data)
        break  # first existing file wins
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` in place (dicts merge, scalars replace)."""
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
    return base


def _warn(msg: str) -> None:
    import sys
    print(f"[embody.config] {msg}", file=sys.stderr)
