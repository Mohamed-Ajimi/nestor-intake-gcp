import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/admin" });
  },
  component: Index,
});

// The root marketing cards are static product metadata — there is no tenant data here,
// so they live as a local constant instead of an inline Supabase read. (`beforeLoad`
// redirects to /admin, so this component is effectively never rendered, but it stays a
// valid, seam-free fallback.)
type Product = {
 id: string;
 name: string;
 tagline: string | null;
 description: string | null;
};

const PRODUCTS: Product[] = [
 {
   id: "pulse",
   name: "pulse",
   tagline: "verified intelligence that compounds",
   description:
     "Structured intake, AI-assisted research questions, and a validated context pack — the flow that runs before deep research.",
 },
];

function ProductCard({
 product,
 hero = false,
}: {
 product: Product;
 hero?: boolean;
}) {
 return (
    <article
      className={
        "border border-ink bg-paper p-8 transition-colors hover:border-2 " +
        (hero ? "md:p-14" : "")
      }
    >
      <h2
        className={
          "font-serif font-normal lowercase tracking-tight text-ink " +
          (hero ? "text-5xl md:text-6xl" : "text-2xl md:text-3xl")
        }
      >
        {product.name}
      </h2>
      {product.tagline && (
        <p
          className={
            "mt-3 text-ink/60 " + (hero ? "text-xl" : "text-base")
          }
        >
          {product.tagline}
        </p>
      )}
      {product.description && (
        <p
          className={
            "mt-6 leading-relaxed text-ink/70 " +
            (hero ? "max-w-2xl text-lg" : "text-[15px]")
          }
        >
          {product.description}
        </p>
      )}
    </article>
 );
}

function Index() {
 const order = ["pulse", "echo", "edge", "flux", "sales"];
 const sorted = PRODUCTS.slice().sort((a, b) => {
 const ai = order.indexOf((a.name || "").toLowerCase());
 const bi = order.indexOf((b.name || "").toLowerCase());
 return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
 });

 const pulse = sorted.find((p) => (p.name || "").toLowerCase() === "pulse");
 const rest = sorted.filter((p) => p !== pulse);

 return (
 <main className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-6xl px-6 py-20 md:py-28">
        <header className="mb-16 md:mb-24">
          <p className="font-mono text-xs uppercase tracking-widest text-ink/60">
            Agenic
          </p>
          <h1 className="mt-4 font-serif text-5xl font-normal lowercase tracking-tight md:text-7xl">
            nestor — verified <em className="italic">intelligence</em> that compounds
          </h1>
        </header>

 <div className="space-y-6">
 {pulse && <ProductCard product={pulse} hero />}
 {rest.length > 0 && (
 <div className="grid gap-6 md:grid-cols-2">
 {rest.map((p, i) => (
 <ProductCard key={p.id ?? p.name ?? i} product={p} />
 ))}
 </div>
 )}
 </div>
 </div>
 </main>
 );
}
