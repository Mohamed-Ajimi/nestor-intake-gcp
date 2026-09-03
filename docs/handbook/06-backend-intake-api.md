# 06 — Backend: the intake API (`nestor-api`)

| | |
|---|---|
| **Audience** | Engineers changing or operating the intake backend; auditors checking how tenancy, auth and secrets are enforced |
| **Type** | Reference (endpoint, config, schema-of-behaviour tables) with Explanation (mechanism and rationale) |
| **Source of truth** | `backend/app/main.py`, `backend/app/core/*`, `backend/app/auth/*`, `backend/app/db/*`, `backend/app/api/*`, `backend/app/mail/*`, `backend/app/storage/*`, `backend/scripts/*.sh`, `backend/tests/conftest.py`, `backend/Dockerfile`, `backend/pyproject.toml`, `cloudbuild.test.yaml` |
| **Last verified** | commit `c8b8583`, 2026-09-03 |

All paths in this chapter are relative to `backend/` unless prefixed with `<repo>/`. Line numbers are from the tree at `c8b8583`. Nothing here was read from `.claude/worktrees/**`.

## 06.1 In one paragraph

`nestor-api` is a single FastAPI process on Cloud Run that is the only thing allowed to talk to the intake database. Every request arrives with an Identity Platform ID token; the backend verifies it, reads the caller's role and space from the token's server-set claims, and picks one of two database engines: a tenant engine whose connections carry the caller's space id as a transaction-local Postgres setting, or a superadmin engine that logs in as a dedicated bypass role. Every table query then runs through a repository class that adds the space filter itself, so an endpoint author cannot forget it, and row-level security in Postgres catches anything that slips past. Around that core sit the intake lifecycle verbs, the AI skill dispatchers (chapter 07), the research seam (chapter 08), signed-URL file storage, notification-only mail in three languages, and two server-sent-event streams. Four grep scripts run in CI to keep the dangerous shapes out of the tree.

## 06.2 How it works

### 06.2.1 One authenticated request, end to end

The mechanism is easiest to follow by tracing one call, `GET /intakes/{intake_id}`, from the browser to the row and back.

1. **The router refuses anonymous traffic.** Every feature router is included under `protected_router`, which is declared as `APIRouter(dependencies=[Depends(get_current_identity)])` (`app/api/auth_routes.py:57`, mounted `app/main.py:137-174`). The only anonymous paths are `/healthz` and `/readyz` (`app/main.py:194-221`), and `/auth/session`, which verifies the bearer itself.
2. **The token is verified, never trusted.** `get_current_identity` pulls the bearer with `HTTPBearer(auto_error=True)` and calls `auth.verify_id_token(token, check_revoked=True)` (`app/auth/dependencies.py:59,76`). The `check_revoked` flag costs one extra Admin SDK round trip per request; that is the price accepted for AUTH-04 so that a deactivated user is denied on the very next call. Claims are read only from the verified token, never from body, path or query (`dependencies.py:8-11`). There is no database lookup on this path (`dependencies.py:11-13`).
3. **A frozen `Identity` is produced.** `Identity(uid, email, role, space_id)` is a frozen dataclass (`app/auth/identity.py:28-40`). A superadmin has `space_id is None`; a user has a non-null space id (`identity.py:8-12`). A token with no `role` claim at all gets 403 with the message "No role claim — sync session" (`dependencies.py:93-99`), which tells the frontend to call `/auth/session` first.
4. **The dependency picks an engine.** `get_tenant_repo` (`app/db/session.py:52-81`) branches on role. Superadmin: `get_superadmin_engine()`, no space. User: `get_engine()` and the token's `space_id`; a user with no `space_id` is refused with 403 "No space — not authorized" before any connection is opened.
5. **One transaction per request, GUC set inside it.** The dependency opens `maker.begin()` and, on the user path only, runs `SELECT set_config('app.current_space_id', :sid, true)` (`app/db/rls.py:44-61`). The third argument `true` makes the setting transaction-local, the equivalent of `SET LOCAL`, so it reverts at COMMIT. The file says "NEVER pass false" (`rls.py:11-17`).
6. **The repository scopes the query.** `IntakeRepository.get(row_id)` routes through `_scope`, which appends `WHERE space_id = :space_id` for a user and leaves the statement unchanged for a superadmin (`app/db/repository.py:80-99`). A miss returns `None` and the route maps it to 404.
7. **Postgres filters again.** On the tenant engine the row-level security policy `intakes_space_isolation` compares `space_id` with the GUC (`app/db/alembic/versions/0002_rls_policies.py:80-84`). On the superadmin engine the OR'd policy `intakes_superadmin_all` matches `current_user = 'app_superadmin'` (`0003_superadmin_bypass.py:107-114`).
8. **Commit, checkin, reset.** The transaction commits when the dependency's `with` block exits, which reverts the `SET LOCAL`. As a belt on top of that, a pool `checkin` listener runs `RESET app.current_space_id` on the raw pg8000 cursor every time a connection returns to the pool (`app/db/base.py:222-243`).

```mermaid
sequenceDiagram
    participant B as Browser
    participant P as protected_router
    participant D as get_current_identity
    participant S as get_tenant_repo
    participant E as Engine factory
    participant PG as Cloud SQL
    participant R as IntakeRepository
    B->>P: GET /intakes/:id with Bearer ID token
    P->>D: Depends
    D->>D: verify_id_token check_revoked=True
    alt expired, revoked, disabled, invalid
        D-->>B: 401
    else no role claim
        D-->>B: 403 sync session
    end
    D-->>S: Identity uid, email, role, space_id
    alt role is superadmin
        S->>E: get_superadmin_engine
    else role is user
        S->>E: get_engine via IAM connector
    end
    S->>PG: BEGIN
    opt user path only
        S->>PG: set_config app.current_space_id, sid, true
    end
    S->>R: IntakeRepository session, identity
    R->>PG: SELECT ... WHERE space_id = sid or unscoped for superadmin
    PG-->>R: rows after RLS policy
    R-->>B: IntakeView JSON
    S->>PG: COMMIT reverts SET LOCAL
    PG-->>PG: pool checkin runs RESET app.current_space_id
```

### 06.2.2 The router tree

```mermaid
flowchart TD
    APP["FastAPI app, lifespan"]
    H["GET /healthz and GET /readyz, anonymous"]
    AUTH["auth_router prefix /auth, self-verifying bearer"]
    PR["protected_router, Depends get_current_identity"]
    ADM["admin_router prefix /admin, superadmin only"]
    INT["intake_router prefix /intakes"]
    AI["ai_router prefix /intakes, skills and search"]
    ST["storage_router prefix /intakes, uploads and signed URLs"]
    RS["research_router prefix /intakes, the Tribunal seam"]
    ME["me_router, /me and /me/locale"]
    APP --> H
    APP --> AUTH
    APP --> PR
    PR --> ADM
    PR --> INT
    PR --> RS
    PR --> AI
    PR --> ST
    PR --> ME
```

Include order in `app/main.py`: admin `:137`, intake `:144`, research `:152`, ai `:159`, storage `:166`, me `:172`, then `auth_router` on the bare app `:173` and `protected_router` on the app `:174`. `main.py` passes no `prefix=` to any include; each prefix is declared inside its router module.

### 06.2.3 Process lifecycle

The app is `FastAPI(lifespan=lifespan)` (`app/main.py:105`). On startup the lifespan initialises the Firebase Admin SDK through Application Default Credentials with no JSON key (`main.py:78`, `app/core/firebase.py:65`), then runs `sweep_orphaned_skill_runs()` inside a try/except so a sweep failure never blocks boot (`main.py:86-91`). The sweep flips any `skill_runs` row still `running` after 30 minutes to `failed` with the message "orphaned by restart" (`app/db/ai_session.py:195-214`). This matters because skill runs execute as in-process background tasks; if an instance dies mid-call, nothing else would ever close the row. On shutdown the pooled engine is disposed only if one was actually built (`main.py:98-102`); building an engine just to dispose it would raise `KeyError` on `DATABASE_URL` on Cloud Run (review finding WR-03). The lifespan runs no migrations and sets no GUC (`main.py:21-24`). Migrations are a discrete Cloud Run Job on the same image (see 06.16).

Handlers are plain `def`, not `async def`, because pg8000 is a blocking driver (`main.py:18-20`). The only `async def` handlers are the two SSE streams, which push their DB reads through `run_in_threadpool`.

### 06.2.4 Two engines, one setting

There are two SQLAlchemy engines, each an `lru_cache(maxsize=1)` singleton, sharing one pool configuration (`app/db/base.py:67-74`):

```python
_POOL_KW = dict(pool_size=2, max_overflow=3, pool_pre_ping=True, pool_recycle=1800, echo=False, future=True)
```

The **tenant engine** (`get_engine`, `base.py:119-149`) runs in Cloud SQL mode when no explicit DSN is given and `INSTANCE_CONNECTION_NAME` is set: it uses the Cloud SQL Python connector with `enable_iam_auth=True`, logging in as the runtime service account named by `DB_USER` with no password (`base.py:94-116`). Otherwise it is in URL mode and reads `DATABASE_URL`. An explicit DSN argument always wins. The **superadmin engine** (`get_superadmin_engine`, `base.py:200-219`) connects as the literal Postgres user `app_superadmin` with a password read from Secret Manager (`base.py:180-197`), the exact literal the 0003 policy matches. Both engines register the same checkin `RESET`.

The superadmin path sets no GUC at all; its bypass is a `current_user` test in the policy (`app/db/session.py:60-65`). Cloud SQL does not permit `BYPASSRLS`, which is why a dedicated login role with an OR'd policy was chosen (see 17 · 01-03).

### 06.2.5 Long calls release the session

A Claude or Whisper call can take 90 to 120 seconds. Holding one of five pooled connections for that long would starve the instance. `run_with_session_release` (`app/db/ai_session.py:99-148`) structures every AI skill as READ in one short tenant session returning plain DTOs, CALL with no connection held, WRITE in a fresh tenant session where the GUC is re-issued. If anything raises, an `on_error` callback runs in yet another fresh session so the skill run can be marked `failed`. The test `test_ai_session_release` pins that `set_space_context` is called exactly twice per user AI run (`ai_session.py:16-17`). The research poll driver reuses the same contract (chapter 08).

## 06.3 App composition and health

| Concern | Behaviour | Cite |
|---|---|---|
| CORS | `CORSMiddleware` is added only when `cors_allowed_origins` is non-empty; `allow_credentials=True`, methods `GET POST PATCH DELETE OPTIONS`, headers `Authorization Content-Type`. Empty list means no middleware at all, never `*` | `app/main.py:114-122` |
| Other middleware | none | `app/main.py` |
| `CodedError` handler | returns `{"detail", "code"}` with the error's status; plain `HTTPException` is untouched and carries no `code` | `app/main.py:177-191` |
| `GET /healthz` | sync, returns `{"status":"ok"}`, never touches the DB | `app/main.py:194-197` |
| `GET /readyz` | sync, `SELECT 1` through `get_engine().connect()`; 200 `{"status":"ready","db":"ok"}` or 503 `{"status":"not-ready","db":"error"}`; the exception is logged on logger `nestor.health`, never returned | `app/main.py:61,200-221` |

Operational note: on the live service `/healthz` has been observed returning 404 from the Google upstream while `/readyz` returns 200; smoke tests should target `/readyz` (memory record of the 2026-08-31 deploy, not determined from the code).

## 06.4 Configuration

`class Settings(BaseSettings)` at `app/core/config.py:33` with `env_file=None, case_sensitive=False, extra="ignore"` (`config.py:56-60`). `get_settings()` returns a fresh, uncached instance on every call (`config.py:184-190`), so an environment change is visible without a restart of the reading code path.

| Field | Env var | Default | Purpose | Cite |
|---|---|---|---|---|
| `instance_connection_name` | `INSTANCE_CONNECTION_NAME` | `None` | Cloud SQL `project:region:instance` | `config.py:37,62` |
| `db_user` | `DB_USER` | `None` | IAM service-account login name, no password | `config.py:38,63` |
| `db_name` | `DB_NAME` | `None` | the `nestor` database | `config.py:39,64` |
| `database_url` | `DATABASE_URL` | `None` | local and test pg8000 DSN, never set on Cloud Run | `config.py:42,65` |
| `port` | `PORT` | `8080` | injected by Cloud Run | `config.py:45,66` |
| `firebase_project_id` | `FIREBASE_PROJECT_ID` | `None` | non-secret local/test override for the Admin SDK `projectId` | `config.py:48-53,70` |
| `storage_bucket` | `STORAGE_BUCKET` | `None` | GCS bucket; keyless V4 signing via IAM signBlob | `config.py:72-77` |
| `nestor_admin_email` | `NESTOR_ADMIN_EMAIL` | `None` | recipient of the `admin_validated` mail | `config.py:84-87` |
| `app_base_url` | `APP_BASE_URL` | `None` | origin for mail CTAs and the set-password action link | `config.py:89-93` |
| `tribunal_service_url` | `TRIBUNAL_SERVICE_URL` | `None` | `tribunal-api` URL, used verbatim as OIDC audience; must carry no path suffix | `config.py:95-107` |
| `model_apply_intake` | `MODEL_APPLY_INTAKE` | `claude-sonnet-4-5` | model id for apply-intake-skill | `config.py:123` |
| `model_context_pack` | `MODEL_CONTEXT_PACK` | `claude-sonnet-4-5` | model id for the context pack | `config.py:124` |
| `model_structure_answers` | `MODEL_STRUCTURE_ANSWERS` | `claude-sonnet-4-6` | model id for structure-answers | `config.py:125` |
| `model_extract_insights` | `MODEL_EXTRACT_INSIGHTS` | `claude-sonnet-4-6` | model id for extract-insights | `config.py:126` |
| `model_embeddings` | `MODEL_EMBEDDINGS` | `text-embedding-3-small` | 1536 dimensions | `config.py:121,127` |
| `model_transcription` | `MODEL_TRANSCRIPTION` | `whisper-1` | Whisper | `config.py:128` |
| `cors_allowed_origins` | `CORS_ALLOWED_ORIGINS` | `[]` | accepts a JSON array or a comma-separated list; empties dropped | `config.py:148-181` |

The model-id fields implement Phase 7 decision D-06 (model ids are configuration, not literals; see 17 · 07 D-06). The defaults above are what the code says. Whether the live `nestor-api` revision overrides them through its environment was not determined from the code; chapter 11 holds the model inventory and chapter 13 the deploy record.

Reads of `os.environ` outside `Settings` (grep over `app/` and `scripts/`, comments excluded): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` in `app/ai/clients.py`; `DATABASE_URL`, `INSTANCE_CONNECTION_NAME` in `app/db/alembic/env.py`; `CLOUD_SQL_IP_TYPE`, `DATABASE_URL`, `DB_NAME`, `DB_USER`, `INSTANCE_CONNECTION_NAME`, `SUPERADMIN_DB_PASSWORD_SECRET` in `app/db/base.py`; `RESEND_API_KEY` in `app/mail/resend.py`; `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` in `scripts/seed_superadmin.py`; `RUNTIME_DB_USER` in migrations 0005, 0006, 0009 and 0011. `base.py` reads the environment directly rather than `Settings` to avoid an import cycle with `app.core` (`config.py:9-13`).

## 06.5 Secrets

Secrets are deliberately absent from `Settings`. The config module says there is no DB password field by design (`config.py:5-7`) and that AI keys are read at call time (`config.py:114-116`), as is `RESEND_API_KEY` (`config.py:79-82`).

| Secret | Where it is read | Mechanism | Cite |
|---|---|---|---|
| Superadmin DB password | `app/db/base.py::_load_superadmin_password` | the only Secret Manager read in the backend: `access_secret_version(name=os.environ["SUPERADMIN_DB_PASSWORD_SECRET"])`, `lru_cache(maxsize=1)`, lazy import; the env var holds the full resource path `projects/<p>/secrets/<name>/versions/latest` | `base.py:158-177` |
| Tenant DB credential | none | IAM database authentication through the connector; no password exists | `base.py:94-116` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | `app/ai/clients.py` | `os.environ[...]` at call time, fresh client per call, 180 s timeout; a missing key raises `KeyError` | `clients.py:38-62` |
| `RESEND_API_KEY` | `app/mail/resend.py` | `os.environ` at call time in the bearer header | `resend.py:36,58-67` |
| Firebase Admin SDK | `app/core/firebase.py` | Application Default Credentials, no credential argument | `firebase.py:65` |
| GCS signing | `app/storage/gcs.py` | `google.auth.default()` plus IAM signBlob; no service-account JSON anywhere | `gcs.py:11-16,111-119` |
| OIDC token to `tribunal-api` | `app/research/tribunal_client.py` | `fetch_id_token` from the attached service account, minted per call | `tribunal_client.py:59-77` |

Which Secret Manager entries feed which env vars at deploy time is chapter 13's table; the `ci_no_sa_json_key.sh` guard (06.14) keeps the keyless posture from regressing.

## 06.6 Auth

### 06.6.1 Token verification order

`get_current_identity` (`app/auth/dependencies.py:62-106`) catches Admin SDK exceptions in an order that is load-bearing because the subclasses must come before their parent:

| Order | Exception | Response | Cite |
|---|---|---|---|
| 1 | `ExpiredIdTokenError` | 401 "Token expired" | `dependencies.py:77-91` |
| 2 | `RevokedIdTokenError` | 401 "Session revoked" | same |
| 3 | `UserDisabledError` | 401 "Account disabled" | same |
| 4 | `InvalidIdTokenError` | 401 "Invalid token" | same |
| 5 | verified but `role` claim is `None` | 403 "No role claim — sync session" | `dependencies.py:93-99` |

The 401 versus 403 split is pinned by `tests/test_auth_dependency.py` (`dependencies.py:15`). `dependencies.py` contains only this one function; the repository and session dependencies live in `app/db/session.py`.

### 06.6.2 The Identity object

```python
@dataclass(frozen=True)
class Identity:            # app/auth/identity.py:28-40
    uid: str
    email: str | None
    role: str
    space_id: str | None
```

Frozen so it cannot be mutated mid-request (`identity.py:14`). Roles are `superadmin` and `user` only (see 17 · P-03).

### 06.6.3 Login sync: `/auth/session` and `SyncResult`

`POST /auth/session` (`app/api/auth_routes.py:149`) is mounted outside `protected_router` because a freshly created user has no `role` claim yet and would be refused by the shared dependency. The handler verifies the bearer itself with `check_revoked=True` (`auth_routes.py:173`) using the same four 401 arms, then calls `sync_claims_from_membership(decoded)` (`app/auth/session.py:116-170`):

| Step | Behaviour | Cite |
|---|---|---|
| Short-circuit | if the token already carries `role`, return `ALREADY_SYNCED` with no DB and no Admin call | `session.py:141-142` |
| Email trust | `email` is used only when `email_verified` is true (review finding CR-01) | `session.py:147` |
| Membership lookup | uid first via `provider_user_id`; fall back to email only when no uid row and email is not None; both arms use `.scalars().first()` so `MultipleResultsFound` cannot raise | `session.py:77-113` |
| No membership | return `NO_MEMBERSHIP`; a user is never created here (Phase 5 D-02) | `session.py:152-156` |
| Write | `set_custom_user_claims(uid, {"role", "space_id"})` with `space_id=None` for superadmin, else the organisation id as string; return `WROTE` | `session.py:161-170` |

`SyncResult` is `WROTE`, `ALREADY_SYNCED`, `NO_MEMBERSHIP` (`session.py:60-74`); the route maps them to 200, 200 and 403 "No membership — not authorized" (`auth_routes.py:190,194`). The lookup reads the root table `organization_memberships` through the default app engine; root tables are never RLS-scoped. Two gotchas are documented in the file: setting claims does not refresh the client's current token, so the frontend must call `getIdToken(true)` afterwards (`session.py:21-26`), and the claim blob is limited to 1000 bytes (`session.py:28-29`).

### 06.6.4 Admin SDK user lifecycle

All calls go through a module-level `from firebase_admin import auth` so tests can patch one seam (`app/auth/admin_users.py:59`).

| Function | What it does | Cite |
|---|---|---|
| `create_invited_user(email, *, role, space_id)` | `auth.create_user` with a random 32-byte password, then `set_custom_user_claims`; the invite endpoint always passes `role="user"` (Phase 5 D-01a) | `admin_users.py:64-85` |
| `generate_set_password_link(email)` | password-reset link; when `app_base_url` is set, wraps it in `ActionCodeSettings(url=f"{base}/auth/action", handle_code_in_app=True)` | `admin_users.py:88-112` |
| `deactivate_user(uid)` | `update_user(disabled=True)` plus `revoke_refresh_tokens`; the SDK has no `disable_user` | `admin_users.py:115-125` |
| `reactivate_user(uid)` | `update_user(disabled=False)`; claims are not re-issued | `admin_users.py:128-135` |
| `resolve_existing_uid(email)` | `get_user_by_email(...).uid` for the re-invite reconcile; the endpoint answers 409 | `admin_users.py:138-146` |

Revocation is enforced at request time by the `check_revoked=True` argument in `dependencies.py:76`, not in this module.

## 06.7 Tenancy and the database layer

### 06.7.1 Engine factory, connector, pool

| Item | Value | Cite |
|---|---|---|
| Schema | `NESTOR_SCHEMA = "nestor"`, `Base.metadata = MetaData(schema="nestor")` | `app/db/base.py:48,59` |
| Pool | `pool_size=2, max_overflow=3, pool_pre_ping=True, pool_recycle=1800` on both engines | `base.py:67-74` |
| Connector | `Connector(refresh_strategy="lazy")`, cached, lazy import | `base.py:77-91` |
| Tenant creator | `connect(INSTANCE_CONNECTION_NAME, "pg8000", user=DB_USER, db=DB_NAME, enable_iam_auth=True, ip_type=CLOUD_SQL_IP_TYPE or "PUBLIC")` | `base.py:94-116` |
| Mode switch | Cloud SQL mode when no DSN argument and `INSTANCE_CONNECTION_NAME` is set; else URL mode on the argument or `DATABASE_URL` | `base.py:119-149` |
| Superadmin creator | `user="app_superadmin"`, Secret Manager password, no IAM auth | `base.py:180-197` |
| Superadmin engine | separate cached engine, same pool args, same checkin reset; no URL-mode branch exists in `base.py` (tests supply their own) | `base.py:200-219` |
| Checkin reset | `RESET app.current_space_id` on every pool checkin | `base.py:222-243` |
| Session factory | `sessionmaker(engine or get_engine(), expire_on_commit=False, future=True)` | `base.py:246-257` |

The pool numbers were chosen in Phase 2 so that worst-case connections across capped Cloud Run instances stay under the Cloud SQL tier limit (see 17 · 02).

### 06.7.2 The GUC

`SPACE_GUC_KEY = "app.current_space_id"` (`app/db/rls.py:41`). `set_space_context` executes `SELECT set_config('app.current_space_id', :sid, true)` (`rls.py:44-61`). The canonical revert is the COMMIT of the `SET LOCAL`; the checkin `RESET` is a belt, not the primary mechanism. The policy uses `NULLIF(current_setting('app.current_space_id', true), '')::uuid` because after a `SET LOCAL` reverts on a pooled connection the setting reads as `''`, not NULL, and a bare `''::uuid` would raise (`0002_rls_policies.py:20-37`). An empty context therefore yields zero rows on read and rejects every write (`0002:30-32`). Chapter 05 quotes the policies and grants in full.

### 06.7.3 Per-request dependencies

All dependencies in `app/db/session.py` are sync generators composing `Depends(get_current_identity)` and following one pattern (`session.py:52-81`): pick the engine by role, refuse a null-space user with 403, open `maker.begin()`, set the GUC on the user path, yield a repository bound to that session.

| Dependency | Yields | Notes | Cite |
|---|---|---|---|
| `get_tenant_repo` | `IntakeRepository` | | `session.py:52-81` |
| `get_intake_answer_repo` | `IntakeAnswerRepository` | | `:84-107` |
| `get_intake_and_answer_repos` | `(IntakeRepository, IntakeAnswerRepository)` | one shared session | `:110-143` |
| `get_intake_and_source_repos` | `(IntakeRepository, IntakeSourceRepository)` | one shared session | `:146-182` |
| `get_intake_source_repo` | `IntakeSourceRepository` | | `:185-212` |
| `get_skill_run_repo` | `SkillRunRepository` | | `:215-236` |
| `get_research_artifact_repo` | `ResearchArtifactRepository` | | `:239-263` |
| `get_intake_template_repo` | `IntakeTemplateRepository` | | `:266-287` |
| `get_me_session` | raw `Session` | both roles; superadmin gets no GUC; null-space user still 403 | `:290-327` |
| `get_admin_session` | `AdminRepo` | 403 "Superadmin only" for any non-superadmin before a session opens; superadmin engine, no GUC | `:330-365` |

### 06.7.4 `TenantRepository`, and why scoping cannot be omitted

`class TenantRepository(Generic[M])` (`app/db/repository.py:58-67`) takes `(session, identity)` and derives two private facts: `_is_super` and `_space_id` parsed from the token (`repository.py:69-78`). `_scope(stmt)` returns the statement unchanged for a superadmin and appends `where(model.space_id == self._space_id)` for a user (`:80-90`). `list`, `get` and `patch` all pass through `_scope` (`:92-118`).

Three properties make omission structurally impossible rather than a matter of discipline:

- **No parameter to get wrong.** "There is no `space_id` parameter anywhere in this module" (`repository.py:9`). A route cannot pass a space id because no method accepts one.
- **`create` refuses ambiguity.** `create(**values)` forces `values["space_id"] = self._space_id` and raises `RuntimeError` when called as a superadmin (`:133-155`), because a superadmin has no implicit space.
- **`create_in_space` is the one explicit door.** It is superadmin-only (raises if `_space_id` is set) and calls `set_space_context(session, space_id)` before inserting (`:157-182`). That GUC set is not decoration: the intake prefill trigger is `SECURITY DEFINER`, inside which `current_user` becomes the function owner, so the `app_superadmin` bypass does not apply to the trigger's child insert into `intake_answers`. The child insert passes its WITH CHECK only because the GUC names the target space (`repository.py:171-177`, `0008_prefill_after_insert.py:15-18`).

Subclasses and their extra methods (`repository.py:185-696`): `IntakeRepository`; `IntakeAnswerRepository` with `list_for_intake`, `upsert_batch` (an `INSERT ... ON CONFLICT ON CONSTRAINT uq_intake_answers_intake_field DO UPDATE ... WHERE space_id = :space_id`), `upsert_batch_in_space`, `upsert_extracted` (stamps `extracted_by="llm"`, `confidence`, `source_chunk_id`) and `upsert_extracted_in_space`; `SkillRunRepository` with `list_for_intake`, `latest_for_intake`; `ResearchRunRepository` with the same two; `ResearchArtifactRepository` with `latest_context_pack_for_intake` and `list_context_packs_for_intake` filtered on `source == "context-pack-generator"`; `IntakeTemplateRepository`; `IntakeSourceRepository` with `list_for_intake`, `delete_by_storage_path`; `TranscriptRepository` with `list_for_intake`, `list_for_source` ordered by `chunk_index`; `ExtractedInsightRepository.list_for_intake`; `ArtifactEmbeddingRepository`.

### 06.7.5 `AdminRepo`

`AdminRepo` (`app/db/admin_repo.py`) is not a `TenantRepository`: it has no `_scope`, no `space_id` predicate except on templates, and no delete method at all (Phase 5 D-10; `admin_repo.py:8-22`). It is reachable only through `get_admin_session`. Methods: users (`list_users`, `get_membership`, `find_active_membership`, `create_membership(org_id, provider_user_id, email, role="user", status="active")`, `set_membership_status`, `count_active_superadmins`, `:90-168`); spaces (`list_spaces`, `get_space`, `create_space(name, slug=None, default_locale=None)`, `update_space`, `set_space_status`, `:172-222`); templates (`list_templates(space_id)`, `get_template`, `clone_template`, `update_template`, `:226-268`). Status values `active` and `deactivated` are application strings, not a Postgres enum (`:48-49`).

### 06.7.6 Sessions for background work and streams

`app/db/ai_session.py` mirrors `session.py` for code that runs outside a request: `_engine_and_space` raises `PermissionError("No space — not authorized")` instead of an HTTP exception (`ai_session.py:62-76`); `tenant_session(identity)` is a context manager that opens `maker.begin()` and sets the GUC on the user path each entry (`:79-96`); `IntakeNotInScopeError` maps to 404 in routes (`:51-59`); `create_running_skill_run` inserts the `status="running"` row, using `create_in_space(intake.space_id, ...)` for a superadmin (`:151-192`); `search_artifacts` is the exact cosine scan used by semantic search (`:217-276`, detail in chapter 07).

`app/db/stream_session.py` serves the SSE handlers with one short transaction per tick and returns plain dicts, never ORM rows (`stream_session.py:1-30`): `check_intake_in_scope` (`:50-60`), `read_latest_run_dict` (`:63-90`), `read_latest_research_run_dict` (`:93-155`), `read_brief_inputs` (`:158-236`, chapter 08).

### 06.7.7 The audit log contract

`audit.log(session, *, actor_uid, actor_membership_id=None, event_type, target=None, space_id=None, metadata=None)` adds an `AuditLog` row to the caller's session and does not commit; the row lands in the same transaction as the action it records (`app/db/audit.py:41-71`). `audit_log` is a root table without RLS (chapter 05). The docstring contract (`audit.py:15-24`) names nine event types:

| Event type | Metadata |
|---|---|
| `user.invited` | `{email, assigned_space_id, role}` |
| `user.deactivated` | `{reason?}` |
| `user.reactivated` | `{}` |
| `auth.login` | `{sync_result}` |
| `space.created` | `{name, slug}` |
| `space.updated` | changed fields |
| `space.deactivated` | `{reason?}` |
| `template.cloned` | `{source_template_id?}` |
| `template.updated` | changed fields |

Routes also emit `space.reactivated`, `mail.sent`, `intake.status_changed {from, to}`, `report.replaced {artifact_id}`, `research.resumed`, `research.cancelled` and `research.chain_reverified` (cites in 06.8). Links, tokens and passwords are never logged (`audit.py:26-29`).

## 06.8 Endpoint inventory

Role vocabulary: **any** means any verified token with a `role` claim; **superadmin** means `identity.role == "superadmin"`; **user** means a tenant user with a `space_id` claim. A user with no `space_id` gets 403 on every data route.

### 06.8.1 `auth_router`, prefix `/auth` (`app/api/auth_routes.py:140`)

| Method | Path | Role | Body | Response | Side effects | Errors |
|---|---|---|---|---|---|---|
| POST | `/auth/session` | anonymous bearer, self-verified | none | `{"synced": true}` | `verify_id_token(check_revoked=True)`; `sync_claims_from_membership` writes custom claims | 401 expired / revoked / disabled / invalid (`:175-181`); 403 "No membership — not authorized" (`:194`) |

### 06.8.2 `me_router`, no prefix (`app/api/me_routes.py:253`)

| Method | Path | Role | Body | Response | Side effects | Errors |
|---|---|---|---|---|---|---|
| GET | `/me` (`:332`) | any | none | `Me{locale, space_default_locale}` (`:256-264`) | none | none |
| PATCH | `/me/locale` (`:341`) | any | `{locale}` | `Me` | writes `membership.locale` on the caller's own active membership (`:358-362`); a superadmin with no membership persists nothing (`:363`) | `CodedError(422, INVALID_LOCALE)` when not in `{nl, fr, en}` (`:245,355-356`) |

Locale resolution: `membership.locale`, then `organization.default_locale`, then `nl` (`:202-206,248,273-297`). Membership lookup is `provider_user_id == uid AND status == "active"`, scoped to the token's space when present, ordered `created_at, id`, `limit(1)` (`:315-329`).

### 06.8.3 `admin_router`, prefix `/admin` (`app/api/admin_routes.py:74`), superadmin only

Every handler depends on `get_admin_session`, so a non-superadmin receives 403 before any session opens.

| Method | Path | Body | Response | Side effects (audit event) | Errors |
|---|---|---|---|---|---|
| GET | `/admin/users` (`:131`) | none | `list[UserView{id, email, space_id, role, status}]` | none | none |
| POST | `/admin/users` (`:137`) | `InviteBody{email, space_id}`, no role field (`:82-90`) | `InviteResult{uid, space_id, action_link}` | IdP user with hard-coded `role="user"` (`:169-171`); membership `role="user", status="active"` (`:179-185`); set-password link (`:188`); `user.invited` (`:192-203`) | 404 "Space not found" (`:155-156`); 409 "User already invited to this space" (`:160-163`); 409 "User already exists" (`:172-176`) |
| POST | `/admin/users/{membership_id}/deactivate` (`:208`) | none | `UserView` | IdP disable and revoke (`:244-245`); status `deactivated` (`:246`); `user.deactivated` (`:248-255`) | 404 (`:226-227`); 409 "Cannot deactivate yourself" (`:230-233`); 409 "Cannot deactivate the last active superadmin" (`:234-241`) |
| POST | `/admin/users/{membership_id}/reactivate` (`:261`) | none | `UserView` | IdP un-disable (`:277-278`); status `active` (`:279`); `user.reactivated` (`:281-288`) | 404 (`:274-275`) |
| POST | `/admin/users/{membership_id}/invite-mail` (`:305`) | none | `MailResult{success}` | fresh action link per send (`:344`); `render_invite(locale=space.default_locale or "nl")` (`:339-345`); `mail.sent {type:"invite"}` on success only (`:356-363`) | 404 (`:323-324`); 409 "Member has no email address to invite" (`:326-329`); transport failure is HTTP 200 `{success:false}` with no audit (`:351-353`) |
| GET | `/admin/spaces` (`:431`) | none | `list[SpaceView{id, name, slug, status, default_locale}]` | none | none |
| POST | `/admin/spaces` (`:437`) | `SpaceCreateBody{name, slug?, default_locale?}` | `SpaceView` | `create_space`; `space.created {name, slug, default_locale}` (`:455-466`) | `CodedError(422, INVALID_LOCALE)` (`:420-428,449-450`) |
| PATCH | `/admin/spaces/{space_id}` (`:470`) | `SpacePatchBody{name?, slug?, default_locale?}`, no status | `SpaceView` | `space.updated` with the changed fields (`:494-500`) | 400 "No fields to update" (`:485`); 422 `INVALID_LOCALE` (`:487-488`); 404 (`:491-492`) |
| POST | `/admin/spaces/{space_id}/deactivate` (`:504`) | none | `SpaceView` | status `deactivated`; `space.deactivated` (`:514-520`) | 404 (`:512-513`) |
| POST | `/admin/spaces/{space_id}/reactivate` (`:524`) | none | `SpaceView` | status `active`; `space.reactivated` (`:534-540`) | 404 (`:532-533`) |
| GET | `/admin/spaces/{space_id}/templates` (`:586`) | none | `list[TemplateView{id, space_id, name, schema}]` | none | none |
| POST | `/admin/spaces/{space_id}/templates` (`:595`) | `TemplateCloneBody{name, schema?, source_template_id?}` | `TemplateView` | `clone_template`; `template.cloned {source_template_id}` (`:611-618`) | 404 "Space not found" (`:607-608`) |
| PATCH | `/admin/spaces/{space_id}/templates/{template_id}` (`:622`) | `TemplatePatchBody{schema}` | `TemplateView` | `update_template`; `template.updated {schema_updated: true}` (`:638-644`) | 404 "Template not found" (`:636-637`) |

There is no DELETE route in this router (`:24-26`). Invite subjects per locale are in `_INVITE_SUBJECTS` (`:55-59`).

### 06.8.4 `intake_router`, prefix `/intakes` (`app/api/intake_routes.py:91`)

Response and body models (`intake_routes.py:99-326`): `IntakeView{id, space_id, status, client_name, validation_link_sent_at, results_link_sent_at, context_pack_artifact_id, final_report_artifact_id}`; `IntakeCreate{client_name?, template_id?}`; `IntakePatch{client_name?}` (no status field, `:18-22`); `AnswerView` and `AnswerItem{field_key, value, value_json}`; `AnswerBatch{answers}`; `SkillRunView{id, skill, status, created_at, applied_at, completed_at}`; `SkillRunsView{latest, runs}`; `SkillRunFullView{id, output_parsed, cost_estimate_usd}`; `TemplateView{id, name, schema}`; `ContextPackView{id, text_content, created_at, notes}`; `IntakeSourceView{id, kind, file_name, language, created_at}`; `MemberView{id, email, name}` where `name` is always `None`; `MailRecipients{recipients: list[str]}` with `extra="forbid"`; `DeliverBody{storage_path, recipients=[]}` with `extra="forbid"`; `ReportView{filename, delivered_at, byte_size, mime_type, storage_path}`.

| Method | Path | Role | Body | Response | Side effects | Errors |
|---|---|---|---|---|---|---|
| GET | `/intakes?space_id=` (`:418`) | any | none | `list[IntakeView]` | none; `space_id` narrows only for a superadmin (`:436-437`), inert for a user | none |
| POST | `/intakes?space_id=` 201 (`:441`) | any | `IntakeCreate` | `IntakeView` | superadmin `create_in_space(space_id)` (`:471`); user `create` in own space (`:475`); DB default `draft` fires the prefill trigger (`:448`) | 422 "Select a client (space) before creating an intake." for a superadmin without `?space_id` (`:466-470`) |
| GET | `/intakes/templates` (`:479`) | any | none | `[TemplateView]` holding the single canonical template (`:492-498`) | none | none |
| GET | `/intakes/{intake_id}` (`:506`) | any | none | `IntakeView` | none | 404 "Intake not found" (`:518-519`) |
| PATCH | `/intakes/{intake_id}` (`:523`) | any | `IntakePatch` | `IntakeView` | `patch(client_name)` (`:541`) | 400 "No fields to update" (`:538-539`); 404 (`:542-543`) |
| GET | `/intakes/{intake_id}/answers` (`:556`) | any | none | `list[AnswerView]` | none | scoped-empty 200, never 404 |
| PATCH | `/intakes/{intake_id}/answers` (`:565`) | any | `AnswerBatch` | full `list[AnswerView]` after upsert (`:596`) | ownership pre-check (`:583-585`); superadmin `upsert_batch_in_space` (`:593`); user `upsert_batch` (`:595`); conflict target `(intake_id, field_key)` | 404 (`:584-585`) |
| GET | `/intakes/{intake_id}/skill-runs` (`:604`) | any | none | `SkillRunsView` latest plus newest-first list (`:614-618`) | none | scoped-empty |
| GET | `/intakes/{intake_id}/context-pack` (`:627`) | any | none | `{"latest": ContextPackView or null, "history": [...]}` (`:646-653`) | none | never 404; existence-hidden 200 (`:639-644`) |
| GET | `/intakes/{intake_id}/sources` (`:661`) | any | none | `IntakeSourcesView` | none | scoped-empty 200 (`:674-680`) |
| GET | `/intakes/{intake_id}/members` (`:856`) | any | none | `list[MemberView]` of active members with an email in the intake's space (`:880-891`) | none | 404 (`:876-878`) |
| POST | `/intakes/{intake_id}/mail/validation` (`:894`) | any | `MailRecipients` | `{"success", "recipient_count", "type"}` (`:1103`) or `{"success": false}` | one render and send per locale group; stamps `validation_link_sent_at` (`:1050,1093-1094`); `mail.sent {type, recipient_count}` (`:1095-1102`) | 404 (`:999-1001`); 422 for any invalid, unknown, deactivated or email-less recipient id or an empty list (`:811-853`); `{"success": false}` when `APP_BASE_URL` is unset (`:1029-1033`) or the transport fails (`:1087-1089`) |
| POST | `/intakes/{intake_id}/mail/reminder` (`:914`) | any | `MailRecipients` | same | validation template with `is_reminder=True` (`:1078-1085`); no timestamp (`:1050`); `mail.sent` | same |
| POST | `/intakes/{intake_id}/mail/results` (`:932`) | any | `MailRecipients` | same | results template with CTA `/intake/{id}/results` (`:1040`); stamps `results_link_sent_at` (`:1042`); `mail.sent` | same |
| POST | `/intakes/{intake_id}/mail/intake` (`:952`) | any | `MailRecipients` | same | intake-invite template with CTA `/intake/{id}` (`:1044`); no timestamp (`:1046`); `mail.sent` | 409 "Cannot send the intake mail in status …" unless `draft` (`:1005-1009`); else same |
| GET | `/intakes/{intake_id}/skill-runs/stream` (`:1136`) | any | none | `text/event-stream` (06.11) | none | 403 null-space (`:1162-1163`); 404 (`:1164-1165`), both before the stream opens |
| GET | `/intakes/{intake_id}/skill-runs/{run_id}` (`:1202`) | any | none | `SkillRunFullView` (`:1219-1225`) | none | 404 "Skill run not found" when out of scope or `run.intake_id != intake_id` (`:1216-1218`) |
| POST | `/intakes/{intake_id}/submit` (`:1274`) | any | none | `IntakeView` | status via `_SUBMIT_TRANSITIONS` (`:1295`); `intake.status_changed {from, to}` in the same transaction (`:1296-1299`); when the new status is `validated_by_client`, fire-and-forget `_send_admin_validated` (`:1307-1314`) | 404 (`:1290-1291`); 409 "Cannot submit an intake in status …" (`:1252-1260`) |
| POST | `/intakes/{intake_id}/review` (`:1356`) | any | none | `IntakeView` | `_REVIEW_TRANSITIONS` (`:1375`); `intake.status_changed` (`:1376-1379`) | 404 (`:1370-1371`); 409 "Cannot review an intake in status …" (`:1263-1271`) |
| POST | `/intakes/{intake_id}/deliver` (`:1517`) | any; runs in `tenant_session`, superadmin writes via `create_in_space` (`:1457-1459`) | `DeliverBody` | `IntakeView` | tx 1: `research_artifacts` row `artifact_type="report", source="human-report", mime_type="application/pdf"` (`:1448-1455`); patch `status=delivered, final_report_artifact_id` (`:1558-1560`); `intake.status_changed` (`:1561-1568`). tx 2: results-family mail with CTA `/intake/{id}/report` (`:1489`); on 2xx stamp `results_link_sent_at` (`:1577-1580`) and `mail.sent {type:"results"}` (`:1506-1513`) | 404 (`:1546-1547`); 409 "Cannot deliver in status …" unless `in_research` (`:1548-1552`); 422 "Report must be a PDF" (`:1426-1429`); 404 "Object not found" when the key is not under `{space_id}/{intake_id}/reports/` (`:1430-1433`); 422 bad recipient id, raised after the delivery commit (`:1534-1536`) |
| POST | `/intakes/{intake_id}/report/replace` (`:1590`) | any | `DeliverBody` | `IntakeView` | new artifact row and repoint of `final_report_artifact_id`; old row and object kept (`:1621-1624`); `report.replaced {artifact_id}` (`:1625-1632`); optional re-send and re-stamp when `recipients` is non-empty (`:1635-1643`) | 404; 409 "Cannot replace in status …" unless exactly `delivered` (`:1614-1618`); 422 and 404 key asserts (`:1619`) |
| GET | `/intakes/{intake_id}/report` (`:1652`) | any | none | `ReportView`; `delivered_at` mirrors `results_link_sent_at` (`:1687-1692`) | none | 404 "Report not found" unless `status == "delivered"` by equality (`:1676-1678`), `final_report_artifact_id` set (`:1679-1680`) and the artifact exists (`:1683-1684`) |

Mail subjects are locale-keyed with an `nl` fallback (`_SUBJECTS` `:707-726`, `_subject_for` `:729-733`); the admin-validated subject is `"[Nestor Pulse] Klant heeft gevalideerd — {client}"` (`:701`).

### 06.8.5 `ai_router`, prefix `/intakes` (`app/api/ai_routes.py:55`), list only

Each handler depends on `Identity` only, creates the `skill_runs` row synchronously through `_dispatch_skill_run` (`:58-77`), then schedules a `BackgroundTasks` job. Every POST returns 202 `{"skill_run_id", "status": "running"}`. Errors: 404 "Intake not found" on `IntakeNotInScopeError` (`:73`), 403 "No space — not authorized" on `PermissionError` (`:76`). No request model carries a tenant field (`:16-18`).

| Method | Path | Skill written to `skill_runs.skill` | Model knob | Cite |
|---|---|---|---|---|
| POST | `/intakes/{intake_id}/skills/apply` | `apply-intake-skill` | `model_apply_intake` | `:80-96` |
| POST | `/intakes/{intake_id}/skills/context-pack` | `context-pack` | `model_context_pack` | `:99-115` |
| POST | `/intakes/{intake_id}/skills/structure-answers` | `structure-answers` | `model_structure_answers` | `:118-132` |
| POST | `/intakes/{intake_id}/skills/extract-insights` | `extract-insights` | `model_extract_insights` | `:135-149` |
| POST | `/intakes/{intake_id}/embeddings` | `generate-embeddings` | `model_embeddings` | `:152-166` |
| POST | `/intakes/{intake_id}/sources/{source_id}/transcribe` | `transcribe-audio` | `model_transcription` | `:169-187` |
| GET | `/intakes/{intake_id}/search?q=` | none (sync inline, returns `{"results": [...]}`) | `model_embeddings` | `:190-204` |

Prompts, parsing, writes and review semantics: [see 07 — AI skills](07-ai-skills.md).

### 06.8.6 `storage_router`, prefix `/intakes` (`app/api/storage_routes.py:63`)

| Method | Path | Role | Body | Response | Side effects | Errors, in gate order |
|---|---|---|---|---|---|---|
| POST | `/intakes/{intake_id}/storage/uploads` 201 (`:135`) | any | multipart `file` and form `category` (`:140-141`) | `UploadedFileMeta{path, filename, size, uploaded_at, mime_type}` (`:69-77`) | key from `build_object_key(space_id, intake_id, category, filename)` (`:194`); `category == "audio"` inserts an `intake_sources` row `{kind:"audio", storage_path, file_name, language:None}` before the upload, superadmin via `create_in_space` (`:201-215`); `gcs.upload_object` (`:219`) | 404 malformed non-UUID id (`:103-115,159`); 422 "Unknown storage category" (`:162-166`); 415 "Unsupported file type" (`:171-175`); 413 "File exceeds the 25 MB limit" via an authoritative `read(_MAX_BYTES + 1)` (`:179-184`); 404 "Intake not found" (`:187-189`) |
| GET | `/intakes/{intake_id}/storage/signed-url?path=&expires_in=300` (`:230`) | any | none | `SignedUrlView{url, expires_in}` with the clamped effective TTL (`:79-84,269-270`) | `gcs.signed_download_url(path, ttl, filename=_filename_from_key(path))` (`:261-266`) | 404 malformed id (`:250`); 404 intake (`:252-254`); 404 "Object not found" unless `path` starts with `{space_id}/{intake_id}/` (`:256-259`) |
| DELETE | `/intakes/{intake_id}/storage/objects` (`:273`) | any | `DeleteObjectsBody{paths}` (`:86-90`) | `DeleteResult{removed}` (`:92-96`) | per key `gcs.delete_object` (idempotent) and `delete_by_storage_path` in the same transaction (`:305-310`) | 404 malformed; 404 intake (`:293-295`); all-or-nothing prefix assert, 404 "Object not found" (`:300-302`) |

`_MAX_BYTES = 25 * 1024 * 1024` (`:66`). `_filename_from_key` strips the 36-character uuid4 and hyphen prefix (`:118-132`).

### 06.8.7 `research_router`, prefix `/intakes` (`app/api/research_routes.py:110`), list only

`_superadmin_gate` turns any non-superadmin into 404 "Intake not found", never 403, and is declared before `get_tenant_repo` so a null-space user also sees 404 (`:153-168`).

| Method | Path | Role | Response | Cite |
|---|---|---|---|---|
| GET | `/intakes/research/runs/{run_id}/locate` | superadmin | `{"intake_id", "research_run_id"}` | `:190` |
| POST | `/intakes/{intake_id}/research` 202 | any, no superadmin gate | `{"research_run_id", "status": "queued"}` or the attempt-cap response `{"research_run_id": null, "status": "needs_investigation", "attempts"}` | `:248` |
| POST | `/intakes/{intake_id}/research/resume` 202 | superadmin | `{"research_run_id", "status": "queued"}` | `:383` |
| POST | `/intakes/{intake_id}/research/cancel` 202 | superadmin | `{"research_run_id", "status"}` as reported by the engine | `:527` |
| GET | `/intakes/{intake_id}/research/{run_id}/bundle-url` | superadmin | `{"url", "expires_in"}` | `:732` |
| POST | `/intakes/{intake_id}/research/{run_id}/verify-chain` | superadmin | `{"chain_status"}` | `:792` |
| GET | `/intakes/{intake_id}/research/{run_id}/verification` | superadmin | engine JSON verbatim | `:876` |
| GET | `/intakes/{intake_id}/research/sources/{source_id}` | superadmin | engine JSON verbatim | `:931` |
| GET | `/intakes/{intake_id}/research/{run_id}/audit/{audit_id}` | superadmin | engine JSON verbatim | `:975` |
| GET | `/intakes/{intake_id}/research/{run_id}/events?after_seq=0&limit=500` | superadmin | engine `RunEventPage` verbatim | `:1028` |
| GET | `/intakes/{intake_id}/research/stream` | any | `text/event-stream` (06.11) | `:1148` |

Constants: `_RESEARCH_TRANSITIONS = {"decomposed": "in_research"}` (`:121`), `_RETRYABLE_RUN_STATUSES = {"failed", "cancelled", "needs_input"}` with `parked` deliberately excluded (`:132-135`), `_MAX_ATTEMPTS = 3` (`:139`). Trigger rules, the poll driver, bundles and delivery: [see 08 — The research seam](08-research-seam.md).

## 06.9 The intake status machine as implemented

The enum `nestor.intake_status` holds `draft, submitted, reviewed, validated_by_client, decomposed, in_research, delivered, archived` (`app/db/models/intake.py:37-49`). The transitions the backend actually performs are:

| From | To | Verb or trigger | Who | Guard | Cite |
|---|---|---|---|---|---|
| (insert) | `draft` | `POST /intakes` | any | DB `server_default` | `intake_routes.py:456-457` |
| `draft` | `submitted` | `POST /{id}/submit` | any | `_SUBMIT_TRANSITIONS` | `:1238-1241` |
| `submitted` | `reviewed` | `POST /{id}/review` | any | `_REVIEW_TRANSITIONS` | `:1242-1244` |
| `reviewed` | `validated_by_client` | `POST /{id}/submit` | any | `_SUBMIT_TRANSITIONS`; fires the `admin_validated` mail | `:1240,1307-1314` |
| any, in practice `validated_by_client` | `decomposed` | context-pack background task; not a verb, no from-status guard | whoever can dispatch the skill | also writes `context_pack_artifact_id` | `app/ai/skills/context_pack.py:171-173` |
| `decomposed` | `in_research` | `POST /{id}/research` | any | `_RESEARCH_TRANSITIONS`; attempt cap; empty-brief 422 | `research_routes.py:121,277-306` |
| `in_research` | `in_research` (re-trigger) | `POST /{id}/research` | any | latest run in `{failed, cancelled, needs_input}`, else 409 | `:135,294-303` |
| `in_research` | `delivered` | `POST /{id}/deliver` | any | `_DELIVER_TRANSITIONS`, the sole path; an engine `completed` never auto-delivers | `intake_routes.py:1245-1249` |
| `delivered` | `delivered` | `POST /{id}/report/replace` | any | status untouched | `:1596,1614-1618` |

Any status not in the relevant map yields 409 (`:1232-1237`). `IntakePatch` has no status field. Resume and cancel of research do not touch intake status (`research_routes.py:497,560-565`). Nothing in the backend writes `archived`. The legacy Postgres function `nestor.submit_intake` still exists from migration 0004 but the endpoints do not call it; the post-`decomposed` bump triggers of the legacy schema were never ported and their names are forbidden tokens in the scope guard (`0004_triggers.py:58-67`, `scripts/ci_no_run_research.sh:72`). Chapter 04 holds the state diagram and the frontend phase machine that sits on top of this.

## 06.10 The `CodedError` contract

`app/api/errors.py` defines four codes: `INVALID_LOCALE` (`:52`), `INTAKE_NOT_FOUND` (`:54`), `RECIPIENT_INVALID` (`:56`), `MAIL_SEND_FAILED` (`:58`), collected in `USER_FACING_CODES` (`:62-69`). `CodedError(status_code, code, detail)` stringifies as `"{code}: {detail}"` (`:72-89`). The app-level handler emits `{"detail", "code"}` (`app/main.py:177-186`), which lets the frontend map a code to a translated message instead of showing raw English. The rule in the file is never to attach a code to an internal 4xx or 5xx (`errors.py:30-34`). Only `INVALID_LOCALE` is raised anywhere (`me_routes.py:356`, `admin_routes.py:428`); the other three are defined but unused (06.19).

## 06.11 Server-sent event streams

Both streams share one design: the handler is `async def`, every DB read is a short transaction on a threadpool, the client gets a snapshot at connect and then a frame only when the view changes, a comment line keeps the connection alive, and the stream closes itself on a terminal status, a client disconnect, or a hard cap. No state lives in process memory, so any Cloud Run instance can serve a reconnecting client (see 17 · 08). Cloud Run's request timeout was raised to 900 s for this (chapter 13).

| Knob | Skill-run stream | Research stream |
|---|---|---|
| Path | `GET /intakes/{id}/skill-runs/stream` (`intake_routes.py:1136`) | `GET /intakes/{id}/research/stream` (`research_routes.py:1148`) |
| Tick | `TICK_SECONDS = 2.0` (`:1118`) | `2.0` (`:1128`) |
| Heartbeat | `HEARTBEAT_SECONDS = 15.0`, sent as `: ping\n\n` (`:1119,1193-1195`) | `15.0` (`:1129`) |
| Cap | `MAX_STREAM_SECONDS = 600` (`:1120`) | `600` (`:1130`) |
| Terminal set | `{"succeeded", "failed"}` (`:1122`) | `RESEARCH_TERMINAL = {"completed", "completed_degraded", "failed", "cancelled", "parked"}` (`app/research/run_status.py:60`); `parked` is terminal for the stream only (`research_routes.py:30-36`) |
| Headers | `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no` (`:1124-1128`) | same (`:1136-1140`) |
| Frame | `data: {json}\n\n`; `data: null` when no run exists (`:1131-1133`) | same shape rule |
| Frame body | `read_latest_run_dict`: `{id, status, created_at, applied_at, completed_at}` (`stream_session.py:63-90`) | `read_latest_research_run_dict`: `{id, status, current_stage, stage_detail, cost_usd_total, started_at, completed_at, error_message, chain_status, chain_broken_at, bundle_key, event_seq}` (`stream_session.py:93-155`) |
| Pre-stream errors | 403 null-space, 404 out of scope (`:1162-1165`) | same (`:1174-1177`) |

The research stream is a bridge, not a direct channel: the poll driver mirrors engine metrics into `research_runs` every three seconds and the stream re-reads that row every two seconds; a moving `event_seq` cursor is by itself a new frame (`app/research/run_task.py:315-323`). The event log itself is fetched through the separate `/events` proxy.

## 06.12 Mail

**Transport.** `app/mail/resend.py::send(to, subject, html)` posts to `https://api.resend.com/emails` with a bearer read from `RESEND_API_KEY` at call time, `timeout=15.0`, `raise_for_status()`, and returns the Resend id or `""` (`resend.py:39-69`). The sender is `Nestor Pulse <nestor@agenic.be>` (`resend.py:30`). The client is blocking on purpose (`:16-18`).

**Render.** Jinja2 with `FileSystemLoader(templates/)` and autoescape for `html` and `j2` (`app/mail/render.py:36-39`). `_localized_template(name, locale)` loads `{locale}/{name}.html.j2` and falls back to `nl/` on `TemplateNotFound` (`:42-56`). The base layout `_base.html.j2` renders the logo only when `app_base_url` is set (`_base.html.j2:1-6,25`).

| Template | Locales | Subject | Intent and CTA | Cite |
|---|---|---|---|---|
| `validation.html.j2` | nl, fr, en | `_SUBJECTS[locale]["validation"]` or `["reminder"]` | validation request, reminder branch on `is_reminder`; CTA `/intake/{id}` | `nl/validation.html.j2:10-21` |
| `intake.html.j2` | nl, fr, en | `["intake"]` | intake-form invite, draft only; CTA `/intake/{id}` | `nl/intake.html.j2:9-15` |
| `results.html.j2` | nl, fr, en | `["results"]` | results ready; CTA `/intake/{id}/results`, or `/report` from deliver and replace | `nl/results.html.j2:9-21` |
| `invite.html.j2` | nl, fr, en | `_INVITE_SUBJECTS[locale]` | set password; the only template whose CTA is a Firebase action link | `nl/invite.html.j2:1-16` |
| `research_complete.html.j2` | nl, fr, en | hardcoded "Je onderzoek is klaar" (`run_task.py:854`) | duration, cost, admin CTA | `nl/research_complete.html.j2:9-15` |
| `research_failed.html.j2` | nl, fr, en | "Je onderzoek is mislukt" (`run_task.py:944,962`) | error summary, admin CTA | `nl/research_failed.html.j2:9-12` |
| `research_parked.html.j2` | nl, fr, en | "Je onderzoek staat op pauze" (`run_task.py:921`) | park reason, resume CTA | `nl/research_parked.html.j2:12-16` |
| `admin_validated.html.j2` | top level only, no locale | "[Nestor Pulse] Klant heeft gevalideerd — {client}" (`intake_routes.py:701`) | ops notice with `Status: validated_by_client`, admin CTA | `admin_validated.html.j2:8-12` |

**Recipient and locale resolution.**

- Intake mails accept only membership ids (`MailRecipients` with `extra="forbid"`, `intake_routes.py:275-288`). `_resolve_recipient_locales` turns them into `(email, locale)` pairs from active members of the intake's own space; locale is `membership.locale`, then `organization.default_locale`, then `nl` (`:796-853`). One render and one send per distinct locale group (`:1057-1086`). Any id that is not active or has no email fails the whole batch with 422 (`:847-853`). `intake.client_name or "team"` is passed as both `first_name` and `project_title` (`:1035,1063-1064`).
- Invite mail: locale is the target space's `default_locale` or `nl` (`admin_routes.py:339-340`).
- `admin_validated`: single recipient `nestor_admin_email`; unset means log and skip, never raise (`intake_routes.py:1332-1339`); a mail failure never fails the client's submit (`:1308-1314`).
- Research mails: recipient is the triggering superadmin's `acting_email` only (`run_task.py:821`), rendered with the default `locale="nl"` and Dutch subjects (`:845-851,913-918,936-941`).

**The no-token rule.** Every non-invite CTA is an intake-id or admin route, never a bearer token (`render.py:31-35`, `intake_routes.py:1024-1028`). With `APP_BASE_URL` unset a send is refused with `{"success": false}` (`:1029-1033,1482-1486`). Timestamps and the `mail.sent` audit row are written only after a 2xx from Resend (`:1052-1056,1091-1102`). This is the mechanism behind 17 · P-04 and 17 · 10.

## 06.13 Storage

| Item | Value | Cite |
|---|---|---|
| Credentials | `google.auth.default()`; V4 signing through IAM signBlob with `service_account_email` and `access_token`; no JSON key | `app/storage/gcs.py:11-16,111-119` |
| TTL | `_clamp_ttl` into `[1, 900]` seconds; default `300` | `gcs.py:42-53` |
| Download disposition | `attachment; filename="<sanitized>"`, `version="v4"`, `method="GET"` | `gcs.py:110-121` |
| Bucket | `Settings.storage_bucket`; `RuntimeError` if unset | `gcs.py:56-70` |
| Key scheme | `{space_id}/{intake_id}/{category}/{uuid4}-{sanitized filename}` | `app/storage/keys.py:90-104` |
| Categories | `attachments`, `audio`, `artifacts`, `reports` | `keys.py:35` |
| Extension allowlist (16) | `.pdf .docx .xlsx .pptx .txt .md .csv .png .jpg .jpeg .webp .m4a .mp3 .wav .webm .ogg`, checked on the declared filename, not sniffed MIME | `keys.py:39-58` |
| Filename sanitiser | NFD and strip combining marks, dashes to `-`, whitespace to `_`, drop anything outside `[A-Za-z0-9._-]`, collapse, trim, cap at 200, fallback `file` | `keys.py:61-87` |
| Size limit | 25 MB, enforced by reading one byte past the limit | `storage_routes.py:66,179-184` |
| Gate order on upload | id shape 404, category 422, extension 415, size 413, intake scope 404 | `storage_routes.py:159-189` |
| Prefix wall | signed-url and delete refuse any key not under `{space_id}/{intake_id}/` with 404 | `storage_routes.py:256-259,300-302` |

Who writes which category: uploads take the client's choice among the four (`storage_routes.py:162`); report staging must sit under `reports/` (`intake_routes.py:1430`); research bundles land under `artifacts/` (`run_task.py:620-625`). The key is authored server-side and the object is namespaced by space, which is how DOC-01 and DOC-02 are met without the browser ever touching the bucket (see 17 · 09).

## 06.14 The four CI guard scripts

Each script in `scripts/` exits 0 when clean, 1 on an offender and 2 on a bad directory; the exit code is the gate.

| Script | Scans | Pattern | Why | Test |
|---|---|---|---|---|
| `ci_no_permissive_rls.sh` (`:38,44`) | `app/db/alembic/versions/*.py` | `USING (true)` or `WITH CHECK (true)` with flexible whitespace | QA-02: the inherited flaw #1 was exactly this policy | `tests/test_ci_guard.py` plants a temp migration containing `USING (true)` and expects non-zero (`:63-81`) |
| `ci_no_raw_db_access.sh` (`:48,63`) | `app/` excluding `db/`, `main.py`, `session.py` | `get_engine(`, `get_superadmin_engine(`, `sessionmaker(`, `create_engine(`, bare `Session(` | Phase 4 D-03: only `app/db/` builds engines and sessions; `main.py` (readyz, dispose) and `auth/session.py` (login sync) are the sanctioned exceptions (`:50-58`) | `tests/test_ci_guard_raw_db.py` |
| `ci_no_run_research.sh` (`:72,80,96-97`) | `app/` and `<repo>/frontend/src/` for `*.py`, `*.ts`, `*.tsx` | `invoke(...run-research/run_research/tribunal)`, `/run-research`, `run_research(`, `.run_research`, the three legacy trigger names, python imports of `*tribunal`, `SERPAPI_API_KEY`, `serpapi.com`, serpapi imports, `google-search-results`; an ALLOW list admits only imports of `app.research.tribunal_client` | INTAKE-05 scope ceiling, narrowed in v1.1 so only the HTTP seam client may reach Tribunal (`:46-55,74-80`); see 17 · P-13 | `tests/test_scope_guard_run_research.py` plants `supabase.functions.invoke("run-research", …)` in a temp `.ts` (`:69-86`) |
| `ci_no_sa_json_key.sh` (`:49,52-59`) | every file under `app/`, comments stripped | `from_service_account_file`, `service_account.json`, `GOOGLE_APPLICATION_CREDENTIALS=...json` | Phase 9 decision: GCS and Identity Platform stay keyless via ADC | referenced from `gcs.py:14` |

Two further route-table tests sit beside these: `tests/test_scope_guard_ai.py` and `tests/test_no_run_research_route.py` walk the mounted `app.routes` and assert no path contains a forbidden token; see 06.19 for their relation to the research router.

## 06.15 The canonical intake template

The Pulse form is one shared questionnaire treated as product configuration, not tenant data (decision D-CANON, `app/intake_canonical.py:1-34`). Constants: `CANONICAL_TEMPLATE_ID = 00000000-0000-0000-0000-0000000000c1` (`:27`), `CANONICAL_TEMPLATE_NAME = "Nestor Pulse — Intake v1"` (`:28`), and `CANONICAL_TEMPLATE_SCHEMA` loaded once at import from `app/data/pulse_intake_v1.json` (`:33-34`).

It is **not seeded into the database**. `GET /intakes/templates` returns it in-memory to every authenticated caller regardless of space (`intake_routes.py:479-498`). The `intake_templates` table and the admin clone and edit endpoints remain, but the fill flow no longer depends on them (`intake_canonical.py:9-11`). `scripts/seed_dev.py` seeds a separate one-field demo template with id ending `00d1`, not the canonical one (`seed_dev.py:48-74`).

Measured shape of `pulse_intake_v1.json` (35,226 bytes):

| Property | Value |
|---|---|
| Top-level keys | `title, submit, version, subtitle, sections, product_slug, save_as_you_go, schema_version, estimated_minutes, field_types_reference` |
| `version` / `schema_version` / `product_slug` | `1` / `"1.0"` / `"pulse"` |
| `save_as_you_go` / `estimated_minutes` | `true` / `30` |
| Sections (14, in order, field count) | `nda(2), client_info(6), research_goal(1), research_questions(1), extra_questions_nestor(1), audience(1), competitors(1), stakeholders(1), sensitivities(1), scope_constraints(4), output_format(3), success_metrics(1), materials(2), strategic_perspective(4)` |
| Fields | 29 total, 13 required, 3 with options |
| Field types | `longtext 11, text 5, list 3, radio 3, download 1, file 1, files 1, email 1, tel 1, proposal_list 1, date 1` |
| Section keys | `id, title, fields, soft_gate, description` |
| Locales | every `title`, `label` and `help` is a `{nl, fr, en}` object; 103 occurrences of each key |
| NDA download | `storage_bucket: "nestor-uploads"`, `storage_path: "templates/NDA/Agenic-Nestor-Overeenkomst.pdf"` |

The `proposal_list` field type carries the AI-suggested questions the client ticks; its review semantics are in chapter 07.

## 06.16 Packaging: Dockerfile, pyproject, alembic.ini

| File | Facts | Cite |
|---|---|---|
| `Dockerfile` | two stages, both `python:3.12-slim`; `uv` copied from `ghcr.io/astral-sh/uv:latest`; copies `pyproject.toml`, `uv.lock*`, `README.md`, `app/`, `alembic.ini`, `scripts/`; `uv pip install --system .`; build-time import smoke of `fastapi, uvicorn, sqlalchemy, alembic, pg8000, google.cloud.sql.connector, pgvector, pydantic_settings, app.main`; `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080`; `CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}` as a single process | `Dockerfile:26,29,49-62,68,84-93` |
| Migration Job | same image, args overridden to `alembic upgrade head`; seed Jobs run `python -m scripts.<name>` | `Dockerfile:6-9,56-59,90-92` |
| `uv.lock` | not present in `backend/`; only the COPY glob names it | `Dockerfile:49` |
| `pyproject.toml` | `nestor-intake-backend` 0.1.0, `requires-python = ">=3.12"`, `hatchling`, `packages = ["app"]` | `pyproject.toml:6,94-101` |
| Runtime deps | `sqlalchemy>=2.0`, `alembic==1.18.4`, `pgvector==0.4.2`, `cloud-sql-python-connector[pg8000]==1.20.2`, `pg8000>=1.31,<1.32`, `fastapi>=0.137`, `uvicorn[standard]>=0.49`, `pydantic-settings>=2.14`, `firebase-admin>=7.4,<8`, `google-cloud-secret-manager>=2.20,<3`, `anthropic==0.113.0`, `openai==2.44.0`, `google-cloud-storage>=3,<4`, `python-multipart>=0.0.9`, `google-auth>=2,<3`, `jinja2>=3.1,<4`, `httpx>=0.27,<1` | `pyproject.toml:7-59` |
| Dev deps | `pytest`, `pytest-asyncio`, `testcontainers[postgresql]`, `httpx`; pytest `asyncio_mode="auto"`, `testpaths=["tests"]`, marker `integration` | `pyproject.toml:61-92` |
| `alembic.ini` | `script_location = %(here)s/app/db/alembic`, `file_template = %%(rev)s_%%(slug)s`, `timezone = UTC`, `sqlalchemy.url` empty by design so `env.py` resolves it | `alembic.ini:15-24` |

`env.py` (`app/db/alembic/env.py`) prefers a pre-set `sqlalchemy.url`, else `DATABASE_URL`, and uses the connector with `NullPool` only when no URL is set and `INSTANCE_CONNECTION_NAME` is (`env.py:43-50,70-115`). Migration lineage 0001 to 0013 is chapter 05's table.

## 06.17 The test suite

59 files under `tests/` with roughly 420 `def test_` functions before parametrisation. `integration` is the only marker in wide use (60 occurrences across 36 files); one conditional `skip` exists in `test_mail_locale.py:208`.

| Theme | Files (test count) |
|---|---|
| Platform, health, config | `test_health(3)`, `test_config_cors(4)`, `test_engine_factory(4)`, `test_error_codes(3)`, `test_migration_env(5)`, `test_grant_migration(8)` |
| Auth | `test_auth_dependency(6)`, `test_auth_session(5)`, `test_admin_users(7)`, `test_no_bearer_routes(2)` |
| Schema, RLS, DB layer | `test_schema_shape(6)`, `test_schema_shape_locale(3)`, `test_rls_isolation(9)`, `test_tenant_repository(4)`, `test_seed_and_triggers(5)`, `test_audit(4)`, `test_research_runs_migration(18)` |
| CI guards | `test_ci_guard(2)`, `test_ci_guard_raw_db(2)`, `test_scope_guard_run_research(2)`, `test_scope_guard_ai(3)`, `test_no_run_research_route(2)` |
| Admin, me, intake routes | `test_admin_routes(13)`, `test_me_routes(8)`, `test_intake_routes(16)`, `test_intake_cross_tenant(13)`, `test_intake_validate_mail(2)`, `test_skill_run_full(2)`, `test_sse_stream(4)` |
| AI | `test_ai_apply_skill(3)`, `test_ai_context_pack(1)`, `test_ai_cross_tenant(2)`, `test_ai_embeddings(1)`, `test_ai_search_cross_tenant(1)`, `test_ai_search_explain(1)`, `test_ai_session_release(1)`, `test_ai_status_contract(2)`, `test_ai_structure_extract(2)`, `test_ai_transcribe(2)` |
| Storage | `test_storage_cross_tenant(5)`, `test_storage_delete(1)`, `test_storage_signed_url(3)`, `test_storage_upload(5)` |
| Mail | `test_mail_denial(2)`, `test_mail_endpoints(13)`, `test_mail_locale(17)`, `test_mail_render(19)`, `test_report_delivery(9)` |
| Research seam | `test_research_brief(26)`, `test_research_brief_input(11)`, `test_research_bundle(9)`, `test_research_bundle_download(4)`, `test_research_cross_tenant(35)`, `test_research_event_cursor(14)`, `test_research_events_proxy(20)`, `test_research_routes(10)`, `test_research_run_task(27)`, `test_tribunal_client(5)`, `test_tribunal_seam_denial(4)` |

**conftest strategy** (`tests/conftest.py`). The suite runs against a real Postgres with pgvector, never a mock database. `pg_container` yields nothing when `DATABASE_URL` is set and otherwise starts a testcontainers `pgvector/pgvector:pg16` (`:51,86-122`); it skips, never errors, when testcontainers or Docker is missing. The `engine` fixture bootstraps the extensions, creates a non-superuser `nestor_owner` (`CREATEDB CREATEROLE NOSUPERUSER`) and makes it the database owner, creates `app_superadmin LOGIN`, grants `app_superadmin TO nestor_owner WITH ADMIN OPTION`, then runs `alembic upgrade head` **as the owner** so `FORCE ROW LEVEL SECURITY` binds the same role the tests use (`:64-65,194-217,275-317`). Running as a superuser would silently void every RLS assertion. Fixtures `set_space` (`:324`) and `two_spaces` (`:352`) drive the denial suites; `fake_anthropic` (`:446`), `fake_openai` (`:571`), `fake_gcs` (`:676`), `fake_resend` (`:770`) and `fake_tribunal_client` (`:829`) replace every external seam so no test spends money.

**The Cloud Build gate** (`<repo>/cloudbuild.test.yaml`, the only Cloud Build file at the repo root). Step 1 starts `pgvector/pgvector:pg16` on the `cloudbuild` network with user, password and database all `test` (`:26-39`); step 2 polls `pg_isready` up to 60 times at 2 s (`:43-59`); step 3 runs in `python:3.12-slim` with `DATABASE_URL=postgresql+pg8000://test:test@nestor-test-pg:5432/test`, installs `uv`, then `uv pip install --system --no-cache-dir -e '.[dev]'` and `python -m pytest tests -m integration -v` (`:66-86`). Timeout 1200 s, logging `CLOUD_LOGGING_ONLY` (`:89-92`). The header says a required-status-check trigger is deferred to the user (`:18-20`). Chapter 15 places this gate among the others.

## 06.18 Why it is built this way

**Context.** The system this replaces was a third-party Lovable build on Supabase with five documented security flaws (`.planning/codebase/CONCERNS.md` #1 to #5): constant-true RLS on every intake table, an anonymous key with write grants on eleven tables, never-expiring bearer links as the client access model, a client-side-only admin guard, and a hardcoded email allowlist in the login page. It also had zero automated tests. The rest of this section is a set of short context, options, decision, consequence blocks; the full rulings are in chapter 17.

- **The API is the only writer; the browser never touches the database.** Options were to keep PostgREST behind better policies, or to put a mediating service in front. Flaw #2 made the first unsafe: any policy fix could be undone by a grant. Decision: FastAPI on Cloud Run mediates everything (API-01, 17 · P-05). Consequence: every feature is an endpoint, and the frontend's data layer had to be rebuilt behind `lib/api/*` (chapter 12).
- **Tenancy is enforced in three layers, and the repository layer comes first.** Options were RLS alone, API filtering alone, or both. RLS alone was exactly what failed. Decision (17 · 04-02, 17 · P-05, 17 · P-11): a repository that cannot omit the filter, a transaction-local GUC that RLS re-checks, and a CI denial suite that proves it before any feature endpoint exists. Consequence: `TenantRepository` has no `space_id` parameter by construction, and the retrospective credits this ordering with the bug class never recurring.
- **Superadmin bypass is a login role, not `BYPASSRLS`.** Cloud SQL does not grant `BYPASSRLS`. Options were a second app role with its own policies, or turning RLS off for admin queries. Decision (17 · 01-03): the `app_superadmin` role and an OR'd `current_user` policy, reached only through a separate engine with a Secret Manager password. Consequence: two engines, and the `create_in_space` GUC trick for `SECURITY DEFINER` triggers.
- **IAM database authentication, no password anywhere for the tenant path.** Decision (17 · 02, D-03/D-09): the runtime service account logs in through the connector. Consequence: the only DB secret is the superadmin password, and it lives in Secret Manager, not in `Settings`.
- **Token verification on every request, with `check_revoked`.** Options were to trust a session cookie, or to verify the ID token each call. Decision (17 · 03, AUTH-02): verify each call; claims are server-set and never accepted from the client. AUTH-04 added `check_revoked=True` at one extra round trip per request so deactivation bites immediately (17 · 05).
- **Login sync is a separate anonymous route.** A new user has no `role` claim, so the shared dependency would refuse them. Decision: `/auth/session` verifies its own bearer and writes claims from the membership table, never creating a user (Phase 5 D-02). Consequence: the frontend must force a token refresh after sync.
- **Never-expiring links are gone; mail is notification-only.** Flaw #3. Decision (17 · P-04, 17 · 10): recipients are membership ids resolved server-side, every CTA is an authenticated route, and the only action link in any mail is the Firebase set-password link. Consequence: there is no way to mail a token to a stranger, and `APP_BASE_URL` unset refuses to send.
- **Long LLM calls release the connection.** With a pool of five per instance, a 120 s call would exhaust it. Decision (17 · 07 D-05, AI-06): READ, CALL, WRITE in separate short sessions. Consequence: every skill returns plain DTOs from its read step, and the startup sweep exists because background tasks can die with the instance.
- **Progress over DB-backed SSE, not websockets or in-memory state.** Supabase Realtime had to be replaced. Decision (17 · 08): the stream re-reads the row each tick so any instance can serve it; Cloud Run timeout raised to 900 s. Consequence: a 2 s tick, a 15 s heartbeat and a 10-minute cap, with reconnect left to the client.
- **Signed URLs through signBlob, server-authored keys.** Decision (17 · 09): no service-account JSON anywhere, TTL clamped to 15 minutes, keys namespaced by space and intake, a prefix wall on every read and delete. Consequence: the `ci_no_sa_json_key.sh` guard and a 25 MB cap enforced by reading one byte past it.
- **The scope ceiling and the sanctioned seam.** v1.0 forbade any path to `run-research` (17 · P-13, INTAKE-05). v1.1 extended the flow through Tribunal but kept the legacy engine barred by narrowing the guard's ALLOW list to `app.research.tribunal_client` (17 · M-03). Consequence: the seam is one HTTP client, no shared DB session, and the guard still fails on any SerpAPI or `run_research` token.
- **Model ids as configuration.** Decision (17 · 07 D-06): six `MODEL_*` env knobs with coded defaults, and the resolved id persisted on each `skill_runs` row. Consequence: the deployed model can differ from the coded default without a code change, which is also why this chapter cannot state what runs live.
- **One canonical template served in-memory.** Decision D-CANON (chapter 17, Phase 6 quick tasks): the Pulse questionnaire is product configuration, so it ships in the image and is not seeded or per-space. Consequence: template admin endpoints remain but the fill flow ignores them.

## 06.19 Known gaps and traps

- **Three `CodedError` codes are defined but never raised.** `INTAKE_NOT_FOUND`, `RECIPIENT_INVALID` and `MAIL_SEND_FAILED` exist in `app/api/errors.py:54-58` but every corresponding failure is a plain `HTTPException` without a `code`. The frontend cannot translate those by code.
- **Research notification mails are Dutch only.** `run_task.py` renders `research_complete`, `research_failed` and `research_parked` with the default `locale="nl"` and hardcoded Dutch subjects (`run_task.py:845-851,913-918,936-941`) even though `fr/` and `en/` templates exist. The recipient is the triggering superadmin, so the visible impact is small, but the locale resolution used by every intake mail is not applied here.
- **The context pack's section 12 is never appended.** The prompt tells the model section 12 (the verbatim research questions) "wordt automatisch toegevoegd" (`app/ai/prompts.py:228`), but the write stores the raw model output unchanged (`app/ai/skills/context_pack.py:163`); no code path appends it. Chapter 07 carries the detail.
- **Two route-table tests assert what the research router contradicts.** `tests/test_scope_guard_ai.py:63-71,141-161` and `tests/test_no_run_research_route.py:44,61-79` assert that no mounted route path contains the token `research`, while `research_router` mounts eleven paths containing exactly that literal (`app/api/research_routes.py:190,248,383,527,732,792,876,931,975,1028,1148`, included at `app/main.py:152`). Both tests `importorskip` `firebase_admin` or `app.main` and were last changed in commits `953b1b3` and `bedf63b`, before the router existed; no `deselect` or `--ignore` for them exists in `pyproject.toml`. ⚠ Whether they currently fail or skip in CI was not determined here. Both facts are recorded; this chapter does not resolve them.
- **The Cloud Build gate runs only `-m integration`.** `cloudbuild.test.yaml:86` selects the integration marker, so the non-integration unit tests in the suite are not executed by that config. What the local runs cover versus the gate is chapter 15's subject.
- **`env.py` says 14 tables; there are 18.** The comment at `app/db/alembic/env.py:36` is stale; `app/db/models/__init__.py:1-17` registers 18.
- **The coded model defaults may not be what runs.** `claude-sonnet-4-5` and `claude-sonnet-4-6` are the defaults in `config.py:123-126`; the live `nestor-api` revision can override them through `MODEL_*` env vars. Not determined from the code. Chapter 11 and chapter 13 hold the live inventory.
- **`/healthz` on the live service.** ⚠ Observed once during the 2026-08-31 deploy: `/healthz` returned 404 from the Google upstream while `/readyz` returned 200. Not explained by the code, which registers both. Smoke on `/readyz`.
- **The superadmin engine has no URL mode in `base.py`.** Local and test runs must supply their own superadmin engine; how `conftest.py` does so beyond the `_ensure_app_superadmin` bootstrap was not fully traced (`base.py:200-219`, `conftest.py:194-217,302`).
- **`admin_validated` mail is untranslated by design.** It has no locale directory and is aimed at the operator address only (`render.py:132-149`).
- **`decomposed` is written without a from-status guard.** The context-pack task sets `status="decomposed"` unconditionally (`context_pack.py:171-173`), so regenerating a pack on an intake that is already `in_research` or `delivered` would move it backwards. ⛔ Not observed; recorded from the code.
- **The 422 for a bad delivery recipient fires after the delivery commit.** In `POST /deliver` the status change and artifact row are committed in transaction 1; a bad recipient id in the mail step raises 422 afterwards (`intake_routes.py:1534-1536`), so the caller sees an error on an intake that is already `delivered`.
- **`skill_runs.status` and `research_runs.status` are strings, not enums.** The literal vocabulary is enforced by code and tests only (`models/skill_run.py:21-70`, `models/research_runs.py:17-23`).
- **`RESEND_API_KEY` rotation is a standing debt** recorded in the deploy memory of Phase 12; see chapter 14.

## 06.20 Where to look

| Path | Responsibility |
|---|---|
| `app/main.py` | app object, lifespan (Firebase init, orphan sweep, engine dispose), CORS, router mounting, `CodedError` handler, `/healthz`, `/readyz` |
| `app/core/config.py` | `Settings` (every env knob and default); no secrets by design |
| `app/core/firebase.py` | idempotent Admin SDK init via ADC |
| `app/auth/identity.py` | the frozen `Identity` dataclass |
| `app/auth/dependencies.py` | `get_current_identity`: token verification and the 401/403 split |
| `app/auth/session.py` | login sync: membership lookup and custom-claim write, `SyncResult` |
| `app/auth/admin_users.py` | Admin SDK wrapper: invite, set-password link, deactivate, reactivate, uid resolve |
| `app/db/base.py` | both engine factories, connector, pool args, Secret Manager password, checkin `RESET` |
| `app/db/rls.py` | `set_space_context` and the GUC key |
| `app/db/session.py` | per-request dependencies yielding repositories, `get_me_session`, `get_admin_session` |
| `app/db/repository.py` | `TenantRepository` and every entity subclass |
| `app/db/admin_repo.py` | unscoped superadmin repository, no delete |
| `app/db/ai_session.py` | `tenant_session`, `run_with_session_release`, `create_running_skill_run`, orphan sweep, `search_artifacts` |
| `app/db/stream_session.py` | dict-returning reads for the SSE streams and the brief |
| `app/db/audit.py` | `audit.log` and the event-type contract |
| `app/db/models/*` | the 18 tables (chapter 05) |
| `app/db/alembic/env.py`, `versions/0001..0013` | migration environment and lineage (chapter 05) |
| `app/api/auth_routes.py` | `/auth/session`, `protected_router` |
| `app/api/me_routes.py` | `/me`, `/me/locale`, locale resolution |
| `app/api/admin_routes.py` | users, spaces, templates, invite mail |
| `app/api/intake_routes.py` | intake CRUD, answers, skill-run reads, context pack, sources, members, mails, transitions, deliver, replace, report, skill-run SSE |
| `app/api/ai_routes.py` | skill dispatch and semantic search (chapter 07) |
| `app/api/storage_routes.py` | upload, signed URL, delete |
| `app/api/research_routes.py` | the Tribunal seam routes and the research SSE (chapter 08) |
| `app/api/errors.py` | `CodedError` and the four codes |
| `app/mail/resend.py`, `app/mail/render.py`, `app/mail/templates/**` | transport, Jinja2 rendering, eight templates across three locales |
| `app/storage/gcs.py`, `app/storage/keys.py` | signBlob signing, key scheme, categories, allowlist, sanitiser |
| `app/research/*` | seam client, brief, poll driver, bundle, status sets (chapter 08) |
| `app/ai/*` | clients, parsing, prompts, search, six skills (chapter 07) |
| `app/intake_canonical.py`, `app/data/pulse_intake_v1.json` | the canonical template |
| `scripts/ci_no_permissive_rls.sh`, `ci_no_raw_db_access.sh`, `ci_no_run_research.sh`, `ci_no_sa_json_key.sh` | the four CI guards |
| `scripts/seed_superadmin.py`, `scripts/seed_dev.py` | seed Jobs |
| `tests/conftest.py`, `tests/test_*.py` | the 59-file suite and its Postgres bootstrap |
| `Dockerfile`, `pyproject.toml`, `alembic.ini` | image, dependencies, migration config |
| `<repo>/cloudbuild.test.yaml` | the integration gate |

Related chapters: [03 — Architecture](03-architecture.md), [04 — Domain model and lifecycles](04-domain-model-and-lifecycles.md), [05 — Data model](05-data-model.md), [07 — AI skills](07-ai-skills.md), [08 — The research seam](08-research-seam.md), [13 — Infrastructure and deploy](13-infrastructure-and-deploy.md), [14 — Security and compliance](14-security-and-compliance.md), [15 — Quality and testing](15-quality-and-testing.md), [17 — Decision log](17-decision-log.md).
