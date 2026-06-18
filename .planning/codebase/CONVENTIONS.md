# Coding Conventions

**Analysis Date:** 2026-06-18

## Naming Patterns

**Files:**
- Routes: dot-separated TanStack file-route convention — `admin.pulse.intakes.$id.tsx`, `auth.login.tsx`, `intake.$token.tsx`
- Components: PascalCase — `IntakeForm.tsx`, `NextStepBanner.tsx`, `SkillRunProgress.tsx`
- UI primitives (shadcn): lowercase-kebab — `button.tsx`, `alert-dialog.tsx`, `dropdown-menu.tsx`
- Lib/utilities: camelCase or kebab — `intake-types.ts`, `intake-phase.ts`, `salesLabels.ts`, `salesMail.ts`
- Generated files: suffix `.gen.ts` — `routeTree.gen.ts`
- Admin sub-components: PascalCase — `ClientDetailDrawer.tsx`, `ProductBadge.tsx`
- One file exception: `clientPills.tsx` (lowercase — inconsistent, flag when adding similar files)

**Functions and hooks:**
- React components: PascalCase — `IntakeDetailPage`, `LoginPage`, `PulseLayout`, `StatusPill`
- Custom hooks: `use` prefix camelCase — `useIsMobile`, `useAuth`, `useActiveSkillRun`, `useSkillRunFull`
- Event handlers: `handle` prefix camelCase — `handleSubmit`, `handleSave`, `handleCancel`, `handleStatusChange`, `handleSemanticSearch`
- Action callbacks passed as props: `on` prefix — `onRunSkill`, `onCopyIntakeLink`, `onSendValidationMail`
- Async helpers: verb + noun — `sendSalesMail`, `loadSkillRuns`, `fetchLatest`
- Pure helpers (non-handler, non-hook): camelCase verb — `derivePhase`, `displayQuestionText`, `stripAnchorPrefix`, `isAnchorQuestion`, `fmt`, `fmtDate`

**Variables:**
- camelCase throughout — `intakeData`, `clientMap`, `skillRuns`, `answersMap`
- Boolean states named with `is`/`has` prefix where possible — `isMobile`, `hasArtifacts`, `hasChanges`
- Loading states: `loading`, `saving`, `sending`, `submitting`, `busy`, `updatingStatus`
- Error states: `error` (string | null), `errors` (string[]) for multi-field validation

**Types and interfaces:**
- Local row types: PascalCase suffix `Row` — `IntakeRow`, `AnswerRow`, `SkillRun`
- Domain types: plain PascalCase — `Intake`, `Client`, `Phase`, `Product`
- Prop types: inline `{ prop: Type }` or named with `Props` suffix — `type Props = { ... }`
- Exported types: named and exported — `ActiveSkillRun`, `BusyKey`, `IntakePayload`, `IntakeSchema`
- Option arrays: `SCREAMING_SNAKE_CASE` — `STATUS_OPTIONS`, `STATUS_LABEL`, `STATUS_VARIANT`, `MEETING_TYPE_OPTIONS`
- Constants: `SCREAMING_SNAKE_CASE` — `MOBILE_BREAKPOINT`, `ANCHOR_PREFIX`, `ALLOWED_DOMAINS`

## Code Style

**Formatting (Prettier):**
- `printWidth`: 100
- `semi`: true (semicolons required)
- `singleQuote`: false (double quotes)
- `trailingComma`: "all"
- Config: `frontend/.prettierrc`

**Linting (ESLint v9 flat config):**
- Base: `@eslint/js` recommended + `typescript-eslint` recommended
- Plugins: `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `eslint-plugin-prettier`
- `@typescript-eslint/no-unused-vars`: turned **off** (tolerated in this codebase)
- `react-hooks/rules-of-hooks`: enforced
- `react-hooks/exhaustive-deps`: enforced (with selective `eslint-disable-next-line` suppressions)
- `react-refresh/only-export-components`: warn
- Config: `frontend/eslint.config.js`

**TypeScript:**
- Strict: yes (TypeScript 5.8)
- `any` use: present but discouraged. 53 occurrences of `as any` / `as unknown` spread across ~11 files; route/data layer uses frequent `as unknown as Type` casts because Supabase JS SDK generics are not wired up (no generated DB types)
- `import type` used consistently for type-only imports
- `void` used to intentionally discard promise results — `void fetch(...)`, `void supabase!.removeChannel(...)`
- `!` non-null assertions used sparingly on `supabase!` after null-guards

## Import Organization

**Order (enforced by Prettier integration, not strict ESLint order rule):**
1. React and framework (`react`, `@tanstack/react-router`, `@tanstack/react-query`)
2. External libraries (`date-fns`, `sonner`, `lucide-react`, `zod`)
3. Internal lib (`@/lib/supabase`, `@/lib/auth-context`, `@/lib/intake-types`, `@/lib/intake-phase`)
4. Internal components (`@/components/intake/...`, `@/components/ui/...`)
5. Relative imports (rare — only within same directory)

**Path Aliases:**
- `@/` maps to `frontend/src/` (configured in `vite-tsconfig-paths`)
- Always use `@/` — never relative `../../` for cross-directory imports

**Barrel files:** None — each file is imported directly by path.

## Data Fetching Pattern

**Two patterns coexist in the codebase:**

**Pattern A — TanStack Query** (used on public-facing / token routes):
Used in `frontend/src/routes/intake.$token.tsx`:
```typescript
const { data, isLoading, error } = useQuery({
  queryKey: ["intake", token],
  queryFn: async (): Promise<IntakePayload> => {
    if (!supabase) throw new Error("Supabase not configured");
    const { data, error } = await supabase.rpc("get_intake_by_token", { p_token: token });
    if (error) throw error;
    return data as IntakePayload;
  },
  retry: false,
});
```

**Pattern B — Local useState + useCallback + useEffect** (dominant in admin routes):
Used throughout `frontend/src/routes/admin.pulse.intakes.$id.tsx`, `admin.pulse.intakes.index.tsx`, etc.:
```typescript
const [data, setData] = useState<T | null>(null);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);

const load = useCallback(async () => {
  if (!supabase) { setError("..."); setLoading(false); return; }
  setLoading(true);
  const { data, error } = await supabase.schema("nestor").from("intakes").select(...);
  if (error) { setError(error.message); setLoading(false); return; }
  setData(data);
  setLoading(false);
}, [dependencies]);

useEffect(() => {
  let cancelled = false;
  (async () => { if (!cancelled) await load(); })();
  return () => { cancelled = true; };
}, [load]);
```

**For the GCP re-platform:** Pattern A (TanStack Query) is preferred — it eliminates manual `cancelled` flags and provides cache invalidation. Pattern B should be migrated toward Pattern A when touching existing code.

## Supabase Client Usage

- Null-checked on every use: `if (!supabase) return;` / `if (!supabase) { setError("Supabase niet geconfigureerd."); ... }`
- Schema qualifier always explicit: `.schema("nestor")` or `.schema("public")`
- The `supabasePublic` export in `frontend/src/lib/supabase.ts` is an alias for `supabase` (same client, back-compat only — do not create a second GoTrueClient)
- Edge function calls via `supabase.functions.invoke("function-name", { body: {...} })`, not raw fetch (except the fire-and-forget `apply-intake-skill` pattern in `admin.pulse.intakes.$id.tsx`)

## Component Design

**Route components:**
- Named function (not arrow) — `function IntakeDetailPage() { ... }`
- Route export always `export const Route = createFileRoute(...)({ component: FunctionName })`
- Local helper components (non-exported) defined at file bottom — `Meta`, `LinkRow`, `ResultsLinkRow`, `StatusPill`, `DeliveredAtEditor`

**Reusable components:**
- Named exports — `export function IntakeForm(...)`, `export function NextStepBanner(...)`
- Props typed inline or as `type Props = { ... }` immediately before the function

**UI primitives (shadcn):**
- `cva` + `cn` pattern for variant-based styling — see `frontend/src/components/ui/button.tsx`
- `React.forwardRef` used on all shadcn primitives
- `displayName` set on forwarded-ref components

**Small presentational components:**
- Defined inline in the same file as their parent when only used there — `PrimaryBtn`, `SecondaryBtn`, `Tooltip`, `RunningClock` in `NextStepBanner.tsx`
- Prop type defined inline — `{ onClick: () => void; busy?: boolean; children: React.ReactNode }`

## Tailwind / Styling

**Approach:** Tailwind CSS v4 utility classes. Design system uses custom semantic tokens (`text-ink`, `bg-paper`, `bg-paper2`, `bg-paperLight`, `border-ink`) — not raw Tailwind colour names.
- `cn()` from `frontend/src/lib/utils.ts` for conditional class merging (clsx + tailwind-merge)
- Shared class strings extracted to `const` when reused within a file:
  ```typescript
  const primaryCls = "inline-flex items-center gap-2 bg-ink px-4 py-2 ...";
  ```
- Inline `style` prop used only for dynamic values (colour driven by runtime data):
  ```typescript
  style={{ borderLeftColor: accentColor }}
  ```
- Font families: IBM Plex Mono (`font-mono`), IBM Plex Sans (`font-sans`), IBM Plex Serif (`font-serif`) — loaded via Google Fonts and `@fontsource` packages

## Error Handling

**Async operations:**
- Supabase error: destructure `error` from result, check, then `toast.error(error.message)`
- Pattern: try/catch with `finally` to clear loading state:
  ```typescript
  try {
    const { error } = await supabase...;
    if (error) throw error;
    toast.success("...");
  } catch (e) {
    toast.error(`Mislukt: ${(e as Error).message}`);
  } finally {
    setLoading(false);
  }
  ```
- User notifications: **always** via `sonner` toast (`toast.success`, `toast.error`, `toast.message`) — never `alert()` except for destructive confirmation dialogs (`confirm(...)`)
- Network/API errors from `salesMail.ts` pattern: return `{ success: boolean; error?: string }` (no throw)

**UI error states:**
- Loading: `<Skeleton>` components from `@/components/ui/skeleton` during data fetch
- Error: inline error message (`<p className="text-sm text-red-600">{error}</p>`) or full-page error card
- Router-level: `DefaultErrorComponent` in `frontend/src/router.tsx` — shows error message in dev only (`import.meta.env.DEV`)
- 404: `NotFoundComponent` in `frontend/src/routes/__root.tsx`

**Cancellation pattern** (for useEffect async):
```typescript
useEffect(() => {
  let cancelled = false;
  (async () => {
    if (!cancelled) await doSomething();
  })();
  return () => { cancelled = true; };
}, [deps]);
```
This pattern appears in `auth-context.tsx`, `SkillRunProgress.tsx`, `admin.pulse.intakes.$id.tsx`.

## Logging

- `console.error` for fetch/data errors in development — not removed before commit in this codebase
- `console.warn` in hooks for non-fatal degraded states (e.g. `[SkillRunProgress] latest run fetch failed`)
- No structured logging library

## Comments

**Inline comments:** Used to explain non-obvious decisions, especially around Supabase quirks and intentional patterns:
```typescript
// Back-compat alias. Use `supabase.schema("public")` for public-schema queries
// instead of constructing a second GoTrueClient (which triggers
// "Multiple GoTrueClient instances detected" warnings).
```

**Dutch comments:** Business-logic comments are frequently written in Dutch (matches the target user language of the app), e.g.:
```typescript
// Fase-machine voor de intake-detail-pagina.
// Pure helper — geen React, geen Supabase.
```

**Section markers:** `// ============== Section Name ==============` used in large route files to delimit handler groups.

**JSDoc/TSDoc:** Not used — function signatures self-document via TypeScript types. Exception: JSDoc used on exported hooks in `SkillRunProgress.tsx` to explain behaviour changes.

## Module Design

**Exports:**
- Named exports preferred — `export function`, `export type`, `export const`
- Default exports: only used by TanStack Router file-route convention (none explicitly in source)
- Route files always export `const Route = createFileRoute(...)(...)` as the primary export

**Lib modules** (`frontend/src/lib/`):
- `supabase.ts`: client singleton + shared types (`Product`)
- `auth-context.tsx`: `AuthProvider` + `useAuth` hook (React Context pattern)
- `intake-types.ts`: pure TypeScript types for intake domain (no logic)
- `intake-phase.ts`: pure phase-machine logic (no React, no Supabase — explicitly noted in file comment)
- `salesLabels.ts`: label maps + option arrays for sales domain
- `salesMail.ts`: standalone async function, no side effects
- `research-question.ts`: pure string helpers
- `utils.ts`: `cn()` utility only

---

*Convention analysis: 2026-06-18*
