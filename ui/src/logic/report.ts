/**
 * The bug report form (spec 012). The page builds no captured text: it shows the server's draft
 * and keeps the tester's edits. A newer draft request wins over an older one (`seq`), and a change
 * that would regenerate edited text waits for "Replace your edits?" before it applies.
 */
import type { FlowSummary, ReportBox, ReportDraft, ReportFormat, Screenshot } from '../types';

export const MAX_SCREENSHOTS = 5;
export const MAX_TITLE = 200;
export const BOXES: readonly ReportBox[] = ['others', 'device', 'app'];
export const REPLACE_QUESTION = 'Replace your edits with a new description?';
export const FORMAT_LABELS: Record<ReportFormat, string> = {
  markdown: 'Markdown (YouTrack, Jira Cloud)',
  jira: 'Jira wiki (Jira Data Center)',
};
export const BOX_LABELS: Record<ReportBox, string> = {
  others: 'Other requests ±30 s',
  device: 'Device logs (same window)',
  app: 'App logs (same window)',
};

export type Change = { kind: 'format'; format: ReportFormat } | { kind: 'box'; box: ReportBox; on: boolean };

export interface FormState {
  phase: 'loading' | 'ready' | 'error';
  /** The newest draft request; an answer to an older one is ignored. */
  seq: number;
  draft: ReportDraft | null;
  format: ReportFormat;
  include: Record<ReportBox, boolean>;
  title: string;
  titleEdited: boolean;
  description: string;
  /** The tester typed in the description since the last draft. */
  edited: boolean;
  /** A change waiting for "Replace your edits?". Nothing of it is applied until she says yes. */
  pending: Change | null;
  error: string | null;
  capturing: boolean;
  shotError: string | null;
  screenshots: Screenshot[];
}

export type FormAction =
  | { type: 'change'; change: Change }
  | { type: 'confirm' }
  | { type: 'cancel' }
  | { type: 'draft'; seq: number; draft: ReportDraft }
  | { type: 'failed'; seq: number; error: string }
  | { type: 'title'; text: string }
  | { type: 'description'; text: string }
  | { type: 'capturing' }
  | { type: 'captured'; screenshots: Screenshot[] }
  | { type: 'captureFailed'; error: string }
  | { type: 'removed'; screenshots: Screenshot[] };

export function initialForm(format: ReportFormat): FormState {
  return {
    phase: 'loading',
    seq: 1,
    draft: null,
    format,
    include: { others: true, device: true, app: true },
    title: '',
    titleEdited: false,
    description: '',
    edited: false,
    pending: null,
    error: null,
    capturing: false,
    shotError: null,
    screenshots: [],
  };
}

function changes(state: FormState, change: Change): boolean {
  return change.kind === 'format' ? change.format !== state.format : state.include[change.box] !== change.on;
}

function apply(state: FormState, change: Change): FormState {
  const next =
    change.kind === 'format'
      ? { ...state, format: change.format }
      : { ...state, include: { ...state.include, [change.box]: change.on } };
  return { ...next, phase: 'loading', seq: state.seq + 1, pending: null, error: null };
}

export function formReducer(state: FormState, action: FormAction): FormState {
  switch (action.type) {
    case 'change':
      if (!changes(state, action.change)) return state;
      return state.edited ? { ...state, pending: action.change } : apply(state, action.change);
    case 'confirm':
      return state.pending ? apply(state, state.pending) : state;
    case 'cancel':
      return { ...state, pending: null };
    case 'draft':
      if (action.seq !== state.seq) return state;
      return {
        ...state,
        phase: 'ready',
        draft: action.draft,
        description: action.draft.description,
        edited: false,
        title: state.titleEdited ? state.title : action.draft.title,
        screenshots: action.draft.screenshots.items,
        error: null,
      };
    case 'failed':
      if (action.seq !== state.seq) return state;
      return { ...state, phase: 'error', error: action.error };
    case 'title':
      return { ...state, title: action.text, titleEdited: true };
    case 'description':
      // The text is read-only while a new draft is on its way, so no edit is lost to it.
      if (state.phase === 'loading') return state;
      return { ...state, description: action.text, edited: true };
    case 'capturing':
      return { ...state, capturing: true, shotError: null };
    case 'captured':
      return { ...state, capturing: false, screenshots: action.screenshots };
    case 'captureFailed':
      return { ...state, capturing: false, shotError: action.error };
    case 'removed':
      return { ...state, screenshots: action.screenshots };
  }
}

export function includedBoxes(include: Record<ReportBox, boolean>): ReportBox[] {
  return BOXES.filter((box) => include[box]);
}

export function titleError(title: string): string | null {
  const length = title.trim().length;
  return length >= 1 && length <= MAX_TITLE ? null : `The title needs 1 to ${MAX_TITLE} characters`;
}

export function canTakeScreenshot(state: FormState): boolean {
  return state.draft?.screenshots.state === 'available' && !state.capturing && state.screenshots.length < MAX_SCREENSHOTS;
}

export function countLabel(box: ReportBox, n: number): string {
  if (box === 'others') return `${n} ${n === 1 ? 'request' : 'requests'}`;
  return `${n} ${n === 1 ? 'line' : 'lines'}`;
}

function failed(flow: FlowSummary): boolean {
  return (flow.status !== null && flow.status >= 400) || flow.error !== null;
}

/** The selected request, else the most recent failed one, else null for the whole session. */
export function reportFlowId(selectedId: string | null, flows: readonly FlowSummary[]): string | null {
  if (selectedId !== null && flows.some((f) => f.id === selectedId)) return selectedId;
  let latest: FlowSummary | null = null;
  for (const flow of flows) if (failed(flow) && (latest === null || flow.ts >= latest.ts)) latest = flow;
  return latest?.id ?? null;
}

const FORMAT_PREFIX = 'wiretrace.reportFormat.';

export function formatKey(preset: string): string {
  return FORMAT_PREFIX + preset;
}

/** The format last chosen for this preset, in the browser's localStorage; Markdown by default. */
export function loadFormat(storage: Pick<Storage, 'getItem'> | null, preset: string): ReportFormat {
  try {
    return storage?.getItem(formatKey(preset)) === 'jira' ? 'jira' : 'markdown';
  } catch {
    return 'markdown';
  }
}

export function storeFormat(storage: Pick<Storage, 'setItem'> | null, preset: string, format: ReportFormat): void {
  try {
    storage?.setItem(formatKey(preset), format);
  } catch {
    // Storage full or off: the choice is kept only while the form is open.
  }
}
