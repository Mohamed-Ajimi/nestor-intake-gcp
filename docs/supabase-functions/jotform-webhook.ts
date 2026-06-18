// DEPRECATED Ã¢ÂÂ Jotform integration retired in favor of Tally.
// This stub returns 410 Gone for any incoming webhook.
import "jsr:@supabase/functions-js/edge-runtime.d.ts";

Deno.serve(() => {
  return new Response(
    JSON.stringify({
      error: "Gone",
      message: "jotform-webhook is deprecated. Use tally-webhook instead."
    }),
    { status: 410, headers: { "content-type": "application/json" } }
  );
});
