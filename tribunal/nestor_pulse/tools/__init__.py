# Namespace shim for the re-homed Tribunal engine (Phase 13, D-01).
#
# The ONLY module carried here is `claude_deep_researcher`, imported at module
# load by `nestor_pulse_sdk/tools/claude_adapter.py`
# (`from nestor_pulse.tools.claude_deep_researcher import deep_research_async`),
# which is on the live engine path via
# research_division -> degraded_parallel -> claude_adapter. It is self-contained
# (stdlib + httpx only). The rest of the sibling repo's `nestor_pulse/tools/`
# (the ADK arm's researchers/search tools) is deliberately NOT copied.
