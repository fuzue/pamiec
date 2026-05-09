# LoCoMo Tier 2 adaptation

Adapts pamiec-bench to the [LoCoMo](https://github.com/snap-research/locomo)
benchmark for long-conversation memory. Provides a literature-anchored
comparison point — the same dataset GAM, Mem0, MemoryOS, and A-Mem report
F1 numbers on.

## What it does

LoCoMo's structure is an excellent fit for pamiec's intended use case: each
conversation is **already split into sessions** (~20 sessions × ~20 turns
each, spread over months), so we don't need to artificially chunk a single
conversation. We feed each session through pamiec's `consolidate_turns`
pipeline as if it were a separate Claude Code session, then ask LoCoMo's QA
pairs against the populated graph.

## Setup (data)

The LoCoMo dataset is **CC BY-NC 4.0** and can't be redistributed via this
MIT-licensed repo. Download it yourself before running:

```bash
curl -sLo benchmark/locomo/locomo10.json \
  https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
```

This is a single JSON file (~2.8 MB) containing 10 multi-session
conversations between fictional speakers, each with 100–260 QA pairs.

## Pipeline

```bash
cd ~/pamiec/benchmark/locomo

# Pick a sample (0–9) and convert its QA list to our questions JSON
python convert_questions.py --sample 1 --out questions/locomo_conv1.json

# Populate an isolated DB by running each LoCoMo session through
# pamiec's capture+consolidate pipeline
PAMIEC_DB=/tmp/locomo-conv1.db python populate_locomo.py --sample 1 --reset

# Run the 4-arm benchmark (uses the existing runner.py at benchmark/)
cd ..
ANTHROPIC_API_KEY=... PAMIEC_DB=/tmp/locomo-conv1.db \
  python runner.py \
    --questions locomo/questions/locomo_conv1.json \
    --out locomo/results/locomo_conv1_haiku.jsonl

# Score with LoCoMo's official F1 metric
python locomo/score_locomo.py \
  --questions locomo/questions/locomo_conv1.json \
  --results locomo/results/locomo_conv1_haiku.jsonl
```

## Question-category mapping

LoCoMo categories are numeric in the source data; we translate to our
benchmark-question category names:

| LoCoMo | Our category    | Notes |
|--------|-----------------|-------|
| 1      | single_hop      | direct retrieval |
| 2      | multi_hop       | reasoning over multiple turns |
| 3      | temporal        | scoring splits gold answer on `;` |
| 4      | open_domain     | commonsense / knowledge update |
| 5      | negative_probe  | adversarial; correct answer is "no information" |

## Scoring

`score_locomo.py` follows LoCoMo's published evaluation:

- Categories 1, 2, 4: token-overlap F1 against the gold answer
- Category 3: F1 against the best-matching split of the gold answer (multiple acceptable answers separated by `;`)
- Category 5: 1 if prediction contains a refusal phrase ("no information", "not mentioned", etc.); 0 otherwise

## Caveats

- **LoCoMo's task is within-conversation episodic memory**, not pamiec's
  primary use case (cross-session entity-level memory in technical work).
  Pamiec's extraction pipeline filters aggressively for stable named
  entities; many LoCoMo questions ask about specific events and personal
  details that the engineering-tuned extraction prompt skips. Expect
  pamiec to underperform LoCoMo-specialized systems like GAM on this
  benchmark — the gap reflects an architectural choice, not a flaw.
- The dataset has no images; only `img_url` references and BLIP captions
  are in the JSON. Conversations remain text-only after the captions are
  inlined.

## License

The LoCoMo dataset itself is CC BY-NC 4.0 — non-commercial use only — see
`https://github.com/snap-research/locomo/blob/main/LICENSE.txt`. This
adapter is MIT, matching the rest of pamiec.
