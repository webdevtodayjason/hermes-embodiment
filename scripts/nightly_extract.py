#!/usr/bin/env python3
"""nightly_extract.py — nightly conversation → holographic-memory extraction (conversation → durable facts).

Reads ONE day of Hermes conversation across every channel (voice/webhook,
Telegram, CLI), extracts only the facts worth remembering long-term with an LLM,
and writes them into the existing holographic memory store — with supersession
(NEW / UPDATE / DUPLICATE), a conservative noise filter, and a default-safe dry
run.

Run on the Pi with the gateway venv python so the store's transitive imports
(`hermes_state`, `hermes_constants`) resolve:

    ~/.hermes/hermes-agent/venv/bin/python scripts/nightly_extract.py            # dry run (default-safe)
    ~/.hermes/hermes-agent/venv/bin/python scripts/nightly_extract.py --write    # actually persist
    ~/.hermes/hermes-agent/venv/bin/python scripts/nightly_extract.py --date 2026-05-30 --write

PIPELINE (4 stages):
  1. fetch    : `hermes sessions export <tmp.jsonl>` (ALL channels) → filter to the
                target day by message timestamp → readable transcript.
  2. extract  : one LLM call with the archivist prompt → candidate facts (JSON).
                Drops anything below CONFIDENCE_THRESHOLD; emotional_beat is OFF
                unless ENABLE_EMOTIONAL_BEAT=true.
  3. classify : the WRITER stage. For each candidate, search_facts(subject) → a 2nd
                small LLM call decides NEW / UPDATE / DUPLICATE vs the matches
                (returns the matched fact_id for UPDATE). Fail-safe → NEW on error.
  4. write    : NEW → add_fact ; UPDATE → update_fact(old_id, …) (PREFER update over
                remove — preserves the row + its trust history; never hard-delete
                for supersession) ; DUPLICATE → skip. WRITES ONLY WHEN --write IS
                PASSED. The default run prints every decision and writes nothing.

LLM source: any local OpenAI-compatible endpoint (e.g. Ollama http://localhost:11434/v1,
or LM Studio http://localhost:1234/v1). Set LLM_BASE_URL (and optional
LLM_BASE_URL_FALLBACK) to point at yours. At startup the job probes LLM_BASE_URL; if
that is unreachable it falls back to LLM_BASE_URL_FALLBACK (when set); if NEITHER is
reachable it exits cleanly rather than hanging the nightly run.

ENV (all optional except the API key when extracting):
  LLM_API_KEY           Bearer key for the local LLM endpoint (in ~/.hermes/nightly-extract.env
                        on the Pi, mode 600). REQUIRED for extraction.
  LLM_BASE_URL          Primary local OpenAI-compatible endpoint. Default: http://localhost:1234/v1
  LLM_BASE_URL_FALLBACK Optional fallback endpoint. Default: "" (only used when set).
  LLM_MODEL             Model your endpoint serves. Default: qwen/qwen3.6-27b (example)
  CONFIDENCE_THRESHOLD  Drop candidate facts below this. Default: 0.7
  ENABLE_EMOTIONAL_BEAT "true" to keep emotional_beat facts. Default: off.
  HERMES_BIN            hermes CLI path. Default: ~/.local/bin/hermes
  MEMORY_DB_PATH        holographic store db. Default: ~/.hermes/memory_store.db
  HOLOGRAPHIC_DIR       dir holding store.py + holographic.py.
                        Default: ~/.hermes/hermes-agent/plugins/memory/holographic
  HERMES_AGENT_DIR      hermes-agent root (so hermes_state/hermes_constants import).
                        Default: ~/.hermes/hermes-agent
  MAX_TRANSCRIPT_CHARS  Truncate (with a loud warning) above this. Default: 60000

See MEMORY_EXTRACTION.md for the taxonomy, noise filter, supersession model, the
category mapping (6 fine → 4 real store categories), and the JSON schema.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration & constants
# --------------------------------------------------------------------------- #

DEFAULT_MODEL = "qwen/qwen3.6-27b"  # example model, good at structured JSON; set LLM_MODEL to a model your endpoint serves
# LLM source: any local OpenAI-compatible endpoint (e.g. Ollama http://localhost:11434/v1,
# or LM Studio http://localhost:1234/v1). Set LLM_BASE_URL (and optional
# LLM_BASE_URL_FALLBACK) to point at yours.
DEFAULT_LLM_BASE_URL = "http://localhost:1234/v1"   # primary endpoint
DEFAULT_LLM_BASE_URL_FALLBACK = ""                  # optional fallback; only used when LLM_BASE_URL_FALLBACK is set

# The store exposes only 4 real categories. The extraction taxonomy has 6 finer
# ones — map each fine category onto a real store category. The FINE category is
# preserved in the tags string so nothing is lost.
#   real store categories: user_pref | project | tool | general
CATEGORY_MAP = {
    "identity_relationship": "general",
    "preference": "user_pref",
    "decision": "project",
    "commitment": "general",
    "project_state": "project",
    "emotional_beat": "general",
}
VALID_FINE_CATEGORIES = set(CATEGORY_MAP)

# Extraction system prompt — used VERBATIM (see MEMORY_EXTRACTION.md).
EXTRACTION_SYSTEM_PROMPT = """You are a memory archivist. You read a day's conversation between the user and their assistant (across voice, chat, and terminal) and extract only the facts worth remembering long-term.
Extract a fact ONLY if it fits one of these categories:
- identity_relationship: a person/pet/entity and who they are to the user
- preference: a standing rule for how the user wants things done
- decision: a choice made over alternatives (capture the rationale if stated)
- commitment: something the user will do, wants done, or is waiting on
- project_state: current status, architecture, what shipped or is blocked
- emotional_beat: what mattered to the user or how something felt (be conservative)
SKIP logistics, unresolved questions, meta-talk, and anything already obviously permanent and generic. When unsure, skip. A fact must earn its place.
For each fact: write `statement` as ONE atomic, self-contained sentence; set `confidence` 0.0-1.0; set `status` for commitments (open/done) else "n/a"; if it likely changes a known fact, describe the prior in `supersedes_hint` (do not resolve it); fill `source` {channel, ts, msg_ref}.
Return ONLY valid JSON: {"facts":[{"category","subject","statement","rationale","confidence","status","supersedes_hint","source":{"channel","ts","msg_ref"}}]}. No prose. If nothing qualifies, return {"facts":[]}."""

# Classifier system prompt — the supersession brain for stage 3. Decides whether a
# fresh candidate is NEW, UPDATES one of the existing facts, or DUPLICATEs one.
CLASSIFY_SYSTEM_PROMPT = """You decide whether a freshly-extracted candidate fact is NEW, an UPDATE of an existing stored fact, or a DUPLICATE of one.
You are given the candidate and a numbered list of EXISTING facts already in memory (each with its fact_id).
- DUPLICATE: an existing fact already says the same thing; nothing changes.
- UPDATE: the candidate supersedes / corrects / refines a specific existing fact about the SAME subject (e.g. a status changed, a preference flipped, a value was corrected). Return that fact's fact_id.
- NEW: no existing fact is about the same subject, or the candidate adds genuinely new information.
When unsure between UPDATE and NEW, prefer NEW (never silently overwrite an unrelated fact).
Return ONLY valid JSON: {"decision":"NEW|UPDATE|DUPLICATE","fact_id":<int or null>}. No prose."""


def expand(p: str) -> str:
    return os.path.expanduser(os.path.expandvars(p))


def env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------- #
# Lazy / deferred imports (kept out of module top-level on purpose)
#   * py_compile and `--help` must run on ANY machine, off the Pi, before the
#     venv / sys.path / db exist. So `openai` and the holographic `store` are
#     imported only inside the functions that actually need them.
# --------------------------------------------------------------------------- #

def _endpoint_reachable(base_url: str, api_key: str, timeout: float = 3.0) -> bool:
    """Short GET /models probe. A response (even an HTTP error) ⇒ reachable;
    only a connection failure / timeout ⇒ unreachable."""
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        # server answered (401/404/etc.) — it's up; auth/path issues surface later
        return True
    except Exception:
        # URLError, timeout, socket error, DNS — genuinely unreachable
        return False


def select_endpoint(api_key: str) -> str:
    """Probe the primary endpoint, then the optional fallback. Exit cleanly if neither is reachable."""
    primary = os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
    fallback = os.environ.get("LLM_BASE_URL_FALLBACK", DEFAULT_LLM_BASE_URL_FALLBACK)
    if _endpoint_reachable(primary, api_key):
        print(f"[llm] using primary endpoint ({primary})")
        return primary
    if fallback and _endpoint_reachable(fallback, api_key):
        print(f"[llm] primary unreachable, using fallback ({fallback})")
        return fallback
    raise SystemExit(
        f"[llm] no LLM endpoint reachable (primary {primary}"
        + (f" / fallback {fallback}" if fallback else "")
        + "); aborting nightly job."
    )


def get_llm_client():
    """Return an OpenAI-compatible client pointed at the local LLM endpoint.

    The endpoint speaks the OpenAI API with Bearer auth. The endpoint is chosen at
    startup (primary, then optional fallback). Deferred import so --help / py_compile
    run anywhere.
    """
    try:
        from openai import OpenAI  # deferred: not needed for --help / py_compile
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "The 'openai' package is required (pip install openai). " + str(exc)
        )
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise SystemExit(
            "LLM_API_KEY is not set (it lives in ~/.hermes/nightly-extract.env on the Pi, mode 600)."
        )
    base_url = select_endpoint(api_key)
    return OpenAI(base_url=base_url, api_key=api_key)


def open_store():
    """Construct the REAL holographic MemoryStore.

    IMPORT GOTCHA (critical): store.py falls back to `import holographic as hrr`
    (its sibling HRR module `holographic.py`). To make `import store` and
    `import holographic` resolve as TOP-LEVEL modules, add ONLY the holographic
    dir to sys.path. Do NOT add its parent (plugins/memory) and do NOT
    `import holographic` from there — that resolves the *provider package*
    `holographic/__init__.py` instead and fails with
    `module 'holographic' has no attribute '_HAS_NUMPY'`.

    The hermes-agent root is appended (not prepended) so the store's transitive
    `hermes_state` / `hermes_constants` imports resolve even on a non-installed
    layout, without shadowing anything.
    """
    holo_dir = expand(os.environ.get(
        "HOLOGRAPHIC_DIR", "~/.hermes/hermes-agent/plugins/memory/holographic"
    ))
    agent_dir = expand(os.environ.get("HERMES_AGENT_DIR", "~/.hermes/hermes-agent"))
    db_path = expand(os.environ.get("MEMORY_DB_PATH", "~/.hermes/memory_store.db"))

    if holo_dir not in sys.path:
        sys.path.insert(0, holo_dir)          # store.py + holographic.py as top-level
    if agent_dir not in sys.path:
        sys.path.append(agent_dir)            # best-effort: hermes_state / hermes_constants

    from store import MemoryStore  # deferred: needs sys.path + gateway venv
    return MemoryStore(db_path=db_path, default_trust=0.5, hrr_dim=1024)


# --------------------------------------------------------------------------- #
# Stage 1 — fetch & build the day's transcript
# --------------------------------------------------------------------------- #

def to_date(ts) -> dt.date | None:
    """Best-effort: an epoch (REAL, the DB schema) or an ISO-8601 string → a date.

    Uses LOCAL time so it matches a LOCAL `today() - 1 day` target day.
    """
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return dt.datetime.fromtimestamp(float(ts)).date()
        s = str(ts).strip()
        if not s:
            return None
        # numeric-looking string → epoch
        try:
            return dt.datetime.fromtimestamp(float(s)).date()
        except ValueError:
            pass
        # ISO-8601 ("2026-05-30T04:02:45.036671", optionally with Z/offset)
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (ValueError, OverflowError, OSError):
        return None


def run_export(hermes_bin: str, out_path: str) -> None:
    """`hermes sessions export <out_path>` — dumps ALL sessions (every channel)."""
    cmd = [hermes_bin, "sessions", "export", out_path]
    print(f"[fetch] running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"`hermes sessions export` failed (exit {proc.returncode}):\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


def parse_export(path: str, target: dt.date) -> tuple[list[dict], int, int]:
    """Parse the export JSONL → the target day's messages.

    Export schema (authoritative, from hermes_state.export_all):
      each LINE is one SESSION object: {..., "source": <channel>, "messages": [...]}
      each message: {"role", "content", "timestamp": <epoch REAL>, ...}
    Channel is the SESSION-level `source`; a session may span days, so we filter
    PER MESSAGE by its own timestamp.

    Returns (messages, n_sessions, n_messages_total) where messages is the kept,
    time-ordered subset of {ts, channel, role, text, msg_ref}.
    """
    kept: list[dict] = []
    n_sessions = 0
    n_messages_total = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                session = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_sessions += 1
            channel = session.get("source") or session.get("platform") or "unknown"
            session_id = session.get("id", "?")
            messages = session.get("messages") or []
            for idx, msg in enumerate(messages):
                n_messages_total += 1
                role = msg.get("role")
                # Only the user's words and the assistant's replies carry durable
                # facts. tool/system/meta messages are pure noise for the archivist.
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content")
                if not isinstance(content, str) or not content.strip():
                    continue
                ts = msg.get("timestamp", session.get("started_at"))
                if to_date(ts) != target:
                    continue
                kept.append({
                    "ts": ts,
                    "channel": channel,
                    "role": role,
                    "text": content.strip(),
                    "msg_ref": f"{session_id}#{idx}",
                })
    # stable order by timestamp (epoch float sorts naturally; None → 0)
    kept.sort(key=lambda m: (float(m["ts"]) if isinstance(m["ts"], (int, float)) else 0.0))
    return kept, n_sessions, n_messages_total


def build_transcript(messages: list[dict]) -> str:
    """Render kept messages as a readable transcript for the extractor."""
    lines = []
    for m in messages:
        d = to_date(m["ts"])
        # show a compact local time if epoch, else the raw ts
        when = ""
        if isinstance(m["ts"], (int, float)):
            when = dt.datetime.fromtimestamp(float(m["ts"])).strftime("%H:%M")
        speaker = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"[{when} {m['channel']}] {speaker}: {m['text']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Stage 2 — extract candidate facts (one LLM call)
# --------------------------------------------------------------------------- #

def _parse_json_object(text: str) -> dict | None:
    """Robustly pull a JSON object out of an LLM reply (handles code fences)."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        # strip ```json ... ``` fences
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # last resort: grab the outermost {...}
        start, end = s.find("{"), s.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(s[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def extract_facts(client, model: str, transcript: str,
                  threshold: float, enable_emotional: bool) -> list[dict]:
    """One LLM call → candidate facts, then apply the local filters."""
    resp = client.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
    )
    raw = resp.choices[0].message.content or ""
    parsed = _parse_json_object(raw)
    if not parsed or "facts" not in parsed:
        print("[extract] WARNING: model returned no parseable {\"facts\":[...]}; "
              f"treating as a quiet day. Raw head: {raw[:160]!r}")
        return []

    candidates: list[dict] = []
    dropped_conf = 0
    dropped_emotional = 0
    dropped_category = 0
    for f in parsed.get("facts", []):
        if not isinstance(f, dict):
            continue
        cat = (f.get("category") or "").strip()
        if cat not in VALID_FINE_CATEGORIES:
            dropped_category += 1
            continue
        if cat == "emotional_beat" and not enable_emotional:
            dropped_emotional += 1
            continue
        try:
            conf = float(f.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < threshold:
            dropped_conf += 1
            continue
        statement = (f.get("statement") or "").strip()
        if not statement:
            continue
        f["confidence"] = conf
        f["statement"] = statement
        f["category"] = cat
        candidates.append(f)

    print(f"[extract] {len(candidates)} candidate(s) kept "
          f"(dropped: {dropped_conf} below conf<{threshold}, "
          f"{dropped_emotional} emotional_beat off, {dropped_category} bad/unknown category)")
    return candidates


# --------------------------------------------------------------------------- #
# Stage 3 — match + classify (NEW / UPDATE / DUPLICATE)
# --------------------------------------------------------------------------- #

def classify_candidate(client, model: str, store, candidate: dict) -> tuple[str, int | None, list[dict]]:
    """search_facts(subject) → small LLM call → (decision, fact_id, matches).

    Fail-safe to NEW on any parse error. If there are no existing matches the
    answer is trivially NEW (no LLM call needed).
    """
    subject = (candidate.get("subject") or candidate.get("statement") or "").strip()
    matches = store.search_facts(subject, min_trust=0.0, limit=5) if subject else []
    if not matches:
        return "NEW", None, []

    listing = "\n".join(
        f"{i}. (fact_id={m.get('fact_id')}) {m.get('content', '')}"
        for i, m in enumerate(matches)
    )
    user_msg = (
        f"CANDIDATE:\n  subject: {subject}\n  statement: {candidate.get('statement', '')}\n"
        f"  fine_category: {candidate.get('category', '')}\n\n"
        f"EXISTING FACTS:\n{listing}"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        parsed = _parse_json_object(resp.choices[0].message.content or "")
    except Exception as exc:  # network/model hiccup → fail-safe
        print(f"[classify] WARNING: classifier call failed ({exc}); failing safe to NEW")
        return "NEW", None, matches

    if not parsed:
        return "NEW", None, matches
    decision = str(parsed.get("decision", "NEW")).upper().strip()
    if decision not in ("NEW", "UPDATE", "DUPLICATE"):
        decision = "NEW"
    fact_id = parsed.get("fact_id")
    if decision == "UPDATE":
        # validate the returned id is actually one of the matches; else fail to NEW
        valid_ids = {m.get("fact_id") for m in matches}
        try:
            fact_id = int(fact_id)
        except (TypeError, ValueError):
            fact_id = None
        if fact_id not in valid_ids:
            print(f"[classify] UPDATE returned unknown fact_id={fact_id}; failing safe to NEW")
            return "NEW", None, matches
        return "UPDATE", fact_id, matches
    return decision, None, matches


# --------------------------------------------------------------------------- #
# Stage 4 — write (or, in dry-run, just narrate)
# --------------------------------------------------------------------------- #

def make_tags(candidate: dict, target: dt.date) -> str:
    """Preserve the FINE category + confidence + source channel + date in tags.

    Example: `decision,conf=0.82,src=telegram,2026-05-30`
    """
    fine = candidate.get("category", "general")
    conf = candidate.get("confidence", 0.0)
    src = (candidate.get("source") or {}).get("channel") or candidate.get("_channel") or "unknown"
    src = str(src).replace(",", " ").strip() or "unknown"
    return f"{fine},conf={conf:.2f},src={src},{target.isoformat()}"


def apply_decision(store, candidate: dict, decision: str, fact_id: int | None,
                   target: dt.date, dry_run: bool) -> str:
    """Carry out (or, in dry-run, narrate) one write decision. Returns a label."""
    statement = candidate["statement"]
    fine = candidate["category"]
    real_category = CATEGORY_MAP[fine]
    tags = make_tags(candidate, target)

    if decision == "DUPLICATE":
        print(f"  DUPLICATE  [{fine}->{real_category}] {statement!r}  (skip)")
        return "duplicate"

    if decision == "UPDATE":
        print(f"  UPDATE     fact_id={fact_id} [{fine}->{real_category}] {statement!r}")
        if not dry_run:
            # PREFER update over remove: keeps the row + its trust history intact.
            ok = store.update_fact(fact_id, content=statement, tags=tags, category=real_category)
            if not ok:
                print(f"    -> update_fact({fact_id}) returned False; row missing — adding as NEW")
                new_id = store.add_fact(content=statement, category=real_category, tags=tags)
                print(f"    -> add_fact => fact_id={new_id}")
        return "update"

    # NEW
    print(f"  NEW        [{fine}->{real_category}] {statement!r}")
    if not dry_run:
        new_id = store.add_fact(content=statement, category=real_category, tags=tags)
        print(f"    -> add_fact => fact_id={new_id}")
    return "new"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Nightly conversation → holographic-memory extraction (default-safe dry run).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--date", help="Target day YYYY-MM-DD (default: yesterday, local time).",
    )
    # DEFAULT-SAFE: dry_run defaults True. --write (alias --no-dry-run) flips it.
    # --dry-run is accepted explicitly too (documents intent; it is already default).
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=True,
        help="Print every NEW/UPDATE/DUPLICATE decision and write NOTHING (the default).",
    )
    parser.add_argument(
        "--write", "--no-dry-run", dest="dry_run", action="store_false",
        help="Actually persist decisions to the store. Without this, nothing is written.",
    )
    parser.add_argument(
        "--hermes-bin", default=expand(os.environ.get("HERMES_BIN", "~/.local/bin/hermes")),
        help="Path to the hermes CLI (default: $HERMES_BIN or ~/.local/bin/hermes).",
    )
    args = parser.parse_args(argv)

    # --- target day ------------------------------------------------------- #
    if args.date:
        try:
            target = dt.date.fromisoformat(args.date)
        except ValueError:
            print(f"Bad --date {args.date!r}; expected YYYY-MM-DD.", file=sys.stderr)
            return 2
    else:
        target = dt.date.today() - dt.timedelta(days=1)

    threshold = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.7"))
    enable_emotional = env_flag("ENABLE_EMOTIONAL_BEAT", False)
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    max_chars = int(os.environ.get("MAX_TRANSCRIPT_CHARS", "60000"))

    mode = "DRY-RUN (no writes)" if args.dry_run else "WRITE"
    print(f"=== nightly_extract  date={target}  mode={mode}  model={model} "
          f"conf>={threshold}  emotional_beat={'on' if enable_emotional else 'off'} ===")

    # --- stage 1: fetch --------------------------------------------------- #
    with tempfile.NamedTemporaryFile(
        prefix="hermes_export_", suffix=".jsonl", delete=False
    ) as tmp:
        export_path = tmp.name
    try:
        run_export(args.hermes_bin, export_path)
        messages, n_sessions, n_msgs = parse_export(export_path, target)
    finally:
        try:
            os.unlink(export_path)
        except OSError:
            pass

    # LOUD accounting so a schema miss reads as "parsed 0 of N", not "quiet day".
    print(f"[fetch] exported {n_sessions} session(s), {n_msgs} message(s) total, "
          f"{len(messages)} on {target}")
    if not messages:
        print("[fetch] nothing on the target day — quiet day, nothing to extract. Done.")
        return 0

    transcript = build_transcript(messages)
    if len(transcript) > max_chars:
        print(f"[fetch] WARNING: transcript is {len(transcript)} chars > "
              f"MAX_TRANSCRIPT_CHARS={max_chars}; TRUNCATING. Some of the day's tail "
              f"will be unseen by the extractor (raise MAX_TRANSCRIPT_CHARS to capture it).")
        transcript = transcript[:max_chars]

    # stash channel per-candidate fallback (the extractor also fills source.channel)
    day_channels = sorted({m["channel"] for m in messages})
    primary_channel = day_channels[0] if len(day_channels) == 1 else "mixed"

    # --- stage 2: extract ------------------------------------------------- #
    client = get_llm_client()
    candidates = extract_facts(client, model, transcript, threshold, enable_emotional)
    if not candidates:
        print("[extract] no candidate facts cleared the bar. Done.")
        return 0

    # --- stages 3 + 4: classify + write ----------------------------------- #
    store = open_store()
    counts = {"new": 0, "update": 0, "duplicate": 0}
    try:
        for cand in candidates:
            cand.setdefault("_channel", primary_channel)
            decision, fact_id, _matches = classify_candidate(client, model, store, cand)
            label = apply_decision(store, cand, decision, fact_id, target, args.dry_run)
            counts[label] = counts.get(label, 0) + 1
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    verb = "would write" if args.dry_run else "wrote"
    print(f"=== summary: {counts['new']} NEW, {counts['update']} UPDATE "
          f"({verb}), {counts['duplicate']} DUPLICATE (skipped)  [{mode}] ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
