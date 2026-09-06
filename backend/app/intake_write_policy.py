"""The client answer-write policy — D-23.2-05 / D-23.2-06 / D-23.2-07 (F-02).

PURE by construction: no web framework, no database, no request, no transaction. Everything
this module decides is a function of ``(items, intake_status, role)`` plus the canonical
schema. That is what lets the whole policy matrix run as unit tests on any box, and it is why
the API layer — not this module — turns a violation into an HTTP response.

Why this exists
---------------
``upsert_answers`` used to verify intake OWNERSHIP and nothing else (23.2-CONTEXT.md § 3):
no status check, no schema-membership check, no admin-only check, no value validation. A
``role=user`` could write an undefined field key onto a ``delivered`` intake. The answers are
the RESEARCH INPUTS — they feed the context pack, the brief, and a ~$45 research run — so a
post-hoc edit silently changes what was researched, after the fact and after delivery.


D-23.2-05 — THE LIFECYCLE / FIELD TABLE, EXACTLY
------------------------------------------------

===============================  ==================================================
Intake status                    A ``role=user`` may write
===============================  ==================================================
``draft``                        any canonical field that is not admin-only
``reviewed``                     ONLY fields whose canonical ``type`` is
``validated_by_client``          ``proposal_list``
everything else                  nothing (409)
===============================  ==================================================

"everything else" is an ALLOW-LIST, not a deny-list of the four post-submission statuses.
``nestor.intake_status`` carries an eighth value the decision table never names (``archived``),
and a later migration may add more; deny-by-default is the only shape that stays correct when
the vocabulary grows.

⛔ THE POLICY IS **NOT** "ONLY ``draft`` IS WRITABLE" — DO NOT "SIMPLIFY" IT TO THAT.

``reviewed`` and ``validated_by_client`` keep ``proposal_list`` fields writable. That is the
client's "keep Nestor's proposal" tick, shipped deliberately on 2026-08-31:

* ``frontend/src/routes/intake.$id.tsx:106`` — ``editable: intake.status === "draft"``
* ``frontend/src/routes/intake.$id.tsx:110-114`` — ``phase: (status === "reviewed" ||
  status === "validated_by_client") ? "validation" : "intake"``
* ``frontend/src/components/intake/IntakeForm.tsx:501`` —
  ``disabled={!editable && !(isValidationPhase && f.type === "proposal_list")}``

A draft-only server rule refuses that tick and NO pre-existing test goes red. The exception is
DERIVED from ``canonical_field(key)["type"]`` — no field key literal appears in this module, so
a second ``proposal_list`` field added to ``app/data/pulse_intake_v1.json`` widens the exception
with no code change (the same discipline as ``app.intake_canonical``).


D-23.2-06 — RESPONSE CODES AND THEIR PRECEDENCE
-----------------------------------------------
The route evaluates, in this order:

0. **Ownership -> 404** — in the ROUTE, before this module is called at all, and it must stay
   there. A cross-tenant caller must not be able to learn whether a field key is valid from the
   response code. ``tests/test_intake_cross_tenant.py::
   test_upsert_answers_cross_tenant_returns_404_answers_unchanged`` writes a NON-canonical key
   cross-tenant and asserts exactly 404; a policy-first order answers 422 and turns a
   tenant-isolation guarantee into an oracle.
1. **Lifecycle -> 409** — status-driven and identical for every key, so it discloses nothing
   per-field; and the client can already read the status from ``GET /intakes/{id}``.
2. **Schema membership -> 422** — a ``field_key`` the canonical form does not define.
3. **Field permission -> 404** — an admin-only ``field_key`` from a client. AFTER membership on
   purpose: an admin key IS a real field, so it passes (2) and is caught here. Existence-hidden
   per D-07, and the detail deliberately does not echo the key back.
4. **Status/field -> 409** — in the validation phase, a known non-admin field that is not a
   ``proposal_list``.
5. **Value -> 422**.

Steps 2-5 are applied PHASE BY PHASE across the whole batch rather than item by item, so the
code a caller sees does not depend on the order they happened to send the items in.

ALL-OR-NOTHING: this function raises on the first violation it finds and the route calls it
BEFORE handing anything to the repository, so a batch with one bad item writes nothing.


SUPERADMIN IS EXEMPT — AND MUST STAY EXEMPT
-------------------------------------------
``check_answer_batch`` returns immediately for ``role == "superadmin"``. Two live writers
depend on it: the AI-review apply path, and ``frontend/src/routes/admin.pulse.intakes.$id.tsx:951``
(the admin edit-mode save, which writes EVERY edited field including the four admin-only ones,
on intakes well past ``draft``). Constraining superadmin here re-creates the live-UAT regression
of 2026-07-13, where a superadmin answer write 500'd and the browser showed "Failed to fetch".

The polarity is ``== "superadmin"`` (exempt) rather than ``!= "user"`` (constrain), so a role
added later is CONSTRAINED by default rather than exempted by omission.


D-23.2-07 — VALUE VALIDATION, BOUNDED
-------------------------------------
Enforce the canonical field's ``type`` and its ``options`` where the schema states them, plus
upper bounds. Do NOT invent constraints the schema does not carry — in particular there is no
format check for ``email`` / ``tel`` / ``date``: the schema states no pattern, and a server
regex that disagrees with ``IntakeForm.tsx``'s browser-side one is how a form and its API drift
apart.

⛔ ``required`` / ``min_length`` / ``min_items`` ARE **NOT** ENFORCED HERE. Someone will
eventually try to "complete" this policy by adding them. That breaks the live client form:

* ``IntakeForm.tsx:214-217`` saves only the DIRTY fields of the current section;
* ``toAnswerInput`` (``IntakeForm.tsx:26-30``) sends ``{value: null, value_json: null}`` for a
  null/undefined value, so CLEARING a field is a normal save;
* ``validateField`` (``IntakeForm.tsx:33-40``) enforces ``required`` in the BROWSER at SUBMIT
  time, not at save time.

Clearing a required field, or saving a section before a required field is filled, therefore
happens on every intake. Enforcing a minimum here 422s the form mid-typing. **An empty value is
ALWAYS accepted for a writable field.** If minimum-constraint enforcement is wanted, its home is
``POST /intakes/{id}/submit``, which is the transition the browser already gates.

⛔ A ``radio`` ANSWER IS NOT ALWAYS A STRING. Two of the three canonical radios carry an
"Anders / Other" option flagged ``allow_text: true``, and ``FieldRenderer.tsx:302-306`` emits
``onChange({choice: opt.value, text: ...})`` for those — an OBJECT, which ``toAnswerInput``
routes to ``value_json``. A "radio => ``value`` in ``options``" rule refuses a live client path
and no pre-existing test catches it. The rule here is therefore DUAL; see :func:`_check_radio`.


THE THREE BOUNDS ARE DoS BOUNDS, NOT BUSINESS RULES
---------------------------------------------------
The canonical schema states no maximum length for any field and no maximum batch size. The
constants below exist only to stop unbounded client JSON inflating a JSONB column and a request
body. They are deliberately far above any plausible real answer, they are REFUSED rather than
truncated (silent truncation would destroy a client's text), and they must not be quoted as
product limits.
"""

from __future__ import annotations

import json
from typing import Any

from app.intake_canonical import admin_only_field_keys, canonical_field

# --- DoS bounds (see the module docstring — NOT business rules) -------------------------

#: Max characters in a single ``value``, and in any string nested inside ``value_json``.
_MAX_VALUE_CHARS = 20_000
#: Max characters in the JSON serialisation of a single ``value_json``.
_MAX_JSON_CHARS = 100_000
#: Max items in one batch. The largest canonical section holds 6 fields; this is headroom.
_MAX_BATCH_ITEMS = 100

# --- Lifecycle allow-lists (D-23.2-05) --------------------------------------------------

#: Statuses in which a client may write any non-admin canonical field.
_OPEN_STATUSES = frozenset({"draft"})
#: Statuses in which a client may write ONLY ``proposal_list`` fields (the validation phase).
_PROPOSAL_ONLY_STATUSES = frozenset({"reviewed", "validated_by_client"})
#: The schema ``type`` that stays writable during the validation phase. Derived, never a key.
_PROPOSAL_TYPE = "proposal_list"

# --- Value-shape families ---------------------------------------------------------------

#: Types whose answer is a plain string in ``value`` (no ``value_json``). No format is checked.
_STRING_TYPES = frozenset({"text", "longtext", "email", "tel", "date"})
#: Types whose answer is a JSON ARRAY in ``value_json`` (no ``value``).
_ARRAY_TYPES = frozenset({"list", "proposal_list", "files"})
#: Types whose answer is a JSON OBJECT in ``value_json`` (no ``value``).
_OBJECT_TYPES = frozenset({"file"})
#: Display-only types. The schema states no input contract for these; inventing one is
#: out of scope (D-23.2-07). Bounds still apply.
_DISPLAY_ONLY_TYPES = frozenset({"download"})

_SUPERADMIN_ROLE = "superadmin"


class AnswerWriteViolation(Exception):
    """A refused answer write, carrying the HTTP status the API layer should answer with.

    ``code`` is an HTTP STATUS INTEGER (404 / 409 / 422), not a machine-readable error string.
    It is deliberately NOT ``app.api.errors.CodedError``: that class is the curated,
    user-facing, translated-message contract, and these refusals are policy denials whose
    detail must stay generic (an admin-only refusal in particular must not name the field it
    is hiding). The API layer maps ``code`` + ``detail`` onto the response.
    """

    def __init__(self, code: int, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def check_answer_batch(items: list[dict], *, intake_status: str, role: str) -> None:
    """Validate a whole answer batch, or raise :class:`AnswerWriteViolation`. Returns ``None``.

    ``items`` are the plain dicts the route produces from its request model — each carrying
    ``field_key`` / ``value`` / ``value_json`` and nothing else (no ``space_id``, no
    ``intake_id``; those come from the identity and the path).

    Call this AFTER the ownership check and BEFORE any write. The route relies on the
    raise-before-write ordering for the all-or-nothing guarantee.
    """
    # Superadmin is exempt — see the module docstring (2026-07-13 regression).
    if role == _SUPERADMIN_ROLE:
        return

    # (1) Lifecycle. Allow-list, so an unknown/new status denies by default.
    if intake_status not in _OPEN_STATUSES and intake_status not in _PROPOSAL_ONLY_STATUSES:
        raise AnswerWriteViolation(
            409, "This intake can no longer be edited."
        )

    # Batch size sits here rather than first so the stated precedence holds: a client on a
    # frozen intake gets the lifecycle 409 whatever the batch looks like. The bound protects
    # the DB write, and nothing expensive happens between these two checks.
    if len(items) > _MAX_BATCH_ITEMS:
        raise AnswerWriteViolation(422, "Too many answers in one save.")

    proposal_only = intake_status in _PROPOSAL_ONLY_STATUSES
    admin_keys = admin_only_field_keys()

    # Phases (2)-(5) run ACROSS the batch, not per item, so the response code does not depend
    # on the order the client happened to send the items in.

    # (2) Schema membership -> 422.
    fields: list[tuple[dict, dict]] = []
    for item in items:
        field_key = item.get("field_key")
        field = canonical_field(field_key) if isinstance(field_key, str) else None
        if field is None:
            raise AnswerWriteViolation(422, "Unknown field in this form.")
        fields.append((item, field))

    # (3) Field permission -> 404, existence-hidden. The detail must NOT name the key: this
    # code exists to hide that the field is real, and echoing it back undoes that.
    for item, _field in fields:
        if item["field_key"] in admin_keys:
            raise AnswerWriteViolation(404, "Field not found.")

    # (4) Status/field -> 409 (validation phase: proposal_list only).
    if proposal_only:
        for _item, field in fields:
            if field.get("type") != _PROPOSAL_TYPE:
                raise AnswerWriteViolation(
                    409, "This answer can no longer be changed at this stage."
                )

    # (5) Value -> 422.
    for item, field in fields:
        _check_value(item, field)


# ---------------------------------------------------------------------------
# Value rules
# ---------------------------------------------------------------------------


def _check_value(item: dict, field: dict) -> None:
    """Type + options + bounds for ONE item. Raises 422, or returns ``None``."""
    value = item.get("value")
    value_json = item.get("value_json")

    _check_bounds(value, value_json)

    # EMPTY IS ALWAYS ACCEPTED — save-as-you-go (see the module docstring). This is the branch
    # that makes `required` / `min_length` / `min_items` non-enforcement true in practice.
    if value_json is None and (value is None or value == ""):
        return

    field_type = field.get("type")

    if field_type in _DISPLAY_ONLY_TYPES:
        return

    if field_type in _STRING_TYPES:
        if value_json is not None:
            raise AnswerWriteViolation(422, "This answer must be plain text.")
        if not isinstance(value, str):
            raise AnswerWriteViolation(422, "This answer must be plain text.")
        return

    if field_type == "radio":
        _check_radio(field, value, value_json)
        return

    if field_type in _ARRAY_TYPES:
        if value is not None:
            raise AnswerWriteViolation(422, "This answer must be a list.")
        if not isinstance(value_json, list):
            raise AnswerWriteViolation(422, "This answer must be a list.")
        # ``max_items`` (list / proposal_list) and ``max_files`` (files) are the only upper
        # counts the schema states. ``min_items`` is NOT enforced — save-as-you-go.
        cap = field.get("max_items")
        if cap is None:
            cap = field.get("max_files")
        if isinstance(cap, int) and len(value_json) > cap:
            raise AnswerWriteViolation(422, "Too many entries for this answer.")
        return

    if field_type in _OBJECT_TYPES:
        if value is not None:
            raise AnswerWriteViolation(422, "This answer must be a file reference.")
        if not isinstance(value_json, dict):
            raise AnswerWriteViolation(422, "This answer must be a file reference.")
        return

    # A canonical type this module does not classify. Deny by default rather than wave it
    # through: an unclassified type means the schema grew and this file did not.
    raise AnswerWriteViolation(422, "This answer has an unsupported shape.")


def _check_radio(field: dict, value: Any, value_json: Any) -> None:
    """The DUAL radio rule — a plain option string, OR the ``allow_text`` ``{choice, text}`` object.

    ``FieldRenderer.tsx:294-323`` emits ``opt.value`` (a string) for an ordinary option and
    ``{choice, text}`` for an option carrying ``allow_text``. Accepting only the first shape
    422s the live "Anders / Other" path on the two canonical radios that offer it.

    No key literal here either (D-23.2-02): which radios carry ``allow_text`` is read out of
    the field's own ``options``, so a third one added to the JSON is handled with no edit.
    """
    options = field.get("options") or []
    option_values = {o.get("value") for o in options if isinstance(o, dict)}
    allow_text_values = {
        o.get("value") for o in options if isinstance(o, dict) and o.get("allow_text")
    }

    if value_json is None:
        if not isinstance(value, str) or value not in option_values:
            raise AnswerWriteViolation(422, "This answer is not one of the offered options.")
        return

    if value is not None:
        raise AnswerWriteViolation(422, "This answer is not one of the offered options.")
    if not isinstance(value_json, dict):
        raise AnswerWriteViolation(422, "This answer is not one of the offered options.")
    if set(value_json) - {"choice", "text"}:
        raise AnswerWriteViolation(422, "This answer is not one of the offered options.")
    if value_json.get("choice") not in allow_text_values:
        # Either the option does not exist, or it exists but carries no free-text box — in
        # which case the renderer would have sent a plain string, not an object.
        raise AnswerWriteViolation(422, "This answer is not one of the offered options.")
    text = value_json.get("text")
    if text is not None and not isinstance(text, str):
        raise AnswerWriteViolation(422, "This answer is not one of the offered options.")


def _check_bounds(value: Any, value_json: Any) -> None:
    """The three DoS bounds. REFUSE, never truncate — truncation destroys a client's text."""
    if value is not None:
        if not isinstance(value, str):
            raise AnswerWriteViolation(422, "This answer must be plain text.")
        if len(value) > _MAX_VALUE_CHARS:
            raise AnswerWriteViolation(422, "This answer is too long.")

    if value_json is not None:
        try:
            encoded = json.dumps(value_json)
        except (TypeError, ValueError):
            raise AnswerWriteViolation(422, "This answer could not be stored.") from None
        if len(encoded) > _MAX_JSON_CHARS:
            raise AnswerWriteViolation(422, "This answer is too long.")
        if _has_overlong_string(value_json):
            raise AnswerWriteViolation(422, "This answer is too long.")


def _has_overlong_string(node: Any) -> bool:
    """True when any string nested anywhere in ``node`` exceeds :data:`_MAX_VALUE_CHARS`."""
    if isinstance(node, str):
        return len(node) > _MAX_VALUE_CHARS
    if isinstance(node, list):
        return any(_has_overlong_string(child) for child in node)
    if isinstance(node, dict):
        return any(_has_overlong_string(child) for child in node.values())
    return False
