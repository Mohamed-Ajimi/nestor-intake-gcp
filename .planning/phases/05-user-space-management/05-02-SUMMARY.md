---
phase: 05-user-space-management
plan: 02
subsystem: backend-data-layer
tags: [alembic, sqlalchemy, audit, tenant-root, grants, status-columns]
requires:
  - "0005_grant_runtime_sa migration (down_revision chain)"
  - "organizations + organization_memberships root tables (0001)"
  - "app_superadmin role + 0003 bypass; runtime SA grant idiom (0005)"
provides:
  - "nestor.audit_log root table (never RLS-scoped, D-07) + AuditLog ORM model"
  - "organization_memberships.status + organizations.status (soft-deactivate flags)"
  - "app/db/audit.log(session, ...) one-tx audit write seam"
affects:
  - "Plan 05-04 admin endpoints (consume audit.log + status columns)"
  - "QA-04 audit instrumentation across all mutating admin actions"
tech-stack:
  added: []
  patterns:
    - "Tenant ROOT table via 0001 root-table create shape (no space_id NOT NULL, no RLS)"
    - "Reserved-name trap: ORM attr event_metadata -> DB column 'metadata'"
    - "Explicit Index() in __table_args__ (no column-level shortcut) for alembic-check-clean"
    - "Dual GRANT (app_superadmin + env-guarded runtime SA DO-block) for a new root table"
    - "Audit-in-the-same-tx: write via the passed-in session, no orphan rows"
key-files:
  created:
    - backend/app/db/models/audit.py
    - backend/app/db/alembic/versions/0006_user_space_audit.py
    - backend/app/db/audit.py
  modified:
    - backend/app/db/models/membership.py
    - backend/app/db/models/organization.py
    - backend/app/db/models/__init__.py
decisions:
  - "PK has no server_default in 0006 (mirrors 0001 root tables; ORM supplies uuid4 client-side) to keep alembic check clean"
  - "status is String + server_default, NOT a PG enum (avoids alembic enum-alter friction); app enforces {active,deactivated}"
  - "audit_log.space_id is a plain nullable UUID with NO FK so the trail outlives a soft-deactivated/removed space (D-07)"
metrics:
  duration: ~25m
  completed: 2026-06-22
  tasks: 3
  files: 6
---

# Phase 5 Plan 02: User/Space Data Layer (audit_log + status columns) Summary

Phase-5 data foundation: Alembic revision 0006 adds `organization_memberships.status` +
`organizations.status` (soft-deactivate flags) and the root `audit_log` table with dual
grants; a matching `AuditLog` ORM model (reserved-name trap avoided) and the
`app/db/audit.log` one-transaction write seam back it.

## What Was Built

### Task 1 — AuditLog model + status columns + registry (commit 20ad506)
- `backend/app/db/models/audit.py`: `AuditLog` ORM model, a tenant ROOT table mirroring
  `membership.py`. Columns: `id` (uuid pk, `default=uuid.uuid4`), `actor_uid` (String NOT
  NULL), `actor_membership_id` (uuid nullable FK → `nestor.organization_memberships.id`
  `ondelete="SET NULL"`), `event_type` (String NOT NULL), `target` (String nullable),
  `space_id` (plain nullable UUID, **NO FK** — D-07 root), `event_metadata`
  (`mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'"))`),
  `created_at` (tz `func.now()`). Three explicit `Index()` entries in `__table_args__`
  (`ix_audit_log_space_id`, `ix_audit_log_created_at`, `idx_audit_log_event_created`).
- **Reserved-name trap avoided:** the Python attribute is `event_metadata`; the DB column
  is the string `"metadata"`. No bare `metadata: Mapped[...]` (would collide with
  `Base.metadata`).
- Added `status: Mapped[str] = mapped_column(String, nullable=False, server_default="active")`
  to `OrganizationMembership` (after `role`) and `Organization` (after `slug`).
- Registered `AuditLog` in `models/__init__.py` (registry now 15 tables) so `Base.metadata`
  carries it for autogenerate + schema-shape tests.

### Task 2 — Alembic 0006 migration (commit aba1a2f)
- `backend/app/db/alembic/versions/0006_user_space_audit.py`, `down_revision = "0005"`.
- `upgrade()`: `add_column` `status` (String, NOT NULL, `server_default="active"`) on both
  root tables (existing rows backfill non-null); `create_table("audit_log", …)` using the
  0001 root-table shape (NO `_space_id_col()`, NO RLS); three explicit `create_index` calls.
- **Grants (Pitfall 1, belt-and-suspenders):** explicit
  `GRANT SELECT, INSERT, UPDATE, DELETE ON nestor.audit_log TO app_superadmin` (0003 idiom)
  + a replicated 0005 `RUNTIME_DB_USER` env-guarded `DO`-block that GRANTs the same to the
  runtime SA (no-ops cleanly when the env is unset on the testcontainer; `RAISE EXCEPTION`
  when the env is set but the role is absent).
- **Never RLS-scoped:** `audit_log` is deliberately absent from every `*_space_isolation` /
  `*_superadmin_all` / `_RLS_TABLES` loop — no `CREATE POLICY` / `ENABLE ROW LEVEL SECURITY`
  statement targets it (D-07).
- `downgrade()`: symmetric reverse order — guarded REVOKE → drop three indexes → drop table
  → drop the two status columns.
- PK carries no `server_default` (mirrors 0001 root tables exactly) so `alembic check` sees
  no drift against the ORM model.

### Task 3 — app/db/audit.log helper (commit f89e3b5)
- `backend/app/db/audit.py`: free function
  `log(session, *, actor_uid, actor_membership_id=None, event_type, target=None,
  space_id=None, metadata=None) -> None` that does
  `session.add(AuditLog(..., event_metadata=metadata or {}))` via the **passed-in session**
  (audit row commits/rolls back WITH the recorded action — no orphan rows, no separate tx).
- Lives INSIDE `app/db/` and imports no engine/sessionmaker, so
  `scripts/ci_no_raw_db_access.sh` stays green (verified locally, exit 0).
- Docstring documents the full event-type → metadata contract and the **never log
  link/token/password** rule (T-5-05).

## Deviations from Plan

None — plan executed as written. Two construction-detail decisions were made within the
plan's stated intent (both noted in `decisions` frontmatter):
- The `audit_log` PK uses no `server_default` to mirror the 0001 root tables exactly and
  keep `alembic check` clean (the plan said "id uuid pk"; 0001's convention is client-side
  `uuid4`, no server default).
- The `app_superadmin` GRANT/REVOKE statements are written as single contiguous string
  literals (not f-string-split) so the plan's acceptance-criterion substring check matches.

## Verification

- **By construction (passed):** all grep/string acceptance checks pass —
  `event_metadata` mapped to column `"metadata"`, no bare `metadata: Mapped[`, no
  `index=True`, three explicit index names present, status columns NOT NULL with
  `server_default="active"`, `down_revision="0005"`, contiguous
  `GRANT … ON nestor.audit_log TO app_superadmin`, `RUNTIME_DB_USER` referenced, no
  `CREATE POLICY`/RLS statement targets `audit_log`, helper signature has the required
  keyword-only params and passes `event_metadata=metadata or {}`.
- **Executed (passed):** `bash scripts/ci_no_raw_db_access.sh` exits 0 (the new helper
  introduces no raw-DB symbol outside the whitelist).
- **DEFERRED — no local Python/Docker runtime** (confirmed project constraint): the Task 1
  `python -c` import/assert, the Task 2 `ast.parse`, and `alembic upgrade head` +
  `alembic check` on real Postgres cannot run on this dev box. These run green in CI / GCP
  per author-by-construction; the model/migration were authored against the exact 0001 root
  shape, the 0003 grant idiom, and the 0005 env-guarded DO-block to guarantee that.

## Notes for Next Plans

- Plan 05-04 admin endpoints consume `app.db.audit.log` and the `status` columns. The admin
  CRUD seam must NOT subclass `TenantRepository` (root + cross-space reach) — use the
  superadmin engine + 0003 bypass (see 05-PATTERNS.md § admin_repo.py / get_admin_session).
- `audit_log` read access flows ONLY through the superadmin engine; never set a space GUC
  to read it.

## Self-Check: PASSED
- FOUND: backend/app/db/models/audit.py
- FOUND: backend/app/db/alembic/versions/0006_user_space_audit.py
- FOUND: backend/app/db/audit.py
- FOUND commit: 20ad506 (Task 1)
- FOUND commit: aba1a2f (Task 2)
- FOUND commit: f89e3b5 (Task 3)
