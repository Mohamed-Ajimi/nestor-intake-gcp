export const ANCHOR_PREFIX = "[ORIGINELE INTAKE-VRAAG";

export function isAnchorQuestion(q: { priority: number | null; question_text: string }): boolean {
  return (q.priority ?? 0) === 1 && (q.question_text ?? "").trimStart().startsWith(ANCHOR_PREFIX);
}

/** Strip the [ORIGINELE INTAKE-VRAAG...] prefix (optionally followed by ":" or "]") for display. */
export function stripAnchorPrefix(text: string): string {
  if (!text) return text;
  const t = text.trimStart();
  if (!t.startsWith(ANCHOR_PREFIX)) return text;
  // remove up to and including the first "]" plus an optional trailing ":" and whitespace
  const close = t.indexOf("]");
  if (close === -1) return text;
  let rest = t.slice(close + 1).replace(/^\s*:\s*/, "").trimStart();
  return rest;
}

export function displayQuestionText(q: { priority: number | null; question_text: string }): string {
  return isAnchorQuestion(q) ? stripAnchorPrefix(q.question_text) : q.question_text;
}
