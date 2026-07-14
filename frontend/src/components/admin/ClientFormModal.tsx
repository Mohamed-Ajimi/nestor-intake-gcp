import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

export type ClientFormValues = {
  id?: string;
  name: string;
  country: string;
  website: string;
  industry: string;
  vat_number: string;
  primary_contact_name: string;
  primary_contact_role: string;
  primary_contact_email: string;
  primary_contact_phone: string;
};

const empty: ClientFormValues = {
  name: "",
  country: "BE",
  website: "",
  industry: "",
  vat_number: "",
  primary_contact_name: "",
  primary_contact_role: "",
  primary_contact_email: "",
  primary_contact_phone: "",
};

export function ClientFormModal({
  open,
  onOpenChange,
  initial,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initial?: Partial<ClientFormValues> | null;
  onSaved: (client: { id: string; name: string }) => void;
}) {
  const { t } = useTranslation("admin");
  const isEdit = Boolean(initial?.id);
  const [values, setValues] = useState<ClientFormValues>(empty);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setValues({ ...empty, ...(initial ?? {}) } as ClientFormValues);
    }
  }, [open, initial]);

  const update = (k: keyof ClientFormValues, v: string) =>
    setValues((s) => ({ ...s, [k]: v }));

  const onSubmit = async () => {
    if (!supabase) return;
    if (!values.name.trim()) {
      toast.error(t("clientModal.nameRequired"));
      return;
    }
    setSaving(true);
    const payload = {
      name: values.name.trim(),
      country: values.country.trim() || "BE",
      website: values.website.trim() || null,
      industry: values.industry.trim() || null,
      vat_number: values.vat_number.trim() || null,
      primary_contact_name: values.primary_contact_name.trim() || null,
      primary_contact_role: values.primary_contact_role.trim() || null,
      primary_contact_email: values.primary_contact_email.trim() || null,
      primary_contact_phone: values.primary_contact_phone.trim() || null,
    };
    try {
      if (isEdit && initial?.id) {
        const { data, error } = await supabase
          .schema("public" as never)
          .from("clients")
          .update(payload)
          .eq("id", initial.id)
          .select("id, name")
          .single();
        if (error || !data) throw new Error(error?.message ?? t("clientModal.updateFailed"));
        toast.success(t("clientModal.saved"));
        onSaved(data as { id: string; name: string });
      } else {
        const { data, error } = await supabase
          .schema("public" as never)
          .from("clients")
          .insert(payload)
          .select("id, name")
          .single();
        if (error || !data) throw new Error(error?.message ?? t("clientModal.createFailed"));
        toast.success(t("clientModal.created"));
        onSaved(data as { id: string; name: string });
      }
      onOpenChange(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("clientModal.unknownError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-serif text-2xl font-normal lowercase">
            {isEdit ? t("clientModal.editTitle") : t("clientModal.createTitle")}
          </DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <Field id="cf-name" label={t("clientModal.name")}>
            <Input
              id="cf-name"
              value={values.name}
              onChange={(e) => update("name", e.target.value)}
              autoFocus
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field id="cf-industry" label={t("clientModal.industry")}>
              <Input
                id="cf-industry"
                value={values.industry}
                onChange={(e) => update("industry", e.target.value)}
              />
            </Field>
            <Field id="cf-country" label={t("clientModal.country")}>
              <Input
                id="cf-country"
                value={values.country}
                onChange={(e) => update("country", e.target.value)}
                placeholder="BE"
              />
            </Field>
          </div>
          <Field id="cf-website" label={t("clientModal.website")}>
            <Input
              id="cf-website"
              type="url"
              placeholder="https://"
              value={values.website}
              onChange={(e) => update("website", e.target.value)}
            />
          </Field>
          <Field id="cf-vat" label={t("clientModal.vatNumber")}>
            <Input
              id="cf-vat"
              value={values.vat_number}
              onChange={(e) => update("vat_number", e.target.value)}
              placeholder="BE0123.456.789"
            />
          </Field>

          <div className="mt-2 border-t border-ink/15 pt-4">
            <p className="font-mono text-[11px] uppercase tracking-wider text-ink">
              {t("clientModal.primaryContact")}
            </p>
          </div>

          <Field id="cf-cname" label={t("clientModal.name")}>
            <Input
              id="cf-cname"
              value={values.primary_contact_name}
              onChange={(e) => update("primary_contact_name", e.target.value)}
            />
          </Field>
          <Field id="cf-crole" label={t("clientModal.contactRole")}>
            <Input
              id="cf-crole"
              value={values.primary_contact_role}
              onChange={(e) => update("primary_contact_role", e.target.value)}
              placeholder={t("clientModal.contactRolePlaceholder")}
            />
          </Field>
          <Field id="cf-cemail" label={t("clientModal.email")}>
            <Input
              id="cf-cemail"
              type="email"
              value={values.primary_contact_email}
              onChange={(e) => update("primary_contact_email", e.target.value)}
            />
          </Field>
          <Field id="cf-cphone" label={t("clientModal.phone")}>
            <Input
              id="cf-cphone"
              value={values.primary_contact_phone}
              onChange={(e) => update("primary_contact_phone", e.target.value)}
              placeholder="+32 …"
            />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            {t("clientModal.cancel")}
          </Button>
          <Button onClick={onSubmit} disabled={saving}>
            {saving ? t("clientModal.saving") : t("clientModal.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
        {label}
      </Label>
      {children}
    </div>
  );
}
