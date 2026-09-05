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

Admin-only confidentiality (D-23.2-02)
--------------------------------------
The schema carries ``"admin_only": true`` at **SECTION** level (today: exactly one section,
``strategic_perspective``, whose own description reads *"Visible only to admin, not to the
client and not in the handoff PDF."*). Until phase 23.2 that flag was honoured only in the
browser (``IntakeForm.tsx``, ``intake.$id.results.tsx``); the backend had never read it.

This module is the ONE place that reads it. ``admin_only_field_keys()`` DERIVES the key set
from the schema rather than listing it, so a fifth admin-only field added to the JSON closes
automatically in every consumer. A hand-written set of the four keys, repeated per consumer,
would be one place per consumer to forget — the bug D-23.2-02 exists to prevent. This module
therefore contains no field-key literal at all, and neither may its consumers.

Note the two sets are NOT interchangeable: ``canonical_field_keys()`` is schema MEMBERSHIP
(admin-only keys included) and ``admin_only_field_keys()`` is the CONFIDENTIALITY set. The
client-visible set is the difference of the two. Using membership as a confidentiality filter
hides everything or nothing.
"""

from __future__ import annotations

import copy
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


# ---------------------------------------------------------------------------
# Derived views of the canonical schema (D-23.2-02)
#
# All four are computed ONCE here at import, by walking CANONICAL_TEMPLATE_SCHEMA; the
# public functions below are thin accessors. Re-deriving per call would put a walk (and,
# for the client-visible copy, a deep copy) on the request hot path for a value that
# cannot change while the process lives — the JSON is read once at import.
#
# The walk mirrors the defensive shape of
# ``app/ai/skills/structure_answers.py::_flatten_template_keys``: it tolerates a section
# that is not a dict, a field that is not a dict, and a field with no ``key``.
#
# ⚠ Sections carry ``id``, NOT ``key`` — ``section["key"]`` is None for all 14 sections.
# A walker keyed on ``key`` returns an empty set and silently turns every downstream
# confidentiality filter into a no-op.
# ---------------------------------------------------------------------------


def _derive() -> tuple[frozenset[str], frozenset[str], dict[str, dict], dict]:
    admin_keys: set[str] = set()
    all_keys: set[str] = set()
    by_key: dict[str, dict] = {}
    visible_section_ids: list[int] = []

    sections = CANONICAL_TEMPLATE_SCHEMA.get("sections", []) or []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        # Truthiness, not ``is True``: a hand edit could land ``1`` or ``"true"`` in the
        # JSON, and the safe reading of any truthy value is "hide it".
        section_is_admin_only = bool(section.get("admin_only"))
        if not section_is_admin_only:
            visible_section_ids.append(index)
        for field in section.get("fields", []) or []:
            if not isinstance(field, dict) or not field.get("key"):
                continue
            key = field["key"]
            all_keys.add(key)
            by_key[key] = field
            # No field carries ``admin_only`` today; reading it costs one ``or`` and means
            # a future field-level flag is honoured rather than silently ignored.
            if section_is_admin_only or bool(field.get("admin_only")):
                admin_keys.add(key)

    # Deep-copy the WHOLE schema first, then filter, so the surviving sections in the
    # client copy are copies too. Filtering first and copying the survivors by reference
    # would leave a caller holding live references into the shared constant.
    client_visible = copy.deepcopy(CANONICAL_TEMPLATE_SCHEMA)
    client_visible["sections"] = [client_visible["sections"][i] for i in visible_section_ids]

    return frozenset(admin_keys), frozenset(all_keys), by_key, client_visible


(
    _ADMIN_ONLY_FIELD_KEYS,
    _CANONICAL_FIELD_KEYS,
    _CANONICAL_FIELDS_BY_KEY,
    _CLIENT_VISIBLE_SCHEMA,
) = _derive()


def admin_only_field_keys() -> frozenset[str]:
    """The CONFIDENTIALITY set: field keys a ``role == "user"`` caller must never see.

    Every ``field["key"]`` under every section whose ``admin_only`` is truthy. Today: 4
    keys, all from ``strategic_perspective``.

    This is NOT schema membership — see :func:`canonical_field_keys`. It is the set to
    SUBTRACT when projecting answers, skill output, template schema or context-pack input
    for a client. Never use it as a validation allow-list.
    """
    return _ADMIN_ONLY_FIELD_KEYS


def canonical_field_keys() -> frozenset[str]:
    """The MEMBERSHIP set: every field key the canonical form defines. Today: 29 keys.

    Admin-only keys ARE included — this answers "is this a real field of the form?", which
    is what a 422 schema-membership gate and an LLM-output filter need.

    This is NOT the client-visible set and must never be used as a confidentiality filter;
    the client-visible set is ``canonical_field_keys() - admin_only_field_keys()``.
    """
    return _CANONICAL_FIELD_KEYS


def canonical_field(field_key: str) -> dict | None:
    """The raw field dict for ``field_key`` (for ``type``, ``options``, ``max_items``, ...).

    Returns ``None`` for a key the canonical form does not define. The returned dict is the
    shared constant's own object — treat it as read-only; it is NOT a defensive copy.
    """
    return _CANONICAL_FIELDS_BY_KEY.get(field_key)


def client_visible_schema() -> dict:
    """The canonical schema with every admin-only SECTION removed. Today: 13 of 14 sections.

    Every non-``sections`` top-level key (``title``, ``submit``, ``version``, ``subtitle``,
    ``product_slug``, ``save_as_you_go``, ``schema_version``, ``estimated_minutes``,
    ``field_types_reference``) is preserved verbatim.

    This is NOT the schema to validate writes against — an admin-only key is still a legal
    field of the form (:func:`canonical_field_keys`); it is simply not disclosed to a client.

    Deep-copied once at import, so a caller cannot mutate ``CANONICAL_TEMPLATE_SCHEMA``
    through the returned structure. It is nevertheless ONE shared object (no per-request
    copy): serialise it, do not mutate it.
    """
    return _CLIENT_VISIBLE_SCHEMA
