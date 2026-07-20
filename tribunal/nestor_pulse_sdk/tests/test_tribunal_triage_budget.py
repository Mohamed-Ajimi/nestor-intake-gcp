"""Tests for tribunal triage.py + budget.py.

Plan 01-14 Tasks 2 & 3 — TDD RED/GREEN cycle.

All tests use fake sessionmakers / fake data — no Cloud SQL, no network.

Coverage (triage half):
  - skeptics_for: low->0, med->2, high->3
  - skeptics_for: unknown tier defaults to 2 (med behaviour)
  - triage_claims: mixed list allocates correct per-tier counts

Coverage (budget half):
  - over_budget: True when sum >= max_budget_usd
  - over_budget: False when sum < max_budget_usd
  - budget_marker: returns flag string for flag-budget-capped behaviour
  - budget_marker: returns empty string for silent-degrade behaviour
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Triage tests
# ---------------------------------------------------------------------------


class TestSkepticsFor:
    """Unit tests for triage.skeptics_for()."""

    def _import(self):
        from nestor_pulse_sdk.pipeline.tribunal.triage import skeptics_for
        return skeptics_for

    def test_low_stakes_zero_skeptics(self):
        skeptics_for = self._import()
        assert skeptics_for("low") == 0

    def test_med_stakes_two_skeptics(self):
        skeptics_for = self._import()
        assert skeptics_for("med") == 2

    def test_high_stakes_three_skeptics(self):
        skeptics_for = self._import()
        assert skeptics_for("high") == 3

    def test_unknown_tier_defaults_to_two(self):
        """Unknown tier must default to med behaviour (2 skeptics), not crash."""
        skeptics_for = self._import()
        result = skeptics_for("mystery_tier")
        assert result == 2, f"Expected 2 for unknown tier, got {result}"

    def test_unknown_tier_does_not_raise(self):
        skeptics_for = self._import()
        # Must never raise even with an arbitrary string
        skeptics_for("not_a_real_tier")

    def test_case_sensitive_tier_names(self):
        """Only lowercase 'low','med','high' are valid tiers."""
        skeptics_for = self._import()
        # 'HIGH' is not the same as 'high' — treated as unknown, defaults to 2
        result = skeptics_for("HIGH")
        assert result == 2


class TestTriageClaims:
    """Unit tests for triage.triage_claims()."""

    def _import(self):
        from nestor_pulse_sdk.pipeline.tribunal.triage import triage_claims
        return triage_claims

    def _make_claims(self, stakes_list: list[str]) -> list[dict]:
        return [{"text": f"claim {i}", "stakes": s} for i, s in enumerate(stakes_list)]

    def test_all_low_returns_zero_skeptics(self):
        triage_claims = self._import()
        claims = self._make_claims(["low", "low", "low"])
        result = triage_claims(claims)
        for claim, n in result:
            assert n == 0, f"Expected 0 for low claim, got {n}"

    def test_mixed_stakes_correct_allocation(self):
        triage_claims = self._import()
        claims = self._make_claims(["low", "med", "high"])
        result = triage_claims(claims)
        assert len(result) == 3
        counts = {r[0]["stakes"]: r[1] for r in result}
        assert counts["low"] == 0
        assert counts["med"] == 2
        assert counts["high"] == 3

    def test_returns_list_of_tuples(self):
        triage_claims = self._import()
        claims = self._make_claims(["med"])
        result = triage_claims(claims)
        assert isinstance(result, list)
        assert len(result) == 1
        claim, n = result[0]
        assert isinstance(claim, dict)
        assert isinstance(n, int)

    def test_empty_list(self):
        triage_claims = self._import()
        result = triage_claims([])
        assert result == []

    def test_preserves_claim_dict(self):
        """The returned claim dict must be the same dict passed in."""
        triage_claims = self._import()
        original = {"text": "test claim", "stakes": "high", "facet": "A"}
        result = triage_claims([original])
        returned_claim, _ = result[0]
        assert returned_claim is original or returned_claim == original

    def test_claim_without_stakes_falls_back_to_med(self):
        """Claims without a stakes key default to med allocation (2)."""
        triage_claims = self._import()
        claim = {"text": "no stakes claim"}  # no 'stakes' key
        result = triage_claims([claim])
        _, n = result[0]
        # No stakes -> unknown tier -> defaults to med behaviour (2)
        assert n == 2, f"Expected 2 for unknown stakes, got {n}"


# ---------------------------------------------------------------------------
# Budget tests
# ---------------------------------------------------------------------------


class TestOverBudget:
    """Unit tests for budget.over_budget()."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_sessionmaker(self, total_cost: float):
        """Build a fake sessionmaker that returns a known sum from audit_log.

        current_cost now opens session.begin() for RLS context; the fake session
        must support the nested async context manager.
        """
        # Fake session with async context manager support
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = Decimal(str(total_cost))

        fake_session = AsyncMock()
        fake_session.execute = AsyncMock(return_value=fake_result)
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        # session.begin() async context manager (for RLS set_tenant_context call)
        fake_txn = AsyncMock()
        fake_txn.__aenter__ = AsyncMock(return_value=fake_txn)
        fake_txn.__aexit__ = AsyncMock(return_value=False)
        fake_session.begin = MagicMock(return_value=fake_txn)

        fake_sm = MagicMock()
        fake_sm.return_value = fake_session
        return fake_sm

    def test_over_budget_when_sum_equals_max(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import over_budget
        import uuid
        fake_sm = self._make_sessionmaker(5.00)
        result = self._run(over_budget(uuid.uuid4(), uuid.uuid4(), 5.00, fake_sm))
        assert result is True

    def test_over_budget_when_sum_exceeds_max(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import over_budget
        import uuid
        fake_sm = self._make_sessionmaker(5.50)
        result = self._run(over_budget(uuid.uuid4(), uuid.uuid4(), 5.00, fake_sm))
        assert result is True

    def test_not_over_budget_when_below_max(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import over_budget
        import uuid
        fake_sm = self._make_sessionmaker(4.99)
        result = self._run(over_budget(uuid.uuid4(), uuid.uuid4(), 5.00, fake_sm))
        assert result is False

    def test_zero_cost_not_over_budget(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import over_budget
        import uuid
        fake_sm = self._make_sessionmaker(0.0)
        result = self._run(over_budget(uuid.uuid4(), uuid.uuid4(), 5.00, fake_sm))
        assert result is False

    def test_null_cost_not_over_budget(self):
        """When audit_log has no rows (sum returns NULL), not over budget."""
        from nestor_pulse_sdk.pipeline.tribunal.budget import over_budget
        import uuid

        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None  # NULL from DB

        fake_session = AsyncMock()
        fake_session.execute = AsyncMock(return_value=fake_result)
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_txn = AsyncMock()
        fake_txn.__aenter__ = AsyncMock(return_value=fake_txn)
        fake_txn.__aexit__ = AsyncMock(return_value=False)
        fake_session.begin = MagicMock(return_value=fake_txn)

        fake_sm = MagicMock()
        fake_sm.return_value = fake_session

        result = self._run(over_budget(uuid.uuid4(), uuid.uuid4(), 5.00, fake_sm))
        assert result is False


class TestCurrentCost:
    """Unit tests for budget.current_cost()."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_fake_session(self, scalar_value):
        """Build a fake async session with begin() support for RLS context."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = scalar_value

        fake_session = AsyncMock()
        fake_session.execute = AsyncMock(return_value=fake_result)
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_txn = AsyncMock()
        fake_txn.__aenter__ = AsyncMock(return_value=fake_txn)
        fake_txn.__aexit__ = AsyncMock(return_value=False)
        fake_session.begin = MagicMock(return_value=fake_txn)
        return fake_session

    def test_returns_decimal(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import current_cost
        import uuid

        fake_session = self._make_fake_session(Decimal("3.50"))
        fake_sm = MagicMock()
        fake_sm.return_value = fake_session

        result = self._run(current_cost(uuid.uuid4(), uuid.uuid4(), fake_sm))
        assert result == Decimal("3.50")

    def test_null_returns_zero(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import current_cost
        import uuid

        fake_session = self._make_fake_session(None)
        fake_sm = MagicMock()
        fake_sm.return_value = fake_session

        result = self._run(current_cost(uuid.uuid4(), uuid.uuid4(), fake_sm))
        assert result == Decimal("0")


class TestBudgetMarker:
    """Unit tests for budget.budget_marker()."""

    def test_flag_behaviour_returns_marker_string(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import budget_marker
        result = budget_marker(over=True, behaviour="flag-budget-capped")
        assert result == "budget-capped", f"Expected 'budget-capped', got {result!r}"

    def test_flag_behaviour_not_over_returns_empty(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import budget_marker
        result = budget_marker(over=False, behaviour="flag-budget-capped")
        assert result == "", f"Expected empty string, got {result!r}"

    def test_silent_degrade_over_returns_empty(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import budget_marker
        result = budget_marker(over=True, behaviour="silent-degrade")
        assert result == "", f"Expected empty string for silent-degrade, got {result!r}"

    def test_silent_degrade_not_over_returns_empty(self):
        from nestor_pulse_sdk.pipeline.tribunal.budget import budget_marker
        result = budget_marker(over=False, behaviour="silent-degrade")
        assert result == ""
