---
phase: quick-260723-ior
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/TopBar.tsx
  - frontend/src/components/LanguageSwitcher.tsx
  - frontend/src/components/admin/ProductShell.tsx
  - frontend/src/components/intake/AISkillsPanel.tsx
  - frontend/src/lib/api/client.ts
  - frontend/src/lib/auth-context.tsx
  - frontend/src/lib/firebase.ts
  - frontend/src/locales/en/admin.json
  - frontend/src/locales/nl/admin.json
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/routes/admin.tsx
  - frontend/src/routes/intake.$id.report.tsx
  - frontend/src/routes/intake.$id.results.tsx
  - frontend/src/routes/intake.$id.tsx
  - frontend/src/routes/intake.index.tsx
  - frontend/vite.config.ts
  - .replit
  - replit.md
  - CHANGES-FOR-CLAUDE-CODE.md
  - mock-backend/server.js
  - mock-backend/package.json
  - mock-backend/package-lock.json
  - attached_assets/
autonomous: true
requirements: [QUICK-MERGE-REPLIT-UI]

must_haves:
  truths:
    - "master contains all 14 commits from origin/replit-ui-changes plus a merge commit (branch history preserved, no squash/rebase)"
    - "frontend typechecks clean (npx tsc --noEmit exit 0) on the merged master"
    - "frontend production build succeeds (npm run build exit 0) on the merged master"
    - "mock-auth code paths remain guarded by VITE_MOCK_AUTH === \"1\" after merge (inert in production)"
    - "origin/master is up to date with local master"
  artifacts:
    - path: "frontend/src/components/TopBar.tsx"
      provides: "New top bar component from the branch"
    - path: "frontend/src/components/intake/AISkillsPanel.tsx"
      provides: "Redesigned AI skills panel"
    - path: "CHANGES-FOR-CLAUDE-CODE.md"
      provides: "Branch change documentation (16 changes)"
  key_links:
    - from: "frontend/src/components/admin/ProductShell.tsx"
      to: "frontend/src/components/TopBar.tsx"
      via: "TopBar import + mount"
      pattern: "TopBar"
    - from: "frontend/src/lib/auth-context.tsx"
      to: "VITE_MOCK_AUTH guard"
      via: "Real/Mock provider split behind env flag"
      pattern: "VITE_MOCK_AUTH"
---

<objective>
Merge `origin/replit-ui-changes` (14 commits of Replit-authored UI work: TopBar, compact
LanguageSwitcher, AISkillsPanel redesign, intake-detail infinite-loop fixes + History Sheet, locale
renames, plus flag-guarded mock-auth dev scaffolding and inert Replit files) into `master`, verify
the frontend still typechecks and production-builds, then push `master` to `origin`.

Purpose: Land the externally-developed UI improvements on the mainline so subsequent deploys and
phase work build on them, without losing branch history.
Output: A merge commit on `master` (pushed), green typecheck + build, and any small fix-forward
commits if the build surfaces integration breakage.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

Orchestrator-verified facts (trust these, do not re-derive):
- `origin/replit-ui-changes` exists with 14 commits; `git show origin/replit-ui-changes:CHANGES-FOR-CLAUDE-CODE.md` documents all 16 changes.
- The branch diff (24 files) does NOT touch `frontend/src/routeTree.gen.ts`. The locally-dirty
  `routeTree.gen.ts` and `.planning/phases/16-*/.continue-here.md` are unrelated working-tree noise:
  leave them dirty, do NOT stage them into the merge commit.
- All mock-auth paths are guarded by `import.meta.env.VITE_MOCK_AUTH === "1"` and inert in prod builds.
- `frontend/node_modules` is already installed in the main tree. Do NOT delete/reinstall — the project
  intentionally has no lockfile and `@radix-ui` is pinned exact to avoid drift (see memory:
  frontend-no-lockfile-drift-trap). Do NOT run `npm install` in `mock-backend/` either — it is
  Replit-only dev scaffolding, never built or deployed here.
- No worktree isolation (orchestrator decision): all work happens directly on `master` in the main tree.
- Environment: Windows, Git Bash for POSIX commands; node/npm available; no Python/Docker.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Merge origin/replit-ui-changes into master</name>
  <files>frontend/src/components/TopBar.tsx, frontend/src/components/LanguageSwitcher.tsx, frontend/src/components/admin/ProductShell.tsx, frontend/src/components/intake/AISkillsPanel.tsx, frontend/src/lib/api/client.ts, frontend/src/lib/auth-context.tsx, frontend/src/lib/firebase.ts, frontend/src/locales/en/admin.json, frontend/src/locales/nl/admin.json, frontend/src/routes/admin.pulse.intakes.$id.tsx, frontend/src/routes/admin.tsx, frontend/src/routes/intake.$id.report.tsx, frontend/src/routes/intake.$id.results.tsx, frontend/src/routes/intake.$id.tsx, frontend/src/routes/intake.index.tsx, frontend/vite.config.ts, .replit, replit.md, CHANGES-FOR-CLAUDE-CODE.md, mock-backend/, attached_assets/</files>
  <action>
    1. `git fetch origin` then confirm `git rev-parse --abbrev-ref HEAD` is `master` and
       `git log --oneline master..origin/replit-ui-changes | wc -l` shows 14 commits incoming.
    2. Read `git show origin/replit-ui-changes:CHANGES-FOR-CLAUDE-CODE.md` — use it as the authority
       on intent when resolving any conflict.
    3. Sanity-check the working tree: dirty files (`frontend/src/routeTree.gen.ts`,
       `.planning/phases/16-*/.continue-here.md`, untracked `.claude-phase1*-image.tmp`, `AGENTS.md`)
       must NOT intersect the branch's 24 changed paths (they don't, per diff stat). Leave them
       untouched and unstaged throughout.
    4. Run `git merge --no-ff origin/replit-ui-changes -m "merge: replit-ui-changes — TopBar, AISkillsPanel redesign, intake-detail history sheet + loop fixes, flag-guarded mock-auth dev scaffolding"`
       (append the standard Co-Authored-By/Claude-Session trailer lines per harness convention).
    5. If conflicts arise, resolve per policy: favor the BRANCH side for UI source files
       (components/, routes/, locales/, lib/), favor MASTER for generated files
       (`routeTree.gen.ts` — then let the build regenerate) and for docs — unless
       CHANGES-FOR-CLAUDE-CODE.md indicates otherwise for a specific hunk. Stage only conflicted
       files; complete the merge commit.
    6. Post-merge guard: `git grep -n "VITE_MOCK_AUTH" -- frontend/src/` must show every mock-auth
       code path gated by the `=== "1"` check (auth-context provider split, api/client mock token,
       firebase MOCK_AUTH export, 5 route beforeLoad bypasses). If any bypass is unguarded, fix it
       in a follow-up commit before proceeding — mock auth must be compile-time inert in production.
  </action>
  <verify>
    <automated>git log --oneline -1 --merges master | grep -q "replit-ui-changes" && git merge-base --is-ancestor origin/replit-ui-changes master && ! git grep -rl "^<<<<<<<" -- frontend/ && echo MERGE-OK</automated>
  </verify>
  <done>Merge commit exists on master; origin/replit-ui-changes is an ancestor of master; zero conflict markers; unrelated dirty files remain unstaged; all mock-auth paths guarded by VITE_MOCK_AUTH === "1".</done>
</task>

<task type="auto">
  <name>Task 2: Typecheck + production build; fix forward if broken</name>
  <files>frontend/src/** (fix-forward only if needed)</files>
  <action>
    From `frontend/` (main tree, existing node_modules — no install step):
    1. `npx tsc --noEmit` — must exit 0.
    2. `npm run build` — must exit 0 and produce `.output/` artifacts.
    3. If either fails: apply SMALL forward fixes only (type errors from master drift since the
       branch fork point, import path issues, prop mismatches between merged components). Do NOT
       revert branch features or reduce their scope. Commit fixes as
       `fix(frontend): post-merge <specific issue>` (one commit per logical fix, standard trailers).
    4. If `routeTree.gen.ts` is regenerated by the build and differs from HEAD, that is expected
       generated-file churn — include it in the fix commit only if the merge itself required route
       changes; otherwise leave it dirty as it was pre-merge.
    5. Do not run or build `mock-backend/` — out of scope, Replit-only.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit && npm run build && echo BUILD-OK</automated>
  </verify>
  <done>Typecheck and production build both exit 0 on merged master; any fixes committed with conventional messages; no feature from the branch reverted.</done>
</task>

<task type="auto">
  <name>Task 3: Push master to origin</name>
  <files>(none — git remote operation)</files>
  <action>
    1. `git push origin master`.
    2. Confirm `git rev-parse master` equals `git rev-parse origin/master` after push.
    3. Do NOT delete the remote `replit-ui-changes` branch — not in scope; leave it for the operator.
  </action>
  <verify>
    <automated>git fetch origin && test "$(git rev-parse master)" = "$(git rev-parse origin/master)" && echo PUSH-OK</automated>
  </verify>
  <done>origin/master matches local master; merge commit and any fix-forward commits are on the remote.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Merged dev scaffolding → production build | Mock-auth bypass code from an external dev environment enters the mainline |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-quick-01 | Spoofing | auth-context.tsx, api/client.ts, firebase.ts, 5 route beforeLoad hooks | mitigate | Task 1 step 6: git grep audit that every mock-auth path is gated by `VITE_MOCK_AUTH === "1"`; prod builds never set this var, so Vite dead-code-eliminates the bypass |
| T-quick-02 | Tampering | mock-backend/ (ships with its own package-lock) | accept | Files land in repo but are never installed, built, or deployed by any pipeline; explicit no-install rule in Tasks 1/2 |
| T-quick-SC | Tampering | npm installs | mitigate | No package installs in this plan (existing node_modules only); mock-backend install explicitly forbidden |
</threat_model>

<verification>
- `git merge-base --is-ancestor origin/replit-ui-changes master` → true (history preserved)
- `cd frontend && npx tsc --noEmit && npm run build` → exit 0
- `git grep -c "VITE_MOCK_AUTH" -- frontend/src/` > 0 and all hits guarded
- `git rev-parse master` == `git rev-parse origin/master`
- Pre-existing dirty files (`routeTree.gen.ts`, `.continue-here.md`, tmp files, `AGENTS.md`) not swept into any commit
</verification>

<success_criteria>
- All 14 branch commits + merge commit reachable from master and pushed to origin
- Frontend typecheck and production build green on merged master
- Mock-auth scaffolding verifiably inert without `VITE_MOCK_AUTH=1`
- No unrelated working-tree changes committed
</success_criteria>

<output>
Create `.planning/quick/260723-ior-merge-replit-ui-changes-branch-into-mast/260723-ior-SUMMARY.md` when done.
</output>
