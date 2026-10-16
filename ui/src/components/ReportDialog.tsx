import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { api, ApiError, reportFileUrl, screenshotUrl, type ReportQuery } from '../api';
import { copyText } from '../clipboard';
import { formatSize } from '../logic/format';
import {
  BOX_LABELS,
  BOXES,
  canTakeScreenshot,
  countLabel,
  FORMAT_LABELS,
  formReducer,
  includedBoxes,
  initialForm,
  loadFormat,
  MAX_SCREENSHOTS,
  MAX_TITLE,
  REPLACE_QUESTION,
  storeFormat,
  titleError,
} from '../logic/report';
import { useDispatch, useStore } from '../store';
import type { ReportFormat } from '../types';
import { Modal } from './Modal';

const LOG_NOTE = 'Log lines are masked by pattern only; check them before sharing.';
const FORMATS: readonly ReportFormat[] = ['markdown', 'jira'];

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
      <path d="M10.5 3.5V3a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5" />
    </svg>
  );
}

function DownloadIcon({ size }: { size?: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10" />
    </svg>
  );
}

function message(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

/**
 * The bug report form (spec 012) for the request `flowId`, or for the whole session when null,
 * of the live session or of the previous session that is open (`session`).
 */
export function ReportDialog({ session = null, flowId = null }: { session?: string | null; flowId?: string | null }) {
  const dispatch = useDispatch();
  const { appState } = useStore();
  const preset = appState?.preset ?? '';
  const [state, send] = useReducer(formReducer, preset, (p) => initialForm(loadFormat(storage(), p)));
  const [copied, setCopied] = useState<'title' | 'description' | null>(null);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const close = useCallback(() => dispatch({ type: 'ui', patch: { dialog: null } }), [dispatch]);
  const query: ReportQuery = { flow: flowId, session, include: includedBoxes(state.include) };

  useEffect(() => {
    // One draft per `seq` (the format and boxes change only with it); the abort makes the last request win.
    const controller = new AbortController();
    const seq = state.seq;
    api
      .reportDraft({ flow: flowId, session, include: includedBoxes(state.include) }, state.format, controller.signal)
      .then((draft) => send({ type: 'draft', seq, draft }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) send({ type: 'failed', seq, error: message(e, 'The draft could not be made.') });
      });
    return () => controller.abort();
  }, [state.seq, flowId, session]);

  useEffect(() => {
    if (preset) storeFormat(storage(), preset, state.format);
  }, [preset, state.format]);

  useEffect(() => () => {
    if (copiedTimer.current) clearTimeout(copiedTimer.current);
  }, []);

  const copy = async (what: 'title' | 'description', text: string) => {
    if (await copyText(text)) {
      setCopied(what);
      if (copiedTimer.current) clearTimeout(copiedTimer.current);
      copiedTimer.current = setTimeout(() => setCopied(null), 2000);
    } else {
      dispatch({ type: 'toast', text: 'Copy failed' });
    }
  };

  const take = async () => {
    send({ type: 'capturing' });
    try {
      const answer = await api.takeScreenshot();
      send({ type: 'captured', screenshots: answer.screenshots });
    } catch (e) {
      send({ type: 'captureFailed', error: message(e, 'The screenshot failed.') });
    }
  };

  const remove = async (name: string) => {
    try {
      const answer = await api.removeScreenshot(name);
      send({ type: 'removed', screenshots: answer.screenshots });
    } catch (e) {
      send({ type: 'captureFailed', error: message(e, 'The screenshot could not be removed.') });
    }
  };

  const draft = state.draft;
  const loading = state.phase === 'loading';
  const titleProblem = titleError(state.title);
  const files = draft?.files.filter((f) => f.kind !== 'zip') ?? [];
  const zip = draft?.files.find((f) => f.kind === 'zip') ?? null;
  const shots = draft?.screenshots ?? null;
  const masked = draft ? [...draft.masked.headers, ...draft.masked.fields] : [];
  const live = !session;

  return (
    <Modal title="Report bug" onClose={close} wide>
      <div className="report-form">
        <p className="lead">
          {!draft ? (
            'Preparing the report…'
          ) : draft.lead.request ? (
            <>
              From request <span className="kbd">{draft.lead.request}</span>
              {draft.lead.at && ` at ${draft.lead.at}`}
              {draft.lead.device && ` · ${draft.lead.device}`}
            </>
          ) : (
            <>
              Whole session <span className="kbd">{draft.lead.session}</span>
              {draft.lead.device && ` · ${draft.lead.device}`}
            </>
          )}
        </p>
        <div className="note-local">
          Nothing is sent anywhere. Copy the title and description, download the files, and add them to your YouTrack or Jira issue.
        </div>

        {state.error && (
          <div className="form-error" role="alert">
            {state.error}
          </div>
        )}

        <div className="field">
          <label htmlFor="report-title">Title</label>
          <div className="with-ico">
            <input
              id="report-title"
              className="textin"
              value={state.title}
              maxLength={MAX_TITLE}
              disabled={!draft}
              onChange={(e) => send({ type: 'title', text: e.target.value })}
            />
            {copied === 'title' && <span className="copied">✓ Copied</span>}
            <button
              type="button"
              className={`ico${copied === 'title' ? ' done' : ''}`}
              title="Copy title"
              aria-label="Copy title"
              disabled={!draft || titleProblem !== null}
              onClick={() => void copy('title', state.title)}
            >
              <CopyIcon />
            </button>
          </div>
          {draft && titleProblem && <div className="field-error">{titleProblem}</div>}
        </div>

        <div className="field">
          <div className="desc-h">
            <label htmlFor="report-description">Description</label>
            <span className="spacer" />
            <div className="seg sm" role="radiogroup" aria-label="Format">
              {FORMATS.map((f) => (
                <button
                  key={f}
                  type="button"
                  role="radio"
                  aria-checked={state.format === f}
                  className={state.format === f ? 'on' : ''}
                  onClick={() => send({ type: 'change', change: { kind: 'format', format: f } })}
                >
                  {FORMAT_LABELS[f]}
                </button>
              ))}
            </div>
            {copied === 'description' && <span className="copied">✓ Copied</span>}
            <button
              type="button"
              className={`ico${copied === 'description' ? ' done' : ''}`}
              title="Copy description"
              aria-label="Copy description"
              disabled={!draft || state.description === ''}
              onClick={() => void copy('description', state.description)}
            >
              <CopyIcon />
            </button>
          </div>
          {state.pending && (
            <div className="confirm" role="alertdialog" aria-label={REPLACE_QUESTION}>
              <span>{REPLACE_QUESTION}</span>
              <span className="spacer" />
              <button type="button" className="btn small" onClick={() => send({ type: 'cancel' })}>
                No, keep my text
              </button>
              <button type="button" className="btn small danger" onClick={() => send({ type: 'confirm' })}>
                Replace
              </button>
            </div>
          )}
          <textarea
            id="report-description"
            className={`desc${loading ? ' busy' : ''}`}
            value={state.description}
            readOnly={loading}
            spellCheck={false}
            onChange={(e) => send({ type: 'description', text: e.target.value })}
          />
          <div className="sub">Editable. Your text stays until you change the format or a box below; Wiretrace asks before replacing it.</div>
        </div>

        <div className="grid-form">
          <div>
            <div className="sec">
              <div className="sec-h">Logs</div>
              {BOXES.map((box) => (
                <label key={box} className="check">
                  <input
                    type="checkbox"
                    checked={state.include[box]}
                    onChange={(e) => send({ type: 'change', change: { kind: 'box', box, on: e.target.checked } })}
                  />
                  {BOX_LABELS[box]}
                  <span className="d">{draft ? countLabel(box, draft.counts[box]) : ''}</span>
                </label>
              ))}
            </div>
            <div className={`sec files${loading ? ' busy' : ''}`}>
              {files.map((f) => (
                <div key={f.kind} className="file">
                  <span className="fn">{f.name}</span>
                  <span className="sz">{formatSize(f.size)}</span>
                  <a className="ico" href={reportFileUrl(f.kind, query)} download={f.name} title={`Download ${f.name}`} aria-label={`Download ${f.name}`}>
                    <DownloadIcon />
                  </a>
                </div>
              ))}
              {draft && files.length === 0 && <p className="note-block">No file has anything in it with these boxes.</p>}
            </div>
            {masked.length > 0 && (
              <div className="sec">
                <div className="sec-h">Masked before export</div>
                <div className="redact">
                  {masked.map((name) => (
                    <span key={name}>{name}</span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="sec">
            <div className="sec-h">
              Screenshots <span className="sec-n">· {state.screenshots.length} of {MAX_SCREENSHOTS}</span>
            </div>
            {shots?.state === 'manual' ? (
              <p className="note-block">{shots.reason}</p>
            ) : (
              <div className="shots">
                {state.screenshots.map((s) => (
                  <div key={s.name} className="thumb">
                    {live && (
                      <button type="button" className="x" title="Remove" aria-label={`Remove the screenshot from ${s.time}`} onClick={() => void remove(s.name)}>
                        ×
                      </button>
                    )}
                    <img src={screenshotUrl(s.name, session)} alt={`Screenshot from ${s.time}`} />
                    <div className="cap">
                      {s.time}
                      <a className="ico" href={screenshotUrl(s.name, session, true)} download title="Download" aria-label={`Download the screenshot from ${s.time}`}>
                        <DownloadIcon />
                      </a>
                    </div>
                  </div>
                ))}
                {state.screenshots.length < MAX_SCREENSHOTS && shots && (
                  <button type="button" className="take" disabled={!canTakeScreenshot(state)} onClick={() => void take()}>
                    <b>+</b>
                    {state.capturing ? 'Taking…' : 'Take screenshot'}
                  </button>
                )}
              </div>
            )}
            {shots?.state === 'off' && <div className="sub">{shots.reason}</div>}
            {shots?.state === 'available' && (
              <div className="sub">
                {appState?.target === 'ios-sim'
                  ? 'Taken from the booted Simulator.'
                  : 'Taken from the phone through adb. On a real iPhone, take it on the phone instead.'}
              </div>
            )}
            {state.shotError && (
              <div className="form-error shot-error" role="alert">
                {state.shotError}
              </div>
            )}
          </div>
        </div>

        <div className="sheet-foot">
          <span className="tip">{LOG_NOTE}</span>
          <span className="spacer" />
          <button type="button" className="btn" onClick={close}>
            Close
          </button>
          {zip && !loading ? (
            <a className="btn primary" href={reportFileUrl('zip', query)} download={zip.name}>
              <DownloadIcon size={14} />
              Download all (.zip)
            </a>
          ) : (
            <button type="button" className="btn primary" disabled>
              <DownloadIcon size={14} />
              Download all (.zip)
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}
