"""
Pydantic v2 schemas for the projects API (D-06 long-lived engagement).

CreateProjectRequest: what the UI sends to open a new client engagement.
ProjectResponse: the canonical DB-backed row returned by POST + the typed
  shape the list/detail handlers build on.

The list/detail endpoints return enriched dicts (briefing counts, owner
email, relative-time string) assembled in the handler -- mirroring the demo
GET /api/projects shape (demo/api.py) so the same UI works in both modes.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    """POST /api/projects request body."""
    name: str = Field(min_length=1, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)


class ProjectResponse(BaseModel):
    """Canonical DB-backed project row (POST /api/projects response)."""
    id: uuid.UUID
    name: str
    client_name: str | None = None
    status: str
    owner_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
