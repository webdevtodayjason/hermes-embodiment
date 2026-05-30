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

Speech happens in post_llm_call (NOT transform_llm_output, which would replace
the reply and serialize the user-facing response behind the whole speech
duration). Playback runs on its own thread (core.voice.speak_async).

All hook callbacks are **kwargs-tolerant — kwargs differ per hook.
"""
from __future__ import annotations

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


def _on_pre_llm(**kw):
    _state.set_state("thinking", status="thinking…")


def _on_pre_tool(tool_name="", **kw):
    _state.set_state("working", status=_tool_status(tool_name))


def _on_post_tool(tool_name="", **kw):
    _state.set_state("thinking", status="thinking…")      # back to thinking; loop may issue more tools


def _on_post_llm(assistant_response="", platform="", **kw):
    # Infer + broadcast the emotional MOOD from the reply, INDEPENDENT of state.
    # set_mood is best-effort (coerces/never raises), so this can never break speech.
    _state.set_mood(_mood.infer_mood(assistant_response))

    # SPEAK here (NOT transform_llm_output). Fire-and-forget so the loop isn't blocked.
    # post_llm_call fires every turn on every platform; first-light is a single kiosk
    # surface so we speak unconditionally. Filter on `platform` if other platforms attach.
    _voice.speak_async(
        assistant_response,
        on_start=lambda: _state.set_state("speaking"),
        on_done=lambda: _state.set_state("idle"),
    )


def _on_session_end(**kw):
    _state.set_state("idle")


def register(ctx) -> None:
    """Hermes plugin entrypoint. Called once at gateway start (and per CLI session)."""
    cfg = _config.load_config()
    backends = _backends.get_active_backends(cfg)   # auto-detected state backends (LEDs/null/...)
    _state.configure(cfg, backends)
    _voice.configure(cfg)
    _voice_input.configure(cfg)                     # PTT voice INPUT (record->STT->webhook inject)
    _controls.set_ptt_callback(_voice_input.on_ptt) # /control/ptt start/stop -> record/transcribe/inject
    _state.start_server()                           # daemon thread: face + /events + /config

    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("pre_llm_call",   _on_pre_llm)
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
