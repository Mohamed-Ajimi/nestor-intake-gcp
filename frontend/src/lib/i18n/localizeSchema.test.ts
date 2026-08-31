import { describe, it, expect } from "vitest";
import { localizeSchema, pick } from "@/lib/i18n/localizeSchema";
import type { LocalizedIntakeSchema } from "@/lib/intake-types";

// localizeSchema flattens the multi-locale SOURCE schema (label/title/... as
// { nl, fr?, en? }) to the RESOLVED scalar shape at load time, with nl as the
// guaranteed fallback for any missing variant (D-05). These cases pin the five
// behaviors the plan requires.

/** A compact source schema exercising sections, nested list fields, and options. */
function makeSchema(): LocalizedIntakeSchema {
  return {
    schema_version: "1.0",
    title: { nl: "Titel", fr: "Titre", en: "Title" },
    subtitle: { nl: "Ondertitel", fr: "Sous-titre" }, // no en → falls back to nl
    sections: [
      {
        id: "s1",
        title: { nl: "Sectie", fr: "Section", en: "Section" },
        description: { nl: "Beschrijving", fr: "Description", en: "Description" },
        fields: [
          {
            key: "f_text",
            type: "text",
            label: { nl: "Naam", fr: "Nom", en: "Name" },
            help: { nl: "Hulp", fr: "Aide", en: "Help" },
            placeholder: { nl: "bv. Acme", fr: "p.ex. Acme", en: "e.g. Acme" },
          },
          {
            key: "f_select",
            type: "select",
            label: { nl: "Type", fr: "Type", en: "Type" },
            options: [
              { value: "a", label: { nl: "Optie A", fr: "Option A", en: "Option A" } },
              {
                value: "b",
                label: { nl: "Optie B", fr: "Option B" }, // no en → nl fallback
                description: { nl: "Beschrijving B", fr: "Description B", en: "Description B" },
              },
            ],
          },
          {
            key: "f_list",
            type: "list",
            label: { nl: "Lijst", fr: "Liste", en: "List" },
            item: {
              type: "object",
              fields: [
                {
                  key: "sub",
                  type: "longtext",
                  label: { nl: "Subveld", fr: "Sous-champ", en: "Subfield" },
                },
              ],
            },
          },
          {
            key: "f_scalar",
            type: "text",
            // Already-scalar legacy string — must pass through unchanged (defensive).
            label: "Al scalar",
          },
        ],
      },
    ],
    submit: {
      label: { nl: "Versturen", fr: "Envoyer", en: "Send" },
      confirmation_title: { nl: "Bedankt", fr: "Merci", en: "Thanks" },
      confirmation_message: { nl: "Ontvangen", fr: "Reçu", en: "Received" },
    },
  };
}

describe("localizeSchema", () => {
  it("resolves every display string to the fr variant", () => {
    const s = localizeSchema(makeSchema(), "fr");
    expect(s.title).toBe("Titre");
    expect(s.sections[0].title).toBe("Section");
    expect(s.sections[0].description).toBe("Description");
    const field = s.sections[0].fields[0];
    expect(field.label).toBe("Nom");
    expect(field.help).toBe("Aide");
    expect(field.placeholder).toBe("p.ex. Acme");
    expect(s.sections[0].fields[1].options?.[0].label).toBe("Option A");
    // nested list item field
    const item = s.sections[0].fields[2].item as { fields: { label: string }[] };
    expect(item.fields[0].label).toBe("Sous-champ");
    expect(s.submit.label).toBe("Envoyer");
  });

  it("falls back to nl when the en variant is missing (D-05)", () => {
    const s = localizeSchema(makeSchema(), "en");
    // subtitle has no en variant → nl
    expect(s.subtitle).toBe("Ondertitel");
    // option b label has no en variant → nl
    expect(s.sections[0].fields[1].options?.[1].label).toBe("Optie B");
    // but option b description DOES have en
    expect(s.sections[0].fields[1].options?.[1].description).toBe("Description B");
    // present-en strings still resolve to en
    expect(s.title).toBe("Title");
  });

  it("falls back to nl for every string on an unknown language", () => {
    const s = localizeSchema(makeSchema(), "de");
    expect(s.title).toBe("Titel");
    expect(s.subtitle).toBe("Ondertitel");
    expect(s.sections[0].title).toBe("Sectie");
    expect(s.sections[0].fields[0].label).toBe("Naam");
    expect(s.sections[0].fields[1].options?.[0].label).toBe("Optie A");
    expect(s.submit.confirmation_message).toBe("Ontvangen");
  });

  it("passes an already-scalar string through unchanged (defensive)", () => {
    const s = localizeSchema(makeSchema(), "fr");
    expect(s.sections[0].fields[3].label).toBe("Al scalar");
  });

  it("leaves no raw {nl,fr,en} object anywhere in the resolved schema", () => {
    const s = localizeSchema(makeSchema(), "fr");
    const seen = JSON.stringify(s);
    // A locale-object would serialize its keys; assert none survive.
    expect(seen).not.toContain('"nl"');
    expect(seen).not.toContain('"fr"');
    expect(seen).not.toContain('"en"');
  });
});

// `pick` was exported by quick task 260831-lm4 so the FOUR surfaces that render
// AI-GENERATED strings (FieldRenderer, FieldDisplay, AIReviewPanel, NestorBriefingPDF)
// share ONE resolution rule with the schema pass instead of growing their own. These
// pin the behaviours those callers depend on.
describe("pick (the shared resolver for AI-generated localized strings)", () => {
  it("passes a plain string through unchanged — OLD INTAKES ARE NOT MIGRATED", () => {
    expect(pick("Een vraag zonder vertalingen?", "fr")).toBe("Een vraag zonder vertalingen?");
    expect(pick("", "nl")).toBe("");
  });

  it("resolves a three-key AI object to the active language", () => {
    const value = { nl: "Nederlandse vraag", fr: "Question française", en: "English question" };
    expect(pick(value, "nl")).toBe("Nederlandse vraag");
    expect(pick(value, "fr")).toBe("Question française");
    expect(pick(value, "en")).toBe("English question");
    // Region-tagged locales resolve on the first two characters.
    expect(pick(value, "fr-BE")).toBe("Question française");
  });

  it("falls back to nl, then to any present variant, never to nothing", () => {
    const noEn = { nl: "Nederlands", fr: "Français" };
    expect(pick(noEn, "en")).toBe("Nederlands");
    expect(pick(noEn, "de")).toBe("Nederlands");
    // A model that dropped nl must still yield TEXT rather than undefined.
    expect(pick({ fr: "Seulement français" }, "en")).toBe("Seulement français");
  });

  it("returns undefined for null, undefined and non-localized objects", () => {
    expect(pick(null, "nl")).toBeUndefined();
    expect(pick(undefined, "nl")).toBeUndefined();
    expect(pick(42, "nl")).toBeUndefined();
    // THE GUARD THAT MATTERS: an arbitrary answer object is NOT a localized value.
    // If `pick` scanned every value it would return "Jan" here and the caller
    // (NestorBriefingPDF.asString) would print a name where a decision belongs.
    expect(pick({ name: "Jan", role: "CFO" }, "nl")).toBeUndefined();
    expect(pick({ choice: "other", text: "max 15 slides" }, "nl")).toBeUndefined();
  });

  it("never returns a stringified object", () => {
    const resolved = pick({ nl: "N", fr: "F", en: "E" }, "fr") ?? "";
    expect(resolved).not.toContain("{");
    expect(resolved).not.toContain("nl");
  });
});
