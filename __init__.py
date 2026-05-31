"""embody — Hermes embodiment plugin (entrypoint).

A persona- and hardware-agnostic plugin: an animated face in a browser + optional
auto-detected hardware (Pironman LEDs) + TTS voice, all driven by the agent's
per-turn state. Everything is read from ``config.yaml`` with defaults for every
key, so it runs on a bare Hermes box as face-in-browser + TTS. "Minnie" is just
an example instance (``examples/minnie/config.yaml``).

Per-turn state wiring (hooks fire in the gateway too):

    on_session_start -> idle
    pre_llm_call     -> thinking
    pre_tool_call    -> working
    post_tool_call   -> thinking      (loop may issue more tool calls)
    post_llm_call    -> speak (async) ; "speaking" on start, "idle" on done
    on_session_end   -> idle

The face is a VOICE-only surface: every per-turn reaction above (state + mood +
TTS) is gated to the platforms in ``voice.speak_platforms`` (default ``webhook``,
the voice/PTT route). Non-voice turns — cron, telegram, cli, memory/housekeeping,
background turns — leave the face idle and silent. ``pre_llm_call``/``post_llm_call``
carry ``platform`` and gate on it directly; the tool hooks don't, so they recognize
a voice turn via a per-turn ``session_id``/``task_id`` -> platform map seeded by the
earlier ``pre_llm_call`` + ``pre_api_request`` hooks (see ``_remember_turn``).

Speech happens in post_llm_call (NOT transform_llm_output, which would replace
the reply and serialize the user-facing response behind the whole speech
duration). Playback runs on its own thread (core.voice.speak_async).

All hook callbacks are **kwargs-tolerant — kwargs differ per hook.
"""
from __future__ import annotations

import threading

from . import backends as _backends
from .core import config as _config
from .core import controls as _controls
from .core import mood as _mood
from .core import state as _state
from .core import voice as _voice
from .core import voice_input as _voice_input


# Map known tool names -> friendly activity labels shown on the face wordmark
# while "working". Unknown tools fall back to f"{tool_name}…" (see _tool_status).
_TOOL_STATUS = {
    "web_search":     "searching the web…",
    "search":         "searching the web…",
    "execute_code":   "running code…",
    "code_execution": "running code…",
    "computer_use":   "browsing…",
    "cronjob":        "scheduling…",
    "delegate_task":  "delegating…",
    "read_file":      "working with files…",
    "write_file":     "working with files…",
}


# Platforms the embody FACE reacts to — i.e. whose turns drive the per-turn state
# machine (thinking/working/speaking + mood) AND TTS. The face is a VOICE-only surface:
# the voice/PTT path rides the Hermes "webhook" platform (voice_input POSTs the
# transcript to /webhooks/<route>, which runs a real agent turn whose lifecycle hooks
# fire), so by DEFAULT only "webhook" turns animate her. Everything else —
# cron/scheduler ("silenced"), memory-injection/housekeeping ("nothing to save"),
# telegram, cli, and background/system turns (often with NO platform) — leaves the face
# idle and silent. Overridable via the embody config key `voice.speak_platforms`;
# populated from config in register(), with this safe default in force before/without
# config.
_EMBODY_PLATFORMS = {"webhook"}


def _resolve_embody_platforms(cfg) -> set:
    """Read the face/voice platform allowlist from ``voice.speak_platforms``
    (default ``["webhook"]``). Accepts a single string or a list; values are
    lowercased + stripped. Falls back to ``{"webhook"}`` on anything unexpected so
    a bad config can never make her animate (or go silent) incorrectly."""
    try:
        voice_cfg = cfg.get("voice", {}) if isinstance(cfg, dict) else {}
        raw = voice_cfg.get("speak_platforms", ["webhook"])
        if isinstance(raw, str):
            raw = [raw]
        platforms = {str(p).strip().lower() for p in raw if str(p).strip()}
        return platforms or {"webhook"}
    except Exception:  # noqa: BLE001 — config quirks must never break the hook wiring.
        return {"webhook"}


# --- per-turn platform map: gate the TOOL hooks, which never receive `platform` ----
# pre_tool_call / post_tool_call fire with `session_id` + `task_id` but NO `platform`
# (verified in the gateway core), so they can't gate on platform directly. Instead we
# remember each VOICE turn's platform keyed by BOTH ids the moment a hook that *does*
# carry platform fires earlier in the same turn (pre_llm_call has session_id+platform;
# pre_api_request has session_id+task_id+platform and fires before any tool call). The
# tool hooks then look the turn up by either id. Only allowlisted (voice) turns are
# ever recorded, so a miss == not-voice == leave the face idle.
_turn_lock = threading.Lock()
_turn_platform: dict = {}          # {session_id|task_id: <allowlisted platform>}
_TURN_MAP_CAP = 512                 # hard bound; task_id keys can't be popped on session_end


def _remember_turn(platform, session_id="", task_id="") -> None:
    """Record an ALLOWLISTED turn's platform under whichever of session_id/task_id are
    non-empty, so the platform-less tool hooks can recognize it. No-op for non-voice
    platforms (never recorded → tool hooks treat them as idle). Best-effort; the cap
    evicts oldest-touched keys so a long-lived gateway can't grow this unbounded."""
    p = str(platform or "").strip().lower()
    if p not in _EMBODY_PLATFORMS:
        return
    with _turn_lock:
        for key in (session_id, task_id):
            k = str(key or "").strip()
            if k:
                _turn_platform.pop(k, None)   # re-insert at end => LRU-ish recency
                _turn_platform[k] = p
        while len(_turn_platform) > _TURN_MAP_CAP:
            try:
                _turn_platform.pop(next(iter(_turn_platform)), None)
            except StopIteration:
                break


def _turn_is_embodied(session_id="", task_id="") -> bool:
    """True iff this turn (by session_id OR task_id) was recorded as an allowlisted
    voice turn — i.e. the face should animate for its tool calls."""
    with _turn_lock:
        for key in (session_id, task_id):
            k = str(key or "").strip()
            if k and _turn_platform.get(k, "") in _EMBODY_PLATFORMS:
                return True
    return False


def _forget_turn(session_id="", task_id="") -> None:
    """Drop a turn's map entries (called on session end). task_id is usually absent
    there; the size cap reaps any task_id keys that outlive their turn."""
    with _turn_lock:
        for key in (session_id, task_id):
            k = str(key or "").strip()
            if k:
                _turn_platform.pop(k, None)


def _tool_status(tool_name: str) -> str:
    """Friendly 'what am I doing' label for a tool call."""
    if not tool_name:
        return "working…"
    key = str(tool_name).lower()
    if key in _TOOL_STATUS:
        return _TOOL_STATUS[key]
    if key.startswith("browser"):
        return "browsing…"
    return f"{tool_name}…"


def _on_session_start(**kw):
    _state.set_state("idle")                              # no status -> face shows the persona name
    _state.set_mood("neutral")                            # fresh session starts emotionally neutral


def _on_pre_llm(platform="", session_id="", **kw):
    # Face is voice-only: a non-voice turn must NOT drive "thinking". Its post_llm_call
    # is gated too, so nothing would ever reset the state → it'd stick on "thinking".
    # Gate here with the SAME allowlist + same empty/unknown=not-spoken rule as
    # _on_post_llm. (pre_llm_call passes `platform`+`session_id`; confirmed in core.)
    if str(platform or "").strip().lower() not in _EMBODY_PLATFORMS:
        return
    _remember_turn(platform, session_id)   # seed the tool-hook map (no task_id here)
    _state.set_state("thinking", status="thinking…")


def _on_pre_api(platform="", session_id="", task_id="", **kw):
    # Pure recorder (touches NO face state). pre_api_request is the only pre-tool hook
    # carrying platform + session_id + task_id together, and it fires before any tool
    # call, so it seeds BOTH map keys — the task_id fallback that keeps a VOICE tool
    # call showing "working" even if session_id is empty/mismatched on that path.
    _remember_turn(platform, session_id, task_id)


def _on_pre_tool(tool_name="", session_id="", task_id="", **kw):
    # No `platform` on this hook — recognize voice turns via the per-turn map instead.
    if not _turn_is_embodied(session_id, task_id):
        return
    _state.set_state("working", status=_tool_status(tool_name))


def _on_post_tool(tool_name="", session_id="", task_id="", **kw):
    if not _turn_is_embodied(session_id, task_id):
        return
    _state.set_state("thinking", status="thinking…")      # back to thinking; loop may issue more tools


def _on_post_llm(assistant_response="", platform="", **kw):
    # Only the VOICE surface speaks aloud. post_llm_call fires every turn on EVERY
    # platform — cron/scheduler ("silenced"), memory-injection/housekeeping ("nothing
    # to save", which also cut off live audio), telegram, cli, and background/system
    # turns (often with NO platform). Gate at the TOP so non-voice turns drive NEITHER
    # TTS nor the speaking/idle state. Empty/unknown platform is treated as NOT spoken
    # (background turns frequently carry no platform). Allowlist is config-driven via
    # voice.speak_platforms (default {"webhook"} — the voice/PTT route's platform).
    if str(platform or "").strip().lower() not in _EMBODY_PLATFORMS:
        return

    # Infer + broadcast the emotional MOOD from the reply, INDEPENDENT of state.
    # set_mood is best-effort (coerces/never raises), so this can never break speech.
    _state.set_mood(_mood.infer_mood(assistant_response))

    # SPEAK here (NOT transform_llm_output). Fire-and-forget so the loop isn't blocked.
    _voice.speak_async(
        assistant_response,
        on_start=lambda: _state.set_state("speaking"),
        on_done=lambda: _state.set_state("idle"),
    )


def _on_session_end(session_id="", task_id="", **kw):
    _state.set_state("idle")
    _forget_turn(session_id, task_id)   # reap this session's platform-map entries


def register(ctx) -> None:
    """Hermes plugin entrypoint. Called once at gateway start (and per CLI session)."""
    cfg = _config.load_config()
    global _EMBODY_PLATFORMS
    _EMBODY_PLATFORMS = _resolve_embody_platforms(cfg)  # which platforms drive the face (state + TTS)
    backends = _backends.get_active_backends(cfg)   # auto-detected state backends (LEDs/null/...)
    _state.configure(cfg, backends)
    _voice.configure(cfg)
    _voice_input.configure(cfg)                     # PTT voice INPUT (record->STT->webhook inject)
    _controls.set_ptt_callback(_voice_input.on_ptt) # /control/ptt start/stop -> record/transcribe/inject
    _state.start_server()                           # daemon thread: face + /events + /config

    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("pre_llm_call",   _on_pre_llm)
    ctx.register_hook("pre_api_request", _on_pre_api)   # recorder only: seeds the tool-hook platform map
    ctx.register_hook("pre_tool_call",  _on_pre_tool)
    ctx.register_hook("post_tool_call", _on_post_tool)
    ctx.register_hook("post_llm_call",  _on_post_llm)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_command(
        "embody",
        handler=_state.slash_handler,
        description="embody face/LED control",
        args_hint="state|face|test",
    )
