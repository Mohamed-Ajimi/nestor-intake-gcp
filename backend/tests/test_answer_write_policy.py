"""D-23.2-05/06/07 — the client answer-write policy, pure matrix + route wiring (F-02).

`23.2-CONTEXT.md` § 3: ``upsert_answers`` verified intake OWNERSHIP and nothing else. A
``role=user`` could write an undefined field key onto a ``delivered`` intake — i.e. mutate the
research inputs after the operator read them, after the context pack was built, after ~$45 of
research ran on them, and after delivery.

This file has TWO halves and they are deliberately different in kind:

* **The pure half** drives ``app.intake_write_policy.check_answer_batch`` directly — no FastAPI,
  no database, no container. It runs on any box and is the real matrix.
* **The route half** (marked ``integration``) drives the REAL ``intake_router`` over the REAL
  Postgres, and proves the three things a pure test cannot: the response-code PRECEDENCE
  (ownership 404 BEFORE the policy), that a refused batch writes NOTHING, and that the 200 body
  of a successful client write is projected through the SAME confidentiality filter the read
  path uses (the seam plan 23.2-06 opened by closing only the GET).

THE TWO TRAPS THIS FILE EXISTS TO CATCH, both of which pass a fully green suite without it:

1. **The policy is NOT "only ``draft`` is writable."** ``IntakeForm.tsx:501`` re-enables
   ``proposal_list`` fields while the intake is ``reviewed`` / ``validated_by_client`` (the
   client's "keep Nestor's proposal" tick, shipped 2026-08-31). A draft-only server rule kills
   it and no pre-existing test goes red. ``test_proposal_list_*`` is written FIRST for that
   reason.
2. **A ``radio`` answer is not always a string.** ``output_form``'s "Anders" option carries
   ``allow_text: true`` and ``FieldRenderer.tsx:302-306`` emits ``{choice, text}`` — an OBJECT,
   which ``toAnswerInput`` routes to ``value_json``. A naive "radio => value in options" rule
   422s a live client path.
"""

from __future__ import annotations

import json
import uuid

import pytest

policy = pytest.importorskip("app.intake_write_policy")
canonical = pytest.importorskip("app.intake_canonical")

AnswerWriteViolation = policy.AnswerWriteViolation
check_answer_batch = policy.check_answer_batch

canonical_field = canonical.canonical_field
canonical_field_keys = canonical.canonical_field_keys
admin_only_field_keys = canonical.admin_only_field_keys

SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# Small helpers — every fixture value is DERIVED from the canonical schema, never
# hard-coded. A test that spells ``extra_questions_proposed`` proves the code works for
# that literal, not that the rule reads the schema (D-23.2-02).
# ---------------------------------------------------------------------------


def _keys_of_type(field_type: str) -> list[str]:
    """Canonical field keys whose schema ``type`` is exactly ``field_type``."""
    return sorted(k for k in canonical_field_keys() if canonical_field(k).get("type") == field_type)


# ⚠ ``client_name`` is SEEDED BY A DATABASE TRIGGER, not by any request: migration 0008's
# ``seed_intake_client_name_answer`` fires AFTER INSERT ON intakes and copies the organization's
# name into an ``intake_answers`` row. A probe on that key therefore finds a row whether or not
# the request under test wrote one, which would make every "a refused write leaves NOTHING
# behind" assertion in the route half silently vacuous. It is excluded from probe SELECTION
# only — the anti-vacuity sweep still walks it, because it is a perfectly ordinary writable
# ``text`` field as far as the POLICY is concerned.
_TRIGGER_SEEDED_KEYS = frozenset({"client_name"})


def _client_keys_of_type(field_type: str) -> list[str]:
    """Probe-usable keys of a type: not admin-only, and not seeded by a trigger."""
    admin = admin_only_field_keys()
    return [
        k
        for k in _keys_of_type(field_type)
        if k not in admin and k not in _TRIGGER_SEEDED_KEYS
    ]


def _one(items: list[str], what: str) -> str:
    assert items, f"the canonical schema defines no {what} field — the matrix would be vacuous"
    return items[0]


def _option_values(field_key: str) -> list[str]:
    return [o["value"] for o in canonical_field(field_key).get("options", [])]


def _allow_text_option(field_key: str) -> str | None:
    for opt in canonical_field(field_key).get("options", []):
        if opt.get("allow_text"):
            return opt["value"]
    return None


def _plain_option(field_key: str) -> str | None:
    for opt in canonical_field(field_key).get("options", []):
        if not opt.get("allow_text"):
            return opt["value"]
    return None


def _item(field_key: str, **kw) -> dict:
    """One inbound answer, in the ``AnswerItem.model_dump()`` shape the route hands over."""
    return {"field_key": field_key, "value": kw.get("value"), "value_json": kw.get("value_json")}


def _plausible_item(field_key: str) -> dict:
    """A minimal, schema-plausible value for ANY canonical field type.

    Used by the anti-vacuity sweep: if a rule accidentally rejects a type nobody wrote a
    dedicated case for, the sweep is what catches it.
    """
    field = canonical_field(field_key)
    ftype = field.get("type")
    if ftype == "radio":
        return _item(field_key, value=_option_values(field_key)[0])
    if ftype in ("list", "proposal_list", "files"):
        return _item(field_key, value_json=["x"])
    if ftype == "file":
        return _item(field_key, value_json={"path": "k", "name": "f.pdf"})
    return _item(field_key, value="x")


def _violation(items, *, status, role="user") -> "AnswerWriteViolation":
    """Assert the batch is REFUSED and hand back the violation for code inspection."""
    with pytest.raises(AnswerWriteViolation) as exc:
        check_answer_batch(items, intake_status=status, role=role)
    return exc.value


def _accepted(items, *, status, role="user") -> None:
    """Assert the batch is ACCEPTED (``check_answer_batch`` returns without raising)."""
    check_answer_batch(items, intake_status=status, role=role)


# ===========================================================================
# (1) THE proposal_list EXCEPTION — written FIRST, because it is the case a naive
#     "draft only" rule breaks silently, with the whole suite still green.
# ===========================================================================


def test_exactly_one_canonical_field_is_a_proposal_list():
    """The exception is DERIVED from ``canonical_field(k)["type"]``, not from a key literal.

    Measured against ``app/data/pulse_intake_v1.json``: exactly one field carries
    ``type == "proposal_list"``. If a second one is added the exception widens automatically —
    which is the point of deriving it.
    """
    proposal_keys = _keys_of_type("proposal_list")
    assert len(proposal_keys) == 1, (
        f"expected exactly ONE proposal_list field in the canonical schema, got {proposal_keys!r}"
    )


@pytest.mark.parametrize("status", ["reviewed", "validated_by_client"])
def test_proposal_list_stays_writable_in_the_validation_phase(status):
    """THE LIVE FEATURE (``IntakeForm.tsx:501``, shipped 2026-08-31).

    In ``reviewed`` AND ``validated_by_client`` the form is otherwise read-only, but a
    ``proposal_list`` field stays enabled — that is the client's "keep Nestor's proposal" tick.
    A server rule of "writable only in draft" refuses this and NO pre-existing test goes red.
    """
    key = _one(_keys_of_type("proposal_list"), "proposal_list")
    _accepted([_item(key, value_json=[{"text": "q", "approved": True}])], status=status)


@pytest.mark.parametrize("status", ["reviewed", "validated_by_client"])
def test_non_proposal_field_is_refused_in_the_validation_phase(status):
    """The other side of the exception: everything that is NOT a proposal_list is frozen -> 409.

    Re-opening a reviewed answer would let the client silently rewrite content the operator
    already validated (``IntakeForm.tsx:485-494``).
    """
    key = _one(_client_keys_of_type("text"), "text")
    assert _violation([_item(key, value="BE")], status=status).code == 409


# ===========================================================================
# (2) LIFECYCLE — D-23.2-05's table, including deny-by-default
# ===========================================================================


def test_draft_accepts_any_non_admin_canonical_field():
    key = _one(_client_keys_of_type("text"), "text")
    _accepted([_item(key, value="BE")], status="draft")


@pytest.mark.parametrize("status", ["submitted", "decomposed", "in_research", "delivered"])
def test_frozen_statuses_refuse_every_write_including_proposal_list(status):
    """The four frozen statuses refuse EVERYTHING — the proposal exception does not reach here."""
    text_key = _one(_client_keys_of_type("text"), "text")
    proposal_key = _one(_keys_of_type("proposal_list"), "proposal_list")

    assert _violation([_item(text_key, value="BE")], status=status).code == 409
    assert _violation([_item(proposal_key, value_json=[])], status=status).code == 409


def test_all_four_frozen_statuses_were_actually_checked():
    """Anti-vacuity for the parametrisation above: the frozen set has exactly four members."""
    frozen = ["submitted", "decomposed", "in_research", "delivered"]
    checked = 0
    key = _one(_client_keys_of_type("text"), "text")
    for status in frozen:
        assert _violation([_item(key, value="BE")], status=status).code == 409
        checked += 1
    assert checked == 4, f"expected 4 frozen statuses exercised, got {checked}"


def test_unrecognised_status_denies_by_default():
    """A status the policy does not know about writes NOTHING — deny by default, not accept.

    ``nestor.intake_status`` carries an eighth value the D-23.2-05 table never names
    (``archived``); an allow-list is the only shape that handles it safely, and the same
    reasoning covers any status a later migration adds.
    """
    key = _one(_client_keys_of_type("text"), "text")
    assert _violation([_item(key, value="BE")], status="archived").code == 409
    assert _violation([_item(key, value="BE")], status="not_a_status").code == 409


# ===========================================================================
# (3) SCHEMA MEMBERSHIP (422) and FIELD PERMISSION (404, existence-hidden)
# ===========================================================================


def test_unknown_field_key_is_422():
    assert _violation([_item("totally_unknown_key", value="x")], status="draft").code == 422


def test_every_admin_only_key_is_404_and_the_detail_does_not_name_it():
    """An admin-only key from a client is 404, consistent with D-07 (existence hidden).

    404 comes AFTER membership on purpose: an admin key IS a real field of the form, so it
    passes the 422 gate and is caught here. And the detail must not echo the key back — naming
    it in the body would undo the existence hiding the status code chose.
    """
    admin_keys = sorted(admin_only_field_keys())
    checked = 0
    for key in admin_keys:
        violation = _violation([_item(key, value="x")], status="draft")
        assert violation.code == 404, f"{key} must be an existence-hidden 404"
        assert key not in violation.detail, (
            f"the 404 detail names {key!r} ({violation.detail!r}) — that re-discloses the field"
        )
        checked += 1
    assert checked == 4, f"expected 4 admin-only keys, got {checked} ({admin_keys!r})"


def test_admin_only_key_is_404_even_in_the_validation_phase():
    """Ordering: field permission (404) outranks the status/field 409 of the validation phase."""
    key = sorted(admin_only_field_keys())[0]
    assert _violation([_item(key, value="x")], status="reviewed").code == 404


# ===========================================================================
# (4) SUPERADMIN — exempt, for four reasons at once
# ===========================================================================


def test_superadmin_is_exempt_from_every_rule():
    """One batch, four reasons it would fail as a client — accepted, because superadmin.

    The admin AI-review apply path and ``admin.pulse.intakes.$id.tsx:951`` (edit-mode save,
    which writes the four admin-only fields) both go through this route as superadmin. The
    live-UAT regression of 2026-07-13 is what a policy applied to superadmin re-creates.
    """
    admin_key = sorted(admin_only_field_keys())[0]
    text_key = _one(_client_keys_of_type("text"), "text")
    _accepted(
        [
            _item(admin_key, value="operator's private bias analysis"),
            _item("a_key_the_schema_never_defined", value="x"),
            _item(text_key, value="y" * (policy._MAX_VALUE_CHARS + 1)),
            _item(text_key, value_json={"not": "a string field"}),
        ],
        status="delivered",
        role="superadmin",
    )


# ===========================================================================
# (5) ALL-OR-NOTHING — order inside the batch must not change the verdict
# ===========================================================================


def test_batch_verdict_is_independent_of_item_order():
    good = _item(_one(_client_keys_of_type("text"), "text"), value="BE")
    bad = _item("nope_not_a_field", value="x")

    first = _violation([good, bad], status="draft")
    second = _violation([bad, good], status="draft")
    assert first.code == second.code == 422, (
        "a batch is all-or-nothing: the same bad item must produce the same code whichever "
        f"position it holds (got {first.code} / {second.code})"
    )


# ===========================================================================
# (6) VALUE VALIDATION — D-23.2-07, bounded
# ===========================================================================


@pytest.mark.parametrize(
    "payload",
    [
        {"value": None, "value_json": None},
        {"value": ""},
    ],
    ids=["cleared", "empty-string"],
)
def test_empty_is_always_accepted_even_for_a_required_min_length_field(payload):
    """SAVE-AS-YOU-GO. ``required`` / ``min_length`` are NOT write-time constraints.

    ``IntakeForm.tsx:214-217`` saves only the DIRTY fields of a section and maps each through
    ``toAnswerInput`` (``:26-30``), which sends ``{value: null, value_json: null}`` for a
    cleared value. Clearing a required field, or saving a section before a required field is
    filled, is a NORMAL operation on every intake. ``validateField`` (``:33-40``) enforces
    ``required`` in the BROWSER at submit time. A policy that enforces it here 422s the live
    client form mid-typing.
    """
    required_longtext = [
        k
        for k in _client_keys_of_type("longtext")
        if canonical_field(k).get("required") and canonical_field(k).get("min_length")
    ]
    key = _one(required_longtext, "required longtext with a min_length")
    _accepted([_item(key, **payload)], status="draft")


def test_radio_accepts_a_plain_option_string():
    key = _one(_client_keys_of_type("radio"), "radio")
    _accepted([_item(key, value=_option_values(key)[0])], status="draft")


def test_radio_refuses_a_string_that_is_not_an_option():
    key = _one(_client_keys_of_type("radio"), "radio")
    assert _violation([_item(key, value="not_an_option")], status="draft").code == 422


def test_radio_accepts_the_allow_text_object_shape():
    """THE ``allow_text`` TRAP. ``FieldRenderer.tsx:302-306`` emits ``{choice, text}``.

    ``toAnswerInput`` routes any non-string to ``value_json``, so the live "Anders / Other"
    path arrives as an OBJECT. A "radio => value in options" rule 422s it.
    """
    radios_with_allow_text = [k for k in _client_keys_of_type("radio") if _allow_text_option(k)]
    assert radios_with_allow_text, (
        "no canonical radio carries an allow_text option — this trap case would be vacuous"
    )
    for key in radios_with_allow_text:
        choice = _allow_text_option(key)
        _accepted([_item(key, value_json={"choice": choice, "text": "iets anders"})], status="draft")


def test_radio_refuses_an_object_whose_choice_has_no_allow_text():
    """``{choice: "notion"}`` is not a shape the renderer can produce — "notion" has no free text."""
    key = _one([k for k in _client_keys_of_type("radio") if _allow_text_option(k)], "allow_text radio")
    plain = _plain_option(key)
    assert plain is not None, f"{key} has no non-allow_text option — the case would be vacuous"
    assert _violation([_item(key, value_json={"choice": plain, "text": "x"})], status="draft").code == 422


def test_radio_without_any_allow_text_option_refuses_every_object():
    """``report_language`` — three options, none with ``allow_text``: only a plain string works."""
    plain_radios = [k for k in _client_keys_of_type("radio") if not _allow_text_option(k)]
    assert plain_radios, "no canonical radio lacks allow_text — this case would be vacuous"
    key = plain_radios[0]
    _accepted([_item(key, value=_option_values(key)[0])], status="draft")
    assert _violation([_item(key, value_json={"choice": _option_values(key)[0]})], status="draft").code == 422


def test_list_enforces_max_items_but_not_min_items():
    capped = [k for k in _client_keys_of_type("list") if canonical_field(k).get("max_items")]
    key = _one(capped, "list with a max_items")
    cap = canonical_field(key)["max_items"]

    _accepted([_item(key, value_json=["x"] * cap)], status="draft")
    assert _violation([_item(key, value_json=["x"] * (cap + 1))], status="draft").code == 422

    min_items = canonical_field(key).get("min_items")
    if min_items:
        # min_items is NOT enforced at write time — same save-as-you-go reasoning as `required`.
        _accepted([_item(key, value_json=[])], status="draft")


def test_list_refuses_a_bare_string():
    key = _one(_client_keys_of_type("list"), "list")
    assert _violation([_item(key, value="a string")], status="draft").code == 422


def test_files_enforces_max_files():
    key = _one(_client_keys_of_type("files"), "files")
    cap = canonical_field(key)["max_files"]
    _accepted([_item(key, value_json=[{"path": f"p{i}"} for i in range(cap)])], status="draft")
    assert (
        _violation([_item(key, value_json=[{"path": f"p{i}"} for i in range(cap + 1)])], status="draft").code
        == 422
    )


def test_file_requires_an_object_not_a_list():
    key = _one(_client_keys_of_type("file"), "file")
    _accepted([_item(key, value_json={"path": "k", "name": "nda.pdf"})], status="draft")
    assert _violation([_item(key, value_json=[{"path": "k"}])], status="draft").code == 422


def test_download_is_display_only_and_carries_no_invented_contract():
    """``nda_download`` renders a link. The schema states no input contract; do not invent one."""
    key = _one(_client_keys_of_type("download"), "download")
    _accepted([_item(key, value="anything")], status="draft")
    _accepted([_item(key, value_json={"acknowledged": True})], status="draft")


def test_textual_field_refuses_a_json_value():
    key = _one(_client_keys_of_type("longtext"), "longtext")
    _accepted([_item(key, value="a paragraph")], status="draft")
    assert _violation([_item(key, value_json=123)], status="draft").code == 422


@pytest.mark.parametrize("ftype", ["email", "tel", "date"])
def test_no_format_regex_is_invented(ftype):
    """D-23.2-07 forbids inventing constraints the schema does not carry.

    The canonical schema states no ``pattern`` for ``email`` / ``tel`` / ``date``, so the policy
    checks only that the value is a string. ``validateField`` (``IntakeForm.tsx:38``) does the
    email shape check in the browser; duplicating it here with a DIFFERENT regex is how a
    server and its form start disagreeing.
    """
    key = _one(_client_keys_of_type(ftype), ftype)
    _accepted([_item(key, value="not-in-any-canonical-format")], status="draft")


# ===========================================================================
# (7) DoS BOUNDS — not business rules; rejected, never truncated
# ===========================================================================


def test_value_over_the_char_bound_is_422():
    key = _one(_client_keys_of_type("longtext"), "longtext")
    _accepted([_item(key, value="x" * policy._MAX_VALUE_CHARS)], status="draft")
    assert _violation([_item(key, value="x" * (policy._MAX_VALUE_CHARS + 1))], status="draft").code == 422


def test_value_json_over_the_json_bound_is_422():
    key = _one(_client_keys_of_type("longtext"), "longtext")
    oversize = {"blob": "x" * policy._MAX_JSON_CHARS}
    assert len(json.dumps(oversize)) > policy._MAX_JSON_CHARS
    assert _violation([_item(key, value_json=oversize)], status="draft").code == 422


def test_batch_over_the_item_bound_is_422():
    key = _one(_client_keys_of_type("text"), "text")
    at_cap = [_item(key, value="x") for _ in range(policy._MAX_BATCH_ITEMS)]
    _accepted(at_cap, status="draft")
    assert _violation(at_cap + [_item(key, value="x")], status="draft").code == 422


def test_bounds_are_not_silently_truncated():
    """The policy REFUSES an over-bound value; it must never mutate the caller's items."""
    key = _one(_client_keys_of_type("longtext"), "longtext")
    items = [_item(key, value="x" * (policy._MAX_VALUE_CHARS + 1))]
    _violation(items, status="draft")
    assert len(items[0]["value"]) == policy._MAX_VALUE_CHARS + 1, (
        "the policy truncated the item in place — it must refuse, not repair"
    )


# ===========================================================================
# (8) ANTI-VACUITY SWEEP over the WHOLE canonical surface
# ===========================================================================


def test_every_canonical_field_is_classified_and_none_is_accidentally_rejected():
    """One plausibly-valid item per canonical field, swept in ``draft`` as ``role=user``.

    This is the criterion that catches a type rule which accidentally rejects a field type
    nobody wrote a dedicated case for. The 25 client fields must ALL be accepted (as one batch
    AND individually), and the 4 admin-only ones must ALL be 404.
    """
    admin = admin_only_field_keys()
    all_keys = sorted(canonical_field_keys())
    client_items, checked = [], 0

    for key in all_keys:
        item = _plausible_item(key)
        if key in admin:
            assert _violation([item], status="draft").code == 404, f"{key} must be an admin 404"
        else:
            _accepted([item], status="draft")
            client_items.append(item)
        checked += 1

    assert checked == 29, f"expected the canonical 29 fields, swept {checked}"
    assert len(client_items) == 25, f"expected 29 - 4 admin = 25 client fields, got {len(client_items)}"
    _accepted(client_items, status="draft")


def test_the_policy_module_is_pure():
    """No FastAPI, no SQLAlchemy, no session — the policy is a function of its arguments.

    A policy that reaches for a request or a session cannot be exercised without a container,
    and the matrix above would degrade into an integration suite.
    """
    import inspect

    source = inspect.getsource(policy)
    for banned in ("fastapi", "sqlalchemy", "HTTPException", "Session"):
        assert banned not in source, f"app/intake_write_policy.py must not reference {banned!r}"


# ===========================================================================
# THE ROUTE HALF — the REAL router over the REAL Postgres (integration)
# ===========================================================================

_ROUTE_DEPS_ERROR: str | None = None
try:  # pragma: no cover - import-shape guard, exercised by the skip path
    import firebase_admin  # noqa: F401

    from app.api import auth_routes as _auth_routes
    from app.api import intake_routes as _intake_routes
    from app.auth import dependencies as _dependencies
    from app.auth import identity as _identity_mod
    from app.db import session as _session_mod
except Exception as exc:  # pragma: no cover
    _ROUTE_DEPS_ERROR = f"route-level deps unavailable: {exc}"

route_test = pytest.mark.skipif(
    _ROUTE_DEPS_ERROR is not None, reason=_ROUTE_DEPS_ERROR or ""
)

AUTH = {"Authorization": "Bearer ignored-overridden"}
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test container only


def _user(space_id):
    return _identity_mod.Identity(
        uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id)
    )


def _superadmin():
    return _identity_mod.Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    monkeypatch.setattr(_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """An engine connecting AS ``app_superadmin`` (mirrors test_intake_routes.py:118-140)."""
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD '{_SUPERADMIN_TEST_PASSWORD}'")
        )
    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


def _build_app():
    from fastapi import FastAPI

    _auth_routes.protected_router.include_router(_intake_routes.intake_router)
    app = FastAPI()
    app.include_router(_auth_routes.protected_router)
    return app


def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": f"Answer Policy {space_id}"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="draft") -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, :status)"
            ),
            {"id": intake_id, "space_id": space_id, "status": status},
        )


def _seed_answer(engine, set_space, space_id, intake_id, field_key, value) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intake_answers (id, space_id, intake_id, field_key, value) "
                "VALUES (:id, :space_id, :intake_id, :field_key, :value)"
            ),
            {
                "id": uuid.uuid4(),
                "space_id": space_id,
                "intake_id": intake_id,
                "field_key": field_key,
                "value": value,
            },
        )


def _read_answer(engine, set_space, space_id, intake_id, field_key):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(
                f"SELECT value, space_id FROM {SCHEMA}.intake_answers "
                "WHERE intake_id = :id AND field_key = :k"
            ),
            {"id": intake_id, "k": field_key},
        ).first()


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
        )


# --- the route cases ---------------------------------------------------------


@route_test
@pytest.mark.integration
def test_route_client_write_on_draft_is_200_and_lands(engine, set_space, monkeypatch):
    """Pinned client route row 5 stays EXACTLY 200 — this plan validates a body, never gates."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = _one(_client_keys_of_type("text"), "text")
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": key, "value": "BE"}]},
            headers=AUTH,
        )
        assert resp.status_code == 200, f"draft client write must be 200, got {resp.text!r}"
        row = _read_answer(engine, set_space, space, intake_id, key)
        assert row is not None and row[0] == "BE", "the 200 must correspond to a real write"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
@pytest.mark.parametrize("status", ["reviewed", "validated_by_client"])
def test_route_proposal_list_write_survives_the_validation_phase(
    engine, set_space, monkeypatch, status
):
    """THE LIVE FEATURE, end to end. A draft-only rule 409s here and the client tick is lost."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = _one(_keys_of_type("proposal_list"), "proposal_list")
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status=status)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.patch(
            f"/intakes/{intake_id}/answers",
            json={
                "answers": [
                    {"field_key": key, "value_json": [{"text": "q", "approved": True}]}
                ]
            },
            headers=AUTH,
        )
        assert resp.status_code == 200, (
            f"a client must still be able to tick Nestor's proposals while the intake is "
            f"{status!r} (IntakeForm.tsx:501) — got {resp.status_code} ({resp.text!r})"
        )
        body = {row["field_key"]: row["value_json"] for row in resp.json()}
        assert body.get(key) == [{"text": "q", "approved": True}]
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
def test_route_non_proposal_write_in_reviewed_is_409_and_leaves_the_row_alone(
    engine, set_space, monkeypatch
):
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = _one(_client_keys_of_type("text"), "text")
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="reviewed")
        _seed_answer(engine, set_space, space, intake_id, key, "reviewed value")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": key, "value": "rewritten"}]},
            headers=AUTH,
        )
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        row = _read_answer(engine, set_space, space, intake_id, key)
        assert row[0] == "reviewed value", "a refused write must leave the reviewed answer intact"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
def test_route_client_write_on_delivered_is_409_and_writes_nothing(engine, set_space, monkeypatch):
    """The research inputs are frozen once the report is out — ~$45 of research ran on them."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = _one(_client_keys_of_type("text"), "text")
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="delivered")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": key, "value": "late edit"}]},
            headers=AUTH,
        )
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        assert _read_answer(engine, set_space, space, intake_id, key) is None
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
def test_route_client_write_of_an_admin_only_field_is_404(engine, set_space, monkeypatch):
    """A client forging the operator's private strategic analysis of them -> existence-hidden 404."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = sorted(admin_only_field_keys())[0]
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": key, "value": "forged"}]},
            headers=AUTH,
        )
        assert resp.status_code == 404, f"expected 404, got {resp.status_code} ({resp.text!r})"
        assert key not in resp.text, "the 404 body must not name the admin-only field"
        assert _read_answer(engine, set_space, space, intake_id, key) is None
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
def test_route_unknown_field_key_is_422_and_writes_nothing(engine, set_space, monkeypatch):
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": "nope", "value": "x"}]},
            headers=AUTH,
        )
        assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({resp.text!r})"
        assert _read_answer(engine, set_space, space, intake_id, "nope") is None
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
def test_route_batch_is_all_or_nothing(engine, set_space, monkeypatch):
    """The GOOD item of a mixed batch must have NO row — the check runs before any write."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = _one(_client_keys_of_type("text"), "text")
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}/answers",
            json={
                "answers": [
                    {"field_key": key, "value": "BE"},
                    {"field_key": "nope", "value": "x"},
                ]
            },
            headers=AUTH,
        )
        assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({resp.text!r})"
        assert _read_answer(engine, set_space, space, intake_id, key) is None, (
            "the valid item of a refused batch was written — the batch is not all-or-nothing"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
def test_route_superadmin_writes_admin_field_on_delivered_intake_into_its_own_space(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The 2026-07-13 regression, restated under the new policy.

    A superadmin has NO own space, so the handler branches to ``upsert_batch_in_space``. The
    policy must not intercept that: the AI-review apply path and the admin edit-mode save
    (``admin.pulse.intakes.$id.tsx:951``) write admin-only fields on non-draft intakes.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = sorted(admin_only_field_keys())[0]
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="delivered")
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_superadmin())

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": key, "value": "operator analysis"}]},
            headers=AUTH,
        )
        assert resp.status_code == 200, (
            f"superadmin writes are unconstrained by D-23.2-05, got {resp.status_code} "
            f"({resp.text!r})"
        )
        row = _read_answer(engine, set_space, space, intake_id, key)
        assert row is not None and row[0] == "operator analysis"
        assert str(row[1]) == str(space), "the row must land in the INTAKE's own space"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@route_test
@pytest.mark.integration
def test_route_cross_tenant_non_canonical_key_is_404_not_422(engine, set_space, monkeypatch):
    """THE ORDERING PROOF, restated here so it survives any reorganisation of the other suite.

    Ownership runs FIRST. A cross-tenant caller writing a key the schema never defined must get
    the existence-hidden 404, NOT the policy's 422 — otherwise the response code becomes an
    oracle for "is this a real field?" against a foreign tenant.
    ``test_intake_cross_tenant.py::test_upsert_answers_cross_tenant_returns_404_answers_unchanged``
    is the original of this claim and is UNMODIFIED by this plan.
    """
    from fastapi.testclient import TestClient

    space_a, space_b, intake_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space_a)
        _seed_space(engine, space_b)
        _seed_intake(engine, set_space, space_b, intake_b)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space_a))

        resp = TestClient(app).patch(
            f"/intakes/{intake_b}/answers",
            json={"answers": [{"field_key": "q1", "value": "x"}]},
            headers=AUTH,
        )
        assert resp.status_code == 404, (
            f"a cross-tenant write must be 404 BEFORE the policy runs; got {resp.status_code} "
            f"({resp.text!r}). A 422 here means the policy was evaluated first and the code "
            f"now discloses field validity across a tenant boundary."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)
        _cleanup(engine, space_b)


@route_test
@pytest.mark.integration
def test_route_successful_client_write_returns_a_filtered_body(engine, set_space, monkeypatch):
    """THE RESPONSE SEAM (T-23.2-09-09).

    ``upsert_answers`` ends by returning ``list_for_intake`` — the SAME row list ``list_answers``
    returns. Plan 23.2-06 filtered the GET; filtering only the GET lets a client read back
    through a PATCH exactly what the GET withheld. Anti-vacuity in BOTH directions: the four
    admin keys are absent AND the key just written is present.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = _one(_client_keys_of_type("text"), "text")
    admin_keys = sorted(admin_only_field_keys())
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        for admin_key in admin_keys:
            _seed_answer(engine, set_space, space, intake_id, admin_key, f"private {admin_key}")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space))

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": key, "value": "BE"}]},
            headers=AUTH,
        )
        assert resp.status_code == 200, resp.text
        returned = {row["field_key"] for row in resp.json()}

        checked = 0
        for admin_key in admin_keys:
            assert admin_key not in returned, (
                f"the write response leaked {admin_key!r} — the seam plan 23.2-06 closed on "
                f"list_answers is open again on upsert_answers"
            )
            checked += 1
        assert checked == 4, f"expected 4 admin-only keys checked, got {checked}"
        assert key in returned, (
            "the filter withheld the client's OWN answer — a filter that returns nothing "
            "passes the leak assertion vacuously"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
