import { useEffect, useState, type ReactNode } from 'react';
import {
  ACTIONS,
  APPLY_MODES,
  clockTime,
  DEFAULT_ERROR_BODY,
  EMPTY_STATS,
  LIMITS,
  METHODS,
  STATUS_TEXT,
  validateRule,
  type FieldErrors,
} from '../logic/rules';
import type { FlowSummary, Rule, RuleAction, RuleStats, RuleTestResult } from '../types';

export interface SaveProblem {
  field: string | null;
  message: string;
}

interface Props {
  initial: Rule;
  isNew: boolean;
  /** The saved `enabled`, so the list's switch shows here too. */
  savedEnabled: boolean | null;
  apiHosts: string[];
  mockFiles: string[] | null;
  others: Rule[];
  stats: RuleStats | null;
  busy: boolean;
  testTarget: FlowSummary | null;
  testTargetLabel: string;
  onSave: (rule: Rule) => Promise<SaveProblem | null>;
  onDelete: () => void;
  onRearm: () => void;
  onTest: (rule: Rule) => Promise<RuleTestResult | string>;
}

const num = (v: number) => (Number.isNaN(v) ? '' : String(v));
const toNum = (s: string) => (/^\s*\d+\s*$/.test(s) ? Number(s) : NaN);

/** A mock defaults to a success status and an injected status to an error, unless one was typed for that kind. */
function statusFor(next: RuleAction, current: Rule['action']): number {
  if (next === 'mock' && current.type !== 'mock' && current.status >= 400) return 200;
  if (next === 'status' && current.type !== 'status' && current.status < 400) return 500;
  return current.status;
}

function Field({ label, error, children, className, htmlFor }: { label: string; error?: string; children: ReactNode; className?: string; htmlFor?: string }) {
  return (
    <div className={`field${className ? ` ${className}` : ''}`}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {error && (
        <div className="field-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

export function Toggle({ on, label, onChange, disabled }: { on: boolean; label: string; onChange: (on: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      title={label}
      disabled={disabled}
      className={`toggle${on ? ' on' : ''}`}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!on);
      }}
    />
  );
}

export function RuleEditor(props: Props) {
  const { initial, isNew, savedEnabled, apiHosts, mockFiles, others, stats, busy, testTarget, testTargetLabel } = props;
  const [rule, setRule] = useState<Rule>(initial);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [test, setTest] = useState<RuleTestResult | string | null>(null);
  const [testing, setTesting] = useState(false);
  const [customStatus, setCustomStatus] = useState(false);

  useEffect(() => {
    if (savedEnabled !== null) setRule((r) => (r.enabled === savedEnabled ? r : { ...r, enabled: savedEnabled }));
  }, [savedEnabled]);

  const set = (next: Rule) => {
    setRule(next);
    setTest(null);
  };
  const match = (p: Partial<Rule['match']>) => set({ ...rule, match: { ...rule.match, ...p } });
  const action = (p: Partial<Rule['action']>) => set({ ...rule, action: { ...rule.action, ...p } });
  const apply = (p: Partial<Rule['apply']>) => set({ ...rule, apply: { ...rule.apply, ...p } });

  const check = (): boolean => {
    const found = validateRule(rule, apiHosts, mockFiles, others);
    setErrors(found);
    setGeneral(found.id ?? null);
    return Object.keys(found).length === 0;
  };

  const save = async () => {
    if (!check()) return;
    const problem = await props.onSave({ ...rule, name: rule.name.trim() });
    if (!problem) {
      setErrors({});
      setGeneral(null);
      return;
    }
    if (problem.field && problem.field !== 'id' && problem.field !== 'rules') {
      setErrors({ [problem.field]: problem.message });
      setGeneral(null);
    } else {
      setGeneral(problem.message);
    }
  };

  const runTest = async () => {
    if (!check()) return;
    setTesting(true);
    try {
      setTest(await props.onTest(rule));
    } finally {
      setTesting(false);
    }
  };

  const a = rule.action;
  const s = stats ?? EMPTY_STATS;
  const otherStatus = customStatus || !(a.status in STATUS_TEXT);
  const statusInput = (
    <Field label="Status" error={errors['action.status']} className="w-status" htmlFor="r-status">
      <div className="with-hint">
        <select
          id="r-status"
          className="selectin"
          value={otherStatus ? 'other' : String(a.status)}
          onChange={(e) => {
            const v = e.target.value;
            setCustomStatus(v === 'other');
            if (v !== 'other') action({ status: Number(v) });
          }}
        >
          {Object.entries(STATUS_TEXT).map(([code, text]) => (
            <option key={code} value={code}>
              {code} {text}
            </option>
          ))}
          <option value="other">Other…</option>
        </select>
        {otherStatus && (
          <input
            className="textin mono"
            aria-label="Status code"
            inputMode="numeric"
            placeholder="100–599"
            value={num(a.status)}
            onChange={(e) => action({ status: toNum(e.target.value) })}
          />
        )}
      </div>
    </Field>
  );
  const delayInput = (label: string) => (
    <Field label={label} error={errors['action.delay_ms']} className="w-delay" htmlFor="r-delay">
      <div className="with-unit">
        <input id="r-delay" className="textin mono" inputMode="numeric" value={num(a.delay_ms)} onChange={(e) => action({ delay_ms: toNum(e.target.value) })} />
        <span className="unit">ms</span>
      </div>
    </Field>
  );

  return (
    <div className="editor">
      <div className="row">
        <Field label="Rule name" error={errors.name} htmlFor="r-name">
          <input id="r-name" className="textin wide" maxLength={LIMITS.name} value={rule.name} placeholder="Order creation fails with server error" onChange={(e) => set({ ...rule, name: e.target.value })} />
        </Field>
        <div className="field fixed">
          <label>Enabled</label>
          <div className="toggle-line">
            <Toggle on={rule.enabled} label="Enabled" onChange={(on) => set({ ...rule, enabled: on })} />
          </div>
        </div>
      </div>

      <div className="field">
        <label htmlFor="r-path">When request matches</label>
        <div className="row">
          <select className="selectin w-method" aria-label="Method" value={rule.match.method} onChange={(e) => match({ method: e.target.value })}>
            {METHODS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <select className="selectin w-host" aria-label="Host" value={rule.match.host} onChange={(e) => match({ host: e.target.value })}>
            <option value="">Any API host</option>
            {apiHosts.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
            {rule.match.host && !apiHosts.includes(rule.match.host) && <option value={rule.match.host}>{rule.match.host} (not in the preset)</option>}
          </select>
          <input id="r-path" className="textin mono grow" maxLength={LIMITS.path} value={rule.match.path} placeholder="/api/v1/orders  (* matches anything)" spellCheck={false} onChange={(e) => match({ path: e.target.value })} />
        </div>
        {(errors['match.method'] || errors['match.host'] || errors['match.path']) && (
          <div className="field-error" role="alert">
            {errors['match.method'] ?? errors['match.host'] ?? errors['match.path']}
          </div>
        )}
        <div className="row gap-top">
          <input
            className="textin mono grow"
            aria-label="Body contains"
            maxLength={LIMITS.bodyContains}
            value={rule.match.body_contains}
            placeholder="+ Body contains (optional, case-sensitive)"
            spellCheck={false}
            onChange={(e) => match({ body_contains: e.target.value })}
          />
        </div>
        {errors['match.body_contains'] && (
          <div className="field-error" role="alert">
            {errors['match.body_contains']}
          </div>
        )}
      </div>

      <div className="field">
        <label>Then</label>
        <div className="seg" role="radiogroup" aria-label="Action">
          {ACTIONS.map((x) => (
            <button
              key={x.id}
              type="button"
              role="radio"
              aria-checked={a.type === x.id}
              className={a.type === x.id ? 'on' : ''}
              onClick={() => action({ type: x.id, status: statusFor(x.id, a) })}
            >
              {x.label}
            </button>
          ))}
        </div>
      </div>

      <div className="row">
        {(a.type === 'mock' || a.type === 'status') && statusInput}
        {delayInput(a.type === 'delay' ? 'Delay' : 'Extra delay')}
        <Field label="Apply" error={errors['apply.n']} className="grow">
          <div className="row center">
            <div className="seg" role="radiogroup" aria-label="Apply">
              {APPLY_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  role="radio"
                  aria-checked={rule.apply.mode === m.id}
                  className={rule.apply.mode === m.id ? 'on' : ''}
                  onClick={() => apply({ mode: m.id, n: m.id === 'every_nth' && rule.apply.n < LIMITS.minNth ? 3 : rule.apply.n })}
                >
                  {m.label}
                </button>
              ))}
            </div>
            {rule.apply.mode === 'every_nth' && (
              <input className="textin mono w-n" aria-label="N" inputMode="numeric" value={num(rule.apply.n)} onChange={(e) => apply({ n: toNum(e.target.value) })} />
            )}
          </div>
        </Field>
      </div>

      {a.type === 'mock' && (
        <Field label="Response body" error={errors['action.mock_file'] ?? errors['action.body']}>
          <select className="selectin wide" aria-label="Body source" value={a.mock_file} onChange={(e) => action({ mock_file: e.target.value })}>
            <option value="">Typed in below</option>
            {(mockFiles ?? []).map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
            {a.mock_file && mockFiles !== null && !mockFiles.includes(a.mock_file) && <option value={a.mock_file}>{a.mock_file} (missing)</option>}
          </select>
          {!a.mock_file && (
            <textarea className="bodyedit gap-top" aria-label="Response body" spellCheck={false} value={a.body} placeholder='{"items": []}' onChange={(e) => action({ body: e.target.value })} />
          )}
        </Field>
      )}
      {a.type === 'status' && (
        <Field label="Response body (optional)" error={errors['action.body']}>
          <textarea className="bodyedit" aria-label="Response body" spellCheck={false} value={a.body} placeholder={DEFAULT_ERROR_BODY} onChange={(e) => action({ body: e.target.value })} />
        </Field>
      )}
      {a.type === 'delay' && <div className="note-block">The request waits, then goes to the server; the app gets the real response.</div>}
      {a.type === 'drop' && <div className="note-block">The connection is closed without a response, as on a network loss.</div>}

      {!isNew && (
        <div className="stat">
          <span>
            Matched <b>{s.matches} {s.matches === 1 ? 'time' : 'times'}</b> this session
          </span>
          <span>
            Applied <b>{s.applied}</b>
          </span>
          <span>
            Last match <b>{clockTime(s.last_ts)}</b>
          </span>
          {rule.apply.mode !== 'always' && (
            <>
              <span className="spacer" />
              <button type="button" className="btn small" onClick={props.onRearm} disabled={busy} title="Reset the counters, so the rule applies again">
                Re-arm
              </button>
            </>
          )}
        </div>
      )}

      {test !== null && (
        <div className={`test-result ${typeof test === 'string' ? 'bad' : test.matches ? 'ok' : 'no'}`} role="status">
          {typeof test === 'string' ? (
            test
          ) : (
            <>
              <b>{test.reason}</b>
              {test.result && <div>The app would get: {test.result}</div>}
            </>
          )}
        </div>
      )}
      {general && (
        <div className="form-error" role="alert">
          {general}
        </div>
      )}

      <div className="row editor-foot">
        {!isNew && (
          <button type="button" className="btn danger" onClick={props.onDelete} disabled={busy}>
            Delete
          </button>
        )}
        <span className="spacer" />
        <button type="button" className="btn" onClick={runTest} disabled={testing || testTarget === null} title={testTarget ? `${testTarget.method} ${testTarget.path}` : 'No request captured yet'}>
          {testing ? 'Testing…' : testTargetLabel}
        </button>
        <button type="button" className="btn primary" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save rule'}
        </button>
      </div>
    </div>
  );
}
