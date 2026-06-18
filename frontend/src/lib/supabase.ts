import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const supabase =
  url && key
    ? createClient(url, key, {
        db: { schema: "nestor" },
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
          storage: typeof window !== "undefined" ? window.localStorage : undefined,
          storageKey: "sb-nestor-auth",
        },
      })
    : null;

// Back-compat alias. Use `supabase.schema("public")` for public-schema queries
// instead of constructing a second GoTrueClient (which triggers
// "Multiple GoTrueClient instances detected" warnings).
export const supabasePublic = supabase;

export type Product = {
  id?: string | number;
  name: string;
  tagline: string | null;
  description: string | null;
  slug?: string | null;
};
