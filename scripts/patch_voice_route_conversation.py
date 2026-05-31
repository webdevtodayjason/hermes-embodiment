#!/usr/bin/env python3
"""Add `conversation: evy-voice` to the Hermes webhook `voice` route so voice
turns thread into one ongoing conversation (pairs with the webhook.py patch).

Anchors on the unique `prompt: '{transcript}'` + `deliver: log` pair of the
voice route. Idempotent; backs up config.yaml once.
"""
import shutil
import sys
from pathlib import Path

CFG = Path.home() / ".hermes/config.yaml"
ANCHOR = "          prompt: '{transcript}'\n          deliver: log\n"
INSERT = "          prompt: '{transcript}'\n          deliver: log\n          conversation: evy-voice\n"
MARKER = "conversation: evy-voice"


def main() -> int:
    if not CFG.exists():
        print(f"ERROR: {CFG} not found", file=sys.stderr)
        return 2
    src = CFG.read_text()
    if MARKER in src:
        print("already has conversation: evy-voice — no-op")
        return 0
    n = src.count(ANCHOR)
    if n != 1:
        print(f"ERROR: voice-route anchor found {n} times (expected 1); aborting", file=sys.stderr)
        return 3
    backup = CFG.with_suffix(".yaml.bak.convo")
    if not backup.exists():
        shutil.copy2(CFG, backup)
        print(f"backup -> {backup}")
    CFG.write_text(src.replace(ANCHOR, INSERT, 1))
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
