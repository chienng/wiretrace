import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../api';
import { methodClass } from '../logic/format';
import {
  emptyRule,
  exportJson,
  filterRules,
  mergeImport,
  newRuleId,
  parseImport,
  replaceAt,
  ruleFromFlow,
  ruleSummary,
  serverError,
  type TypeFilter,
} from '../logic/rules';
import { useDispatch, useStore } from '../store';
import type { Rule, RuleAction } from '../types';
import { Modal } from './Modal';
import { RuleEditor, Toggle, type SaveProblem } from './RuleEditor';

const TAG_CLASS: Record<RuleAction, string> = { mock: 'mock', status: 'fault', delay: 'slow', drop: 'fault' };
const TYPE_FILTERS: { id: TypeFilter; label: string }[] = [
  { id: 'all', label: 'All types' },
  { id: 'mock', label: 'Mock' },
  { id: 'status', label: 'Status' },
  { id: 'delay', label: 'Delay' },
  { id: 'drop', label: 'Drop' },
];

/** The rule being edited: a saved one (by id) or a new one not saved yet. */
type Editing = { kind: 'saved'; id: string } | { kind: 'new'; rule: Rule } | null;

function RuleItem({ rule, selected, onSelect, onToggle, busy }: { rule: Rule; selected: boolean; onSelect: () => void; onToggle?: (on: boolean) => void; busy: boolean }) {
  return (
    <div
      className={`rule${selected ? ' sel' : ''}${rule.enabled ? '' : ' off'}`}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      title={rule.name}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="rt">
        <span className={`m ${methodClass(rule.match.method)}`}>{rule.match.method}</span>
        <span className="rp">{rule.match.path}</span>
      </div>
      {onToggle ? <Toggle on={rule.enabled} label={rule.enabled ? 'Turn the rule off' : 'Turn the rule on'} onChange={onToggle} disabled={busy} /> : <span className="tag new">new</span>}
      <div className="ra">
        <span className={`tag ${TAG_CLASS[rule.action.type]}`}>{rule.action.type}</span>
        <span className="rn">{rule.name || 'Unnamed rule'}</span>
        <span className="rs"> · {ruleSummary(rule)}</span>
      </div>
    </div>
  );
}

function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function RulesView() {
  const { rules, rulesStale, appState, ui, flows } = useStore();
  const dispatch = useDispatch();
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mockFiles, setMockFiles] = useState<string[] | null>(null);
  const [text, setText] = useState('');
  const [type, setType] = useState<TypeFilter>('all');
  const [editing, setEditing] = useState<Editing>(null);
  const [busy, setBusy] = useState(false);
  const [pendingImport, setPendingImport] = useState<Rule[] | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const toast = useCallback((t: string) => dispatch({ type: 'toast', text: t }), [dispatch]);

  const load = useCallback(async () => {
    try {
      dispatch({ type: 'rules', rules: await api.rules() });
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : 'Could not load the rules.');
    }
  }, [dispatch]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (rulesStale) void load();
  }, [rulesStale, load]);
  useEffect(() => {
    let cancelled = false;
    api
      .mocks()
      .then((files) => !cancelled && setMockFiles(files))
      .catch(() => !cancelled && setMockFiles(null));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!ui.ruleSeed || !rules) return;
    setEditing({ kind: 'new', rule: ruleFromFlow(ui.ruleSeed, rules.api_hosts, newRuleId()) });
    dispatch({ type: 'ui', patch: { ruleSeed: null } });
  }, [ui.ruleSeed, rules, dispatch]);

  const list = rules?.rules ?? [];
  const visible = useMemo(() => filterRules(list, text, type), [list, text, type]);
  const savedIndex = editing?.kind === 'saved' ? list.findIndex((r) => r.id === editing.id) : -1;
  const savedRule = savedIndex >= 0 ? (list[savedIndex] as Rule) : null;
  const draftRule = editing?.kind === 'new' ? editing.rule : savedRule;

  useEffect(() => {
    // A rule deleted elsewhere (another tab, a hand edit) closes its editor.
    if (editing?.kind === 'saved' && rules && savedIndex < 0) setEditing(null);
  }, [editing, rules, savedIndex]);

  const selectedFlow = ui.selectedFlowId ? flows.find((f) => f.id === ui.selectedFlowId) ?? null : null;
  const testTarget = selectedFlow ?? (flows.length ? flows[flows.length - 1]! : null);
  const testTargetLabel = selectedFlow ? 'Test against selected request' : 'Test against last request';

  /** Save the whole list; a 409 reloads it. Returns the problem, or null once saved. */
  const persist = async (next: Rule[], index: number): Promise<SaveProblem | null> => {
    if (!rules) return { field: null, message: 'The rules are not loaded yet.' };
    setBusy(true);
    try {
      dispatch({ type: 'rules', rules: await api.putRules(rules.revision, next) });
      return null;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        void load();
        return { field: null, message: e.message };
      }
      if (e instanceof ApiError && e.status === 400) return serverError(e.data, index) ?? { field: null, message: e.message };
      return { field: null, message: e instanceof ApiError ? e.message : 'Could not save the rules.' };
    } finally {
      setBusy(false);
    }
  };

  const onSave = async (rule: Rule): Promise<SaveProblem | null> => {
    const index = editing?.kind === 'saved' ? savedIndex : list.length;
    const problem = await persist(replaceAt(list, index, rule), index);
    if (!problem) {
      setEditing({ kind: 'saved', id: rule.id });
      toast('Rule saved: it applies from the next request');
    }
    return problem;
  };

  const onToggle = async (rule: Rule, on: boolean) => {
    const index = list.findIndex((r) => r.id === rule.id);
    const problem = await persist(replaceAt(list, index, { ...rule, enabled: on }), index);
    if (problem) toast(problem.message);
  };

  const onDelete = async () => {
    if (!savedRule || !window.confirm(`Delete the rule "${savedRule.name}"?`)) return;
    const problem = await persist(
      list.filter((r) => r.id !== savedRule.id),
      -1,
    );
    if (problem) toast(problem.message);
    else {
      setEditing(null);
      toast('Rule deleted');
    }
  };

  const onRearm = async () => {
    if (!savedRule) return;
    try {
      dispatch({ type: 'rules', rules: await api.rearm(savedRule.id) });
      toast('Counters reset');
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Could not re-arm the rule.');
    }
  };

  const onTest = async (rule: Rule) => {
    if (!testTarget) return 'No request captured yet.';
    try {
      return await api.testRule(rule, testTarget.id);
    } catch (e) {
      return e instanceof ApiError ? e.message : 'Could not test the rule.';
    }
  };

  const onPickFile = async (file: File | undefined) => {
    if (!file) return;
    const parsed = parseImport(await file.text());
    if ('error' in parsed) {
      toast(parsed.error);
      return;
    }
    setImportError(null);
    setPendingImport(parsed);
  };

  const doImport = async (mode: 'add' | 'replace') => {
    if (!pendingImport) return;
    const problem = await persist(mergeImport(list, pendingImport, mode), -1);
    if (problem) {
      setImportError(problem.message);
      return;
    }
    toast(`${pendingImport.length} ${pendingImport.length === 1 ? 'rule' : 'rules'} imported`);
    setPendingImport(null);
    setEditing(null);
  };

  const preset = appState?.preset ?? '';

  return (
    <div className="rules-wrap">
      <div className="rules-bar">
        <span className="title">Rules — preset: {preset}</span>
        {rules?.file && <span className="rules-file">{rules.file}</span>}
        <span className="spacer" />
        <button type="button" className="btn small" onClick={() => fileInput.current?.click()} disabled={!rules || busy}>
          Import…
        </button>
        <button type="button" className="btn small" onClick={() => download(`wiretrace-rules-${preset || 'preset'}.json`, exportJson(list))} disabled={!rules || list.length === 0}>
          Export…
        </button>
        <button type="button" className="btn small primary" onClick={() => setEditing({ kind: 'new', rule: emptyRule(newRuleId()) })} disabled={!rules}>
          + New rule
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          className="sr"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => {
            void onPickFile(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
      </div>
      {loadError && <div className="banner bad">{loadError}</div>}
      {rules?.error && (
        <div className="banner bad">
          {rules.file || 'The rules file'} was not applied: {rules.error}. The rules listed below are still in effect.
        </div>
      )}
      {rules?.legacy_faults_on && (
        <div className="banner warn">
          A <span className="kbd">qa_fault_*</span> option is on: it applies to requests that no rule changes.
        </div>
      )}
      <div className="rules-body">
        <div className="rule-list">
          <div className="hdr">
            <div className="search">
              <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true">
                <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
              <input type="text" value={text} onChange={(e) => setText(e.target.value)} placeholder="Filter rules…" aria-label="Filter rules" spellCheck={false} />
            </div>
            <span className="select-wrap">
              <select aria-label="Rule type" value={type} onChange={(e) => setType(e.target.value as TypeFilter)}>
                {TYPE_FILTERS.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </span>
          </div>
          <div className="rule-items">
            {editing?.kind === 'new' && <RuleItem rule={editing.rule} selected onSelect={() => undefined} busy={busy} />}
            {visible.map((r) => (
              <RuleItem
                key={r.id}
                rule={r}
                selected={editing?.kind === 'saved' && editing.id === r.id}
                onSelect={() => setEditing({ kind: 'saved', id: r.id })}
                onToggle={(on) => void onToggle(r, on)}
                busy={busy}
              />
            ))}
            {rules && list.length === 0 && editing?.kind !== 'new' && (
              <div className="note">No rules yet. Create one with + New rule, or from a request in Traffic.</div>
            )}
            {rules && list.length > 0 && visible.length === 0 && <div className="note">No rule matches the filter.</div>}
            {!rules && !loadError && <div className="note">Loading…</div>}
          </div>
          <div className="rule-order">Rules apply in this order; the first enabled one that applies wins.</div>
        </div>
        {draftRule && rules ? (
          <RuleEditor
            key={editing?.kind === 'new' ? `new:${draftRule.id}` : draftRule.id}
            initial={draftRule}
            isNew={editing?.kind === 'new'}
            savedEnabled={savedRule ? savedRule.enabled : null}
            apiHosts={rules.api_hosts}
            mockFiles={mockFiles}
            others={list.filter((_, i) => i !== savedIndex)}
            stats={savedRule ? rules.stats[savedRule.id] ?? null : null}
            busy={busy}
            testTarget={testTarget}
            testTargetLabel={testTargetLabel}
            onSave={onSave}
            onDelete={() => void onDelete()}
            onRearm={() => void onRearm()}
            onTest={onTest}
          />
        ) : (
          <div className="editor">
            <div className="empty static">Select a rule to edit it, or create a new one.</div>
          </div>
        )}
      </div>
      {pendingImport && (
        <Modal title="Import rules" lead={`The file has ${pendingImport.length} ${pendingImport.length === 1 ? 'rule' : 'rules'}. They are checked like a saved rule.`} onClose={() => setPendingImport(null)}>
          {importError && (
            <div className="form-error" role="alert">
              {importError}
            </div>
          )}
          <div className="sheet-foot">
            <button type="button" className="btn" onClick={() => setPendingImport(null)}>
              Cancel
            </button>
            <span className="spacer" />
            <button type="button" className="btn danger" disabled={busy} onClick={() => void doImport('replace')}>
              Replace all {list.length} rules
            </button>
            <button type="button" className="btn primary" disabled={busy} onClick={() => void doImport('add')}>
              Add to the current rules
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
