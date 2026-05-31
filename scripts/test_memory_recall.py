#!/usr/bin/env python3
"""Probe the holographic recall path directly against the live DB.

Run on the Pi with the gateway venv python:
  ~/.hermes/hermes-agent/venv/bin/python /tmp/test_memory_recall.py

Answers: (1) does FactRetriever.search() surface the favorite-color fact for a
natural query, and at what min_trust; (2) does the provider's prefetch() —
the ACTUAL per-turn recall hook — return it, and is self._min_trust even set?
"""
import os
import sys

PLUGIN = os.path.expanduser("~/.hermes/hermes-agent/plugins/memory/holographic")
sys.path.insert(0, PLUGIN)
sys.path.insert(0, os.path.dirname(PLUGIN))  # for any sibling imports

DB = os.path.expanduser("~/.hermes/memory_store.db")
QUERIES = [
    "what is my favorite color",
    "favorite color",
    "color",
    "what color do I like",
]

print("=== direct FactRetriever.search() ===")
try:
    from store import MemoryStore
    from retrieval import FactRetriever
    store = MemoryStore(db_path=DB, default_trust=0.5, hrr_dim=1024)
    retr = FactRetriever(store=store, hrr_weight=0.3, hrr_dim=1024)
    for q in QUERIES:
        for mt in (0.3, 0.5):
            res = retr.search(q, min_trust=mt, limit=5)
            hits = [f"{r.get('content','')[:50]} (s={r.get('score',0):.2f})" for r in res]
            print(f"  q={q!r} min_trust={mt}: {len(res)} hits -> {hits}")
except Exception as e:
    import traceback
    print("  search probe FAILED:", e)
    traceback.print_exc()

print("\n=== provider.prefetch() — the real per-turn recall hook ===")
try:
    import importlib
    prov_mod = importlib.import_module("__init__")  # holographic/__init__.py
    Provider = prov_mod.HolographicMemoryProvider
    p = Provider()
    # mirror how the gateway configures it
    if hasattr(p, "_config"):
        p._config = {"db_path": DB, "default_trust": 0.5, "hrr_dim": 1024}
    # try the documented setup hook names
    for setup in ("setup", "_setup", "initialize", "configure"):
        fn = getattr(p, setup, None)
        if callable(fn):
            try:
                fn(); print(f"  (called {setup}())")
                break
            except Exception as e:
                print(f"  ({setup}() raised {e})")
    print("  has _min_trust attr?", hasattr(p, "_min_trust"),
          "value=", getattr(p, "_min_trust", "<MISSING>"))
    for q in ("what is my favorite color", "favorite color"):
        try:
            out = p.prefetch(q)
            print(f"  prefetch({q!r}) -> {out!r}")
        except Exception as e:
            print(f"  prefetch({q!r}) RAISED: {e}")
except Exception as e:
    import traceback
    print("  prefetch probe FAILED:", e)
    traceback.print_exc()
