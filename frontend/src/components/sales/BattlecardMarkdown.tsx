import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";

export type MarkerType = "v" | "!" | "?" | "x";

const MARKER_CONFIG: Record<MarkerType, { bg: string; sym: string }> = {
  v: { bg: "bg-fluoGreen", sym: "✓" },
  "!": { bg: "bg-fluoPink", sym: "!" },
  "?": { bg: "bg-fluoYellow", sym: "?" },
  x: { bg: "bg-fluoRed", sym: "×" },
};

export function MarkerBadge({ type }: { type: MarkerType }) {
  const c = MARKER_CONFIG[type] || MARKER_CONFIG.v;
  return (
    <span
      className={`inline-flex items-center justify-center w-3.5 h-3.5 ${c.bg} text-black font-bold text-[10px] leading-none align-text-bottom mx-0.5`}
    >
      {c.sym}
    </span>
  );
}

export function ConfidenceBadge({ level }: { level: "H" | "M" }) {
  const isHigh = level === "H";
  return (
    <span
      className={`inline-flex items-center justify-center ml-1 px-1 text-[9px] font-mono font-bold border align-baseline ${
        isHigh
          ? "border-ink/40 text-ink/70"
          : "border-ink/25 text-ink/50"
      }`}
      title={
        isHigh
          ? "High confidence — verifieerbaar"
          : "Medium confidence — inference"
      }
    >
      {level}
    </span>
  );
}

function transformContent(content: string): string {
  return content
    // Status markers
    .replace(/\[v\]\s*/g, '<marker data-type="v"></marker> ')
    .replace(/\[!\]\s*/g, '<marker data-type="!"></marker> ')
    .replace(/\[\?\]\s*/g, '<marker data-type="?"></marker> ')
    .replace(/\[x\]\s*/g, '<marker data-type="x"></marker> ')
    // Confidence pills — alleen [H]/[M] niet binnen een woord
    .replace(/(?<![A-Za-z0-9])\[H\](?![A-Za-z0-9])/g, '<conf data-level="H"></conf>')
    .replace(/(?<![A-Za-z0-9])\[M\](?![A-Za-z0-9])/g, '<conf data-level="M"></conf>')
    // Legacy emoji's (backwards-compat)
    .replace(/✅\s*/g, '<marker data-type="v"></marker> ')
    .replace(/❓\s*/g, '<marker data-type="?"></marker> ')
    .replace(/🚩\s*/g, '<marker data-type="x"></marker> ')
    .replace(/^►\s+/gm, '<marker data-type="!"></marker> ');
}

export function BattlecardMarkdown({
  children,
  content,
}: {
  children?: string;
  content?: string;
}) {
  const src = content ?? children ?? "";
  return (
    <div className="text-sm leading-relaxed text-ink">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          marker: ({ "data-type": dataType }: any) => (
            <MarkerBadge type={(dataType as MarkerType) || "v"} />
          ),
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ...({ conf: ({ "data-level": level }: any) => (
            <ConfidenceBadge level={(level as "H" | "M") || "M"} />
          ) } as any),
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-ink">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => (
            <ul className="space-y-2 my-2 list-none pl-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 space-y-2 my-2">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="text-sm leading-relaxed pl-5 -indent-5">{children}</li>
          ),
          h1: ({ children }) => (
            <h1 className="font-serif text-xl mt-4 mb-2">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="font-serif text-lg mt-3 mb-2">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="font-medium text-base mt-3 mb-1">{children}</h3>
          ),
          code: ({ children }) => (
            <code className="bg-ink/10 px-1 py-0.5 font-mono text-xs">
              {children}
            </code>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-ink"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="my-3 border-ink/15" />,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-ink/30 pl-3 italic text-ink/80 my-2">
              {children}
            </blockquote>
          ),
        }}
      >
        {transformContent(src)}
      </ReactMarkdown>
    </div>
  );
}
