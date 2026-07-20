"""nestor_pulse_sdk.critique — blind head-to-head report critique.

User-triggered (button on the Compare screen): judges two engines' final
reports against each other on clarity / content / robustness and hunts for
cross-report numeric conflicts. The judge is BLIND by construction — see
judge.py for the objectivity measures.
"""

from nestor_pulse_sdk.critique.judge import run_blind_critique, sanitize_report

__all__ = ["run_blind_critique", "sanitize_report"]
