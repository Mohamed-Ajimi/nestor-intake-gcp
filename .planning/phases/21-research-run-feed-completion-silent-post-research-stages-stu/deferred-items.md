# Phase 21 — deferred items (out of scope, logged not fixed)

Executors append here. Nothing in this file was fixed; each entry is a pre-existing
condition discovered while executing a plan, outside that plan's scope boundary.

## `npm run lint` is RED at the phase base commit (`eac6f2b`) — found by 21-01

`frontend/scripts/c.ts` — an ad-hoc Supabase scratch script, untouched by phase 21 —
carries **3 genuine `@typescript-eslint/no-explicit-any` errors** plus prettier
formatting errors. It is not imported by anything in `src/`. Because `npm run lint`
runs `eslint .` over the whole frontend, that one file makes the whole command exit 1
regardless of what any plan does.

**Consequence for every phase-21 frontend plan:** the acceptance criterion
`cd frontend && npm run lint` exits 0 is **not satisfiable at this base commit** and
its failure says nothing about the plan's own code. Verify per-file instead:

```
npm exec --prefix frontend -- eslint --config frontend/eslint.config.js <the files you touched>
```

21-01 verified its three files this way: **zero non-prettier rule violations.**

### Also: this repo's Windows worktrees make local `eslint` unusable without filtering

`core.autocrlf=true`, so `git ls-files --eol` reports `i/lf w/crlf` — the index is LF,
the working tree is CRLF. Prettier's `endOfLine: "lf"` therefore reports **one
`Delete ␍` error per line, on every file in the tree**, including files no one has
touched. CI checks out on Linux with LF and never sees these.

To check prettier conformance of the form that will actually be committed, feed the
file through a CR strip:

```
tr -d '\r' < <file> | npm exec --prefix frontend -- prettier --stdin-filepath <file> --check
```

**Doing this found two REAL pre-existing prettier deviations in `RunFeed.tsx`** that the
CRLF noise had been burying (`stableAfterRow` and the collapse-toggle ternary were both
wrapped where prettier joins them). 21-01 normalised those two because they sat in a file
it already owned. There may be more elsewhere in `frontend/src/`; nobody has looked,
because the local signal is drowned.

**Not fixed here** — `scripts/c.ts` and any wider prettier sweep are unrelated to the run
feed and belong to whoever decides whether that scratch script should exist at all.

`frontend/cloudbuild.yaml` has no lint, tsc or vitest step, so none of this currently
blocks a deploy — which is also why it went unnoticed.
