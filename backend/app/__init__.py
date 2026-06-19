"""Nestor Intake (GCP re-platform) backend application package.

Phase 1 lands the database layer only (`app.db`). FastAPI app wiring arrives
in Phase 2; this package marker exists now so `import app.db.models` resolves
for the Alembic env and the test harness.
"""
