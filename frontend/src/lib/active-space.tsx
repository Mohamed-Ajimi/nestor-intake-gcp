import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

// frontend/src/lib/active-space.tsx — the superadmin "active space" view-filter.
//
// SECURITY (T-06-13): the active-space id is UX STATE, NEVER an authorization input.
// `withActiveSpace()` appends `?space_id=<id>` to read paths so a superadmin (already
// authorized for all spaces) can narrow the displayed set to a single client. For a
// regular user the param is inert — the backend re-derives the user's space from the
// verified token and ignores the query param, so it can never widen access.
//
// The non-hook module accessor (`_activeSpaceId` + `withActiveSpace`) mirrors
// `client.ts` `currentIdToken` (lines 24-26): a module-level value read by the
// `lib/api` transport WITHOUT a React hook, kept in sync by the provider effect.

const STORAGE_KEY = "nestor.activeSpaceId";

// ---------------------------------------------------------------------------
// Non-hook module accessor (mirrors client.ts currentIdToken / auth singleton)
// ---------------------------------------------------------------------------

let _activeSpaceId: string | null = null;

/**
 * Set the module-level active-space id. Called by the provider effect so the
 * non-hook accessor stays in sync with React state — the `lib/api` modules read
 * `withActiveSpace(...)` without depending on a hook.
 */
export function setActiveSpaceId(id: string | null) {
  _activeSpaceId = id;
}

/**
 * Append the superadmin view-filter to a read path.
 *
 * Returns `${path}?space_id=<id>` when a space is selected, else `path` unchanged
 * ("Alle klanten"). This is a UX filter only — see the security note above.
 */
export function withActiveSpace(path: string): string {
  return _activeSpaceId ? `${path}?space_id=${_activeSpaceId}` : path;
}

// ---------------------------------------------------------------------------
// React provider (mirrors auth-context.tsx AuthProvider/useAuth)
// ---------------------------------------------------------------------------

type ActiveSpaceContextValue = {
  // The selected space id, or null for "Alle klanten" (no filter).
  activeSpaceId: string | null;
  // Update the selection (also syncs the non-hook accessor + localStorage).
  setActiveSpace: (id: string | null) => void;
};

const ActiveSpaceContext = createContext<ActiveSpaceContextValue>({
  activeSpaceId: null,
  setActiveSpace: () => {},
});

/** Read the persisted selection (browser only; null on SSR / first run). */
function readPersisted(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function ActiveSpaceProvider({ children }: { children: ReactNode }) {
  const [activeSpaceId, setActiveSpaceIdState] = useState<string | null>(() =>
    readPersisted(),
  );

  // Keep the non-hook module accessor + localStorage in sync with React state so
  // `withActiveSpace(...)` (read from the transport layer) always reflects the
  // current selection — mirrors the auth-context effect syncing the auth singleton.
  useEffect(() => {
    setActiveSpaceId(activeSpaceId);
    if (typeof window === "undefined") return;
    try {
      if (activeSpaceId) {
        window.localStorage.setItem(STORAGE_KEY, activeSpaceId);
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      /* ignore — persistence is best-effort UX state */
    }
  }, [activeSpaceId]);

  const setActiveSpace = (id: string | null) => setActiveSpaceIdState(id);

  return (
    <ActiveSpaceContext.Provider value={{ activeSpaceId, setActiveSpace }}>
      {children}
    </ActiveSpaceContext.Provider>
  );
}

export function useActiveSpace() {
  return useContext(ActiveSpaceContext);
}
