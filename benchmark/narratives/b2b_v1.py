"""B2B SaaS engineering team — synthetic multi-session narrative.

Three sessions of a fictional team working on 'Lumen', a customer-data
ingestion product at a fictional company 'Helix'. Each session introduces
specific entities, decisions, and relationships. The ground-truth tree
below is the single source of truth for question generation and scoring.

Conventions:
- Every entity that questions can reference appears in `entities`.
- Every decision has an `id`, `text`, optional `when`, and optional `why`.
- Edges are explicit (source, type, target) where source/target are entity names.
- `negative_probes` lists entity names that DELIBERATELY DO NOT appear in
  any session — used to test hallucination resistance.
"""

GROUND_TRUTH = {
    "project_name": "b2b_lumen_v1",

    "entities": {
        "Helix":     {"type": "company", "facts": ["B2B SaaS company", "headquartered in Lisbon"]},
        "Lumen":     {"type": "project", "facts": ["customer data ingestion product owned by Helix"]},
        "Maya":      {"type": "person",  "facts": ["engineering lead on Lumen", "joined Helix from Datadog"]},
        "Theo":      {"type": "person",  "facts": ["backend engineer on Lumen", "owns the ingestion pipeline"]},
        "Priya":     {"type": "person",  "facts": ["staff PM on Lumen"]},
        "Postgres":  {"type": "tool",    "facts": ["original primary store for Lumen telemetry"]},
        "ClickHouse":{"type": "tool",    "facts": ["replaced Postgres for telemetry in Lumen, decided session 2"]},
        "Acme":      {"type": "company", "facts": ["enterprise customer of Helix using Lumen at scale"]},
    },

    "decisions": [
        {"id": "d1", "session": 1,
         "text": "Lumen's ingestion pipeline will be rewritten in Rust",
         "why":  "current Python implementation cannot keep up with Acme's volume",
         "owner": "Theo"},
        {"id": "d2", "session": 2,
         "text": "Switched Lumen telemetry from Postgres to ClickHouse",
         "why":  "Postgres queries over 90 days of metrics took 40+ seconds; ClickHouse benchmarks showed 200ms",
         "owner": "Maya"},
        {"id": "d3", "session": 3,
         "text": "Postponed multi-region deployment for Lumen until Q3",
         "why":  "Acme is the only customer who'd benefit and they signed a renewal without it"},
    ],

    "edges": [
        ("Helix", "OWNS",       "Lumen"),
        ("Maya",  "LEADS",      "Lumen"),
        ("Theo",  "WORKS_ON",   "Lumen"),
        ("Priya", "WORKS_ON",   "Lumen"),
        ("Lumen", "USES",       "ClickHouse"),
        ("Lumen", "PREVIOUSLY_USED", "Postgres"),
        ("Acme",  "CUSTOMER_OF","Helix"),
    ],

    # Entities that MUST NOT appear anywhere in the sessions.
    "negative_probes": [
        "Snowflake", "MongoDB", "Cassandra",   # databases not chosen
        "Carlos", "Rin",                       # people not mentioned
        "Stripe", "AWS",                       # tools not discussed
    ],
}


SESSIONS = [
    # ────────────────────────────────────────────────────────────────────────
    # Session 1 — kickoff: introduce Helix/Lumen/team, decide Rust rewrite
    # ────────────────────────────────────────────────────────────────────────
    {
        "id": 1,
        "summary": "Lumen kickoff and Rust-rewrite decision",
        "turns": [
            ("user", "I'm Maya, the new engineering lead on Lumen. We're a B2B SaaS team at Helix here in Lisbon. Lumen is our customer data ingestion product. Wanted to think through what to focus on first."),
            ("assistant", "Welcome. Quick orienting questions: what's the team size, what's the current state of Lumen in production, and what's been the loudest pain you've inherited?"),
            ("user", "Three engineers right now. Theo owns the ingestion pipeline. Priya is our staff PM. I joined from Datadog. Lumen is shipping but we have one enterprise customer, Acme, whose volume is breaking us."),
            ("assistant", "Got it. What's the failure mode with Acme — throughput, latency, cost, correctness?"),
            ("user", "Throughput. Theo's been profiling the Python ingester and we hit a wall around 40k events/sec. Acme needs at least 200k sustained. We've been talking about a rewrite in Rust for the hot path."),
            ("assistant", "200k vs 40k is a 5x gap; rewrite-vs-optimize calls usually break around 3x. Has Theo identified specific Python-level bottlenecks (GIL, JSON parsing, async) that a profiler can't squeeze further?"),
            ("user", "Yeah, he's exhausted the easy wins — orjson, uvloop, batching. The remaining bottleneck is the GIL when we fan out per-tenant. Decision: we're going to rewrite the ingester in Rust. Theo will own it."),
            ("assistant", "Reasonable. Two follow-ups worth capturing: timeline target, and what stays in Python vs gets rewritten."),
            ("user", "Hot path only — the pipeline. Control plane, schema management, billing all stay in Python. Targeting an internal cutover in 8 weeks."),
            ("assistant", "Understood. Rust ingester for the hot path only, Python for control plane, 8-week target with Theo as owner. Anything else for this session?"),
            ("user", "That's it for now."),
        ],
    },

    # ────────────────────────────────────────────────────────────────────────
    # Session 2 — telemetry storage: Postgres → ClickHouse
    # ────────────────────────────────────────────────────────────────────────
    {
        "id": 2,
        "summary": "Telemetry storage migration from Postgres to ClickHouse",
        "turns": [
            ("user", "Different topic today. Lumen's internal telemetry — request latencies, error rates, per-tenant throughput — has been stored in Postgres since day one. Queries over 90 days are now taking 40+ seconds. It's becoming a problem during incident review."),
            ("assistant", "What's the data shape and volume? Time-series with high cardinality (per-tenant, per-route) is exactly where Postgres struggles."),
            ("user", "Right, that's the issue. Around 2 billion rows, ~50 metric series, 200+ tenants. We've been considering ClickHouse. I had Theo run a benchmark last week."),
            ("assistant", "And the numbers?"),
            ("user", "Same 90-day query: 40s on Postgres, 200ms on ClickHouse. We're going to migrate. Theo will run the dual-write period for 2 weeks, then cut over."),
            ("assistant", "200x speedup on the central query is decisive. Two checks before commit: are you OK losing Postgres' transactional consistency for telemetry (telemetry should be append-only so probably yes), and do you have an exit plan if ClickHouse ops turn out worse than expected?"),
            ("user", "Append-only for telemetry, yes. Exit plan is the dual-write — we keep Postgres warm for 30 days post-cutover. If ClickHouse ops surprise us, we flip back."),
            ("assistant", "Decision recorded: Lumen telemetry moves from Postgres to ClickHouse. Owner Maya, Theo runs the migration, dual-write for 2 weeks, Postgres kept warm for 30 days post-cutover."),
            ("user", "Yes."),
        ],
    },

    # ────────────────────────────────────────────────────────────────────────
    # Session 3 — multi-region punt
    # ────────────────────────────────────────────────────────────────────────
    {
        "id": 3,
        "summary": "Multi-region deployment postponed to Q3",
        "turns": [
            ("user", "Quick one. The roadmap had Lumen multi-region deployment for this quarter. Priya wants to push it."),
            ("assistant", "What's driving the push?"),
            ("user", "Acme was the only customer asking for it, and they just renewed for a year without making it a condition. So the demand pull is gone for now. Two other customers that asked about regions in pre-sales never closed."),
            ("assistant", "How much engineering capacity would multi-region have cost you this quarter?"),
            ("user", "Six weeks across the team. Theo's deep in the Rust rewrite, Priya doesn't want him pulled. We're punting to Q3."),
            ("assistant", "Decision noted: multi-region deployment postponed to Q3. Reason: Acme renewed without it being a condition, and no other customer is gating on it."),
            ("user", "Right."),
        ],
    },
]
