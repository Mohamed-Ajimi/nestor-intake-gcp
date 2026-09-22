import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ArrowRight, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createIntake, type Intake } from "@/lib/api/intakes";
import { useActiveSpace } from "@/lib/active-space";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/admin/pulse/intakes/new")({
 // Optional search key (`{ client_id?: string }`, not a required possibly-undefined key)
 // so links/navigates to this route need not pass `search`. Type hygiene only.
 validateSearch: (s: Record<string, unknown>): { client_id?: string } =>
  typeof s.client_id === "string" ? { client_id: s.client_id } : {},
 component: NewIntakePage,
});

function NewIntakePage() {
 const { t } = useTranslation("admin");
 const navigate = useNavigate();

 // The intake's PROJECT name (free text). The variable is still called `clientName`
 // and the API field is still `client_name` ON PURPOSE: D-23.5-03 is a LABEL change
 // only — `intakes.client_name` is not renamed and there is no migration. Do not
 // "fix" this mismatch; the column name and the label are deliberately out of step.
 // The owning space is injected server-side from the verified identity (TENANT-02)
 // — never sent from the browser. Superadmins target a space via the global
 // active-space switcher (plan 08), not this form.
 const [clientName, setClientName] = useState("");

 // The no-client-selected guard. `create_intake` (intake_routes.py) answers 422
 // "Select a client (space) before creating an intake." for a SUPERADMIN with no
 // `?space_id`, and ignores the param entirely for a regular user (their space comes
 // from the verified token). So the guard mirrors the backend exactly: superadmin AND
 // no active client. `AdminLayout` already walls off non-superadmins, which makes the
 // role half redundant today — it is kept so the guard stays true to the backend rule
 // rather than to the current shape of the wall above it.
 const { activeSpaceId } = useActiveSpace();
 const { isSuperadmin } = useAuth();
 const noClientSelected = isSuperadmin && !activeSpaceId;

 const [submitting, setSubmitting] = useState(false);
 const [errors, setErrors] = useState<string[]>([]);
 const [created, setCreated] = useState<Intake | null>(null);

 const reset = () => {
 setClientName("");
 setErrors([]);
 setCreated(null);
 };

 const submit = async () => {
 // Re-checked here and not only on the button's `disabled`: a disabled attribute is
 // an affordance, not a guard (the same rule plan 23.5-02 applied to the typed-DELETE
 // confirmation).
 if (noClientSelected) {
 setErrors([t("intakesNew.noClientSelected")]);
 return;
 }
 const errs: string[] = [];
 if (!clientName.trim()) errs.push(t("intakesNew.clientNameRequired"));
 setErrors(errs);
 if (errs.length) return;

 setSubmitting(true);
 const res = await createIntake({ client_name: clientName.trim() });
 setSubmitting(false);

 if (!res.success) {
 toast.error(res.error);
 return;
 }
 setCreated(res.data);
 };

 if (created) {
 return (
 <div className="mx-auto max-w-2xl py-8">
 <div className="border border-ink/10 bg-paper p-8 text-center shadow-sm">
 <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100">
 <Check className="h-7 w-7 text-emerald-600" />
 </div>
 <h1 className="mt-4 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
 {t("intakesNew.createdTitle")}
 </h1>
 <p className="mt-2 text-sm text-ink/60">{t("intakesNew.createdBody")}</p>
 {created.client_name && (
 <p className="mt-4 font-mono text-xs uppercase tracking-wider text-ink/60">
 {t("intakesNew.clientLabel", { name: created.client_name })}
 </p>
 )}
 <div className="mt-6 flex flex-wrap justify-center gap-2">
 <Button
 onClick={() =>
 navigate({ to: "/admin/pulse/intakes/$id", params: { id: created.id } })
 }
 >
 <ArrowRight className="mr-1.5 h-4 w-4" />
 {t("intakesNew.openIntake")}
 </Button>
 </div>
 <div className="mt-6 flex justify-center gap-6 text-sm">
 <Link to="/admin/pulse/intakes" className="text-ink/60 hover:text-ink hover:underline">
 {t("intakesNew.backToList")}
 </Link>
 <button onClick={reset} className="text-ink/60 hover:text-ink hover:underline">
 {t("intakesNew.createAnother")}
 </button>
 </div>
 </div>
 </div>
 );
 }

 return (
 <div className="max-w-2xl">
 <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
 {t("intakesNew.title")}
 </h1>
 <p className="mt-1 text-sm text-ink/60">{t("intakesNew.subtitle")}</p>

 <div className="mt-6 space-y-8 border border-ink bg-paper p-6">
 <section>
 <Label htmlFor="client_name" className="block font-mono text-[11px] uppercase tracking-wider text-ink/70">
 {t("intakesNew.clientNameLabel")}<span className="ml-1 text-red-600">*</span>
 </Label>
 <Input
 id="client_name"
 value={clientName}
 onChange={(e) => setClientName(e.target.value)}
 placeholder={t("intakesNew.clientNamePlaceholder")}
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

 {noClientSelected && (
 <div className="border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
 {t("intakesNew.noClientSelected")}
 </div>
 )}

 <div className="flex items-center justify-between border-t border-ink/15 pt-6">
 <Link to="/admin/pulse/intakes" className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink">
 {t("intakesNew.cancel")}
 </Link>
 <Button onClick={submit} disabled={submitting || noClientSelected}>
 {submitting ? (
 <>
 <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
 {t("intakesNew.creating")}
 </>
 ) : (
 t("intakesNew.createButton")
 )}
 </Button>
 </div>
 </div>
 </div>
 );
}
