"""Populate a pamiec test DB from one LoCoMo conversation.

Each LoCoMo conversation has up to ~35 'sessions' between two speakers, spread
over months. We treat each session as a separate Claude Code session: feed its
turns through pamiec's consolidate_turns pipeline so the resulting graph has
the same shape it would after the cron processed real cross-session content.

Usage:
  PAMIEC_DB=/tmp/locomo-conv0.db python populate_locomo.py --sample 0 --reset
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def _parse_locomo_date(s: str) -> float:
    """LoCoMo dates look like '1:56 pm on 8 May, 2023'. Parse to unix epoch.

    Returns 0.0 on parse failure (caller will substitute a synthetic timestamp).
    """
    s = s.strip()
    m = re.match(r"(\d+):(\d+)\s*([ap]m)\s+on\s+(\d+)\s+([A-Za-z]+),\s*(\d{4})", s)
    if not m:
        return 0.0
    hour, minute, ampm, day, month_name, year = m.groups()
    hour = int(hour)
    minute = int(minute)
    if ampm.lower() == "pm" and hour < 12:
        hour += 12
    if ampm.lower() == "am" and hour == 12:
        hour = 0
    try:
        dt = datetime.strptime(
            f"{day} {month_name} {year} {hour:02d}:{minute:02d}",
            "%d %B %Y %H:%M",
        )
    except ValueError:
        return 0.0
    return dt.timestamp()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, required=True, help="LoCoMo sample index 0-9")
    parser.add_argument("--reset", action="store_true", help="wipe DB first")
    parser.add_argument("--data", default=str(Path(__file__).parent / "locomo10.json"))
    args = parser.parse_args()

    if not os.environ.get("PAMIEC_DB"):
        print("ERROR: set PAMIEC_DB to an isolated test path first.", file=sys.stderr)
        sys.exit(1)

    if args.reset and Path(os.environ["PAMIEC_DB"]).exists():
        Path(os.environ["PAMIEC_DB"]).unlink()
        print(f"Reset {os.environ['PAMIEC_DB']}")

    samples = json.load(open(args.data))
    if not 0 <= args.sample < len(samples):
        print(f"ERROR: sample index {args.sample} out of range 0-{len(samples)-1}", file=sys.stderr)
        sys.exit(1)
    sample = samples[args.sample]
    conv = sample["conversation"]
    sample_id = sample["sample_id"]

    # Imports must come AFTER PAMIEC_DB is set so db.py reads the env var.
    from pamiec.consolidation import consolidate_turns
    from pamiec.db import init_db
    from pamiec.session_reader import Turn

    init_db()
    print(f"Initialized DB: {os.environ['PAMIEC_DB']}")
    print(f"Sample: {sample_id}")
    print(f"Speakers: {conv['speaker_a']} & {conv['speaker_b']}\n")

    # Discover sessions in chronological order (by integer suffix)
    session_keys = sorted(
        [k for k in conv if re.fullmatch(r"session_\d+", k)],
        key=lambda k: int(k.split("_")[1]),
    )

    grand = {"new": 0, "touched": 0, "edges": 0, "skipped": 0, "episodes": 0}

    for sk in session_keys:
        session_idx = int(sk.split("_")[1])
        date_str = conv.get(f"{sk}_date_time", "")
        base_t = _parse_locomo_date(date_str)
        if base_t == 0.0:
            # fall back to a synthetic linearly-spaced timestamp
            base_t = 1_700_000_000 + session_idx * 86400 * 14  # 2 weeks apart

        turns = []
        for i, turn in enumerate(conv[sk]):
            speaker = turn.get("speaker", "?")
            text = turn.get("text", "").strip()
            if not text:
                continue
            # Pamiec's role taxonomy is user/assistant. Map alternating LoCoMo
            # speakers so the conversation looks natural to the extractor.
            role = "user" if speaker == conv["speaker_a"] else "assistant"
            # Prefix the speaker name in the text so the extractor sees who
            # said what (LoCoMo extraction needs both speakers as named
            # entities, unlike Claude Code where 'user'/'assistant' is enough).
            prefixed = f"{speaker}: {text}"
            turns.append(Turn(
                role=role, text=prefixed,
                timestamp=base_t + i * 60, iso_ts="",
            ))

        if not turns:
            continue

        result = consolidate_turns(
            turns,
            session_file=f"locomo:{sample_id}:{sk}",
        )
        if result.get("skipped_no_entities"):
            grand["skipped"] += 1
            print(f"  {sk:>10s} ({date_str:35s}): {len(turns):2d} turns → SKIPPED (no entities)")
        else:
            grand["episodes"] += 1
            grand["new"] += result["nodes_created"]
            grand["touched"] += result["entities_touched"]
            grand["edges"] += result["edges_created"]
            print(
                f"  {sk:>10s} ({date_str:35s}): {len(turns):2d} turns → "
                f"+{result['nodes_created']:2d} entities, {result['entities_touched']:2d} touched, "
                f"{result['edges_created']:2d} edges"
            )

    print(
        f"\nTotal: {grand['episodes']} episodes, +{grand['new']} entities, "
        f"{grand['touched']} touched, {grand['edges']} edges, {grand['skipped']} segments skipped"
    )


if __name__ == "__main__":
    main()
