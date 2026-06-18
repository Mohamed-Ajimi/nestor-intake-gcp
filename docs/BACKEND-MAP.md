# New Nestor (agenic) backend map — pulled 2026-06-18 (read-only, via Management API)

Project: **"Sweep Database Project"** ref `inmsssedwdmgtnhaydmg`, region eu-west-1.
Schemas: `nestor` (main app), `sales` (sales product), `public`, + Supabase system schemas.
Backend = Supabase: Postgres (RLS) + PostgREST (`nestor` schema via Accept-Profile) +
21 Deno edge functions + Storage (bucket `nestor-uploads`).

## nestor tables (14)
- organizations, organization_memberships, products — tenancy + product catalog
- intakes, intake_answers, intake_templates — the intake forms (template = JSON schema of sections/fields)
- skill_runs — runs of the "intake skill" (apply-intake-skill)
- decompositions, research_questions — brief decomposed into prioritized research questions
- research_artifacts, findings, deliverables — research outputs
- artifact_embeddings, search_index — RAG / semantic search

## Edge functions (21)
Intake intake: tally-webhook, jotform-webhook (external form ingestion)
Processing: structure-answers, extract-insights, transcribe-audio, apply-intake-skill, generate-context-pack
Research: **run-research** (the deep-research seam), ask-research (RAG Q&A)
Embeddings/search: generate-embeddings, embed-artifact, embed-pending-search, match-artifacts, semantic-search, search-global, upload-pending-artifacts
Output: save-manual-synthesis, send-pulse-mail
Sales: generate-battlecard, send-sales-mail, sales-friday-reminder

## THE TRIBUNAL INTEGRATION CONTRACT (run-research v3)
Trigger: `supabase.functions.invoke("run-research", { body: { intake_id } })`.
Today it is a SHALLOW aggregator: per open research_question it runs 3 sources
(SerpAPI + SearchAPI + Apify rag-web-browser) + optional hard-coded domain crawlers.
Async (EdgeRuntime.waitUntil), ~5-10 min/question. Uses SERVICE_ROLE key (bypasses RLS).

INPUT it reads:
- `intakes` row by id
- `research_questions WHERE intake_id=? AND status='open' ORDER BY priority` — the decomposed brief.
  cols: id, intake_id, decomposition_id, question_text, question_type, priority, rationale, status

OUTPUT it writes:
1. `intakes.status := 'in_research'`
2. Storage `nestor-uploads/{intake_id}/research/{question_id}/{label}.json` (raw provider JSON)
3. `research_artifacts` INSERT per source: {intake_id, research_question_id, source, artifact_type:'search_result',
   filename, storage_bucket, storage_path, byte_size, mime_type, text_content (markdown), embed_status:'pending', notes}

Downstream (already built): embed-pending-search embeds artifacts → search_index/artifact_embeddings;
ask-research does RAG over them; admin uploads/sets a `deliverables` row (final report, has client_view_token)
→ status flows to 'delivered' → results link emailed via send-pulse-mail.

### Best output target for Tribunal's VERIFIED claims = `findings`
findings cols: id, intake_id, research_question_id, kind(enum), label, summary, supporting_text,
**confidence (real)**, **sources (jsonb)**, llm_model, reviewed_by, reviewed_at, archived, created_at.
→ This table is already shaped for claims-with-confidence-and-sources = Tribunal's native output.
So Tribunal can: read research_questions, do deep research + adversarial verification, then write
research_artifacts (raw evidence) AND findings (verified claims w/ confidence+sources), and a deliverables report.

## nestor RPCs (Postgres functions, called from the front-end)
Token (client-facing, no login): get_intake_by_token, save_intake_answer, submit_intake,
get_results_by_token, get_final_report_by_token, get_synthesis_text_by_token,
get_artifact_storage_path_by_token, set_client_answer_artifact, intake_id_from_token, ensure_intake_tokens
Admin/data: list_organizations, user_organization_ids, set_final_report, refresh_search_index,
match_artifacts, match_search_index, prefill_intake_answers
Triggers: persist_questions_on_research_start, tg_bump_to_in_research, tg_bump_to_delivered,
tg_fire_embed_artifact, auto_create_org_for_client, handle_new_agenic_user, tg_grant_master_admin_on_client_org, set_updated_at, tg_set_*

## FULL FLOW — intake status state machine (nestor.intakes.status)
draft → submitted → reviewed → validated_by_client → decomposed → in_research → delivered (→ archived)

1. draft: intake created (admin: admin.pulse.intakes.new). prefill_intake_answers trigger seeds client_name.
   Client fills the form — either the app's own form (RPC save_intake_answer per field) OR an
   external Tally/Jotform form (tally-webhook/jotform-webhook map fields → intake_answers via DB
   mapping tables tally_form_mappings/tally_field_mappings/tally_option_mappings).
2. submit_intake(token): draft→submitted.
3. submitted: admin runs apply-intake-skill (Claude sonnet-4-5, "Nestor Intake Decomposer" prompt,
   max 5 sharp questions, 4 domains competitor/customer/trend/positioning, bias-radar + blind spots).
   Output = STRICT JSON → skill_runs.output_parsed (refined Qs, additional Qs, dropped, gaps). NOTE:
   this does NOT write research_questions; it's a suggestion the admin reviews/edits (AIReviewPanel,
   ValidationDiff, proposal_list field). Approved/edited questions are stored back into
   intake_answers under field_key 'questions' (+ 'extra_questions_proposed'). Admin → reviewed.
4. reviewed: admin sends client a validation link (send-pulse-mail). Client confirms via
   submit_intake(validation_token): reviewed→validated_by_client.
5. validated_by_client: admin runs generate-context-pack (Claude, condenses intake → 12-section
   markdown briefing "for Nestor the researcher"; appends research questions verbatim as §12).
   Writes a research_artifacts row (artifact_type='note'), sets intakes.context_pack_artifact_id,
   status→decomposed, skill_runs.applied_at.
6. decomposed: admin clicks Start Research → invoke run-research {intake_id}.
   run-research PATCHes status→in_research; that UPDATE fires trigger
   persist_questions_on_research_start which MATERIALIZES nestor.research_questions from
   intake_answers 'questions' (priority 5..1, type descriptive) + approved 'extra_questions_proposed'
   (priority 2), creating a decompositions row. run-research then reads research_questions
   (status='open') and runs its 3-source search per question (see contract above).
   (Alt manual path: admin can set status in_research directly; tg_bump_to_in_research also flips
   decomposed→in_research when a research_artifact is inserted.)
7. in_research: artifacts embedded (embed-pending-search), RAG via ask-research/semantic-search.
   Admin assembles/uploads the final report → deliverables row; set_final_report RPC; when a
   client_results_token is set, tg_bump_to_delivered flips in_research→delivered.
8. delivered: results link emailed (send-pulse-mail); client views via get_results_by_token /
   get_final_report_by_token (token routes, no login).

KEY for Tribunal: the validated, prioritized brief = nestor.research_questions (materialized at
research-start from intake_answers.questions). That is Tribunal's input. Tribunal's verified
output → research_artifacts (evidence) + findings (claims w/ confidence+sources) + a deliverables report.

## Function secrets NOT pulled (set in Supabase, needed to actually run): SERPAPI_API_KEY,
SEARCHAPI_API_KEY, APIFY_API_TOKEN, plus LLM keys for the skill/extract functions, email provider key.

## How this was pulled
Management API (https://api.supabase.com) with a Personal Access Token:
- GET /v1/projects/{ref}/functions[/{slug}/body]  → function bundles in ./functions/<slug>/index.ts
  (ESZIP format: small binary header, then transpiled JS, then ORIGINAL TS in the trailing sourcemap sourcesContent)
- POST /v1/projects/{ref}/database/query {query}   → schema + RPC introspection
Token stored at ./.pat (gitignored location, outside both repos) — REVOKE after use at
https://supabase.com/dashboard/account/tokens
