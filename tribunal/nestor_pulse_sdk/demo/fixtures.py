"""
In-memory fixture data for demo mode. Matches the mock data the JSX screens
were authored against (Sofia Delaere / EpicImpact / Mercator etc.) so the
visual continuity from Claude Design carries over to the wired demo.

Shapes mirror the real API response schemas so swapping demo -> real is a
one-line change in server.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 5, 28, 14, 22, tzinfo=timezone.utc)


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def _rel(when: datetime) -> str:
    """Human-friendly relative time used by the row 'when' display."""
    delta = NOW - when
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return when.strftime("%d %b")


# ---- workspace + user ------------------------------------------------------

WORKSPACE = {
    "id": "00000000-0000-0000-0000-000000000001",
    "name": "EpicImpact",
}

USERS = {
    "u_sofia":   {"id": "u_sofia",   "initials": "SD", "name": "Sofia Delaere",   "email": "sofia@epicimpact.be",  "role": "Owner"},
    "u_mira":    {"id": "u_mira",    "initials": "MK", "name": "Mira Klein",      "email": "mira@epicimpact.be",   "role": "Researcher"},
    "u_tomas":   {"id": "u_tomas",   "initials": "TL", "name": "Tomas Lefevre",   "email": "tomas@epicimpact.be",  "role": "Researcher"},
    "u_priya":   {"id": "u_priya",   "initials": "PS", "name": "Priya Shah",      "email": "priya@epicimpact.be",  "role": "Researcher"},
    "u_antoine": {"id": "u_antoine", "initials": "AN", "name": "Antoine N.",      "email": "antoine@epicimpact.be","role": "Researcher"},
    "u_lina":    {"id": "u_lina",    "initials": "LH", "name": "Lina H.",         "email": "lina@epicimpact.be",   "role": "Compliance"},
}

CURRENT_USER = USERS["u_sofia"]


# ---- projects --------------------------------------------------------------
#
# Stable UUIDs so the URL `Project.html?id=...` works across reloads.

PROJECTS = [
    {
        "id": "11111111-1111-1111-1111-000000000001",
        "name": "lifecycle revamp",
        "client_name": "Mercator",
        "status": "active",
        "owner": USERS["u_mira"],
        "team": [USERS["u_mira"], USERS["u_sofia"], USERS["u_antoine"], USERS["u_priya"]],
        "briefing_count": 14,
        "active_count": 1,
        "updated_at": _ago(hours=2).isoformat(),
        "updated_rel": "Updated 2h ago",
        "about": "Lifecycle marketing teardown for Mercator's retail division. Focus areas: post-purchase nurture flows, win-back automation, churn signal definition.",
        "documents": [
            {"id": "d1", "name": "Mercator-brand-guidelines.pdf",      "size_kb": 412, "uploaded_by": "Sofia Delaere", "uploaded_rel": "2 weeks ago"},
            {"id": "d2", "name": "Mercator-Q1-customer-segments.pdf",  "size_kb": 188, "uploaded_by": "Mira Klein",    "uploaded_rel": "12 days ago"},
            {"id": "d3", "name": "Brevo-current-flows-audit.pdf",      "size_kb": 567, "uploaded_by": "Mira Klein",    "uploaded_rel": "5 days ago"},
        ],
    },
    {
        "id": "11111111-1111-1111-1111-000000000002",
        "name": "compliance research",
        "client_name": "Argo Legal",
        "status": "active",
        "owner": USERS["u_tomas"],
        "team": [USERS["u_tomas"], USERS["u_sofia"]],
        "briefing_count": 22,
        "active_count": 1,
        "updated_at": _ago(minutes=24).isoformat(),
        "updated_rel": "Updated 24m ago",
        "about": "Ongoing regulatory horizon scan covering EU AI Act, GDPR enforcement actions, and sector-specific AI governance for client-facing AI deployments.",
        "documents": [
            {"id": "d4", "name": "EU-AI-Act-final-text-2024.pdf",            "size_kb": 1240, "uploaded_by": "Tomas Lefevre", "uploaded_rel": "3 months ago"},
            {"id": "d5", "name": "Argo-internal-AI-governance-charter.pdf",  "size_kb": 92,   "uploaded_by": "Tomas Lefevre", "uploaded_rel": "1 month ago"},
        ],
    },
    {
        "id": "11111111-1111-1111-1111-000000000003",
        "name": "pricing experiment",
        "client_name": "Helix Analytics",
        "status": "active",
        "owner": USERS["u_priya"],
        "team": [USERS["u_priya"], USERS["u_sofia"], USERS["u_mira"]],
        "briefing_count": 8,
        "active_count": 0,
        "updated_at": _ago(days=1).isoformat(),
        "updated_rel": "Updated yesterday",
        "about": "Q2 pricing experiment design for Helix's mid-market tier. Comparable SaaS pricing benchmarks, willingness-to-pay surveys, packaging frameworks.",
        "documents": [
            {"id": "d6", "name": "Helix-current-pricing-snapshot.pdf", "size_kb": 78,  "uploaded_by": "Priya Shah", "uploaded_rel": "9 days ago"},
        ],
    },
    {
        "id": "11111111-1111-1111-1111-000000000004",
        "name": "brand position refresh",
        "client_name": "Norden Coffee",
        "status": "active",
        "owner": USERS["u_sofia"],
        "team": [USERS["u_sofia"], USERS["u_lina"]],
        "briefing_count": 5,
        "active_count": 0,
        "updated_at": _ago(days=2).isoformat(),
        "updated_rel": "Updated 26 May",
        "about": "Brand position refresh for Norden Coffee's DTC subscription product. Category landscape, competitor positioning maps, retention benchmarks.",
        "documents": [
            {"id": "d7", "name": "Norden-brand-history-2018-2025.pdf", "size_kb": 304, "uploaded_by": "Sofia Delaere", "uploaded_rel": "3 weeks ago"},
        ],
    },
    {
        "id": "11111111-1111-1111-1111-000000000005",
        "name": "channel mix Q3",
        "client_name": "Veridian Foods",
        "status": "active",
        "owner": USERS["u_sofia"],
        "team": [USERS["u_sofia"]],
        "briefing_count": 3,
        "active_count": 0,
        "updated_at": _ago(days=4).isoformat(),
        "updated_rel": "Updated 24 May",
        "about": "Quarterly channel mix optimisation. Attribution methodology evaluation across paid social, search, OOH, and retail trade.",
        "documents": [],
    },
    {
        "id": "11111111-1111-1111-1111-000000000006",
        "name": "category landscape",
        "client_name": "Hexcel Materials",
        "status": "active",
        "owner": USERS["u_priya"],
        "team": [USERS["u_priya"], USERS["u_antoine"], USERS["u_mira"], USERS["u_lina"]],
        "briefing_count": 11,
        "active_count": 0,
        "updated_at": _ago(days=6).isoformat(),
        "updated_rel": "Updated 22 May",
        "about": "Advanced composites category landscape. Adjacent material entrants, supply chain shifts, downstream M&A activity.",
        "documents": [],
    },
]

PROJECTS_BY_ID = {p["id"]: p for p in PROJECTS}


# ---- runs ------------------------------------------------------------------

RUNS = [
    {
        "id": "22222222-0000-0000-0000-000000000001",
        "project_id": PROJECTS[0]["id"],
        "title": "Competitive teardown -- Brevo onboarding flow Q2 2026",
        "engine": "sdk",
        "status": "running",
        "owner": USERS["u_mira"],
        "started_at": _ago(minutes=12).isoformat(),
        "elapsed_seconds": 12 * 60 + 34,
        "estimated_remaining_seconds": 13 * 60,
        "created_at": _ago(minutes=12).isoformat(),
        "cost_usd_total": "0.47",
        "tokens_total": 12440,
    },
    {
        "id": "22222222-0000-0000-0000-000000000002",
        "project_id": PROJECTS[1]["id"],
        "title": "EU AI Act Art. 50 -- disclosure requirements for consumer assistants",
        "engine": "sdk",
        "status": "running",
        "owner": USERS["u_tomas"],
        "started_at": _ago(minutes=24).isoformat(),
        "elapsed_seconds": 24 * 60,
        "estimated_remaining_seconds": 6 * 60,
        "created_at": _ago(minutes=24).isoformat(),
        "cost_usd_total": "0.92",
        "tokens_total": 24180,
    },
    {
        "id": "22222222-0000-0000-0000-000000000003",
        "project_id": PROJECTS[3]["id"],
        "title": "DTC retention benchmarks -- coffee subscriptions 2025",
        "engine": "sdk",
        "status": "completed",
        "owner": USERS["u_sofia"],
        "started_at": _ago(hours=2, minutes=30).isoformat(),
        "completed_at": _ago(hours=2).isoformat(),
        "created_at": _ago(hours=2, minutes=30).isoformat(),
        "cost_usd_total": "3.12",
        "tokens_total": 84230,
    },
    {
        "id": "22222222-0000-0000-0000-000000000004",
        "project_id": PROJECTS[2]["id"],
        "title": "Vertical SaaS M&A activity Q1 2026",
        "engine": "adk",
        "status": "completed",
        "owner": USERS["u_priya"],
        "started_at": _ago(days=1, hours=2).isoformat(),
        "completed_at": _ago(days=1, hours=1).isoformat(),
        "created_at": _ago(days=1, hours=2).isoformat(),
        "cost_usd_total": "2.84",
        "tokens_total": 71540,
    },
    {
        "id": "22222222-0000-0000-0000-000000000005",
        "project_id": PROJECTS[1]["id"],
        "title": "Regulatory landscape -- agentic systems in healthcare EU/US",
        "engine": "sdk",
        "status": "completed",
        "owner": USERS["u_tomas"],
        "started_at": _ago(days=1, hours=4).isoformat(),
        "completed_at": _ago(days=1, hours=3).isoformat(),
        "created_at": _ago(days=1, hours=4).isoformat(),
        "cost_usd_total": "4.06",
        "tokens_total": 108290,
    },
    {
        "id": "22222222-0000-0000-0000-000000000006",
        "project_id": PROJECTS[4]["id"],
        "title": "Channel attribution methodology -- paid social 2025",
        "engine": "adk",
        "status": "failed",
        "owner": USERS["u_sofia"],
        "started_at": _ago(days=2).isoformat(),
        "error_message": "Gemini deep research timed out after 35m. Retry with fewer sources or split the question.",
        "created_at": _ago(days=2).isoformat(),
        "cost_usd_total": "0.18",
        "tokens_total": 4280,
    },
    {
        "id": "22222222-0000-0000-0000-000000000007",
        "project_id": PROJECTS[5]["id"],
        "title": "Composites supply chain -- China + India producer shifts 2024-2025",
        "engine": "sdk",
        "status": "completed",
        "owner": USERS["u_priya"],
        "started_at": _ago(days=3).isoformat(),
        "completed_at": _ago(days=3, hours=-1).isoformat(),
        "created_at": _ago(days=3).isoformat(),
        "cost_usd_total": "3.91",
        "tokens_total": 96420,
    },
    {
        "id": "22222222-0000-0000-0000-000000000008",
        "project_id": PROJECTS[0]["id"],
        "title": "Win-back automation -- best-in-class examples 2024-2025",
        "engine": "sdk",
        "status": "completed",
        "owner": USERS["u_mira"],
        "started_at": _ago(days=4).isoformat(),
        "completed_at": _ago(days=4, hours=-1).isoformat(),
        "created_at": _ago(days=4).isoformat(),
        "cost_usd_total": "2.45",
        "tokens_total": 62110,
    },
]

# Augment each run with derived display fields
for _r in RUNS:
    _when = datetime.fromisoformat(_r["created_at"])
    _r["when_rel"] = _rel(_when)
    _r["project"] = PROJECTS_BY_ID[_r["project_id"]]["client_name"] + " - " + PROJECTS_BY_ID[_r["project_id"]]["name"]

RUNS_BY_ID = {r["id"]: r for r in RUNS}


# ---- sources (for report viewer citations) ---------------------------------

SOURCES = [
    {"id": "s1", "title": "Coffee Subscription Market Report 2025",          "url": "https://example.com/coffee-subscriptions-2025",  "provider": "Claude",  "fetched_at": "2026-05-28T11:30:00Z", "snapshot_text": "DTC coffee subscription churn rates in 2025 averaged 7.4% monthly across surveyed roasters, with retention curves stabilising around month 6. Top-quartile operators achieved 4.1% through onboarding personalisation and flavour-discovery surveys."},
    {"id": "s2", "title": "Trade Industry Quarterly Q2 2025",                 "url": "https://example.com/trade-q2-2025",              "provider": "OpenAI",  "fetched_at": "2026-05-28T11:32:00Z", "snapshot_text": "European specialty coffee subscriptions grew 18% YoY in Q1 2025, driven primarily by under-30 households trading down from cafe consumption. Average ticket size fell 6%, with subscribers favouring smaller, more frequent shipments."},
    {"id": "s3", "title": "Specialty Coffee Association Annual",              "url": "https://example.com/sca-annual-2025",            "provider": "Gemini",  "fetched_at": "2026-05-28T11:34:00Z", "snapshot_text": "Member surveys show 62% of specialty subscription operators consider personalisation as their top retention driver, ahead of price (14%) and shipping speed (11%)."},
    {"id": "s4", "title": "DTC Subscription Benchmarks 2025",                 "url": "https://example.com/dtc-benchmarks-2025",        "provider": "Claude",  "fetched_at": "2026-05-28T11:36:00Z", "snapshot_text": "Cohort analysis across 142 DTC subscription brands shows that brands offering a guided onboarding within 7 days of first purchase achieve a 23% lift in month-3 retention versus brands relying on a single welcome email."},
    {"id": "s5", "title": "Forrester Subscription Economy 2024",              "url": "https://example.com/forrester-sub-2024",         "provider": "OpenAI",  "fetched_at": "2026-05-28T11:38:00Z", "snapshot_text": "Subscription brands that introduce a flavour-or-style preference quiz at signup see 31% lower 90-day churn versus brands without preference capture, controlling for product category and price band."},
    {"id": "s6", "title": "Coffee Retail Quarterly",                          "url": "https://example.com/coffee-retail-q1",            "provider": "Gemini",  "fetched_at": "2026-05-28T11:40:00Z", "snapshot_text": "Subscription bag size of 250g outperformed 340g and 500g on retention in 2024, suggesting subscribers prefer smaller, more frequent shipments over bulk."},
    {"id": "s7", "title": "Specialty Roaster Survey 2025",                    "url": "https://example.com/roaster-survey-2025",        "provider": "Claude",  "fetched_at": "2026-05-28T11:42:00Z", "snapshot_text": "Among 287 surveyed specialty roasters with subscription programs, 71% reported plans to introduce or expand a personalisation feature in 2026, with flavour-profile matching as the most common."},
    {"id": "s8", "title": "DTC Coffee Operators Interview Series",            "url": "https://example.com/dtc-interviews-2025",        "provider": "OpenAI",  "fetched_at": "2026-05-28T11:44:00Z", "snapshot_text": "Operators consistently identified the second-month cliff as their largest retention challenge. Common interventions included a free swap, a personalised tasting note insert, and proactive customer service outreach at day 28."},
]

SOURCES_BY_ID = {s["id"]: s for s in SOURCES}


# ---- report body (for completed run id=22222222-...-000003) ---------------

REPORT_BODY = {
    "run_id": RUNS[2]["id"],
    "title": RUNS[2]["title"],
    "sections": [
        {
            "heading": "Executive summary",
            "paragraphs": [
                "DTC coffee subscriptions in 2025 sit at an inflection. The category grew 18% YoY in Europe [2] but average ticket size fell 6% [2] as subscribers traded down from cafe consumption to smaller, more frequent shipments [6]. Top-quartile operators on retention -- those holding monthly churn under 4.5% [1] -- share three operating habits, all evidenced in the source set below.",
            ],
        },
        {
            "heading": "What the leaders do differently",
            "paragraphs": [
                "First, leaders invest in onboarding within seven days of first purchase. Cohort data across 142 DTC subscription brands shows brands with structured 7-day onboarding flows achieve a 23% lift in month-3 retention versus brands relying on a single welcome email [4]. Norden's current welcome sequence ends at day 2.",
                "Second, leaders capture preferences at signup. A flavour-or-style preference quiz at signup correlates with 31% lower 90-day churn versus signup flows without preference capture [5]. Among 287 surveyed specialty roasters, 71% plan to introduce or expand personalisation in 2026 [7] -- the moat is closing.",
                "Third, leaders treat the second month as a tier-one risk window. Operators in the DTC Coffee Interview Series [8] consistently identified the second-month cliff as their largest retention challenge and intervened via day-28 outreach, free swaps, and tasting-note inserts.",
            ],
        },
        {
            "heading": "Format and shipment cadence",
            "paragraphs": [
                "Smaller bags win. 250g subscription bags outperformed 340g and 500g on retention in 2024 [6] -- subscribers prefer smaller, more frequent shipments over bulk. Norden's default 500g bag is at the wrong end of this curve.",
                "Among Specialty Coffee Association members, 62% rank personalisation as their top retention driver, ahead of price (14%) and shipping speed (11%) [3]. Discount-first competition is not where the category is going.",
            ],
        },
        {
            "heading": "Recommendations for the Norden refresh",
            "paragraphs": [
                "The brand position refresh should lead with three operating commitments rather than positioning prose alone:",
            ],
            "list": [
                "Introduce a 5-question flavour preference quiz at signup; route to a starting bag tailored to the answers.",
                "Move default bag size to 250g with a 'try two bags this month' upgrade nudge in month two.",
                "Add a structured 7-day onboarding flow: day 1 brew guide, day 3 origin story video, day 5 flavour-profile feedback prompt, day 7 'rate your first bag' survey.",
                "Add a day-28 proactive outreach: free swap or tasting-note insert before the month-2 cliff hits.",
            ],
        },
        {
            "heading": "Risks and unknowns",
            "paragraphs": [
                "The sources skew Anglo-American. European-only data is thinner, particularly outside the UK and Germany. Norden's Belgian/Dutch market may show different second-month behaviour given the espresso-first consumption habit, which the sources don't address.",
            ],
        },
    ],
}


# ---- audit -----------------------------------------------------------------

AUDIT_CALLS = [
    {"timestamp": "2026-05-28T11:30:14Z", "provider": "Claude",  "model": "claude-sonnet-4-6",         "tokens_in": 412,   "tokens_out": 2840,  "cost_usd": "0.0241", "purpose": "Deep research -- pass 1"},
    {"timestamp": "2026-05-28T11:31:42Z", "provider": "OpenAI",  "model": "o4-mini-deep-research",     "tokens_in": 380,   "tokens_out": 3120,  "cost_usd": "0.0188", "purpose": "Deep research -- pass 1"},
    {"timestamp": "2026-05-28T11:33:08Z", "provider": "Gemini",  "model": "deep-research-pro-preview", "tokens_in": 401,   "tokens_out": 2670,  "cost_usd": "0.0214", "purpose": "Deep research -- pass 1"},
    {"timestamp": "2026-05-28T11:42:11Z", "provider": "Claude",  "model": "claude-sonnet-4-6",         "tokens_in": 8420,  "tokens_out": 6112,  "cost_usd": "0.0612", "purpose": "Citation extraction"},
    {"timestamp": "2026-05-28T11:44:33Z", "provider": "Claude",  "model": "claude-opus-4-7",           "tokens_in": 11200, "tokens_out": 4820,  "cost_usd": "0.4882", "purpose": "Synthesis -- final pass"},
    {"timestamp": "2026-05-28T11:48:01Z", "provider": "Claude",  "model": "claude-sonnet-4-6",         "tokens_in": 6840,  "tokens_out": 1240,  "cost_usd": "0.0392", "purpose": "Quality gate -- LLM judge"},
]

VERIFY_RESULTS = [
    {"run_id": RUNS[2]["id"], "title": RUNS[2]["title"], "verified_at": "2026-05-28T11:50:22Z", "ok": True,  "broken_at": None},
    {"run_id": RUNS[3]["id"], "title": RUNS[3]["title"], "verified_at": "2026-05-27T16:22:14Z", "ok": True,  "broken_at": None},
    {"run_id": RUNS[4]["id"], "title": RUNS[4]["title"], "verified_at": "2026-05-27T12:08:41Z", "ok": True,  "broken_at": None},
    {"run_id": RUNS[6]["id"], "title": RUNS[6]["title"], "verified_at": "2026-05-25T09:11:02Z", "ok": True,  "broken_at": None},
    {"run_id": RUNS[7]["id"], "title": RUNS[7]["title"], "verified_at": "2026-05-24T15:42:18Z", "ok": True,  "broken_at": None},
]

COSTS_BY_MONTH = {
    "2026-05": {
        "total_usd": "184.62",
        "by_provider": [
            {"provider": "Claude",  "cost_usd": "112.40", "percent": 60.9},
            {"provider": "OpenAI",  "cost_usd": "38.92",  "percent": 21.1},
            {"provider": "Gemini",  "cost_usd": "33.30",  "percent": 18.0},
        ],
        "by_project": [
            {"project_id": PROJECTS[0]["id"], "name": "Mercator - lifecycle revamp",        "cost_usd": "54.20"},
            {"project_id": PROJECTS[1]["id"], "name": "Argo Legal - compliance research",    "cost_usd": "62.40"},
            {"project_id": PROJECTS[2]["id"], "name": "Helix Analytics - pricing experiment","cost_usd": "21.10"},
            {"project_id": PROJECTS[3]["id"], "name": "Norden Coffee - brand position",      "cost_usd": "18.92"},
            {"project_id": PROJECTS[4]["id"], "name": "Veridian Foods - channel mix Q3",     "cost_usd": "9.40"},
            {"project_id": PROJECTS[5]["id"], "name": "Hexcel Materials - category landscape","cost_usd": "18.60"},
        ],
    },
}


# ---- in-memory POST stub for new briefings ---------------------------------
# Mutated by POST /api/runs in demo mode. Resets on process restart.

def make_new_run(project_id: str, brief: str, engine: str, comparison_id: str | None = None) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    new = {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "title": brief.split("\n")[0][:80],
        "brief": brief,
        "engine": engine,
        "status": "running",
        "owner": CURRENT_USER,
        "started_at": now.isoformat(),
        "elapsed_seconds": 0,
        "estimated_remaining_seconds": 30,  # demo: auto-completes in ~30s
        "created_at": now.isoformat(),
        "cost_usd_total": "0.00",
        "tokens_total": 0,
        "when_rel": "just now",
        "project": PROJECTS_BY_ID[project_id]["client_name"] + " - " + PROJECTS_BY_ID[project_id]["name"],
        "comparison_id": comparison_id,
        "_demo_created": True,  # flag for demo/api.py auto-progression
    }
    RUNS.insert(0, new)
    RUNS_BY_ID[new["id"]] = new
    return new
