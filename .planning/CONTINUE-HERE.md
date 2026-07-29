# CONTINUE HERE — session handoff 2026-07-29 (late)

Supersedes the earlier 2026-07-29 handoff, which said *"Next action — Wave 1, and ship it alone."*
**That is done, and the "ship it alone" half is overridden.** Tree is clean, nothing in flight,
**nothing is deployed.**

## The one thing to know before you touch anything

**OPERATOR RULING, 2026-07-29:** *"I don't want to measure anything unless we finish all changes."*

No deploy and no live run until the **whole** engine redesign is built. Wave 1 is code-complete and
gate-verified but deliberately **not live**. Waves 2–5 land on top of it and **one** run measures all
of it together.

This reverses `.planning/ENGINE-REDESIGN-SPEC.md` § 2 and the previous handoff. The trade-off was
stated and accepted: with several waves landing at once, an odd result in that run cannot be
attributed to a single change. **Do not re-argue it.** Both the spec and the parked deploy plan carry
the override in-place, because both still read as the opposite on their face.

## Start here

**`/gsd-plan-phase 15.5`** — Wave 2, claim attribution (D-R3), off `ENGINE-REDESIGN-SPEC.md` § 3.

It is a **hard prerequisite** for 15.6, not a nice-to-have: today a claim's `facet` is inherited from
the angle it was dispatched under, so the moment a dispatch group spans two client questions that
inheritance breaks and the claim has no single parent.

## The path, and why it is in this order

| Phase | Wave | What |
|---|---|---|
| 15.4 | 1 | Extraction repair — **DONE, gate-verified, NOT deployed** |
| **15.5** | **2** | **NEXT** — claim attribution (sub-question + `corroboration_key` on the claim row) |
| 15.6 | 3 | ≤5 LLM-formed groups × all providers, `own` dropped, **+ discovery bracket** |
| 15.7 | 4 | Creative workshop loop — generative evolve, reasoned judges, meta-review, 10-round cap |
| 15.8 | 5 | Yield instrumentation, then **ONE deploy + ONE measuring run** |

15.5 before 15.6 because grouping across client questions breaks the inherited facet. 15.7 after 15.6
because the tournament only earns its cost once the discovery bracket gives it genuinely different
ideas to rank, instead of narrower rewordings of questions the client already asked.

## What Wave 1 actually delivered (phase 15.4, 10 plans, ~30 commits)

The engine was discarding research it had successfully extracted and then telling clients it did not
have it. V-01's report said the coffee data *"geeft geen volledig beeld"*; the engine had **278
well-formed coffee claims** and threw every one away because gemini wrote the literal string `<TAB>`
while the prompt used `<TAB>` as a placeholder *describing* the separator.

- **The 278 are recovered** — proven in CI against the real audit blobs
  (`test_the_two_coffee_calls_sum_to_the_278_the_client_never_saw`), and independently by lifting the
  committed parser out of `steps.py` and running it over the fixture: **141 / 137 / 43 / 143**. The
  two already-working responses still yield exactly 43 and 143 — the half that proves a fix, not a
  trade.
- **The silence is fixed**, which matters more. A `log.debug` was the only trace of 278 losses. The
  WARNING now carries the provider, the line count, "this is a PARSE FAILURE, not an empty research
  result", and the offending first line with the `<TAB>` visible in it.
- **The ZERO-claims warning stopped crying wolf** — it now names only facets the call actually saw.
- Plus: one additive retry on an unusable fact list, the `STATEMENT`-prefix normaliser, the
  `[cite: N]` cite index, redirect resolution at ingest (outside the persistence transaction), and
  tolerant `agent_done` lambdas.

Final gate state: engine gate **1030 passed / 32 of 32 files**, gates build **182 passed**, zero
failures. Full record: `.planning/phases/15.4-.../15.4-WAVE1-GATE.md`.

## Owed before the 15.8 run — all three block it

1. **Rotate `Nestor_Claude_Temp`.** It transited a chat in plaintext on 2026-07-27 and is still live
   on both Tribunal services.
2. **Plan 15.4-07 — the `gpt-5.6-sol` cost row.** Deferred by the operator, still open. Either
   published rates, or a recorded ruling that none exist. **Adding the key with nulls is not an
   option** — `_rate()` turns a null into `Decimal("0")`, producing a confident **$0.00** and clearing
   `cost_pending` on a fabricated number. ROADMAP criterion 6 was amended so "no published rate
   exists" is a PASS, not a gap.
3. **Alembic `0016` has never touched a database.** Proof is the literal `Running upgrade 0015 ->
   0016` line — never exit 0. This repo has been burned by exactly that.

Also open: **15.4-05's revert-and-confirm-red proof** needs a deliberately mutated tree (batched, not
per-plan). And **`15.4-11` must be RE-SCOPED** from "Wave 1 alone" to the whole redesign before it
runs; it is parked with a DO-NOT-EXECUTE banner.

## Booked, deliberately out of scope — do not absorb these

From plan 15.4-06's investigation (`docs/tribunal-run-reports/run-20260728-7dcf51d5-OPEN-QUESTIONS.md`,
operator ruling appended):

- **`gate_errors: 153` is the same class of defect as `<TAB>`, one stage over** — provider format
  drift, all 11 calls returned `STOP` with full answers, the model just used a one-column shorthand.
  43 of the 153 were explicit DROPs sent to paid skeptics anyway (~**$6–8/run**), and the feed
  rendered `status: "done"`. Deferred **because fixing it changes which claims reach paid
  verification** — the one variable the measuring run must hold still.
- **The un-rendered degradation sentence** — `verification/report.py::_degradation` returns early, so
  the one line that would tell a human about defaulted gate answers never renders. Cheaper and safer
  than the parsing half; changes no claim's fate.
- **86 of 302 verdicts came back `insufficient`** (28%) and the report says so nowhere. Bigger than
  the certainty question, and the natural home for the "surface the skeptic verdict" work.
- **Q1 closed:** `426 − 27 refuted − 3 conflict losers = 396`, residual 0. The `293` was a different
  cut of the same 426 — that misreading is why it looked unanswerable.
- **Q3 ruled A-now-C-later:** `certainty` is a **write-only column** — a writer, a clamp, no reader.
  Note the null share goes ~44% → ~67% after this phase, so "it's a minority" expires next run.

## Standing cautions that still apply

- **Judge the engine from the delivered report** (`output` row, `format='markdown'`) — not the claim
  table, not the logs.
- **The verification stage works. Do not touch it.**
- **`tribunal/cloudbuild.test-engine.yaml`** — its script is one single-quoted `bash -c '…'` block
  capped by Cloud Build at **10,000 chars** (now ~5,300 after its commentary was moved verbatim into
  YAML comments). **No apostrophes anywhere inside it** — one closes the string and the build dies
  with exit 127. Cost a build this session.
- **A stdlib-only Python exists** at
  `C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe` (3.14.4 — `ast`, `py_compile`,
  `json`; **no** pytest/sqlalchemy). It cannot run the suite, but it makes real proof possible: lift a
  pure function out with `ast` and drive it. Three executors used it to prove things that would
  otherwise have been PENDING.
- **`.planning/` is gitignored** — always `git add -f`.
- **Parallel executors race STATE.md/ROADMAP.md.** Let them skip it and roll up centrally.

## Carried forward — a real finding, deliberately not fixed

`_parse_distiller_response` calls `line.strip()` **before** splitting, so a leading empty facet column
is reachable via `<TAB>`/`|||`/`|` but a **real tab is eaten and every column shifts left**. Found by
running the parser, asserted as recorded behaviour with a named test, and left alone: changing
`line.strip()` would alter how every already-working tab response parses, including V-01's 43 and 143.
It deserves its own decision, not a drive-by fix.
