#!/usr/bin/env node
// frontend/scripts/i18n-audit.mjs
//
// Exhaustive i18n audit for the Nestor Intake frontend. No external deps (node:fs only).
// Run from frontend/:  node scripts/i18n-audit.mjs
//
// Four checks:
//   CHECK A — 3-way key parity across nl/fr/en per namespace           (HARD gate)
//   CHECK B — every literal single-arg t("key") resolves in all locales (HARD gate)
//   CHECK C — zero genuine two-arg i18n fallbacks t("key","Dutch")      (HARD gate)
//   CHECK D — hardcoded user-visible strings                            (advisory / WARN)
//
// Exit code: 1 if any HARD gate (A/B/C) fails, else 0. CHECK D never fails the build.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const ROOT = process.cwd();
const SRC = join(ROOT, "src");
const LOCALES_DIR = join(SRC, "locales");
const LOCALES = ["nl", "fr", "en"];
const NAMESPACES = ["admin", "auth", "common", "intake"];

// Directories/files under src/ excluded from the source scan (CHECK B/C/D).
const EXCLUDE_DIRS = new Set(["ui", "mock-backend", "locales"]);
const EXCLUDE_FILES = new Set(["routeTree.gen.ts"]);
const SRC_EXT = new Set([".ts", ".tsx"]);

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const rel = relative(SRC, full);
    const st = statSync(full);
    if (st.isDirectory()) {
      // exclude whole subtrees (ui/, mock-backend/, locales/)
      if (EXCLUDE_DIRS.has(name)) continue;
      walk(full, acc);
    } else {
      if (EXCLUDE_FILES.has(name)) continue;
      const dot = name.lastIndexOf(".");
      const ext = dot >= 0 ? name.slice(dot) : "";
      if (!SRC_EXT.has(ext)) continue;
      // skip the locales tree defensively (relative starts with locales/)
      if (rel.split(sep)[0] === "locales") continue;
      acc.push(full);
    }
  }
  return acc;
}

function flatten(obj, prefix = "", out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      flatten(v, key, out);
    } else {
      out[key] = v;
    }
  }
  return out;
}

function loadCatalog(locale, ns) {
  const p = join(LOCALES_DIR, locale, `${ns}.json`);
  return JSON.parse(readFileSync(p, "utf8"));
}

// line number of a char index
function lineOf(text, idx) {
  let line = 1;
  for (let i = 0; i < idx && i < text.length; i++) if (text[i] === "\n") line++;
  return line;
}

// ---------------------------------------------------------------------------
// load locales
// ---------------------------------------------------------------------------

// flat[locale][ns] = { dottedKey: value }
const flat = {};
for (const loc of LOCALES) {
  flat[loc] = {};
  for (const ns of NAMESPACES) {
    flat[loc][ns] = flatten(loadCatalog(loc, ns));
  }
}

// merged set of every dotted key across all namespaces of one locale
function mergedKeys(locale) {
  const s = new Set();
  for (const ns of NAMESPACES) for (const k of Object.keys(flat[locale][ns])) s.add(k);
  return s;
}

// ---------------------------------------------------------------------------
// CHECK A — 3-way key parity per namespace
// ---------------------------------------------------------------------------

function checkA() {
  const diffs = [];
  for (const ns of NAMESPACES) {
    const keySets = LOCALES.map((l) => new Set(Object.keys(flat[l][ns])));
    const union = new Set();
    keySets.forEach((s) => s.forEach((k) => union.add(k)));
    for (const key of union) {
      const missingIn = LOCALES.filter((_, i) => !keySets[i].has(key));
      if (missingIn.length > 0) {
        diffs.push({ ns, key, missingIn });
      }
    }
  }
  return diffs;
}

// ---------------------------------------------------------------------------
// scan source once, collecting t() calls
// ---------------------------------------------------------------------------

const files = walk(SRC);

// single-arg literal:  t("some.key")  — anchored on a non-word/non-dot char before t(
const RE_SINGLE = /[^.A-Za-z]t\(\s*"([^"]+)"\s*\)/g;
// two-arg literal:     t("some.key", "fallback")
const RE_TWO = /[^.A-Za-z]t\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)/g;
// dynamic key:         t(`...${...}...`)  — template literal first arg
const RE_DYNAMIC = /[^.A-Za-z]t\(\s*`([^`]*\$\{[^`]*)`/g;

// non-i18n two-arg denylist (jsPDF/headers/etc.) — belt-and-suspenders on top of the anchor
const TWO_ARG_DENY = /helvetica|content-type|application\/|multipart|text\/|charset/i;

const usedSingle = []; // { key, file, line }
const twoArg = []; // { key, fallback, file, line }
const dynamic = []; // { expr, file, line }

for (const file of files) {
  const text = readFileSync(file, "utf8");
  const relPath = relative(ROOT, file);

  let m;
  RE_SINGLE.lastIndex = 0;
  while ((m = RE_SINGLE.exec(text))) {
    const key = m[1];
    // Real i18n keys are dotted identifiers (word chars, dots, hyphens, optional `ns:`).
    // Anything with `<`, `>`, spaces, etc. is a doc/comment artifact, not a call — skip.
    if (!/^[\w.:$-]+$/.test(key)) continue;
    usedSingle.push({ key, file: relPath, line: lineOf(text, m.index) });
  }
  RE_TWO.lastIndex = 0;
  while ((m = RE_TWO.exec(text))) {
    const key = m[1];
    const fallback = m[2];
    if (TWO_ARG_DENY.test(key) || TWO_ARG_DENY.test(fallback)) continue;
    twoArg.push({ key, fallback, file: relPath, line: lineOf(text, m.index) });
  }
  RE_DYNAMIC.lastIndex = 0;
  while ((m = RE_DYNAMIC.exec(text))) {
    dynamic.push({ expr: m[1], file: relPath, line: lineOf(text, m.index) });
  }
}

// ---------------------------------------------------------------------------
// CHECK B — used-key coverage
// ---------------------------------------------------------------------------
// A key resolves if it is present (as a dotted key) in the merged catalog of a
// locale. It may be namespaced (`admin:foo.bar`) or bare (`foo.bar`, resolved
// against the component's useTranslation ns — we accept a match in ANY namespace).

function stripNs(key) {
  const colon = key.indexOf(":");
  return colon >= 0 ? key.slice(colon + 1) : key;
}

function checkB() {
  const merged = {};
  for (const loc of LOCALES) merged[loc] = mergedKeys(loc);
  const seen = new Set();
  const missing = [];
  for (const u of usedSingle) {
    const key = stripNs(u.key);
    // ignore anything that clearly is not a translation key (no dot AND not a known leaf)
    const dedupe = `${key}`;
    if (seen.has(dedupe)) continue;
    seen.add(dedupe);
    const missingIn = LOCALES.filter((loc) => !merged[loc].has(key));
    if (missingIn.length === LOCALES.length) {
      // present in NO locale — genuine miss (could be a false positive literal that
      // isn't actually a translation key; those are surfaced for human review)
      missing.push({ key, file: u.file, line: u.line, missingIn: "all" });
    } else if (missingIn.length > 0) {
      // present in some but not all — a parity miss (CHECK A also catches, but flag)
      missing.push({ key, file: u.file, line: u.line, missingIn: missingIn.join(",") });
    }
  }
  return missing;
}

// ---------------------------------------------------------------------------
// CHECK D — hardcoded user-visible strings (advisory)
// ---------------------------------------------------------------------------

// Dutch signal words inside string literals
const DUTCH_WORDS =
  /\b(van|het|naar|wordt|beschikbaar|mislukt|voltooid|bezig|geen|nog|verstuur|bekijk|antwoorden|vragen|onderzoek|klik)\b/i;

// literal string props we care about
const RE_PROP = /\b(title|placeholder|aria-label|alt)=("([A-Za-zÀ-ÿ][^"]*)")/g;
// JSX text node with 2+ letters not wrapped in {t(...)}
const RE_JSX_TEXT = />\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ ,.'’!?()–—-]{2,})\s*</g;

function checkD() {
  const hits = [];
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    const relPath = relative(ROOT, file);

    // (ii) literal string props
    let m;
    RE_PROP.lastIndex = 0;
    while ((m = RE_PROP.exec(text))) {
      const val = m[3];
      // skip obvious non-copy: single tokens that are clearly identifiers/urls
      if (/^https?:\/\//.test(val)) continue;
      hits.push({ kind: `prop:${m[1]}`, text: val, file: relPath, line: lineOf(text, m.index) });
    }

    // (iii) Dutch signal words in any double-quoted literal
    const RE_STR = /"([^"\n]{2,})"/g;
    let s;
    while ((s = RE_STR.exec(text))) {
      const val = s[1];
      if (DUTCH_WORDS.test(val)) {
        hits.push({ kind: "dutch", text: val, file: relPath, line: lineOf(text, s.index) });
      }
    }

    // (i) JSX text nodes not wrapped in {t(...)} — only .tsx files
    if (file.endsWith(".tsx")) {
      RE_JSX_TEXT.lastIndex = 0;
      while ((m = RE_JSX_TEXT.exec(text))) {
        const val = m[1].trim();
        // skip if this looks like it's part of {t(...)} (heuristic: preceded by })
        const before = text.slice(Math.max(0, m.index - 3), m.index);
        if (before.includes("}")) continue;
        // skip common html-ish or single-word non-copy tokens
        if (/^(true|false|null|undefined)$/i.test(val)) continue;
        hits.push({ kind: "jsx-text", text: val, file: relPath, line: lineOf(text, m.index) });
      }
    }
  }
  return hits;
}

// ---------------------------------------------------------------------------
// run + report
// ---------------------------------------------------------------------------

let hardFail = false;

console.log("═══════════════════════════════════════════════════════════════");
console.log(" i18n audit — Nestor Intake frontend");
console.log("═══════════════════════════════════════════════════════════════\n");

// CHECK A
const aDiffs = checkA();
console.log("── CHECK A: 3-way key parity (nl/fr/en) ──────────────────────");
if (aDiffs.length === 0) {
  console.log("  ✓ all namespaces key-consistent across nl/fr/en\n");
} else {
  hardFail = true;
  for (const d of aDiffs) {
    console.log(`  ✗ [${d.ns}] "${d.key}" missing in: ${d.missingIn.join(", ")}`);
  }
  console.log(`  → ${aDiffs.length} parity gap(s)\n`);
}

// CHECK B
const bMiss = checkB();
console.log("── CHECK B: used-key coverage (literal single-arg t()) ───────");
if (bMiss.length === 0) {
  console.log("  ✓ every literal t() key resolves in all locales\n");
} else {
  hardFail = true;
  for (const d of bMiss) {
    console.log(`  ✗ "${d.key}" (missing: ${d.missingIn}) — ${d.file}:${d.line}`);
  }
  console.log(`  → ${bMiss.length} unresolved key(s)\n`);
}

// dynamic-key allowlist (informational, never fails)
console.log("── CHECK B (info): dynamic-key allowlist (unresolvable) ──────");
if (dynamic.length === 0) {
  console.log("  (none)\n");
} else {
  const seen = new Set();
  for (const d of dynamic) {
    const line = `  • t(\`${d.expr}\`) — ${d.file}:${d.line}`;
    if (seen.has(d.expr)) continue;
    seen.add(d.expr);
    console.log(line);
  }
  console.log("");
}

// CHECK C
console.log("── CHECK C: genuine two-arg i18n fallbacks ───────────────────");
if (twoArg.length === 0) {
  console.log("  ✓ no genuine two-arg t('key','fallback') calls remain\n");
} else {
  hardFail = true;
  for (const d of twoArg) {
    console.log(`  ✗ t("${d.key}", "${d.fallback}") — ${d.file}:${d.line}`);
  }
  console.log(`  → ${twoArg.length} fallback(s)\n`);
}

// CHECK D
const dHits = checkD();
console.log("── CHECK D: hardcoded user-visible strings (ADVISORY) ────────");
if (dHits.length === 0) {
  console.log("  ✓ no hardcoded strings detected\n");
} else {
  for (const d of dHits) {
    console.log(`  ⚠ [${d.kind}] "${d.text}" — ${d.file}:${d.line}`);
  }
  console.log(`  → ${dHits.length} advisory hit(s) — review + fix or justify in SUMMARY\n`);
}

console.log("═══════════════════════════════════════════════════════════════");
if (hardFail) {
  console.log(" RESULT: FAIL — CHECK A/B/C must be clean (CHECK D is advisory)");
  console.log("═══════════════════════════════════════════════════════════════");
  process.exit(1);
} else {
  console.log(" RESULT: PASS — A/B/C clean" + (dHits.length ? ` (${dHits.length} CHECK D advisories)` : ""));
  console.log("═══════════════════════════════════════════════════════════════");
  process.exit(0);
}
