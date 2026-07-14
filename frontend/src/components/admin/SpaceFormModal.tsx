import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { z } from "zod";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createSpace, updateSpace, type Space, type SpaceLocale } from "@/lib/api/admin";

/** The three selectable space default locales (D-09). New spaces default to "nl". */
const LOCALE_OPTIONS: SpaceLocale[] = ["nl", "fr", "en"];

// Screen 3 helper — create / edit a space (USER-03). Name is required; slug is optional.
// There is deliberately NO status / delete control here: deactivate/reactivate go through
// the dedicated row actions, so a benign edit can never soft-delete a space (D-10).

const spaceSchema = z.object({
  name: z.string().trim().min(1),
  slug: z.string().trim().optional(),
});

export function SpaceFormModal({
  open,
  onOpenChange,
  initial,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initial?: Space | null;
  onSaved: () => void;
}) {
  const { t } = useTranslation("admin");
  const isEdit = Boolean(initial?.id);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  // D-09: new spaces default to "nl"; editing shows the space's current default_locale.
  const [defaultLocale, setDefaultLocale] = useState<SpaceLocale>("nl");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setSlug(initial?.slug ?? "");
      setDefaultLocale(initial?.default_locale ?? "nl");
      setSaving(false);
      setError(null);
    }
  }, [open, initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const parsed = spaceSchema.safeParse({ name, slug });
    if (!parsed.success) {
      setError(t("spaceForm.nameRequired"));
      return;
    }

    setSaving(true);
    const slugValue = parsed.data.slug && parsed.data.slug.length > 0 ? parsed.data.slug : undefined;
    const result =
      isEdit && initial
        ? await updateSpace(initial.id, {
            name: parsed.data.name,
            slug: slugValue,
            default_locale: defaultLocale,
          })
        : await createSpace({
            name: parsed.data.name,
            slug: slugValue,
            default_locale: defaultLocale,
          });
    setSaving(false);

    if (!result.success) {
      setError(result.error);
      toast.error(result.error);
      return;
    }

    toast.success(t("spaceForm.saved"));
    onSaved();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle className="font-serif text-2xl font-normal lowercase">
              {isEdit ? t("spaceForm.editTitle") : t("spaceForm.createTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-1.5">
              <Label
                htmlFor="space-name"
                className="font-mono text-[11px] uppercase tracking-wider text-ink/70"
              >
                {t("spaceForm.name")}
              </Label>
              <Input
                id="space-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="grid gap-1.5">
              <Label
                htmlFor="space-slug"
                className="font-mono text-[11px] uppercase tracking-wider text-ink/70"
              >
                {t("spaceForm.slug")}
              </Label>
              <Input
                id="space-slug"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder={t("spaceForm.slugPlaceholder")}
              />
            </div>
            <div className="grid gap-1.5">
              <Label
                htmlFor="space-locale"
                className="font-mono text-[11px] uppercase tracking-wider text-ink/70"
              >
                {t("spaceForm.defaultLocale")}
              </Label>
              <Select
                value={defaultLocale}
                onValueChange={(v) => setDefaultLocale(v as SpaceLocale)}
              >
                <SelectTrigger id="space-locale">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LOCALE_OPTIONS.map((loc) => (
                    <SelectItem key={loc} value={loc}>
                      {t(`spaceForm.locale.${loc}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              {t("spaceForm.cancel")}
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? t("spaceForm.saving") : t("spaceForm.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
