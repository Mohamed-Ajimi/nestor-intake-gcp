# Workshop forensics — run `d6bb3aae` (2026-07-27, aborted)

Reconstructed from the audit bucket (`gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/d6bb3aae-…`),
253 audited calls, 50 of them pre-dispatch. All Dutch source text translated to English below;
originals are in the audit blobs.

> **Headline: the workshop worked mechanically and failed completely on substance.**
> Every stage did what it was built to do. But it was fed the client's entire context pack — page
> counts, NDA status, contact names, tone-of-voice notes — as if those were research questions, and
> it ranked them against a decision statement that read `Deep research for moetest.`
> **Of the 11 paid deep-research angles dispatched, 3 were legitimate external research.**
> The client's actual research questions — dynamic pricing, competitor coffee strategies, the
> supermarket-format threat — **were never dispatched at all.**

## 1. The funnel, with real numbers

| Stage | Count | Source |
|---|---|---|
| Client "questions" fed to the workshop | **32** | 31 deepen calls + 1 duplicate |
| Candidate sub-questions generated | **186** | deepen responses (6 per parent) |
| Trimmed by the 60-cap | −126 → **60** | log 08:09:49 |
| After near-duplicate clustering | **37** | log |
| After critique (4 killed) | **33** | log |
| Tournament winners | **30** | log |
| **Dispatched as paid research** | **15** (11 distinct recovered) | audit |

Reconciles exactly: 186 generated − 126 trimmed = 60.

## 2. Root cause — two input defects, compounding

### 2a. The context pack was fed in as "client-validated questions"

Of the 32 parents the workshop deepened, only **11** are externally researchable market questions.
The rest are the intake's own administrative fields:

| Class | Count | Examples |
|---|---|---|
| **A — real external research** | 11 | dynamic pricing adoption; competitor coffee strategies; supermarket-format threat; customer loyalty; regulatory BeNeLux vs Germany |
| **B — internal client facts** (only the client can answer) | 11 | "Decision-maker: MOE, CEO"; "Primary client contact: MEEMZ (email)"; "CAPEX envelope: how much budget"; "Franchisees: what do they consider feasible?" |
| **C — report/scope metadata** (not questions at all) | 10 | **"Output size (hard constraint): Standard (15–25 pages)"**; "NDA status: intake says 'dont know'"; "How the client talks: businesslike, little jargon"; "In scope / Out of scope"; "By when: June 2026" |

The engine generated six research sub-questions for **"Output size: Standard (15–25 pages)"**. That
is the workshop faithfully executing on garbage input.

### 2b. The decision statement was null

Log, 08:09:49:

> `the workshop returned no research prompt — using the brief's opening line so the gates keep a
> decision to judge materiality against`

The fallback opening line was:

> **`Deep research for moetest.`**

Every tournament prompt therefore contained:

```
The client's decision this research has to serve:
Deep research for moetest.
```

The tournament's entire job is ranking questions by *materiality to the decision*. With no decision,
ranking is arbitrary — which is exactly why metadata out-ranked the client's real questions.

### 2c. A corrupted duplicate parent

`P15` and `P16` are the same NDA field, but one reads `"dont know"` and the other `"dont oko"`.
The corrupted variant produced its own sub-question. Text is being mangled somewhere upstream.

## 3. What was actually dispatched — the money spent

11 distinct angles recovered from the deep-research request payloads. Class per §2a.

| # | Provider | Parent (translated) | Sub-question dispatched (translated) | Class |
|---|---|---|---|---|
| 1 | OpenAI | "By whom: MOE (CEO) + senior leadership (names/roles still to be filled in)" | Which senior leadership roles (CFO, CCO, Head of Ops, Head of Strategy) must attend the 'Germany 2027 vs NL' decision? | **B** |
| 2 | Gemini | "Alternatives on the table: A) Germany 2027 / B) deepen NL / C) both / D) status quo" | (echoes the parent verbatim) | **B** |
| 3 | Gemini | "CAPEX envelope: how much budget 2026-27 for shop refit, IT, new sites?" | What total CAPEX has LUKOIL reserved for 2026-27, split by shop refit, IT/dynamic pricing and new sites? | **B** |
| 4 | Gemini | "By when: June 2026 — so 2027 planning can start" | Which concrete decision milestones must be completed by June 2026? | **C** |
| 5 | OpenAI | "What must be decided: launch Germany 2027, or consolidate NL first" | Realistic minimum investment and time-to-break-even for a 2027 Germany launch vs margin upside of deepening NL | **B** |
| 6 | Gemini | "Primary client contact: MEEMZ (mohamed.ajimi@azentic.be) — role still to be filled in" | **What is the exact job title and organisational role of Mohamed Ajimi (MEEMZ) within or towards LUKOIL — internal strategy lead, external consultant, or other?** | **B + PII** |
| 7 | OpenAI | "If Germany fails: exit strategy, downside, reputational damage in BeNeLux?" | Which concrete exit scenarios (full withdrawal, partial divestment, franchising, sale-and-leaseback) are realistically executable? | **A** |
| 8 | OpenAI | "Cost of changing nothing: if LUKOIL doesn't differentiate and competitors do" | In what concrete steps do fuel volume and customer frequency erode at a mid-size fuel retailer offering no loyalty or differentiation response? | **A** |
| 9 | OpenAI | "NDA status: intake says 'dont know' on sensitivities" | Which categories of customer data, pricing information or strategic data typically fall under a confidentiality classification? | **C** |
| 10 | Gemini | "Decision-maker: MOE, CEO + senior leadership. Whether MEEMZ decides or liaises is unclear." | Who inside LUKOIL actually decides the strategic direction — MOE alone, the CEO with senior leadership, or a higher body? | **B** |
| 11 | Gemini | "Regulatory: BeNeLux vs German differences in opening hours, price transparency, convenience regulation" | Exact statutory opening-hours rules for filling stations and attached convenience shops in NL, BE, LU and DE | **A** |

**3 of 11 are legitimate external research** (#7, #8, #11).

### 3a. A personal email address was sent to third-party research providers

Angle #6 dispatched a paid Google deep-research assignment to establish the job title of a **named
individual**, carrying `mohamed.ajimi@azentic.be` in the query. That is personal data leaving the
platform to an external processor as a research task, with no purpose that serves the client's
decision. Treat as a data-protection incident, not a quality bug.

## 4. What was NOT dispatched

The client's flagship research questions never reached a provider:

- **"Which fuel retailers in Europe apply dynamic pricing today to fuel and/or shop products, how is
  it operationalised…"** — the intake's headline question.
- **"How have the coffee strategies of the main BeNeLux petrol retailers evolved, what impact on
  coffee sales, traffic and brand perception over the last 3 years…"**
- **"Now that the competitive advantage of a supermarket format at filling stations is eroding due to
  wider retail opening hours, how are fuel retailers elsewhere responding strategically…"**
- Customer-loyalty migration risk under premiumisation; competitor strategies of Shell/TotalEnergies/BP.

## 5. Tournament outcome — verdicts survive, mapping does not

8 tournament calls ran on `gemini-2.5-flash`, pairwise ("for each pair, say which matters more").
The raw verdicts are intact:

```
call 1:  0|A 1|B 2|A 3|A 4|A 5|B 6|B 7|A 8|A 9|A
call 2: 10|A 11|A 12|A 13|A 14|B 15|B
call 3: 10|A 11|B 12|A 13|A 14|A 15|A
call 4: 10|A 11|A 12|B 13|A 14|B 15|A
call 5: 10|A 11|B 12|A 13|A 14|B 15|B
call 6:  0|B 1|A 2|B 3|A 4|B 5|B 6|A 7|A 8|B 9|B
call 7:  0|B 1|A 2|B 3|B 4|B 5|A 6|B 7|A 8|A 9|A
call 8:  0|A 1|B 2|A 3|B 4|A 5|A 6|A 7|A 8|A 9|B
```

**These cannot be mapped back to questions.** See §6.

## 6. NOT RECOVERABLE — the audit truncates prompts at 2000 characters

Every `gemini-2.5-flash` request in the audit is stored at **exactly 2000 chars, cut mid-sentence**.
The Anthropic requests (5.5k) and responses (up to 99k) are complete; only these are clipped.

Consequently the following are **permanently unreconstructable** for this run:

- the exact **60** that survived the cap,
- the **37** after clustering,
- the **33** that entered the tournament,
- therefore **which question each A/B verdict refers to**, and the **30 winners**.

This matters beyond convenience. The audit trail is the EU AI Act Art. 12 record. The hash chain
proves integrity of *what was stored*, but a truncated prompt means the record cannot show what the
model was actually asked. **Integrity is intact; completeness is not.**

## 7. Defects this adds

- **D-G — the workshop's input is the whole context pack, not the client's questions.** Report-format
  and admin fields are deepened, ranked and dispatched as paid research. Highest-value fix in the
  phase: it wastes most of the research budget and buries the real questions.
- **D-H — the decision statement fell back to `Deep research for moetest.`** The workshop returned no
  research prompt; the tournament then ranked materiality against nothing.
- **D-I — PII dispatched to third-party providers** (§3a). Data-protection, not quality.
- **D-J — audit truncates prompts at 2000 chars** (§6), defeating forensic reconstruction of the
  legally-mandated record.
- **D-K — text corruption upstream** (`"dont know"` → `"dont oko"`, §2c).

Ordering note: **D-G and D-H outrank D-A/D-B from `15.2-V01-ABORTED-FINDINGS.md`.** Fixing the two
dead provider streams would only have bought more expensive answers to the wrong questions.
