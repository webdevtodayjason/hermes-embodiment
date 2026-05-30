"""embody.backends — backend interface + auto-detect registry (the cross-worker seam).

THE BACKEND INTERFACE (canonical, as-built)
-------------------------------------------
A *state backend* is a **module** in this package that exposes three module-level
functions. (This is the shape the hardware workers actually ship — e.g.
``leds_pironman.py`` and ``null.py`` — so it is the single source of truth. There
is no base class to subclass.)

    is_available() -> bool
        True iff this backend can run here (e.g. the `pironman5` CLI is on PATH).
        Environment-based; takes no args. The auto-detect gate.

    setup(cfg: dict) -> None
        Prepare the backend from the loaded config. Called once at register().
        Must never raise.

    on_state(state: str, cfg: dict) -> None
        Drive the hardware to match an agent state
        ("idle" | "thinking" | "working" | "speaking" | "listening").
        Called from core.state.set_state() on every transition. Must never raise.

A module WITHOUT a callable ``on_state`` is not a state backend and is ignored by
discovery — that is how ``audio.py`` (which exposes ``play()``, not ``on_state``)
stays out of the state-dispatch list without a hand-maintained skip-list.

CONFIG GATING
-------------
``get_active_backends(cfg)`` disables a backend if the config section named after
its module prefix turns it off, e.g. ``leds.backend: "off"`` (or ``enabled: false``)
disables ``leds_pironman``. ``null`` has no matching section, so it is never gated
off — it is the universal no-op fallback.

AUDIO
-----
Audio is handled separately (it has ``play(path, cfg)``, not ``on_state``): see
``embody.backends.audio``, called by ``core.voice``.
"""
from __future__ import annotations

import importlib
import pkgutil

# state vocabulary (the cross-worker contract shared by core.state and face-ui)
VALID_STATES = ("idle", "thinking", "working", "speaking", "listening")

# modules in this package that are transport/helpers, never state backends
_NON_STATE_MODULES = {"audio"}

# discovered {module_name: module}, populated lazily by _discover()
_module_backends: "dict[str, object]" = {}
_discovered = False


class _ModuleBackend:
    """Adapter wrapping a backend MODULE so callers have a uniform object."""

    def __init__(self, name: str, module: object):
        self.name = name
        self.config_section = name.split("_", 1)[0]   # "leds_pironman" -> "leds"
        self._module = module

    def is_available(self) -> bool:
        fn = getattr(self._module, "is_available", None)
        return bool(fn()) if callable(fn) else True

    def setup(self, cfg: dict) -> None:
        fn = getattr(self._module, "setup", None)
        if callable(fn):
            fn(cfg)

    def on_state(self, state: str, cfg: dict) -> None:
        fn = getattr(self._module, "on_state", None)
        if callable(fn):
            fn(state, cfg)


def _discover() -> None:
    """Import every submodule once; record those exposing a callable on_state()."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    for modinfo in pkgutil.iter_modules(__path__):
        name = modinfo.name
        if name.startswith("_") or name in _NON_STATE_MODULES:
            continue
        try:
            module = importlib.import_module(f"{__name__}.{name}")
        except Exception as exc:  # a broken/incomplete backend must not kill discovery
            _warn(f"backend module {name!r} failed to import: {exc}")
            continue
        if callable(getattr(module, "on_state", None)):
            _module_backends[name] = module


def get_active_backends(cfg: dict) -> "list[_ModuleBackend]":
    """Return the state backends that are enabled by config AND available here.

    For each, ``setup(cfg)`` has already been called. ``core.state.set_state()``
    calls ``on_state(state, cfg)`` on each returned backend.
    """
    _discover()
    active: "list[_ModuleBackend]" = []
    for name in sorted(_module_backends):
        backend = _ModuleBackend(name, _module_backends[name])

        # config gate: <section>.backend == "off" or <section>.enabled == False
        section = cfg.get(backend.config_section) if isinstance(cfg, dict) else None
        if isinstance(section, dict) and (
            section.get("backend") == "off" or section.get("enabled") is False
        ):
            continue

        try:
            if not backend.is_available():
                continue
        except Exception as exc:  # pragma: no cover - defensive
            _warn(f"{name}.is_available() raised: {exc}")
            continue

        try:
            backend.setup(cfg)
        except Exception as exc:  # pragma: no cover - defensive
            _warn(f"{name}.setup() raised: {exc}")
            continue

        active.append(backend)
    return active


def _warn(msg: str) -> None:
    import sys
    print(f"[embody.backends] {msg}", file=sys.stderr)
