import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, Copy, ExternalLink, Loader2, Plus, Search } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/admin/pulse/intakes/new")({
 validateSearch: (s: Record<string, unknown>) => ({
  client_id: typeof s.client_id === "string" ? s.client_id : undefined,
 }),
 component: NewIntakePage,
});

type Client = { id: string; name: string; country: string | null };

type Created = { id: string; token: string; title: string };

function NewIntakePage() {
 const preselectClientId = Route.useSearch({ select: (s) => s.client_id });
 // client selection
 const [clientSearch, setClientSearch] = useState("");
 const [clientResults, setClientResults] = useState<Client[]>([]);
 const [clientOpen, setClientOpen] = useState(false);
 const [selectedClient, setSelectedClient] = useState<Client | null>(null);
 const [creatingNewClient, setCreatingNewClient] = useState(false);
 const [newClient, setNewClient] = useState({ name: "", country: "BE", website: "", industry: "", primary_contact_name: "", primary_contact_role: "", primary_contact_email: "", primary_contact_phone: "" });

 useEffect(() => {
  if (!preselectClientId || !supabase || selectedClient) return;
  (async () => {
   const { data } = await supabase!
    .schema("public" as never)
    .from("clients")
    .select("id, name, country")
    .eq("id", preselectClientId)
    .single();
   if (data) setSelectedClient(data as Client);
  })();
 }, [preselectClientId, selectedClient]);

 // title
 const [title, setTitle] = useState("");

 // submit
 const [submitting, setSubmitting] = useState(false);
 const [errors, setErrors] = useState<string[]>([]);
 const [created, setCreated] = useState<Created | null>(null);

 const comboRef = useRef<HTMLDivElement>(null);

 // search clients (debounced)
 useEffect(() => {
 if (!supabase || creatingNewClient) return;
 const sb = supabase;
 const t = setTimeout(async () => {
 let q = sb.schema("public" as never).from("clients").select("id, name, country").order("name").limit(10);
 if (clientSearch.trim()) q = q.ilike("name", `%${clientSearch.trim()}%`);
 const { data } = await q;
 setClientResults((data as Client[]) ?? []);
 }, 150);
 return () => clearTimeout(t);
 }, [clientSearch, creatingNewClient]);

 // close combobox on outside click
 useEffect(() => {
 const onClick = (e: MouseEvent) => {
 if (comboRef.current && !comboRef.current.contains(e.target as Node)) setClientOpen(false);
 };
 document.addEventListener("mousedown", onClick);
 return () => document.removeEventListener("mousedown", onClick);
 }, []);

 const reset = () => {
 setSelectedClient(null);
 setCreatingNewClient(false);
 setNewClient({ name: "", country: "BE", website: "", industry: "", primary_contact_name: "", primary_contact_role: "", primary_contact_email: "", primary_contact_phone: "" });
 setClientSearch("");
 setTitle("");
 setErrors([]);
 setCreated(null);
 };

 const submit = async () => {
 if (!supabase) {
 toast.error("Supabase niet geconfigureerd");
 return;
 }
 const errs: string[] = [];
 if (creatingNewClient) {
 if (!newClient.name.trim()) errs.push("Geef een naam voor de nieuwe klant.");
 } else if (!selectedClient) {
 errs.push("Kies een klant of maak een nieuwe aan.");
 }
 if (!title.trim()) errs.push("Projecttitel is verplicht.");
 setErrors(errs);
 if (errs.length) return;

 setSubmitting(true);
 try {
 // 1. resolve client
 let clientId: string;
 if (creatingNewClient) {
 const { data, error } = await supabase
 .schema("public" as never)
 .from("clients")
 .insert({
  name: newClient.name.trim(),
  country: newClient.country.trim() || "BE",
  website: newClient.website.trim() || null,
  industry: newClient.industry.trim() || null,
  primary_contact_name: newClient.primary_contact_name.trim() || null,
  primary_contact_role: newClient.primary_contact_role.trim() || null,
  primary_contact_email: newClient.primary_contact_email.trim() || null,
  primary_contact_phone: newClient.primary_contact_phone.trim() || null,
  })
 .select("id, name")
 .single();
 if (error || !data) throw new Error(error?.message ?? "Kon klant niet aanmaken");
 clientId = (data as { id: string }).id;
 } else {
 clientId = selectedClient!.id;
 }

 // 2. resolve template (Pulse active)
 const { data: template, error: tErr } = await supabase
 .schema("nestor")
 .from("intake_templates")
 .select("id")
 .eq("product_slug", "pulse")
 .eq("is_active", true)
 .order("version", { ascending: false })
 .limit(1)
 .single();
 if (tErr || !template) throw new Error("Geen actieve Pulse-template gevonden");

 // 3. token
 const token = crypto.randomUUID().replace(/-/g, "").slice(0, 16);

 // 4. insert intake
 const finalTitle = title.trim();
 const { data: intake, error: iErr } = await supabase
 .schema("nestor")
 .from("intakes")
 .insert({
 client_id: clientId,
 product_slug: "pulse",
 template_id: (template as { id: string }).id,
 status: "draft",
 title: finalTitle,
 client_intake_token: token,
 })
 .select("id, client_intake_token, title")
 .single();
 if (iErr || !intake) throw new Error(iErr?.message ?? "Kon intake niet aanmaken");

 setCreated({
 id: (intake as { id: string }).id,
 token: (intake as { client_intake_token: string }).client_intake_token,
 title: (intake as { title: string }).title,
 });
 } catch (e) {
 toast.error(e instanceof Error ? e.message : "Er ging iets mis");
 } finally {
 setSubmitting(false);
 }
 };

  if (created) {
 const url = `${window.location.origin}/intake/${created.token}`;
 const clientName = creatingNewClient ? newClient.name.trim() : selectedClient?.name ?? "";
 const industry = creatingNewClient ? newClient.industry.trim() : "";
 const emailSubject = `Gratis Nestor-run voor ${clientName}`;
 const emailBody = `Beste,

Wie zijn wij in het kort:

Agenic bouwt AI-intelligence en -tools die teams scherper laten beslissen dan hun concurrenten — Nestor is daar één van. We werken vanuit de Cronos-groep, met 500 AI-specialisten in het netwerk.

Ik zou jullie een gratis run aanbieden van Nestor, ons onderzoekssysteem bij Agenic. Jullie kiezen de vragen, wij leveren binnen 48 uur een rapport dat een richting kiest — niet een overzicht dat alle kanten openhoudt.

Wat Nestor is in één zin: een onderzoekssysteem dat consumer/audience, competition en sentimentvragen kraakt met onze interne methodiek. Geen samenvatting van wat al op Google staat. Een mening, met onderbouwing. Inclusief — als de data het vraagt — het ongemakkelijke ding dat een ander bureau niet zou durven opschrijven.

Geen catch. Geen demo, geen vendor-deck, geen "en als je daarna een retainer wil…". Een paar vragen, één keer goed gedaan.

Voorbeeldje van zo'n vragen${industry ? ` (geënt op ${industry})` : ""}:

1. [Voorbeeldvraag 1 — pas aan op de business van ${clientName}]

2. [Voorbeeldvraag 2 — pas aan op de business van ${clientName}]

3. [Voorbeeldvraag 3 — pas aan op de business van ${clientName}]

4. [Voorbeeldvraag 4 — pas aan op de business van ${clientName}]

Hier is jullie persoonlijke intake-link (10 minuten invullen):
${url}

Many thanks,
Yanick`;
 const mailto = `mailto:?subject=${encodeURIComponent(emailSubject)}&body=${encodeURIComponent(emailBody)}`;
 return (
 <div className="mx-auto max-w-2xl py-8">
 <div className="border border-ink/10 bg-paper p-8 text-center shadow-sm">
 <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100">
 <Check className="h-7 w-7 text-emerald-600" />
 </div>
 <h1 className="mt-4 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
 Intake aangemaakt
 </h1>
 <p className="mt-2 text-sm text-ink/60">
 Stuur deze link naar je klant. Geldig tot ze 'Submit' klikken.
 </p>
 <div className="mt-6 break-all border border-ink/10 bg-paper2 p-3 text-left font-mono text-xs text-ink/80">
 {url}
 </div>
 <div className="mt-4 flex flex-wrap justify-center gap-2">
 <Button
 onClick={async () => {
 try {
 await navigator.clipboard.writeText(url);
 toast.success("Link gekopieerd");
 } catch {
 toast.error("Kopiëren mislukt");
 }
 }}
 >
 <Copy className="mr-1.5 h-4 w-4" />
 Kopieer link
 </Button>
 <Button variant="outline" onClick={() => window.open(url, "_blank")}>
 <ExternalLink className="mr-1.5 h-4 w-4" />
 Open intake
 </Button>
 </div>

 {/* Email template preview */}
 <div className="mt-8 text-left">
 <div className="mb-2 flex items-center justify-between">
 <Label className="text-sm font-semibold text-ink">Voorbeeld-mail</Label>
 <div className="flex gap-2">
 <Button
 variant="outline"
 size="sm"
 onClick={async () => {
 try {
 await navigator.clipboard.writeText(emailBody);
 toast.success("Mail-tekst gekopieerd");
 } catch {
 toast.error("Kopiëren mislukt");
 }
 }}
 >
 <Copy className="mr-1.5 h-3.5 w-3.5" />
 Kopieer mail
 </Button>
 <Button variant="outline" size="sm" onClick={() => window.open(mailto, "_blank")}>
 Open in mail-app
 </Button>
 </div>
 </div>
 <div className="border border-ink/10 bg-paper2/40 p-4">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink/60">
 Onderwerp: {emailSubject}
 </div>
 <textarea
 readOnly
 value={emailBody}
 onClick={(e) => (e.target as HTMLTextAreaElement).select()}
 className="h-96 w-full resize-y border border-ink/10 bg-paper p-3 font-sans text-sm text-ink"
 />
 <p className="mt-2 text-xs text-ink/60">
 Vervang de 4 voorbeeldvragen door vragen die passen bij de business van {clientName || "de klant"}.
 </p>
 </div>
 </div>
 <p className="mt-6 text-xs text-ink/60">
 Wat nu? Je krijgt een melding wanneer de klant submit. Tot dan staat de intake op status 'Concept'.
 </p>
 <div className="mt-6 flex justify-center gap-6 text-sm">
 <Link to="/admin/pulse/intakes" className="text-ink/60 hover:text-ink hover:underline">
 ← Terug naar intakes-lijst
 </Link>
 <button onClick={reset} className="text-ink/60 hover:text-ink hover:underline">
 Nog een intake aanmaken
 </button>
 </div>
 </div>
 </div>
 );
 }

 return (
 <div className="mx-auto max-w-2xl py-8">
 <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">Nieuwe intake</h1>
 <p className="mt-1 text-sm text-ink/60">
 Kies een klant en geef het project een titel. We genereren een unieke link die je naar de klant stuurt.
 </p>

 <div className="mt-6 space-y-8 border border-ink/10 bg-paper p-6 shadow-sm">
 {/* Section 1 — Klant */}
 <section>
 <Label className="text-sm font-semibold text-ink">Klant</Label>
 {!creatingNewClient ? (
 <div ref={comboRef} className="relative mt-2">
 <div className="relative">
 <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" />
 <Input
 value={selectedClient ? selectedClient.name : clientSearch}
 onFocus={() => setClientOpen(true)}
 onChange={(e) => {
 setSelectedClient(null);
 setClientSearch(e.target.value);
 setClientOpen(true);
 }}
 placeholder="Zoek bestaande klant…"
 className="pl-9"
 />
 </div>
 {clientOpen && (
 <div className="absolute z-10 mt-1 max-h-72 w-full overflow-auto border border-ink/10 bg-paper shadow-lg">
 {clientResults.length === 0 && (
 <div className="px-3 py-2 text-sm text-ink/60">Geen resultaten</div>
 )}
 {clientResults.map((c) => (
 <button
 key={c.id}
 type="button"
 onClick={() => {
 setSelectedClient(c);
 setClientOpen(false);
 setClientSearch("");
 }}
 className="flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left hover:bg-ink/5"
 >
 <span className="text-sm text-ink">{c.name}</span>
 {c.country && <span className="text-xs text-ink/60">{c.country}</span>}
 </button>
 ))}
 <button
 type="button"
 onClick={() => {
 setCreatingNewClient(true);
 setClientOpen(false);
 setSelectedClient(null);
 setNewClient((s) => ({ ...s, name: clientSearch }));
 }}
 className="flex w-full items-center gap-2 border-t border-ink/5 px-3 py-2 text-left text-sm font-medium text-ink hover:bg-ink/5"
 >
 <Plus className="h-4 w-4" /> Nieuwe klant aanmaken
 </button>
 </div>
 )}
 </div>
 ) : (
 <div className="mt-2 space-y-3 border border-ink/10 bg-paper2/40 p-4">
 <div className="flex items-center justify-between">
 <span className="text-sm font-medium text-ink/70">Nieuwe klant</span>
 <button
 type="button"
 onClick={() => setCreatingNewClient(false)}
 className="text-xs text-ink/60 hover:text-ink hover:underline"
 >
 Annuleer
 </button>
 </div>
 <div>
 <Label htmlFor="nc-name" className="text-xs text-ink/60">Naam *</Label>
 <Input
 id="nc-name"
 value={newClient.name}
 onChange={(e) => setNewClient({ ...newClient, name: e.target.value })}
 className="mt-1"
 />
 </div>
 <div className="grid grid-cols-2 gap-3">
 <div>
 <Label htmlFor="nc-country" className="text-xs text-ink/60">Land</Label>
 <Input
 id="nc-country"
 value={newClient.country}
 onChange={(e) => setNewClient({ ...newClient, country: e.target.value })}
 className="mt-1"
 />
 </div>
 <div>
 <Label htmlFor="nc-industry" className="text-xs text-ink/60">Industry</Label>
 <Input
 id="nc-industry"
 value={newClient.industry}
 onChange={(e) => setNewClient({ ...newClient, industry: e.target.value })}
 className="mt-1"
 />
 </div>
 </div>
  <div>
  <Label htmlFor="nc-website" className="text-xs text-ink/60">Website</Label>
  <Input
  id="nc-website"
  type="url"
  placeholder="https://…"
  value={newClient.website}
  onChange={(e) => setNewClient({ ...newClient, website: e.target.value })}
  className="mt-1"
  />
  </div>

  <div className="border-t border-ink/10 pt-3">
  <p className="font-mono text-[11px] uppercase tracking-wider text-ink">Hoofdcontact <span className="font-sans normal-case text-ink/50">(optioneel — kan later)</span></p>
  <p className="mt-1 text-xs italic text-ink/50">Hoofdcontact wordt later getoond in de klantenlijst.</p>
  </div>
  <div className="grid grid-cols-2 gap-3">
  <div>
  <Label htmlFor="nc-cname" className="text-xs text-ink/60">Naam</Label>
  <Input id="nc-cname" value={newClient.primary_contact_name} onChange={(e) => setNewClient({ ...newClient, primary_contact_name: e.target.value })} className="mt-1" />
  </div>
  <div>
  <Label htmlFor="nc-crole" className="text-xs text-ink/60">Rol</Label>
  <Input id="nc-crole" value={newClient.primary_contact_role} onChange={(e) => setNewClient({ ...newClient, primary_contact_role: e.target.value })} placeholder="bv. CEO" className="mt-1" />
  </div>
  </div>
  <div className="grid grid-cols-2 gap-3">
  <div>
  <Label htmlFor="nc-cemail" className="text-xs text-ink/60">Email</Label>
  <Input id="nc-cemail" type="email" value={newClient.primary_contact_email} onChange={(e) => setNewClient({ ...newClient, primary_contact_email: e.target.value })} className="mt-1" />
  </div>
  <div>
  <Label htmlFor="nc-cphone" className="text-xs text-ink/60">Telefoon</Label>
  <Input id="nc-cphone" value={newClient.primary_contact_phone} onChange={(e) => setNewClient({ ...newClient, primary_contact_phone: e.target.value })} placeholder="+32 …" className="mt-1" />
  </div>
  </div>
  </div>
  )}
 </section>

 {/* Section 2 — Projecttitel */}
 <section>
 <Label htmlFor="title" className="text-sm font-semibold text-ink">
 Projecttitel <span className="font-normal text-ink/60">*</span>
 </Label>
 <Input
 id="title"
 value={title}
 onChange={(e) => setTitle(e.target.value)}
 placeholder="bv. EU-expansie 2026 — Q1 onderzoek"
 className="mt-2"
 />
 </section>

 {errors.length > 0 && (
 <div className="border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
 <ul className="list-inside list-disc space-y-0.5">
 {errors.map((e) => (
 <li key={e}>{e}</li>
 ))}
 </ul>
 </div>
 )}

 <div className="flex items-center justify-between">
 <Link to="/admin/pulse/intakes" className="text-sm text-ink/60 hover:text-ink hover:underline">
 ← Annuleer
 </Link>
 <Button onClick={submit} disabled={submitting}>
 {submitting ? (
 <>
 <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
 Bezig met aanmaken…
 </>
 ) : (
 "Genereer intake-link"
 )}
 </Button>
 </div>
 </div>
 </div>
 );
}
