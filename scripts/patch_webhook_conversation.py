#!/usr/bin/env python3
"""Patch Hermes' webhook platform to support a STABLE conversation key.

Root cause of "every PTT starts a brand-new conversation": the webhook session
key is ``webhook:{route}:{delivery_id}`` and ``delivery_id`` falls back to a
per-request millisecond timestamp — so every voice turn gets its own session and
zero shared history.

Fix: let a caller pin a stable conversation (payload ``conversation_id``, header
``X-Conversation-ID``, or route config ``conversation``); fall back to the old
per-request ``delivery_id`` otherwise. Idempotency still keys on ``delivery_id``
so no turn is dropped. Fully backward-compatible.

Idempotent: re-running is a no-op if already patched. Backs up once, then
``py_compile``-verifies. Re-apply after a Hermes upgrade (this is core, like the
holographic FTS patch).
"""
import py_compile
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / ".hermes/hermes-agent/gateway/platforms/webhook.py"
ANCHOR = '        session_chat_id = f"webhook:{route_name}:{delivery_id}"'

REPLACEMENT = '''        # Pin a STABLE conversation so multi-turn sources (e.g. voice PTT) thread
        # into ONE ongoing agent conversation instead of a fresh one per request.
        # Precedence: payload.conversation_id -> X-Conversation-ID header ->
        # route_config["conversation"] -> per-request delivery_id (old default).
        # Idempotency still keys on delivery_id, so no turn is dropped. The value
        # becomes part of chat_id (parsed on ':'), so constrain its charset.
        _convo = (
            (payload.get("conversation_id") if isinstance(payload, dict) else None)
            or request.headers.get("X-Conversation-ID")
            or route_config.get("conversation")
        )
        if _convo:
            _convo = "".join(c for c in str(_convo) if c.isalnum() or c in "_.-")[:64]
        session_chat_id = f"webhook:{route_name}:{_convo or delivery_id}"'''

MARKER = "Pin a STABLE conversation"  # presence => already patched


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found", file=sys.stderr)
        return 2
    src = TARGET.read_text()

    if MARKER in src:
        print("already patched (marker present) — no-op")
        return 0

    n = src.count(ANCHOR)
    if n != 1:
        print(f"ERROR: anchor found {n} times (expected 1); aborting", file=sys.stderr)
        return 3

    backup = TARGET.with_suffix(".py.bak.convo")
    if not backup.exists():
        shutil.copy2(TARGET, backup)
        print(f"backup -> {backup}")

    TARGET.write_text(src.replace(ANCHOR, REPLACEMENT, 1))
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(backup, TARGET)  # roll back
        print(f"ERROR: py_compile failed, rolled back: {exc}", file=sys.stderr)
        return 4

    print("patched OK + py_compile clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
