import { useState } from "react";
import { format } from "date-fns";
import { nl } from "date-fns/locale";
import { Download } from "lucide-react";
import { toast } from "sonner";
import type { IntakeField } from "@/lib/intake-types";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

type Props = {
 field: IntakeField;
 value: unknown;
 editedByClient?: boolean;
 clientEditedAt?: string | null;
};

function isEmpty(v: unknown): boolean {
 if (v === null || v === undefined) return true;
 if (typeof v === "string" && v.trim() === "") return true;
 if (Array.isArray(v) && v.length === 0) return true;
 if (typeof v === "object" && !Array.isArray(v) && v !== null) {
 if ("choice" in (v as Record<string, unknown>)) {
 return !(v as { choice?: string }).choice;
 }
 return Object.keys(v as object).length === 0;
 }
 return false;
}

function formatDate(d: string) {
 try {
 return format(new Date(d), "dd MMM yyyy", { locale: nl });
 } catch {
 return d;
 }
}

export function formatEditedAt(d: string) {
  try {
    const date = new Date(d);
    const day = new Intl.DateTimeFormat("nl-BE", {
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(date);
    const time = new Intl.DateTimeFormat("nl-BE", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
    return `${day} · ${time}`;
  } catch {
    return d;
  }
}

function formatBytes(n: number) {
 if (!n) return "0 B";
 const u = ["B", "KB", "MB", "GB"];
 const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
 return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

export function FieldDisplay({ field, value, editedByClient, clientEditedAt }: Props) {
 if (field.type === "download") return null;

 const empty = isEmpty(value);
 if (empty && !field.required) {
 return null;
 }
 if (empty && field.required) {
 return (
 <Row label={field.label} required editedByClient={editedByClient} clientEditedAt={clientEditedAt}>
 <span className="font-medium" style={{ color: "#FF2D87" }}>— ontbreekt</span>
 </Row>
 );
 }

 return (
 <Row label={field.label} required={field.required} editedByClient={editedByClient} clientEditedAt={clientEditedAt}>
 <ValueRenderer field={field} value={value} />
 </Row>
 );
}

export function isFieldDisplayEmpty(field: IntakeField, value: unknown): boolean {
 if (field.type === "download") return true;
 return isEmpty(value) && !field.required;
}

function Row({
 label,
 required,
 children,
 editedByClient,
 clientEditedAt,
}: {
 label: string;
 required?: boolean;
 children: React.ReactNode;
 editedByClient?: boolean;
 clientEditedAt?: string | null;
}) {
 return (
 <div className="grid grid-cols-1 gap-x-8 gap-y-1 border-b border-ink/10 py-4 last:border-b-0 sm:grid-cols-[260px_1fr]">
 <dt className="font-sans text-sm font-normal text-ink/70">
 {label}
 {required && <span className="ml-1 text-ink/40">*</span>}
 </dt>
 <dd className="font-sans text-ink">
 <div>{children}</div>
 {editedByClient && (
 <div className="mt-1 font-sans text-xs font-normal text-ink/60">
 Laatst gewijzigd door klant
 {clientEditedAt ? ` · ${formatEditedAt(clientEditedAt)}` : ""}
 </div>
 )}
 </dd>
 </div>
 );
}

function ValueRenderer({ field, value }: { field: IntakeField; value: unknown }) {
 switch (field.type) {
 case "text":
 case "email":
 case "tel":
 return <span>{String(value)}</span>;
 case "longtext":
 return <p className="whitespace-pre-wrap">{String(value)}</p>;
 case "date":
 return <span>{formatDate(String(value))}</span>;
 case "select":
 case "radio": {
 const v = value as string | { choice: string; text?: string };
 const choice = typeof v === "string" ? v : v.choice;
 const opt = field.options?.find((o) => o.value === choice);
 const label = opt?.label ?? choice;
 if (typeof v === "object" && v.choice === "other") {
 return <span>Anders: {v.text || "—"}</span>;
 }
 return <span>{label}</span>;
 }
 case "list": {
 const items = (value as unknown[]) ?? [];
 const item = field.item;
 const isObject = item && "type" in item && (item as { type?: string }).type === "object";
 if (isObject) {
 const subFields = (item as unknown as { fields: IntakeField[] }).fields;
 const textKey = subFields.find((sf) => sf.key === "text" || sf.type === "longtext")?.key;
 return (
 <div className="space-y-4">
 {items.map((it, i) => {
 const obj = (it as Record<string, unknown>) ?? {};
 const text = textKey ? (obj[textKey] as string | undefined) : undefined;
 const kind = obj["kind"] as string | undefined;
 const rationale = obj["rationale"] as string | undefined;
 if (text !== undefined) {
 return (
 <div key={i} className="flex gap-3">
 <span className="font-mono text-xs uppercase tracking-wider text-ink/60 pt-0.5">
 V{i + 1}.
 </span>
 <div className="flex-1 space-y-1">
 <div className="font-sans text-ink">{text}</div>
 {kind && (
 <div className="font-sans text-sm text-ink/60">
 Type: {kind}
 </div>
 )}
 {rationale && (
 <div className="font-sans text-sm italic text-ink/60">{rationale}</div>
 )}
 </div>
 </div>
 );
 }
 return (
 <div key={i} className="space-y-1">
 {subFields.map((sf) => (
 <FieldDisplay
 key={sf.key}
 field={sf}
 value={obj?.[sf.key]}
 />
 ))}
 </div>
 );
 })}
 </div>
 );
 }
 return (
 <ul className="list-disc space-y-1 pl-5">
 {items.map((it, i) => (
 <li key={i}>{String(it)}</li>
 ))}
 </ul>
 );
 }
 case "file": {
 return <FileRow file={value as FileMeta} bucket={field.storage_bucket} />;
 }
 case "files": {
 const arr = (value as FileMeta[]) ?? [];
 return (
 <ul className="space-y-1.5">
 {arr.map((f, i) => (
 <li key={i}>
 <FileRow file={f} bucket={field.storage_bucket} />
 </li>
 ))}
 </ul>
 );
 }
 case "proposal_list": {
 const items = (value as Array<{ text?: string; rationale?: string; approved?: boolean }>) ?? [];
 if (!Array.isArray(items) || items.length === 0) {
 return <span className="text-ink/40">—</span>;
 }
 return (
 <div className="space-y-4">
 {items.map((item, idx) => (
 <div key={idx} className="flex items-start gap-3">
 <div
 className={cn(
 "mt-1 h-3 w-3 flex-shrink-0 border border-ink",
 item.approved ? "bg-ink" : "bg-paper",
 )}
 >
 {item.approved && (
 <svg className="h-full w-full text-paper" viewBox="0 0 12 12">
 <path d="M2 6 L5 9 L10 3" stroke="currentColor" strokeWidth="2" fill="none" />
 </svg>
 )}
 </div>
 <div className="flex-1 space-y-1">
 <div className="font-sans text-ink">{item.text}</div>
 {item.rationale && (
 <div className="font-sans text-sm italic text-ink/60">{item.rationale}</div>
 )}
 <div className="font-mono text-xs uppercase tracking-wider">
 {item.approved ? (
 <span className="text-ink/70">OPGENOMEN IN RESEARCH</span>
 ) : (
 <span className="text-ink/40">NIET OPGENOMEN</span>
 )}
 </div>
 </div>
 </div>
 ))}
 </div>
 );
 }
 default:
 return <span className="text-ink/40">—</span>;
 }
}

type FileMeta = { path: string; filename: string; size?: number; uploaded_at?: string };

function FileRow({ file, bucket }: { file: FileMeta | undefined; bucket?: string }) {
 const [busy, setBusy] = useState(false);
 if (!file?.path) return <span className="text-ink/40">—</span>;
 const open = async () => {
 if (!supabase || !bucket) {
 toast.error("Storage niet geconfigureerd");
 return;
 }
 setBusy(true);
 try {
 const { data, error } = await supabase.storage.from(bucket).createSignedUrl(file.path, 300);
 if (error || !data) {
 toast.error("Download mislukt");
 return;
 }
 window.open(data.signedUrl, "_blank");
 } finally {
 setBusy(false);
 }
 };
 return (
 <div className="flex items-center justify-between gap-3">
 <div className="min-w-0 flex flex-wrap items-baseline gap-x-2">
 <span className="truncate font-sans text-ink">{file.filename}</span>
 <span className="font-mono text-xs uppercase tracking-wider text-ink/60">
 {file.size ? `· ${formatBytes(file.size)}` : ""}
 {file.uploaded_at ? ` · ${formatDate(file.uploaded_at)}` : ""}
 </span>
 </div>
 <button
 type="button"
 onClick={open}
 disabled={busy}
 className={cn(
 "inline-flex shrink-0 items-center gap-1 border border-ink bg-paper px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5",
 busy && "opacity-50",
 )}
 >
 <Download className="h-3.5 w-3.5" />
 Open
 </button>
 </div>
 );
}
