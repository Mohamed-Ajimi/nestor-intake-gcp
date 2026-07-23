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
