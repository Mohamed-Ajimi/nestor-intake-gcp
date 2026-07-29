"""D-R4 question grouping — the LLM PROPOSES, Python CLAMPS. Phase 15.6 plan 01.

WHAT THIS REPLACES AND WHY. Until this module, `_divide_from_winners` dealt the top
`_D6_TOP_K` winners to every stream and the remainder round-robin BY POSITION
(`research_division.py:867-874`). On run 7dcf51d5 the client's coffee question landed
on gemini because of where it fell in the deal, not because gemini suits Benelux
retail — and because only the top 3 were dispatched as corroboration copies, roughly
12 of 15 winners got no `corroboration_key` at all. Grouping by shared research
groundwork replaces position with TOPIC, and sending every group to every provider is
what finally populates `corroboration_key` for every claim instead of ~3 of 15.

THE GROUP RECORD — the contract every consumer in this phase reads. Plans 15.6-03
(dispatch), 15.6-04 (coverage guard) and 15.6-06 (pipeline) all read these keys, so
change none of them without changing those::

    group_id   str    engine-authored. "g1".."g5" for mandate groups. "d1" -- and
                      only ever d1, never d2 -- for the ONE cross-cutting discovery
                      group, which exists ONLY when a __discovery__-parented question
                      exists (D-W3-5.3). There is NO reserved slot: with no
                      cross-cutting question the ids are g1..gN and nothing else.
                      Becomes the angle corroboration_key, so it must be stable
                      within a run.
    bracket    str    GROUP_BRACKET_MANDATE or GROUP_BRACKET_DISCOVERY
    members    list   winner dicts COPIED from the winners list, in ascending rank
    parents    list   ordered, deduped union of the members' `parents`/`parent`
    parent     str    the highest-ranked member's parent; becomes the angle focus_area
    rank       int    min member rank; drives stakes via `_stakes_for_rank`
    client_parents
               list   ordered, deduped parents of the MANDATE members only --
                      discovery riders EXCLUDED. THIS, not `parents`, is what decides
                      whether a group is mixed: a group holding one client question
                      plus a discovery rider is the INTENDED shape under D-W3-5.2 and
                      must never be flagged as mixed. See [[gate-integrity-traps]] --
                      the ZERO-claims warning that cried wolf about facets the call
                      never saw is half of why nobody noticed 278 lost claims.
    riders     int    how many members are discovery questions riding along.
                      Telemetry only.
    why        str    the model's own sentence, bounded to `_WHY_MAX_CHARS`. LOG AND
                      TELEMETRY ONLY -- it is NEVER interpolated into a research query
                      and never reaches a provider.

THE RULE ABOVE `parent` AND `parents`: both are STAMPED IN PYTHON FROM THE
ASSIGNMENT, NEVER READ FROM GROUPING OUTPUT. So is `group_id`. This is the same rule
`enforce_scope_guard` and `workshop._parse_orientation` already apply, and the reason
is that a grouping LLM's output is UNTRUSTED INPUT on a path to three third-party
research providers (T-15.2-60): grouping supplies MEMBERSHIP and nothing else. The
tool schema in `tools.py` enforces the other half — it admits integers only, so there
is no string in grouping output that could become a parent even by accident.

Everything in this module is PURE and NEVER RAISES, except `group_winners`, which
makes exactly one audited LLM call and also never raises. On any failure the run falls
back to ONE GROUP PER CLIENT QUESTION and records a D-12 degradation.

Deliberately NOT imported here:
  * `research_division._D6_STREAMS` and `_SUBQ_CHARS` — plan 15.6-03 is editing that
    module in this same phase, and pinning its values from here is exactly the
    exact-set trap that turned phase 15.5's merged tree red. The stream count arrives
    as a PARAMETER; the winner-line bound is duplicated locally with a comment.
  * `workshop` — `group_winners` reads its model env var directly rather than import
    it, to keep this module free of a circular import.
  * the facet-resolution seam in `claim_attribution` — plan 15.6-04 owns wiring it in.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, Sequence

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants. One comment per number saying what the number is FOR, in the
# `research_division.py:126-172` style.
# ---------------------------------------------------------------------------

# How many groups a run may dispatch. D-W3-1 makes 5 a HARD CEILING TAKEN BY THE
# OPERATOR, so the env knob may only ever LOWER it — that is what the `min(5, ...)`
# is for, and it is not defensive tidiness. There is no rule that lets the ceiling
# rise for a complex brief; spec § 4 asked for a rising dial and the operator
# overrode that half in session on 2026-07-29.
#
# THE CONSEQUENCE THE OPERATOR ACCEPTED, recorded so nobody "fixes" it later: a brief
# with 7 genuinely distinct topics gets ONE GRAB-BAG GROUP. Fewer than 5 groups is
# also a normal, unremarked outcome — there is no floor and nothing pads.
_D6_MAX_GROUPS = min(5, max(1, int(os.environ.get("NESTOR_TRIBUNAL_D6_MAX_GROUPS", "5"))))

# How many questions one group may carry — § 4 requirement 2, whose risk is a provider
# writing six thin paragraphs instead of one deep report.
#
# THE ARITHMETIC: `research_division._D6_MAX_WINNERS` is 15 and the ceiling above is 5
# groups, so 15 / 5 = 3 is the INFEASIBILITY FLOOR (a cap below 3 cannot be satisfied
# at all) and 4 leaves slack. Hence `max(3, ...)`.
#
# THE PRECEDENCE, STATED EXPLICITLY BECAUSE THE TWO COLLIDE: the ceiling is an
# OPERATOR decision and this size cap is the engine's own. WHEN THEY COLLIDE THE
# CEILING WINS — an oversized group is ACCEPTED and logged loudly, never split into a
# sixth group. Every question is still researched, so that is a note, not a
# degradation.
_D6_MAX_GROUP_SIZE = max(3, int(os.environ.get("NESTOR_TRIBUNAL_D6_MAX_GROUP_SIZE", "4")))

#: The two bracket values, EXPORTED because four other modules test against them and
#: none of them may retype a string literal.
GROUP_BRACKET_MANDATE = "mandate"
GROUP_BRACKET_DISCOVERY = "discovery"

# A winner's `source` marking it as a discovery question rather than one of the
# client's. It happens to be the same literal as GROUP_BRACKET_DISCOVERY and is a
# DIFFERENT concept: this one describes a MEMBER, that one describes a GROUP. A
# mandate group can legitimately hold members with this source (D-W3-5.2 riders).
_WINNER_SOURCE_DISCOVERY = "discovery"

# The bound on the model's own `why_grouped` sentence. It is log/telemetry text and
# never reaches a provider, but it is still model output being stored, so it is
# bounded on the same principle as every other model string in this engine.
_WHY_MAX_CHARS = 200

# A rank that sorts LAST, for a winner whose `rank` is missing or garbled.
_RANK_LAST = 10**9


# ---------------------------------------------------------------------------
# Tolerant readers. Local ON PURPOSE — see the module docstring.
# ---------------------------------------------------------------------------


def _coerce_json(value: Any, expect: type) -> Any:
    """Coerce a tool-input field the model returned as a JSON-encoded STRING.

    F-01 (live run 4cbb5311, 2026-07-22): the model sometimes emits object/array
    tool-input fields — or `input` itself — as JSON strings, which crashed the verdict
    parsers with `'str' object has no attribute 'get'`. Mirrors
    `skeptic._coerce_json`; duplicated rather than imported because that module
    reaches the provider SDK at import time and this one must stay stdlib-pure.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, expect) else None


def _rank_of(entry: Any) -> int:
    """One winner's tournament rank, defensively. Missing or garbled sorts LAST."""
    try:
        value = (entry or {}).get("rank")
    except Exception:  # noqa: BLE001 — a reader never raises
        return _RANK_LAST
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return _RANK_LAST
    return rank if rank >= 1 else _RANK_LAST


def _parents_of(entry: Any) -> list[str]:
    """The ordered parent labels one winner covers.

    UNION OVER `parents`, FALLING BACK TO `parent`. Mirrors
    `workshop_rank._parents_of` and is duplicated rather than imported for the reason
    the module docstring gives: a plan in this same phase is editing that module. The
    plural matters — plan 15.2-10's near-duplicate collapse can carry TWO client
    questions onto ONE winner, so a coverage union written against `parent` alone
    would report a false scope violation on valid clustering.
    """
    out: list[str] = []
    try:
        raw_parents = (entry or {}).get("parents")
    except Exception:  # noqa: BLE001 — a reader never raises
        return out
    if isinstance(raw_parents, list):
        for raw in raw_parents:
            label = str(raw or "").strip()
            if label and label not in out:
                out.append(label)
    if out:
        return out
    try:
        label = str((entry or {}).get("parent") or "").strip()
    except Exception:  # noqa: BLE001
        return out
    return [label] if label else out


def _own_parent(entry: Any) -> str:
    """A winner's single `parent` label, defensively. Empty string when absent."""
    try:
        return str((entry or {}).get("parent") or "").strip()
    except Exception:  # noqa: BLE001 — a reader never raises
        return ""


def _is_rider(entry: Any) -> bool:
    """True when this member is a DISCOVERY question riding along (D-W3-5.2)."""
    try:
        return str((entry or {}).get("source") or "").strip() == _WINNER_SOURCE_DISCOVERY
    except Exception:  # noqa: BLE001 — a reader never raises
        return False


def _bounded_why(raw: Any) -> str:
    """The model's own sentence, collapsed and bounded. LOG AND TELEMETRY ONLY."""
    try:
        text = " ".join(str(raw or "").split())
    except Exception:  # noqa: BLE001 — a reader never raises
        return ""
    return text[:_WHY_MAX_CHARS]


def _why_for(whys: Any, *, group_position: int, member_indices: Sequence[int]) -> str:
    """Find the model's sentence for a group, after clamping has reshaped it.

    Accepts BOTH shapes, deliberately. A DICT keyed by WINNER INDEX is what
    `group_winners` passes, because `clamp_groups` merges, splits and re-sorts groups
    and so a positional list stops meaning anything the moment it does: keying on the
    winner index survives every one of those moves and a group inherits the sentence
    of its best-ranked member. A LIST is accepted positionally for direct callers and
    tests. Anything else yields "".
    """
    if isinstance(whys, dict):
        for index in member_indices:
            found = whys.get(index)
            if found:
                return _bounded_why(found)
        return ""
    if isinstance(whys, list):
        if 0 <= group_position < len(whys):
            return _bounded_why(whys[group_position])
    return ""


# ---------------------------------------------------------------------------
# build_groups — the ONLY place a group record is created. PURE.
# ---------------------------------------------------------------------------


def build_groups(
    assignment: Any,
    winners: Any,
    *,
    bracket: str = GROUP_BRACKET_MANDATE,
    whys: Any = None,
) -> list[dict[str, Any]]:
    """Turn a list-of-index-lists into the group record above. PURE. NEVER RAISES.

    Every string a consumer reads is stamped HERE, in Python, from the `winners` list:
    `parent`, `parents`, `client_parents` and `group_id` are derived from the
    assignment, never read from grouping output. The only model-authored text that
    survives is a member's own `text` (copied verbatim, exactly as the pre-grouping
    dispatch already sent it) and `why`, which is bounded and never leaves the log.

    `group_id` is `f"g{n}"` over the SURVIVING groups for the mandate bracket, so the
    ids are dense from g1. For the discovery bracket it is the literal `"d1"`: there
    is AT MOST ONE cross-cutting discovery group ever (D-W3-5.3), so a counter here
    would imply a `"d2"` that cannot exist.

    `parent` is the highest-ranked member's parent. Riders never participate in that
    choice because they are attached AFTER this function runs — see
    `attach_discovery_riders`, which deliberately leaves `parent`, `rank` and
    `client_parents` frozen so a rider can never steal its host's facet.

    A group whose members all resolve away is OMITTED rather than returned empty.
    """
    out: list[dict[str, Any]] = []
    try:
        pool = list(winners or [])
        is_discovery_bracket = bracket == GROUP_BRACKET_DISCOVERY

        for position, raw_group in enumerate(list(assignment or [])):
            if not isinstance(raw_group, (list, tuple)):
                continue

            # Members are COPIES, ordered by (rank, position within the assignment) —
            # stable, total and therefore replayable, the same discipline
            # `_normalise_winners` applies.
            picked: list[tuple[int, int, int, dict[str, Any]]] = []
            for order, raw_index in enumerate(raw_group):
                if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                    continue
                if not 0 <= raw_index < len(pool):
                    continue
                member = pool[raw_index]
                if not isinstance(member, dict):
                    continue
                picked.append((_rank_of(member), order, raw_index, dict(member)))
            if not picked:
                continue
            picked.sort(key=lambda item: (item[0], item[1]))

            members = [item[3] for item in picked]
            member_indices = [item[2] for item in picked]

            parents: list[str] = []
            client_parents: list[str] = []
            riders = 0
            for member in members:
                labels = _parents_of(member)
                if _is_rider(member):
                    riders += 1
                else:
                    for label in labels:
                        if label not in client_parents:
                            client_parents.append(label)
                for label in labels:
                    if label not in parents:
                        parents.append(label)

            group_id = "d1" if is_discovery_bracket else "g%d" % (len(out) + 1)

            out.append(
                {
                    "group_id": group_id,
                    "bracket": (
                        GROUP_BRACKET_DISCOVERY
                        if is_discovery_bracket
                        else GROUP_BRACKET_MANDATE
                    ),
                    "members": members,
                    "parents": parents,
                    "parent": _own_parent(members[0]),
                    "rank": min(_rank_of(member) for member in members),
                    "client_parents": client_parents,
                    "riders": riders,
                    "why": _why_for(
                        whys, group_position=position, member_indices=member_indices
                    ),
                }
            )

        if is_discovery_bracket and len(out) > 1:
            # Not a supported input: D-W3-5.3 allows exactly one cross-cutting group.
            # Never silently mint a "d2" — say so and keep the first.
            log.error(
                "question_grouping: build_groups was asked for %d discovery groups but "
                "D-W3-5.3 allows exactly one cross-cutting group — keeping the first "
                "and dropping %d",
                len(out),
                len(out) - 1,
            )
            out = out[:1]
    except Exception as exc:  # noqa: BLE001 — grouping never breaks a run
        log.error("question_grouping: build_groups failed: %r", exc, exc_info=True)
        return []
    return out


# ---------------------------------------------------------------------------
# validate_groups — read grouping output, TOTALLY. PURE.
# ---------------------------------------------------------------------------


def _place_orphan(
    assignment: list[list[int]], pool: Sequence[Any], orphan: int
) -> int:
    """Which group an unnamed winner joins. DETERMINISTIC. Returns a group position.

    First choice: the group already holding the HIGHEST-RANKED winner that shares this
    winner's `parent` — its shared groundwork is most likely to be there already.
    Otherwise: the group with the FEWEST members, ties broken by the LOWEST group
    position, so the placement never depends on set iteration order.
    """
    parent = _own_parent(pool[orphan]) if 0 <= orphan < len(pool) else ""

    best_position = -1
    best_rank = _RANK_LAST + 1
    if parent:
        for position, group in enumerate(assignment):
            for index in group:
                if not 0 <= index < len(pool):
                    continue
                if _own_parent(pool[index]) != parent:
                    continue
                rank = _rank_of(pool[index])
                if rank < best_rank:
                    best_rank = rank
                    best_position = position
    if best_position >= 0:
        return best_position

    return min(range(len(assignment)), key=lambda p: (len(assignment[p]), p))


def validate_groups(raw_groups: Any, winners: Any) -> tuple[list[list[int]], list[str]]:
    """Read grouping output into a TOTAL, DISJOINT index assignment. NEVER RAISES.

    Reads ONLY `member_numbers` (integers) and `why_grouped` (string) off each entry;
    anything else the model attached to its objects is IGNORED, which is what makes
    the index-addressed schema in `tools.py` an actual control rather than a hope.

    Returns `(assignment, notes)`. On unusable input, or if the totality
    post-condition fails, returns `([], notes)` so the caller falls back rather than
    dispatching an incomplete set — a partial assignment silently drops a client's
    question, and that is the one outcome this engine must never produce quietly.

    Notes come back as plain-words sentences, never codes (Shared Pattern 5).
    """
    notes: list[str] = []
    assignment: list[list[int]] = []

    try:
        pool = list(winners or [])
        total = len(pool)
        groups = _coerce_json(raw_groups, list)
        if groups is None:
            notes.append(
                "The grouping step did not return a list of groups at all, so its "
                "output could not be used."
            )
            return [], notes
        if total == 0:
            notes.append(
                "There were no ranked questions to group, so grouping had nothing to "
                "do."
            )
            return [], notes

        claimed: set[int] = set()
        out_of_range = 0
        duplicated = 0
        unusable_entries = 0

        for raw_entry in groups:
            entry = _coerce_json(raw_entry, dict)
            if entry is None:
                unusable_entries += 1
                continue
            numbers = _coerce_json(entry.get("member_numbers"), list)
            if numbers is None:
                unusable_entries += 1
                continue

            indices: list[int] = []
            for raw_number in numbers:
                # The model is given 1-BASED numbers; the conversion to 0-based
                # happens HERE, in one place, and nowhere else in this module.
                # `bool` is an `int` subclass and is NOT a question number.
                if isinstance(raw_number, bool) or not isinstance(raw_number, int):
                    out_of_range += 1
                    continue
                index = raw_number - 1
                if not 0 <= index < total:
                    out_of_range += 1
                    continue
                if index in claimed:
                    # FIRST WINS — the same rule D-W2-3 and the facet-resolution seam
                    # in `claim_attribution` already apply.
                    duplicated += 1
                    continue
                claimed.add(index)
                indices.append(index)

            if indices:
                assignment.append(indices)
            else:
                # A group left empty once out-of-range and duplicate numbers are gone
                # is dropped: it would dispatch a paid call with nothing in it.
                unusable_entries += 1

        if out_of_range:
            notes.append(
                "%d question number(s) the grouping step returned pointed at no "
                "question in the list, so they were ignored and the questions "
                "themselves were placed by the engine instead." % out_of_range
            )
        if duplicated:
            notes.append(
                "%d question(s) were claimed by more than one group, so each stayed "
                "in the first group that named it." % duplicated
            )
        if unusable_entries:
            notes.append(
                "%d group(s) the grouping step returned held no usable question "
                "numbers and were dropped." % unusable_entries
            )

        if not assignment:
            notes.append(
                "The grouping step returned no group holding a usable question "
                "number, so its output could not be used."
            )
            return [], notes

        # TOTALITY. Every winner the model forgot is placed DETERMINISTICALLY rather
        # than dropped: an LLM deciding grouping is an LLM that can drop a question,
        # and a dropped winner is a client question that silently goes unresearched.
        missing = [index for index in range(total) if index not in claimed]
        for orphan in missing:
            assignment[_place_orphan(assignment, pool, orphan)].append(orphan)
        if missing:
            notes.append(
                "%d question(s) the grouping step left out of every group were placed "
                "with the questions closest to them, so none went unresearched."
                % len(missing)
            )

        # THE POST-CONDITION, ASSERTED IN CODE AND NOT ONLY IN A TEST.
        union: set[int] = set()
        disjoint = True
        for group in assignment:
            if union & set(group):
                disjoint = False
            union |= set(group)
        if union != set(range(total)) or not disjoint:
            log.error(
                "question_grouping: the totality post-condition FAILED — %d of %d "
                "question(s) assigned, disjoint=%s. Falling back rather than "
                "dispatching an incomplete set.",
                len(union),
                total,
                disjoint,
            )
            notes.append(
                "The engine could not place every question into exactly one group, so "
                "grouping was abandoned rather than risk leaving a question "
                "unresearched."
            )
            return [], notes
    except Exception as exc:  # noqa: BLE001 — grouping never breaks a run
        log.error("question_grouping: validate_groups failed: %r", exc, exc_info=True)
        return [], notes

    return assignment, notes


# ---------------------------------------------------------------------------
# clamp_groups — the ceiling, mandate-strict, and the size cap. PURE.
# ---------------------------------------------------------------------------


def _group_min_rank(group: Sequence[int], pool: Sequence[Any]) -> int:
    """The best (lowest) rank in a group. An empty group sorts LAST."""
    ranks = [_rank_of(pool[i]) for i in group if 0 <= i < len(pool)]
    return min(ranks) if ranks else _RANK_LAST


def _group_parents(group: Sequence[int], pool: Sequence[Any]) -> list[str]:
    """The ordered distinct `parent` labels in a group. A LIST, never a set."""
    out: list[str] = []
    for index in group:
        if not 0 <= index < len(pool):
            continue
        label = _own_parent(pool[index])
        if label and label not in out:
            out.append(label)
    return out


def clamp_groups(
    assignment: Any,
    winners: Any,
    *,
    max_groups: int,
    max_size: int,
    prefer_single_parent: bool,
) -> tuple[list[list[int]], list[str]]:
    """Clamp a proposed assignment to the ceiling, the parent rule and the size cap.

    PURE, DETERMINISTIC, NEVER RAISES. The order below is the whole contract and is
    load-bearing — mandate-strict, then the CEILING, then size, then sort.

    `prefer_single_parent` is `True` IN PRODUCTION, ALWAYS. It is a parameter so that
    BOTH behaviours are testable in one place, not so a caller can choose: it is
    **not** a feature flag and there is **no dual run** — D-03 forbids the latter, not
    the former.

    WHY MANDATE-STRICT EXISTS (D-W3-5). On the primary D8 fact-list path a claim's
    `facet` is stamped in Python FROM THE ANGLE (`steps.py:2400`) and passed at three
    `fact_source="fact_list"` call sites (`:2435`, `:2498`, `:2570` — find them by
    symbol, the numbers drift), and the D8 contract itself (`facts.py:298` —
    ``STATEMENT<TAB>SOURCE_URL<TAB>QUALITY<TAB>CERTAINTY<TAB>EVIDENCE``) carries NO
    FACET COLUMN. So everything sharing a group shares one attribution: a mixed group
    gives every one of its claims the top-ranked member's parent, INCLUDING the claims
    answering the other client question. A single-parent group makes `facet` exact by
    construction. The seeded FACET at `steps.py:1627` is the `distiller_fallback` path
    only and does NOT correct this.

    THE PRECEDENCE, applied twice below: the ≤ `max_groups` ceiling is an OPERATOR
    decision (D-W3-1); the parent split and the size cap are the engine's own derived
    rules. Both yield to the ceiling — a mixed or oversized group is kept and NOTED,
    never split into one group past the ceiling.

    Returns `(assignment, notes)`.
    """
    notes: list[str] = []
    try:
        pool = list(winners or [])
        ceiling = max(1, int(max_groups))
        size_cap = max(1, int(max_size))

        work: list[list[int]] = []
        for raw_group in list(assignment or []):
            if isinstance(raw_group, (list, tuple)):
                group = [
                    i
                    for i in raw_group
                    if isinstance(i, int)
                    and not isinstance(i, bool)
                    and 0 <= i < len(pool)
                ]
                if group:
                    work.append(list(group))
        if not work:
            return [], notes

        # --- 0. MANDATE STRICT (D-W3-5) ------------------------------------
        # Split any group carrying more than one distinct parent into one group per
        # parent, ONLY WHILE the ceiling permits. When it does not, keep the mixed
        # group and NOTE it. When the flag is false this step does nothing at all.
        if prefer_single_parent:
            position = 0
            while position < len(work):
                group = work[position]
                buckets: dict[str, list[int]] = {}
                for index in group:
                    buckets.setdefault(_own_parent(pool[index]), []).append(index)
                if len(buckets) <= 1:
                    position += 1
                    continue

                # Best-ranked parent stays in place; the rest split off in rank order,
                # so the split is independent of dict insertion order.
                ordered = sorted(
                    buckets.items(),
                    key=lambda item: (_group_min_rank(item[1], pool), item[0]),
                )
                room = ceiling - len(work)
                if room <= 0:
                    notes.append(
                        "A group had to keep questions from %d different client "
                        "questions because splitting it would have needed more than "
                        "the %d groups this run allows."
                        % (len(buckets), ceiling)
                    )
                    position += 1
                    continue

                taken = ordered[1 : 1 + room]
                leftover = ordered[1 + room :]
                work[position] = list(ordered[0][1])
                for _label, members in taken:
                    work.append(list(members))
                if leftover:
                    for _label, members in leftover:
                        work[position].extend(members)
                    notes.append(
                        "A group still holds questions from %d different client "
                        "questions because separating them would have needed more "
                        "than the %d groups this run allows."
                        % (1 + len(leftover), ceiling)
                    )
                else:
                    notes.append(
                        "One group was separated into %d groups so that each covers a "
                        "single client question." % (1 + len(taken))
                    )
                position += 1

        # --- 1. THE CEILING (D-W3-1) ---------------------------------------
        # Merge the two WEAKEST groups until the count fits. Weakest = highest minimum
        # member rank, ties broken by the LATER position.
        while len(work) > ceiling:
            weakest_first = sorted(
                range(len(work)),
                key=lambda p: (-_group_min_rank(work[p], pool), -p),
            )

            chosen: Optional[tuple[int, int]] = None
            if prefer_single_parent:
                # Prefer a merge of two SAME-PARENT groups over one that would create a
                # mixed group; only mix when no same-parent merge is available.
                for first in weakest_first:
                    for second in weakest_first:
                        if first == second:
                            continue
                        merged_parents = set(_group_parents(work[first], pool)) | set(
                            _group_parents(work[second], pool)
                        )
                        if len(merged_parents) <= 1:
                            chosen = (first, second)
                            break
                    if chosen is not None:
                        break

            forced_mix = False
            if chosen is None:
                chosen = (weakest_first[0], weakest_first[1])
                merged_parents = set(_group_parents(work[chosen[0]], pool)) | set(
                    _group_parents(work[chosen[1]], pool)
                )
                forced_mix = len(merged_parents) > 1

            keep, drop = min(chosen), max(chosen)
            work[keep] = work[keep] + work[drop]
            del work[drop]
            notes.append(
                "Two groups were merged so the run stays within the %d groups it "
                "allows." % ceiling
            )
            if forced_mix and prefer_single_parent:
                # The ONLY way a mandate group may hold two client questions under
                # D-W3-5. Plan 15.6-03 warns on exactly this condition.
                notes.append(
                    "That merge had to put two different client questions in one "
                    "group, because no two groups covering the same client question "
                    "were available to merge instead."
                )

        # --- 2. THEN SIZE (§ 4 requirement 2) ------------------------------
        # Split the weakest-ranked tail off an oversized group, ONLY WHILE the ceiling
        # permits. When it does not, the ceiling wins — see the warning after the sort.
        position = 0
        while position < len(work):
            if len(work[position]) > size_cap and len(work) < ceiling:
                ordered_members = sorted(
                    work[position], key=lambda i: (_rank_of(pool[i]), i)
                )
                work[position] = ordered_members[:size_cap]
                work.append(ordered_members[size_cap:])
                notes.append(
                    "A group holding more than %d questions was split by rank so no "
                    "single research call carries too many." % size_cap
                )
            position += 1

        # --- 3. SORT so g1 holds rank 1. Renumbering happens in build_groups. --
        work.sort(key=lambda group: (_group_min_rank(group, pool), group[:1]))

        # The oversized warning is emitted HERE, after the sort, so the group id it
        # names is the id `build_groups` will actually assign.
        for position, group in enumerate(work):
            if len(group) > size_cap:
                log.warning(
                    "question_grouping: group %s holds %d questions, above the cap of "
                    "%d, and was NOT split because the run allows at most %d groups. "
                    "The group ceiling is an operator decision and the size cap is "
                    "not, so the ceiling wins and the oversized group is dispatched "
                    "as it stands.",
                    "g%d" % (position + 1),
                    len(group),
                    size_cap,
                    ceiling,
                )
                notes.append(
                    "One group carries %d questions, more than the %d this run aims "
                    "for, because splitting it would have needed more than the %d "
                    "groups allowed. Every question is still researched."
                    % (len(group), size_cap, ceiling)
                )
    except Exception as exc:  # noqa: BLE001 — grouping never breaks a run
        log.error("question_grouping: clamp_groups failed: %r", exc, exc_info=True)
        return [], notes

    return work, notes


# ---------------------------------------------------------------------------
# fallback_groups — D-W3-2's deterministic replacement. PURE.
# ---------------------------------------------------------------------------


def fallback_groups(winners: Any, client_questions: Any) -> tuple[list[list[int]], str]:
    """ONE GROUP PER CLIENT QUESTION, in client-question order. NEVER RAISES.

    D-W3-2's deterministic replacement for the deleted top-k / round-robin machinery.
    Each group holds every winner whose `parent` matches that label; a winner whose
    parent matches no label joins the FIRST group, the same orphan rule
    `build_mission_brief_from_winners` already applies at
    `research_division.py:577-587` — a label typo must never lose a winner. Empty
    groups are dropped.

    IT IS NOT CLAMPED TO `_D6_MAX_GROUPS`, AND THAT IS THE ACCEPTED SPEND CONSEQUENCE
    OF D-W3-2. Six client questions is 6 x 3 = 18 paid calls, above the happy-path
    ceiling of 5 x 3 = 15. This was shown to the operator and accepted: on the
    degraded path, covering every client question beats holding the spend line. It
    collides with T-15.2-61 — the budget governor is inert under
    `NESTOR_TRIBUNAL_UNCAPPED=1`, so angle count is the only real spend control this
    engine has left — which is why the caller must pass the result to
    `warn_if_over_ceiling` and log the overshoot LOUDLY.

    Returns `(assignment, degradation_reason)`. The reason is a D-12 degradation, not
    a note: this is a FULL fallback of the grouping step, so the output is complete
    but the run is degraded.
    """
    reason = (
        "The step that groups research questions by shared groundwork produced "
        "nothing usable, so the questions were grouped one group per client question "
        "instead. Groundwork shared between two questions was therefore searched once "
        "per question rather than once per topic."
    )
    assignment: list[list[int]] = []
    try:
        pool = list(winners or [])
        if not pool:
            return [], reason

        labels: list[str] = []
        for raw in list(client_questions or []):
            label = str(raw or "").strip()
            if label and label not in labels:
                labels.append(label)
        if not labels:
            # Tolerant fallback: the caller lost the client questions, but the winners
            # still name their parents. Never return zero groups.
            for winner in pool:
                label = _own_parent(winner)
                if label and label not in labels:
                    labels.append(label)
        if not labels:
            return [list(range(len(pool)))], reason

        buckets: dict[str, list[int]] = {label: [] for label in labels}
        orphans = 0
        for index, winner in enumerate(pool):
            label = _own_parent(winner)
            if label not in buckets:
                label = labels[0]
                orphans += 1
            buckets[label].append(index)
        if orphans:
            log.warning(
                "question_grouping: %d winner(s) named a parent question that matches "
                "no client-validated label — they joined the first group rather than "
                "being dropped",
                orphans,
            )

        assignment = [buckets[label] for label in labels if buckets[label]]
    except Exception as exc:  # noqa: BLE001 — the fallback never breaks a run
        log.error("question_grouping: fallback_groups failed: %r", exc, exc_info=True)
        return [], reason
    return assignment, reason


# ---------------------------------------------------------------------------
# attach_discovery_riders — D-W3-5.2. PURE.
# ---------------------------------------------------------------------------


def attach_discovery_riders(
    groups: Any, riders: Any, *, max_size: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Ride discovery questions along inside their host mandate group. NEVER RAISES.

    D-W3-5.2: a discovery question parented to a CLIENT QUESTION LABEL joins that
    label's mandate group, because that is where its shared groundwork already is and
    it costs NO EXTRA CALL. Only a cross-cutting `__discovery__` question gets a group
    of its own, and that group is built separately with
    `bracket=GROUP_BRACKET_DISCOVERY`.

    THE SIZE CAP NOW BINDS ON RIDERS, AND ONLY ON RIDERS. § 4 requirement 2 caps
    questions per group because the risk is a provider writing six thin paragraphs
    instead of one deep report, and D-W3-4 says discovery NEVER BORROWS FROM THE
    MANDATE — so when prompt space runs out, DISCOVERY is what yields. A winner is
    never shed. A rider never displaces a client question's sub-question.

    `parent`, `rank` and `client_parents` are left FROZEN from the mandate members. A
    rider must not steal its host's facet, and `client_parents` is what decides
    whether a group is MIXED: a group holding one client question plus a rider is the
    INTENDED shape, not a defect, and the mixed-group warning must not cry wolf about
    it.

    Returns `(groups, shed, notes)`. Every shed rider comes back in `shed` so the
    caller can record it as raised-but-not-researched. It still reaches the client:
    `discovery_bracket.annotate_conflicts` annotates only DISPATCHED questions, so a
    shed one renders as a plain brief-vs-world conflict with no `researched_as`
    clause — the honest rendering.
    """
    notes: list[str] = []
    shed: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    try:
        size_cap = max(1, int(max_size))
        for raw_group in list(groups or []):
            if not isinstance(raw_group, dict):
                continue
            group = dict(raw_group)
            group["members"] = [
                dict(m) for m in list(group.get("members") or []) if isinstance(m, dict)
            ]
            group["parents"] = list(group.get("parents") or [])
            group["client_parents"] = list(group.get("client_parents") or [])
            out.append(group)

        for raw_rider in list(riders or []):
            if not isinstance(raw_rider, dict):
                continue
            rider = dict(raw_rider)
            rider.setdefault("source", _WINNER_SOURCE_DISCOVERY)
            parent = _own_parent(rider)

            candidates = [
                position
                for position, group in enumerate(out)
                if group.get("bracket") == GROUP_BRACKET_MANDATE
                and parent
                and parent in list(group.get("client_parents") or [])
            ]
            if not candidates:
                # SHED, NOT RE-HOMED. It cannot happen once the coverage guard has
                # run, and inventing a host for it would be exactly the fabricated
                # attribution this phase refuses everywhere else.
                shed.append(rider)
                log.warning(
                    "question_grouping: a discovery question parented %r matches no "
                    "mandate group, so it is reported rather than researched",
                    parent[:80],
                )
                notes.append(
                    "One question the evidence raised could not be attached to any of "
                    "the client's questions, so it is reported but was not researched."
                )
                continue

            # When the same client question is split across two groups, join the one
            # holding that parent's HIGHEST-RANKED winner: deterministic, and it puts
            # the rider where the deepest groundwork already is.
            def _host_key(position: int, _parent: str = parent) -> tuple[int, int]:
                best = _RANK_LAST
                for member in out[position].get("members") or []:
                    if _is_rider(member):
                        continue
                    if _parent in _parents_of(member):
                        best = min(best, _rank_of(member))
                return best, position

            host = min(candidates, key=_host_key)
            out[host]["members"].append(rider)
            out[host]["riders"] = int(out[host].get("riders") or 0) + 1
            for label in _parents_of(rider):
                if label not in out[host]["parents"]:
                    out[host]["parents"].append(label)

        # THE SIZE CAP, on riders only.
        for group in out:
            members = group.get("members") or []
            while len(members) > size_cap:
                # Positions, not dict identity: two riders can be equal dicts and
                # `list.remove` would then drop whichever compared equal first.
                rider_positions = [
                    p for p, member in enumerate(members) if _is_rider(member)
                ]
                if not rider_positions:
                    # A WINNER IS NEVER SHED. The group stays oversized instead.
                    break
                victim_position = max(
                    rider_positions, key=lambda p: (_rank_of(members[p]), p)
                )
                victim = members.pop(victim_position)
                shed.append(victim)
                group["riders"] = max(0, int(group.get("riders") or 0) - 1)
                notes.append(
                    "One question the evidence raised was dropped from a research "
                    "group that was already full, so it is reported but was not "
                    "researched. The client's own questions were kept."
                )
            group["members"] = members
            # Re-stamp `parents` only. `parent`, `rank` and `client_parents` stay
            # frozen — see the docstring.
            parents: list[str] = []
            for member in members:
                for label in _parents_of(member):
                    if label not in parents:
                        parents.append(label)
            group["parents"] = parents
    except Exception as exc:  # noqa: BLE001 — grouping never breaks a run
        log.error(
            "question_grouping: attach_discovery_riders failed: %r", exc, exc_info=True
        )
    return out, shed, notes


# ---------------------------------------------------------------------------
# warn_if_over_ceiling — the spend alarm. PURE.
# ---------------------------------------------------------------------------


def warn_if_over_ceiling(n_groups: Any, n_streams: Any) -> Optional[str]:
    """Say so, loudly, when the paid-call count exceeds the happy-path ceiling.

    `n_streams` is a PARAMETER and is NEVER imported from
    `research_division._D6_STREAMS`: plan 15.6-03 is editing that tuple in this same
    phase, and pinning it from here is the exact-set trap that turned phase 15.5's
    merged tree red. This module computes its warning from a number it is GIVEN.

    Returns the sentence when it fires, else None.
    """
    try:
        groups = max(0, int(n_groups))
        streams = max(0, int(n_streams))
    except (TypeError, ValueError):
        return None
    if streams <= 0:
        return None

    calls = groups * streams
    ceiling_calls = _D6_MAX_GROUPS * streams
    if calls <= ceiling_calls:
        return None

    sentence = (
        "This run dispatches %d groups to %d research providers, which is %d paid "
        "calls against the %d this engine aims for (%d groups x %d providers). The "
        "budget governor is switched off by decision, so the number of groups is the "
        "only real spend control left — treat this as the spend alarm it is."
        % (groups, streams, calls, ceiling_calls, _D6_MAX_GROUPS, streams)
    )
    log.warning("question_grouping: %s", sentence)
    return sentence
