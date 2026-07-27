"""D-I regression — no personal identifier leaves this engine to a research provider.

WHY THIS FILE EXISTS. On run `d6bb3aae` (2026-07-27) angle #6 was a PAID Google
deep-research assignment whose parent line carried a named individual's email
address. The address left the platform to an external processor as a research
task, serving no client decision. That is a data-protection incident, not a
quality bug, and this file is its regression gate.

THE FIXTURE IS THE REAL QUERY. Test 1 below reconstructs the actual angle-#6
dispatch — parent line and sub-question, transcribed from
`docs/tribunal-run-reports/run-20260727-d6bb3aae-WORKSHOP-FORENSICS.md` §3 row 6.
The leaked address exists in this repository HERE AND NOWHERE ELSE: it is the
proof the scrub works, and `grep -rn "mohamed.ajimi" tribunal/nestor_pulse_sdk/`
returning only this file is part of the plan's verification.

THIS FILE MAKES ZERO LLM CALLS and opens no socket and no database. `run_angles`
is driven with a recording stub runner in the shape
`test_research_division_assignment.py` already uses — there is no second harness.

Cloud Build invocation (no Postgres and no provider key needed):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import uuid

import pytest

from nestor_pulse_sdk.pipeline.tribunal import own_researcher as orx
from nestor_pulse_sdk.pipeline.tribunal import research_division as rd
from nestor_pulse_sdk.pipeline.tribunal.pii import REDACTED, scrub_pii

# ---------------------------------------------------------------------------
# THE FIXTURE. Transcribed verbatim from the forensics table
# (run-20260727-d6bb3aae-WORKSHOP-FORENSICS.md §3, row 6): the parent line that
# became the angle, and the sub-question that was dispatched under it. The
# composed query is what `_angle_query` builds and what `run_angles` sends.
# ---------------------------------------------------------------------------

ANGLE_6_PARENT = (
    "Primary client contact: MEEMZ (mohamed.ajimi@azentic.be) — role still to be "
    "filled in"
)
ANGLE_6_SUBQUESTION = (
    "What is the exact job title and organisational role of Mohamed Ajimi (MEEMZ) "
    "within or towards LUKOIL — internal strategy lead, external consultant, or "
    "other?"
)
ANGLE_6_QUERY = f"{ANGLE_6_PARENT}\n\n{ANGLE_6_SUBQUESTION}"


# ---------------------------------------------------------------------------
# Test 1 — THE D-I REGRESSION.
# ---------------------------------------------------------------------------


def test_the_real_angle_six_query_is_scrubbed() -> None:
    """The exact text that caused the incident comes back carrying no address.

    Asserted on the `@` character rather than on the address string, because the
    point is not that ONE address is gone — it is that no address-shaped token
    survives the dispatch point at all.
    """
    scrubbed, count = scrub_pii(ANGLE_6_QUERY)

    assert count == 1
    assert "@" not in scrubbed
    assert "azentic.be" not in scrubbed
    assert REDACTED in scrubbed

    # The RESEARCH QUESTION survives. A scrubber that eats the question would
    # turn a data-protection fix into a wasted paid angle (T-15.2-233).
    assert "MEEMZ" in scrubbed
    assert "LUKOIL" in scrubbed
    assert "job title and organisational role" in scrubbed
    assert scrubbed.startswith("Primary client contact: MEEMZ (")


# ---------------------------------------------------------------------------
# Test 2 — dialling shapes go; numbers that carry meaning stay.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phone",
    [
        "+32 470 12 34 56",
        "0470/12.34.56",
        "+31 6 12345678",
        "0470123456",
        "+32 2 123 45 67",
    ],
)
def test_phone_shapes_are_removed(phone: str) -> None:
    text = f"Bel de woordvoerder op {phone} voor commentaar."
    scrubbed, count = scrub_pii(text)

    assert count == 1
    assert phone not in scrubbed
    assert REDACTED in scrubbed
    assert scrubbed.startswith("Bel de woordvoerder op ")
    assert scrubbed.endswith(" voor commentaar.")


@pytest.mark.parametrize(
    "keep",
    [
        # A year range — the single most common shape in this engine's questions.
        "CAPEX-envelope 2026-27 voor shop refit en IT",
        "Welke besluiten moeten in juni 2026 rond zijn?",
        # A percentage and a margin.
        "De omzet steeg met 12% en de marge met 3,5%.",
        # Money, in both the euro-symbol and the EUR-prefix spelling.
        "De marktomvang bedroeg EUR 1,2 miljard in 2024.",
        "Cafe-omzet steeg naar EUR 4,5 miljoen.",
        "Een koffie kost circa EUR 3,50 in het zelfbedieningsconcept.",
        # A four-digit statistic, and a thousands-separated one.
        "De BeNeLux-markt telde 8.000 tankstations in 2024.",
        "1200 locaties werden omgebouwd.",
        # Statutory opening hours — this engine literally researches these
        # (angle #11 of the same run), and an eight-digit time range must not
        # read as a dialling shape.
        "Openingstijden 08.00-18.00 op werkdagen.",
        # A leading-zero decimal.
        "Een correlatie van 0.75 tussen prijs en volume.",
    ],
)
def test_meaningful_numbers_are_never_touched(keep: str) -> None:
    """T-15.2-233 — an over-eager scrubber destroys paid angles.

    Every string here is research content this engine produces or consumes. If
    the phone pattern eats any of them, the fix costs more than the defect.
    """
    scrubbed, count = scrub_pii(keep)

    assert count == 0
    assert scrubbed == keep, "no-op input must come back byte-identical"


# ---------------------------------------------------------------------------
# Test 3 — source URLs are not collateral damage.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url_text",
    [
        "Zie https://x.test/a@b voor de bron.",
        "Zie [de bron](https://example.com/report-2024) voor de cijfers.",
        "Bron: https://www.spglobal.com/commodity-insights/en/2024/report",
        "Bron: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbCd1234",
    ],
)
def test_source_urls_survive(url_text: str) -> None:
    """A scrub that breaks a citation URL breaks the evidence trail.

    The first case is the pointed one: an `@` inside a URL path is not an email
    address, and treating it as one would silently corrupt a source link.
    """
    scrubbed, count = scrub_pii(url_text)

    assert count == 0
    assert scrubbed == url_text


def test_an_address_inside_a_url_is_left_to_the_url_layer() -> None:
    """A userinfo-style URL is a URL, and this module does not rewrite URLs.

    Stated as a test rather than left implicit: the boundary is deliberate, and
    a future reader must be able to see that it was a decision.
    """
    text = "Zie https://mohamed.ajimi@azentic.be/profile voor het profiel."
    scrubbed, count = scrub_pii(text)

    assert count == 0
    assert scrubbed == text


# ---------------------------------------------------------------------------
# Test 4 — the (text, count) contract.
# ---------------------------------------------------------------------------


def test_count_is_the_number_of_identifiers_removed() -> None:
    text = (
        "Contact a@example.com or b@example.org, or call +32 470 12 34 56 "
        "or 0470/98.76.54."
    )
    scrubbed, count = scrub_pii(text)

    assert count == 4
    assert scrubbed.count(REDACTED) == 4
    assert "@" not in scrubbed


def test_clean_text_returns_byte_identical_with_zero() -> None:
    """The no-op path must be provably a no-op — no trimming, no normalisation."""
    text = "  Which fuel retailers apply dynamic pricing today?\t\n\n  Second line.  "
    scrubbed, count = scrub_pii(text)

    assert (scrubbed, count) == (text, 0)
    assert scrubbed is text or scrubbed == text


# ---------------------------------------------------------------------------
# Test 5 — pathological input never raises.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        None,
        "",
        "@",
        "@@@@@@",
        "\t\n\r\x00\x01",
        "a" * 200_000,
        "x" * 100_000 + "mohamed.ajimi@azentic.be" + "y" * 100_000,
        "+" * 5_000,
        "0" * 5_000,
        "..@..",
        "日本語 テキスト 070-1234-5678",
        "mail:mohamed.ajimi@azentic.beXYZ",
    ],
)
def test_never_raises(hostile: object) -> None:
    """A failure to scrub degrades a dispatch. It must never fail one."""
    scrubbed, count = scrub_pii(hostile)  # type: ignore[arg-type]

    assert isinstance(scrubbed, str)
    assert isinstance(count, int)
    assert count >= 0


def test_a_non_string_input_degrades_to_a_string() -> None:
    """`scrub_pii` returns a str for anything, so the caller can always dispatch."""
    for raw in (123, 4.5, object(), [], {}):
        scrubbed, count = scrub_pii(raw)  # type: ignore[arg-type]
        assert isinstance(scrubbed, str)
        assert count == 0


# ---------------------------------------------------------------------------
# Test 6 — hop one: the dispatch choke point in `run_angles`.
# ---------------------------------------------------------------------------


def _runner_recording(calls: dict, name: str):
    """The recording stub from `test_research_division_assignment.py:55`.

    Reused verbatim in shape rather than reinvented: there is one stubbing
    harness for `run_angles` in this suite and this is it.
    """

    async def _run(*, query, audited, run_id, tenant_id):
        calls.setdefault(name, []).append(query)
        return {"status": "success", "report": f"{name} report"}

    return _run


@pytest.mark.asyncio
async def test_run_angles_scrubs_before_dispatch(monkeypatch) -> None:
    """THE REGRESSION THAT MATTERS. No provider runner ever sees the address.

    Also pins that the scrub did not DISPLACE the D8 attachment: the fact-list
    block must still be appended for a `_D8_PROMPT_PROVIDERS` stream, or this
    fix would have silently broken 15.2-14.
    """
    from nestor_pulse_sdk.pipeline.tribunal.facts import FACTS_END, FACTS_START

    calls: dict = {}
    monkeypatch.setattr(
        rd,
        "_PROVIDER_RUNNERS",
        {n: _runner_recording(calls, n) for n in ("gemini", "claude", "openai")},
    )
    monkeypatch.setattr(
        rd,
        "_enabled_providers",
        lambda: [("gemini", None), ("claude", None), ("openai", None)],
    )

    angle = {
        "query": ANGLE_6_QUERY,
        "stakes": "high",
        "focus_area": "Primary client contact",
        "provider": "gemini",
        "language": "",
    }
    results = await rd.run_angles(
        angles=[angle], audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )

    assert len(results) == 1
    dispatched = calls["gemini"][0]

    # (a) Nothing address-shaped reached the provider.
    assert "mohamed.ajimi" not in dispatched
    assert "azentic.be" not in dispatched
    assert "@" not in dispatched
    assert REDACTED in dispatched

    # (b) The research question still reached it.
    assert "LUKOIL" in dispatched
    assert "job title and organisational role" in dispatched

    # (c) The D8 block is STILL attached — the scrub sits before the attachment,
    #     it does not replace it (15.2-14 must not regress).
    assert FACTS_START in dispatched
    assert FACTS_END in dispatched

    # (d) The count is recorded on the angle for the operator-facing layer, and
    #     the angle's own `query` is NOT rewritten: `checkpoints.angles_digest`
    #     is derived from exactly that field, so mutating it would invalidate
    #     every research checkpoint on a resumed run (T-15.2-123).
    assert angle["pii_removed"] == 1
    assert angle["query"] == ANGLE_6_QUERY


@pytest.mark.asyncio
async def test_a_clean_angle_records_no_removal(monkeypatch) -> None:
    """The common case must stay silent — no marker, no counter, no noise."""
    calls: dict = {}
    monkeypatch.setattr(
        rd, "_PROVIDER_RUNNERS", {n: _runner_recording(calls, n) for n in ("openai",)}
    )
    monkeypatch.setattr(rd, "_enabled_providers", lambda: [("openai", None)])

    angle = {
        "query": "Which fuel retailers in Europe apply dynamic pricing today?",
        "stakes": "med",
        "focus_area": "Dynamic pricing",
        "provider": "openai",
        "language": "",
    }
    await rd.run_angles(
        angles=[angle], audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )

    dispatched = calls["openai"][0]
    assert dispatched.startswith(angle["query"])
    assert REDACTED not in dispatched
    assert "pii_removed" not in angle


@pytest.mark.asyncio
async def test_the_scrub_never_logs_the_value_it_removed(monkeypatch, caplog) -> None:
    """T-15.2-232. Logging the removed address would put it straight back.

    The WARNING carries the angle index, the stream and the COUNT — and the log
    and the audit blob are exactly the places the identifier must not reappear.
    """
    import logging

    calls: dict = {}
    monkeypatch.setattr(
        rd, "_PROVIDER_RUNNERS", {n: _runner_recording(calls, n) for n in ("gemini",)}
    )
    monkeypatch.setattr(rd, "_enabled_providers", lambda: [("gemini", None)])

    with caplog.at_level(logging.DEBUG):
        await rd.run_angles(
            angles=[
                {
                    "query": ANGLE_6_QUERY,
                    "stakes": "high",
                    "focus_area": "Primary client contact",
                    "provider": "gemini",
                    "language": "",
                }
            ],
            audited=None,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )

    emitted = "\n".join(record.getMessage() for record in caplog.records)
    assert "mohamed.ajimi" not in emitted
    assert "azentic.be" not in emitted
    # ...but the removal itself IS reported. A silent scrub is the failure mode
    # this whole family of helpers exists to avoid.
    assert "personal identifier" in emitted.lower()


# ---------------------------------------------------------------------------
# Test 7 — hop two: the model-authored search input.
# ---------------------------------------------------------------------------


def test_clamp_search_input_scrubs_the_model_authored_query() -> None:
    """The own-researcher writes its OWN searches from the angle it was given.

    A scrubbed angle can still produce an identifier-bearing search if the model
    recalls one from its context, so the same rule applies at
    `_clamp_search_input`, which is already this stream's untrusted-model-input
    boundary. Every other clamped field must survive untouched.
    """
    clamped = orx._clamp_search_input(
        {
            "q": "Mohamed Ajimi mohamed.ajimi@azentic.be LUKOIL job title",
            "hl": "NL",
            "gl": "be",
            "num": 7,
        },
        default_gl="nl",
    )

    assert "@" not in clamped["q"]
    assert "azentic.be" not in clamped["q"]
    assert REDACTED in clamped["q"]
    assert "LUKOIL job title" in clamped["q"]

    assert clamped["hl"] == "nl"
    assert clamped["gl"] == "be"
    assert clamped["num"] == 7


def test_clamp_search_input_is_unchanged_for_a_clean_query() -> None:
    """The clamp's existing contract is not disturbed by the scrub."""
    clamped = orx._clamp_search_input(
        {"q": "  dynamic pricing fuel retail benelux  ", "hl": "??", "num": 99},
        default_gl="nl",
    )

    assert clamped == {
        "q": "dynamic pricing fuel retail benelux",
        "hl": "",
        "gl": "nl",
        "num": 10,
    }


def test_clamp_search_input_still_bounds_an_over_long_query() -> None:
    """The `_QUERY_MAX_CHARS` bound is a prompt-injection control, not formatting."""
    clamped = orx._clamp_search_input({"q": "x" * 5_000}, default_gl="")

    assert len(clamped["q"]) == orx._QUERY_MAX_CHARS
