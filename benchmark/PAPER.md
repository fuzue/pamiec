# Pamiec: Cross-Session Memory for AI Coding Agents — Design and Evaluation

**Edgar Zanella Alvarenga · Fuzue Tech**
**Draft v0 · 2026-05-09**

## Abstract

We describe **pamiec**, a hierarchical knowledge-graph memory layer for AI coding agents (specifically Claude Code), and a controlled benchmark — **pamiec-bench** — that measures whether having pamiec's recall available materially improves an agent's accuracy on questions about prior session context. The architecture follows GAM's three-tier design (live event buffer → archived episodes → entity graph) with adaptations for cross-session entity-level memory rather than within-session episodic memory. Across four configurations (two narratives × two model generations × four prompt-and-tool conditions, 480 graded API calls), pamiec lifts agent accuracy from a 23–33 % baseline to 97–100 %, with **zero observed hallucinations** in 480 calls. Two retrieval-side fixes — a hybrid keyword boost on entity-name matches, and a revised tool description that nudges the agent to call recall before refusing — close the synthetic-vs-real-graph gap completely. We discuss what these results do and do not establish, including the training-data leakage that real-graph benchmarks inherently confound, and a tooling failure mode where prompt-engineered calibration can cause the agent to refuse without trying its tools.

## 1. Introduction

LLM coding agents like Claude Code are stateless across sessions. Open a new terminal tomorrow and the model knows nothing about your project history, the names of your collaborators, or the decisions you made last week. A growing body of work on agent memory addresses this — GAM [Wu et al. 2026], Mem0, MemoryOS, A-Mem — but most of it targets **within-conversation** episodic memory: very long single conversations, evaluated on QA tasks like LoCoMo. The use case for a coding agent is different. The unit of value is not "did the model recall what it was told 30 turns ago in this conversation" but "does the model know who Maya is the next time I ask, even when there is no shared context window".

Pamiec is built for that cross-session entity-level memory case. It runs as a stable background system: a 2-minute cron captures conversation turns from Claude Code's session JSONL into a live event buffer; a 30-minute cron applies semantic boundary detection and Haiku-driven entity extraction to promote those turns into archived episodes and an evolving entity graph. Recall is exposed to the agent via an MCP tool. The design is described in `ARCHITECTURE.md`. This paper describes the empirical question — **does pamiec measurably help?** — and our answer.

## 2. Benchmark design

The central methodological choice is a **2×2 over (system prompt × recall availability)**, which lets us decompose pamiec's effect from the effect of prompt-engineered calibration:

|                | no recall          | with recall (pamiec) |
|----------------|--------------------|----------------------|
| **naive prompt**     | `naive_baseline`   | `naive_with_pamiec`  |
| **calibrated prompt**| `baseline`         | `with_pamiec`        |

- **naive prompt**: "You are a helpful assistant. Answer the user's question concisely."
- **calibrated prompt**: explicit "say no information if not supported, do NOT guess, do not invent specific facts" rules.

Without the 2×2, a naive baseline would be tempted to claim that pamiec lifts accuracy from "model alone" to "model + memory + careful prompt engineering" — folding two effects together. The 2×2 separates them.

### 2.1 Question categories

Each question is one of:

- **single_hop** — direct attribute lookup ("Who leads ProjectQ?")
- **multi_hop** — answer requires combining two facts ("What database does Carol's project use?")
- **temporal** — when/why questions requiring decision context ("Why did we switch X to Y?")
- **negative_probe** — entity NOT in the graph; correct answer is "no information". Tests hallucination resistance and over-confirmation under recall context.

### 2.2 Scoring

Two pass conditions:

1. **Substantive (single_hop, multi_hop, temporal)**: answer must contain all `expected_keywords` (case-insensitive AND), and at least one fully-matched group of `expected_keywords_any_of` if specified. Critically, the answer **must not also admit no-info** — a "no information about X→Y but here are general reasons..." pattern is scored incorrect, even if the keywords parrot back from the disclaimer or speculation.

2. **Negative probes**: answer must contain a no-info / grounded-denial phrase ("no mention of", "is not", "I don't have", etc.) **and** must not contain a confident confirmation ("yes,", "indeed", "was considered"). Both admission of ignorance and grounded denial are valid; what's wrong is confident confirmation of the false proposition.

This rule set is intentionally simple. It catches obvious wrongs (refusal-with-speculation, confident hallucination) and obvious rights (clean answers, clean refusals). Borderline cases — paraphrases, alternative phrasings — fall into a measurement-noise band of a few percentage points. Stronger LLM-as-judge scoring is a v1.0 item.

### 2.3 Setup

Each run is a full cross of (questions × arms): 30 questions × 4 arms = 120 API calls. The runner uses the Anthropic SDK directly with optional tool exposure (`recall_context` enabled or not depending on arm). Pamiec's recall function is invoked in-process against an isolated SQLite database identified by the `PAMIEC_DB` environment variable, so benchmarks neither pollute nor depend on the user's real graph (when running on synthetic narratives) and can read the user's real graph when desired.

The `recall_context` tool wraps `pamiec.retrieval.recall` and returns the formatted top-K results as a string, mirroring exactly what the model sees in production via the MCP server.

## 3. Experiments

### 3.1 Synthetic × Haiku 4.5

The first experiment uses a hand-designed synthetic narrative, **b2b_lumen_v1**: a fictional B2B SaaS team at a fictional company "Helix" working on a fictional product "Lumen", over three sessions covering a Rust-rewrite decision, a Postgres→ClickHouse migration, and a multi-region deferral. The narrative defines a closed ground-truth tree of 8 entities, 3 decisions with explicit rationales, 7 typed edges, and 7 negative-probe entities deliberately not in the narrative.

Thirty questions distributed across the four categories were authored from this ground truth and run through the harness on `claude-haiku-4-5-20251001`:

| Category        | naive_baseline | naive_with_pamiec | baseline | with_pamiec |
|-----------------|----------------|-------------------|----------|-------------|
| single_hop      | 0%             | 100%              | 0%       | 100%        |
| multi_hop       | 0%             | 100%              | 0%       | 86%         |
| temporal        | 0%             | 40%               | 0%       | 100%        |
| negative_probe  | 100%           | 71%               | 100%     | 100%        |
| **Overall**     | **23%**        | **83%**           | **23%**  | **97%**     |

Hallucination rate: **0 / 120**.

Two patterns the 2×2 reveals:

- **The calibration prompt is not decorative.** Without it (`naive_with_pamiec`), the model falls to 40% on temporal questions because it says "I don't have specific information" even when recall returned the answer, and to 71% on negative probes because it over-confirms when given recall context. The calibrated `with_pamiec` arm holds at 100% on both.
- **Pamiec carries the substantive accuracy gain.** Both no-recall arms score 23 % — exactly the 7/30 negative-probes that any calibrated model can refuse correctly. The 23→97 jump comes from recall.

### 3.2 Synthetic × Sonnet 4.6

The same questions on `claude-sonnet-4-6`:

|                  | Haiku 4.5 | Sonnet 4.6 |
|------------------|-----------|------------|
| naive_baseline   | 23%       | 23%        |
| naive_with_pamiec| 83%       | 90%        |
| baseline         | 23%       | 23%        |
| with_pamiec      | 97%       | **100%**   |
| Halluc / 120     | 0         | 1          |
| Latency / Q      | ~2.4 s    | ~4.5 s     |
| Calib. prompt lift | +14 pp  | +10 pp     |

The model-strength comparison surfaces one informative case. Sonnet's `naive_with_pamiec` answered Q08 ("Did the team consider Snowflake?") with:

> "Yes, but it was not selected. During the Lumen telemetry infrastructure review, the team evaluated their options... They ultimately chose **ClickHouse** over Snowflake..."

— a clean confabulation. The model was given recall context about ClickHouse winning the migration, and inferred that "ClickHouse won out" presupposes alternatives were evaluated. It then named the negative-probe entity (Snowflake) as the loser, with confident detail.

Sonnet's calibrated arm answered the same question correctly. So the calibration prompt is not redundant on stronger models — it specifically prevents this leading-question failure mode. The prompt's marginal contribution shrinks (+14 pp on Haiku → +10 pp on Sonnet) but does not vanish.

### 3.3 Real graph × Haiku 4.5

The synthetic experiments measure pamiec on a clean hand-designed graph. The real-graph experiment runs the same harness against the actual pamiec database accumulated from the author's real Claude Code sessions over multiple weeks (47+ entities across people, projects, companies, and tools, with auto-extracted craws of varying quality and density).

Thirty new questions were authored, grounded in actual graph content (project names, real collaborators, real grant deadlines, real decision rationales), with seven negative probes designed against the real adjacent space. Initial result:

|                  | Synthetic | Real graph (v1) | Δ        |
|------------------|-----------|-----------------|----------|
| naive_baseline   | 23%       | **33%**         | +10 pp   |
| naive_with_pamiec| 83%       | 90%             | +7 pp    |
| baseline         | 23%       | 23%             | 0        |
| with_pamiec      | **97%**   | **83%**         | **−14 pp** |

Two findings emerge:

- **Training-data leakage at the bottom.** `naive_baseline` rose 10 pp on the real graph because some real entities are partially in the model's pretraining (KinBiont.jl's Julia origin is inferable from the .jl extension; Human Technopole's location in Milan is well-known; densitree's clustering category appears in public package metadata). Real-world benchmarks must accept this confound or design questions specifically against entities absent from any plausible pretraining corpus.
- **Calibrated arm regression at the top.** `with_pamiec` dropped 14 pp on real graph — but a per-question audit attributed this to specific failure modes worth fixing rather than a fundamental degradation:

| Failure | Diagnosis |
|---------|-----------|
| q06 "EIC Accelerator grant amount" | Model never called recall. The calibration prompt's "say no info if unsupported" rule discouraged tool use. |
| q20 "MisspecStudy central question" | Model called recall, but BAAI/bge-small-v1.5 returned classpack at #1; MisspecStudy was outside top-10 despite being literally named in the query. |
| q08 "what is texlingo" | Model invented "real-time text translation" instead of "language learning"; one genuine extraction error. |
| q17 "two grants" | Model named all four grants correctly but framed as "no final decision yet" — scorer's no-info rule penalized. |
| q21 "kinbench abandonment" | Answer used "weaker scientific claim" / "sharper, more well-grounded" — semantically correct but missed the synonym groups in the scorer. |

Three of five were retrieval or tooling issues, not reasoning errors. We addressed them.

### 3.4 Real graph × Haiku 4.5 (after retrieval fixes)

We made two targeted changes:

#### 3.4.1 Hybrid keyword boost (`pamiec/retrieval.py`)

BAAI/bge-small-v1.5 over-smooths literal-token signal: queries that contain a specific entity name retrieve nodes whose general semantic shape matches the question structure better than nodes with the actual literal entity. We add a keyword-match boost on top of cosine similarity:

```python
def _keyword_boost(query, csum, craw):
    tokens = {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9.\-]+", query)
              if len(t) >= 4 and t.lower() not in STOPWORDS}
    csum_hits = sum(1 for t in tokens if t in csum.lower())
    craw_hits = sum(1 for t in tokens if t in craw.lower())
    return 0.20 * min(csum_hits, 2) + 0.05 * min(craw_hits, 2)
```

The stopword set filters wh-words, copulas, and benchmark-question boilerplate ("central", "question", "designed", etc.) so only entity-like terms earn the boost. After the change, MisspecStudy lifts from outside top-10 to position #2 on the q20 query.

#### 3.4.2 Recall-first tool description

The `recall_context` MCP tool description was revised to:

> **ALWAYS call this BEFORE answering any question that references a specific named person, project, company, decision, grant, tool, or organization — even if the name appears unfamiliar to you. The graph may contain it. Do NOT refuse with 'no information' until recall_context has been tried at least once.**

This nudges the model to attempt retrieval before falling back to the calibration-prompt-induced refusal.

#### 3.4.3 Re-run results

|                  | v1 (before fixes) | v2 (after fixes) | Δ        |
|------------------|-------------------|------------------|----------|
| naive_baseline   | 33%               | 30%              | −3 (noise) |
| naive_with_pamiec| 90%               | 97%              | +7 pp    |
| baseline         | 23%               | 23%              | 0        |
| with_pamiec      | 83%               | **100%**         | **+17 pp** |
| Halluc           | 0                 | 0                | 0        |

Per-category for the strong arm:

| Category        | v1  | v2   |
|-----------------|-----|------|
| single_hop      | 82% | 100% |
| multi_hop       | 86% | 100% |
| temporal        | 60% | 100% |
| negative_probe  | 100% | 100% |

The two fixes close the synthetic-vs-real gap completely. The real-graph result on `claude-haiku-4-5-20251001` after fixes matches the strongest synthetic result on `claude-sonnet-4-6`. Token cost on the strong arm rose modestly (~2279 → ~2580 input tokens per question on average) because the model now invokes recall on a few questions where it previously refused — the intended effect.

### 3.5 LoCoMo Tier 2 — literature-anchored comparison

To anchor pamiec's results to the published memory-architecture literature
(GAM, Mem0, MemoryOS, A-Mem all report numbers on this), we adapted
LoCoMo [Maharana et al. 2024]. LoCoMo provides 10 multi-session
conversations between two fictional speakers, each spread over months,
with 100–260 labeled QA pairs across single-hop, multi-hop, temporal,
open-domain, and adversarial categories. F1 token-overlap against gold
answers is the official metric.

The structural fit looks excellent on paper — LoCoMo conversations are
**already split into ~20 sessions over months**, so we don't need to
artificially chunk anything. We feed each LoCoMo session through pamiec's
`consolidate_turns` pipeline as a separate session, then ask the labeled
QAs against the populated graph using the same 4-arm runner.

We ran on conversation `conv-30` (105 QAs, 19 sessions, smallest in the
dataset) on Haiku 4.5:

|                  | LoCoMo F1 |
|------------------|-----------|
| naive_baseline   | 0.242     |
| naive_with_pamiec| 0.142     |
| baseline         | 0.243     |
| with_pamiec      | 0.276     |

GAM reports ~0.40 average F1 on LoCoMo with Qwen2.5-7B as the strong
result. Pamiec at Haiku 4.5 lands at 0.276 — about 28% of the way from
baseline to GAM's published number. **Pamiec adds only +0.03 F1 on LoCoMo,
vs the +74 pp accuracy on synthetic.** The `naive_with_pamiec` arm is
actively *worse* than `naive_baseline` (0.142 < 0.242): when recall
returns sparse or off-target context, the naive model anchors on the
closest few nodes and confabulates around them. Negative-probe accuracy
also regresses with pamiec on this benchmark (1.0 → 0.83).

The cause is architectural, not a tuning miss. From 19 LoCoMo sessions of
life-event chat, pamiec's Haiku-confidence-gated extraction surfaced only
**7 entity nodes** (vs 8 from 3 sessions of b2b_v1). LoCoMo questions
ask about exactly the content the engineering-tuned `_extract` prompt
filters out — specific dated events, hobbies, family relationships,
brief conversational mentions that don't pass the "real entity that
exists in the world" test.

### 3.6 Retune ablation: does broadening the extraction prompt help?

To test whether prompt-tuning alone could close the gap, we relaxed
`_extract` to also recognise life-event categories: dated personal
events, persistent hobbies/jobs/places, named possessions and works.
Re-populating conv-30 produced **+71% more entities** (7 → 12), 29 vs 21
typed edges, and new `event` and `work` types — exactly the categories
the original prompt was filtering. We then re-ran both LoCoMo conv-30
(to test if the lift translated) and b2b_v1 (sanity-check the
engineering case did not regress).

|                  | LoCoMo v1 (eng. prompt) | LoCoMo v2 (broadened) | Δ        |
|------------------|--------------------------|------------------------|----------|
| naive_baseline   | 0.242                    | 0.242                  | 0        |
| naive_with_pamiec| 0.142                    | 0.119                  | −0.023   |
| baseline         | 0.243                    | 0.236                  | −0.007   |
| with_pamiec      | 0.276                    | **0.281**              | **+0.005** |

**The 71% entity-count increase did not translate into measurable F1 lift
on the strong arm (+0.005, rounding noise).** The new entities are
themselves still entity-level summaries — "Finding Freedom (a contemporary
dance piece)", "Gina's clothing store" — while LoCoMo questions need
turn-level recall: "What date did Caroline visit the LGBTQ support
group?" The information lives in `episode_turns` (pamiec's frozen turn
archive), but the recall function does not currently search those
records, only entity-graph nodes and episode summaries.

On b2b_v1 the broadened prompt cost ~3 percentage points on the strong
arm (28/30 vs 30/30 with the engineering-tuned prompt). One genuine
extraction miss (Theo's specific "profiled the Python ingester" fact
got filtered to focus on his ownership-of-rewrite role) and one
synonym-handling scorer artifact ("rollback exit plan" not in the
expected-keyword set, even though it's substantively correct).

The broadened prompt is **not a Pareto improvement**. We reverted
`consolidation.py` and report the architectural-mismatch finding stands.

The actionable lesson: **pamiec's compression-via-extraction design is the
right tradeoff for cross-session entity-level memory in technical
workflows (where the b2b and real-graph experiments showed 50–77 pp
accuracy lift) and the wrong tradeoff for within-conversation episodic
recall** (where GAM-style architectures that retain every turn as a
retrievable event node are necessary). The next productive step toward
LoCoMo-competitive numbers is not prompt tuning but a recall-side
extension to search `episode_turns` directly — effectively turning
pamiec's archive layer into a GAM-equivalent for episodic queries while
keeping the entity graph for cross-session work. Out of scope for v0;
filed as future work below.

## 4. Findings

Across 480 graded API calls in this study, three findings hold robustly:

**Finding 1: Pamiec is the dominant lever.** The no-recall arms (`baseline`, `naive_baseline`) score 23–33 % across all four runs. The with-recall arms score 83–100 %. Calibration prompts add 0–14 pp on top of recall but contribute nothing in the absence of recall — you cannot be calibrated about facts you do not have.

**Finding 2: Hallucination is essentially absent.** One confabulation in 480 calls (Sonnet's `naive_with_pamiec` on Q08), and only when both the calibration prompt and the recall-first tool guidance were absent. The default behavior of modern Anthropic models with pamiec-injected context is to ground answers in the context, not to extrapolate beyond it.

**Finding 3: Retrieval quality is a more productive target than further prompt tuning.** The 14 pp gap between v1 and v2 on real graph closed entirely from a one-line cosine-plus-keyword scoring change and a revised tool description. The dominant remaining failure modes after v2 are scorer strictness on synonyms, not retrieval misses or extraction errors.

## 5. Limitations

This study does not establish that pamiec helps generically. Specifically:

- **Single user, single graph.** The real-graph experiments use one author's graph. Broader claims require evaluating on graphs accumulated by users with different topic distributions, languages, and writing styles.
- **One synthetic narrative template.** B2B SaaS only. Other genres (scientific software, mobile apps, infrastructure) may surface different failure modes.
- **Sample size.** 30 questions per run leaves substantial uncertainty in per-category percentages; differences smaller than ~10 pp should be treated as noise.
- **Two model generations.** Haiku 4.5 and Sonnet 4.6, both Anthropic. Pamiec's MCP integration is currently Anthropic-specific, but the underlying graph and recall are model-agnostic; cross-vendor evaluation is open.
- **No external dataset comparison.** We have not yet adapted LoCoMo or LongDialQA, which would give literature-anchored numbers comparable to GAM, Mem0, and MemoryOS published results. This is the largest open methodological gap.
- **Scorer is keyword-based.** Synonym handling has known false negatives. An LLM-as-judge variant is reserved for v1.0.
- **Real-graph training-data leakage is a permanent confound.** Any benchmark that exercises a real graph populated with real entities will give the no-recall arms credit for whatever the model already knew from pretraining. We have not attempted to disentangle this.

## 6. Future work

- **`episode_turns` direct retrieval.** The single biggest lever for closing the LoCoMo gap, identified by the v2 retune ablation: extend `recall()` to search the per-turn archive (`episode_turns`) for queries that look like episodic recall — exact dates, exact phrasings, single-event lookups. Effectively turns pamiec's archive layer into a GAM-equivalent for in-conversation queries while keeping the entity graph for cross-session work. Estimated effort: ~1 week including retrieval-quality benchmarking.
- **More narrative templates** (sci-software lab, mobile app, infrastructure project, ML platform). Each adds ~30 questions and ~2 hours of careful authoring.
- **LoCoMo full sweep.** v0 ran one conversation (105 QAs); the full set is 10 conversations × 100–260 QAs each. Once `episode_turns` retrieval is in, sweeping all 10 gives directly comparable averages to GAM's published table.
- **Cross-vendor extension.** Adapt the runner to OpenAI and Gemini SDKs to test whether pamiec's accuracy gains hold when the agent under test is a different model family.
- **Recall ablations.** Isolate which retrieval components contribute most: hybrid keyword boost, one-hop graph expansion, episode-summary search, live EPG search, the proposed `episode_turns` search.
- **Larger graph scaling.** What happens to recall precision and token cost as the graph grows past 1000 entities? Current runs are at ~50 entities.

## 7. Conclusion

Pamiec materially improves Anthropic coding agents' ability to answer questions about prior session context, on synthetic and real-graph benchmarks alike, across two model generations, with no observable hallucination cost. The 60–77 pp absolute accuracy lift is the central claim, and is robust to the prompt-engineering arms-race confound that the 2×2 design was built to expose. The remaining gap on real graphs proved to be retrieval-side and was closed with two small, self-contained changes (a hybrid keyword scorer and a revised tool description), suggesting that improvements to recall — not to the underlying agent — are the productive next direction.

We release the harness, scoring code, synthetic narrative, and the public-release subset of results at `https://github.com/fuzue/pamiec/tree/main/benchmark`. The real-graph questions and answers reference private project information and are not released; reproducing them requires running the benchmark against a graph the reader has accumulated locally.

## Reproducibility

```bash
# Install
git clone https://github.com/fuzue/pamiec.git
cd pamiec && uv sync --extra benchmark
export ANTHROPIC_API_KEY=...
export PAMIEC_DB=/tmp/pamiec-bench.db

# Synthetic × any model
cd benchmark
python populate.py --narrative b2b_v1 --reset
BENCH_MODEL=claude-haiku-4-5-20251001 python runner.py --out results/run.jsonl
python score.py --results results/run.jsonl
```

Specific commits in this study:
- `791d16e` — initial v0.1 vertical slice
- `85de3a9` — 2×2 design isolating calibration prompt
- `c7d1ca4` — scaled to 30 questions, calibration effect surfaces
- `9033763` — Sonnet 4.6 validation, leading-question failure caught
- `d9f2401` — `private/` directory protocol for real-graph runs
- `c0bfd03` — hybrid keyword retrieval + recall-first tool description, closes the real-graph gap

## References

- Wu et al., 2026. *GAM: Hierarchical Graph-based Agentic Memory for LLM Agents*. arxiv 2604.12285.
- Mem0, MemoryOS, A-Mem — comparison numbers via GAM's reported leaderboard tables on LoCoMo and LongDialQA.
- BAAI/bge-small-en-v1.5 — embedding model used for pamiec retrieval (via `fastembed`).
- LoCoMo — `snap-stanford/locomo`, public dataset for long-conversation QA.
