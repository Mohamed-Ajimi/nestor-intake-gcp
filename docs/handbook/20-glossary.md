# 20 — Glossary

| | |
|---|---|
| **Audience** | Everyone |
| **Type** | Reference |
| **Source of truth** | The chapters that define each term; identifier families come from `.planning/` |
| **Last verified** | commit `c8b8583`, 2026-09-03 |

## 20.1 Product and domain terms

| Term | Meaning | Chapter |
|---|---|---|
| **Nestor Pulse** | The product: intake → verified research → delivered report. "Pulse" is the intake product slug; other product slugs (`sales`, `echo`, `edge`, `flux`) are disabled or placeholders | 01 |
| **Agenic** | The agency that owns and operates the product; its operators are the superadmins | 01 |
| **Intake** | One client engagement, from a blank form to a delivered report; a row in `nestor.intakes` with a status | 04 |
| **Space** | The tenant; an organisation; `space_id` is the sole isolation key | 04, 14 |
| **Superadmin / operator** | An Agenic user with cross-space access | 04 |
| **User / client user** | A member of exactly one space | 04 |
| **Membership** | The link between an Identity Platform user and a space, with role, status and locale | 04 |
| **Template** | The form definition: sections and fields, every label in three languages; the Pulse form is one canonical template served in memory | 06, 07 |
| **Answer** | One value per `(intake, field_key)` | 05 |
| **Skill** | One of the six pre-research AI functions (apply-intake-skill, context-pack, structure-answers, extract-insights, generate-embeddings, transcribe-audio) | 07 |
| **Skill run** | One execution of a skill: `running → succeeded / failed` | 07 |
| **AI review** | The operator's accept / edit / reject pass over the apply skill's output | 07, 12 |
| **Proposal** | An AI-suggested extra research question; `show_to_client` is the operator's choice to show it, `approved` is the client's choice to run it | 07, 12 |
| **Validation** | The client's confirmation of the refined questions; moves `reviewed → validated_by_client` | 04 |
| **Context pack** | The Dutch 11-section briefing generated from the intake; versioned; the input the engine receives verbatim | 07, 08 |
| **Decomposed** | The intake status that ends the pre-research flow: validated questions plus a context pack | 04 |
| **Brief** | The prose the engine receives: questions, `[DECISION]`, `[REPORT]`, a report hint, `[CONTEXT PACK]` | 08 |
| **Research run** | One engine execution on an intake; mirrored into `nestor.research_runs` | 04, 08 |
| **Attempt** | A fresh trigger of a research run; capped at 3 for failure recovery | 08 |
| **Re-run** | A deliberate new run of a completed intake with a steering note (Phase 24, planned) | 19 |
| **Steering note** | The operator's instruction to a re-run asking for something different (planned) | 17, 19 |
| **Bundle / raw output** | The zip an operator downloads after a verified run: `report.md`, scrubbed provider reports, `sources.json` | 08 |
| **Final report / deliverable** | The operator-authored PDF the client receives | 08 |
| **Deliver** | The explicit act that flips `in_research → delivered` and mails the client | 04, 08 |

## 20.2 Engine terms

| Term | Meaning | Chapter |
|---|---|---|
| **Tribunal** | The deep-research engine (`nestor_pulse_sdk`), absorbed in v1.1 | 09, 10 |
| **`tribunal-api` / `tribunal-worker`** | The engine's HTTP service (internal) and its always-on queue poller | 09 |
| **Seam** | The HTTP boundary between the intake backend and the engine; `tribunal_client.py` | 08 |
| **Tenant id** | The engine's name for the space id; header `X-Nestor-Tenant-Id`; GUC `app.tenant_id` | 09, 14 |
| **Stage** | One step of the pipeline (the `set_stage` keys); thirteen in the run feed | 10 |
| **Question workshop** | The pre-dispatch stage that turns client questions into sharpened, ranked sub-questions | 10 |
| **Orientation** | The workshop's first, web-grounded pass per client question, producing findings and brief conflicts | 10 |
| **Brief conflict** | "The brief assumes X, a source says Y", with quote and URL; the seed of a discovery question | 10 |
| **Candidate** | A generated sub-question; 12 per client question by default | 10 |
| **Ask / aspect** | One distinct thing a compound client question asks; every ask must be covered by at least one candidate | 10 |
| **Critique** | The KEEP / WEAK / KILL judgement on each candidate | 10 |
| **Tournament** | Swiss-paired pairwise matches judged by a model, scored with Elo; `wins` is the primary sort key | 10 |
| **Catch-up schedule** | A newcomer plays up to the field's median match count on entry | 10, 17 |
| **Evolve** | The generative step producing new candidates by COMBINE, EXTEND, INVERT, SPECIALISE, INVENT | 10 |
| **Meta-review** | One call per round summarising critique flaws and judge reasons into guidance for the next round | 10 |
| **Grounded admission** | The web-search test an invented angle must pass: its premise is real, evidenced by a fetched http(s) source | 10 |
| **Rejected register** | The within-run list of barred candidates (bar causes: KILL defect, WEAK twice, lookup failed) | 10 |
| **Exit criteria** | Coverage, quality, saturation; a floor of 4 rounds and a cap of 10 | 10 |
| **Winner** | A candidate selected for research: a floor of 5 per client question plus 2 cross-cutting, preferring KEEP | 10 |
| **Mandate bracket** | The client's questions and their sub-questions; coverage guaranteed | 10 |
| **Discovery bracket** | Evidence-anchored questions the client did not ask; ≤5 slots, per-parent cap 3, "no source, no slot" | 10 |
| **Rider** | A discovery question parented to a client question, carried inside that question's group at no extra cost | 10 |
| **Cross-cutting** | A question whose parents span two client questions, or a discovery question with parent `__discovery__` | 10 |
| **Scope guard** | The Python assertion that every client question is represented among winners (and among groups), with a repair ladder | 10 |
| **Group** | A set of winners dispatched together; default one per client question; optional LLM topic grouping ≤5 | 10 |
| **Angle / assignment** | One group sent to one provider; one paid deep-research call | 10 |
| **Stream / provider** | One of the three deep-research vendors (`gemini`, `openai`, `claude`); `own` is a removed fourth | 10, 11 |
| **Corroboration key** | The shared key (`w01`, `g1`, …) linking the same group's claims across providers | 10 |
| **Stakes** | `high`, `med`, `low`, derived from rank; drives verification depth | 10 |
| **Fact list** | The structured facts block every provider must end its report with (`FACTS_START` / `FACTS_END`) | 10 |
| **Distiller** | The fallback that extracts claims from prose when a provider returns no usable fact list | 10, 11 |
| **Claim** | One extracted statement with facet, sub-question, corroboration key, date, certainty, provenance | 05 |
| **Merge / canonical grouping** | Clustering same-fact claims across providers ("block then cluster") before the gates | 10 |
| **Gates** | Materiality (falsifiable and load-bearing) and error-likelihood (stable-fact skip); corroboration prioritisation | 10 |
| **Funnel** | The per-bucket counts every distilled claim lands in; 18 keys | 10, 12 |
| **Skeptic / group skeptic** | The adversarial verification session over a claim group, with web search and fetch tools | 10 |
| **Verdict** | `support`, `refute`, `insufficient`, `superseded` | 10 |
| **Survival rule** | A claim drops only on a majority of refutations with at least one independent-source refutation | 10, 18 |
| **Reconciliation** | The skeptic's settlement of contradictory variants, with a canonical value | 10 |
| **Coverage re-entry** | A second verification pass for high-stakes claims that were not covered | 10 |
| **Checked incidentally** | A verdict on a gate-dropped member of a selected group, filed under its own funnel line | 10 |
| **Synthesis** | Report planning and writing; anchors → deterministic `[n]` numbers | 10 |
| **Anchor** | An opaque `[[c:xxxxxxxx]]` token the writer copies per fact, rewritten by Python to `[n]` | 09, 10 |
| **Citation numbering** | Deterministic `[n]` assigned from the claim–source tables in a pinned order; never renumbered | 09 |
| **Snapshot** | The stored source text (or, on the skeptic path, the URL) shown in the citation panel | 09 |
| **Redirect resolution** | HEAD-resolving Gemini grounding redirects to publisher URLs at ingest | 09 |
| **Verification report** | The superadmin-only post-run report: funnel, verdicts, superseded, reconciled, unverified, citations, cost | 10, 12 |
| **Run event / feed** | Append-only rows (`seq`, `stage`, `kind`, `text`, `meta`) rendered as the run page's activity feed; twelve kinds | 09, 12 |
| **Audit row / audit blob** | The hash-chained metadata row and the full-body GCS object written for every LLM call | 09, 14 |
| **Hash chain / `verify_chain`** | `sha256(prev_hash ‖ canonical_json(frozen payload))` per row; the verifier returns `{ok, broken_at}` | 09, 14 |
| **Cost pending** | The run flag set when a call could not be priced (no usage metadata or no unit price) | 09, 11 |
| **Budget governor** | The per-run USD ceiling (`DEFAULT_MAX_BUDGET_USD = 25`) that `NESTOR_TRIBUNAL_UNCAPPED=1` keeps inert | 10, 17 |
| **Breaker** | The per-provider circuit breaker that stops dispatch after consecutive identical hard failures | 10 |
| **Park / resume** | Stopping a run with its state preserved when no honest deliverable is possible; resumed by a superadmin click | 04, 10 |
| **Degraded (`completed_degraded`)** | Finished with a named shortfall | 04 |
| **Yield** | Per-assignment and per-round instrumentation (`assignment_yield`, `workshop_round_yield`) | 05, 10 |

## 20.3 Platform terms

| Term | Meaning |
|---|---|
| **Cloud Run** | Google's container platform; the four services and two Jobs run here |
| **Cloud SQL** | The managed Postgres 16 instance (`nestor-pg`) with pgvector |
| **Identity Platform (IdP)** | Google's identity service (Firebase Auth); email + password sign-in, custom claims |
| **Custom claims** | `role` and `space_id` written into the ID token server-side |
| **GUC** | A Postgres session setting (`app.current_space_id`, `app.tenant_id`) read by RLS policies |
| **RLS** | Row-level security; `FORCE` makes it bind the table owner too |
| **`app_superadmin`** | The intake database's bypass login role, recognised by name in a policy |
| **`app_user` / `worker_user`** | The engine's tenant-scoped API role and cross-tenant worker role |
| **Cloud SQL connector** | The Python library that tunnels to Cloud SQL over the Admin API with IAM authentication |
| **Signed URL** | A time-limited GCS download link minted through IAM `signBlob` |
| **Secret Manager** | Where every API key and the one database password live |
| **SSE** | Server-sent events; the one-way stream the browser reads for skill and research progress |
| **Cloud Build** | Google's build service; every image and every test gate runs here |
| **Alembic** | The migration tool; two independent lines (`nestor` 0001–0013, `tribunal` 0001–0018) |
| **Terraform** | The infrastructure-as-code description that was never applied; the runbook is the truth |
| **Digest** | The immutable image hash a deploy is proven by; tags are mutable |

## 20.4 Identifier families

| Prefix | Meaning | Where defined |
|---|---|---|
| `P-NN`, `M-NN` | Founding v1.0 decisions; v1.1 milestone decisions (handbook numbering) | 17 |
| `INFRA-`, `API-`, `AUTH-`, `TENANT-`, `USER-`, `DOC-`, `INTAKE-`, `AI-`, `NOTIF-`, `I18N-`, `QA-` | v1.0 requirement ids | `.planning/milestones/v1.0-REQUIREMENTS.md` |
| `ENGINE-`, `SEAM-`, `RUN-`, `REPORT-`, `CHAT-`, `CLOSE-`, `FUT-` | v1.1 requirement ids | `.planning/REQUIREMENTS.md` |
| `D-NN` (in a phase) | A phase-local decision from that phase's `CONTEXT.md` | 17 |
| `D1…D15`, `R1…R7`, `C1` | The 2026-07-24 engine brainstorm decisions | 17 § 17.9 |
| `S-`, `B-`, `V-`, `F-` | Phase 15 scope, build order, validation, failure policy | 17 § 17.10 |
| `G-01…G-14` | Phase 15.1 gate decisions | 17 § 17.11 |
| `D-R1…D-R11` | The 2026-07-29 redesign spec decisions | 17 § 17.14 |
| `D-W3-`, `D-W4-`, `D-W5-` | Waves 3, 4, 5 operator rulings | 17 § 17.15 |
| `D-22-1…5` | Phase 22 decisions | 17 § 17.16 |
| `D-RR-1…3a` | Re-run feature rulings | 17 § 17.17 |
| `D-V01-N` | Findings of the V-01 run analysis | `docs/tribunal-run-reports/run-20260728-7dcf51d5-V01-FINDINGS.md` |
| `D-A…D-M` | Findings of the aborted run `d6bb3aae` | `.planning/phases/15.2-*/15.2-V01-ABORTED-FINDINGS.md` |
| `CR-NN`, `WR-NN` | Code-review criticals and warnings for a phase | that phase's `REVIEW.md` |
| `DEF-NN-NN` | Deferred items from a phase | that phase's `deferred-items.md` |
| `UAT-22-F1…F4` | Findings from the Phase 22 operator UAT | `.planning/phases/22-*/22-UAT.md` |
| `T-NN-NN` | Task-level notes in plans | plan files |
| `V-01`, `V-02`, `V-03` | The redesign's validation run, acceptance checklist, and old-path removal | 17 § 17.10 |
| `Q-PRE-0…4` | The pre-flight gates before the measuring run | `.planning/phases/15.8-*/15.8-UAT.md` |
| `260903-fbt` etc. | Quick-task ids (`YYMMDD-xxx`) | `.planning/quick/` |
| `20260901-134253` etc. | Deploy tags (`YYYYMMDD-HHMMSS`, one shared SHA per deploy) | 13 |
| `nestor-api-00047-ghp` etc. | Cloud Run revision names | 13 |

## 20.5 Status and stage vocabularies

**Intake status:** `draft`, `submitted`, `reviewed`, `validated_by_client`, `decomposed`,
`in_research`, `delivered`, `archived`.

**Frontend phase:** `awaiting_client_submission`, `awaiting_skill_run`, `awaiting_review`,
`awaiting_validation_send`, `awaiting_client_validation`, `awaiting_context_pack`,
`awaiting_research_start`, `in_research`, `awaiting_report_upload`, `awaiting_results_send`,
`completed`, `archived`.

**Work-phase presentation:** `running`, `finished`, `stopped`, `paused`, `unknown`.

**Engine run status:** `queued`, `running`, `completed`, `completed_degraded`, `parked`, `failed`,
`cancelled`, `needs_input`, `needs_report_spec`.

**Skill-run status:** `queued`, `running`, `succeeded`, `failed`.

**Run-event kinds (12):** `divider`, `summary`, `dispatch`, `agent_run`, `agent_done`,
`agent_retry`, `agent_fail`, `thinking`, `tool`, `search`, `plan`, `streams`.

**Critique vocabulary:** `KEEP`, `WEAK`, `KILL`. **Verdicts:** `support`, `refute`,
`insufficient`, `superseded`. **Certainty:** `certain`, `single`. **Source quality:** `official`,
`press`, `other` (tiers 1, 2, 3).

**Funnel keys (18):** gate stage `distilled`, `kept`, `dropped`, `not_falsifiable`,
`not_load_bearing`, `both`, `selected_verify`, `skipped_stable`, `gate_errors`; pipeline stage
`checked`, `should_have_been_checked`, `verify_sessions`, `checked_incidentally`,
`checked_incidentally_not_falsifiable`, `checked_incidentally_not_load_bearing`,
`checked_incidentally_both`, `checked_incidentally_stable`, `unresolved_anchors`.

**Pipeline stages in the feed (13):** `intake`, `workshop`, `research_division`, `deep_research`,
`own_research`, `distill`, `merge`, `gate`, `verify`, `adjudicate`, `coverage`, `conflict`,
`synthesize` (chapter 10 gives the executed order and what each does).
