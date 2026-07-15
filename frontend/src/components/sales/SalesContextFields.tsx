import { useState, useEffect } from "react";
import {
  MEETING_TYPE_OPTIONS,
  DEAL_STAGE_OPTIONS,
  KLANT_TYPE_OPTIONS,
  INDUSTRY_VERTICAL_SUGGESTIONS,
} from "@/lib/salesLabels";

export type SalesContextValues = {
  meeting_type: string;
  deal_stage: string;
  klant_type: string;
  industry_vertical: string;
};

export const EMPTY_SALES_CONTEXT: SalesContextValues = {
  meeting_type: "",
  deal_stage: "",
  klant_type: "",
  industry_vertical: "",
};

const selectCls =
  "w-full border border-ink bg-paper2 px-3 py-2 text-sm focus:outline-none focus:border-ink";

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-1 block">
      {children}
    </label>
  );
}

export function SalesContextFields({
  values,
  onChange,
  variant = "intake",
}: {
  values: SalesContextValues;
  onChange: (next: SalesContextValues) => void;
  variant?: "intake" | "admin";
}) {
  // Decide initial dropdown state for the industry vertical: if the stored
  // value isn't in our suggestion list (and isn't empty), we're in "other" mode.
  const isSuggestion = (v: string) =>
    !v || INDUSTRY_VERTICAL_SUGGESTIONS.includes(v);
  const [industryMode, setIndustryMode] = useState<"suggestion" | "other">(
    isSuggestion(values.industry_vertical) ? "suggestion" : "other",
  );

  useEffect(() => {
    setIndustryMode(
      isSuggestion(values.industry_vertical) ? "suggestion" : "other",
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (k: keyof SalesContextValues, v: string) =>
    onChange({ ...values, [k]: v });

  return (
    <section className={variant === "admin" ? "" : "mb-2"}>
      {variant === "intake" && (
        <>
          <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-1">
            Context & nadruk
          </div>
          <h3 className="font-serif text-xl mb-2">
            Wat voor gesprek wordt dit?
          </h3>
          <p className="text-sm text-ink/60 mb-4">
            Deze antwoorden bepalen welke onderdelen van de battlecard extra
            aandacht krijgen. Optioneel — laten staan kan ook.
          </p>
        </>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <FieldLabel>Type meeting</FieldLabel>
          <select
            value={values.meeting_type}
            onChange={(e) => set("meeting_type", e.target.value)}
            className={selectCls}
          >
            <option value="">Kies een type…</option>
            {MEETING_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <FieldLabel>Deal stage</FieldLabel>
          <select
            value={values.deal_stage}
            onChange={(e) => set("deal_stage", e.target.value)}
            className={selectCls}
          >
            <option value="">Kies stage…</option>
            {DEAL_STAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <FieldLabel>Klantsoort</FieldLabel>
          <select
            value={values.klant_type}
            onChange={(e) => set("klant_type", e.target.value)}
            className={selectCls}
          >
            <option value="">Kies…</option>
            {KLANT_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <FieldLabel>Industry vertical</FieldLabel>
          <select
            value={
              industryMode === "other"
                ? "__other__"
                : values.industry_vertical
            }
            onChange={(e) => {
              const v = e.target.value;
              if (v === "__other__") {
                setIndustryMode("other");
                set("industry_vertical", "");
              } else {
                setIndustryMode("suggestion");
                set("industry_vertical", v);
              }
            }}
            className={selectCls}
          >
            <option value="">Kies sector…</option>
            {INDUSTRY_VERTICAL_SUGGESTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
            <option value="__other__">Andere…</option>
          </select>
          {industryMode === "other" && (
            <input
              type="text"
              value={values.industry_vertical}
              onChange={(e) => set("industry_vertical", e.target.value)}
              placeholder="bv. Defense / Aerospace"
              className={`${selectCls} mt-2`}
            />
          )}
        </div>
      </div>
    </section>
  );
}
