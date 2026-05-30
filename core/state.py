"""embody.core.state — state transport: HTTP + SSE server, and set_state() fan-out.

Started inside ``register()`` on a **daemon thread** with its own loop
(stdlib ``http.server`` + a per-subscriber queue). Deliberately NOT coupled to
the gateway's asyncio loop — a blocking server in the main loop would stall the
agent.

Endpoints
---------
  GET /            -> the face page (static files from the sibling ``face/`` dir;
                      an in-memory fallback page if face/ isn't built yet)
  GET /events      -> Server-Sent-Events stream of state changes
  GET /state.json  -> current state (poll fallback)
  GET /config      -> persona/theme JSON for the face-ui (see below)

Contracts (must match the other workers exactly)
-------------------------------------------------
  * State vocabulary: "idle" | "thinking" | "working" | "speaking" | "listening"
  * Mood vocabulary (INDEPENDENT of state; default "neutral"): "neutral" |
    "happy" | "excited" | "loving" | "playful" | "curious" | "sad" | "surprised"
    | "concerned"  (see embody.core.mood for inference).
  * SSE messages:  ``data: {"state": "<name>", "status": <s>, "mood": "<m>"}\\n\\n``
    EVERY broadcast — from set_state() AND set_mood() — carries the CURRENT mood,
    so a face that connects mid-stream never misses it. Absent/extra keys stay
    backward-compatible (a consumer reading only ``state`` is unaffected).
  * /config JSON:  ``{"persona": {...}, "theme": <face.theme>, "states": [...],
    "moods": [...]}``. NOTE: face.js reads the theme as a TOP-LEVEL ``theme`` key
    (not face.theme), so we flatten ``config.face.theme`` up to ``theme`` here.
  * Hardware fan-out: set_state() calls ``on_state(name, cfg)`` and set_mood()
    calls ``on_mood(mood, cfg)`` on every active backend (best-effort; a backend
    error never escapes). See embody.backends.get_active_backends.
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VALID_STATES = ("idle", "thinking", "working", "speaking", "listening")

# Mood vocabulary (the locked cross-worker contract; default "neutral"). Mood is
# the persona's *feeling*, INDEPENDENT of the activity STATE. Order matters: it is
# the order config_payload() reports under "moods". Mirrors core.mood.MOODS.
VALID_MOODS = (
    "neutral", "happy", "excited", "loving",
    "playful", "curious", "sad", "surprised", "concerned",
)

# face/ is a sibling of the plugin root (parent of this core/ package)
FACE_DIR = str(Path(__file__).resolve().parent.parent / "face")

# --- runtime state (set by configure(); safe defaults so set_state never KeyErrors)
_cfg: dict = {}
_backends: list = []

_state_lock = threading.Lock()
_current_state = "idle"
_current_status = None   # optional human-friendly activity label (e.g. "searching the web…")
_current_mood = "neutral"   # persona feeling; updated by set_mood(), guarded by _state_lock

# Mood decay: revert to "neutral" after face.mood_hold seconds of no new mood, so
# a one-off reaction fades instead of sticking. Guarded by its own lock (never
# nested under _state_lock) so the daemon Timer can re-enter set_mood() safely.
_mood_timer_lock = threading.Lock()
_mood_timer: "threading.Timer | None" = None

_subscribers_lock = threading.Lock()
_subscribers: "set[queue.Queue]" = set()

_server = None  # StateServer singleton


# =============================================================================
# Public module API
# =============================================================================
def configure(cfg: dict, backends=None) -> None:
    """Install the loaded config and the active hardware backends."""
    global _cfg, _backends
    _cfg = cfg or {}
    _backends = list(backends or [])


def set_state(name: str, status=None) -> str:
    """Set the embodiment state: push it to the face (SSE) and to every backend.

    ``status`` is an OPTIONAL human-friendly activity label (e.g. "searching the
    web…"). It is carried in the SSE payload and /state.json so the face can show
    WHAT the agent is doing, then revert to the persona name when status is None.
    Backwards-compatible: ``status=None`` emits ``"status": null`` (ignored by any
    consumer that only reads ``state``).

    Safe to call before the server starts and with zero subscribers. Unknown
    states are ignored (with a warning) so a typo never drives an undefined face.
    """
    global _current_state, _current_status
    if name not in VALID_STATES:
        _warn(f"ignoring unknown state {name!r}; valid: {', '.join(VALID_STATES)}")
        return _current_state

    with _state_lock:
        _current_state = name
        _current_status = status
        mood = _current_mood   # carry the current mood in EVERY broadcast

    # 1) push to all connected faces (SSE) — mood rides along so a late-joining
    #    face stays in sync even when only the state changed.
    _broadcast(json.dumps({"state": name, "status": status, "mood": mood}))

    # 2) drive hardware backends (never let a backend crash the hook)
    #    (backends react to `state` only; `status` is a face-only concern)
    for backend in _backends:
        try:
            backend.on_state(name, _cfg)
        except Exception as exc:  # pragma: no cover - defensive
            _warn(f"backend {getattr(backend, 'name', '?')}.on_state({name!r}) failed: {exc}")

    return name


def set_mood(mood: str) -> str:
    """Set the embodiment MOOD: push it to the face (SSE) and to every backend.

    Mood is the persona's *feeling* and is INDEPENDENT of the activity STATE — it
    tints the face/LEDs between (and during) activity transitions. An unknown mood
    is coerced to ``"neutral"`` (never an error), so a bad inference or typo can't
    drive an undefined expression.

    The broadcast carries the CURRENT state/status plus the new mood
    (``{"state", "status", "mood"}``) so a face only ever needs one event shape.
    Backends are driven via ``on_mood(mood, cfg)`` — best-effort, exactly like
    ``on_state``. Returns the mood actually applied (post-coercion).

    Safe to call before the server starts and with zero subscribers/backends.
    """
    global _current_mood
    if mood not in VALID_MOODS:
        mood = "neutral"

    with _state_lock:
        _current_mood = mood
        state = _current_state
        status = _current_status

    # 1) push to all connected faces (SSE) with the current state/status + new mood
    _broadcast(json.dumps({"state": state, "status": status, "mood": mood}))

    # 2) drive hardware backends (never let a backend crash the hook)
    for backend in _backends:
        try:
            backend.on_mood(mood, _cfg)
        except Exception as exc:  # pragma: no cover - defensive
            _warn(f"backend {getattr(backend, 'name', '?')}.on_mood({mood!r}) failed: {exc}")

    # 3) (re)arm the decay-to-neutral timer so a one-off reaction fades
    _arm_mood_decay(mood)

    return mood


def current_state() -> str:
    with _state_lock:
        return _current_state


def current_mood() -> str:
    with _state_lock:
        return _current_mood


def snapshot() -> dict:
    """Current {state, status, mood} — used by /state.json AND the SSE connect-sync frame."""
    with _state_lock:
        return {"state": _current_state, "status": _current_status, "mood": _current_mood}


def start_server() -> "StateServer":
    """Start the daemon-thread state server (idempotent). Host/port come from config."""
    global _server
    face = _cfg.get("face", {}) if isinstance(_cfg, dict) else {}
    host = face.get("host", "127.0.0.1")
    port = int(face.get("port", 8830))
    if _server is None:
        _server = StateServer(host, port)
    _server.start()
    return _server


def stop_server() -> None:
    """Stop the state server if running (used by tests/smoke checks)."""
    global _server
    if _server is not None:
        _server.stop()
        _server = None


def config_payload() -> dict:
    """The /config response: persona + flattened theme for the face-ui."""
    persona = _cfg.get("persona", {}) if isinstance(_cfg, dict) else {}
    face = _cfg.get("face", {}) if isinstance(_cfg, dict) else {}
    return {
        "persona": {
            "name": persona.get("name", "Assistant"),
            "wake_word": persona.get("wake_word", ""),
        },
        "theme": face.get("theme", "default"),   # TOP-LEVEL for face.js (cfg.theme)
        "states": list(VALID_STATES),
        "moods": list(VALID_MOODS),
    }


def slash_handler(raw_args: str) -> str:
    """Handler for the ``/embody`` slash command:  state | mood | face | test."""
    args = (raw_args or "").strip().split()
    if not args:
        return _status_text()

    cmd = args[0].lower()

    if cmd == "state":
        if len(args) >= 2:
            target = args[1].lower()
            if target in VALID_STATES:
                set_state(target)
                return f"embody state set to '{target}'."
            return f"Unknown state '{target}'. Valid: {', '.join(VALID_STATES)}."
        return _status_text()

    if cmd == "mood":
        # explicit MOOD override (bypasses inference). Unknown -> coerced to neutral.
        if len(args) >= 2:
            target = args[1].lower()
            applied = set_mood(target)
            if target not in VALID_MOODS:
                return (f"Unknown mood '{target}', coerced to '{applied}'. "
                        f"Valid: {', '.join(VALID_MOODS)}.")
            return f"embody mood set to '{applied}'."
        return _status_text()

    if cmd == "face":
        host, port = _host_port()
        return f"embody face: http://{host}:{port}/  (stream: /events, poll: /state.json, cfg: /config)"

    if cmd == "test":
        threading.Thread(target=_run_test_cycle, name="embody-test", daemon=True).start()
        return "embody test: cycling thinking->working->speaking->idle (~4s)."

    return "Usage: /embody [state <name> | mood <name> | face | test]"


# =============================================================================
# Internals
# =============================================================================
def _host_port():
    face = _cfg.get("face", {}) if isinstance(_cfg, dict) else {}
    return face.get("host", "127.0.0.1"), int(face.get("port", 8830))


def _mood_hold_seconds() -> float:
    """How long a non-neutral mood lingers before decaying to neutral (config-driven)."""
    face = _cfg.get("face", {}) if isinstance(_cfg, dict) else {}
    try:
        return float(face.get("mood_hold", 8))
    except (TypeError, ValueError):
        return 8.0


def _arm_mood_decay(mood: str) -> None:
    """(Re)arm the decay timer that reverts the mood to "neutral".

    Cancels any pending timer first (newest mood wins), then — for a non-neutral
    mood with a positive hold — starts a fresh daemon ``threading.Timer``. Setting
    "neutral" simply disarms (no timer armed). Best-effort: a timer failure is
    swallowed so a mood set can never crash a turn. Daemon => never blocks exit.
    """
    global _mood_timer
    with _mood_timer_lock:
        if _mood_timer is not None:
            _mood_timer.cancel()
            _mood_timer = None
        if mood == "neutral":
            return
        hold = _mood_hold_seconds()
        if hold <= 0:
            return
        try:
            timer = threading.Timer(hold, _decay_to_neutral)
            timer.daemon = True
            _mood_timer = timer
            timer.start()
        except Exception as exc:  # pragma: no cover - defensive
            _warn(f"failed to arm mood decay timer: {exc}")
            _mood_timer = None


def _decay_to_neutral() -> None:
    """Timer callback: fade back to neutral. (set_mood re-enters _arm_mood_decay,
    which disarms cleanly because the mood is "neutral".)"""
    set_mood("neutral")


def _broadcast(data_str: str) -> None:
    with _subscribers_lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(data_str)
        except queue.Full:  # slow/stuck client — drop rather than block set_state
            pass


def _status_text() -> str:
    host, port = _host_port()
    with _subscribers_lock:
        n = len(_subscribers)
    names = ", ".join(getattr(b, "name", "?") for b in _backends) or "(none)"
    return (
        f"embody state: '{current_state()}' | mood: '{current_mood()}' "
        f"| face: http://{host}:{port}/ | SSE clients: {n} | backends: {names}"
    )


def _run_test_cycle() -> None:
    import time
    for s in ("thinking", "working", "speaking", "idle"):
        set_state(s)
        time.sleep(1.0)


def _warn(msg: str) -> None:
    import sys
    print(f"[embody.state] {msg}", file=sys.stderr)


# Minimal in-memory face shown when the sibling face/ app isn't built yet.
# (face-ui owns face/*; this is a string, not a file, so it doesn't create one.)
_FALLBACK_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>embody</title>
<style>
 html,body{height:100%;margin:0;background:#0b0f17;color:#e6edf3;
   font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 .wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1rem}
 #state{font-size:clamp(2rem,10vw,6rem);font-weight:700;letter-spacing:.04em;text-transform:uppercase}
 .dot{width:.6em;height:.6em;border-radius:50%;display:inline-block;margin-right:.3em;
   background:currentColor;box-shadow:0 0 1.5em currentColor}
 .idle{color:#3a78c2}.thinking{color:#ffb000}.working{color:#a060ff}
 .speaking{color:#00c853}.listening{color:#ff5d8f}
 small{opacity:.5}
</style></head>
<body><div class="wrap">
 <div id="state" class="idle"><span class="dot"></span><span id="label">idle</span></div>
 <small>embody state monitor (fallback page) &mdash; awaiting face app</small>
</div>
<script>
 var el=document.getElementById('state'),label=document.getElementById('label');
 function apply(s){el.className=s;label.textContent=s;}
 function connect(){var es=new EventSource('/events');
  es.onmessage=function(e){try{apply(JSON.parse(e.data).state);}catch(x){}};
  es.onerror=function(){es.close();setTimeout(connect,1000);};}
 connect();
</script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    """Per-connection request handler (one thread each under ThreadingHTTPServer)."""

    server_version = "embodyState/0.1"

    def log_message(self, *args):  # silence default stderr access log
        pass

    def do_GET(self):  # noqa: N802 (stdlib naming)
        path = urllib.parse.urlparse(self.path).path
        if path == "/events":
            self._handle_events()
        elif path == "/state.json":
            self._send_json(snapshot())
        elif path == "/config":
            self._send_json(config_payload())
        elif path in ("", "/"):
            self._serve_static("index.html")
        else:
            self._serve_static(path.lstrip("/"))

    # --- JSON helper ---------------------------------------------------------
    def _send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    # --- /events (SSE) -------------------------------------------------------
    def _handle_events(self):
        q: "queue.Queue" = queue.Queue(maxsize=100)
        with _subscribers_lock:
            _subscribers.add(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # sync a freshly-connected face to the current state immediately
            self._sse_send(json.dumps(snapshot()))

            while True:
                try:
                    data = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")   # heartbeat -> detect dead peers
                    self.wfile.flush()
                    continue
                self._sse_send(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # client went away
        finally:
            with _subscribers_lock:
                _subscribers.discard(q)

    def _sse_send(self, data_str: str):
        self.wfile.write(("data: " + data_str + "\n\n").encode("utf-8"))
        self.wfile.flush()

    # --- static face files ---------------------------------------------------
    def _serve_static(self, rel: str):
        rel = rel.split("?", 1)[0].split("#", 1)[0]
        target = os.path.normpath(os.path.join(FACE_DIR, rel))

        # path-traversal guard: must stay within FACE_DIR
        if target != FACE_DIR and not target.startswith(FACE_DIR + os.sep):
            self.send_error(403, "Forbidden")
            return

        if os.path.isdir(target):
            target = os.path.join(target, "index.html")

        if os.path.isfile(target):
            try:
                with open(target, "rb") as fh:
                    body = fh.read()
            except OSError:
                self.send_error(404, "Not Found")
                return
            self.send_response(200)
            self.send_header("Content-Type", _guess_type(target))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return

        # face/ not built yet -> fallback page for the index, else 404
        if rel in ("", "index.html"):
            body = _FALLBACK_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "Not Found")


def _guess_type(path: str) -> str:
    ctype, _ = mimetypes.guess_type(path)
    if ctype is None:
        return "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
        return ctype + "; charset=utf-8"
    return ctype


class StateServer:
    """Owns the daemon-thread HTTP server. Thread-isolated from the gateway loop."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8830):
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return  # already running
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="embody-state-server",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            finally:
                self._httpd.server_close()
            self._httpd = None
        self._thread = None
