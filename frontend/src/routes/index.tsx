import { createFileRoute, redirect } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase, type Product } from "@/lib/supabase";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/admin" });
  },
  component: Index,
});

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
 const [products, setProducts] = useState<Product[] | null>(null);
 const [error, setError] = useState<string | null>(null);

 useEffect(() => {
 if (!supabase) {
 setError(
 "Supabase is not configured yet. Add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY."
 );
 return;
 }
 const client = supabase;
 async function fetchProducts() {
 const { data, error } = await client
 .schema("nestor")
 .from("products")
 .select("*");

 console.log("SUPABASE_TEST:", { data, error });

 if (error) setError(error.message);
 else setProducts((data ?? []) as Product[]);
 }

 fetchProducts();
 }, []);

 const order = ["pulse", "echo", "edge", "flux", "sales"];
 const sorted = (products ?? []).slice().sort((a, b) => {
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

 {error && (
 <div className="border border-ink/10 bg-paper2 p-6 text-sm text-ink/60">
 {error}
 </div>
 )}

 {!error && products === null && (
 <div className="text-sm text-ink/40">Loading…</div>
 )}

 {products && (
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
 )}
 </div>
 </main>
 );
}
