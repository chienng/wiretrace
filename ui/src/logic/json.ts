export type JsonResult = { ok: true; value: unknown } | { ok: false };

/** Parses only text that looks like a JSON object or array. */
export function tryParseJson(text: string): JsonResult {
  const t = text.trim();
  if (!(t.startsWith('{') || t.startsWith('['))) return { ok: false };
  try {
    return { ok: true, value: JSON.parse(t) as unknown };
  } catch {
    return { ok: false };
  }
}
