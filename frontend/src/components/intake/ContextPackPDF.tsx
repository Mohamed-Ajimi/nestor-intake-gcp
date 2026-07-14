import { Document, Page, Text, View, StyleSheet, pdf } from "@react-pdf/renderer";
import "./pdfFonts";

const SANS = "Helvetica";
const SERIF = "Times-Roman";

const INK = "#1A1A1A";
const MUTED = "#666666";

const styles = StyleSheet.create({
  page: {
    backgroundColor: "#ffffff",
    paddingTop: 64,
    paddingBottom: 72,
    paddingHorizontal: 64,
    fontSize: 11,
    lineHeight: 1.55,
    color: INK,
    fontFamily: SANS,
  },
  cover: { flex: 1, justifyContent: "center" },
  topLabel: {
    fontSize: 9,
    letterSpacing: 2,
    color: INK,
    marginBottom: 28,
  },
  coverClient: {
    fontSize: 44,
    fontFamily: SERIF,
    color: INK,
    marginBottom: 10,
  },
  coverTitle: {
    fontSize: 18,
    fontFamily: SERIF,
    color: INK,
    marginBottom: 28,
  },
  coverMeta: { fontSize: 10, color: INK, marginBottom: 4 },
  h1: {
    fontSize: 22,
    fontFamily: SERIF,
    color: INK,
    marginTop: 14,
    marginBottom: 6,
  },
  h2: {
    fontSize: 16,
    fontFamily: SERIF,
    color: INK,
    marginTop: 16,
    marginBottom: 4,
  },
  h3: {
    fontSize: 13,
    fontFamily: "Times-Bold",
    color: INK,
    marginTop: 12,
    marginBottom: 4,
  },
  hairline: {
    borderBottomWidth: 1,
    borderBottomColor: INK,
    marginBottom: 12,
    marginTop: 2,
  },
  para: { fontSize: 11, color: INK, marginBottom: 8, lineHeight: 1.55 },
  bulletRow: { flexDirection: "row", marginBottom: 4, paddingLeft: 8 },
  bulletDot: { width: 12, fontSize: 11, color: INK },
  bulletText: { flex: 1, fontSize: 11, color: INK, lineHeight: 1.5 },
  quote: {
    borderLeftWidth: 2,
    borderLeftColor: INK,
    paddingLeft: 10,
    marginVertical: 8,
    color: "#333333",
    fontSize: 11,
  },
  bold: { fontFamily: "Helvetica-Bold" },
  italic: { fontFamily: "Times-Italic" },
  footer: {
    position: "absolute",
    bottom: 28,
    left: 64,
    right: 64,
    flexDirection: "row",
    justifyContent: "space-between",
    fontSize: 8,
    color: "#888888",
    letterSpacing: 1.2,
  },
});

// Pitfall 3: this component renders via pdf(<.../>).toBlob() OUTSIDE the I18nextProvider,
// so the react-i18next translation hook has no context here. All display strings —
// including the two pre-formatted date lines and the locale-aware date fallback — arrive
// as pre-resolved props built by the CALLING component (which IS inside the provider).
// See generateContextPackBlob.
export type ContextPackPDFLabels = {
  footer: string;
  validated: string;
  generated: string;
};

function Footer({ footer }: { footer: string }) {
  return (
    <View style={styles.footer} fixed>
      <Text>{footer}</Text>
      <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
    </View>
  );
}

// Render inline markdown: **bold**, *italic*, `code`
type Span = { text: string; bold?: boolean; italic?: boolean };

function parseInline(input: string): Span[] {
  const spans: Span[] = [];
  const re = /\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(input))) {
    if (m.index > last) spans.push({ text: input.slice(last, m.index) });
    if (m[1] != null) spans.push({ text: m[1], bold: true });
    else if (m[2] != null) spans.push({ text: m[2], italic: true });
    else if (m[3] != null) spans.push({ text: m[3] });
    last = m.index + m[0].length;
  }
  if (last < input.length) spans.push({ text: input.slice(last) });
  return spans;
}

function InlineText({ text, italic: italicBase }: { text: string; italic?: boolean }) {
  const spans = parseInline(text);
  return (
    <>
      {spans.map((s, i) => {
        const isBold = s.bold;
        const isItalic = s.italic || italicBase;
        const style = isBold && isItalic
          ? { fontFamily: "Times-BoldItalic" }
          : isBold
            ? styles.bold
            : isItalic
              ? styles.italic
              : undefined;
        return (
          <Text key={i} style={style}>
            {s.text}
          </Text>
        );
      })}
    </>
  );
}

type Block =
  | { kind: "h1" | "h2" | "h3"; text: string }
  | { kind: "para"; text: string }
  | { kind: "bullet"; text: string }
  | { kind: "quote"; text: string }
  | { kind: "hr" };

function parseMarkdown(md: string): Block[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  const flushPara = () => {
    if (para.length) {
      blocks.push({ kind: "para", text: para.join(" ").trim() });
      para = [];
    }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushPara();
      continue;
    }
    if (/^---+$/.test(line.trim())) {
      flushPara();
      blocks.push({ kind: "hr" });
      continue;
    }
    let m;
    if ((m = line.match(/^###\s+(.*)$/))) {
      flushPara();
      blocks.push({ kind: "h3", text: m[1] });
    } else if ((m = line.match(/^##\s+(.*)$/))) {
      flushPara();
      blocks.push({ kind: "h2", text: m[1] });
    } else if ((m = line.match(/^#\s+(.*)$/))) {
      flushPara();
      blocks.push({ kind: "h1", text: m[1] });
    } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
      flushPara();
      blocks.push({ kind: "bullet", text: m[1] });
    } else if ((m = line.match(/^>\s?(.*)$/))) {
      flushPara();
      blocks.push({ kind: "quote", text: m[1] });
    } else {
      para.push(line.trim());
    }
  }
  flushPara();
  return blocks;
}

function MarkdownBlocks({ md }: { md: string }) {
  const blocks = parseMarkdown(md);
  return (
    <>
      {blocks.map((b, i) => {
        if (b.kind === "h1")
          return (
            <View key={i} wrap={false}>
              <Text style={styles.h1}>{b.text}</Text>
              <View style={styles.hairline} />
            </View>
          );
        if (b.kind === "h2")
          return (
            <View key={i} wrap={false}>
              <Text style={styles.h2}>{b.text}</Text>
              <View style={styles.hairline} />
            </View>
          );
        if (b.kind === "h3")
          return (
            <Text key={i} style={styles.h3}>
              {b.text}
            </Text>
          );
        if (b.kind === "hr")
          return <View key={i} style={styles.hairline} />;
        if (b.kind === "bullet")
          return (
            <View key={i} style={styles.bulletRow}>
              <Text style={styles.bulletDot}>•</Text>
              <Text style={styles.bulletText}>
                <InlineText text={b.text} />
              </Text>
            </View>
          );
        if (b.kind === "quote")
          return (
            <View key={i} style={styles.quote}>
              <Text>
                <InlineText text={b.text} italic />
              </Text>
            </View>
          );
        return (
          <Text key={i} style={styles.para}>
            <InlineText text={b.text} />
          </Text>
        );
      })}
    </>
  );
}

type Props = {
  clientName: string;
  intakeTitle: string;
  contextPackMarkdown: string;
  /** Pre-resolved display strings from the calling component (Pitfall 3). */
  labels: ContextPackPDFLabels;
};

export function ContextPackPDF({
  clientName,
  intakeTitle,
  contextPackMarkdown,
  labels,
}: Props) {
  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <View style={styles.cover}>
          <Text style={styles.topLabel}>AGENIC × NESTOR</Text>
          <Text style={styles.coverClient}>{clientName.toLowerCase()}</Text>
          <Text style={styles.coverTitle}>{intakeTitle}</Text>
          <Text style={styles.coverMeta}>{labels.validated}</Text>
          <Text style={styles.coverMeta}>{labels.generated}</Text>
        </View>
        <Footer footer={labels.footer} />
      </Page>

      <Page size="A4" style={styles.page}>
        <MarkdownBlocks md={contextPackMarkdown} />
        <Footer footer={labels.footer} />
      </Page>
    </Document>
  );
}

export async function generateContextPackBlob(props: Props): Promise<Blob> {
  return await pdf(<ContextPackPDF {...props} />).toBlob();
}
