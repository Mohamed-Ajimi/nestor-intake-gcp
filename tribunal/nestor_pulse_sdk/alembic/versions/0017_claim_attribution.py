"""0017 D-R3 claim attribution (Phase 15.5, wave 2).

Additive-only migration: THREE nullable columns on an existing table. No new
table, no index, no constraint, no backfill, no data read, no security DDL.

Why this exists
---------------
A claim records WHAT it says and WHO found it, but not WHICH SUB-QUESTION IT
ANSWERS or WHICH CORROBORATION GROUP IT CAME FROM. Both facts already exist in
memory at dispatch time -- `research_division.py::_angle()` builds every angle
with `sub_question` and `corroboration_key` alongside `focus_area` -- and they
simply stop short of the claim row.

Today `claim.facet` carries the PARENT CLIENT QUESTION, inherited from the angle
the claim was dispatched under. That inheritance is correct only while one angle
maps to exactly one client question. Phase 15.6 makes an LLM group winners into
at most five groups and sends each group to ALL providers; the moment a group
spans two client questions, a claim from it has no single parent and `facet`
becomes a lie. This revision is therefore a HARD PREREQUISITE for 15.6, not a
convenience. It is deliberately small and deliberately boring: it records
information that already exists and currently goes nowhere.

`as_of` is here for a different reason, and it is not a "dates feature". Finding
D-V01-4 of the V-01 forensics was WITHDRAWN: gemini and claude had read
different De Haan articles at different points in one rollout -- 7 sites in 2021
against roughly 90 later -- and BOTH WERE TRUE. What looked like a contradiction
was a time series, and neither the engine nor the human analysis could tell the
difference, because nothing on the row carried a date. This is missing metadata,
not a missing detector.

What this migration carries
---------------------------
1. `claim.sub_question` (TEXT nullable) -- the winner text this claim answers.
2. `claim.corroboration_key` (TEXT nullable) -- the shared dispatch key
   ('w01' / 'w02' / ...), the real join key for corroboration. Per D-W2-2 only
   the TOP-3 winners get a key today (`research_division.py:867-874` deals the
   remainder round-robin with the EMPTY STRING), so this column will be NULL for
   roughly 12 of 15 winners on the next run. That is EXPECTED AND CORRECT; it
   fills up in phase 15.6 when every group goes to every provider. An absent key
   is bound as NULL and never as '' -- the `found_by` rule in
   `citations/extractor.py::_insert_claim` ("an ABSENT provenance is bound as
   None, never as []") applies unchanged, because "no key recorded" and
   "recorded as the empty key" are different facts and the corroboration queries
   must be able to tell them apart.
3. `claim.as_of` (DATE nullable) -- the claim's own date where the provider
   stated one. DATE and not TIMESTAMP: a claim is dated to a day at best.

Why nullable
------------
All three are nullable so that NOT ONE EXISTING ROW IS TOUCHED, and the reason
goes further than legacy data.

Every row written before this revision predates all three columns. Beyond that,
the `claim_distiller` fallback path carries NO DISPATCH ATTRIBUTION AT ALL, BY
CONSTRUCTION: it builds its units as `(provider_name, chunk_text)`, so the angle
-- and with it the sub-question and the corroboration key -- is already gone
before distillation begins. Claims from that path will carry NULL for
`sub_question` and `corroboration_key` permanently, and that is the honest
record of what happened, not a gap to be filled. `as_of` is NULL whenever the
provider stated no date, which will be the common case.

A NOT NULL column on any of the three would therefore demand a fabricated
backfill of values nobody has and nobody can honestly invent. `ADD COLUMN ...
NULL` with no default is a catalogue-only change in PostgreSQL 11+: no table
rewrite, no index build, a brief ACCESS EXCLUSIVE lock that returns immediately.

Which alembic line
------------------
The TRIBUNAL line (`tribunal/nestor_pulse_sdk/alembic/versions/`), whose head
was 0016 (`0016_source_resolved_url.py`, phase 15.4 wave 1) and whose version
table is `tribunal.tribunal_alembic_version`. It is NOT the intake `nestor` line
under `backend/app/db/alembic/versions/`, which ships its own independent
revision sequence. Two schemas, two `alembic_version` tables, two revision
sequences, never crossed (v1.1 roadmap decision, Pitfall 2). A revision id
borrowed from the other line is how one of them silently stops upgrading.

NOTE ON THE SPEC. `.planning/ENGINE-REDESIGN-SPEC.md` section 3 says "a new
alembic revision on top of 0015". That sentence is STALE, not wrong-in-spirit:
it was written before wave 1 landed 0016. The verified head at the time this
file was written is 0016, so `down_revision` is "0016".

No CHECK constraint and no enum type
------------------------------------
`sub_question` and `corroboration_key` are CALLER-supplied -- stamped in Python
from the dispatch assignment, never parsed out of model output, the same rule
`_parse_distiller_response` applies to `provider` and `enforce_scope_guard`
applies to `parent`. They are clamped in Python inside `_insert_claim`, which is
the `claim.certainty` idiom migration 0013 established. A CHECK here would turn
a threading bug into a FAILED INSERT in the final persistence step of a roughly
$50 run, trading a wrong string for lost claims. `as_of` needs none either: it
is a DATE, so the type is the constraint, and the extractor returns a real
`datetime.date` or None and never a string.

ADDITIVE ONLY
-------------
No existing row is read, written, backfilled or deleted by this revision.
`upgrade()` contains exactly three `op.add_column` calls and nothing else;
`downgrade()` contains exactly three `op.drop_column` calls in exact inverse
order and nothing else. No index is created: none of the three columns is
searched across tenants, and an index added here would be a build cost plus a
per-write cost on the persistence path of a paid run.

Hash-chain safety
-----------------
`nestor_pulse_sdk/audit/hash_chain.py::_payload_for_row` freezes ELEVEN fields
on `audit_log`. NONE of them lives on `claim`. This revision names exactly one
table, `claim`, and adds only columns the chain has never seen, so
`verify_chain` cannot move off `(True, None)` and the frozen payload field count
stays 11 -- unaffected BY CONSTRUCTION, not by inspection (EU AI Act Art. 12
audit-trail gate, deadline 2026-08-02).

Deploy-time proof -- OWED, NOT CLAIMED
--------------------------------------
THE PROOF OF THIS MIGRATION IS THE LITERAL LOG LINE, on one line and unwrapped:

    Running upgrade 0016 -> 0017

IT IS NEVER EXIT CODE 0. This repository has a recorded incident of an
alembic step that exited 0 without ever printing an upgrade line, and reported
green.

Phase 15.5 PERFORMS NO DEPLOY. Per the operator ruling of 2026-07-29, waves 1-4
of the engine redesign land in git only; there is ONE deploy and ONE measuring
run at the end of phase 15.8. So that proof is OWED AT PHASE 15.8 -- alongside
0016's own still-unpaid `Running upgrade 0015 -> 0016`, which has likewise never
touched a database.

Until both lines print, BOTH revisions are WRITTEN, NOT APPLIED. Do not assert
that either one ran.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No schema= kwarg: env.py has already pointed search_path at the `tribunal`
    # schema, the same way every additive column in 0011, 0012, 0013 and 0016 is
    # written.
    #
    # Deliberately NO security DDL. `claim` already carries ENABLE + FORCE ROW
    # LEVEL SECURITY, its `claim_tenant_isolation` policy (re-issued in 0010s
    # NULLIF form) and its `claim_worker_all` policy (0008). A PostgreSQL
    # row-level POLICY is a TABLE-level object evaluated against row values, so a
    # newly added column is covered BY CONSTRUCTION. Re-issuing a policy, an
    # index or a GRANT here would be pure regression risk with zero security
    # benefit -- the reasoning 0013 and 0016 both record.

    # -------------------------------------------------- (1) claim.sub_question
    # The winner text this claim answers. `facet` is the PARENT client question
    # inherited from the angle; once a dispatch group can span two client
    # questions (phase 15.6) that inheritance breaks, so the sub-question is
    # recorded on the row.
    op.add_column(
        "claim",
        sa.Column("sub_question", sa.Text(), nullable=True),
    )

    # --------------------------------------------- (2) claim.corroboration_key
    # The shared dispatch key: 'w01' | 'w02' | ... | NULL. NULL for roughly 12 of
    # 15 winners today because only the top-3 get a key (D-W2-2) -- correct, not
    # a bug. NULL and the empty string are different facts; see the docstring.
    op.add_column(
        "claim",
        sa.Column("corroboration_key", sa.Text(), nullable=True),
    )

    # --------------------------------------------------------- (3) claim.as_of
    # The claim date where the provider stated one. DATE, not TIMESTAMP.
    op.add_column(
        "claim",
        sa.Column("as_of", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    # Exact inverse order, and NOTHING ELSE. In particular this touches no
    # policy and no index -- there is nothing to restore, because `upgrade()`
    # never touched either.
    op.drop_column("claim", "as_of")
    op.drop_column("claim", "corroboration_key")
    op.drop_column("claim", "sub_question")
