"""
User -- application user, scoped to an Org via tenant_id.

W7 plan-check fix: the table is named `app_user`, not `user`. `user` is a
Postgres reserved keyword; using it bare in raw SQL would either fail or
require quoting (`"user"`) at every reference site. `app_user` also
mirrors the `app_user_id` semantic that Plan 04's AuthClaims dataclass
uses (the Nestor-side UUID decoupled from any provider uid -- see
01-CONTEXT.md `<specifics>`).

Composite index `(tenant_id, email)` leads with tenant_id (Pitfall 2)
so RLS-filtered email lookups stay index-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nestor_pulse_sdk.db.base import Base


class User(Base):
    __tablename__ = "app_user"  # W7: avoid reserved keyword `user`

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # provider_user_id == firebase uid for D-10 IdentityPlatformProvider.
    # Per CONTEXT.md `<specifics>`, this column is the ONLY place a
    # provider-side identifier appears; the rest of the app keys on
    # `app_user.id` (== `app_user_id` in AuthClaims).
    provider_user_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="admin", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    org = relationship("Org", back_populates="users")

    __table_args__ = (
        Index("idx_app_user_tenant_email", "tenant_id", "email"),
    )
