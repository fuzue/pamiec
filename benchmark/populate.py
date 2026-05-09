"""Populate a test pamiec DB from a synthetic narrative.

Usage:
  PAMIEC_DB=/tmp/pamiec-bench.db python populate.py --narrative b2b_v1

Mimics what the cron does: writes turns to the EPG, then runs consolidation
across semantic boundaries. Result: a DB the runner can query via
recall_context.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--narrative", required=True, help="module name under narratives/, e.g. b2b_v1")
    parser.add_argument("--reset", action="store_true", help="wipe the DB first")
    args = parser.parse_args()

    if not os.environ.get("PAMIEC_DB"):
        print("ERROR: set PAMIEC_DB to an isolated test path first.", file=sys.stderr)
        print("  e.g.  export PAMIEC_DB=/tmp/pamiec-bench.db", file=sys.stderr)
        sys.exit(1)

    bench_dir = Path(__file__).parent
    sys.path.insert(0, str(bench_dir / "narratives"))
    narrative = importlib.import_module(args.narrative)

    if args.reset and Path(os.environ["PAMIEC_DB"]).exists():
        Path(os.environ["PAMIEC_DB"]).unlink()
        print(f"Reset {os.environ['PAMIEC_DB']}")

    # Imports must come AFTER PAMIEC_DB is set so db.py reads the env var.
    from pamiec.boundaries import split_at_boundaries
    from pamiec.consolidation import consolidate_turns
    from pamiec.db import init_db
    from pamiec.session_reader import Turn

    init_db()
    print(f"Initialized DB: {os.environ['PAMIEC_DB']}\n")

    # Each session in the narrative becomes one consolidate_turns call.
    # Use a per-session synthetic 'session_file' so our tracking matches the
    # multi-session-isolation behavior of the real cron.
    base_t = time.time() - 60 * 60 * 24 * 3  # backdate 3 days ago
    grand = {"new": 0, "touched": 0, "edges": 0, "skipped": 0}

    for sess in narrative.SESSIONS:
        session_file = f"bench:{narrative.GROUND_TRUTH['project_name']}:{sess['id']:02d}"
        t = base_t + sess["id"] * 3600  # one hour apart
        turns = []
        for role, text in sess["turns"]:
            turns.append(Turn(role=role, text=text, timestamp=t, iso_ts=""))
            t += 60  # one minute per turn

        segments = split_at_boundaries(turns)
        print(f"Session {sess['id']} ({sess['summary']}): {len(turns)} turns → {len(segments)} segment(s)")

        for i, seg in enumerate(segments, 1):
            res = consolidate_turns(seg, session_file=session_file)
            if res.get("skipped_no_entities"):
                grand["skipped"] += 1
                print(f"  [{i}/{len(segments)}] SKIPPED (no entities)")
            else:
                grand["new"] += res["nodes_created"]
                grand["touched"] += res["entities_touched"]
                grand["edges"] += res["edges_created"]
                print(
                    f"  [{i}/{len(segments)}] episode {res['episode_id'][:8]} | "
                    f"+{res['nodes_created']} entities, {res['entities_touched']} touched, "
                    f"{res['edges_created']} edges"
                )

    print(f"\nTotal: +{grand['new']} entities, {grand['touched']} touched, "
          f"{grand['edges']} edges, {grand['skipped']} segments skipped")


if __name__ == "__main__":
    main()
