// Labels & option lists for the 4 Sales "context & nadruk" dropdowns.
// Display labels are used in the UI — DB-values are never shown raw.

export const MEETING_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "discovery", label: "Discovery — eerste verkenning" },
  { value: "demo", label: "Demo — product/dienst tonen" },
  { value: "follow_up", label: "Follow-up — opvolging" },
  { value: "executive_pitch", label: "Executive pitch — C-level" },
  { value: "renewal", label: "Renewal — vernieuwing" },
  { value: "win_back", label: "Win-back — terugwinnen" },
];

export const DEAL_STAGE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "new", label: "New — net contact gelegd" },
  { value: "qualified", label: "Qualified — interesse bevestigd" },
  { value: "proposal", label: "Proposal — voorstel uitgestuurd" },
  { value: "negotiation", label: "Negotiation — onderhandelingen" },
  { value: "decision", label: "Decision — finale beslissing" },
];

export const KLANT_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "new_client", label: "Nieuwe klant" },
  { value: "existing_client", label: "Bestaande klant" },
];

export const INDUSTRY_VERTICAL_SUGGESTIONS: string[] = [
  "Technology",
  "Financial Services",
  "Retail / E-commerce",
  "Healthcare / Pharma",
  "Manufacturing / Industry",
  "Energy / Oil & Gas",
  "Public Sector",
  "Professional Services",
  "Media / Marketing",
];

export const MEETING_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  MEETING_TYPE_OPTIONS.map((o) => [o.value, o.label]),
);
export const DEAL_STAGE_LABELS: Record<string, string> = Object.fromEntries(
  DEAL_STAGE_OPTIONS.map((o) => [o.value, o.label]),
);
export const KLANT_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  KLANT_TYPE_OPTIONS.map((o) => [o.value, o.label]),
);

export const meetingTypeLabel = (v?: string | null) =>
  v ? MEETING_TYPE_LABELS[v] || v : null;
export const dealStageLabel = (v?: string | null) =>
  v ? DEAL_STAGE_LABELS[v] || v : null;
export const klantTypeLabel = (v?: string | null) =>
  v ? KLANT_TYPE_LABELS[v] || v : null;

export type Stakeholder = {
  name: string;
  role: string;
  linkedin_url: string;
};

export const GEOGRAPHY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "BE-NL (Vlaanderen)", label: "BE-NL (Vlaanderen)" },
  { value: "BE-FR (Wallonië)", label: "BE-FR (Wallonië)" },
  { value: "BE-bilingual", label: "BE-bilingual" },
  { value: "NL", label: "NL" },
  { value: "FR", label: "FR" },
  { value: "DE", label: "DE" },
  { value: "UK", label: "UK" },
  { value: "US", label: "US" },
  { value: "Other", label: "Andere" },
];

