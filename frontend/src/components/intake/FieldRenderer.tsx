import { useState } from "react";
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
};

const inputCls =
 "w-full border border-ink bg-paper2 px-3.5 py-2.5 text-[15px] text-ink placeholder:text-ink/40 focus:outline-none focus:border-2 focus:px-[calc(0.875rem-1px)] focus:py-[calc(0.625rem-1px)] disabled:bg-paper2 disabled:text-ink/60";

export function FieldRenderer(props: Props) {
 const { field, value, onChange, error, disabled } = props;

 return (
 <div className="space-y-2">
 <div>
 <label className="block font-mono text-xs uppercase tracking-wider text-ink">
 {field.label}
 {field.required && <span className="ml-1 text-red-500">*</span>}
 </label>
 {field.help && (
 <p className="mt-1 text-xs text-ink/60">{field.help}</p>
 )}
 </div>
 <FieldControl {...props} />
 {field.examples && (field.examples.good || field.examples.bad) && (
 <details className="text-xs text-ink/60">
 <summary className="cursor-pointer select-none hover:text-ink/70">
 ▶ Voorbeelden
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

function FieldControl({ field, value, onChange, intakeId, disabled }: Props) {
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
 <option value="">— Kies —</option>
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
 return <FileControl field={field} value={value} onChange={onChange} intakeId={intakeId} multi={false} disabled={disabled} />;
 case "files":
 return <FileControl field={field} value={value} onChange={onChange} intakeId={intakeId} multi={true} disabled={disabled} />;
 case "download":
 return <DownloadControl field={field} />;
 case "proposal_list":
 return <ProposalListControl value={value} onChange={onChange} disabled={disabled} />;
 default:
 return <p className="text-xs text-red-600">Unsupported field type: {field.type}</p>;
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
 const items: Array<{ text: string; rationale?: string; approved?: boolean }> = Array.isArray(value)
 ? value
 : [];
 if (items.length === 0) {
 return <p className="text-sm text-ink/60">Geen extra voorstellen.</p>;
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
 <div className="mt-1 text-xs text-ink/60">Opnemen in research?</div>
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
 placeholder="Specificeer…"
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
 field={{ ...(item as IntakeField), label: (item as IntakeField).label || "Item" }}
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
 + Voeg toe
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
}: {
 field: IntakeField;
 value: any;
 onChange: (v: any) => void;
 intakeId: string;
 multi: boolean;
 disabled?: boolean;
}) {
 const [uploading, setUploading] = useState<number | null>(null);
 const bucket = field.storage_bucket ?? "nestor-uploads";
 const prefix = (field.storage_path_prefix ?? `intakes/{intake_id}/${field.key}`).replace(
 "{intake_id}",
 intakeId,
 );

 const files: any[] = multi ? (Array.isArray(value) ? value : []) : value ? [value] : [];
 const acceptOnlyPdf =
 Array.isArray(field.accept) &&
 field.accept.length === 1 &&
 field.accept[0].toLowerCase() === ".pdf";
 const useSlots = multi && (field.max_files ?? 0) > 0 && (field.max_files ?? 0) <= 5;

 const uploadOne = async (f: File): Promise<any | null> => {
 if (acceptOnlyPdf && !f.name.toLowerCase().endsWith(".pdf")) {
 toast.error(
 "Alleen PDF bestanden toegestaan. Sla je PowerPoint/Word/Excel eerst op als PDF.",
 );
 return null;
 }
 if (field.max_size_mb && f.size > field.max_size_mb * 1024 * 1024) {
 toast.error(`${f.name} is te groot (max ${field.max_size_mb}MB)`);
 return null;
 }
 const path = `${prefix}/${crypto.randomUUID()}-${f.name}`;
 const res = await storage.uploadFile({
 intakeId,
 bucket,
 path,
 file: f,
 filename: f.name,
 contentType: f.type || undefined,
 });
 if (!res.success) {
 toast.error(`Upload mislukt: ${res.error}`);
 return null;
 }
 return {
 path: res.data.path ?? path,
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
 void storage.removeFile({ bucket, paths: [next[slotIndex].path] });
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
 toast.error(`Maximum ${field.max_files} bestanden.`);
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
 void storage.removeFile({ bucket, paths: [f.path] });
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
 Slot {i + 1}
 </div>
 {f ? (
 <div>
 <div className="truncate text-sm font-medium text-ink">{f.filename}</div>
 <div className="text-xs text-ink/60">{fmtSize(f.size)}</div>
 <div className="mt-2 flex gap-2">
 <label className="inline-flex cursor-pointer items-center border border-ink/10 bg-paper px-2.5 py-1 text-xs font-medium text-ink/70 hover:border-ink/30">
 {busy ? "Bezig…" : "Vervang"}
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
 Verwijder
 </button>
 </div>
 </div>
 ) : (
 <label className="flex cursor-pointer items-center justify-center py-3 text-sm font-medium text-ink/60 hover:text-ink">
 {busy ? "Uploaden…" : "+ PDF kiezen"}
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
 Verwijderen
 </button>
 )}
 </li>
 ))}
 </ul>
 )}
 {!disabled && (multi || files.length === 0) && (
 <div>
 <label className="inline-flex cursor-pointer items-center border border-ink/10 bg-paper px-4 py-2 text-sm font-medium text-ink/70 hover:border-ink/30">
 {uploading !== null ? "Uploaden…" : "Bestand kiezen"}
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

function DownloadControl({ field }: { field: IntakeField }) {
 const [loading, setLoading] = useState(false);
 const handleClick = async () => {
 if (!field.storage_bucket || !field.storage_path) return;
 setLoading(true);
 try {
 const res = await storage.signedDownloadUrl({
 bucket: field.storage_bucket,
 path: field.storage_path,
 expiresIn: 300,
 });
 if (!res.success) {
 toast.error("Download mislukt");
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
 {loading ? "Laden…" : "Download"}
 </button>
 );
}
