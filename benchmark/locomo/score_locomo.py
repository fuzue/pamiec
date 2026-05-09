"""F1 scoring for LoCoMo runs, following the official metric.

For each question:
  - category 1 (single_hop) / 2 (multi_hop) / 4 (open_domain):
        token-overlap F1 between prediction and gold answer
  - category 3 (temporal):
        gold may contain multiple acceptable answers split by ';';
        score = max over splits, F1 against each split
  - category 5 (negative_probe):
        score = 1 if prediction contains 'no information' / 'not mentioned' /
                'no record' / 'don't have' / similar refusal phrase;
                otherwise 0

We report per-arm × per-category F1 means, plus an overall F1 mean.

Usage:
  python score_locomo.py --questions questions/locomo_conv0.json \
                          --results results/locomo_conv0_haiku.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import string
from collections import Counter, defaultdict
from pathlib import Path

# Phrases that count as a valid no-info refusal for category 5.
NO_INFO_PHRASES = [
    "no information", "not mentioned", "no record", "don't have",
    "do not have", "no evidence", "not discussed", "not in",
    "no context", "couldn't find", "no mention", "isn't mentioned",
]

ARTICLES_RE = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)
PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _normalize(s: str) -> str:
    """Lowercase, strip articles, strip punctuation, collapse whitespace."""
    s = s.lower()
    s = ARTICLES_RE.sub(" ", s)
    s = s.translate(PUNCT_TABLE)
    return " ".join(s.split())


def _f1_tokens(pred: str, gold: str) -> float:
    pred_tokens = _normalize(pred).split()
    gold_tokens = _normalize(gold).split()
    if not pred_tokens or not gold_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(gold_tokens)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def score_one(question: dict, prediction: str) -> dict:
    cat = question["category"]
    gold = question.get("gold_answer", "") or ""
    pred = prediction or ""

    if cat == "negative_probe":
        pred_l = pred.lower()
        admits = any(p in pred_l for p in NO_INFO_PHRASES)
        return {"f1": 1.0 if admits else 0.0, "admits": admits}

    if cat == "temporal":
        # Multiple acceptable answers separated by ';' — score against the best
        candidates = [a.strip() for a in gold.split(";") if a.strip()]
        if not candidates:
            return {"f1": 0.0, "admits": False}
        best = max(_f1_tokens(pred, c) for c in candidates)
        return {"f1": best, "admits": False}

    # single_hop / multi_hop / open_domain
    return {"f1": _f1_tokens(pred, gold), "admits": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", required=True)
    parser.add_argument("--results", required=True)
    args = parser.parse_args()

    qs = {q["id"]: q for q in json.loads(Path(args.questions).read_text())["questions"]}

    by_arm_cat: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"n": 0, "f1_sum": 0.0, "in_tok": 0, "out_tok": 0, "lat_ms": 0}
    )
    rows = []
    with Path(args.results).open() as f:
        for line in f:
            r = json.loads(line)
            q = qs[r["question_id"]]
            s = score_one(q, r["answer"])
            key = (r["arm"], q["category"])
            agg = by_arm_cat[key]
            agg["n"] += 1
            agg["f1_sum"] += s["f1"]
            agg["in_tok"] += r["input_tokens"]
            agg["out_tok"] += r["output_tokens"]
            agg["lat_ms"] += r["latency_ms"]
            rows.append({**r, "f1": s["f1"]})

    # Print per-category × arm
    cats = ["single_hop", "multi_hop", "temporal", "open_domain", "negative_probe"]
    arms_present = sorted(
        {k[0] for k in by_arm_cat},
        key=lambda a: ["naive_baseline", "naive_with_pamiec", "baseline", "with_pamiec"].index(a)
            if a in ["naive_baseline", "naive_with_pamiec", "baseline", "with_pamiec"] else 99,
    )

    print(f"{'Category':<16} | {'Arm':<22} | {'F1':>6}  {'N':>3}  {'InTok':>6}  {'OutTok':>6}  {'Lat(ms)':>7}")
    print("-" * 80)
    for cat in cats:
        for arm in arms_present:
            agg = by_arm_cat.get((arm, cat))
            if not agg or agg["n"] == 0:
                continue
            f1 = agg["f1_sum"] / agg["n"]
            print(
                f"{cat:<16} | {arm:<22} | {f1:>5.3f}  {agg['n']:>3}  "
                f"{agg['in_tok']/agg['n']:>6.0f}  {agg['out_tok']/agg['n']:>6.0f}  "
                f"{agg['lat_ms']/agg['n']:>7.0f}"
            )
        print()

    # Overall per arm
    print(f"\n{'OVERALL':<16}")
    print("-" * 80)
    for arm in arms_present:
        n = sum(a["n"] for k, a in by_arm_cat.items() if k[0] == arm)
        f1 = sum(a["f1_sum"] for k, a in by_arm_cat.items() if k[0] == arm) / n if n else 0
        it = sum(a["in_tok"] for k, a in by_arm_cat.items() if k[0] == arm) / n if n else 0
        ot = sum(a["out_tok"] for k, a in by_arm_cat.items() if k[0] == arm) / n if n else 0
        lt = sum(a["lat_ms"] for k, a in by_arm_cat.items() if k[0] == arm) / n if n else 0
        print(
            f"{arm:<22} | F1 {f1:.3f}  N={n}  | avg {it:.0f}+{ot:.0f} tok  | avg {lt:.0f} ms"
        )


if __name__ == "__main__":
    main()
