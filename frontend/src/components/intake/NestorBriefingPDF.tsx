import { Document, Page, Text, View, StyleSheet, pdf } from "@react-pdf/renderer";
import type { IntakeField, IntakeSchema } from "@/lib/intake-types";
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

function Footer() {
  return (
    <View style={styles.footer} fixed>
      <Text>AGENIC × NESTOR — CONFIDENTIEEL</Text>
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
    if ("text" in o) return String(o.text ?? "");
    return JSON.stringify(v);
  }
  return String(v);
}

function fmtDate(d: string | null | undefined) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("nl-NL", { day: "numeric", month: "long", year: "numeric" });
  } catch {
    return d;
  }
}

type Question = { text: string; type?: string; domain?: string; kind?: string };

type Props = {
  clientName: string;
  intakeTitle: string;
  productName: string;
  validatedAt: string | null;
  answers: Record<string, unknown>;
  schema?: IntakeSchema;
};

export function NestorBriefingPDF({
  clientName,
  intakeTitle,
  productName,
  validatedAt,
  answers,
}: Props) {
  const decision = asString(answers.decision_or_goal);
  const refined = (answers.research_questions_refined as Question[] | undefined) ?? [];
  const original = (answers.research_questions as Question[] | undefined) ?? [];
  const questions: Question[] = refined.length > 0 ? refined : original;

  const extra = ((answers.extra_questions_proposed as Array<{
    text: string;
    rationale?: string;
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
  const materials = (answers.materials_files as Array<{
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
          <Text style={styles.coverMeta}>Gevalideerd op {fmtDate(validatedAt)}</Text>
          <Text style={styles.coverMeta}>Nestor {productName}</Text>
        </View>
        <Footer />
      </Page>

      <Page size="A4" style={styles.page}>
        <Text style={styles.sectionHeading}>beslissing & doel</Text>
        <View style={styles.hairline} />
        <Text style={styles.body}>{decision || "—"}</Text>

        <Text style={styles.sectionHeading}>onderzoeksvragen</Text>
        <View style={styles.hairline} />
        {questions.length === 0 ? (
          <Text style={styles.body}>—</Text>
        ) : (
          questions.map((q, i) => (
            <View key={i} style={styles.qBlock} wrap={false}>
              <Text style={styles.qNum}>V{i + 1}</Text>
              <Text style={styles.qText}>{q.text}</Text>
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
            <Text style={styles.sectionHeading}>extra vragen (klant-goedgekeurd)</Text>
            <View style={styles.hairline} />
            {extra.map((q, i) => (
              <View key={i} style={styles.qBlock} wrap={false}>
                <Text style={styles.qNum}>E{i + 1}</Text>
                <Text style={styles.qText}>{q.text}</Text>
                {q.rationale && <Text style={styles.rationale}>{q.rationale}</Text>}
              </View>
            ))}
          </>
        )}
        <Footer />
      </Page>

      <Page size="A4" style={styles.page}>
        <Text style={styles.sectionHeading}>klantcontext</Text>
        <View style={styles.hairline} />

        <Text style={styles.label}>BEDRIJF</Text>
        <Text style={styles.body}>{company || "—"}</Text>

        <Text style={styles.label}>DOELGROEP</Text>
        <Text style={styles.body}>{audience || "—"}</Text>

        <Text style={styles.label}>CONCURRENTEN</Text>
        <Text style={styles.body}>{asString(competitors) || "—"}</Text>

        <Text style={styles.label}>STAKEHOLDERS</Text>
        {Array.isArray(stakeholders) && stakeholders.length > 0 ? (
          stakeholders.map((s, i) => {
            const o = (s ?? {}) as Record<string, unknown>;
            return (
              <View key={i} style={styles.tableRow}>
                <Text style={styles.tableCell}>{asString(o.name) || "—"}</Text>
                <Text style={styles.tableCell}>{asString(o.role) || ""}</Text>
                <Text style={styles.tableCell}>{asString(o.email) || ""}</Text>
              </View>
            );
          })
        ) : (
          <Text style={styles.body}>—</Text>
        )}

        <Text style={styles.sectionHeading}>scope & constraints</Text>
        <View style={styles.hairline} />
        <Text style={styles.label}>DEADLINE</Text>
        <Text style={styles.body}>{deadline || "—"}</Text>
        <Text style={styles.label}>GEO SCOPE</Text>
        <Text style={styles.body}>{geo || "—"}</Text>
        <Text style={styles.label}>TIME HORIZON</Text>
        <Text style={styles.body}>{horizon || "—"}</Text>
        <Text style={styles.label}>OUT OF SCOPE</Text>
        <Text style={styles.body}>{oos || "—"}</Text>
        <Text style={styles.label}>OUTPUT SIZE</Text>
        <Text style={styles.body}>{outSize || "—"}</Text>
        <Text style={styles.label}>OUTPUT FORM</Text>
        <Text style={styles.body}>{outForm || "—"}</Text>
        <Footer />
      </Page>

      <Page size="A4" style={styles.page}>
        <Text style={styles.sectionHeading}>bijlagen — door klant geüpload</Text>
        <View style={styles.hairline} />
        {materials.length === 0 ? (
          <Text style={styles.body}>Geen bestanden geüpload.</Text>
        ) : (
          materials.map((m, i) => (
            <View key={i} style={styles.tableRow}>
              <Text style={styles.tableCell}>{m.name || m.path || "bestand"}</Text>
              <Text style={styles.tableCell}>
                {m.size ? `${(m.size / 1024).toFixed(0)} KB` : ""}
              </Text>
            </View>
          ))
        )}
        {materialsNote && (
          <>
            <Text style={styles.label}>NOTITIE</Text>
            <Text style={styles.body}>{materialsNote}</Text>
          </>
        )}
        <Footer />
      </Page>
    </Document>
  );
}

export async function generateBriefingBlob(props: Props): Promise<Blob> {
  return await pdf(<NestorBriefingPDF {...props} />).toBlob();
}

export function buildResearchMarkdown(
  clientName: string,
  intakeTitle: string,
  answers: Record<string, unknown>,
): string {
  const refined = (answers.research_questions_refined as Question[] | undefined) ?? [];
  const original = (answers.research_questions as Question[] | undefined) ?? [];
  const questions: Question[] = refined.length > 0 ? refined : original;
  const extra = ((answers.extra_questions_proposed as Array<{
    text: string;
    rationale?: string;
    approved?: boolean;
  }>) ?? []).filter((q) => q.approved === true);

  const lines: string[] = [];
  lines.push(`# Research-vragen — ${clientName} — ${intakeTitle}`, "");
  questions.forEach((q, i) => {
    lines.push(`## V${i + 1}. ${q.text}`);
    const meta = [q.type || q.kind, q.domain].filter(Boolean).join(" · ");
    if (meta) lines.push(`- Type: ${meta}`);
    lines.push("");
  });
  if (extra.length > 0) {
    lines.push("## Extra vragen (klant-goedgekeurd)", "");
    extra.forEach((q, i) => {
      lines.push(`### E${i + 1}. ${q.text}`);
      if (q.rationale) lines.push(`- ${q.rationale}`);
      lines.push("");
    });
  }
  return lines.join("\n");
}

export type { IntakeField };
