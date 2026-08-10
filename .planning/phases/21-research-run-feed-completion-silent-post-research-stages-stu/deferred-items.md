# Phase 21 — deferred items

Out-of-scope discoveries logged during execution. Per the executor scope boundary these were
NOT fixed: they are pre-existing and not caused by the task's own changes.

---

## DEF-21-01 — `npm run lint` is already red at HEAD, for two unrelated reasons

**Found during:** 21-02 Task 2 (`cd frontend && npm run lint` acceptance criterion)
**Status:** deferred, not fixed
**Files:** repo-wide; the two content complaints are in
`frontend/src/routes/admin.pulse.runs.$runId.tsx` at the `useRunEvents` destructure and the
`EmptyFeed` return — both PRE-EXISTING lines, unchanged by 21-02.

### Reason 1 — CRLF, and it is a Windows-worktree artifact only

`git config core.autocrlf` is `true` on this machine, so the worktree checkout is CRLF while
`.prettierrc` leaves `endOfLine` at its `"lf"` default. Every file in the tree therefore fails
`prettier/prettier` with ``Delete `␍` ``, including files nobody has touched in months
(`frontend/vitest.config.ts` among them). Measured: **28,046 problems / 28,010 errors** across
the tree.

This is a checkout artifact, not a repo defect: CI checks out on Linux with LF and would not
see it. It is NOT fixable from here without rewriting line endings across the whole tree, which
is exactly the blanket working-tree operation the executor is forbidden to perform.

### Reason 2 — two genuine, EOL-independent formatting drifts, already at HEAD

Filtering the CRLF noise leaves exactly **two** errors in `admin.pulse.runs.$runId.tsx`:

- the `useRunEvents(...)` destructure — prettier wants the multi-line form collapsed;
- `EmptyFeed`'s `return (...)` — prettier wants the parentheses dropped.

**Both are proven pre-existing.** `git show HEAD:frontend/src/routes/admin.pulse.runs.$runId.tsx`
was exported to a scratch path and checked with `prettier --config .prettierrc --end-of-line auto`
— which removes the CRLF variable entirely — and the untouched HEAD version **still fails**. So
the frontend lint gate does not exit 0 at `eac6f2b` either, on Linux or on Windows.

### What 21-02 itself contributed

**Zero.** `npx eslint` on the three files 21-02 touches, with `Delete ␍` filtered out, reports
only the two pre-existing lines above. Every line 21-02 added is prettier-clean.

### Why it was not fixed here

Reformatting those two hunks would put unrelated churn into a diff whose acceptance criteria
explicitly measure that it touches exactly one path and nothing else. It is a one-line-each fix
for whoever owns the lint gate, and it should land as its own change together with a ruling on
whether `.prettierrc` should pin `endOfLine: "auto"` so Windows worktrees stop drowning the
signal in 28,000 carriage-return errors.

**Recommended follow-up (not done here):** pin `endOfLine` in `.prettierrc`, then run
`prettier --write` once across `frontend/src/` as a single dedicated commit.
