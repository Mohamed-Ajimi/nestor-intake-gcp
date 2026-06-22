"""Model registry — importing this package registers all 15 tables.

Order matters only for human readability; SQLAlchemy resolves FK targets by
name at mapper-configuration time, not import time. Importing every module
here ensures ``Base.metadata`` carries the full ``nestor`` schema for both
Alembic autogenerate and the schema-shape tests.

The 15 tables (D-03 + Phase 5 audit_log):
  Tenant roots (NO space_id): organizations, organization_memberships,
    audit_log (Phase 5 — never RLS-scoped, D-07)
  Tenant-owned (space_id NOT NULL FK -> organizations.id):
    products, intakes, intake_answers, intake_templates, skill_runs,
    decompositions, research_questions, research_artifacts, findings,
    deliverables, artifact_embeddings, search_index
"""

from __future__ import annotations

from app.db.models.organization import Organization
from app.db.models.membership import OrganizationMembership
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.intake import Intake, IntakeAnswer, IntakeTemplate
from app.db.models.skill_run import SkillRun
from app.db.models.research import (
    Decomposition,
    ResearchQuestion,
    ResearchArtifact,
)
from app.db.models.findings import Finding, Deliverable
from app.db.models.embeddings import ArtifactEmbedding, SearchIndex

__all__ = [
    "Organization",
    "OrganizationMembership",
    "AuditLog",
    "Product",
    "Intake",
    "IntakeAnswer",
    "IntakeTemplate",
    "SkillRun",
    "Decomposition",
    "ResearchQuestion",
    "ResearchArtifact",
    "Finding",
    "Deliverable",
    "ArtifactEmbedding",
    "SearchIndex",
]
