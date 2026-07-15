import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { IntakeField } from "@/lib/intake-types";
import * as storage from "@/lib/api/storage";
import { toast } from "sonner";

type Props = {
 field: IntakeField;
 value: any;
 onChange: (v: any) => void;
 intakeId: string;
 error?: string;
 disabled?: boolean;
 // WR-04: when the field lives inside an unsaved edit draft (admin edit mode), the
 // destructive server-side delete of a replaced/removed object must be DEFERRED until
 // the draft is committed — otherwise a cancel leaves the persisted answer pointing at a
 // deleted object. The parent supplies this to queue paths-to-remove; it flushes them
 // after a successful save and drops them on cancel. When omitted (client save-as-you-go
 // form, where every change persists immediately), the delete fires inline instead.
 onDeferRemove?: (paths: string[]) => void;
};

const inputCls =
 "w-full border border-ink bg-paper2 px-3.5 py-2.5 text-[15px] text-ink placeholder:text-ink/40 focus:outline-none focus:border-2 focus:px-[calc(0.875rem-1px)] focus:py-[calc(0.625rem-1px)] disabled:bg-paper2 disabled:text-ink/60";

export function FieldRenderer(props: Props) {
 const { field, error } = props;
 const { t } = useTranslation("intake");

 return (
 <div className="space-y-2">
 <div>
 <label className="block font-mono text-xs uppercase tracking-wider text-ink">
 {field.label}
 {field.required && <span className="ml-1 text-red-600">*</span>}
 </label>
 {field.help && (
 <p className="mt-1 text-xs text-ink/60">{field.help}</p>
 )}
 </div>
 <FieldControl {...props} />
 {field.examples && (field.examples.good || field.examples.bad) && (
 <details className="text-xs text-ink/60">
 <summary className="cursor-pointer select-none hover:text-ink/70">
 ▶ {t("field.examples")}
 </summary>
 <div className="mt-2 space-y-1">
 {field.examples.good?.map((g, i) => (
 <div key={`g${i}`} className="flex gap-2">
 <span>✅</span>
 <span className="text-ink/70">{g}</span>
 </div>
 ))}
 {field.examples.bad?.map((b, i) => (
 <div key={`b${i}`} className="flex gap-2">
 <span>❌</span>
 <span className="text-ink/70">{b}</span>
 </div>
 ))}
 </div>
 </details>
 )}
 {error && <p className="text-xs text-red-600">{error}</p>}
 </div>
 );
}

function FieldControl({ field, value, onChange, intakeId, disabled, onDeferRemove }: Props) {
 const { t } = useTranslation("intake");
 switch (field.type) {
 case "text":
 return (
 <input
 type="text"
 className={inputCls}
 value={value ?? ""}
 placeholder={field.placeholder}
 disabled={disabled}
 onChange={(e) => onChange(e.target.value)}
 />
 );
 case "longtext":
 return (
 <textarea
 rows={field.rows ?? 3}
 className={inputCls}
 value={value ?? ""}
 placeholder={field.placeholder}
 disabled={disabled}
 onChange={(e) => onChange(e.target.value)}
 />
 );
 case "email":
 return (
 <input
 type="email"
 className={inputCls}
 value={value ?? ""}
 placeholder={field.placeholder}
 disabled={disabled}
 onChange={(e) => onChange(e.target.value)}
 />
 );
 case "tel":
 return (
 <input
 type="tel"
 className={inputCls}
 value={value ?? ""}
 placeholder={field.placeholder}
 disabled={disabled}
 onChange={(e) => onChange(e.target.value)}
 />
 );
 case "date":
 return (
 <input
 type="date"
 className={inputCls}
 value={value ?? ""}
 disabled={disabled}
 onChange={(e) => onChange(e.target.value)}
 />
 );
 case "select":
 return (
 <select
 className={inputCls}
 value={value ?? ""}
 disabled={disabled}
 onChange={(e) => onChange(e.target.value)}
 >
 <option value="">{t("field.choose")}</option>
 {field.options?.map((o) => (
 <option key={o.value} value={o.value}>
 {o.label}
 </option>
 ))}
 </select>
 );
 case "radio":
 return <RadioControl field={field} value={value} onChange={onChange} disabled={disabled} />;
 case "list":
 return <ListControl field={field} value={value} onChange={onChange} intakeId={intakeId} disabled={disabled} />;
 case "file":
 return <FileControl field={field} value={value} onChange={onChange} intakeId={intakeId} multi={false} disabled={disabled} onDeferRemove={onDeferRemove} />;
 case "files":
 return <FileControl field={field} value={value} onChange={onChange} intakeId={intakeId} multi={true} disabled={disabled} onDeferRemove={onDeferRemove} />;
 case "download":
 return <DownloadControl field={field} intakeId={intakeId} />;
 case "proposal_list":
 return <ProposalListControl value={value} onChange={onChange} disabled={disabled} />;
 default:
 return <p className="text-xs text-red-600">{t("field.unsupported", { type: field.type })}</p>;
 }
}

function ProposalListControl({
 value,
 onChange,
 disabled,
}: {
 value: any;
 onChange: (v: any) => void;
 disabled?: boolean;
}) {
 const { t } = useTranslation("intake");
 const items: Array<{ text: string; rationale?: string; approved?: boolean }> = Array.isArray(value)
 ? value
 : [];
 if (items.length === 0) {
 return <p className="text-sm text-ink/60">{t("field.noProposals")}</p>;
 }
 const toggle = (i: number) => {
 const next = items.map((it, idx) => (idx === i ? { ...it, approved: !it.approved } : it));
 onChange(next);
 };
 return (
 <div className="space-y-3">
 {items.map((it, i) => (
 <label
 key={i}
 className={
 "flex cursor-pointer items-start gap-3 border p-3 transition-colors " +
 (it.approved
 ? "border-ink bg-paper2"
 : "border-ink/10 hover:border-ink/10")
 }
 >
 <input
 type="checkbox"
 className="mt-1"
 checked={!!it.approved}
 disabled={disabled}
 onChange={() => toggle(i)}
 />
 <div className="flex-1">
 <div className="text-sm font-medium text-ink">{it.text}</div>
 {it.rationale && (
 <div className="mt-1 text-xs text-ink/60">{it.rationale}</div>
 )}
 <div className="mt-1 text-xs text-ink/60">{t("field.includeInResearch")}</div>
 </div>
 </label>
 ))}
 </div>
 );
}

function RadioControl({
 field,
 value,
 onChange,
 disabled,
}: {
 field: IntakeField;
 value: any;
 onChange: (v: any) => void;
 disabled?: boolean;
}) {
 const { t } = useTranslation("intake");
 const current =
 typeof value === "object" && value !== null ? value : { choice: value ?? "", text: "" };

 return (
 <div className="space-y-2">
 {field.options?.map((opt) => {
 const selected = current.choice === opt.value;
 return (
 <label
 key={opt.value}
 className={
 "flex cursor-pointer items-start gap-3 border p-3 transition-colors " +
 (selected ? "border-ink bg-paper2" : "border-ink/10 hover:border-ink/10")
 }
 >
 <input
 type="radio"
 name={field.key}
 className="mt-1"
 checked={selected}
 disabled={disabled}
 onChange={() => {
 if (opt.allow_text) {
 onChange({ choice: opt.value, text: current.text ?? "" });
 } else {
 onChange(opt.value);
 }
 }}
 />
 <div className="flex-1">
 <div className="text-sm font-medium text-ink">{opt.label}</div>
 {opt.description && (
 <div className="mt-0.5 text-xs text-ink/60">{opt.description}</div>
 )}
 {opt.allow_text && selected && (
 <input
 type="text"
 className={inputCls + " mt-2"}
 value={current.text ?? ""}
 disabled={disabled}
 placeholder={t("field.specify")}
 onChange={(e) => onChange({ choice: opt.value, text: e.target.value })}
 />
 )}
 </div>
 </label>
 );
 })}
 </div>
 );
}

function ListControl({
 field,
 value,
 onChange,
 intakeId,
 disabled,
}: {
 field: IntakeField;
 value: any;
 onChange: (v: any) => void;
 intakeId: string;
 disabled?: boolean;
}) {
 const { t } = useTranslation("intake");
 const items: any[] = Array.isArray(value) ? value : [];
 const item = field.item;
 const min = field.min_items ?? 0;
 const max = field.max_items ?? 999;

 const emptyItem = () => {
 if (!item) return "";
 if ("type" in item && item.type === "object") {
 const o: Record<string, any> = {};
 (item as any).fields.forEach((f: IntakeField) => (o[f.key] = ""));
 return o;
 }
 return "";
 };

 const update = (i: number, v: any) => {
 const next = [...items];
 next[i] = v;
 onChange(next);
 };

 const remove = (i: number) => {
 const next = items.filter((_, idx) => idx !== i);
 onChange(next);
 };

 const add = () => onChange([...items, emptyItem()]);

 return (
 <div className="space-y-3">
 {items.map((it, i) => (
 <div key={i} className="border border-ink/10 bg-paper2/50 p-4">
 <div className="mb-2 flex items-center justify-between">
 <span className="text-xs font-medium uppercase tracking-wide text-ink/60">
 #{i + 1}
 </span>
 {!disabled && items.length > min && (
 <button
 type="button"
 onClick={() => remove(i)}
 className="text-sm text-ink/40 hover:text-red-600"
 >
 ×
 </button>
 )}
 </div>
 {item && "type" in item && item.type === "object" ? (
 <div className="space-y-3">
 {(item as any).fields.map((sub: IntakeField) => (
 <FieldRenderer
 key={sub.key}
 field={sub}
 value={it?.[sub.key] ?? ""}
 onChange={(v) => update(i, { ...it, [sub.key]: v })}
 intakeId={intakeId}
 disabled={disabled}
 />
 ))}
 </div>
 ) : (
 <FieldRenderer
 field={{ ...(item as IntakeField), label: (item as IntakeField).label || t("field.itemFallback") }}
 value={it}
 onChange={(v) => update(i, v)}
 intakeId={intakeId}
 disabled={disabled}
 />
 )}
 </div>
 ))}
 {!disabled && items.length < max && (
 <button
 type="button"
 onClick={add}
 className="border border-dashed border-ink/10 px-4 py-2 text-sm font-medium text-ink/60 hover:border-ink/30 hover:text-ink"
 >
 {t("field.addItem")}
 </button>
 )}
 </div>
 );
}

function FileControl({
 field,
 value,
 onChange,
 intakeId,
 multi,
 disabled,
 onDeferRemove,
}: {
 field: IntakeField;
 value: any;
 onChange: (v: any) => void;
 intakeId: string;
 multi: boolean;
 disabled?: boolean;
 onDeferRemove?: (paths: string[]) => void;
}) {
 const { t } = useTranslation("intake");
 const [uploading, setUploading] = useState<number | null>(null);
 // The server authors the stored key (D-05); the browser only tags a category.
 // Audio-accept fields land under "audio" (they seed intake_sources), all other
 // client attachments under "attachments".
 // WR-03: classify audio via an EXPLICIT extension set mirroring the backend allowlist
 // (backend/app/storage/keys.py ALLOWED_EXT) — the old ".mp" prefix wrongly matched
 // .mp4 (video) and ".aac" was never in the server allowlist, so the picker implied a
 // file the server then rejected with 415. Keep the server authoritative.
 const AUDIO_EXTS = new Set([".m4a", ".mp3", ".wav", ".webm", ".ogg"]);
 const isAudioField =
 Array.isArray(field.accept) &&
 field.accept.length > 0 &&
 field.accept.every((a) => {
 const t = a.toLowerCase();
 return t.startsWith("audio/") || AUDIO_EXTS.has(t);
 });
 const category = isAudioField ? "audio" : "attachments";

 const files: any[] = multi ? (Array.isArray(value) ? value : []) : value ? [value] : [];
 const acceptOnlyPdf =
 Array.isArray(field.accept) &&
 field.accept.length === 1 &&
 field.accept[0].toLowerCase() === ".pdf";
 const useSlots = multi && (field.max_files ?? 0) > 0 && (field.max_files ?? 0) <= 5;

 // WR-04: destructive server-side deletes are DEFERRED to the parent's save when
 // onDeferRemove is provided (edit-mode draft) — a cancel then leaves the stored object
 // intact. Without it (client save-as-you-go), fire immediately but AWAIT and surface a
 // toast on failure instead of the old fire-and-forget `void`.
 const removeStoredObject = async (path: string) => {
 if (onDeferRemove) {
 onDeferRemove([path]);
 return;
 }
 const res = await storage.removeFile({ intakeId, paths: [path] });
 if (!res.success) {
 toast.error(t("field.removeFailed", { error: res.error }));
 }
 };

 const uploadOne = async (f: File): Promise<any | null> => {
 if (acceptOnlyPdf && !f.name.toLowerCase().endsWith(".pdf")) {
 toast.error(t("field.onlyPdf"));
 return null;
 }
 if (field.max_size_mb && f.size > field.max_size_mb * 1024 * 1024) {
 toast.error(t("field.tooLarge", { name: f.name, max: field.max_size_mb }));
 return null;
 }
 const res = await storage.uploadFile({
 intakeId,
 file: f,
 filename: f.name,
 category,
 contentType: f.type || undefined,
 });
 if (!res.success) {
 toast.error(t("field.uploadFailed", { error: res.error }));
 return null;
 }
 return {
 path: res.data.path,
 filename: f.name,
 size: f.size,
 uploaded_at: res.data.uploaded_at ?? new Date().toISOString(),
 };
 };

 const handleSlot = async (slotIndex: number, selected: FileList | null, replace: boolean) => {
 if (!selected || !selected[0]) return;
 setUploading(slotIndex);
 try {
 const uploaded = await uploadOne(selected[0]);
 if (!uploaded) return;
 const next = [...files];
 if (replace && next[slotIndex]?.path) {
 await removeStoredObject(next[slotIndex].path);
 }
 next[slotIndex] = uploaded;
 onChange(next.filter(Boolean));
 } finally {
 setUploading(null);
 }
 };

 const handleMulti = async (selected: FileList | null) => {
 if (!selected) return;
 const list = Array.from(selected);
 if (multi && field.max_files && files.length + list.length > field.max_files) {
 toast.error(t("field.maxFiles", { max: field.max_files }));
 return;
 }
 setUploading(-1);
 try {
 const uploaded: any[] = [];
 for (const f of list) {
 const u = await uploadOne(f);
 if (u) uploaded.push(u);
 }
 if (multi) onChange([...files, ...uploaded]);
 else if (uploaded[0]) onChange(uploaded[0]);
 } finally {
 setUploading(null);
 }
 };

 const removeFile = async (idx: number) => {
 const f = files[idx];
 if (f?.path) {
 await removeStoredObject(f.path);
 }
 if (multi) {
 onChange(files.filter((_, i) => i !== idx));
 } else {
 onChange(null);
 }
 };

 if (useSlots && !disabled) {
 const max = field.max_files ?? 5;
 const slots = Array.from({ length: max });
 const fmtSize = (n?: number) => {
 if (!n) return "";
 const u = ["B", "KB", "MB", "GB"];
 const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
 return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
 };
 return (
 <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
 {slots.map((_, i) => {
 const f = files[i];
 const busy = uploading === i;
 return (
 <div
 key={i}
 className={
 "border p-3 " +
 (f
 ? "border-ink/10 bg-paper"
 : "border-2 border-dashed border-ink/10 bg-paper2/50")
 }
 >
 <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-ink/60">
 {t("field.slot", { index: i + 1 })}
 </div>
 {f ? (
 <div>
 <div className="truncate text-sm font-medium text-ink">{f.filename}</div>
 <div className="text-xs text-ink/60">{fmtSize(f.size)}</div>
 <div className="mt-2 flex gap-2">
 <label className="inline-flex cursor-pointer items-center border border-ink/10 bg-paper px-2.5 py-1 text-xs font-medium text-ink/70 hover:border-ink/30">
 {busy ? t("field.busy") : t("field.replace")}
 <input
 type="file"
 className="hidden"
 accept={field.accept?.join(",")}
 onChange={(e) => handleSlot(i, e.target.files, true)}
 disabled={busy}
 />
 </label>
 <button
 type="button"
 onClick={() => removeFile(i)}
 className="border border-ink/10 px-2.5 py-1 text-xs font-medium text-ink/60 hover:border-red-300 hover:text-red-600"
 >
 {t("field.remove")}
 </button>
 </div>
 </div>
 ) : (
 <label className="flex cursor-pointer items-center justify-center py-3 text-sm font-medium text-ink/60 hover:text-ink">
 {busy ? t("field.uploading") : t("field.choosePdf")}
 <input
 type="file"
 className="hidden"
 accept={field.accept?.join(",")}
 onChange={(e) => handleSlot(i, e.target.files, false)}
 disabled={busy}
 />
 </label>
 )}
 </div>
 );
 })}
 </div>
 );
 }

 return (
 <div className="space-y-2">
 {files.length > 0 && (
 <ul className="space-y-1">
 {files.map((f, i) => (
 <li
 key={i}
 className="flex items-center justify-between border border-ink/10 bg-paper px-3 py-2 text-sm"
 >
 <span className="truncate text-ink/70">{f.filename}</span>
 {!disabled && (
 <button
 type="button"
 onClick={() => removeFile(i)}
 className="ml-3 text-xs text-ink/40 hover:text-red-600"
 >
 {t("field.removeLong")}
 </button>
 )}
 </li>
 ))}
 </ul>
 )}
 {!disabled && (multi || files.length === 0) && (
 <div>
 <label className="inline-flex cursor-pointer items-center border border-ink/10 bg-paper px-4 py-2 text-sm font-medium text-ink/70 hover:border-ink/30">
 {uploading !== null ? t("field.uploading") : t("field.chooseFile")}
 <input
 type="file"
 className="hidden"
 multiple={multi}
 accept={field.accept?.join(",")}
 onChange={(e) => handleMulti(e.target.files)}
 disabled={uploading !== null}
 />
 </label>
 </div>
 )}
 </div>
 );
}

function DownloadControl({ field, intakeId }: { field: IntakeField; intakeId: string }) {
 const { t } = useTranslation("intake");
 const [loading, setLoading] = useState(false);
 const handleClick = async () => {
 if (!field.storage_path) return;
 // Shared template assets (e.g. "templates/NDA/…") are NOT intake-scoped — the
 // space-scoped signed-URL seam rightly 404s them (D-05/D-08). Serve them from the
 // vite static root instead (frontend/public/templates → /templates). A missing file
 // surfaces the browser's own 404; do NOT toast a false storage error for these.
 if (field.storage_path.startsWith("templates/")) {
 window.open("/" + field.storage_path, "_blank");
 return;
 }
 setLoading(true);
 try {
 const res = await storage.signedDownloadUrl({
 intakeId,
 path: field.storage_path,
 expiresIn: 300,
 });
 if (!res.success) {
 toast.error(t("display.downloadFailed"));
 return;
 }
 window.open(res.data.url, "_blank");
 } finally {
 setLoading(false);
 }
 };
 return (
 <button
 type="button"
 onClick={handleClick}
 disabled={loading}
 className="border border-ink/10 bg-paper px-4 py-2 text-sm font-medium text-ink/70 hover:border-ink/30"
 >
 {loading ? t("field.loading") : t("field.download")}
 </button>
 );
}
