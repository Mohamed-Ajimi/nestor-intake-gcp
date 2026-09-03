# The Nestor Pulse Handbook

Complete documentation of the Nestor Pulse platform: the intake application, the Tribunal
deep-research engine, the infrastructure they run on, and the reasoning behind every decision that
shaped them.

| | |
|---|---|
| **Covers** | the repository at commit `c8b8583`, 2026-09-03 |
| **Live at that commit** | `nestor-frontend-00035-zz2`, `nestor-api-00047-ghp`, `tribunal-api-00023-bc6`, `tribunal-worker-00009-fkm` |
| **Written from** | the source tree, the planning record in `.planning/`, the forensic run reports in `docs/tribunal-run-reports/`, and the deploy history in `infra/DEPLOY-RUNBOOK.md` |

⛔ **The one fact that shapes everything here.** Every change on disk is deployed, and the engine
models deployed on 2026-09-01 have never executed a research run. Wherever this handbook gives a
figure for them it is arithmetic or a replay, and it says so. Chapter 19 lists what the next run must
check.

## Reading paths

Nobody needs all twenty chapters. Pick a path.

| If you are | Read | Then |
|---|---|---|
| A stakeholder or client-side decision maker | [01 Executive overview](01-executive-overview.md) → [18 Market positioning](18-market-positioning.md) | [19 Known gaps and roadmap](19-known-gaps-and-roadmap.md) |
| A new engineer | [01](01-executive-overview.md) → [03 Architecture](03-architecture.md) → [04 Domain model](04-domain-model-and-lifecycles.md) → [05 Data model](05-data-model.md) | the module chapter you are touching, then [15 Quality and testing](15-quality-and-testing.md) and [13 Infrastructure and deploy](13-infrastructure-and-deploy.md) |
| The operator | [16 Operations runbook](16-operations-runbook.md) | [10 The pipeline](10-tribunal-pipeline.md) for what a stage is doing, [11 Models and providers](11-models-and-providers.md) for cost |
| An auditor or security reviewer | [14 Security and compliance](14-security-and-compliance.md) | [05](05-data-model.md) for the isolation at storage level, [09 Tribunal service](09-tribunal-service.md) § 09.6 for the audit chain |
| Planning the next phase | [19](19-known-gaps-and-roadmap.md) → [17 Decision log](17-decision-log.md) | [02 History and timeline](02-history-and-timeline.md) for why the order was what it was |
| Looking up a term or an identifier | [20 Glossary](20-glossary.md) | |

## Contents

| # | Chapter | Type | Abstract |
|---|---|---|---|
| 01 | [Executive overview](01-executive-overview.md) | explanation | What the product is, its two halves, the actors, the system in one diagram, what makes it different, and where it stands |
| 02 | [History and timeline](02-history-and-timeline.md) | narrative | Where the code came from, the five inherited flaws, both milestones phase by phase, the six live runs and what each taught, the deploy ledger |
| 03 | [Architecture](03-architecture.md) | explanation | Four services, two schemas, six trust boundaries, the three end-to-end flows, and why the boundaries sit where they do |
| 04 | [Domain model and lifecycles](04-domain-model-and-lifecycles.md) | reference | Roles and tenancy, the three state machines (intake status, frontend phase, engine run status), and every noun the system uses |
| 05 | [Data model](05-data-model.md) | reference | Both schemas table by table, the row-level security patterns, both migration lineages, and the two bucket layouts |
| 06 | [Backend: the intake API](06-backend-intake-api.md) | reference | App composition, config, auth, tenancy, the full endpoint inventory, both event streams, mail, storage, the CI guards |
| 07 | [AI skills](07-ai-skills.md) | reference | The six pre-research functions: prompts, output contracts, parsing, the review loop, context-pack versioning, semantic search |
| 08 | [The research seam](08-research-seam.md) | reference | The seam client, brief assembly, trigger rules, the poll driver, the completion path, delivery, the scope guard |
| 09 | [Tribunal: service and audit](09-tribunal-service.md) | reference | The HTTP surface, the internal caller, the worker loop, the event feed, the audit chain, the price table, citations |
| 10 | [Tribunal: the pipeline](10-tribunal-pipeline.md) | explanation | All thirteen stages, the question workshop in depth, dispatch, the fact-list contract, gates, verification, synthesis, reliability |
| 11 | [Models and providers](11-models-and-providers.md) | reference | Every model id and why, the three deep-research adapters, the cost anatomy of a real run, the three cost gaps, Perplexity |
| 12 | [Frontend](12-frontend.md) | reference | Stack, the route map, auth, the complete API contract, the phase machine, every screen, the run and verification pages, i18n |
| 13 | [Infrastructure and deploy](13-infrastructure-and-deploy.md) | reference and how-to | The GCP topology as coded, the IaC drift, the deploy procedure and its gates, the tags ledger, every CI config, local development |
| 14 | [Security and compliance](14-security-and-compliance.md) | explanation | The inherited flaws and what closes each, six layers of isolation, secrets, prompt-injection bounds, the EU AI Act record |
| 15 | [Quality and testing](15-quality-and-testing.md) | explanation | The three suites, the guards, the replay fixtures, and the catalogue of twelve ways a gate lied |
| 16 | [Operations runbook](16-operations-runbook.md) | how-to | The pre-flight checklist, triggering and reading a run, reading cost from the audit bucket, the incident playbook |
| 17 | [Decision log](17-decision-log.md) | reference | Every decision that shaped the system, in ADR form, with its context, options, ruling and consequence |
| 18 | [Market positioning](18-market-positioning.md) | explanation | What it is compared against, where it leads, where others lead, and what is measured versus projected |
| 19 | [Known gaps and roadmap](19-known-gaps-and-roadmap.md) | reference | What has never run, the cost gaps, every open defect, the deferred ledger, the planned phases |
| 20 | [Glossary](20-glossary.md) | reference | Every term, acronym, identifier family, status and stage vocabulary |

## Conventions

Every chapter opens with the same header block: audience, type, the files a reader should open to
verify it, and the commit it was verified against.

**Types** follow a documentation split. *Explanation* answers "why is it like this"; *reference*
answers "what exactly is it"; *how-to* answers "how do I do this"; *narrative* answers "how did we
get here". Several chapters combine two.

**Every fact that a reader could dispute cites its source**, as `path:line` or `path::symbol`.
Numbers from a research run cite the run id. Where something could not be established from the
repository, the chapter says "not determined from the code" rather than guessing.

**Reasoning is written as context, options, decision, consequence.** Module chapters link to
[chapter 17](17-decision-log.md) by identifier rather than restating a rationale.

**Diagrams are Mermaid**, so they render on GitHub without a build step. Twenty of them: system
context and containers, three sequence flows, the three state machines, both entity diagrams, the
pipeline, the workshop loop, the deploy order, the route tree and the isolation layers.

## Honesty markers

The project's own convention, used throughout:

| Marker | Meaning |
|---|---|
| ⛔ | Never executed, or never observed. A projection, not an observation |
| ⚠ | Measured once, fragile, or inconsistent with something adjacent |
| **SUPERSEDED** | Kept deliberately. A reader who finds only the current rule cannot tell why the earlier one was wrong |

Two rules follow from these and are worth stating once. **A projection is never presented as an
observation**: the cost and quality figures for the models deployed on 2026-09-01 are arithmetic over
replayed prompts, and every chapter that mentions them says so. And **a decision that looks like
unfinished work is flagged as a decision**: two model constants are deliberately older than the rest,
and both carry a "do not finish the job" note here and in the code.

## Keeping this current

The handbook is verified against a commit, not maintained continuously. When you change the system:

1. Update the module chapter that owns the fact. The "Where to look" table at the end of each module
   chapter maps files to the chapter that documents them.
2. Add the decision to [chapter 17](17-decision-log.md) with its context and consequence. Mark what
   it supersedes rather than deleting it.
3. Move the item out of [chapter 19](19-known-gaps-and-roadmap.md) if it closed one, and add whatever
   the change newly owes.
4. Update the **Last verified** commit in the header block of every chapter you touched.

The planning record under `.planning/` remains the primary source for decisions in flight;
this handbook is the consolidated, verified account of what was actually built.
