import { useMemo, useState, type ReactNode } from 'react';
import { tryParseJson } from '../logic/json';
import { formatSize } from '../logic/format';
import type { Body } from '../types';

const MAX_TEXT_CHARS = 300_000;
const MAX_CHILDREN = 200;
const AUTO_OPEN_DEPTH = 2;

function Scalar({ value }: { value: unknown }) {
  if (typeof value === 'string') return <span className="s">{JSON.stringify(value)}</span>;
  if (typeof value === 'number') return <span className="n">{String(value)}</span>;
  return <span className="p">{String(value)}</span>;
}

function isContainer(v: unknown): v is Record<string, unknown> | unknown[] {
  return typeof v === 'object' && v !== null;
}

function JsonNode({ name, value, depth, last }: { name: string | null; value: unknown; depth: number; last: boolean }) {
  const [open, setOpen] = useState(depth < AUTO_OPEN_DEPTH);
  const [shown, setShown] = useState(MAX_CHILDREN);
  const comma = last ? '' : ',';
  const key: ReactNode = name !== null ? (
    <>
      <span className="k">{JSON.stringify(name)}</span>
      <span className="p">: </span>
    </>
  ) : null;

  if (!isContainer(value)) {
    return (
      <div className="jline">
        <span className="jtoggle" />
        {key}
        <Scalar value={value} />
        <span className="p">{comma}</span>
      </div>
    );
  }

  const isArray = Array.isArray(value);
  const entries: [string, unknown][] = isArray
    ? (value as unknown[]).map((v, i) => [String(i), v])
    : Object.entries(value);
  const [openCh, closeCh] = isArray ? ['[', ']'] : ['{', '}'];

  if (entries.length === 0) {
    return (
      <div className="jline">
        <span className="jtoggle" />
        {key}
        <span className="p">
          {openCh}
          {closeCh}
          {comma}
        </span>
      </div>
    );
  }

  return (
    <div>
      <div className="jline">
        <button type="button" className="jtoggle" onClick={() => setOpen(!open)} aria-label={open ? 'Fold' : 'Unfold'}>
          {open ? '▾' : '▸'}
        </button>
        {key}
        <span className="p">{openCh}</span>
        {!open && (
          <>
            <span className="fold"> … {entries.length} {isArray ? 'items' : 'keys'} </span>
            <span className="p">
              {closeCh}
              {comma}
            </span>
          </>
        )}
      </div>
      {open && (
        <>
          <div className="jchildren">
            {entries.slice(0, shown).map(([k, v], i) => (
              <JsonNode
                key={k}
                name={isArray ? null : k}
                value={v}
                depth={depth + 1}
                last={i === entries.length - 1 && shown >= entries.length}
              />
            ))}
            {entries.length > shown && (
              <div className="jline">
                <span className="jtoggle" />
                <button type="button" className="linkbtn" onClick={() => setShown(shown + MAX_CHILDREN * 5)}>
                  Show {Math.min(MAX_CHILDREN * 5, entries.length - shown)} more of {entries.length - shown}
                </button>
              </div>
            )}
          </div>
          <div className="jline">
            <span className="jtoggle" />
            <span className="p">
              {closeCh}
              {comma}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

export function BodyView({ body, label }: { body: Body; label: string }) {
  const parsed = useMemo(() => (body.text !== null ? tryParseJson(body.text) : null), [body.text]);

  if (body.binary || body.text === null) {
    return <div className="note">Binary {label.toLowerCase()} body, {formatSize(body.size)}. Not shown.</div>;
  }
  if (body.text === '' && body.size === 0) return <div className="note">No {label.toLowerCase()} body.</div>;

  const truncatedNote = body.truncated ? (
    <div className="note warn">Body truncated: showing the first part of {formatSize(body.size)}.</div>
  ) : null;

  if (parsed?.ok) {
    return (
      <div className="code">
        {truncatedNote}
        <JsonNode name={null} value={parsed.value} depth={0} last />
      </div>
    );
  }

  const text = body.text.length > MAX_TEXT_CHARS ? body.text.slice(0, MAX_TEXT_CHARS) : body.text;
  return (
    <div className="code">
      {truncatedNote}
      {text.length < body.text.length && (
        <div className="note warn">Showing the first {MAX_TEXT_CHARS.toLocaleString('en-US')} characters.</div>
      )}
      <pre className="plain">{text}</pre>
    </div>
  );
}
