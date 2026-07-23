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
    // Schema matches IntakeSchema type (intake-types.ts).
    // Labels are plain strings (localizeSchema passthrough for non-LocalizedString values).
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

const MOCK_INTAKES = [
  {
    id: "int-001",
    space_id: "space-001",
    status: "draft",
    client_name: "Sample Client",
    validation_link_sent_at: null,
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
  },
  {
    id: "int-002",
    space_id: "space-001",
    status: "submitted",
    client_name: "Beta Tester",
    validation_link_sent_at: new Date(Date.now() - 86400000).toISOString(),
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
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

// GET /admin/spaces/:id/invitations
app.get("/admin/spaces/:id/invitations", (req, res) => res.json([]));

// ---------------------------------------------------------------------------
// Admin — Organizations
// ---------------------------------------------------------------------------

app.get("/admin/organizations", (req, res) => res.json([MOCK_ORG]));

// ---------------------------------------------------------------------------
// Intakes — static sub-routes MUST come before dynamic /intakes/:id
// ---------------------------------------------------------------------------

// GET /intakes/templates — list templates visible to the current identity
app.get("/intakes/templates", (req, res) => res.json(MOCK_TEMPLATES));

// GET /intakes
app.get("/intakes", (req, res) => res.json(MOCK_INTAKES));

// POST /intakes
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

// GET /intakes/:id
app.get("/intakes/:id", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (!intake) return res.status(404).json({ detail: "Not found" });
  res.json(intake);
});

// PATCH /intakes/:id
app.patch("/intakes/:id", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (!intake) return res.status(404).json({ detail: "Not found" });
  Object.assign(intake, req.body);
  res.json(intake);
});

// Intake status transitions — all return the updated Intake object
// Status names mirror frontend contract exactly (intake-phase.ts / _status.tsx):
// draft → submitted → reviewed → validated_by_client → decomposed → in_research → delivered
const STATUS_TRANSITIONS = {
  submit: "submitted",          // draft→submitted, or reviewed→validated_by_client (frontend re-uses this verb)
  review: "reviewed",           // submitted→reviewed  (frontend expects "reviewed", not "in_review")
  deliver: "delivered",         // in_research→delivered
  validate: "validated_by_client", // alias: reviewed→validated_by_client
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

// POST /intakes/:id/report/replace — upload / replace final report
app.post("/intakes/:id/report/replace", (req, res) => {
  const intake = MOCK_INTAKES.find((i) => i.id === req.params.id);
  if (!intake) return res.status(404).json({ detail: "Not found" });
  intake.final_report_artifact_id = `art-${Date.now()}`;
  res.json(intake);
});

// GET /intakes/:id/report
app.get("/intakes/:id/report", (req, res) => {
  res.json({
    intake_id: req.params.id,
    artifact_id: null,
    download_url: null,
    filename: null,
  });
});

// GET /intakes/:id/members — space members for this intake
app.get("/intakes/:id/members", (req, res) => {
  res.json([
    { id: "mem-001", email: "admin@example.com", role: "superadmin", status: "active" },
    { id: "mem-002", email: "user@example.com", role: "user", status: "active" },
  ]);
});

// POST /intakes/:id/mail/:type — send notification mail
app.post("/intakes/:id/mail/:type", (req, res) => {
  console.log(`[mock] mail type=${req.params.type} for intake=${req.params.id}`);
  res.json({ success: true });
});

// ---------------------------------------------------------------------------
// Intake — Answers
// ---------------------------------------------------------------------------

app.get("/intakes/:id/answers", (req, res) => res.json([]));

// PATCH batch-upsert (matches frontend saveAnswers — method: "PATCH")
app.patch("/intakes/:id/answers", (req, res) => res.json({ success: true }));

// ---------------------------------------------------------------------------
// Intake — Skills (all return a SkillDispatch stub)
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
// Intake — Skill runs
// ---------------------------------------------------------------------------

app.get("/intakes/:id/skill-runs", (req, res) => {
  res.json({ runs: [], total: 0 });
});

app.get("/intakes/:id/skill-runs/:runId", (req, res) => {
  res.status(404).json({ detail: "No skill run found" });
});

// ---------------------------------------------------------------------------
// Intake — Research
// ---------------------------------------------------------------------------

app.post("/intakes/:id/research", (req, res) => {
  res.status(202).json({ research_run_id: `rrun-${Date.now()}` });
});

app.get("/intakes/:id/research/:runId/bundle-url", (req, res) => {
  res.json({ url: "https://example.com/mock-bundle", expires_in: 3600 });
});

app.post("/intakes/:id/research/:runId/verify-chain", (req, res) => {
  res.json({ chain_status: "verified" });
});

// SSE streaming — return empty stream (not implemented in mock)
app.get("/intakes/:id/research/stream", (req, res) => {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  res.write("data: {\"type\":\"done\"}\n\n");
  res.end();
});

// ---------------------------------------------------------------------------
// Intake — Context pack
// ---------------------------------------------------------------------------

app.get("/intakes/:id/context-pack", (req, res) => {
  res.json({
    intake_id: req.params.id,
    artifact_id: null,
    content: null,
    generated_at: null,
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
// Global search
// ---------------------------------------------------------------------------

app.get("/search", (req, res) => res.json([]));
app.post("/search/refresh", (req, res) => res.status(204).send());

// ---------------------------------------------------------------------------
// Admin search
// ---------------------------------------------------------------------------

app.get("/admin/search", (req, res) => res.json({ results: [] }));

// ---------------------------------------------------------------------------
// Catch-all — fail loudly for unimplemented routes (helps detect contract gaps)
// ---------------------------------------------------------------------------
app.use((req, res) => {
  console.warn(`[mock] NOT IMPLEMENTED: ${req.method} ${req.path}`);
  res.status(501).json({
    detail: `Mock backend: ${req.method} ${req.path} is not implemented.`,
  });
});

app.listen(PORT, () => {
  console.log(`Mock backend running on http://localhost:${PORT}`);
});
