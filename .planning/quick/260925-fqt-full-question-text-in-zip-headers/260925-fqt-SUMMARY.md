---
status: complete
quick_id: 260925-fqt
date: 2026-09-25
---
# Quick 260925-fqt — full question text in raw-output zip headers and index

**Problem (seen on dev acceptance run 4e91bb85):** research file headers and `research/index.md` showed the
question cut at 120 characters mid-word. The cut is upstream: the engine's `_angle` is
`workshop._LABEL_MAX_CHARS` (120), a join key that must stay short in the engine.

**Fix (backend only, `backend/app/research/bundle.py`):** the full client question is already in the bundle as a
`## ` chapter heading of `report.md`, and a label is a prefix of its question by construction. For a label of
>= 100 characters, the header and index show the first heading that starts with it; otherwise the label as-is.
File names unchanged (still the 60-char slug). No tribunal change.

**Verified:** 3 new tests (expand / short label never expands / no match stays). Bundle tests 20 passed with
`-W error::UserWarning`; full backend suite 919 passed, 2 skipped. On the real dev run all 3 labels expand
120 -> 288/309/288 characters.
