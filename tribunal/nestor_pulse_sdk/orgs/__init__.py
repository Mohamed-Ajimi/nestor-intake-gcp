"""
nestor_pulse_sdk.orgs -- internal-seam org/project provisioning.

Phase 14 (SEAM-02). The user-facing bootstrap endpoint + first-login
provisioner (`ensure_org_for_user`) are retired; the surviving surface is:

  ensure_org      -- idempotent space->org get-or-create (org.id == space_id)
  ensure_project  -- idempotent one-project-per-space get-or-create
  router          -- FastAPI APIRouter for POST /api/orgs/ensure + /api/projects/ensure
"""

from nestor_pulse_sdk.orgs.provision import ensure_org, ensure_project
from nestor_pulse_sdk.orgs.api import router

__all__ = ["ensure_org", "ensure_project", "router"]
