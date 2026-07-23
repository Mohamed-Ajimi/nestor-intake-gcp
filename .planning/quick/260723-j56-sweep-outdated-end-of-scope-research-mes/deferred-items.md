# Deferred Items — quick-260723-j56

## Pre-existing locale key drift (out of scope)

`frontend/src/locales/nl/admin.json` carries two `intakeDetail.toast.*` keys that are
absent from the `fr` and `en` families:

- `intakeDetail.toast.researchStarted`
- `intakeDetail.toast.researchStartFailed`

Confirmed present-only-in-nl at parent commit `7c2d258` (before this task). These are
Tribunal research-start toasts, unrelated to the out-of-scope messaging this task removed.
Left untouched per the executor scope boundary (only auto-fix issues caused by the current
task's changes). A future i18n-parity sweep should backfill the `fr`/`en` translations.
