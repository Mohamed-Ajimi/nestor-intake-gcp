"""Canonical intake template (product config, NOT per-tenant data) — D-CANON.

The Pulse intake form is ONE shared questionnaire, identical for every space — it is
product configuration, not tenant-owned data. So it is served from this in-repo asset
instead of per-space ``nestor.intake_templates`` rows. This removes the per-space copy +
"superadmin edits raw JSON" workflow: the read path (``GET /intakes/templates``) returns
this single canonical template to EVERY authenticated caller, regardless of space.

The ``intake_templates`` table and the Phase-5 admin clone/edit endpoints remain in place
for a possible future per-client-customization track, but the fill flow no longer depends
on them — there is exactly one form, defined here.

The schema JSON was recovered from the legacy Supabase template "Nestor Pulse — Intake v1"
(14 sections) and is the single source of truth; it is shipped inside the app package
(``app/data/pulse_intake_v1.json``) so the Cloud Run image serves it with no DB seed.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

# Fixed, deterministic id so the canonical template has a stable identity across requests
# and instances. The UI keys on this id; intake answers key on ``field_key`` (never on the
# template id), so a constant here is safe.
CANONICAL_TEMPLATE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
CANONICAL_TEMPLATE_NAME = "Nestor Pulse — Intake v1"

# Loaded once at import. The asset lives next to this module inside the app package, so it
# is present in the Cloud Run image (Dockerfile copies ``app/``) and resolvable via
# ``__file__`` whether run from the source tree or the installed package.
_SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "pulse_intake_v1.json"
CANONICAL_TEMPLATE_SCHEMA: dict = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
