import { useEffect, useState } from "react";
import { toast } from "sonner";
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
import { createSpace, updateSpace, type Space } from "@/lib/api/admin";

// Screen 3 helper — create / edit a space (USER-03). Name is required; slug is optional.
// There is deliberately NO status / delete control here: deactivate/reactivate go through
// the dedicated row actions, so a benign edit can never soft-delete a space (D-10).

const spaceSchema = z.object({
  name: z.string().trim().min(1, "Naam is verplicht"),
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
  const isEdit = Boolean(initial?.id);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setSlug(initial?.slug ?? "");
      setSaving(false);
      setError(null);
    }
  }, [open, initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const parsed = spaceSchema.safeParse({ name, slug });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Ongeldige invoer");
      return;
    }

    setSaving(true);
    const slugValue = parsed.data.slug && parsed.data.slug.length > 0 ? parsed.data.slug : undefined;
    const result =
      isEdit && initial
        ? await updateSpace(initial.id, { name: parsed.data.name, slug: slugValue })
        : await createSpace({ name: parsed.data.name, slug: slugValue });
    setSaving(false);

    if (!result.success) {
      setError(result.error);
      toast.error(result.error);
      return;
    }

    toast.success("Opgeslagen");
    onSaved();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle className="font-serif text-2xl font-normal lowercase">
              {isEdit ? "space bewerken" : "nieuwe space"}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-1.5">
              <Label
                htmlFor="space-name"
                className="font-mono text-[11px] uppercase tracking-wider text-ink/70"
              >
                Naam
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
                Slug
              </Label>
              <Input
                id="space-slug"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="bv. acme-corp"
              />
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
              Annuleren
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Opslaan…" : "Opslaan"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
