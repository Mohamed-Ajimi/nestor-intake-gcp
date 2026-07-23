# nestor-intake-gcp

Re-platform of the Nestor intake flow (originally Supabase) onto Google Cloud Platform. Covers everything **before** the research stage: intake frontend, Cloud SQL, Identity Platform auth, Cloud Run FastAPI backend, and GCS storage.

## Project layout

```
frontend/          React 19 + TanStack Router + shadcn (Vite, the intake UI)
backend/           FastAPI on Cloud Run (Python 3.12, partially built)
infra/             Terraform for GCP (Cloud SQL, Identity Platform, GCS, Cloud Run)
mock-backend/      Local Express mock server — stands in for FastAPI in dev
docs/              Backend map, DB functions, original edge-function source
```

## Running locally (mock mode)

Two workflows run the full local dev stack without any GCP credentials:

| Workflow | Command | URL |
|---|---|---|
| **Start application** | `cd frontend && npm run dev -- --port 5000 --host` | http://localhost:5000 |
| **Mock Backend** | `node mock-backend/server.js` | http://localhost:3001 |

`frontend/.env.local` sets `VITE_MOCK_AUTH=1` which bypasses Firebase and signs in automatically as a mock superadmin. All API calls go to the mock backend at port 3001.

### What works in mock mode
- Full admin UI: product picker, intakes list, users, spaces, templates, organizations
- Create / patch / transition intakes (state machine)
- Invite / deactivate / reactivate users
- Create / update spaces and templates
- User intake flow (`/intake`)

### What doesn't work in mock mode
- Real Firebase authentication
- File uploads (signed GCS URLs return a placeholder)
- Skill-run SSE streaming
- Research / decomposition (returns empty arrays)
- Supabase-backed Sales pages (inert without `VITE_SUPABASE_URL`)

## Running with real GCP

To connect to a real GCP backend, remove `VITE_MOCK_AUTH=1` from `frontend/.env.local` and set:

```
VITE_API_BASE_URL=https://your-cloud-run-url
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=...
VITE_FIREBASE_PROJECT_ID=...
```

The backend (`backend/`) is a FastAPI app deployable to Cloud Run. See `infra/DEPLOY-RUNBOOK.md` for Terraform provisioning steps.

## Stack

- **Frontend**: React 19, TanStack Router + Start, shadcn/ui, Vite 7, i18next (nl/fr/en)
- **Auth**: Firebase / GCP Identity Platform (client SDK + server token verification)
- **Backend**: FastAPI, SQLAlchemy 2, Alembic, Cloud SQL (Postgres), GCS, Secret Manager
- **Infra**: Terraform, Cloud Run, Cloud SQL, Identity Platform

## User preferences

- Keep the existing project structure — do not restructure or migrate it.
- Mock mode (`VITE_MOCK_AUTH=1`) is the default for local dev on Replit.
