"""Independent re-derivation of the canonical-schema helpers (D-23.2-02).

Every expectation in this module is re-derived HERE, from the raw asset
``app/data/pulse_intake_v1.json`` read off disk, and never from the module under test.
A test that imports ``app.intake_canonical``'s own constant and compares it to itself is
vacuous: an empty derivation would equal an empty expectation and go green.

The anti-vacuity assertions exist for one measured failure shape (T-23.2-01-01): sections
in this schema carry ``id``, **not** ``key`` -- ``section["key"]`` is ``None`` for all 14 --
so a walker keyed on ``key`` returns the empty set and every downstream confidentiality
filter silently becomes a no-op. Hence ``sections_walked == 14`` and ``len(...) >= 1``.

Pure schema logic: no database, no engine patch, no seeded space, no marker.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# The asset, located WITHOUT importing the module under test.
_RAW_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "pulse_intake_v1.json"


def _raw_schema() -> dict[str, Any]:
    return json.loads(_RAW_SCHEMA_PATH.read_text(encoding="utf-8"))


def _walk() -> tuple[set[str], set[str], int, int]:
    """Re-derive (admin_only keys, all keys, sections walked, admin-only sections).

    Deliberately written straight -- no reuse of the production walk.
    """
    schema = _raw_schema()
    admin_keys: set[str] = set()
    all_keys: set[str] = set()
    sections_walked = 0
    admin_sections = 0
    for section in schema["sections"]:
        sections_walked += 1
        is_admin = bool(section.get("admin_only"))
        if is_admin:
            admin_sections += 1
        for field in section.get("fields", []) or []:
            key = field["key"]
            all_keys.add(key)
            if is_admin:
                admin_keys.add(key)
    return admin_keys, all_keys, sections_walked, admin_sections


# ===========================================================================
# admin_only_field_keys() -- the confidentiality set
# ===========================================================================


def test_admin_only_field_keys_matches_independent_walk():
    from app.intake_canonical import admin_only_field_keys

    admin_keys, _all_keys, sections_walked, admin_sections = _walk()

    # ANTI-VACUITY: the independent walk must have seen the whole schema, and the
    # derivation must not be able to pass by returning nothing.
    assert sections_walked == 14, (
        f"the raw schema must have 14 sections, walked {sections_walked} -- if the asset "
        "changed, every count in this module needs re-measuring"
    )
    assert admin_sections == 1, (
        f"exactly one section carries admin_only today, found {admin_sections}"
    )
    assert len(admin_keys) >= 1, (
        "the independent walk itself found no admin-only field -- the expectation is "
        "vacuous and the test proves nothing"
    )

    assert admin_only_field_keys() == admin_keys, (
        "admin_only_field_keys() must equal the section-level admin_only walk re-derived "
        f"from the raw JSON; got {sorted(admin_only_field_keys())} vs {sorted(admin_keys)}"
    )
    assert len(admin_only_field_keys()) >= 1, (
        "an empty admin-only set turns every downstream confidentiality filter into a "
        "no-op (T-23.2-01-01) -- most likely cause: the walker reads section['key'], "
        "which is None for all 14 sections; it must read section['admin_only'] off the "
        "section identified by 'id'"
    )


def test_admin_only_field_keys_todays_value_canary():
    from app.intake_canonical import admin_only_field_keys

    assert admin_only_field_keys() == {
        "bias_radar",
        "blind_spots_upstream",
        "blind_spots_downstream",
        "blind_spots_perspectief",
    }, (
        "The admin-only field set changed. This literal is a CANARY, not the source of "
        "truth -- the derivation is. If you added a fifth admin-only field to "
        "app/data/pulse_intake_v1.json, update this literal AND re-check every consumer: "
        "intake_routes.list_answers, intake_routes.get_skill_run_full, "
        "ai/skills/context_pack._format_intake_markdown, and the write policy in "
        "intake_write_policy."
    )


# ===========================================================================
# canonical_field_keys() -- schema MEMBERSHIP (admin keys included)
# ===========================================================================


def test_canonical_field_keys_matches_independent_walk():
    from app.intake_canonical import canonical_field_keys

    _admin_keys, all_keys, sections_walked, _admin_sections = _walk()

    assert sections_walked == 14, f"walked {sections_walked} sections, expected 14"
    assert canonical_field_keys() == all_keys, (
        "canonical_field_keys() must equal every sections[].fields[].key in the raw JSON"
    )
    assert len(canonical_field_keys()) == 29, (
        f"the canonical schema has 29 fields; canonical_field_keys() returned "
        f"{len(canonical_field_keys())}"
    )


def test_admin_only_keys_are_a_proper_subset_of_canonical_keys():
    from app.intake_canonical import admin_only_field_keys, canonical_field_keys

    assert admin_only_field_keys() < canonical_field_keys(), (
        "admin_only_field_keys() must be a PROPER subset of canonical_field_keys() -- "
        "equality would mean the derivation returned the same set for both, and a "
        "consumer using membership as a confidentiality filter would hide everything "
        "or nothing (T-23.2-01-03)"
    )


# ===========================================================================
# canonical_field() -- the raw field dict, for type / options / limits
# ===========================================================================


def test_canonical_field_exposes_the_raw_field_dict():
    from app.intake_canonical import canonical_field

    assert canonical_field("bias_radar")["type"] == "longtext"
    assert canonical_field("extra_questions_proposed")["type"] == "proposal_list"
    options = canonical_field("output_form")["options"]
    assert isinstance(options, list) and len(options) > 0, (
        f"output_form must expose a non-empty options list, got {options!r}"
    )


def test_canonical_field_returns_none_for_an_unknown_key():
    from app.intake_canonical import canonical_field

    assert canonical_field("does_not_exist_anywhere") is None


def test_exactly_one_canonical_field_is_a_proposal_list():
    """Plan 23.2-09 depends on the proposal_list field being DERIVABLE, not listed."""
    from app.intake_canonical import canonical_field, canonical_field_keys

    checked = 0
    proposal_lists: list[str] = []
    for key in canonical_field_keys():
        field = canonical_field(key)
        assert field is not None, f"canonical_field({key!r}) returned None for a known key"
        checked += 1
        if field.get("type") == "proposal_list":
            proposal_lists.append(key)

    assert checked == len(canonical_field_keys()) == 29, (
        f"walked {checked} of {len(canonical_field_keys())} keys -- the loop must cover "
        "every canonical field or the 'exactly one' claim is unproven"
    )
    assert proposal_lists == ["extra_questions_proposed"], (
        f"exactly one field must be type=proposal_list, found {sorted(proposal_lists)}"
    )


# ===========================================================================
# client_visible_schema() -- the canonical schema minus admin-only sections
# ===========================================================================


def test_client_visible_schema_drops_exactly_the_admin_only_sections():
    from app.intake_canonical import client_visible_schema

    _admin_keys, _all_keys, sections_walked, admin_sections = _walk()
    assert sections_walked == 14 and admin_sections == 1

    sections = client_visible_schema()["sections"]
    assert len(sections) == 13, (
        f"13 of 14 sections are client-visible today, got {len(sections)}"
    )
    assert sections_walked - len(sections) == 1 == admin_sections, (
        "exactly one section must be dropped, matching the raw walk"
    )
    leaked = [s.get("id") for s in sections if s.get("admin_only")]
    assert leaked == [], f"admin-only sections leaked into the client copy: {leaked}"


def test_client_visible_schema_preserves_every_other_top_level_key():
    from app.intake_canonical import CANONICAL_TEMPLATE_SCHEMA, client_visible_schema

    visible = client_visible_schema()
    checked = 0
    for key, value in CANONICAL_TEMPLATE_SCHEMA.items():
        if key == "sections":
            continue
        assert key in visible, f"top-level key {key!r} was dropped from the client copy"
        assert visible[key] == value, f"top-level key {key!r} changed value"
        checked += 1

    assert checked == 9, (
        f"the schema has 9 non-'sections' top-level keys; checked {checked} -- if the asset "
        "gained or lost one, re-measure before changing this number"
    )


def test_client_visible_schema_cannot_corrupt_the_shared_constant():
    """The deep-copy criterion. A SHALLOW copy passes every count above and fails here."""
    from app.intake_canonical import CANONICAL_TEMPLATE_SCHEMA, client_visible_schema

    visible = client_visible_schema()
    sentinel_section = {"id": "__sentinel_section__"}
    visible["sections"].append(sentinel_section)
    visible["sections"][0]["__sentinel_key__"] = "tampered"
    try:
        assert len(CANONICAL_TEMPLATE_SCHEMA["sections"]) == 14, (
            "mutating the client-visible copy appended a section to the shared canonical "
            "constant (T-23.2-01-02) -- client_visible_schema() must be a deep copy"
        )
        assert not any(
            "__sentinel_key__" in s for s in CANONICAL_TEMPLATE_SCHEMA["sections"]
        ), (
            "mutating a section of the client-visible copy reached a section of the shared "
            "canonical constant -- the sections were copied by reference, not deep-copied"
        )
    finally:
        # Restore: the module hands back ONE import-time constant by design (no per-request
        # deep copy), so an unrestored mutation would leak into every later test.
        visible["sections"].remove(sentinel_section)
        visible["sections"][0].pop("__sentinel_key__", None)
