"""
nestor_pulse_sdk.orgs — per-user org provisioning and bootstrap endpoint.

Plan: 01-17 Task 2 (D-16).

Public API:
  ensure_org_for_user  — idempotent first-login org + user + project provisioner
  router               — FastAPI APIRouter for POST /api/orgs/bootstrap
"""

from nestor_pulse_sdk.orgs.provision import ensure_org_for_user
from nestor_pulse_sdk.orgs.api import router

__all__ = ["ensure_org_for_user", "router"]
