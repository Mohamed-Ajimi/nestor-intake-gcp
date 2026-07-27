"""Re-export every model class so callers can `from ...models import X`.

Importing this module also registers every table in `Base.metadata`,
which the Alembic env.py relies on (`import nestor_pulse_sdk.db.models`
makes autogenerate aware of the full schema).
"""

from nestor_pulse_sdk.db.models.org import Org
from nestor_pulse_sdk.db.models.user import User
from nestor_pulse_sdk.db.models.project import Project
from nestor_pulse_sdk.db.models.run import Run
from nestor_pulse_sdk.db.models.output import Output
from nestor_pulse_sdk.db.models.source import Source
from nestor_pulse_sdk.db.models.claim import Claim
from nestor_pulse_sdk.db.models.claim_source import ClaimSource
from nestor_pulse_sdk.db.models.research_gap import ResearchGap
from nestor_pulse_sdk.db.models.audit_log import AuditLog
from nestor_pulse_sdk.db.models.verification_verdict import VerificationVerdict
from nestor_pulse_sdk.db.models.run_event import RunEvent

__all__ = [
    "Org",
    "User",
    "Project",
    "Run",
    "Output",
    "Source",
    "Claim",
    "ClaimSource",
    "ResearchGap",
    "AuditLog",
    "VerificationVerdict",
    "RunEvent",
]
