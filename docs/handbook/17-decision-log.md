# 17 — Decision log (ADR register)

| | |
|---|---|
| **Audience** | Engineers, planners, auditors — anyone asking "why is it like this?" |
| **Type** | Reference (architecture decision records) |
| **Source of truth** | `.planning/PROJECT.md` (Key Decisions), `.planning/RESEARCH-ENGINE-DECISIONS.md`, `.planning/ENGINE-REDESIGN-SPEC.md`, `.planning/STAKEHOLDER-NOTES.md`, every `.planning/phases/*/*-CONTEXT.md` decision block, `.planning/STATE.md` (Decisions, Quick Tasks) |
| **Last verified** | commit `c8b8583`, 2026-09-03 |

This chapter is the canonical register of every decision that shaped the system. Module chapters
link here instead of restating rationale. Entries keep the project's own identifiers so a reader can
find the original ruling in the planning record.

**How to read an entry.** Each row or block gives the identifier, the date it was taken, its status,
the context that forced a choice, the choice, and the consequence. Where the operator (the project's
product owner and superadmin) ruled personally, the entry says so. **Superseded decisions are kept
and marked** — this project's convention is to mark rather than delete, because a reader who finds
only the current rule cannot tell why the earlier one was wrong.

**Identifier families.** `D-NN` is a phase-local decision (the phase is named in the heading);
`D1…D15`, `R1…R7`, `C1` are the 2026-07-24 engine brainstorm; `D-R1…D-R11` are the 2026-07-29
redesign spec; `G-01…G-14` are Phase 15.1's gate decisions; `D-W3-*`, `D-W4-*`, `D-W5-*` are the
redesign waves 3/4/5; `D-22-*` is Phase 22; `D-RR-*` is the re-run feature; `S/B/V/F-*` are Phase 15's
scope, build-order, validation and failure-policy decisions.

---

## 17.1 The founding decisions (v1.0 project scope, 2026-06-18)

Context for all of them: the original application was a third-party Lovable build on Supabase whose
security model was broken in five documented ways (see chapter 14). GCP was mandated as the target
platform. There was no test coverage at all.

| id | Decision | Rationale | Consequence / status |
|---|---|---|---|
| P-01 | **Big-bang cutover; Supabase retired once GCP is validated end-to-end** | A long dual-run would keep the leaky anon-key path alive and force two systems to be maintained | Executed 2026-07-20. Amended by D-08 (Phase 12): retirement = independence only, the legacy project is never touched |
| P-02 | **Start on an empty Cloud SQL database — no data migration** | No production data worth migrating; a clean slate avoids porting legacy or broken rows | Held. Also applied to the Tribunal re-home (its dev data was not migrated) |
| P-03 | **Roles limited to `superadmin` and `user`** | Keeps auth simple; `client-admin` can be added later (claim designed to extend) | Held; `client-admin` is FUT-03 |
| P-04 | **Login required for everyone; never-expiring bearer links removed; email becomes notification-only** | The token links were the #3 flaw: no expiry, no revocation, no audit | Held. Every mail carries no token; links point at authenticated routes |
| P-05 | **Per-client spaces, isolation enforced at the API layer, RLS as defence-in-depth** | The #1 flaw was `USING (true)` RLS; relying on DB RLS alone was the failure | Held. Repository layer + GUC + CI denial suite + `USING(true)` CI guard |
| P-06 | **Full pre-research AI feature parity in v1.0** | An end-to-end cutover needs every function the old app used | Delivered in Phase 7 (seven ports) |
| P-07 | **Frontend moves to GCP (Cloud Run SSR container)** | One platform to operate | Delivered in Phase 12 with the D-11 bundle guard |
| P-08 | **Multi-language UI NL/FR/EN from the start** | Broader client reach; cheaper now than retrofitted | Delivered in Phase 11 |
| P-09 | **`findings` / `deliverables` tables created empty** | Preserve the Tribunal handoff contract in the schema without populating it | Held; `deliverables` gained a real writer in Phase 18 |
| P-10 | **Tally / Jotform external-form ingestion dropped** | Anonymous forms conflict with the login-only model; Jotform already returned 410 | Held |
| P-11 | **Isolation proven by tests before any feature endpoint ships (Phase 4 gate)** | The bug class must be structurally unable to recur | Held; the retrospective credits this ordering with "the broken-RLS bug class never recurred" |
| P-12 | **Tests are phase-zero work, not cleanup** | Zero coverage inherited; the safety net must be built alongside the migration | Held (QA-01/02/03) |
| P-13 | **Scope ceiling at `decomposed`; `run-research` must be unreachable from the new credentials** | Deep research was a separate track with its own engine | Held; enforced by `backend/scripts/ci_no_run_research.sh` and tests. Superseded in *scope* by v1.1, which extends the flow through Tribunal — but the legacy `run-research` is still barred |

## 17.2 v1.0 phase decisions (2026-06-18 → 2026-07-20)

| Phase | id | Decision | Why |
|---|---|---|---|
| 1 | 01-01 | RLS test harness uses sync `pg8000` so the test engine and Alembic `env.py` share one driver | One driver, one connection semantics for tests and migrations |
| 1 | 01-02 | **No `public.clients` table: organisation = space; `space_id` (= org id) is the sole isolation key** | Removes a second identity that the legacy schema had split across two schemas |
| 1 | 01-03 | **Superadmin bypass via an `app_superadmin` login role and a `current_user = 'app_superadmin'` policy clause** OR'd with isolation | Cloud SQL has no `BYPASSRLS`; the app role stays space-scoped |
| 1 | 01-04 | Only in-scope (≤ `decomposed`) triggers ported; the three post-decomposed Tribunal triggers are absent as objects and as names | INTAKE-05 scope ceiling |
| 2 | 02 | Engine factory mode-switch where an explicit DSN always wins; bounded shared pool on both modes; split `/healthz` and `/readyz` | Local/test parity and Cloud SQL connection-count safety |
| 2 | 02 | One multi-stage `uv` Dockerfile serves both the service and the migration Job; no baked secrets; migrations run as a discrete Job, never at app startup | One image, one truth; no startup races across instances |
| 2 | 02 | IAM database authentication, no stored DB credential; runtime SA GRANTed direct privileges by migration 0005 (RLS still applies) | D-03/D-09: no password anywhere |
| 3 | 03 | Identity Platform ID tokens verified server-side on every request; `role` and `space_id` as **server-set** custom claims; never trusted from the browser | AUTH-02/03 |
| 4 | 04-01 | A CI grep guard bans raw DB access outside `app/db/` | Tenant scoping cannot be bypassed by a new endpoint |
| 4 | 04-02 | `TenantRepository` derives `space_id` from the verified token only; the RLS GUC is set on checkout and reset on check-in | Pooled connections never leak tenant context |
| 5 | 05 | JIT provisioning on first login; deactivate = Identity Platform disable + refresh-token revoke + server re-check; root `audit_log` for security events | AUTH-04, QA-04 |
| 6 | 06 | All frontend data access behind `lib/api/*`; batched save-as-you-go; characterisation tests over `derivePhase` | The 34-file Supabase coupling was the migration's main risk |
| 7 | 07 D-05 | **DB session released before every LLM/Whisper call and reopened to persist** (`run_with_session_release`) | A 90–120 s call must never hold a pooled connection |
| 7 | 07 D-06 | Model ids are configuration, not literals scattered in code | Swappable without a code hunt |
| 8 | 08 | Skill-run progress via **DB-backed SSE**, no in-memory state; Cloud Run request timeout 900 s | Any instance can serve a reconnecting client; replaces Supabase Realtime |
| 9 | 09 | GCS V4 signed URLs minted through IAM `signBlob` (no SA JSON key anywhere), TTL ≤ 15 min, server-authored keys, objects namespaced by space | DOC-01/02 and the no-key CI guard |
| 10 | 10 | Notification-only mail; recipients resolved server-side from space membership (no free addresses); NL/FR/EN templates | NOTIF-01/02, and no way to mail a token to a stranger |
| 11 | 11 | `react-i18next`; a CI Dutch-string guard; per-user / per-space default locale | I18N-01/02 |
| 12 | **D-08** | **Retirement = independence only.** Zero Supabase env vars, calls or keys in the deployed system; the legacy project is never paused or deleted | Operator ruling 2026-07-20; irreversible actions on the legacy system were judged unnecessary risk |
| 12 | **D-11** | **A build-time bundle guard fails the frontend image if a Supabase signature ships** | Independence must be proven by construction, not asserted |
| 12 | close | **"PARITY ACCEPTED WITH DEFERRALS"** — 21 UAT items and 9 `human_needed` verifications deferred to post-Tribunal, ledgered verbatim | Operator decision 2026-07-20; the gate was closed honestly rather than falsely green |

## 17.3 v1.1 milestone decisions (scoped 2026-07-20)

| id | Decision | Rationale | Status |
|---|---|---|---|
| M-01 | **Redeploy the Tribunal engine into the intake GCP project** (two Cloud Run services) | One project to operate; avoids cross-project IAM and DB sprawl | Done (Phase 13) |
| M-02 | **Retire the Tribunal standalone app** (own logins, orgs, screens) | One login, one UI; intake auth and spaces govern research runs | Done (Phase 14) |
| M-03 | **Two-schema topology**: Tribunal keeps its own `tribunal` schema, its own Alembic line with a separate version table, its own GUC and RLS; the intake backend is the sole HTTP seam — no shared DB session | Both codebases had Alembic revisions `0001–0010` with identical ids, GUC names differed (`app.current_space_id` vs `app.tenant_id`), and the audit hash chain is frozen | Done; the research summary's Pitfalls 1/2 |
| M-04 | **Human-in-the-loop report**: raw engine output is superadmin-only; the client receives only a hand-crafted PDF; run `completed` does NOT auto-deliver | The generated report is an operator's working material, not a client deliverable | Done (Phases 17, 18) |
| M-05 | **Voyage `voyage-3-large` (1024-dim) for Q&A chat**, dedicated `Vector(1024)` table, never mixed with the OpenAI 1536 column | Fidelity to the legacy `ask-research` behaviour; accepted a new vendor | Pending (Phase 19 not started) |
| M-06 | **Audit-chain verification (`verify_chain`) pulled early into Phase 13** | EU AI Act Art. 12 enforcement 2026-08-02; a broken chain after the move must be caught before dependent work | Done; green on every deploy since |
| M-07 | **Per-run audit-chain advisory lock in Phase 13** | The chain was single-worker-safe only; multi-client concurrency needed it first | Done (ENGINE-08, proven with ≥2 concurrent runs) |
| M-08 | Legacy `run-research.ts` (SerpAPI/SearchAPI/Apify) is **not ported** | Research verdict: fully superseded by Tribunal; only trivial edge-case losses | Held |
| M-09 | No Cloud Run Jobs re-architecture for runs | The existing queue + always-on worker already solves request timeouts | Held |
| M-10 | Frontier ideas: adopt a research-plan critique (A2) and consider a draft tournament (A1); **decline** hypothesis-evolution loops, diversity clustering, self-play | Frontier comparison verdict 2026-07-20 | **Partly reversed** on 2026-07-24/29: the critique was absorbed into the question workshop (S-02); the draft tournament was dropped (S-03); a bounded evolution loop *was* adopted at question level (D-R6/D-R10) once the discovery bracket gave it something real to rank |

## 17.4 Phase 13 — Tribunal re-home (decisions 2026-07-20)

| id | Decision | Consequence |
|---|---|---|
| D-01 | `nestor_pulse_sdk` is **copied** into this repo at `tribunal/`; the old Nestor repo becomes a frozen reference | All Tribunal work happens here from Phase 13 onward |
| D-02 | The old standalone deployment on `project-cb01b861` is torn down after the proof run | Deliberately departs from D-08's "leave legacy untouched" — chosen explicitly. *Note: the project id turned out to be the same GCP project as "Nestor Pulse"; teardown meant resources only* |
| D-03 | v1.0-style deploys: build by construction, operator-run live sessions, every step in the runbook | Same account (`tools@dotto.be`) and project as v1.0 |
| D-04 | **Always-on worker accepted** (`min-instances=1`, no CPU throttling, ~$5–10/month idle) | Runs start within seconds of being queued |
| D-05 | Proof run uses a known benchmark brief (LUKOIL family) | Isolates deployment issues from research-quality issues |
| D-06 | All three providers enabled from day one; the Gemini key reused from the old project | Full ≥2-of-3 degradation headroom |
| **D-07** | **`NESTOR_TRIBUNAL_UNCAPPED=1` stays on** for proof runs ("uncap for now") | The $25 governor has **never fired**. Re-confirmed by the operator on 2026-09-01 ("leave it uncapped"). The question caps became the only spend control |
| D-08 | Production sizing target 5+ concurrent runs; proof test ≥2 | Lock design validated under the target |
| D-09 | Audit-evidence bucket retention mirrors the old deployment (7 years) | No new legal analysis |
| D-10 | Meeting the Art. 12 date is best-effort; the `verify_chain` green gate is mandatory regardless | Gate held on every deploy |

## 17.5 Phase 14 — auth retirement and the seam (2026-07-20)

| id | Decision | Consequence |
|---|---|---|
| D-01 | Retirement applies only to the in-repo copy; the original app stays intact | Mirrors independence-only |
| D-02 | Hard-delete the retired surfaces (orgs API, account, web UI, `identity_platform.py`, `firebase-admin`) | Git history keeps them recoverable |
| D-03 | Dev/eval surfaces (demo router, compare endpoints, eval critique) removed in the same sweep | The deployed API exposes only what the intake backend calls |
| **D-04** | **Defence in depth, not IAM-only**: Cloud Run IAM restricts invocation to the intake runtime SA **and** `InternalCallerProvider` verifies the Google-signed OIDC token (audience = service URL, caller = expected SA) before accepting the tenant id | A mis-set IAM binding cannot silently open tenants |
| D-04b | Tribunal gets its own least-privilege service account; the invoker binding becomes meaningful only when caller SA ≠ callee SA | Closed live 2026-07-20 (WR-03) |
| **D-05** | The intake backend forwards the acting superadmin's id and email on every seam call; the provider maps them into the **existing** `AuthClaims` fields | The legally load-bearing audit chain attributes each run to a real human **without** adding a payload field (which would break the hash chain) |
| D-06 | Minimal client in Phase 14 (`ensure_org`/`ensure_project`, OIDC minting); run methods wait for Phase 16 | Avoids re-work against the final stage shape |
| D-07 | One full run through the seam as live proof, plus three negative proofs | Run `b188a83e` completed, chain OK, $1.60; absorbed Phase 13's queue-path proof |
| D-08 | Each layer tested in its native harness: Tribunal RLS in the asyncpg suite, seam denial in the backend pg8000 suite | No driver mixing |

## 17.6 Phase 16 — trigger and progress bridge (2026-07-21)

| id | Decision | Consequence |
|---|---|---|
| **D-01** | **`needs_input` never fires for seam runs** — the validated context pack *is* the answered brief; the engine enters at question delegation | Zero-touch runs; the clarification gate is obsolete on this path |
| D-01b | The report spec is auto-derived from intake answers, with a fixed fallback | `needs_report_spec` never fires |
| **D-02** | **UNCAPPED stays on** — the cap flip-on is explicitly deferred to before client-billed runs, Phase 20 at the latest; the stale-run reclaim window *is* calibrated here | See D-07 (Phase 13) |
| D-03 | A confirmation dialog precedes every trigger | Paid action needs a deliberate click |
| D-04 | Re-trigger on failure up to **3 attempts**; then a "needs investigation" state | The counter is for failure recovery (see D-RR-1) |
| D-05 | Multi-provider fallback is verified, not built | Existed in the engine already |
| D-06 | One active run per intake via the status machine (`decomposed` → `in_research` removes the button) | No extra locking UI |
| D-07 | A full progress panel with the stage list rendered **dynamically** from the stage trace | Phase 15's added stages cost nothing later |
| **D-08** | **The client sees no change at all during research** | Research is invisible to clients until delivery |
| D-09 | On completion the panel collapses into a summary card (the anchor for later download/lock affordances) | |
| D-10 / D-11 | Completion/failure mail goes to whoever triggered; short body + link, same template stack | |

## 17.7 Phase 17 — raw output and the audit-chain guard (2026-07-21)

| id | Decision | Consequence |
|---|---|---|
| D-01 | The bundle = report + scrubbed per-provider research + sources; **rejected claims excluded** | The download never exposes discredited content |
| D-02 / D-03 | Sources as the claim→source trail (`sources.json`); one zip of standalone files | `report.md` feeds the external Claude Design step |
| D-04 / D-05 | Materialised **once** at completion into the uploads bucket (not the audit bucket) | Immutable snapshot, independent of Tribunal availability |
| **D-06** | **A broken chain → complete-but-locked**: the run records as completed, the download is blocked | Nothing leaves the system on a broken chain; completed research is never thrown away |
| D-07 / D-08 | Locked state is UI-only (no mail variant); a re-verify button re-runs `verify_chain` | |
| D-09 | Download exists only for chain-verified completed runs | No partial content is exported |

## 17.8 Phase 18 — human report upload and delivery (2026-07-22)

| id | Decision | Consequence |
|---|---|---|
| **D-01** | Upload only **stages** the PDF; a separate **Deliver** act flips `in_research → delivered` and sends the mail | Matches the reserved phase states and the explicit-send mail pattern |
| D-02 / D-03 | Recipient picker in the Deliver dialog; the existing results template | |
| D-04 / D-05 / D-06 | Replace allowed after delivery (optional re-notify); **delivered is one-way** | Retraction is a manual intervention |
| D-07 / D-08 / D-09 | A dedicated client report route, download-only, two entry points | Laid out with the Phase 19 chat in mind |
| D-10 / D-11 | **PDF only**, one file per intake, enforced server-side | |

## 17.9 The engine brainstorm (2026-07-24) — D1–D15, R1–R7, C1

Context: the first green run (`4cbb5311`, 2026-07-22) completed "green" while its skeptic arm was
effectively off, 776 usage-cap errors were sprayed in 55 seconds, and the cost panel said ~€5 against
~$43–45 real. The operator held all further runs and brainstormed the redesign with the run's
forensic report and a comparison with Replit deep research and Google's co-scientist in hand.

| id | Decision | Rationale |
|---|---|---|
| **D1** | Keep multiple research providers | Their different coverage of the same question is a feature |
| **D2** | Build a **question workshop** before dispatch: orientation searches → many candidates → cluster → critique → **pairwise tournament** → evolve → final list | Co-scientist-style selection pressure on the questions the money is spent on |
| **D3** | The workshop **consumes** the context pack; it does not replace it | The client contract (answers, skills, validation, pack) stays as-is |
| **D4** | The workshop may **add depth, never change scope**; contradictions become "brief assumes X, world says Y" flags that travel into the report | No silent rewrites of client-validated questions |
| **D5** | Fully automatic — no operator pause before dispatch; chosen questions visible live | Keeps the no-pause rule |
| **D6** | Distribute deliberately: the most important sub-questions go to **all** providers | Agreement = corroboration, difference = verification input |
| **D7** | Tag each sub-question with the languages worth searching in | Providers instructed accordingly; report language stays single |
| **D8** | Every provider ends its report with a **structured facts section** (source, quality, certainty, couldn't-find list); a slimmed distiller is a per-provider safety net only | The facts list is the primary claim source; prose extraction is the fallback |
| **D9** | **Cross-provider merge**: cluster same facts; agreement lowers checking priority, single-provider raises it, contradiction goes to **one** shared skeptic session | Fixes the shipped Aral 16%-vs-21% class of contradiction |
| **D10** | Add a fourth stream: an own researcher fuelled by SerpAPI | Transparent and metered. *Superseded by D-R5 / D-W3-3 — dropped from the rotation after it failed 2 of 4 angles* |
| **D11** | Verification gates apply **after** the merge: materiality → stable-known-fact skip → corroboration priority → skeptics on ~100–150 checks instead of ~950 | Spend verification where it matters |
| **D12** | Live view at agent level with full drill-down, superadmin-only | Fulfils D5's visibility promise |
| **D13** | Numbered, graded, clickable citations; **numbering generated from the claim–source database, never by the writing model** | The model stripped 28 markers on run 4cbb5311 |
| **D14** | Keep the report skeleton; add "Disputed & changed" and "What we could not establish", both **fed from pipeline data** | The writing model presents, it does not invent |
| **D15** | The live view is a chronological **activity feed** (Replit-style), not a status checklist: agent cards, per-agent status, narration, work-block summaries, errors shown as recovery, frozen and clickable after the run | Professionalism signal; reliability becomes visible |
| **R1** | Retry only transient errors (429/5xx/timeouts) with exponential backoff + jitter, honouring retry-after; never retry hard errors (the usage-cap 400, auth) | The cap was retried 776× in one minute |
| **R2** | Circuit breaker per stage/provider on consecutive identical hard failures | Stop spraying |
| **R3** | Checkpoint after every completed step; resume from checkpoint, never from zero; idempotent side effects | Never pay twice |
| **R4** | Park, don't die, never fake-finish: a hard wall parks the run with state preserved | Resume rule settled by F-01: superadmin click only |
| **R5** | Retries are visible in the feed | Hidden errors destroy confidence |
| **R6** | Four honest terminal states: `completed`, `completed-degraded`, `parked`, `failed` | Silent-green ceases to exist |
| **R7** | Use provider background/continuation modes | A dropped connection cannot kill a 20-minute provider task |
| **C1** | **Count every cost class, no estimates ever**: all four Anthropic token classes, search/fetch fees, Gemini `usageMetadata`; unavailable fees show "pending" and are backfilled exact; totals are "final" only when nothing is pending; mismatches with invoices are bugs | The panel said €5; reality was $43–45 |

Also agreed the same day (STAKEHOLDER-NOTES): the verification-gate package (materiality gate,
error-likelihood gate, canonical grouping, superseded verdict, fail-loud) and the **requirement** of
a superadmin-only post-run verification report.

## 17.10 Phase 15 scope, build order, validation and failure policy (2026-07-24)

| id | Decision |
|---|---|
| S-01 | Phase 15 becomes the full redesign, split into 15 (surfaces), 15.1 (gates), 15.2 (engine core) |
| S-02 | ENGINE-05 (plan critique) is **absorbed** by the workshop — orientation + critique + tournament *is* the critique pass |
| S-03 | ENGINE-06 (draft tournament) is **dropped**; single synthesis + operator shaping stays; the tournament exists at question level only |
| B-01 / B-02 / B-03 | Surfaces first, gates second, core last; three phases not one; all before Phase 19 so the chat indexes the new engine's output from day one |
| **B-04** | Cross-provider clustering is **LLM-based**, no embedding machinery (~1,000 facts/run is within LLM-grouping scale) |
| V-01 | Validation = one live run compared against the **recorded** old-engine baseline (run 4cbb5311); no A/B double-run |
| V-02 | Acceptance = a hard checklist **plus** operator sign-off after reading the report next to the baseline |
| V-03 | On acceptance the old engine path is removed immediately, no fallback flag |
| **F-01** | Parked runs resume on **superadmin click only** — spend never restarts without a human |
| F-02 | The 3-attempt rule counts full restarts only; checkpoint resumes are free and unlimited |
| F-03 | Park/failure mail to the triggering superadmin, with a Resume link |

## 17.11 Phase 15.1 — verification gates G-01…G-14 (2026-07-24/25)

Summarised from the plan register; the gate package was proven by replaying the recorded
1,162-claim fixture and reproducing its keep/drop numbers.

| id | Decision |
|---|---|
| G-01 | A deterministic answer-key replay is the CI gate; a live classifier calibration exists but has no threshold (LLM judgement quality is never a CI gate) |
| G-02 | Gate stage inserted into the pipeline; the selector is gate-driven; corroboration ordering; a low-stakes depth tier |
| G-03 / G-04 | Canonical clustering: block-then-cluster replaces exact-key bucketing; the signature is frozen |
| G-06 / G-07 | `superseded` verdict: tool enum, skeptic prompt, normalising parse boundary; `superseded_note` stored (alembic 0012) |
| G-08 / G-09 / G-10 / G-14 | Report shaper with three buckets; `verification_degraded` stated in words; a degraded run never locks the superadmin out of its output; **the client never receives the generated report** — only the final report the superadmin submits |
| G-11 | Gate errors fail **toward more checking**; a usage-cap 400 is never retried |
| G-12 | `found_by` provenance recorded on claims; deduping merges rather than drops |
| G-13 | `RECORDED_FUNNEL_COUNTS` is the single source of the recorded numbers |
| gap closure | A production writer for `verification_verdict` (survivors linked by claim, dropped claims persisted with NULL); the caveat reaches synthesis via `contested_notes`; the `gate` stage is declared in the schema |

## 17.12 Phase 15.2 — engine core D-01…D-17 (2026-07-26)

| id | Decision | Why it matters |
|---|---|---|
| D-01 | One phase left open across the Anthropic cap-reset wall | No roadmap churn for a one-week wait |
| D-02 | Proof bar = a stubbed end-to-end run + contract tests; LLM judgement quality is not a CI gate | Same principle as G-01 |
| D-03 | The old path stays in-tree but unreferenced until sign-off; no feature flag, no dual run | Recovery is reverting one wiring change |
| D-04 | The 1,162-claim replay feeds the gates directly | Keeps proving the gates at zero cost |
| **D-05** | **The model marks opaque anchors; Python assigns the `[n]` numbers** | The model never chooses a number |
| D-06 | An unresolvable anchor is stripped, counted, and stated in words | Never ship a broken `[n]`; never lose silently |
| D-07 | The citation surface is the superadmin's working tool (G-14 governs over D13's client framing) | The client PDF is hand-crafted |
| D-08 | D14's two new sections are deterministic Python blocks the model never sees | Testable from fixtures; the model cannot omit items |
| D-09 | One shared status predicate: `completed_degraded` gets everything `completed` gets; `parked` gets inspection only | One place to audit |
| D-10 | Incidental verdicts are kept and filed under a `checked_incidentally` funnel line subtracted from bucket 2 | Every claim lands in exactly one bucket; paid checking is never discarded |
| D-11 | The dead coverage gate (WR-01) is fixed **and** re-entry is gated on the circuit breaker | The budget governor is not a backstop — it is inert |
| **D-12** | **`completed_degraded` means the output fell short, with every reason named**; recovered retries and `cost_pending` never degrade a run | Alarm fatigue on one side, silent-green on the other |
| D-13 | D8 fact metadata gets real columns (`certainty`, `found_by`, provider-stated quality, a couldn't-find table) — additive, chain-safe | Reconstructable after the run |
| D-14 | A provider returning no usable fact list falls back to full distillation, recorded per provider | Degrades one stream, not the run |
| **D-15** | Consequently the distiller's full-extraction mode **survives** the old-path removal | "Remove the old engine path" ≠ "delete `claim_distiller`" |
| D-16 | SerpAPI spend = recorded count × published per-search unit price, recorded with the run | Exact, not estimated |
| D-17 | **Park only when no honest deliverable is possible**; otherwise finish degraded | Park should mean "this genuinely needs you" |

Gap-closure decisions after the aborted first live run (`d6bb3aae`, 2026-07-27): heartbeat liveness
and a reclaim ceiling (D-E); **the workshop takes only the client-validated questions, the context
pack is context** (D-G/D-H); the OpenAI deep-research model id with a fail-loud config class
(D-A/D-B); PII scrub at the dispatch choke point (D-I); stage entry/exit logging with counts (D-F);
a `cancel_run` seam method and Stop button (D-D). D-C (a suspected stall) was withdrawn as a
misdiagnosis — the wait was a 35-minute provider poll.

## 17.13 Phase 15.3 — the run page and run events (2026-07-27)

| id | Decision |
|---|---|
| D-03 | Ships in the same deploy batch as the 15.2 gap fixes; engine events are built before the UI |
| D-05 | One connection, one terminal authority: the event cursor rides the existing SSE frame |
| **D-06** | **An event write must never be able to fail a run** — the emit path is best-effort; text is built inside a thunk inside the emitter's `try` |
| D-07 | Events are redacted on the same rule as every other outbound string |
| D-08 | A flat, bookmarkable route `/admin/pulse/runs/:runId` |
| D-09 | The elapsed clock derives from `run.started_at`, never from mount |
| D-10 | Four affordances carried over non-negotiably: audit drill-down, chain-status download lock + re-verify, resume-on-parked, Stop confirmation |
| D-11 | All eight run statuses handled; degraded shares the success branch; parked has its own; failed/cancelled keep their evidence |
| D-12 | The app's idiom: Tailwind utilities and `t()` for every string |

## 17.14 The redesign spec (2026-07-29) — D-R1…D-R11

Context: V-01 (`7dcf51d5`, 2026-07-28) produced a report telling the client the Benelux coffee data
"gives no complete picture" — false; the engine had 278 well-formed coffee claims and dropped all of
them because the model emitted the literal string `<TAB>` and the parser split on a real tab.

| id | Decision | Status |
|---|---|---|
| **D-R1** | The distiller parser accepts every separator the model actually uses; the prompt stops describing the separator with a copyable placeholder; a unit that returns lines but zero claims logs at WARNING | Built (15.4); replay proof recovered 278 claims |
| D-R2 | Retry once on an unusable fact list, covering all three Gemini format deviations | Built (15.4) |
| D-R3 | Stamp `sub_question`, `corroboration_key` and `as_of` on the claim row, in Python from the assignment, never parsed from model output | Built (15.5) |
| **D-R4** | An LLM groups winners into ≤5 groups; **each group goes to all providers** | Built (15.6); refined by D-W3-1/5; then D-W4-4a (2026-07-31) made **one deterministic group per client question the primary path** with the LLM "topic" grouping kept as an option (`NESTOR_TRIBUNAL_D6_GROUPING_MODE`) |
| **D-R5** | Drop `own` from the rotation → 3 providers | Built (D-W3-3) |
| **D-R6** | The workshop becomes a **creative loop**: generative evolve, judges give reasons, meta-review, 10-round cap | Built (15.7) |
| **D-R7** | A **discovery bracket**: evidence-anchored questions the client did not ask; **no source, no slot** | Built (15.6) |
| D-R8 | Record yield per assignment and per workshop round | Built (15.8, alembic 0018) |
| **D-R9** | **Keep the tournament and make it real** — pairwise Elo retained; ties fixed by raising the rounds (operator: "we are not killing tournament") | Confirmed by measurement |
| **D-R10** | **The loop discovers, it does not only sharpen**: evolve may invent; a grounded lookup admits or drops. Admission test **corrected 2026-07-31**: verify the *premise* is real, not that an answer already exists; evidence must be a real `groundingChunks` URL, never the model's own line | Built (15.7) |
| D-R11 | Elo carries across rounds (stands); the median seed was measured **inert** and replaced by a **catch-up schedule** (a newcomer plays up to the field's median match count) | Ruled D-W4-3 |

**Superseded within the spec, kept for the record:** the "ship Wave 1 alone and measure it" sequencing
(overridden 2026-07-29: *"I don't want to measure anything unless we finish all changes"* — one
deploy, one measuring run, attribution of an unexpected result to a single wave accepted as lost);
the ~$3.00 ten-round loop estimate (measured $0.24, exp11); the "9 of 10 winners WEAK" quality
diagnosis (a 240-char truncation artefact); the population-explosion fear (true only under
per-question brackets, which were rejected).

## 17.15 Waves 3, 4 and 5 — operator rulings D-W3, D-W4, D-W5

| id | Date | Decision |
|---|---|---|
| **D-W3-1** | 2026-07-29 | Group count: the LLM proposes, Python clamps, **hard maximum 5**, fewer expected on a simple brief |
| D-W3-2 | 2026-07-29 | Grouping failure → one group per client question, degraded; the top-k round-robin machinery deleted |
| **D-W3-3** | 2026-07-29 | `own` leaves the rotation and **only** the rotation (runner kept; still reachable on the degraded broadcast path — an accepted, commented gap) |
| D-W3-4 | 2026-07-29 | Discovery bracket: one group, ≤5 slots, per-parent cap 3, global pool (a quota would force invention), unused slots roll back to the mandate |
| **D-W3-5** | 2026-07-29 | **Mandate strict, discovery rides along**: a mandate group holds one client question (unless >5 questions); a parented discovery question joins its parent's group; cross-cutting questions get their own group; coverage is counted on mandate *members* |
| **D-W4-1** | 2026-07-31 | The rejected register is **within-run only**; bar on defect (KILL-unanswerable, WEAK after two evolves), never on defeat (losers stay promotable); enforcement in prompt *and* by semantic clustering; every drop logged with what and onto what |
| D-W4-2 | 2026-07-31 | A discovery question's admitting quote+URL is its own enrichment anchor; cross-cutting questions get both parents' findings |
| **D-W4-3** | 2026-07-31 | Median seed replaced by the **catch-up schedule** (99.8% strong-newcomer admission vs 1.5%) |
| D-W4-4 | 2026-07-31 | (a) grouping declamp: one-group-per-client-question is the primary path, topic grouping optional, the `min(5, …)` clamp removed; (b) aspect extraction becomes an explicit step with a Python assertion that every ask has ≥1 sub-question |
| D-W4-5…8 | 2026-07-31 | Winners = floor 5 per client question + 2 cross-cutting applied at the cut; 12 candidates generated per client question (the selection-ratio lever); prefer KEEP over WEAK; the five truncation constants raised together |
| **D-W4-9** | 2026-08-04 | A minimum-round floor (`round_no >= 4`) inside the exit verdict — saturation was vacuously true in round 1 and the loop broke after one pass |
| D-W4-10 / 11 | 2026-08-04 | Dead `max_size` parameter removed; every workshop note persisted as a run event |
| **D-W5-1** | 2026-08-04 | Yield data gets its own tables (`assignment_yield`, `workshop_round_yield`) and alembic 0018 — not `run_events` (allowlisted meta drops keys silently) and not `audit_log` (the legal chain) |
| D-W5-2 | 2026-08-04 | `client_question` nullable with a `parent_kind` discriminator (assistant call, flagged for override) |
| D-W5-3 | 2026-08-04 | The carried defects are closed **before** the run — measuring through a known misreport means hand-correcting the only evidence |
| D-W5-8 / 9 | 2026-08-04 | Accept and document the catch-up median boundary; remove the HTTP resolver from the `actions` spend signal |
| D-W5-16 | 2026-08-05 | The deploy surface is derived from the diff (two services, not four) |
| D-W5-17 / 18 | 2026-08-05 | The frozen yield columns are not widened; the yield tables' lack of a read surface is a pre-flight gate (`logging.logWriter` grant) |

## 17.16 Phases 21, 22, 23 — the run page, the verification page, legibility

| id | Date | Decision |
|---|---|---|
| 21 D-01/02 | 2026-08-10 | The feed is completed **before** the first measured run, so one run validates the engine and the feed together; the deploy surface is re-derived from the actual diff |
| 21 D-03…06 | 2026-08-10 | All 13 stages emit feed rows through one shared emitter shape and row budget with a visible elision row |
| 21 D-07…09 | 2026-08-10 | A finished agent never renders as a spinner (settle rule); "Show more" only when rows are hidden |
| 21 D-10/11 | 2026-08-10 | The verification report is a sibling of the card and the feed, gated on whether a report *can* exist, so failed and cancelled runs keep their verdicts |
| 21 D-12…14 | 2026-08-10 | The deep-research `thinking` prose is diagnosed before it is trimmed; measured verdict: zero content cuts, the volume driver was cardinality. *Later reversed on operator request 2026-08-31 — the waiting lines were removed outright (quick task 260831-jx2)* |
| 21 D-15 | 2026-08-10 | No raw stage key ever reaches the screen; every allowlisted marker must prove it has a human label |
| **D-22-1…5** | 2026-08-11 | The verification report gets its own page; restyled as a dashboard; citations preview on hover with the list collapsed; duplicate citations collapse to one number per source **without renumbering**; the activity feed leaves the intake page (reversing 21 R2 with the reversal in front of the operator) |
| 23 | 2026-08-13 | Business-friendly labels + tooltips for all 18 funnel keys; an honest work-phase banner that never says research is running once it is terminal; the dead `run-research` sentence deleted |

## 17.17 Phase 24 — re-runs and the steering note (ruled 2026-08-13, not yet built)

| id | Decision |
|---|---|
| **D-RR-1** | Deliberate re-runs get their **own counter**; the 3-attempt failure-recovery budget is untouched |
| **D-RR-2** | Typed confirmation before dispatch, and **no cost figure quoted** — per-run cost varies, so a number would be a fabricated fact |
| **D-RR-3** | The note **steers** the run (recording only was rejected), with no length cap |
| D-RR-3a | Mitigation adopted under D-RR-3: injected **once** in a delimited block, sanitised at the provider-prompt boundary, size surfaced in the UI — an unbounded field on a paid prompt was a shipped critical in 15.6 |
| sequencing | Zero-spend items (labels, banner) split into Phase 23; everything needing a paid run bundled into Phase 24 so **one** run validates it all |
| collision | Alembic `0019` is claimed by the write-side source-identity fix (DEF-22-06); the steering-note column must not silently take it |

## 17.18 Operator rulings recorded outside a phase (2026-07-22 → 2026-09-01)

| Date | Ruling | Where recorded |
|---|---|---|
| 2026-07-22 | No Anthropic usage-limit increase and no further live runs until the run-4cbb5311 defects are fixed; engine fixes come last, after phases 17 → 18 → 19 | STAKEHOLDER-NOTES |
| 2026-07-24 | One combined Phase-15* browser UAT against a live run, not piecemeal | STATE |
| 2026-07-27 | Anthropic secret repointed `Nestor_Claude → Nestor_Claude2` on all three services; a temporary burner key `Nestor_Claude_Temp` for V-01 | STATE |
| 2026-07-29 | **"I don't want to measure anything unless we finish all changes"** — one deploy, one measuring run | ENGINE-REDESIGN-SPEC § 2 |
| 2026-08-03 | `Nestor_Claude_Temp` rotation **deferred to go-live** — a decision, not an oversight; do not re-raise | ROADMAP 15.8 |
| 2026-08-06 | **Report synthesis moves to `claude-opus-5`**; the caps go to 20,000 under the SDK's 21,333 non-streaming ceiling | quick 260806-dn8 |
| 2026-08-06 | The client's chosen report language and size reach synthesis; `output_size` maps to both a keyword and a page range | quick 260806-lvt |
| 2026-08-13 | The operator said "decide" on the Phase 24 open points → D-RR-3a and the 23/24 split | STAKEHOLDER-NOTES |
| 2026-08-31 | **The context pack stays Dutch** — the operators are Dutch speakers | memory / CONTINUE-HERE |
| 2026-08-31 | The intake skill emits nl+fr+en in one call; echoed client text is never translated; truncation fails loudly | quick 260831-lm4 |
| 2026-08-31 | Remove the deep-research waiting lines from the feed (accepting up to 35 minutes of silence); drop the fact count from the "angle done" row | quick 260831-jx2 / ksq |
| 2026-08-31 | The research-start banner names the real providers and warns it is a paid run, **with no dollar figure** | quick 260831-lpm |
| 2026-09-01 | **Tribunal engine stages move to `claude-sonnet-5`**; the `claude` deep-research adapter stays on 4.6 | quick 260901-j6w |
| 2026-09-01 | **The five Flash stages move to `gemini-3.7-flash`** on measured position bias; the distiller stays on 2.5 Flash | quick 260901-lf2 |
| 2026-09-01 | **Budget stays uncapped**; surface cost on the run page instead | CONTINUE-HERE |
| 2026-09-01 | **Do not add Perplexity as a fourth research stream** (it resolves to the same OpenAI model already in use) | CONTINUE-HERE |

## 17.19 Stakeholder decisions still open

| Raised | Question | Options on the table |
|---|---|---|
| 2026-07-21 | Old context-pack versions stay in semantic search | delete / flag / keep |
| 2026-07-21 | Regenerating a pack resets status to `decomposed` | block / keep status / accept |
| 2026-07-21 | Start research while a regenerate is running uses the previous pack | disable the button (recommended) / operator discipline |
| 2026-09-01 | RAG over research questions — the proposal from the last stakeholder meeting | awaiting the stakeholders; the natural workshop agenda |
