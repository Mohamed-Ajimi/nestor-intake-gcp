# Re-homed Tribunal engine (Phase 13, D-01).
#
# Only `nestor_pulse.secrets` is carried into this repo — it is the sole
# cross-package dependency of the Tribunal engine path
# (`nestor_pulse_sdk/secrets_bootstrap.py` does
# `from nestor_pulse.secrets import load_secrets_into_env`).
#
# The sibling repo's `nestor_pulse/__init__.py` eagerly imports the ADK arm
# modules (agent, decomposer_agent, ...), which are the `engine="adk"` path
# and are deliberately NOT copied here. Re-exporting them would ImportError at
# boot. This package intentionally stays a bare namespace so that
# `import nestor_pulse.secrets` resolves without dragging in the ADK modules.
