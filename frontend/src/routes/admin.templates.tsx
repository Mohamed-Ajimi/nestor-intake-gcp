import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ProductShell } from "@/components/admin/ProductShell";
import { ADMIN_NAV } from "@/components/admin/adminNav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  cloneTemplate,
  listSpaces,
  listTemplates,
  updateTemplate,
  type Space,
  type Template,
} from "@/lib/api/admin";

// Screen 4 — Template management (USER-03 / D-11). Per-space template list, clone a
// template into a space, and a monospace JSON editor for the schema with LIVE validation:
// invalid JSON disables "Schema opslaan" with an inline red message; valid JSON shows
// "GELDIGE JSON". There is NO drag-drop builder and NO delete affordance.

export const Route = createFileRoute("/admin/templates")({
  component: TemplatesPage,
});

function TemplatesPage() {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string>("");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loadingSpaces, setLoadingSpaces] = useState(true);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [editing, setEditing] = useState<Template | null>(null);

  // Load spaces once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingSpaces(true);
      const res = await listSpaces();
      if (cancelled) return;
      if (!res.success) {
        setError(res.error);
        setLoadingSpaces(false);
        return;
      }
      setSpaces(res.data);
      const firstActive = res.data.find((s) => s.status === "active") ?? res.data[0];
      if (firstActive) setSelectedSpaceId(firstActive.id);
      setLoadingSpaces(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Load templates whenever the selected space changes.
  useEffect(() => {
    if (!selectedSpaceId) {
      setTemplates([]);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoadingTemplates(true);
      setError(null);
      const res = await listTemplates(selectedSpaceId);
      if (cancelled) return;
      if (!res.success) {
        setError(res.error);
        setLoadingTemplates(false);
        return;
      }
      setTemplates(res.data);
      setLoadingTemplates(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedSpaceId]);

  async function reloadTemplates() {
    if (!selectedSpaceId) return;
    const res = await listTemplates(selectedSpaceId);
    if (res.success) setTemplates(res.data);
  }

  return (
    <ProductShell product="beheer" items={ADMIN_NAV}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
            templates
          </h1>
          <p className="mt-1 font-sans text-sm italic text-ink/60">
            Kloon een standaard-template in een space en bewerk het schema (JSON).
          </p>
        </div>
        <Button onClick={() => setCloneOpen(true)} disabled={!selectedSpaceId}>
          + Template klonen
        </Button>
      </div>

      <div className="mt-6 max-w-sm">
        <Label className="font-mono text-[11px] uppercase tracking-wider text-ink/70">Space</Label>
        <div className="mt-1.5">
          <Select value={selectedSpaceId} onValueChange={setSelectedSpaceId} disabled={loadingSpaces}>
            <SelectTrigger>
              <SelectValue placeholder="Kies een space…" />
            </SelectTrigger>
            <SelectContent>
              {spaces.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="mt-6">
        {loadingSpaces || loadingTemplates ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : error ? (
          <div className="py-12 text-center text-sm text-red-600">{error}</div>
        ) : templates.length === 0 ? (
          <div className="mt-6 border border-ink/20 bg-paper2/40 p-12 text-center">
            <p className="mb-4 font-mono text-sm text-ink/60">⌀ Nog geen templates in deze space</p>
            <p className="mb-6 text-sm text-ink/50">Kloon een standaard-template om te beginnen.</p>
            <Button onClick={() => setCloneOpen(true)} disabled={!selectedSpaceId}>
              + Template klonen
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            {templates.map((t) => (
              <button
                key={t.id}
                onClick={() => setEditing(t)}
                className="flex w-full items-center justify-between gap-4 border border-ink/15 bg-paper px-4 py-3 text-left hover:bg-ink/5"
              >
                <span className="font-sans font-medium text-ink">{t.name}</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-ink/50">
                  schema bewerken →
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <CloneTemplateDialog
        open={cloneOpen}
        onOpenChange={setCloneOpen}
        spaces={spaces}
        defaultSpaceId={selectedSpaceId}
        onCloned={(spaceId) => {
          if (spaceId === selectedSpaceId) void reloadTemplates();
          else setSelectedSpaceId(spaceId);
        }}
      />

      <SchemaEditorDialog
        template={editing}
        spaceId={selectedSpaceId}
        onClose={() => setEditing(null)}
        onSaved={() => void reloadTemplates()}
      />
    </ProductShell>
  );
}

// ---------------------------------------------------------------------------
// Clone-template dialog — space + source-template picker + new name.
// ---------------------------------------------------------------------------

function CloneTemplateDialog({
  open,
  onOpenChange,
  spaces,
  defaultSpaceId,
  onCloned,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  spaces: Space[];
  defaultSpaceId: string;
  onCloned: (spaceId: string) => void;
}) {
  const [targetSpaceId, setTargetSpaceId] = useState(defaultSpaceId);
  const [sourceTemplateId, setSourceTemplateId] = useState<string>("");
  const [name, setName] = useState("");
  const [sources, setSources] = useState<Template[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTargetSpaceId(defaultSpaceId);
      setSourceTemplateId("");
      setName("");
      setError(null);
      setSaving(false);
    }
  }, [open, defaultSpaceId]);

  // Load candidate source templates for the chosen target space.
  useEffect(() => {
    if (!open || !targetSpaceId) {
      setSources([]);
      return;
    }
    let cancelled = false;
    (async () => {
      const res = await listTemplates(targetSpaceId);
      if (cancelled) return;
      if (res.success) setSources(res.data);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, targetSpaceId]);

  async function handleClone(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!targetSpaceId) {
      setError("Kies een space.");
      return;
    }
    if (!name.trim()) {
      setError("Naam is verplicht.");
      return;
    }
    setSaving(true);
    const res = await cloneTemplate(targetSpaceId, {
      name: name.trim(),
      sourceTemplateId: sourceTemplateId || undefined,
    });
    setSaving(false);
    if (!res.success) {
      setError(res.error);
      toast.error(res.error);
      return;
    }
    toast.success("Template gekloond");
    onCloned(targetSpaceId);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <form onSubmit={handleClone}>
          <DialogHeader>
            <DialogTitle className="font-serif text-2xl font-normal lowercase">
              template klonen
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-1.5">
              <Label className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
                Space
              </Label>
              <Select value={targetSpaceId} onValueChange={setTargetSpaceId}>
                <SelectTrigger>
                  <SelectValue placeholder="Kies een space…" />
                </SelectTrigger>
                <SelectContent>
                  {spaces.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
                Bron-template
              </Label>
              <Select value={sourceTemplateId} onValueChange={setSourceTemplateId}>
                <SelectTrigger>
                  <SelectValue placeholder="Optioneel — kies een bron…" />
                </SelectTrigger>
                <SelectContent>
                  {sources.map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label
                htmlFor="clone-name"
                className="font-mono text-[11px] uppercase tracking-wider text-ink/70"
              >
                Naam
              </Label>
              <Input
                id="clone-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="bv. intake v2"
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
              {saving ? "Klonen…" : "Template klonen"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Schema editor — monospace JSON <Textarea> with live validation.
// ---------------------------------------------------------------------------

function SchemaEditorDialog({
  template,
  spaceId,
  onClose,
  onSaved,
}: {
  template: Template | null;
  spaceId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (template) {
      setText(JSON.stringify(template.schema ?? {}, null, 2));
      setSaving(false);
    }
  }, [template]);

  // Live JSON validation — recomputed each render from the editor text.
  const validation = useMemo<
    { ok: true; value: Record<string, unknown> } | { ok: false; message: string }
  >(() => {
    try {
      const parsed = JSON.parse(text);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { ok: false, message: "schema moet een JSON-object zijn" };
      }
      return { ok: true, value: parsed as Record<string, unknown> };
    } catch (err) {
      return { ok: false, message: err instanceof Error ? err.message : "parse error" };
    }
  }, [text]);

  async function handleSave() {
    if (!template || !validation.ok) return;
    setSaving(true);
    const res = await updateTemplate(spaceId, template.id, validation.value);
    setSaving(false);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    toast.success("Opgeslagen");
    onSaved();
    onClose();
  }

  return (
    <Dialog open={Boolean(template)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle className="font-serif text-2xl font-normal lowercase">
            schema bewerken
          </DialogTitle>
        </DialogHeader>
        <div className="grid gap-2 py-2">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            rows={18}
            className="min-h-[320px] border border-ink bg-paperLight font-mono text-sm text-ink"
          />
          {validation.ok ? (
            <p className="font-mono text-[11px] uppercase tracking-wider text-ink/60">GELDIGE JSON</p>
          ) : (
            <p className="text-sm text-red-600">Ongeldige JSON: {validation.message}</p>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
            Annuleren
          </Button>
          <Button type="button" onClick={handleSave} disabled={!validation.ok || saving}>
            {saving ? "Opslaan…" : "Schema opslaan"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
