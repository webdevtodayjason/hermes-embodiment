# MEMORY_EXTRACTION.md — nightly conversation → holographic memory

The job `scripts/nightly_extract.py` reads **one day** of the user's conversation
across every channel (voice/webhook, Telegram, CLI), extracts only the facts
worth keeping long-term, and writes them into the **existing holographic memory
store** with supersession, a conservative noise filter, and a default-safe dry
run.

> Why this exists: voice, Telegram, and terminal each remembered their own
> slice. Durable, cross-channel recall needs a single nightly pass that distils
> the day into atomic facts and shelves them where every channel reads from.

---

## Pipeline (4 stages)

| # | Stage | What happens |
|---|-------|--------------|
| 1 | **fetch** | `hermes sessions export <tmp.jsonl>` (all channels) → filter to the target day by message timestamp → build a readable transcript. |
| 2 | **extract** | One LLM call with the archivist prompt → candidate facts (JSON). Drop below `CONFIDENCE_THRESHOLD`; `emotional_beat` off unless enabled. |
| 3 | **classify** | The *writer* stage. For each candidate, `search_facts(subject)` → a 2nd small LLM call decides **NEW / UPDATE / DUPLICATE** vs the matches. Fail-safe → NEW on any parse error. |
| 4 | **write** | NEW → `add_fact`; UPDATE → `update_fact(old_id, …)`; DUPLICATE → skip. **Writes only with `--write`.** |

### The export schema (authoritative)

`hermes sessions export` writes **one session object per JSONL line** (from
`hermes_state.export_all`):

```jsonc
{ "id": "<session id>", "source": "<channel>",      // webhook(voice)/telegram/cli
  "started_at": 1764000000.0, "ended_at": 1764003600.0,
  "messages": [ { "role": "user", "content": "...", "timestamp": 1764000123.0 }, ... ] }
```

- **Channel** = the session-level `source`.
- **Timestamp** = the message-level `timestamp` (epoch REAL seconds).
- There is **no date flag** on `export`. A session can span days, so the job
  filters **per message** by its own timestamp (local time, to match a local
  "yesterday"). Only `user` and `assistant` messages are kept; `tool`/`system`
  are noise for the archivist.

---

## Taxonomy (6 fine categories + one-line tests)

A fact must EARN a shelf. Default posture is **SKIP**.

| Fine category | One-line test | Churn |
|---|---|---|
| **identity_relationship** | A person/pet/entity and who they are to the user — durable. | low |
| **preference** | A standing rule for how the user wants things done. | low |
| **decision** | A choice made over alternatives (+ rationale if stated). | medium |
| **commitment** | An obligation / open loop the user will do, wants done, or is waiting on (`status`: open/done). | medium |
| **project_state** | Current status / architecture / what shipped or is blocked — **highest churn, needs supersession most**. | high |
| **emotional_beat** | What mattered to the user or how something felt — **be conservative**. | — |

### Noise filter — SKIP (default)

- Logistics ("let's do it at 3"), unresolved questions, meta-chat about the
  conversation itself.
- Anything already obviously permanent and generic, or already known.
- The assistant's own outputs **unless** they record a committed decision.
- When unsure → **skip**. A quiet day legitimately returns `{"facts":[]}`.

---

## Confidence threshold & emotional_beat

- `CONFIDENCE_THRESHOLD` (env, default **0.7**): candidates below it are dropped.
- `emotional_beat` is **OFF by default**; set `ENABLE_EMOTIONAL_BEAT=true` to keep
  those facts. (Sentiment is the easiest thing to over-collect.)

---

## Category mapping (6 fine → 4 real store categories)

The store has only four real categories: `user_pref | project | tool | general`.
Each fine category maps onto one; the **fine** category is preserved in `tags`
so nothing is lost.

| Fine | → Real store category |
|---|---|
| identity_relationship | `general` |
| preference | `user_pref` |
| decision | `project` |
| commitment | `general` |
| project_state | `project` |
| emotional_beat | `general` |

**Tags string** carries fine category + confidence + source channel + date:

```
decision,conf=0.82,src=telegram,2026-05-30
```

(`tool` is reachable by the store but the archivist taxonomy never emits it; it
stays available for facts written by other paths.)

---

## Supersession model (NEW / UPDATE / DUPLICATE)

Built on the **real** store API — no separate revision table.

```
add_fact(content, category="general", tags="") -> int      # dedups by exact content (UNIQUE)
search_facts(query, category=None, min_trust=0.3, limit=10) -> list[dict]   # dicts keyed `fact_id`
update_fact(fact_id, content=None, trust_delta=None, tags=None, category=None) -> bool
remove_fact(fact_id) -> bool                                # NOT used for supersession
```

For each candidate the classifier (a small LLM call seeded with
`search_facts(subject)` results) returns one of:

- **NEW** → `add_fact(content=statement, category=<mapped>, tags=<fine,conf,src,date>)`.
- **UPDATE** → `update_fact(old_id, content=statement, tags=…, category=<mapped>)`.
  **Prefer UPDATE over remove** — it preserves the row and its accumulated trust
  history. **Never hard-delete for supersession.** (If `update_fact` reports the
  row is gone, the job falls back to `add_fact`.)
- **DUPLICATE** → skip. `add_fact`'s content-level UNIQUE dedup is a backstop, so
  even a misclassified duplicate can't create a second identical row.

Fail-safe: any classifier parse error, or an `UPDATE` pointing at a `fact_id`
that wasn't among the search matches, degrades to **NEW** (never silently
overwrite an unrelated fact).

---

## JSON schema (extractor output)

```json
{"facts": [
  {"category": "decision",
   "subject": "billing service datastore",
   "statement": "The user chose PostgreSQL over MongoDB for the billing service.",
   "rationale": "relational integrity for invoices",
   "confidence": 0.82,
   "status": "n/a",
   "supersedes_hint": "previously leaning toward MongoDB",
   "source": {"channel": "telegram", "ts": "2026-05-30T14:00:00", "msg_ref": "<session id>#12"}}
]}
```

- `statement`: ONE atomic, self-contained sentence.
- `confidence`: 0.0–1.0.
- `status`: `open`/`done` for commitments, else `"n/a"`.
- `supersedes_hint`: describe the prior fact if this likely changes one — **do
  not resolve it** (stage 3 does that against the live store).
- Empty days → `{"facts": []}`.

---

## Extraction prompt (used verbatim as the system prompt)

```
You are a memory archivist. You read a day's conversation between the user and their assistant (across voice, chat, and terminal) and extract only the facts worth remembering long-term.
Extract a fact ONLY if it fits one of these categories:
- identity_relationship: a person/pet/entity and who they are to the user
- preference: a standing rule for how the user wants things done
- decision: a choice made over alternatives (capture the rationale if stated)
- commitment: something the user will do, wants done, or is waiting on
- project_state: current status, architecture, what shipped or is blocked
- emotional_beat: what mattered to the user or how something felt (be conservative)
SKIP logistics, unresolved questions, meta-talk, and anything already obviously permanent and generic. When unsure, skip. A fact must earn its place.
For each fact: write `statement` as ONE atomic, self-contained sentence; set `confidence` 0.0-1.0; set `status` for commitments (open/done) else "n/a"; if it likely changes a known fact, describe the prior in `supersedes_hint` (do not resolve it); fill `source` {channel, ts, msg_ref}.
Return ONLY valid JSON: {"facts":[{"category","subject","statement","rationale","confidence","status","supersedes_hint","source":{"channel","ts","msg_ref"}}]}. No prose. If nothing qualifies, return {"facts":[]}.
```

---

## Running it

```bash
# DEFAULT-SAFE: dry-run, writes nothing — prints every NEW/UPDATE/DUPLICATE decision
~/.hermes/hermes-agent/venv/bin/python scripts/nightly_extract.py

# Actually persist (the nightly timer uses this):
~/.hermes/hermes-agent/venv/bin/python scripts/nightly_extract.py --write

# A specific day:
~/.hermes/hermes-agent/venv/bin/python scripts/nightly_extract.py --date 2026-05-30 --write
```

Run with the **gateway venv python** so the store's transitive imports
(`hermes_state`, `hermes_constants`) resolve.

### Environment

| Var | Default | Meaning |
|---|---|---|
| `LLM_API_KEY` | — (required) | Bearer key for the local LLM endpoint (in `~/.hermes/nightly-extract.env` on the Pi, mode 600). |
| `LLM_BASE_URL` | `http://localhost:1234/v1` | Primary local OpenAI-compatible endpoint. |
| `LLM_BASE_URL_FALLBACK` | `""` (empty) | Optional fallback endpoint (only used when set). |
| `LLM_MODEL` | `qwen/qwen3.6-27b` (example) | Model your endpoint serves. |
| `CONFIDENCE_THRESHOLD` | `0.7` | Drop candidate facts below this. |
| `ENABLE_EMOTIONAL_BEAT` | off | `true` keeps emotional_beat facts. |
| `HERMES_BIN` | `~/.local/bin/hermes` | hermes CLI path. |
| `MEMORY_DB_PATH` | `~/.hermes/memory_store.db` | Holographic store DB. |
| `HOLOGRAPHIC_DIR` | `~/.hermes/hermes-agent/plugins/memory/holographic` | Dir with `store.py` + `holographic.py`. |
| `HERMES_AGENT_DIR` | `~/.hermes/hermes-agent` | hermes-agent root (for `hermes_state`/`hermes_constants`). |
| `MAX_TRANSCRIPT_CHARS` | `60000` | Truncate (loudly) above this. |

### LLM source — local OpenAI-compatible LLM (primary → optional fallback)

The extractor + classifier run against your **local LLM** (Ollama, LM Studio, etc.
— OpenAI-compatible API, Bearer auth). At startup the job does a short `GET /models`
probe:

1. **`LLM_BASE_URL`** — primary. → logs `[llm] using primary endpoint`.
2. else **`LLM_BASE_URL_FALLBACK`** (optional; only probed when set).
   → logs `[llm] primary unreachable, using fallback`.
3. else **exit cleanly** (never hang the nightly job).

The key (`LLM_API_KEY`) is read from env only — the systemd unit pulls it from a
dedicated mode-600 `EnvironmentFile=%h/.hermes/nightly-extract.env`, never inlined.

### Import gotcha (why the store loads the way it does)

`store.py` falls back to `import holographic as hrr` (its sibling HRR module
`holographic.py`). The job adds **only** the holographic dir to `sys.path`, so
`import store` and `import holographic` resolve as **top-level** modules. Adding
the *parent* (`plugins/memory`) instead would resolve `import holographic` to the
**provider package** `holographic/__init__.py` and fail with
`module 'holographic' has no attribute '_HAS_NUMPY'`.

---

## Deploy

User systemd units in `deploy/`:

- `deploy/nightly-extract.service` — oneshot; runs the job for **yesterday** with
  the gateway venv python and **`--write`**.
- `deploy/nightly-extract.timer` — `OnCalendar` daily ~04:30, `Persistent=true`.

```bash
# on the Pi
mkdir -p ~/.config/systemd/user
cp deploy/nightly-extract.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now nightly-extract.timer
systemctl --user list-timers nightly-extract.timer
```

> The `.service` **must** pass `--write` — without it the timer dry-runs forever
> and silently writes nothing while looking healthy in the logs.

---

## Verification

After a week of nightly runs, ask your assistant for **the detective story** — the
thread about *"Telegram letters with half their pages missing."* If that phrase is
gone from how it's told (because the facts were distilled and shelved, not lost per
channel), the job took. Until then, run `--dry-run` and eyeball the
NEW/UPDATE/DUPLICATE decisions for a few days.
