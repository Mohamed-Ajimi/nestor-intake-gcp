const express = require("express");
const cors = require("cors");

const app = express();
const PORT = 3001;

app.use(cors({ origin: true, credentials: true }));
app.use(express.json());

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_SPACE = {
  id: "space-001",
  name: "Acme Corp",
  slug: "acme",
  status: "active",
  default_locale: "nl",
};

const MOCK_SPACES = [MOCK_SPACE];

const MOCK_USERS = [
  {
    id: "mem-001",
    email: "admin@example.com",
    space_id: "space-001",
    role: "superadmin",
    status: "active",
  },
  {
    id: "mem-002",
    email: "user@example.com",
    space_id: "space-001",
    role: "user",
    status: "active",
  },
];

const MOCK_TEMPLATES = [
  {
    id: "tpl-001",
    space_id: "space-001",
    name: "Standard Intake",
    schema: {
      schema_version: "1",
      title: "Standard Intake",
      subtitle: "Mock intake form for local development",
      estimated_minutes: 10,
      save_as_you_go: true,
      sections: [
        {
          id: "section-context",
          title: "Context",
          description: "Tell us about the research topic.",
          fields: [
            {
              key: "client_name",
              type: "text",
              label: "Client or project name",
              required: true,
              placeholder: "e.g. Acme Corp — Q3 strategy",
            },
            {
              key: "main_question",
              type: "longtext",
              label: "What is the main research question?",
              required: true,
              rows: 4,
              placeholder: "Describe the core question you want answered.",
            },
          ],
        },
        {
          id: "section-background",
          title: "Background",
          fields: [
            {
              key: "background",
              type: "longtext",
              label: "Background context",
              rows: 5,
              placeholder: "Any relevant background, constraints, or prior knowledge.",
            },
            {
              key: "target_audience",
              type: "text",
              label: "Target audience",
              placeholder: "Who should this research serve?",
            },
          ],
        },
        {
          id: "section-scope",
          title: "Scope & Deliverables",
          fields: [
            {
              key: "desired_output",
              type: "longtext",
              label: "Desired output",
              rows: 3,
              placeholder: "What format should the research deliverable take?",
            },
            {
              key: "deadline",
              type: "text",
              label: "Deadline",
              placeholder: "e.g. End of Q3 2025",
            },
          ],
        },
      ],
      submit: {
        label: "Submit intake",
        confirmation: "Are you sure you want to submit this intake?",
      },
    },
  },
];

// Shared mock answers for submitted-and-beyond intakes
const FILLED_ANSWERS = (intakeId) => [
  { field_key: "client_name", value: "Strategisch Plan 2026", value_json: null },
  { field_key: "main_question", value: "Welke marktsegmenten bieden de hoogste groeipotentie voor onze kernproducten in de Benelux?", value_json: null },
  { field_key: "background", value: "We opereren al 8 jaar in de Benelux maar zien marktaandeel slinken in het MKB-segment. We willen begrijpen of dit structureel is of gedreven door specifieke productproblemen.", value_json: null },
  { field_key: "target_audience", value: "Directie en product-management team", value_json: null },
  { field_key: "desired_output", value: "Executive rapport met top-3 segmentaanbevelingen en een go/no-go matrix per segment.", value_json: null },
  { field_key: "deadline", value: "Q4 2025", value_json: null },
];

// Per-intake skill runs — only submitted+ intakes have runs
const MOCK_SKILL_RUNS = {
  "int-003": [
    {
      id: "run-003-a",
      skill: "apply-intake-skill",
      status: "succeeded",
      triggered_at: new Date(Date.now() - 3600000 * 4).toISOString(),
      completed_at: new Date(Date.now() - 3600000 * 3).toISOString(),
      applied_at: new Date(Date.now() - 3600000 * 2).toISOString(),
      error: null,
    },
  ],
  "int-004": [
    {
      id: "run-004-a",
      skill: "apply-intake-skill",
      status: "succeeded",
      triggered_at: new Date(Date.now() - 86400000 * 3).toISOString(),
      completed_at: new Date(Date.now() - 86400000 * 3 + 600000).toISOString(),
      applied_at: new Date(Date.now() - 86400000 * 3 + 700000).toISOString(),
      error: null,
    },
  ],
  "int-005": [
    {
      id: "run-005-a",
      skill: "apply-intake-skill",
      status: "succeeded",
      triggered_at: new Date(Date.now() - 86400000 * 5).toISOString(),
      completed_at: new Date(Date.now() - 86400000 * 5 + 600000).toISOString(),
      applied_at: new Date(Date.now() - 86400000 * 5 + 700000).toISOString(),
      error: null,
    },
    {
      id: "run-005-b",
      skill: "context-pack",
      status: "succeeded",
      triggered_at: new Date(Date.now() - 86400000 * 2).toISOString(),
      completed_at: new Date(Date.now() - 86400000 * 2 + 300000).toISOString(),
      applied_at: null,
      error: null,
    },
  ],
  "int-006": [
    {
      id: "run-006-a",
      skill: "apply-intake-skill",
      status: "succeeded",
      triggered_at: new Date(Date.now() - 86400000 * 7).toISOString(),
      completed_at: new Date(Date.now() - 86400000 * 7 + 600000).toISOString(),
      applied_at: new Date(Date.now() - 86400000 * 7 + 700000).toISOString(),
      error: null,
    },
  ],
  "int-007": [
    {
      id: "run-007-a",
      skill: "apply-intake-skill",
      status: "succeeded",
      triggered_at: new Date(Date.now() - 86400000 * 14).toISOString(),
      completed_at: new Date(Date.now() - 86400000 * 14 + 600000).toISOString(),
      applied_at: new Date(Date.now() - 86400000 * 14 + 700000).toISOString(),
      error: null,
    },
  ],
  "int-008": [
    {
      id: "run-008-a",
      skill: "apply-intake-skill",
      status: "succeeded",
      triggered_at: new Date(Date.now() - 86400000 * 30).toISOString(),
      completed_at: new Date(Date.now() - 86400000 * 30 + 600000).toISOString(),
      applied_at: new Date(Date.now() - 86400000 * 30 + 700000).toISOString(),
      error: null,
    },
  ],
};

// One intake per status so every workflow phase is visible in the dev UI
const MOCK_INTAKES = [
  {
    id: "int-001",
    space_id: "space-001",
    status: "draft",
    client_name: "Draft Project",
    validation_link_sent_at: null,
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
  },
  {
    id: "int-002",
    space_id: "space-001",
    status: "submitted",
    client_name: "Benelux Groeianalyse",
    validation_link_sent_at: null,
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
  },
  {
    id: "int-003",
    space_id: "space-001",
    status: "reviewed",
    client_name: "DACH Expansie Scan",
    // validation_link_sent_at null → phase = awaiting_validation_send
    validation_link_sent_at: null,
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
  },
  {
    id: "int-004",
    space_id: "space-001",
    status: "reviewed",
    client_name: "Retailstrategie NL",
    // validation_link_sent_at set → phase = awaiting_client_validation
    validation_link_sent_at: new Date(Date.now() - 86400000).toISOString(),
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
  },
  {
    id: "int-005",
    space_id: "space-001",
    status: "validated_by_client",
    client_name: "Concurrentieanalyse 2026",
    validation_link_sent_at: new Date(Date.now() - 86400000 * 4).toISOString(),
    results_link_sent_at: null,
    // context_pack_artifact_id set → phase = awaiting_research_start
    context_pack_artifact_id: "art-cp-005",
    final_report_artifact_id: null,
  },
  {
    id: "int-006",
    space_id: "space-001",
    status: "in_research",
    client_name: "Klantpanel Financiën",
    validation_link_sent_at: new Date(Date.now() - 86400000 * 8).toISOString(),
    results_link_sent_at: null,
    context_pack_artifact_id: "art-cp-006",
    final_report_artifact_id: null,
  },
  {
    id: "int-007",
    space_id: "space-001",
    status: "delivered",
    client_name: "HR Tech Benchmark",
    validation_link_sent_at: new Date(Date.now() - 86400000 * 15).toISOString(),
    // results_link_sent_at set → phase = completed
    results_link_sent_at: new Date(Date.now() - 86400000 * 2).toISOString(),
    context_pack_artifact_id: "art-cp-007",
    final_report_artifact_id: "art-rep-007",
  },
  {
    id: "int-008",
    space_id: "space-001",
    status: "archived",
    client_name: "Marktintrede Scan 2024",
    validation_link_sent_at: new Date(Date.now() - 86400000 * 45).toISOString(),
    results_link_sent_at: new Date(Date.now() - 86400000 * 30).toISOString(),
    context_pack_artifact_id: "art-cp-008",
    final_report_artifact_id: "art-rep-008",
  },
];

const MOCK_ORG = {
  id: "org-001",
  name: "Agenic",
  status: "active",
};

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

app.post("/auth/session", (req, res) => {
  res.json({ role: "superadmin", space_id: "space-001" });
});

// ---------------------------------------------------------------------------
// Me
// ---------------------------------------------------------------------------

app.get("/me", (req, res) => {
  res.json({ locale: "nl", space_default_locale: "nl" });
});

app.patch("/me/locale", (req, res) => {
  const { locale } = req.body;
  res.json({ locale: locale ?? "nl", space_default_locale: "nl" });
});

// ---------------------------------------------------------------------------
// Admin — Users
// ---------------------------------------------------------------------------

app.get("/admin/users", (req, res) => res.json(MOCK_USERS));

app.post("/admin/users", (req, res) => {
  const { email, space_id } = req.body;
  const newUser = { id: `mem-${Date.now()}`, email, space_id, role: "user", status: "active" };
  MOCK_USERS.push(newUser);
  res.status(201).json({
    uid: `uid-${Date.now()}`,
    space_id,
    action_link: "https://example.com/set-password?mock=1",
  });
});

app.post("/admin/users/:id/deactivate", (req, res) => {
  const user = MOCK_USERS.find((u) => u.id === req.params.id);
  if (!user) return res.status(404).json({ detail: "Not found" });
  user.status = "deactivated";
  res.json(user);
});

app.post("/admin/users/:id/reactivate", (req, res) => {
  const user = MOCK_USERS.find((u) => u.id === req.params.id);
  if (!user) return res.status(404).json({ detail: "Not found" });
  user.status = "active";
  res.json(user);
});

app.post("/admin/users/:id/invite-mail", (req, res) => {
  res.json({ success: true });
});

// ---------------------------------------------------------------------------
// Admin — Spaces
// ---------------------------------------------------------------------------

app.get("/admin/spaces", (req, res) => res.json(MOCK_SPACES));

app.post("/admin/spaces", (req, res) => {
  const { name, slug } = req.body;
  const s = { id: `space-${Date.now()}`, name, slug: slug ?? null, status: "active", default_locale: "nl" };
  MOCK_SPACES.push(s);
  res.status(201).json(s);
});

app.patch("/admin/spaces/:id", (req, res) => {
  const s = MOCK_SPACES.find((x) => x.id === req.params.id);
  if (!s) return res.status(404).json({ detail: "Not found" });
  Object.assign(s, req.body);
  res.json(s);
});

app.post("/admin/spaces/:id/deactivate", (req, res) => {
  const s = MOCK_SPACES.find((x) => x.id === req.params.id);
  if (!s) return res.status(404).json({ detail: "Not found" });
  s.status = "deactivated";
  res.json(s);
});

app.post("/admin/spaces/:id/reactivate", (req, res) => {
  const s = MOCK_SPACES.find((x) => x.id === req.params.id);
  if (!s) return res.status(404).json({ detail: "Not found" });
  s.status = "active";
  res.json(s);
});

// GET/POST /admin/spaces/:spaceId/templates (MUST be declared before /admin/spaces/:id)
app.get("/admin/spaces/:spaceId/templates", (req, res) => {
  res.json(MOCK_TEMPLATES.filter((t) => t.space_id === req.params.spaceId));
});

app.post("/admin/spaces/:spaceId/templates", (req, res) => {
  const { name, schema } = req.body;
  const t = { id: `tpl-${Date.now()}`, space_id: req.params.spaceId, name, schema: schema ?? null };
  MOCK_TEMPLATES.push(t);
  res.status(201).json(t);
});

app.patch("/admin/spaces/:spaceId/templates/:templateId", (req, res) => {
  const t = MOCK_TEMPLATES.find((x) => x.id === req.params.templateId);
  if (!t) return res.status(404).json({ detail: "Not found" });
  Object.assign(t, req.body);
  res.json(t);
});

app.delete("/admin/spaces/:spaceId/templates/:templateId", (req, res) => {
  const idx = MOCK_TEMPLATES.findIndex((x) => x.id === req.params.templateId);
  if (idx === -1) return res.status(404).json({ detail: "Not found" });
  MOCK_TEMPLATES.splice(idx, 1);
  res.status(204).send();
});

app.get("/admin/spaces/:id/invitations", (req, res) => res.json([]));

// ---------------------------------------------------------------------------
// Admin — Organizations
// ---------------------------------------------------------------------------

app.get("/admin/organizations", (req, res) => res.json([MOCK_ORG]));

// ---------------------------------------------------------------------------
// Intakes — static sub-routes MUST come before dynamic /intakes/:id
// ---------------------------------------------------------------------------

app.get("/intakes/templates", (req, res) => res.json(MOCK_TEMPLATES));

app.get("/intakes", (req, res) => res.json(MOCK_INTAKES));

app.post("/intakes", (req, res) => {
  const { client_name } = req.body;
  const intake = {
    id: `int-${Date.now()}`,
    space_id: "space-001",
    status: "draft",
    client_name: client_name ?? null,
    validation_link_sent_at: null,
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
  };
  MOCK_INTAKES.push(intake);
  res.status(201).json(intake);
});

app.get("/intakes/:id", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (!intake) return res.status(404).json({ detail: "Not found" });
  res.json(intake);
});

app.patch("/intakes/:id", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (!intake) return res.status(404).json({ detail: "Not found" });
  Object.assign(intake, req.body);
  res.json(intake);
});

// Status transitions
const STATUS_TRANSITIONS = {
  submit: "submitted",
  review: "reviewed",
  deliver: "delivered",
  validate: "validated_by_client",
  reject: "rejected",
  "start-decompose": "decomposed",
  "start-context-pack": "in_research",
  archive: "archived",
};

Object.entries(STATUS_TRANSITIONS).forEach(([verb, newStatus]) => {
  app.post(`/intakes/:id/${verb}`, (req, res) => {
    const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
    if (!intake) return res.status(404).json({ detail: "Not found" });
    intake.status = newStatus;
    res.json(intake);
  });
});

app.post("/intakes/:id/report/replace", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (!intake) return res.status(404).json({ detail: "Not found" });
  intake.final_report_artifact_id = `art-${Date.now()}`;
  res.json(intake);
});

app.get("/intakes/:id/report", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  res.json({
    intake_id: req.params.id,
    artifact_id: intake?.final_report_artifact_id ?? null,
    download_url: intake?.final_report_artifact_id ? "https://example.com/mock-report.pdf" : null,
    filename: intake?.final_report_artifact_id ? "nestor-rapport.pdf" : null,
  });
});

app.get("/intakes/:id/members", (req, res) => {
  res.json([
    { id: "mem-001", email: "admin@example.com", role: "superadmin", status: "active" },
    { id: "mem-002", email: "user@example.com", role: "user", status: "active" },
  ]);
});

app.post("/intakes/:id/mail/:type", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  const type = req.params.type;
  const now = new Date().toISOString();
  if (intake) {
    if (type === "validation" || type === "reminder") intake.validation_link_sent_at = now;
    if (type === "results") intake.results_link_sent_at = now;
  }
  console.log(`[mock] mail type=${type} for intake=${req.params.id}`);
  res.json({ success: true });
});

// ---------------------------------------------------------------------------
// Intake — Answers
// ---------------------------------------------------------------------------

// Return filled answers for all non-draft intakes
app.get("/intakes/:id/answers", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (!intake || intake.status === "draft") return res.json([]);
  res.json(FILLED_ANSWERS(req.params.id));
});

app.patch("/intakes/:id/answers", (req, res) => res.json({ success: true }));

// ---------------------------------------------------------------------------
// Intake — Skills
// ---------------------------------------------------------------------------

const skillDispatchStub = () => ({
  skill_run_id: `run-${Date.now()}`,
  status: "queued",
  created_at: new Date().toISOString(),
});

app.post("/intakes/:id/skills/apply", (req, res) => res.status(202).json(skillDispatchStub()));
app.post("/intakes/:id/skills/context-pack", (req, res) => res.status(202).json(skillDispatchStub()));
app.post("/intakes/:id/skills/structure-answers", (req, res) => res.status(202).json(skillDispatchStub()));
app.post("/intakes/:id/skills/extract-insights", (req, res) => res.status(202).json(skillDispatchStub()));
app.post("/intakes/:id/embeddings", (req, res) => res.status(202).json(skillDispatchStub()));
app.post("/intakes/:id/sources/:sourceId/transcribe", (req, res) => res.status(202).json(skillDispatchStub()));

// ---------------------------------------------------------------------------
// Intake — Skill runs (per-intake, keyed by intake id)
// ---------------------------------------------------------------------------

// Must return { latest, runs } — the API contract (SkillRunsView) expects a `latest`
// field; returning only `runs` makes res.data.latest undefined and breaks phase derivation.
app.get("/intakes/:id/skill-runs", (req, res) => {
  const runs = MOCK_SKILL_RUNS[req.params.id] ?? [];
  const latest = runs.length > 0 ? runs[runs.length - 1] : null;
  res.json({ latest, runs, total: runs.length });
});

// SSE stream for skill-run progress.
// Return 404 — the stream client handles 404/401 as "no active run" (closed=true →
// onFallback → single poll, then stops). Any other non-OK status triggers the backoff
// retry loop, which is what was causing "Maximum update depth exceeded".
app.get("/intakes/:id/skill-runs/stream", (req, res) => {
  res.status(404).json({ detail: "No active skill run to stream" });
});

// GET a specific run by runId — must be declared AFTER /stream to avoid matching "stream" as a runId
app.get("/intakes/:id/skill-runs/:runId", (req, res) => {
  const runs = MOCK_SKILL_RUNS[req.params.id] ?? [];
  const run = runs.find((r) => r.id === req.params.runId);
  if (!run) return res.status(404).json({ detail: "No skill run found" });
  res.json({ ...run, output_parsed: null });
});

// ---------------------------------------------------------------------------
// Intake — Research
// ---------------------------------------------------------------------------

app.post("/intakes/:id/research", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (intake) intake.status = "in_research";
  res.status(202).json({ research_run_id: `rrun-${Date.now()}` });
});

app.get("/intakes/:id/research", (req, res) => {
  res.json({ runs: [], total: 0 });
});

app.get("/intakes/:id/research/:runId/bundle-url", (req, res) => {
  res.json({ url: "https://example.com/mock-bundle", expires_in: 3600 });
});

app.post("/intakes/:id/research/:runId/verify-chain", (req, res) => {
  res.json({ chain_status: "verified" });
});

// SSE streaming — emit a single done event so clients don't hang
app.get("/intakes/:id/research/stream", (req, res) => {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  res.write('data: {"type":"done"}\n\n');
  res.end();
});

// ---------------------------------------------------------------------------
// Intake — Context pack
// ---------------------------------------------------------------------------

app.get("/intakes/:id/context-pack", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  const hasCP = !!intake?.context_pack_artifact_id;
  res.json({
    intake_id: req.params.id,
    artifact_id: intake?.context_pack_artifact_id ?? null,
    content: hasCP
      ? "# Context Pack\n\nDit is een mock context pack met de kern van de intake-antwoorden."
      : null,
    generated_at: hasCP ? new Date(Date.now() - 86400000).toISOString() : null,
  });
});

// ---------------------------------------------------------------------------
// Intake — Sources
// ---------------------------------------------------------------------------

app.get("/intakes/:id/sources", (req, res) => {
  res.json({ sources: [] });
});

// ---------------------------------------------------------------------------
// Intake — Storage
// ---------------------------------------------------------------------------

app.post("/intakes/:id/storage/uploads", (req, res) => {
  res.status(201).json({
    artifact_id: `art-${Date.now()}`,
    filename: req.body?.filename ?? "mock-file.pdf",
    upload_url: "https://example.com/mock-upload",
    content_type: req.body?.content_type ?? "application/pdf",
  });
});

app.delete("/intakes/:id/storage/objects", (req, res) => {
  res.json({ removed: 0 });
});

app.get("/intakes/:id/storage/signed-url", (req, res) => {
  res.json({ url: "https://example.com/mock-signed-url", expires_in: 3600 });
});

// ---------------------------------------------------------------------------
// Intake — Search
// ---------------------------------------------------------------------------

app.get("/intakes/:id/search", (req, res) => res.json({ results: [] }));

// ---------------------------------------------------------------------------
// Global / admin search
// ---------------------------------------------------------------------------

app.get("/search", (req, res) => res.json([]));
app.post("/search/refresh", (req, res) => res.status(204).send());
app.get("/admin/search", (req, res) => res.json({ results: [] }));

// ---------------------------------------------------------------------------
// Catch-all — fail loudly for unimplemented routes
// ---------------------------------------------------------------------------
app.use((req, res) => {
  console.warn(`[mock] NOT IMPLEMENTED: ${req.method} ${req.path}`);
  res.status(501).json({
    detail: `Mock backend: ${req.method} ${req.path} is not implemented.`,
  });
});

app.listen(PORT, () => {
  console.log(`Mock backend running on http://localhost:${PORT}`);
  console.log(`Intakes available: ${MOCK_INTAKES.map(i => `${i.id}(${i.status})`).join(', ')}`);
});
