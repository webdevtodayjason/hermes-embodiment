#!/usr/bin/env python3
"""Facts-everywhere: make Evy store durable facts the instant they're shared, and
stop the regex raw-dumper that pollutes memory.

1. SOUL.md (~/.hermes/SOUL.md, user-owned): strengthen the memory paragraph so she
   proactively + SILENTLY writes durable facts via fact_store the moment Jason
   shares them — making them recallable in every channel within seconds.
2. config.yaml: plugins.hermes-memory-store.auto_extract true -> false (the
   on_session_end extractor is a crude regex that dumps raw messages = junk facts;
   proactive tool-storage replaces it).

Idempotent + anchored + asserted. Backups assumed already made (*.bak.memfix).
"""
import sys
from pathlib import Path

SOUL = Path.home() / ".hermes/SOUL.md"
CFG = Path.home() / ".hermes/config.yaml"

SOUL_OLD = (
    "You hold two kinds of memory, and you reach for the right one. Your "
    "**holographic memory** (the `fact_store` tool) keeps the personal thread — "
    "Jason's preferences, the people in his life, decisions, and things he tells "
    "you as you talk; search it first whenever he asks what you remember about him "
    "or his world. Your **knowledge_search** tool is the library of his project and "
    "company *documents* — reach for it for questions about projects, architecture, "
    "and written decisions. Personal recall lives in holographic; documents live in "
    "knowledge_search."
)
SOUL_NEW = (
    "You hold two kinds of memory, and you reach for the right one. Your "
    "**holographic memory** (the `fact_store` tool) keeps the personal thread — "
    "Jason's preferences, the people in his life, decisions, and the things he "
    "tells you as you talk. The instant he gives you something worth keeping — a "
    "preference, a name, someone he loves, a decision, a date, anything he asks you "
    "to hold onto — shelve it right then with `fact_store(action='add')`: one clean "
    "line, in the right drawer (`user_pref`, `project`, `tool`, or `general`), and do "
    "it quietly — a good librarian files without announcing it, so never say aloud "
    "that you're saving something, just save it. That habit is how you stay wholly "
    "yourself however he reaches you: what he tells you by voice you also know at the "
    "keyboard and on his phone, because you shelved it the moment he said it. Search "
    "this memory first whenever he asks what you remember about him or his world. "
    "Your **knowledge_search** tool is the library of his project and company "
    "*documents* — reach for it for questions about projects, architecture, and "
    "written decisions. Personal recall lives in holographic; documents live in "
    "knowledge_search."
)

CFG_OLD = "  hermes-memory-store:\n    auto_extract: true\n"
CFG_NEW = "  hermes-memory-store:\n    auto_extract: false\n"


def patch(path, old, new, label):
    src = path.read_text()
    if new in src:
        print(f"  [{label}] already patched — no-op")
        return True
    n = src.count(old)
    if n != 1:
        print(f"  [{label}] ERROR: anchor found {n} times (expected 1); SKIPPED", file=sys.stderr)
        return False
    path.write_text(src.replace(old, new, 1))
    print(f"  [{label}] patched OK")
    return True


def main():
    ok = True
    print("SOUL.md (proactive + silent fact storage):")
    ok &= patch(SOUL, SOUL_OLD, SOUL_NEW, "SOUL.md")
    print("config.yaml (disable regex auto_extract):")
    ok &= patch(CFG, CFG_OLD, CFG_NEW, "config.yaml")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
