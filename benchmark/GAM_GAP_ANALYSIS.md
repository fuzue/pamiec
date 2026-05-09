# Why is pamiec getting ~30% relative loss vs GAM on LoCoMo?

**A diagnostic note · 2026-05-09**

GAM published ~0.40 average F1 on LoCoMo. Pamiec scored 0.276 on conv-30 with Haiku 4.5. That's a 31% relative gap and **only +0.03 absolute F1 over baseline**, vs GAM's ~+0.15 over a similar baseline. Where does the loss come from?

This note traces the gap to its empirical root with a single dominant cause and three smaller ones.

## Diagnosis: pamiec doesn't search the table where the answers live

The LoCoMo gold answers are quite literally in the `episode_turns` SQLite table — the per-turn archive that pamiec writes during consolidation. But pamiec's `recall()` function searches three other surfaces and never touches it:

| Tier | Table | Searched by recall? |
|------|-------|---------------------|
| 3    | `topic_nodes` (entity summaries) | ✓ |
| 2a   | `episodes` (per-episode summaries) | ✓ |
| 1    | `epg_turns` (live, current-session buffer) | ✓ |
| 2b   | **`episode_turns`** (per-turn archive of past sessions) | **✗** |

We populated 19 LoCoMo sessions of conv-30 — that's 349 archived turns — and built no path from queries to them.

### Empirical proof

For each LoCoMo question we sampled as failing on `with_pamiec`, an ad-hoc cosine search over `episode_turns` returns the gold answer in the **top-2 results**:

```
Query: "When did Jon lose his banking job?"  Gold: 19 January 2023
  sim=0.727  "Jon: Hey Gina, I had to shut down my bank account..."
  sim=0.726  "Jon: ...Lost my job as a banker yesterday..."  ← answer (session_1 dated 20 Jan, "yesterday" = 19 Jan)

Query: "What does Jon's ideal dance studio look like?"  Gold: by the water, natural light, Marley flooring
  sim=0.789  "Jon: I'm prepping for my dance studio more than ever!"
  sim=0.765  "Jon: Check my ideal dance studio by the water."  ← answer

Query: "When did Gina lose her DoorDash job?"  Gold: January 2023
  sim=0.716  "Gina: Since I lost my job at Door Dash..."
  sim=0.704  "Gina: Unfortunately, I also lost my job at Door Dash this..."  ← answer
```

If `recall()` searched `episode_turns` with bge-small-v1.5 alone, these questions would land in the model's context. Pamiec's published 0.276 → likely ~0.40+ on the strong arm.

### Why isn't the answer making it into the entity nodes either?

Pamiec's extraction is Haiku-confidence-gated. From 19 LoCoMo sessions the extraction surfaced 7 entity nodes — which is the right number of *named real-world entities* (Jon, Gina, DoorDash, Jon's dance studio, Gina's clothing store, Finding Freedom, the bank). The extracted craws describe what each entity *is*, not every dated mention of it. "Jon lost banking job — yesterday" was filtered as a transient event below the confidence threshold. That's the right call for cross-session entity memory and exactly wrong for episodic QA.

## Other architectural gaps (smaller individual impact)

Beyond the missing `episode_turns` search, pamiec deviates from GAM in three other measurable ways:

### 1. No cross-encoder reranker

GAM uses `cross-encoder/ms-marco-MiniLM-L-6-v2` over the top-K bi-encoder candidates. Cross-encoders consistently score 5–10 percentage points higher than pure bi-encoder retrieval on QA benchmarks because they jointly encode the query and candidate rather than scoring independent embeddings.

Pamiec uses pure cosine similarity from `BAAI/bge-small-en-v1.5` for everything. Even with the hybrid keyword boost we added during the real-graph experiments, no cross-encoder reranking step exists.

**Expected gap contribution: ~0.03–0.05 F1 once `episode_turns` search lands.**

### 2. No multi-factor re-ranking

GAM applies multiplicative modulation factors during ranking:

```
Score(v, q) = P_sem(v|q) · ∏_{k ∈ K} β_k^{I_k(v,q)}
```

where K = {time, role, conf} and indicator functions detect:
- **β_time = 1.4**: query is time-sensitive (LoCoMo's category 3 always is)
- **β_role = 1.4**: query implies a specific speaker (multi-party signal)
- **β_conf = 1.2**: candidate passed self-consistency verification at encoding time

Pamiec applies a single linear recency boost (`0.8·sim + 0.2·recency`). No role detection. No confidence-aware reranking.

For LoCoMo specifically, the `β_time` factor matters — a non-trivial fraction of failing questions are temporal ("when did X happen?") and the answer often lives in the turn whose session-timestamp we can read directly. We have the data (`episode_turns.timestamp`) but no scoring path that uses it.

**Expected gap contribution: ~0.02–0.04 F1.**

### 3. Centroid-based vs LLM-triggered semantic boundary detection

GAM's ablation showed semantic-event-triggered partitioning at F1 = 40.00 vs fixed-window at 34.23 — a 6 pp lift from boundary quality alone. Pamiec uses cosine-centroid distance between sliding turn windows, which the GAM paper specifically classified as a fixed-window-class strategy.

For LoCoMo this matters less than it would for free-running conversations, because each LoCoMo "session" already comes pre-split. Pamiec's centroid detector mostly returns one segment per session.

**Expected gap contribution: ~0.01–0.03 F1.**

## Summary table

| GAM feature | Pamiec status | Estimated F1 contribution |
|-------------|---------------|---------------------------|
| Per-turn event archive accessible by retrieval | ✗ (data exists, query path missing) | **0.08–0.15** (dominant) |
| Cross-encoder reranker | ✗ (bi-encoder cosine + keyword boost only) | 0.03–0.05 |
| Multi-factor (time, role, conf) modulation | ✗ (linear recency only) | 0.02–0.04 |
| Semantic-event-triggered boundary detection | ✗ (centroid-based) | 0.01–0.03 |
| **Total expected close** | | **~0.14–0.27 F1** |

Closing the dominant gap alone (`episode_turns` retrieval) should put pamiec in the 0.36–0.43 range on LoCoMo conv-30 — at or above GAM's 0.40 published baseline on this conversation, on a *cheaper* model (Haiku 4.5 vs Qwen2.5-7B). Adding the cross-encoder rerank stacks on top.

## What's actually missing in the code

For the dominant gap, the change is small. `retrieval.recall()` needs:

```python
# new — currently absent
for turn in get_episode_turns():
    if not turn.embedding:
        # lazy-embed on first query — also worth backfilling at consolidation time
        turn.embedding = embed_batch([turn.text])[0]
        update_episode_turn_embedding(turn.id, to_bytes(turn.embedding))
    sim = cosine_similarity(query_vec, from_bytes(turn.embedding))
    if sim < 0.55:
        continue
    score = sim * 0.7 + recency * 0.3
    results.append(Result(
        text=f"[turn {iso_ts}] {role}: {text}",
        score=score * 0.7,  # discount vs entity nodes which are higher signal
        source="episode_turn",
        node_id=turn.id,
    ))
```

Also needs:
- A new `get_episode_turns()` and `update_episode_turn_embedding()` in `store.py`
- One-time backfill at consolidation time to embed turns up-front (current code stores them with `embedding=None`)

Estimated effort: 2–3 hours including a `score_locomo.py` re-run on conv-30 to verify the predicted lift. Effort to implement the cross-encoder rerank is another ~1 day; the multi-factor modulation is half a day.

## Recommendation

1. **Implement `episode_turns` retrieval first.** Highest expected lift, smallest change, validates the diagnosis on real data. If LoCoMo F1 climbs to ~0.40 we have the same architectural reach as GAM at lower model cost. If it doesn't move as predicted, the diagnosis is wrong and we learn something else.
2. **Then add a cross-encoder rerank.** Even on synthetic and real-graph benchmarks where pamiec already scores 97–100% accuracy, a reranker would tighten the calibrated arm's wrong-answers-with-relevant-context cases (the texlingo "real-time translation" miss in the real-graph experiment was a ranking-of-context issue, not a recall miss).
3. **Multi-factor modulation last.** The smallest single contribution, but likely the right framing for a methods-paper claim — pamiec extends GAM's modulation factors with an explicit `β_entity_node` discount when an entity-graph hit is overshadowed by a more specific turn-level hit.
