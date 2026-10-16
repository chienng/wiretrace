/** The `#flow=<id>` fragment from the menu bar's Show last error. */

export interface FlowLink {
  /** A listed flow to select, or null when the fragment names nothing we have. */
  id: string | null;
  /** True when the fragment was a flow link and should be removed. */
  clear: boolean;
}

/** What to do with the page's hash once the first load has its flows. */
export function flowLinkChoice(hash: string, ids: readonly string[]): FlowLink {
  const match = /^#flow=(.*)$/.exec(hash);
  if (!match) return { id: null, clear: false };
  let raw = match[1] ?? '';
  try {
    raw = decodeURIComponent(raw);
  } catch {
    // Keep the raw text; an undecodable id simply matches nothing.
  }
  const id = raw !== '' && ids.includes(raw) ? raw : null;
  return { id, clear: true };
}
