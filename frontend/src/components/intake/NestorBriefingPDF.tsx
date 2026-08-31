import { Document, Page, Text, View, StyleSheet, pdf } from "@react-pdf/renderer";
import type { IntakeField, IntakeSchema } from "@/lib/intake-types";
// Pitfall 3 says the react-i18next HOOK has no context here — that is about React
// context, not about the i18next instance. The SINGLETON is a plain module import and
// works fine, and it is what FieldDisplay already uses for the same reason. This is not
// a new language source: it is THE language source, read directly.
import i18n from "@/lib/i18n";
import { pick } from "@/lib/i18n/localizeSchema";
import "./pdfFonts";

const SANS = "Helvetica";
const SERIF = "Times-Roman";

const styles = StyleSheet.create({
  page: {
    backgroundColor: "#ffffff",
    paddingTop: 56,
    paddingBottom: 64,
    paddingHorizontal: 56,
    fontSize: 10,
    color: "#1A1A1A",
    fontFamily: SANS,
  },
  cover: {
    flex: 1,
    justifyContent: "center",
  },
  topLabel: {
    fontSize: 9,
    letterSpacing: 2,
    color: "#1A1A1A",
    marginBottom: 24,
    fontFamily: SANS,
  },
  coverClient: {
    fontSize: 42,
    fontFamily: SERIF,
    color: "#1A1A1A",
    marginBottom: 8,
  },
  coverTitle: {
    fontSize: 18,
    fontFamily: SERIF,
    color: "#1A1A1A",
    marginBottom: 24,
  },
  coverMeta: {
    fontSize: 10,
    color: "#1A1A1A",
    marginBottom: 4,
  },
  sectionHeading: {
    fontSize: 20,
    fontFamily: SERIF,
    color: "#1A1A1A",
    marginTop: 8,
    marginBottom: 4,
  },
  hairline: {
    borderBottomWidth: 1,
    borderBottomColor: "#1A1A1A",
    marginBottom: 14,
  },
  label: {
    fontSize: 8,
    letterSpacing: 1.5,
    color: "#666666",
    marginBottom: 4,
    marginTop: 10,
  },
  body: {
    fontSize: 10,
    lineHeight: 1.5,
    color: "#1A1A1A",
    marginBottom: 6,
  },
  qBlock: {
    marginBottom: 12,
  },
  qNum: {
    fontSize: 8,
    letterSpacing: 1.5,
    color: "#666666",
    marginBottom: 2,
  },
  qText: {
    fontSize: 11,
    lineHeight: 1.4,
    color: "#1A1A1A",
    marginBottom: 2,
  },
  qMeta: {
    fontSize: 8,
    color: "#666666",
    letterSpacing: 1,
  },
  rationale: {
    fontSize: 9,
    color: "#444444",
    marginTop: 2,
    fontStyle: "italic",
  },
  footer: {
    position: "absolute",
    bottom: 24,
    left: 56,
    right: 56,
    flexDirection: "row",
    justifyContent: "space-between",
    fontSize: 8,
    color: "#888888",
    letterSpacing: 1.2,
  },
  tableRow: {
    flexDirection: "row",
    borderBottomWidth: 0.5,
    borderBottomColor: "#cccccc",
    paddingVertical: 4,
  },
  tableCell: { flex: 1, fontSize: 9, color: "#1A1A1A", paddingRight: 6 },
});

// Pitfall 3: this component renders via pdf(<.../>).toBlob() OUTSIDE the I18nextProvider,
// so the react-i18next translation hook has no context here. All display strings arrive
// as pre-resolved props built by the CALLING component (which IS inside the provider).
// See generateBriefingBlob.
export type NestorBriefingPDFLabels = {
  footer: string;
  validatedOn: string;
  nestorProduct: string;
  decisionGoal: string;
  researchQuestions: string;
  extraQuestions: string;
  clientContext: string;
  company: string;
  audience: string;
  competitors: string;
  stakeholders: string;
  scopeConstraints: string;
  deadline: string;
  geoScope: string;
  timeHorizon: string;
  outOfScope: string;
  outputSize: string;
  outputForm: string;
  attachments: string;
  noFiles: string;
  fileFallback: string;
  note: string;
  dash: string;
};

function Footer({ footer }: { footer: string }) {
  return (
    <View style={styles.footer} fixed>
      <Text>{footer}</Text>
      <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
    </View>
  );
}

function asString(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(asString).filter(Boolean).join(", ");
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("choice" in o) return String(o.choice ?? "");
    if ("text" in o) return asString(o.text);
    // 260831-lm4: a localized {nl, fr, en} — e.g. `decision_or_goal` after the
    // operator accepted the skill's suggestion. Without this branch it would fall to
    // the JSON.stringify below and the client would receive a PDF with a raw JSON
    // blob where the decision should be.
    const localized = pick(o, i18n.language);
    if (localized !== undefined) return localized;
    return JSON.stringify(v);
  }
  return String(v);
}

/** `text` is AI-authored and may be localized; `type`/`domain`/`kind` are codes. */
type Question = { text?: unknown; type?: string; domain?: string; kind?: string };

/** The one place this file turns a possibly-localized question into display text. */
function questionText(q: { text?: unknown }): string {
  return pick(q.text, i18n.language) ?? "";
}

type Props = {
  clientName: string;
  intakeTitle: string;
  answers: Record<string, unknown>;
  schema?: IntakeSchema;
  /** Pre-resolved display strings from the calling component (Pitfall 3). */
  labels: NestorBriefingPDFLabels;
};

export function NestorBriefingPDF({
  clientName,
  intakeTitle,
  answers,
  labels,
}: Props) {
  const decision = asString(answers.decision_or_goal);
  const refined = (answers.research_questions_refined as Question[] | undefined) ?? [];
  const original = (answers.research_questions as Question[] | undefined) ?? [];
  const questions: Question[] = refined.length > 0 ? refined : original;

  const extra = ((answers.extra_questions_proposed as Array<{
    text?: unknown;
    rationale?: unknown;
    approved?: boolean;
  }>) ?? []).filter((q) => q.approved === true);

  const company = asString(answers.company_intro);
  const audience = asString(answers.audience_description);
  const competitors = answers.competitors_list;
  const stakeholders = answers.stakeholders_list;
  const deadline = asString(answers.deadline);
  const geo = asString(answers.geo_scope);
  const horizon = asString(answers.time_horizon);
  const oos = asString(answers.out_of_scope);
  const outSize = asString(answers.output_size);
  const outForm = asString(answers.output_form);
  // FieldRenderer.uploadOne writes { path, filename, size, uploaded_at } — `filename`
  // is the human name; NEVER print the raw GCS object path (leaks internal key
  // structure into a client-adjacent document, WR-08). `name` kept for legacy values.
  const materials = (answers.materials_files as Array<{
    filename?: string;
    name?: string;
    size?: number;
    path?: string;
  }>) ?? [];
  const materialsNote = asString(answers.materials_note);

  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <View style={styles.cover}>
          <Text style={styles.topLabel}>AGENIC × NESTOR</Text>
          <Text style={styles.coverClient}>{clientName.toLowerCase()}</Text>
          <Text style={styles.coverTitle}>{intakeTitle}</Text>
          <Text style={styles.coverMeta}>{labels.validatedOn}</Text>
          <Text style={styles.coverMeta}>{labels.nestorProduct}</Text>
        </View>
        <Footer footer={labels.footer} />
      </Page>

      <Page size="A4" style={styles.page}>
        <Text style={styles.sectionHeading}>{labels.decisionGoal}</Text>
        <View style={styles.hairline} />
        <Text style={styles.body}>{decision || labels.dash}</Text>

        <Text style={styles.sectionHeading}>{labels.researchQuestions}</Text>
        <View style={styles.hairline} />
        {questions.length === 0 ? (
          <Text style={styles.body}>{labels.dash}</Text>
        ) : (
          questions.map((q, i) => (
            <View key={i} style={styles.qBlock} wrap={false}>
              <Text style={styles.qNum}>V{i + 1}</Text>
              <Text style={styles.qText}>{questionText(q)}</Text>
              {(q.type || q.domain || q.kind) && (
                <Text style={styles.qMeta}>
                  {[q.type || q.kind, q.domain].filter(Boolean).join(" · ").toUpperCase()}
                </Text>
              )}
            </View>
          ))
        )}

        {extra.length > 0 && (
          <>
            <Text style={styles.sectionHeading}>{labels.extraQuestions}</Text>
            <View style={styles.hairline} />
            {extra.map((q, i) => {
              const rationale = pick(q.rationale, i18n.language);
              return (
                <View key={i} style={styles.qBlock} wrap={false}>
                  <Text style={styles.qNum}>E{i + 1}</Text>
                  <Text style={styles.qText}>{questionText(q)}</Text>
                  {rationale && <Text style={styles.rationale}>{rationale}</Text>}
                </View>
              );
            })}
          </>
        )}
        <Footer footer={labels.footer} />
      </Page>

      <Page size="A4" style={styles.page}>
        <Text style={styles.sectionHeading}>{labels.clientContext}</Text>
        <View style={styles.hairline} />

        <Text style={styles.label}>{labels.company}</Text>
        <Text style={styles.body}>{company || labels.dash}</Text>

        <Text style={styles.label}>{labels.audience}</Text>
        <Text style={styles.body}>{audience || labels.dash}</Text>

        <Text style={styles.label}>{labels.competitors}</Text>
        <Text style={styles.body}>{asString(competitors) || labels.dash}</Text>

        <Text style={styles.label}>{labels.stakeholders}</Text>
        {Array.isArray(stakeholders) && stakeholders.length > 0 ? (
          stakeholders.map((s, i) => {
            const o = (s ?? {}) as Record<string, unknown>;
            return (
              <View key={i} style={styles.tableRow}>
                <Text style={styles.tableCell}>{asString(o.name) || labels.dash}</Text>
                <Text style={styles.tableCell}>{asString(o.role) || ""}</Text>
                <Text style={styles.tableCell}>{asString(o.email) || ""}</Text>
              </View>
            );
          })
        ) : (
          <Text style={styles.body}>{labels.dash}</Text>
        )}

        <Text style={styles.sectionHeading}>{labels.scopeConstraints}</Text>
        <View style={styles.hairline} />
        <Text style={styles.label}>{labels.deadline}</Text>
        <Text style={styles.body}>{deadline || labels.dash}</Text>
        <Text style={styles.label}>{labels.geoScope}</Text>
        <Text style={styles.body}>{geo || labels.dash}</Text>
        <Text style={styles.label}>{labels.timeHorizon}</Text>
        <Text style={styles.body}>{horizon || labels.dash}</Text>
        <Text style={styles.label}>{labels.outOfScope}</Text>
        <Text style={styles.body}>{oos || labels.dash}</Text>
        <Text style={styles.label}>{labels.outputSize}</Text>
        <Text style={styles.body}>{outSize || labels.dash}</Text>
        <Text style={styles.label}>{labels.outputForm}</Text>
        <Text style={styles.body}>{outForm || labels.dash}</Text>
        <Footer footer={labels.footer} />
      </Page>

      <Page size="A4" style={styles.page}>
        <Text style={styles.sectionHeading}>{labels.attachments}</Text>
        <View style={styles.hairline} />
        {materials.length === 0 ? (
          <Text style={styles.body}>{labels.noFiles}</Text>
        ) : (
          materials.map((m, i) => (
            <View key={i} style={styles.tableRow}>
              <Text style={styles.tableCell}>{m.filename || m.name || labels.fileFallback}</Text>
              <Text style={styles.tableCell}>
                {m.size ? `${(m.size / 1024).toFixed(0)} KB` : ""}
              </Text>
            </View>
          ))
        )}
        {materialsNote && (
          <>
            <Text style={styles.label}>{labels.note}</Text>
            <Text style={styles.body}>{materialsNote}</Text>
          </>
        )}
        <Footer footer={labels.footer} />
      </Page>
    </Document>
  );
}

export async function generateBriefingBlob(props: Props): Promise<Blob> {
  return await pdf(<NestorBriefingPDF {...props} />).toBlob();
}

// Pre-resolved markdown labels (Pitfall 3 — this pure builder has no provider access;
// the caller resolves the two localized headers via t() and passes them in).
export type ResearchMarkdownLabels = {
  header: string;
  extraSection: string;
};

export function buildResearchMarkdown(
  clientName: string,
  intakeTitle: string,
  answers: Record<string, unknown>,
  labels: ResearchMarkdownLabels,
): string {
  const refined = (answers.research_questions_refined as Question[] | undefined) ?? [];
  const original = (answers.research_questions as Question[] | undefined) ?? [];
  const questions: Question[] = refined.length > 0 ? refined : original;
  const extra = ((answers.extra_questions_proposed as Array<{
    text?: unknown;
    rationale?: unknown;
    approved?: boolean;
  }>) ?? []).filter((q) => q.approved === true);

  void clientName;
  void intakeTitle;
  const lines: string[] = [];
  lines.push(labels.header, "");
  questions.forEach((q, i) => {
    lines.push(`## V${i + 1}. ${questionText(q)}`);
    const meta = [q.type || q.kind, q.domain].filter(Boolean).join(" · ");
    if (meta) lines.push(`- Type: ${meta}`);
    lines.push("");
  });
  if (extra.length > 0) {
    lines.push(labels.extraSection, "");
    extra.forEach((q, i) => {
      lines.push(`### E${i + 1}. ${questionText(q)}`);
      const rationale = pick(q.rationale, i18n.language);
      if (rationale) lines.push(`- ${rationale}`);
      lines.push("");
    });
  }
  return lines.join("\n");
}

export type { IntakeField };
