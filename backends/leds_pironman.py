"""leds_pironman.py — Pironman RGB LED backend for hermes-embody.

Drives the Pironman 5 Pro Max case RGB (18× WS2812B) **directly over SPI** so an
agent-state change lights the case **instantly** — no config-file write, no
``pironman5`` CLI, no service restart. This replaces the old CLI-shelling backend
(which wrote a root-owned config and fought pironman's own LED loop).

Implements the shared backend interface (see ``backends/__init__.py``, owned by
the scaffold worker):

    is_available() -> bool        # True iff /dev/spidev0.0 is writable AND the
                                  #   neopixel_spi/board driver imports
    setup(cfg: dict) -> None      # build the state->LED + mood->LED tables
    on_state(state, cfg) -> None  # drive the LEDs to match an agent state
    on_mood(mood, cfg) -> None    # tint the LEDs to match an emotional mood

Pure hardware adapter — no HTTP, no TTS, no agent imports. LEDs are best-effort
cosmetics: every call is wrapped so a missing driver, a busy bus, or a flaky
write can NEVER raise into the agent. On a host without a Pironman (no writable
``/dev/spidev0.0`` or no Blinka driver) this backend is inert: ``is_available()``
is False and ``on_state`` no-ops.

Hardware path (verified on the live Pi 5 / kernel 6.6.74 as the ``spi``-group
user — the *same* code path pironman runs):

    import board, neopixel_spi
    strip = neopixel_spi.NeoPixel_SPI(board.SPI(), 18,
                                      pixel_order=neopixel_spi.GRB,
                                      auto_write=False, brightness=1.0)
    strip.fill((r, g, b)); strip.show()   # the lib re-orders RGB -> GRB on the wire

Pre-req (one-time, handled at deploy): pironman must release the SPI bus — done by
removing ``"ws2812"`` from the Pro Max variant's ``PERIPHERALS`` so its
``WS2812Addon`` never opens ``/dev/spidev0.0``. OLED / dashboard / fans are
unaffected. Two processes cannot both own the bus.

Hardware imports are **lazy** (inside functions) so this module imports/compiles
fine off-Pi, where ``board`` is absent.

Config (from the generic plugin schema)::

    leds:
      brightness: 60                 # optional global default brightness (0-100)
      states:
        idle:     { color: "0044ff", style: "breathing" }
        thinking: { color: "ff9900", style: "flow" }
        ...                          # per-state {color, style[, brightness]}
      moods:                         # OPTIONAL emotional tints (see on_mood)
        happy:    { color: "FFC107" }
        sad:      { color: "2962FF" }
        ...                          # per-mood {color[, brightness]}

Anything missing falls back to the built-in defaults below, so the backend runs
even with an empty/absent config. ``style`` is recorded but **not animated** in
v1 — every state is a solid fill (animation is a v2 background-thread concern).

MOOD vs STATE precedence on the strip
-------------------------------------
``on_state`` and ``on_mood`` drive the *same* 18 LEDs last-write-wins (no blend).
The **resting state IS the mood**: ``on_state("idle")`` resolves the strip to the
CURRENT mood's color (``_MOOD_COLORS[_current_mood]``, default ``neutral`` →
``1E3A5F``), NOT a fixed idle color — so between turns the body persistently
"reflects her mood", matching the face's emotional baseline. The activity states
(thinking/working/speaking/listening) are TRANSIENT overlays: each flashes its own
color while the agent is busy, then the return to ``idle`` settles the case back
onto the mood. ``on_mood`` records the mood in ``_current_mood`` and tints
immediately; core.state's decay timer fades mood→neutral after ``face.mood_hold``
seconds, which now reads as an emotional afterglow on the body. Mood brightness is
*intrinsic* (sad dims, excited brightens) — unlike states, a per-mood base
brightness wins over the global ``leds.brightness`` (see setup()).
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger("embody.backends.leds_pironman")

# Pironman 5 Pro Max case strip: 18 WS2812B on SPI0 (GPIO10/MOSI).
_SPI_DEV = "/dev/spidev0.0"
_LED_COUNT = 18

# Built-in default state -> LED table. Kept as the team default; everything here
# is overridable per-key via cfg["leds"]. color = 6-digit hex WITHOUT '#'.
DEFAULT_STATE_COLORS: dict[str, dict] = {
    "idle":      {"style": "breathing", "color": "0044ff", "brightness": 25},
    "thinking":  {"style": "flow",      "color": "ff9900", "brightness": 60},
    "working":   {"style": "solid",     "color": "8800ff", "brightness": 70},
    "speaking":  {"style": "flow",      "color": "00ff66", "brightness": 80},
    "listening": {"style": "breathing", "color": "00ddff", "brightness": 60},
}

# Built-in default MOOD -> LED table (the persona's *feeling*, independent of
# state). Overridable per-key via cfg["leds"]["moods"]. color = 6-digit hex w/o '#'.
# Brightness is intrinsic to the mood (sad reads dim, excited bright) and — unlike
# states — wins over the global leds.brightness so the nuance survives (see setup).
DEFAULT_MOOD_COLORS: dict[str, dict] = {
    "neutral":   {"color": "1E3A5F", "brightness": 25},
    "happy":     {"color": "FFC107", "brightness": 70},
    "excited":   {"color": "FF6D00", "brightness": 85},
    "loving":    {"color": "FF2D78", "brightness": 75},
    "playful":   {"color": "00E5FF", "brightness": 70},
    "curious":   {"color": "7C4DFF", "brightness": 65},
    "sad":       {"color": "2962FF", "brightness": 45},
    "surprised": {"color": "EAEAEA", "brightness": 80},
    "concerned": {"color": "FF7043", "brightness": 70},
}

# Resolved tables (defaults merged with cfg). None until setup() runs; on_state()/
# on_mood() lazily resolve from their cfg arg if setup() was never called.
_STATE_COLORS: dict[str, dict] | None = None
_MOOD_COLORS: dict[str, dict] | None = None

# Last mood applied via on_mood() — the RESTING color for on_state("idle") so the
# body persistently reflects her mood. Plain module global: a single string
# assignment is GIL-atomic, and it is read OUTSIDE _set_rgb's (non-reentrant)
# _lock, so it needs no extra guard. Defaults to "neutral" => 1E3A5F (≈ the prior
# resting blue), so nothing regresses before any mood is set.
_current_mood: str = "neutral"

# Serialize hardware access so rapid calls from multiple threads produce a clean
# last-write-wins on the strip instead of overlapping SPI transactions.
_lock = threading.Lock()

# Lazy hardware handles / probes (all hardware imports are deferred to runtime so
# this module imports off-Pi). _driver_ok caches the import probe; _strip is the
# NeoPixel_SPI singleton; _init_failed latches a hard init failure -> stay inert.
_driver_ok: bool | None = None
_strip: object | None = None
_init_failed = False
_absent_logged = False


# --------------------------------------------------------------------------- #
# Backend interface
# --------------------------------------------------------------------------- #
def is_available() -> bool:
    """True iff the case strip is drivable here.

    Gate: ``/dev/spidev0.0`` exists AND is writable by us (``jason`` is in the
    ``spi`` group, so no sudo) AND the ``board``/``neopixel_spi`` driver imports.
    """
    if not (os.path.exists(_SPI_DEV) and os.access(_SPI_DEV, os.W_OK)):
        return False
    return _probe_driver()


def setup(cfg: dict | None = None) -> None:
    """Build the resolved state->LED AND mood->LED tables from ``cfg``, with defaults.

    Merge precedence per STATE:
      * style:  cfg state override -> built-in default -> "solid"
      * color:  cfg state override -> built-in default -> "ffffff"
      * brightness: cfg per-state override -> cfg ``leds.brightness`` global
                    -> built-in default -> 60
    Merge precedence per MOOD (note: base brightness wins over the global, so a
    mood's intrinsic intensity isn't flattened by the always-present global):
      * color:  cfg mood override -> built-in default -> "ffffff"
      * brightness: cfg per-mood override -> built-in default
                    -> cfg ``leds.brightness`` global -> 60
    A mood override may be a ``{color[, brightness]}`` dict OR a bare hex string.
    User-defined states/moods not in the defaults are accepted too. Never raises.
    """
    global _STATE_COLORS, _MOOD_COLORS
    cfg = cfg or {}
    leds_cfg = cfg.get("leds") or {}
    global_brightness = leds_cfg.get("brightness")
    states_cfg = leds_cfg.get("states") or {}
    moods_cfg = leds_cfg.get("moods") or {}

    resolved: dict[str, dict] = {}
    for name in set(DEFAULT_STATE_COLORS) | set(states_cfg):
        base = DEFAULT_STATE_COLORS.get(name, {})
        override = states_cfg.get(name) or {}

        style = override.get("style") or base.get("style") or "solid"
        color = _normalize_hex(override.get("color") or base.get("color") or "ffffff")

        if override.get("brightness") is not None:
            brightness = override["brightness"]
        elif global_brightness is not None:
            brightness = global_brightness
        else:
            brightness = base.get("brightness", 60)

        resolved[name] = {
            "style": str(style),
            "color": color,
            "brightness": _clamp_brightness(brightness),
        }

    resolved_moods: dict[str, dict] = {}
    for name in set(DEFAULT_MOOD_COLORS) | set(moods_cfg):
        base = DEFAULT_MOOD_COLORS.get(name, {})
        override = moods_cfg.get(name)
        if isinstance(override, str):           # bare hex string shorthand
            override = {"color": override}
        elif not isinstance(override, dict):
            override = {}

        color = _normalize_hex(override.get("color") or base.get("color") or "ffffff")

        if override.get("brightness") is not None:
            brightness = override["brightness"]
        elif base.get("brightness") is not None:   # mood intensity is intrinsic
            brightness = base["brightness"]
        elif global_brightness is not None:
            brightness = global_brightness
        else:
            brightness = 60

        resolved_moods[name] = {
            "color": color,
            "brightness": _clamp_brightness(brightness),
        }

    with _lock:
        _STATE_COLORS = resolved
        _MOOD_COLORS = resolved_moods


def on_state(state: str, cfg: dict | None = None) -> None:
    """Set the LEDs to match ``state``. Best-effort; never raises.

    The RESTING state is the mood: ``state == "idle"`` resolves to the CURRENT
    mood's color (``_MOOD_COLORS[_current_mood]``, default neutral) so the body
    persistently reflects her mood between turns instead of snapping to a fixed
    idle color. The activity states (thinking/working/speaking/listening) are
    transient overlays, driven by their own colors while the agent is busy.

    Unknown/unmapped states are silent no-ops (the strip keeps its last color).
    A host without a drivable strip is inert. Safe to call rapidly from any thread.
    """
    if not is_available():
        return

    table = _STATE_COLORS
    if table is None:
        # setup() was never called — resolve from this call's cfg (fills moods too).
        try:
            setup(cfg)
        except Exception:  # noqa: BLE001 — config resolution must never crash the agent.
            logger.debug("led setup() failed (ignored).", exc_info=True)
            return
        table = _STATE_COLORS or {}

    # Resting state -> settle on the CURRENT mood color (the persistent baseline),
    # NOT the idle state color. _MOOD_COLORS is populated alongside _STATE_COLORS
    # by setup(), so it is non-None here whenever the state table is.
    if state == "idle":
        moods = _MOOD_COLORS or {}
        mood_params = moods.get(_current_mood) or moods.get("neutral")
        if mood_params:
            _set_rgb(mood_params["color"], mood_params["brightness"])
            return
        # mood table somehow empty -> fall through to the idle state color below.

    params = table.get(state)
    if not params:
        return  # unknown state -> no-op (leave strip as-is)
    _set_rgb(params["color"], params["brightness"])


def on_mood(mood: str, cfg: dict | None = None) -> None:
    """Tint the LEDs to match an emotional ``mood`` AND record it as the resting
    baseline. Best-effort; never raises.

    First records ``mood`` in module-level ``_current_mood`` (coerced to one of the
    nine known moods; ``neutral`` on anything else) so a later ``on_state("idle")``
    settles the body back onto it — this is what makes the case *rest* on her mood
    rather than the idle color (see the module precedence note). The mood is
    recorded even on an inert host, so a strip that later becomes drivable still
    reflects the last mood. Then tints the strip immediately. An unknown/unmapped
    mood falls back to the ``neutral`` tint. Safe to call rapidly from any thread.
    """
    global _current_mood
    # Record FIRST (top of on_mood, per the resting-mood contract). A single string
    # assignment is GIL-atomic and read outside _set_rgb's non-reentrant _lock, so
    # no extra guard is needed. neutral-fallback coercion against the known 9 moods.
    _current_mood = mood if mood in DEFAULT_MOOD_COLORS else "neutral"

    if not is_available():
        return

    table = _MOOD_COLORS
    if table is None:
        # setup() was never called — resolve from this call's cfg.
        try:
            setup(cfg)
        except Exception:  # noqa: BLE001 — config resolution must never crash the agent.
            logger.debug("led setup() failed (ignored).", exc_info=True)
            return
        table = _MOOD_COLORS or {}

    params = table.get(_current_mood) or table.get("neutral")
    if not params:
        return  # no mapping at all -> no-op (leave strip as-is)
    _set_rgb(params["color"], params["brightness"])


# --------------------------------------------------------------------------- #
# Internals (the only place that knows the SPI / WS2812 driver)
# --------------------------------------------------------------------------- #
def _probe_driver() -> bool:
    """Cache-check whether the Blinka neopixel_spi driver imports on this host."""
    global _driver_ok, _absent_logged
    if _driver_ok is not None:
        return _driver_ok
    try:
        import board  # noqa: F401  (Blinka — Pi-only)
        import neopixel_spi  # noqa: F401
        _driver_ok = True
    except Exception:  # noqa: BLE001 — off-Pi this is expected; backend goes inert.
        _driver_ok = False
        if not _absent_logged:
            logger.debug("neopixel_spi/board unavailable; LED backend inert.", exc_info=True)
            _absent_logged = True
    return _driver_ok


def _ensure_strip() -> object | None:
    """Lazily build the NeoPixel_SPI singleton. Caller must hold ``_lock``.

    Returns the strip handle, or None if init failed (then the backend is inert
    for the rest of the process — never retried, never raises).
    """
    global _strip, _init_failed
    if _strip is not None or _init_failed:
        return _strip
    try:
        import board
        import neopixel_spi as neopixel

        # brightness=1.0: we scale colors manually (like pironman) to avoid
        # double-dimming. auto_write=False: every change needs an explicit show().
        _strip = neopixel.NeoPixel_SPI(
            board.SPI(),
            _LED_COUNT,
            pixel_order=neopixel.GRB,
            auto_write=False,
            brightness=1.0,
        )
    except Exception:  # noqa: BLE001 — LEDs are best-effort; never crash the agent.
        _init_failed = True
        _strip = None
        logger.debug("LED strip init failed; backend inert.", exc_info=True)
    return _strip


def _set_rgb(color: str, brightness: int) -> None:
    """Solid-fill all 18 LEDs with ``color`` scaled by ``brightness`` (0-100).

    Best-effort, thread-safe (last-write-wins), never raises. v1 ignores ``style``
    (solid fill only). A 162-byte SPI write is sub-millisecond → instant.
    """
    rgb = _hex_to_rgb(color)
    if rgb is None:
        return
    # Scale like pironman's ws2812 addon: color * brightness%; clamp to a byte.
    scaled = tuple(max(0, min(255, int(x * brightness * 0.01))) for x in rgb)
    try:
        with _lock:
            strip = _ensure_strip()
            if strip is None:
                return
            strip.fill(scaled)   # NeoPixel_SPI re-orders RGB -> GRB on the wire
            strip.show()
    except Exception:  # noqa: BLE001 — LEDs are best-effort; never crash the agent.
        logger.debug("LED SPI write failed (ignored).", exc_info=True)


def _hex_to_rgb(value: object) -> tuple[int, int, int] | None:
    """Parse a 6-digit hex color (with/without '#') into an (r, g, b) tuple.

    Returns None on malformed input so the caller no-ops instead of raising.
    """
    h = _normalize_hex(value)
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _normalize_hex(value: object) -> str:
    """Coerce a color to a bare 6-ish-digit hex string (strip '#'/whitespace)."""
    return str(value).strip().lstrip("#")


def _clamp_brightness(value: object) -> int:
    """Coerce brightness to an int in [0, 100]; fall back to 60 on bad input."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 60
    return max(0, min(100, n))


__all__ = [
    "is_available", "setup", "on_state", "on_mood",
    "DEFAULT_STATE_COLORS", "DEFAULT_MOOD_COLORS",
]
