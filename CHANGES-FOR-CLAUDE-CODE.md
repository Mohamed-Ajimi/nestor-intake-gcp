# Changes made in Replit dev setup — implement these in the real app

These changes were added to run the frontend on Replit without GCP credentials.
They are **local-dev only** additions. Nothing touches production logic.

---

## 1. `frontend/vite.config.ts`

Add `allowedHosts` and API proxy under a `vite:` key (required because the
`@lovable.dev/vite-tanstack-config` wrapper only merges Vite config placed
under `vite:` when a Lovable-specific key like `nitro` is also present).

```ts
export default defineConfig({
  nitro: { preset: "node-server" },
  vite: {
    server: {
      allowedHosts: true,          // allow Replit proxy domain
      proxy: {
        "/api": {
          target: "http://localhost:3001",   // mock backend
          rewrite: (path: string) => path.replace(/^\/api/, ""),
        },
      },
    },
  },
});
```

---

## 2. `frontend/.env.local` (new file — already gitignored)

```
VITE_MOCK_AUTH=1
VITE_API_BASE_URL=/api

VITE_FIREBASE_API_KEY=mock-api-key
VITE_FIREBASE_AUTH_DOMAIN=mock-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=mock-project
```

---

## 3. `frontend/src/lib/firebase.ts`

Add a `MOCK_AUTH` export (single source of truth for the mock flag):

```ts
/** Set VITE_MOCK_AUTH=1 to bypass Firebase and use a local mock superadmin session. */
export const MOCK_AUTH = import.meta.env.VITE_MOCK_AUTH === "1";
```

---

## 4. `frontend/src/lib/api/client.ts`

Make `currentIdToken()` return a fixed mock token instead of calling Firebase
when `MOCK_AUTH` is enabled:

```ts
import { apiUrl, auth, MOCK_AUTH } from "@/lib/firebase";

const MOCK_TOKEN = "mock-token-for-local-development";

export async function currentIdToken(forceRefresh = false): Promise<string | null> {
  if (MOCK_AUTH) return MOCK_TOKEN;
  return auth.currentUser ? getIdToken(auth.currentUser, forceRefresh) : null;
}
```

---

## 5. `frontend/src/lib/auth-context.tsx`

Split `AuthProvider` into `RealAuthProvider` (original logic, unchanged) and a
thin `AuthProvider` wrapper that short-circuits to a mock superadmin session
when `MOCK_AUTH=1`. Add at module level, before `RealAuthProvider`:

```ts
import { MOCK_AUTH } from "@/lib/firebase";

const MOCK_USER = MOCK_AUTH
  ? ({ uid: "mock-user-001", email: "admin@example.com", displayName: "Mock Admin" } as unknown as User)
  : null;

async function mockGetToken(): Promise<string> {
  return "mock-token-for-local-development";
}
```

Rename existing `AuthProvider` → `RealAuthProvider`, then add:

```ts
export function AuthProvider({ children }: { children: ReactNode }) {
  if (MOCK_AUTH) {
    return (
      <AuthContext.Provider
        value={{ session: MOCK_USER, loading: false, getToken: mockGetToken, role: "superadmin", isSuperadmin: true }}
      >
        {children}
      </AuthContext.Provider>
    );
  }
  return <RealAuthProvider>{children}</RealAuthProvider>;
}
```

---

## 6. Route guards — add `MOCK_AUTH` bypass to every `beforeLoad`

Five route files have a Firebase `authReady()` guard in `beforeLoad`. Each
needs one line added at the top:

### Files to patch:
- `frontend/src/routes/admin.tsx`
- `frontend/src/routes/intake.index.tsx`
- `frontend/src/routes/intake.$id.tsx`
- `frontend/src/routes/intake.$id.results.tsx`
- `frontend/src/routes/intake.$id.report.tsx`

### Change per file:

```ts
// 1. Add to import
import { auth, MOCK_AUTH } from "@/lib/firebase";

// 2. Add as first line inside beforeLoad: async () => {
if (MOCK_AUTH) return;
```

---

## 7. `mock-backend/` (new directory — entire contents are new)

A standalone Express server that stubs every API endpoint the frontend calls.
Run with `node mock-backend/server.js` on port 3001.

See `mock-backend/server.js` for the full implementation. Key contracts:
- All intake status names match frontend (`reviewed`, `validated_by_client`,
  `decomposed`, `in_research`, `delivered` — not `in_review` / `validated`).
- Template routes are `/admin/spaces/:spaceId/templates` (per-space, not `/admin/templates`).
- `/intakes/templates` is declared **before** `/intakes/:id` to avoid Express
  swallowing the static path as a dynamic segment.
- Answers use `PATCH /intakes/:id/answers` (not PUT).
- Template schema uses `longtext` (not `textarea`) — matches `FieldType` in `intake-types.ts`.
- Unimplemented routes return `501` (not `200 {}`) so gaps fail loudly.

---

---

## 8. New component: `frontend/src/components/TopBar.tsx`

A thin sticky bar (`h-11`) with a compact language switcher and a disabled
notification bell placeholder. Mount it at the top of every authenticated
layout.

```tsx
import { Bell } from "lucide-react";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

export function TopBar({ persist = true }: { persist?: boolean }) {
  return (
    <div className="flex h-11 shrink-0 items-center justify-end gap-1 border-b border-ink/10 bg-paper px-6">
      <LanguageSwitcher persist={persist} compact />
      <button
        type="button"
        disabled
        title="Notificaties — binnenkort beschikbaar"
        aria-label="Notificaties"
        className="relative flex h-7 w-7 items-center justify-center text-ink/30 transition-colors"
      >
        <Bell className="h-4 w-4" />
        {/* Wire up badge once GET /me/notifications exists */}
      </button>
    </div>
  );
}
```

---

## 9. `frontend/src/components/LanguageSwitcher.tsx` — add `compact` prop

Add a `compact` boolean prop. When `true`, the trigger shows just the ISO
code ("NL") + a small chevron using a tight inline style, instead of the
full-width bordered box with the full language name.

```tsx
export function LanguageSwitcher({
  persist = true,
  compact = false,
}: {
  persist?: boolean;
  compact?: boolean;
}) {
  // ...
  // trigger:
  className={compact ? COMPACT_TRIGGER_CLASS : TRIGGER_CLASS}
  // content:
  {compact ? (
    <><span>{current.toUpperCase()}</span><ChevronsUpDown className="h-3 w-3 shrink-0 opacity-40" /></>
  ) : (
    <><span className="truncate">{t(`language.${current}`)}</span><ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" /></>
  )}
}
```

Add this constant alongside `TRIGGER_CLASS`:
```ts
const COMPACT_TRIGGER_CLASS =
  "flex items-center gap-1 px-2 py-1 font-mono text-[10px] uppercase tracking-widest " +
  "text-ink/50 hover:text-ink transition-colors";
```

Also update `PopoverContent` to use a fixed width and right-align when compact (otherwise the
popover inherits the tiny trigger width and clips the language names):
```tsx
<PopoverContent
  className={compact ? "w-36 p-0" : "w-[var(--radix-popover-trigger-width)] p-0"}
  align={compact ? "end" : "start"}
>

---

## 10. `frontend/src/components/admin/ProductShell.tsx` — mount TopBar, remove sidebar switcher

1. Replace `import { LanguageSwitcher }` with `import { TopBar }`.
2. Delete the sidebar language switcher block:
   ```tsx
   // DELETE:
   <div className="mt-4">
     <LanguageSwitcher persist />
   </div>
   ```
3. Wrap `<main>` in a flex column so TopBar sits above it:
   ```tsx
   // BEFORE:
   <main className="flex-1 px-6 py-8 md:px-10 md:py-10">{children}</main>

   // AFTER:
   <div className="flex flex-1 flex-col overflow-hidden">
     <TopBar />
     <main className="flex-1 overflow-y-auto px-6 py-8 md:px-10 md:py-10">{children}</main>
   </div>
   ```

---

## 11. `frontend/src/routes/intake.index.tsx` — mount TopBar, remove inline switcher

1. Replace `import { LanguageSwitcher }` with `import { TopBar }`.
2. Delete the inline `<div className="w-28"><LanguageSwitcher persist /></div>` from the
   header flex row.
3. Add `<TopBar />` as the first child of the outermost `<div className="min-h-screen ...">`:
   ```tsx
   <div className="min-h-screen bg-paper text-ink">
     <TopBar />
     <div className="mx-auto max-w-4xl px-6 py-12">
       ...
     </div>
   </div>
   ```

---

## 12. `frontend/src/routes/admin.pulse.intakes.$id.tsx` — move AISkillsPanel into workflow card

**Problem:** `<AISkillsPanel>` was mounted in `<main>` as a floating content block, visually
disconnected from the workflow stepper card (NextStepBanner + ResearchRunProgress).

**Fix:** Remove the existing mount in `<main>` and add it inside the workflow card div
(`mb-8 border border-ink/15 bg-paper`), between `<NextStepBanner>` and `<ResearchRunProgress>`.

```tsx
// INSIDE the workflow card (between NextStepBanner and ResearchRunProgress):
{/* AI enrichment skills — self-gates on status (submitted → decomposed).
    Lives inside the workflow card as a secondary action block. */}
<AISkillsPanel intakeId={intake.id} intakeStatus={intake.status} />

{intake.status === "in_research" && (
  <ResearchRunProgress intakeId={intake.id} onRetry={onRetryResearch} />
)}

// REMOVE the old free-standing mount in <main>:
// {/* AISkillsPanel self-gates on status (submitted → decomposed); mount unconditionally. */}
// <AISkillsPanel intakeId={intake.id} intakeStatus={intake.status} />
```

`AISkillsPanel` already has its own `VISIBLE_STATUSES` guard so it hides itself outside of
`submitted`, `reviewed`, `validated_by_client`, and `decomposed` — no conditional wrapper needed.

---

## 13. `mock-backend/server.js` — all 8 intake statuses + correct API shapes

**Problem:** Mock only had 2 intakes (draft + submitted). The UI's workflow stepper and phase
machine couldn't be exercised past the first step. Also:
- `/intakes/:id/skill-runs` returned `{ runs, total }` but the API client expects
  `{ latest, runs }` (`SkillRunsView` shape).
- `/intakes/:id/skill-runs/stream` was unhandled → caught by the 501 catch-all →
  the SSE stream client enters its backoff retry loop (any non-404/401 non-OK response
  triggers `retry()`, not the clean `onFallback()` path).

**Fixes:**

1. Add one intake per status so every phase of the workflow is testable:
   - `int-001` → `draft`
   - `int-002` → `submitted`
   - `int-003` → `reviewed`, `validation_link_sent_at: null` (awaiting send)
   - `int-004` → `reviewed`, `validation_link_sent_at` set (awaiting client)
   - `int-005` → `validated_by_client`, `context_pack_artifact_id` set (awaiting research start)
   - `int-006` → `in_research`
   - `int-007` → `delivered`, `results_link_sent_at` set (completed)
   - `int-008` → `archived`

2. Fix `skill-runs` list response shape:
   ```js
   // BEFORE:
   res.json({ runs, total: runs.length });
   // AFTER:
   const latest = runs.length > 0 ? runs[runs.length - 1] : null;
   res.json({ latest, runs, total: runs.length });
   ```

3. Add an SSE stream endpoint that returns 404 (no active run to stream):
   ```js
   // Return 404 — client handles 404/401 as "no active run":
   //   closed=true → onFallback() → single poll → stops.
   // Any other non-OK status triggers backoff retry loop.
   app.get("/intakes/:id/skill-runs/stream", (req, res) => {
     res.status(404).json({ detail: "No active skill run to stream" });
   });
   ```
   **Important:** declare this route BEFORE `/intakes/:id/skill-runs/:runId` so Express
   doesn't match the string "stream" as a runId.

4. Add per-intake mock skill runs (succeeded apply-intake-skill for intakes 003–008 and a
   context-pack run for int-005) and pre-filled answers for all non-draft intakes.

---

---

## Change 14 — Fix "Maximum update depth exceeded" infinite loop

**Files:** `src/routes/admin.pulse.intakes.$id.tsx`

Three cascading setState loops were diagnosed and fixed:

### 14a — `reviewData?.parsed ?? {}` inline object (root cause of the Popover crash)

```tsx
// BEFORE (line ~230):
const reviewState = useAIReview(reviewData?.parsed ?? {});

// AFTER:
// Module-level constant — must NOT be an inline literal:
const EMPTY_PARSED: ParsedSkillOutput = {};
// ...inside component:
const reviewState = useAIReview(reviewData?.parsed ?? EMPTY_PARSED);
```

**Why:** When `reviewData` is null, `?? {}` creates a new object reference on every render.
`useAIReview` has `useEffect([parsed])` which fires whenever `parsed` changes → calls
`setDecisions` + `setExtraQuestions` → re-render → new `{}` → fires again → infinite loop.
Opening any Popover (e.g. the AI-verrijking dropdown) triggers an extra re-render that made
the loop visible as a hard crash. A module-level constant has a stable reference forever.

### 14b — `loadSkillRuns` useCallback depends on `intake` object

```tsx
// BEFORE:
const loadSkillRuns = useCallback(async () => {
  if (!intake) return;
  const res = await listSkillRuns(intake.id);
  ...
}, [intake]);  // ← new reference every time load() sets intake

// AFTER:
const intakeIdForRuns = useRef<string | undefined>(undefined);
intakeIdForRuns.current = intake?.id;           // updated every render, no re-render

const loadSkillRuns = useCallback(async () => {
  if (!intakeIdForRuns.current) return;
  const res = await listSkillRuns(intakeIdForRuns.current);
  ...
}, []);  // ← stable forever
```

**Why:** `load()` always creates a new `intake` object via `setIntake(row)`. This gave
`loadSkillRuns` a new function reference after every fetch, which destabilised the two
effects that list it as a dep (review-mode entry at ~L807, terminal-status refresh at ~L825).

### 14c — `closeRef` side-effect during render in AISkillsPanel

Removed the `closeRef.current = ...` assignment that ran as a side-effect every render inside
`AISkillsPanel`. While refs don't trigger re-renders, assigning to `.current` during render
is a pattern React Strict Mode flags. The ref was also unused — `setOpen(false)` is called
inline in `run(...)`. Removed entirely.

---

## Summary of why each change exists

| Change | Reason |
|---|---|
| `vite.vite.server.allowedHosts` | Replit proxy domain was blocked by Vite's host check |
| `vite.vite.server.proxy` | `localhost:3001` is unreachable from the user's browser; proxy through port 5000 fixes it |
| `VITE_API_BASE_URL=/api` | Makes `apiFetch` use relative paths so the Vite proxy intercepts them |
| `MOCK_AUTH` in `firebase.ts` | Single flag, imported everywhere — avoids drift |
| `currentIdToken` mock | Without this, `apiFetch` returns `NOT_LOGGED_IN` because `auth.currentUser` is null |
| `AuthProvider` split | React rules of hooks — can't early-return before `useState` calls |
| `beforeLoad` bypasses | Firebase `authReady()` hangs forever when no real Firebase user exists |
| `mock-backend/` | Provides typed API responses so the UI renders data, not error/empty states |
