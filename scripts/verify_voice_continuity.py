#!/usr/bin/env python3
"""Verify voice-PTT conversation continuity through the REAL authenticated path.

Sends two sequential signed webhook turns (exactly as core.voice_input does) and
then inspects sessions.json. PASS = both turns land in ONE
``webhook:voice:evy-voice`` session (not two timestamped ones) AND turn 2's reply
recalls the fact from turn 1.

Run ON the Pi (loopback 8644). Stdlib only.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

# Read the voice route's webhook HMAC secret from the environment — never hardcode
# it (this repo is public). Export it before running:
#   HERMES_WEBHOOK_SECRET=$(…) python3 verify_voice_continuity.py
SECRET = os.environ.get("HERMES_WEBHOOK_SECRET", "")
if not SECRET:
    raise SystemExit("Set HERMES_WEBHOOK_SECRET (the voice route's webhook secret) before running.")
URL = "http://127.0.0.1:8644/webhooks/voice"
SESSIONS = Path.home() / ".hermes/sessions/sessions.json"

TURNS = [
    "Please remember this exactly: the secret passphrase is blue dolphin. Reply in one short sentence.",
    "What is the secret passphrase I just told you? Answer in one short sentence.",
]


def post(text: str) -> int:
    body = json.dumps({"transcript": text, "type": "voice"}).encode("utf-8")
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Webhook-Signature": sig},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def evy_voice_sessions() -> dict:
    """{chat_id: {session_id, total_tokens, updated_at}} for every webhook:voice:* session."""
    data = json.loads(SESSIONS.read_text())
    out = {}
    for sess in data.values():
        if not isinstance(sess, dict):
            continue
        chat_id = (sess.get("origin") or {}).get("chat_id", "")
        if chat_id.startswith("webhook:voice:"):
            out[chat_id] = {
                "session_id": sess.get("session_id", "")[:12],
                "total_tokens": sess.get("total_tokens"),
                "updated_at": sess.get("updated_at"),
            }
    return out


def main() -> None:
    before = evy_voice_sessions()
    print(f"[before] webhook:voice sessions = {len(before)}")
    print(f"[before] evy-voice = {before.get('webhook:voice:evy-voice')}")

    for i, t in enumerate(TURNS, 1):
        code = post(t)
        print(f"[turn {i}] POST -> HTTP {code}  ({t[:48]}...)", flush=True)
        # wait for the async agent turn (LLM + post_llm_call + TTS) to land
        time.sleep(35)

    time.sleep(5)
    after = evy_voice_sessions()
    print(f"[after] webhook:voice sessions = {len(after)}")
    print(f"[after] evy-voice = {after.get('webhook:voice:evy-voice')}")
    new_keys = sorted(set(after) - set(before))
    print(f"[after] NEW session keys this run = {new_keys}")

    print("\n=== VERDICT ===")
    new_ts = [k for k in new_keys if k != "webhook:voice:evy-voice"]
    if "webhook:voice:evy-voice" in after and not new_ts:
        print("PASS: turns went to the single evy-voice session; "
              "no new per-timestamp sessions spawned.")
    elif new_ts:
        print(f"FAIL: new per-timestamp sessions spawned -> {new_ts} "
              "(threading not applied — check patch/restart).")
    else:
        print("INCONCLUSIVE: no evy-voice session found "
              "(did the POSTs reach the agent? check HTTP codes above).")


if __name__ == "__main__":
    main()
