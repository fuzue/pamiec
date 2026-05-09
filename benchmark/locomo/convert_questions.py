"""Convert LoCoMo's QA list into our benchmark questions JSON.

LoCoMo categories (numeric in source) map to our category names:
  1 → single_hop
  2 → multi_hop
  3 → temporal
  4 → open_domain      (new — multi-hop-ish, often commonsense or knowledge update)
  5 → negative_probe   (adversarial; correct answer is "no information available")

We preserve the LoCoMo gold answer (untouched) under `gold_answer`, plus the
evidence dia_ids for diagnostic backtracking. Our existing keyword-based
score.py is retained for any sanity checks; F1 scoring against `gold_answer`
is the metric of record (score_locomo.py).

Usage:
  python convert_questions.py --sample 0 --out questions/locomo_conv0.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CATEGORY_MAP = {
    1: "single_hop",
    2: "multi_hop",
    3: "temporal",
    4: "open_domain",
    5: "negative_probe",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, required=True)
    parser.add_argument("--data", default=str(Path(__file__).parent / "locomo10.json"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    samples = json.load(open(args.data))
    sample = samples[args.sample]
    sample_id = sample["sample_id"]

    questions = []
    for i, qa in enumerate(sample["qa"], 1):
        category_int = qa.get("category", 0)
        category = CATEGORY_MAP.get(category_int, f"locomo_cat_{category_int}")
        gold = qa.get("answer", "")

        q = {
            "id": f"q{i:03d}",
            "category": category,
            "question": qa["question"],
            "gold_answer": gold,
            "evidence": qa.get("evidence", []),
            "locomo_category": category_int,
        }

        # negative_probe (cat 5): scoring uses LoCoMo's substring rule, so we
        # don't attach expected_keywords. The score_locomo.py module handles it.
        if category != "negative_probe":
            # Provide a permissive keyword fallback in case anyone wants to run
            # the existing keyword scorer on this. Pick the longest word in the
            # gold answer as a sanity-check token; not used by F1 scoring.
            words = [w for w in gold.replace(",", " ").split() if len(w) >= 4]
            if words:
                q["expected_keywords_any_of"] = [[words[0]]]

        questions.append(q)

    out = {"project": f"locomo_{sample_id}", "questions": questions}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))

    from collections import Counter
    cat_counts = Counter(q["category"] for q in questions)
    print(f"Wrote {args.out}")
    print(f"  sample_id: {sample_id}")
    print(f"  total: {len(questions)} questions")
    for c, n in sorted(cat_counts.items()):
        print(f"    {c}: {n}")


if __name__ == "__main__":
    main()
