"""Audited adapter shims wrapping legacy deep-research tools (D-01 / Pitfall 8).

The shims here CONSUME AuditedLLMClient's two-phase API (start_call / end_call).
They import nestor_pulse/tools/*.py READ-ONLY -- the legacy files are byte-identical
across Phase 1 (test_legacy_tools_not_modified enforces).
"""
