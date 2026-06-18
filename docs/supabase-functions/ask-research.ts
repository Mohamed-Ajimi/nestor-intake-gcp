import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const VOYAGE_API_KEY = Deno.env.get("VOYAGE_API_KEY")!;
const ANTHROPIC_API_KEY = Deno.env.get("ANTHROPIC_API_KEY")!;

const VOYAGE_MODEL = "voyage-3-large";
const VOYAGE_DIM = 1024;
const VOYAGE_ENDPOINT = "https://api.voyageai.com/v1/embeddings";

const ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages";
const HAIKU_MODEL = "claude-haiku-4-5-20251001";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-supabase-api-version",
  "Access-Control-Max-Age": "86400",
};

const SYSTEM_PROMPT = `Je bent Nestor, een onderzoeksassistent voor strategische research.
Beantwoord de vraag van de gebruiker UITSLUITEND op basis van de aangeleverde context-fragmenten.

Regels voor je antwoord:
- Schrijf in helder, professioneel Belgisch Nederlands
- Volledig coherent in volzinnen Ã¢ÂÂ geen losse fragmenten of opsomming van losse feiten
- Lengte: 150 tot 400 woorden, afhankelijk van de complexiteit van de vraag
- Geen markdown opmaak (geen **, geen ###, geen --- separators, geen bullet points met asterisken)
- Geen verwijzingen naar bronnen, filenames, "micro_001", "Gemini Deep Research", URLs of encoded strings
- Geen "volgens de bron" of "in het document staat" Ã¢ÂÂ gewoon het antwoord neerzetten alsof jij het zelf weet
- Als de context onvoldoende is om de vraag te beantwoorden: zeg dat eerlijk in 1-2 zinnen, en suggereer een betere herformulering
- Geen samenvatting of tussenkop Ã¢ÂÂ alleen het antwoord zelf
- Lopende paragrafen, geen lijsten tenzij het echt natuurlijk is`;

async function getEmbedding(query: string): Promise<{ embedding: number[]; tokens: number }> {
  const res = await fetch(VOYAGE_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${VOYAGE_API_KEY}`,
    },
    body: JSON.stringify({
      input: [query],
      model: VOYAGE_MODEL,
      input_type: "query",
      output_dimension: VOYAGE_DIM,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Voyage API ${res.status}: ${errText}`);
  }
  const json = await res.json();
  return {
    embedding: json.data[0].embedding,
    tokens: json.usage?.total_tokens ?? 0,
  };
}

async function callHaiku(query: string, contextChunks: string[]): Promise<string> {
  const contextBlock = contextChunks
    .map((c, i) => `--- Fragment ${i + 1} ---\n${c}`)
    .join("\n\n");

  const userMessage = `Hier zijn ${contextChunks.length} fragmenten uit het onderzoeksdossier:\n\n${contextBlock}\n\n---\n\nVraag van de gebruiker: ${query}\n\nGeef je antwoord als ÃÂ©ÃÂ©n coherente tekst.`;

  const res = await fetch(ANTHROPIC_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: HAIKU_MODEL,
      max_tokens: 1500,
      system: SYSTEM_PROMPT,
      messages: [{ role: "user", content: userMessage }],
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Anthropic API ${res.status}: ${errText}`);
  }
  const json = await res.json();
  const answer = (json.content as Array<{ type: string; text?: string }>)
    .filter((b) => b.type === "text")
    .map((b) => b.text || "")
    .join("\n")
    .trim();
  return answer;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), {
      status: 405,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  type Body = {
    intake_id?: string;
    client_results_token?: string;
    query?: string;
    top_k?: number;
    include_fragments?: boolean;
  };

  let body: Body;
  try {
    body = await req.json();
  } catch (e) {
    return new Response(
      JSON.stringify({ error: "invalid JSON: " + (e as Error).message }),
      { status: 400, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  if (!body.query || body.query.trim().length === 0) {
    return new Response(
      JSON.stringify({ error: "query is required" }),
      { status: 400, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
    db: { schema: "nestor" },
  });

  let intakeId: string | null = null;
  let isKlantPath = false;

  if (body.client_results_token) {
    isKlantPath = true;
    const { data: intakeRow, error: tokenErr } = await supabase
      .from("intakes")
      .select("id")
      .eq("client_results_token", body.client_results_token)
      .in("status", ["in_research", "decomposed", "delivered"])
      .single();
    if (tokenErr || !intakeRow) {
      return new Response(
        JSON.stringify({ error: "invalid_token" }),
        { status: 401, headers: { ...cors, "Content-Type": "application/json" } },
      );
    }
    intakeId = intakeRow.id;
  } else if (body.intake_id) {
    intakeId = body.intake_id;
  } else {
    return new Response(
      JSON.stringify({ error: "intake_id or client_results_token is required" }),
      { status: 400, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  const top_k = Math.min(Math.max(body.top_k ?? 8, 1), 25);

  try {
    const { embedding } = await getEmbedding(body.query);

    const { data: chunks, error: rpcErr } = await supabase.rpc("match_artifacts", {
      query_embedding: embedding,
      filter_intake_id: intakeId,
      filter_question_id: null,
      match_threshold: 0,
      match_count: top_k,
    });
    if (rpcErr) throw new Error("rpc match_artifacts: " + rpcErr.message);

    const chunkArr = (chunks ?? []) as Array<{
      chunk_text: string;
      similarity: number;
      research_question_id: string | null;
      filename?: string;
      source?: string;
    }>;

    if (chunkArr.length === 0) {
      return new Response(
        JSON.stringify({
          success: true,
          query: body.query,
          answer:
            "Ik vind geen informatie in het onderzoeksdossier die deze vraag beantwoordt. Probeer een andere formulering of stel een specifiekere vraag.",
          sources_used: 0,
          model: HAIKU_MODEL,
        }),
        { headers: { ...cors, "Content-Type": "application/json" } },
      );
    }

    const answer = await callHaiku(body.query, chunkArr.map((c) => c.chunk_text));

    const responseBody: Record<string, unknown> = {
      success: true,
      query: body.query,
      answer: answer,
      sources_used: chunkArr.length,
      model: HAIKU_MODEL,
    };

    if (!isKlantPath && body.include_fragments) {
      responseBody.fragments = chunkArr;
    }

    return new Response(JSON.stringify(responseBody), {
      headers: { ...cors, "Content-Type": "application/json" },
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ success: false, error: (err as Error).message }),
      { status: 500, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }
});
