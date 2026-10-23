import type { BreakpointEdits, FlowDetail, Headers, PausePhase } from '../types';

/** The same limits and texts as addons/wiretrace_ui.py; the server checks the edits again. */
export const HINT_S = 20;
export const GIVE_UP = 'Apps usually give up after 30–60 s.';
export const FIXED_HEADERS = ['host', 'content-length', 'transfer-encoding'] as const;
export const MAX_HEADERS = 200;
export const MAX_BODY_BYTES = 1 << 20;
const MAX_PATH = 8192;
const METHOD_RE = /^[A-Z]{1,16}$/;
const HEADER_NAME_RE = /^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,256}$/;
const LINE_BREAK_RE = /[\r\n\0]/;
const PATH_BAD_RE = /[\s\u0000-\u001f\u007f]/;

export const TEXTS = {
  method: 'The method must be 1 to 16 capital letters.',
  path: 'The path must start with / and have no spaces or line breaks.',
  status: 'The status must be a number from 100 to 599.',
  header: "A header needs a name of letters, digits and - _ . ! # $ % & ' * + ^ ` | ~, and no line break.",
  headers: `Send at most ${MAX_HEADERS} headers, each a name and a value.`,
  fixed: 'Host, Content-Length and Transfer-Encoding cannot be edited.',
  bodySize: 'The body must be at most 1 MiB.',
} as const;

/** What the editor holds: the held message's parts as text. `body` is null when it cannot be edited. */
export interface Draft {
  phase: PausePhase;
  method: string;
  path: string;
  status: string;
  headers: Headers;
  body: string | null;
}

export function isFixed(name: string): boolean {
  return (FIXED_HEADERS as readonly string[]).includes(name.trim().toLowerCase());
}

/** The draft of the held message as it is now; null unless the detail is of a paused flow. */
export function draftOf(detail: FlowDetail): Draft | null {
  const held = detail.breakpoint;
  if (!held) return null;
  const editable = held.body_not_editable === null;
  if (held.phase === 'request') {
    const body = detail.request.body;
    return {
      phase: 'request',
      method: detail.summary.method,
      path: detail.summary.path,
      status: '',
      headers: detail.request.headers.map(([k, v]) => [k, v]),
      body: editable ? (body.text ?? '') : null,
    };
  }
  const response = detail.response;
  if (!response) return null;
  return {
    phase: 'response',
    method: '',
    path: '',
    status: String(response.status),
    headers: response.headers.map(([k, v]) => [k, v]),
    body: editable ? (response.body.text ?? '') : null,
  };
}

function fixedOf(headers: Headers): string[] {
  return headers.filter(([k]) => isFixed(k)).map(([k, v]) => `${k.toLowerCase()}\n${v}`).sort();
}

/** Why the draft cannot be sent, or null: the server's checks, in its order. Blank header rows are left out. */
export function draftProblem(draft: Draft, initial: Draft): string | null {
  if (draft.phase === 'request') {
    if (!METHOD_RE.test(draft.method)) return TEXTS.method;
    if (!draft.path.startsWith('/') || draft.path.length > MAX_PATH || PATH_BAD_RE.test(draft.path)) return TEXTS.path;
  } else {
    const status = Number(draft.status);
    if (!/^\d{3}$/.test(draft.status.trim()) || status < 100 || status > 599) return TEXTS.status;
  }
  const headers = sentHeaders(draft.headers);
  if (headers.length > MAX_HEADERS) return TEXTS.headers;
  if (headers.some(([k, v]) => !HEADER_NAME_RE.test(k) || LINE_BREAK_RE.test(v))) return TEXTS.header;
  if (fixedOf(headers).join('\0') !== fixedOf(initial.headers).join('\0')) return TEXTS.fixed;
  if (draft.body !== null && new TextEncoder().encode(draft.body).length > MAX_BODY_BYTES) return TEXTS.bodySize;
  return null;
}

function sentHeaders(headers: Headers): Headers {
  return headers.filter(([k, v]) => k.trim() !== '' || v !== '').map(([k, v]) => [k.trim(), v]);
}

/** What Continue sends: every part, the body null when it was not changed. */
export function editsOf(draft: Draft, initial: Draft): BreakpointEdits {
  const headers = sentHeaders(draft.headers);
  const body = draft.body !== null && draft.body !== initial.body ? draft.body : null;
  return draft.phase === 'request'
    ? { method: draft.method, path: draft.path, headers, body }
    : { status: Number(draft.status), headers, body };
}

/** The parts the draft changed, for "Edited: status, body"; empty when nothing changed. */
export function editedParts(draft: Draft, initial: Draft): string[] {
  const parts: string[] = [];
  if (draft.phase === 'request') {
    if (draft.method !== initial.method) parts.push('method');
    if (draft.path !== initial.path) parts.push('path');
  } else if (draft.status.trim() !== initial.status) {
    parts.push('status');
  }
  if (JSON.stringify(sentHeaders(draft.headers)) !== JSON.stringify(initial.headers)) parts.push('headers');
  if (draft.body !== initial.body) parts.push('body');
  return parts;
}

/** How long it has waited, as the row shows it: `0:14`. */
export function waited(since: number | null, nowMs: number): string {
  const s = since === null ? 0 : Math.max(0, Math.floor(nowMs / 1000 - since));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** After 20 s paused, the editor says the app may give up; null before. */
export function giveUpHint(since: number | null, nowMs: number): string | null {
  if (since === null) return null;
  const s = Math.max(0, Math.floor(nowMs / 1000 - since));
  return s >= HINT_S ? `${GIVE_UP} This one has waited ${s} s.` : null;
}

export function bodyNotEditableText(reason: string): string {
  return `Body not editable: ${reason}`;
}

export function phaseText(phase: PausePhase): string {
  return phase === 'request' ? 'Before sending' : 'Before the app gets the response';
}
