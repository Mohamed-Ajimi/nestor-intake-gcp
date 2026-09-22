"""Phase 23.5 kill switches. Nothing else lives here.

No DB import, no provider import, no logging configuration -- this module is
imported by pure functions deep inside the citation path and must stay cheap and
side-effect free.

WHY THE SHAPE IS WHAT IT IS
--------------------------

**One master, five fine-grained switches.** `NESTOR_CITATIONS_V2` defaults
`false`: the shipped default IS today's behaviour, so nothing changes on a
deploy until an operator flips one variable (D-23.5-04), and flipping it back is
the whole revert -- by configuration, with no rebuild. The five fine-grained
switches each default `true` and are ANDed with the master, so they are inert
until the master is on. They exist for exactly one job: bisecting a bad dev run
without a rebuild.

Defaulting the fine-grained switches to `false` as well was considered and
rejected. It would mean the operator flips the master and NOTHING happens --
a silent no-op that reads as "the fix does not work". A master that changes
everything it claims to change is the louder, and therefore the safer, failure
mode.

**`NESTOR_SYNTHESIS_CONTINUE_TRUNCATED` is a SEPARATE master**, default `false`,
deliberately NOT gated by `NESTOR_CITATIONS_V2`. It governs the writer, not the
citation graph; its blast radius is one extra provider call per truncated
section (money and latency), where the citation switches only change which rows
get written. Tying the two together would make one lever mean two things, and
the operator could not turn the cheap fix on without also buying the expensive
one.

**Every accessor reads `os.environ` AT CALL TIME, not at import.** The
import-time idiom used elsewhere in this tree (`citations/anchors.py:87`
`_ANCHORS_ENABLED = os.environ.get(...)`) is precisely why
`test_citation_anchors.py` has to `skipif(not _ANCHORS_ENABLED)` rather than
assert both states: once the module is imported, the flag is frozen and no test
can flip it. The flags-off golden test in `tests/test_citation_replay.py` is
worth nothing if it cannot turn the master off in-process, so that idiom is NOT
reused here. The cost is one `os.environ` dict lookup per call, on a path that
already does network and database work.

THE SWITCHES
------------

=========================================== ======= ==================
Env var                                     Default Gated by the master
=========================================== ======= ==================
``NESTOR_CITATIONS_V2``                     false   -- (it IS the master)
``NESTOR_CITATIONS_SKEPTIC_AS_EVIDENCE``    true    yes
``NESTOR_CITATIONS_PER_URL_META``           true    yes
``NESTOR_CITATIONS_PRIMARY_ANCHOR``         true    yes
``NESTOR_CITATIONS_LEDGER_NUMBERABLE_ONLY`` true    yes
``NESTOR_CITATIONS_RENDER_RESOLVED``        true    yes
``NESTOR_SYNTHESIS_CONTINUE_TRUNCATED``     false   no (separate master)
=========================================== ======= ==================

Accepted values are ``1/true/yes/on`` and ``0/false/no/off``, case-insensitive
and whitespace-stripped. ANYTHING ELSE -- including an empty string, which is
what Cloud Run gives you for a variable that is declared and left blank --
falls back to the documented default rather than being read as false. A typo
must not silently disable a fix.
"""

import os

__all__ = [
    "citations_v2",
    "skeptic_as_evidence",
    "per_url_meta",
    "primary_anchor",
    "ledger_numberable_only",
    "render_resolved",
    "synthesis_continue_truncated",
]

#: The master. Named once so the accessors below cannot drift from the docstring.
_MASTER_ENV = "NESTOR_CITATIONS_V2"

_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def _truthy(raw: "str | None", default: bool) -> bool:
    """Parse an env value, falling back to `default` on anything unrecognised.

    `None` (unset), `""` (declared and blank) and `"maybe"` are all the same
    thing here: the operator did not express an opinion, so the documented
    default stands.
    """
    if not isinstance(raw, str):
        return default
    token = raw.strip().lower()
    if token in _TRUE_WORDS:
        return True
    if token in _FALSE_WORDS:
        return False
    return default


def _flag(env_name: str, *, default: bool) -> bool:
    """One switch, read from the environment AT CALL TIME."""
    return _truthy(os.environ.get(env_name), default)


def _gated(env_name: str) -> bool:
    """A fine-grained switch: its own value ANDed with the master.

    The AND is the operator's guarantee. With `NESTOR_CITATIONS_V2` off, no
    value of any other variable in this module can change what a run writes.
    """
    if not citations_v2():
        return False
    return _flag(env_name, default=True)


def citations_v2() -> bool:
    """The master switch for the phase-23.5 Sources-list change (default OFF)."""
    return _flag(_MASTER_ENV, default=False)


def skeptic_as_evidence() -> bool:
    """A skeptic's session urls stay on the VERDICT, not on every member claim.

    Mechanism 1 of the run-7784e71c defect: the group skeptic's whole-session
    `web_search` result list was copied onto each member claim's verdict and
    then upserted as a `claim_source` row of every one of them.
    """
    return _gated("NESTOR_CITATIONS_SKEPTIC_AS_EVIDENCE")


def per_url_meta() -> bool:
    """Title and provider grade are computed PER URL, not once per claim.

    Mechanism 2: one claim's display domain and self-declared grade were stamped
    on every url it touched, including urls on entirely foreign hosts.
    """
    return _gated("NESTOR_CITATIONS_PER_URL_META")


def primary_anchor() -> bool:
    """A claim's citation number points at its OWN primary provider url.

    Mechanism 3: the anchor resolved to the claim's first source by
    `(position, id, source id)` -- in practice the lowest UUID, which is
    arbitrary.
    """
    return _gated("NESTOR_CITATIONS_PRIMARY_ANCHOR")


def ledger_numberable_only() -> bool:
    """The writer's fact ledger offers only claims that can actually be numbered.

    Mechanism 5: claims with no `claim_source` row still reached the ledger, so
    the writer emitted anchors that the numbering pass then stripped -- 108 of
    them on run 7784e71c.
    """
    return _gated("NESTOR_CITATIONS_LEDGER_NUMBERABLE_ONLY")


def render_resolved() -> bool:
    """The rendered Sources list prints `resolved_url` when one was stored.

    Mechanism 4: 21 of 27 redirects had been resolved and stored, and the
    renderer printed the opaque redirect anyway.
    """
    return _gated("NESTOR_CITATIONS_RENDER_RESOLVED")


def synthesis_continue_truncated() -> bool:
    """On `stop_reason == "max_tokens"`, issue ONE continuation call (default OFF).

    Remark 2b. A SEPARATE master by design -- see the module docstring: this one
    spends money per truncated section, the citation switches do not.
    """
    return _flag("NESTOR_SYNTHESIS_CONTINUE_TRUNCATED", default=False)
