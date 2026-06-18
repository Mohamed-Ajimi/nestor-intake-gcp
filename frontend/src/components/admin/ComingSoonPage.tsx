import { Link } from "@tanstack/react-router";

export function ComingSoonPage({ product }: { product: string }) {
  return (
    <div className="mx-auto max-w-2xl py-24 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/60">
        Agenic › Nestor {product}
      </p>
      <h1 className="mt-4 font-serif text-4xl lowercase text-ink">
        ⌀ Binnenkort beschikbaar
      </h1>
      <p className="mt-4 text-sm text-ink/70">
        Nestor {product} is in ontwikkeling. We laten je weten zodra het klaar
        is.
      </p>
      <Link
        to="/admin"
        className="mt-8 inline-block font-mono text-xs uppercase tracking-wider text-ink underline-offset-2 hover:underline"
      >
        ← Terug naar overzicht
      </Link>
    </div>
  );
}
