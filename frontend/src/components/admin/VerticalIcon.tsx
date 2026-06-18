type Variant = "pulse" | "sweep" | "edge" | "sales" | "echo" | "flux";

/**
 * Iconic drawings for the 5 Nestor verticals.
 * Square viewBox, thin black strokes, central black square with a soft yellow glow.
 */
export function VerticalIcon({
  variant,
  className,
  size = 72,
}: {
  variant: Variant;
  className?: string;
  size?: number;
}) {
  const glowId = `vi-glow-${variant}`;
  return (
    <svg
      viewBox="0 0 120 120"
      width={size}
      height={size}
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <defs>
        <radialGradient id={glowId} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#E6FF3A" stopOpacity="0.95" />
          <stop offset="55%" stopColor="#E6FF3A" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#E6FF3A" stopOpacity="0" />
        </radialGradient>
      </defs>
      {renderVariant(variant, glowId)}
    </svg>
  );
}

function renderVariant(v: Variant, glowId: string) {
  // Helper: glow + black square at given center.
  const core = (cx: number, cy: number, sq = 6, glowR = 14) => (
    <>
      <circle cx={cx} cy={cy} r={glowR} fill={`url(#${glowId})`} stroke="none" />
      <rect
        x={cx - sq / 2}
        y={cy - sq / 2}
        width={sq}
        height={sq}
        fill="currentColor"
        stroke="none"
      />
    </>
  );

  switch (v) {
    case "pulse":
      // Square on left, concentric arc waves radiating right.
      return (
        <>
          <path d="M40 35 A 30 30 0 0 1 40 85" />
          <path d="M52 28 A 40 40 0 0 1 52 92" />
          <path d="M64 22 A 50 50 0 0 1 64 98" />
          {core(28, 60)}
        </>
      );

    case "sweep":
    case "edge":
      // Circle with a single radial line going up-right (radar sweep).
      return (
        <>
          <circle cx="60" cy="60" r="38" />
          <line x1="60" y1="60" x2="92" y2="32" />
          {core(60, 60)}
        </>
      );


    case "sales":
      // Concentric circles with arrow going straight up from center.
      return (
        <>
          <circle cx="60" cy="60" r="14" />
          <circle cx="60" cy="60" r="26" />
          <circle cx="60" cy="60" r="38" />
          <line x1="60" y1="60" x2="60" y2="14" />
          <polyline points="55,21 60,14 65,21" />
          {core(60, 60)}
        </>
      );

    case "echo":
      // Three concentric circles centered on the square.
      return (
        <>
          <circle cx="60" cy="60" r="14" />
          <circle cx="60" cy="60" r="26" />
          <circle cx="60" cy="60" r="38" />
          {core(60, 60)}
        </>
      );

    case "flux":
      // Concentric circles with vertical + horizontal lines crossing through.
      return (
        <>
          <circle cx="60" cy="60" r="14" />
          <circle cx="60" cy="60" r="26" />
          <circle cx="60" cy="60" r="38" />
          <line x1="60" y1="14" x2="60" y2="106" />
          <line x1="14" y1="60" x2="106" y2="60" />
          {core(60, 60)}
        </>
      );
  }
}
