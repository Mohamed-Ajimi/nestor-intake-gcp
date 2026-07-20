"""Projects API package (D-06 long-lived client engagements).

Public surface:
  - router: FastAPI APIRouter mounted at /api/projects (create + list + detail).

The runs endpoints 404 on an unknown project_id; this is where projects are
actually created, so real-mode operation has a project to hang runs off of.
"""

from nestor_pulse_sdk.projects.api import router

__all__ = ["router"]
