"""Container entrypoint. Exists so `worker.py` is only ever imported under its canonical
name — running it via `python -m nestor_pulse_sdk.runs.worker` made it `__main__`, and
execute.py's lazy `from nestor_pulse_sdk.runs.worker import execute_run` then loaded a
SECOND copy with a SECOND `WORKER_ID`, so every ownership-fenced write matched zero rows
(DEF-23.3-01, 2026-09-09)."""

from nestor_pulse_sdk.runs.worker import main

if __name__ == "__main__":
    main()
