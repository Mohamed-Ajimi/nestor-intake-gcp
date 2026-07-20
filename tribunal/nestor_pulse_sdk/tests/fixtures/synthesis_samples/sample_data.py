"""
Canned synthesis output samples for the ADR-005 Outcomes spike.

These samples represent synthetic (not real client) synthesis outputs covering
the quality spectrum that the existing rule-based QualityGate handles:
  - PASS: well-structured, long enough, narrative prose
  - ITERATE: borderline (single fixable issue)
  - FAIL: multiple structural issues or too short

Five samples from three research domains:
  1. strategy_healthy    — EXPECTED: pass   (complete strategic brief)
  2. competitor_bullets  — EXPECTED: iterate (too many bullet points, single issue)
  3. short_stub          — EXPECTED: fail    (too short)
  4. no_headers          — EXPECTED: fail    (missing section structure)
  5. mixed_quality       — EXPECTED: pass    (borderline but meets all 3 checks)

None of these contain real client data (T-08-01 mitigation).
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SynthesisSample:
    sample_id: str
    description: str
    brief_topic: str
    focus_areas: list[str]
    synthesis: str
    expected_existing_verdict: str  # what the deterministic gate should return


# ---------------------------------------------------------------------------
# Sample 1: Healthy strategic synthesis (should PASS)
# ---------------------------------------------------------------------------

SAMPLE_1 = SynthesisSample(
    sample_id="strategy_healthy",
    description="Complete strategic synthesis with headers, narrative, and adequate length",
    brief_topic="Market entry strategy for sustainable packaging in the Benelux region",
    focus_areas=["competitive_landscape", "regulatory_environment", "consumer_trends"],
    expected_existing_verdict="pass",
    synthesis="""
# Executive Summary

The sustainable packaging market in Benelux presents a compelling opportunity for market entry
over the next 24 months. Regulatory tailwinds from the EU Packaging Regulation 2025 (PPWR),
combined with measurable consumer willingness to pay a premium, create a structural demand pull
that incumbents have not yet fully exploited. This synthesis consolidates findings from primary
research into three strategic recommendation tiers.

## Competitive Landscape

The Benelux packaging market is dominated by four players holding approximately 68% market
share: DS Smith, Smurfit Kappa, Sonoco, and Huhtamaki. Each has made sustainability pledges,
but none has moved aggressively on the SME mid-market segment (50–500 employees), which
represents roughly 34% of total packaging spend by volume. This gap defines the entry vector.

Competitive intensity is moderate in the premium tier and high in the commodity segment.
New entrants using bio-based or recycled-content materials at cost parity with conventional
plastics have demonstrated 18-month payback periods in comparable Northern European markets
(Netherlands 2023, Denmark 2024). The window for differentiation narrows as DS Smith's
announced capacity expansion completes in Q3 2026.

## Regulatory Environment

The EU Packaging and Packaging Waste Regulation (PPWR), entering force 2025–2028 in phased
tranches, mandates 30% recycled content in plastic packaging by 2030 and bans specific
single-use formats. Belgium has front-loaded implementation via Fostplus extended producer
responsibility (EPR) fees revised upward in January 2025 — creating immediate cost pressure
for packaging buyers.

This regulatory regime is a structural tailwind: companies switching to PPWR-compliant
alternatives before mandatory deadlines can lock in supply agreements at current (lower)
prices before compliance-driven demand spikes. First-mover credentialing value is real;
procurement teams cite "certification readiness" as a top-3 buying criterion in 2025 surveys.

## Consumer Trends

Consumer research across 1,800 Benelux respondents (Q1 2025) shows 61% report willingness
to pay 5–12% premium for verified sustainable packaging, rising to 74% among 25–44
demographics. Importantly, this preference translates to shelf behaviour only when the
sustainability claim is independently certified (e.g., Cradle to Cradle, FSC, or SCS
Global Services). Self-declared sustainability claims have eroded trust significantly since
2022 greenwashing scandals.

The implication for go-to-market is that certification infrastructure is table stakes, not
a differentiator. Differentiation will come from supply chain transparency tooling and
co-design services for brand clients.

## Strategic Recommendations

**Tier 1 (Immediate — 0-6 months):** Secure PPWR compliance pre-certification for core
SKUs. Commission an independent lifecycle assessment (LCA) from a recognised Belgian body.
Establish commercial relationships with 3–5 anchor customers in the mid-market SME segment.

**Tier 2 (6-18 months):** Build out co-design capability for custom sustainable formats.
This is the margin lever — DS Smith and Smurfit do not offer design services below €500K
annual contract value. Target food & beverage and e-commerce verticals where regulatory
pressure and brand sensitivity overlap.

**Tier 3 (18-36 months):** Consider JV or acquisition of Belgian/Dutch recycling
infrastructure to close the loop. Regulatory incentives for closed-loop certification are
projected to arrive via PPWR secondary legislation in 2027; being vertically integrated
at that point is a significant competitive moat.

## Risk Register

The primary execution risk is lead time on bio-based material supply. Current EU production
capacity for PHA (polyhydroxyalkanoates) and PLA compounds is 60% subscribed through 2026.
Alternative: ISCC+ certified recycled polyolefins have 6-month availability versus 14-month
for bio-based. This substitution slightly weakens the premium narrative but remains
PPWR-compliant and certifiable.

Secondary risk: Belgian EPR fee schedule revisions are annual. Model three scenarios
(base, upside, downside) in financial projections.
""",
)


# ---------------------------------------------------------------------------
# Sample 2: Competitor analysis — too many bullet points (should ITERATE)
# ---------------------------------------------------------------------------

SAMPLE_2 = SynthesisSample(
    sample_id="competitor_bullets",
    description="Competitor analysis rendered as bullets — insufficient narrative prose",
    brief_topic="Competitor intelligence on Elicit and Consensus research tools",
    focus_areas=["product_capabilities", "pricing_model", "market_positioning"],
    expected_existing_verdict="iterate",
    synthesis="""
# Competitor Intelligence: Elicit vs Consensus

## Overview

Research synthesis tools targeting academic and business users.

## Elicit

- Founded 2021 by Ought
- Focused on systematic literature reviews
- Strengths:
  - Large-scale evidence synthesis
  - Structured data extraction from papers
  - Elicit Notebooks for collaborative review
- Weaknesses:
  - Academic-only focus
  - No business research integration
  - Slow on non-academic queries
- Pricing:
  - Free tier: 5 queries/month
  - Plus: $12/month
  - Team: $50/seat/month
- Market position:
  - Leader in academic systematic reviews
  - Used by 80,000+ researchers

## Consensus

- Founded 2022
- Search through 200M+ peer-reviewed papers
- Strengths:
  - Fast evidence answers
  - Citation exploration
  - Quality filters (RCT, meta-analysis)
- Weaknesses:
  - Academic-only corpus
  - No grey literature
  - Limited export options
- Pricing:
  - Free tier available
  - Premium: $9.99/month
  - Team plan enterprise pricing
- Market position:
  - Strong in clinical/medical research
  - Growing life sciences vertical

## Comparison Summary

- Both: academic only
- Elicit: better for systematic reviews
- Consensus: better for quick evidence lookups
- Neither: competes with Nestor on business research
- Key differentiator for Nestor: multi-LLM parallel deep research on business topics
- Both lack: executive report formats, strategic memo output, slide deck generation

## Implications

- Nestor niche is defensible
- No direct competitor on business strategic research
- Opportunity to serve customers who use both Elicit and Consensus but need business data
""",
)


# ---------------------------------------------------------------------------
# Sample 3: Short stub — fails minimum length check (should FAIL)
# ---------------------------------------------------------------------------

SAMPLE_3 = SynthesisSample(
    sample_id="short_stub",
    description="Incomplete synthesis — too short, fails word count check",
    brief_topic="Sentiment analysis of consumer electronics brand perception",
    focus_areas=["brand_sentiment", "social_media_trends"],
    expected_existing_verdict="fail",
    synthesis="""
# Brand Sentiment Overview

## Key Findings

The sentiment analysis across social media platforms for the target consumer electronics
brands shows mixed results. Positive sentiment is strongest on Instagram and TikTok,
while Twitter/X shows more neutral-to-negative patterns.

## Recommendations

Further research is needed to draw actionable conclusions.
""",
)


# ---------------------------------------------------------------------------
# Sample 4: No headers — fails structure check (should FAIL)
# ---------------------------------------------------------------------------

SAMPLE_4 = SynthesisSample(
    sample_id="no_headers",
    description="Synthesis without section headers — fails structure requirement",
    brief_topic="Digital transformation readiness in Belgian SME manufacturing sector",
    focus_areas=["technology_adoption", "skills_gap", "investment_appetite"],
    expected_existing_verdict="fail",
    synthesis="""
The Belgian manufacturing SME sector faces a significant digital transformation challenge
as Industry 4.0 adoption accelerates among larger competitors. A survey of 450 Belgian
manufacturing SMEs (under 250 employees) conducted in Q4 2024 reveals that only 31% have
implemented any IoT connectivity in production lines, compared to 67% of large enterprises.

The skills gap is the primary barrier cited by 58% of respondents. Qualified automation
engineers and data scientists are concentrated in the Brussels, Ghent, and Antwerp
metropolitan areas, leaving rural manufacturing clusters underserved. Hourly rates for
contract automation specialists have risen 34% since 2022 in the Flemish market.

Investment appetite exists but is constrained by payback period uncertainty. SMEs report
median ROI evaluation horizon of 18 months for digital investments, while most IoT and
ERP modernisation projects deliver measurable returns in 24-36 months. This gap is the
financial barrier that digital transformation service providers must bridge.

The VLAIO Digital Transformation subsidy programme (60% cost coverage up to €25,000 per
project) has uptake of only 23% among eligible companies, suggesting awareness and
application complexity are secondary barriers. Simplifying the subsidy application process
and increasing awareness via sector federations (Agoria, Fedustria) could accelerate
adoption by an estimated 40,000 SMEs over 36 months.

Government initiatives like the Digital Innovation Hubs (DIHs) network provide testing
facilities and coaching, but only 12% of Flemish manufacturing SMEs have engaged with
a DIH in the past 12 months. Geographic accessibility and time-cost for SME owners
appear to be the primary friction points for DIH engagement.

Recommended interventions fall into three clusters: reduce friction in subsidy access,
expand regional coaching capacity through sector federation partnerships, and create
industry-specific digital transformation playbooks that reduce uncertainty about payback
timelines. The last point is perhaps most critical — quantified case studies from
comparable Belgian SMEs would reduce the perceived risk that currently prevents 42% of
potential adopters from initiating digital transformation projects.

In conclusion, the Belgian manufacturing SME digital transformation market is ripe for
structured intervention. The combination of skills gap, payback uncertainty, and subsidy
underutilisation creates a serviceable gap for advisory and implementation services
targeting firms in the 10-250 employee range with established manufacturing operations.
""",
)


# ---------------------------------------------------------------------------
# Sample 5: Mixed quality — passes all checks (should PASS)
# ---------------------------------------------------------------------------

SAMPLE_5 = SynthesisSample(
    sample_id="mixed_quality",
    description="Borderline synthesis — meets all three checks minimally",
    brief_topic="Cloud cost optimisation strategies for scale-up SaaS companies",
    focus_areas=["cost_drivers", "optimisation_levers", "vendor_strategies"],
    expected_existing_verdict="pass",
    synthesis="""
# Cloud Cost Optimisation for SaaS Scale-Ups

## Context and Cost Drivers

SaaS companies at the Series B through IPO stage face cloud cost escalation that
frequently outpaces revenue growth. The primary cost drivers are compute (typically
40-60% of total cloud spend), data transfer and storage (20-30%), and managed services
like databases and message queues (15-25%). Understanding the composition of spend is
the prerequisite for any optimisation initiative.

The key insight from 2024-2025 benchmark data: companies that invest in cost observability
tooling (FinOps platforms) before Series C reduce cloud spend as a percentage of revenue
by an average of 18 percentage points over 24 months compared to those who defer. The
investment in tooling pays back in under 6 months at scale.

## Optimisation Levers

Reserved instances and savings plans are the highest-leverage immediate action for
workloads with predictable utilisation (>70% of core infrastructure). AWS Reserved
Instances and GCP Committed Use Discounts offer 30-60% savings versus on-demand rates
for 1-3 year commitments. The risk is over-commitment for fast-growing workloads — the
standard mitigation is committing 60-70% of baseline load and leaving the remainder on
spot or on-demand.

Right-sizing under-utilised instances is the second lever. Industry data shows that 30-40%
of cloud instances in typical SaaS environments run at under 20% average CPU utilisation.
Automated right-sizing via AWS Compute Optimiser or GCP Recommender captures this
without engineering investment.

Architectural changes — moving to serverless, containers, or spot-tolerant workloads —
offer larger long-term savings but require 3-6 months of engineering effort per
initiative. Prioritise these for workloads with bursty or unpredictable patterns.

## Vendor Negotiation Strategies

Cloud providers increasingly negotiate enterprise agreements (EAs) with Series B+ companies.
AWS Enterprise Discount Programme (EDP) and GCP Google Cloud Partner Programme provide
10-25% discounts on committed annual spend above $1M. Multi-cloud positioning (even if
you don't intend to execute) is a proven negotiation lever — documented competitor offers
improve EA terms by 8-12% on average according to procurement consultants.

The timing of negotiations matters: Q4 is when cloud provider sales teams have quota
pressure. Companies that initiate EA discussions in September-October consistently report
better terms than those who renew at contract anniversary dates outside Q4.
""",
)


ALL_SAMPLES: list[SynthesisSample] = [
    SAMPLE_1,
    SAMPLE_2,
    SAMPLE_3,
    SAMPLE_4,
    SAMPLE_5,
]
