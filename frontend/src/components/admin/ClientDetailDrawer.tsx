import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Link } from "@tanstack/react-router";
import { format } from "date-fns";
import { useTranslation } from "react-i18next";
import { getDateLocale } from "@/lib/i18n/date-locale";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ProductPill, STATUS_NL, statusPillClass } from "./clientPills";

export type ClientDrawerInitial = {
  id: string;
  name: string;
  country: string | null;
  website: string | null;
  industry: string | null;
  vat_number: string | null;
  primary_contact_name: string | null;
  primary_contact_role: string | null;
  primary_contact_email: string | null;
  primary_contact_phone: string | null;
};

type Project = {
  id: string;
  title: string;
  product_slug: string | null;
  product_name: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  delivered_at?: string | null;
};

export function ClientDetailDrawer({
  open,
  onOpenChange,
  client,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  client: ClientDrawerInitial | null;
  onSaved: () => void;
}) {
  const { t, i18n } = useTranslation("admin");
  const [v, setV] = useState({
    name: "",
    country: "BE",
    website: "",
    industry: "",
    primary_contact_name: "",
    primary_contact_role: "",
    primary_contact_email: "",
    primary_contact_phone: "",
  });
  const [saving, setSaving] = useState(false);
  const [projects, setProjects] = useState<Project[] | null>(null);

  useEffect(() => {
    if (!open || !client) return;
    setV({
      name: client.name ?? "",
      country: client.country ?? "BE",
      website: client.website ?? "",
      industry: client.industry ?? "",
      primary_contact_name: client.primary_contact_name ?? "",
      primary_contact_role: client.primary_contact_role ?? "",
      primary_contact_email: client.primary_contact_email ?? "",
      primary_contact_phone: client.primary_contact_phone ?? "",
    });
    setProjects(null);
    if (!supabase) return;
    (async () => {
      const { data, error } = await supabase!
        .schema("public" as never)
        .rpc("list_client_intakes", { p_client_id: client.id });
      if (!error) setProjects((data ?? []) as Project[]);
      else setProjects([]);
    })();
  }, [open, client]);

  const upd = (k: keyof typeof v, val: string) => setV((s) => ({ ...s, [k]: val }));

  const submit = async () => {
    if (!supabase || !client) return;
    if (!v.name.trim()) {
      toast.error(t("clientDrawer.nameRequired"));
      return;
    }
    setSaving(true);
    const { error } = await supabase
      .schema("public" as never)
      .from("clients")
      .update({
        name: v.name.trim(),
        country: v.country.trim() || "BE",
        website: v.website.trim() || null,
        industry: v.industry.trim() || null,
        primary_contact_name: v.primary_contact_name.trim() || null,
        primary_contact_role: v.primary_contact_role.trim() || null,
        primary_contact_email: v.primary_contact_email.trim() || null,
        primary_contact_phone: v.primary_contact_phone.trim() || null,
      })
      .eq("id", client.id);
    setSaving(false);
    if (error) {
      toast.error(error.message);
      return;
    }
    toast.success(t("clientDrawer.saved"));
    onSaved();
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-[480px] overflow-y-auto bg-paper border-l border-ink p-0"
      >
        <div className="border-b border-ink px-6 py-5">
          <SheetHeader>
            <SheetTitle className="font-serif text-2xl font-normal lowercase tracking-tight text-ink">
              {t("clientDrawer.title")}
            </SheetTitle>
          </SheetHeader>
        </div>

        {client && (
          <div className="px-6 py-6 space-y-6">
            <section className="space-y-4">
              <SectionTitle>{t("clientDrawer.clientData")}</SectionTitle>
              <Field id="d-name" label={t("clientDrawer.name")}>
                <Input id="d-name" value={v.name} onChange={(e) => upd("name", e.target.value)} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field id="d-ind" label={t("clientDrawer.industry")}>
                  <Input id="d-ind" value={v.industry} onChange={(e) => upd("industry", e.target.value)} />
                </Field>
                <Field id="d-co" label={t("clientDrawer.country")}>
                  <Input id="d-co" value={v.country} onChange={(e) => upd("country", e.target.value)} />
                </Field>
              </div>
              <Field id="d-web" label={t("clientDrawer.website")}>
                <Input id="d-web" type="url" placeholder="https://" value={v.website} onChange={(e) => upd("website", e.target.value)} />
              </Field>
            </section>

            <section className="space-y-4 border-t border-ink/15 pt-5">
              <SectionTitle>{t("clientDrawer.primaryContact")}</SectionTitle>
              <div className="grid grid-cols-2 gap-3">
                <Field id="d-cn" label={t("clientDrawer.name")}>
                  <Input id="d-cn" value={v.primary_contact_name} onChange={(e) => upd("primary_contact_name", e.target.value)} />
                </Field>
                <Field id="d-cr" label={t("clientDrawer.role")}>
                  <Input id="d-cr" value={v.primary_contact_role} onChange={(e) => upd("primary_contact_role", e.target.value)} placeholder={t("clientDrawer.rolePlaceholder")} />
                </Field>
              </div>
              <Field id="d-ce" label={t("clientDrawer.email")}>
                <Input id="d-ce" type="email" value={v.primary_contact_email} onChange={(e) => upd("primary_contact_email", e.target.value)} />
              </Field>
              <Field id="d-cp" label={t("clientDrawer.phone")}>
                <Input id="d-cp" value={v.primary_contact_phone} onChange={(e) => upd("primary_contact_phone", e.target.value)} placeholder="+32 …" />
              </Field>
              <div className="flex gap-2 pt-1">
                <Button onClick={submit} disabled={saving}>
                  {saving ? t("clientDrawer.saving") : t("clientDrawer.save")}
                </Button>
                <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
                  {t("clientDrawer.cancel")}
                </Button>
              </div>
            </section>

            <section className="space-y-3 border-t border-ink/15 pt-5">
              <SectionTitle>
                {t("clientDrawer.projectsTitle")}{projects ? ` (${projects.length})` : ""}
              </SectionTitle>
              {projects === null ? (
                <p className="font-mono text-xs uppercase tracking-wider text-ink/40">{t("clientDrawer.loading")}</p>
              ) : projects.length === 0 ? (
                <p className="font-mono text-xs uppercase tracking-wider text-ink/40">{t("clientDrawer.noProjects")}</p>
              ) : (
                <div className="space-y-3">
                  {projects.map((p) => (
                    <div key={p.id} className="border border-ink/30 bg-paperLight p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            {p.product_slug && (
                              <ProductPill slug={p.product_slug} name={p.product_name ?? p.product_slug} />
                            )}
                            <span className="font-sans text-sm font-medium text-ink truncate">
                              {p.title}
                            </span>
                          </div>
                          <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink/60">
                            {t("clientDrawer.createdAt")}: {format(new Date(p.created_at), "d MMM yyyy", { locale: getDateLocale(i18n.language) })}
                            {p.status === "delivered" && p.delivered_at
                              ? ` · ${t("clientDrawer.deliveredAt")}: ${format(new Date(p.delivered_at), "d MMM yyyy", { locale: getDateLocale(i18n.language) })}`
                              : ` · ${t("clientDrawer.lastEdited")}: ${format(new Date(p.updated_at), "d MMM HH:mm", { locale: getDateLocale(i18n.language) })}`}
                          </div>
                        </div>
                        <span className={statusPillClass(p.status)}>
                          {STATUS_NL[p.status] ?? p.status}
                        </span>
                      </div>
                      <div className="mt-3">
                        <Link
                          to="/admin/pulse/intakes/$id"
                          params={{ id: p.id }}
                          className="font-mono text-[11px] uppercase tracking-wider text-ink underline-offset-4 hover:underline"
                          onClick={() => onOpenChange(false)}
                        >
                          {t("clientDrawer.openIntake")}
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="pt-2">
                <Button
                  asChild
                  variant="outline"
                  className="font-mono text-[11px] uppercase tracking-wider"
                >
                  <Link
                    to="/admin/pulse/intakes/new"
                    search={{ client_id: client.id }}
                    onClick={() => onOpenChange(false)}
                  >
                    {t("clientDrawer.newProject")}
                  </Link>
                </Button>
              </div>
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[11px] uppercase tracking-wider text-ink">
      {children}
    </p>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
        {label}
      </Label>
      {children}
    </div>
  );
}
