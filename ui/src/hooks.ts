import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { isBodySearch, isServerExpr } from './logic/filters';
import type { FlowSummary } from './types';

export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

interface ServerResult {
  key: string;
  ids: ReadonlySet<string> | null;
  error: string | null;
}

const EMPTY: ServerResult = { key: '', ids: null, error: null };

/**
 * Asks the server: a `~`/`!` expression for the ids it matches, plain text of three or more
 * characters for the ids whose headers or bodies contain it. Debounced while typing, then
 * refreshed while new or changed flows arrive (every 1.5 s for an expression, 3 s for text).
 */
export function useServerFilter(search: string, flows: FlowSummary[], session: string | null = null) {
  const expr = isServerExpr(search);
  const text = !expr && isBodySearch(search);
  const active = expr || text;
  const query = search.trim();
  const mode = `${expr ? 'expr' : 'text'}|${session ?? ''}|`;
  const key = mode + query;
  const [result, setResult] = useState<ServerResult>(EMPTY);
  const flowsRef = useRef(flows);
  flowsRef.current = flows;

  useEffect(() => {
    if (!active) {
      setResult((r) => (r.ids === null && r.error === null ? r : EMPTY));
      return;
    }
    let cancelled = false;
    let controller: AbortController | null = null;
    let seen = flowsRef.current;

    const run = async () => {
      controller?.abort();
      const mine = new AbortController();
      controller = mine;
      try {
        const ids = expr ? await api.filter(query, mine.signal, session) : await api.search(query, mine.signal, session);
        if (!cancelled && !mine.signal.aborted) setResult({ key, ids: new Set(ids), error: null });
      } catch (e) {
        if (cancelled || mine.signal.aborted) return;
        if (e instanceof ApiError && e.status === 400 && expr) setResult({ key, ids: null, error: e.message });
      }
    };

    const first = setTimeout(() => void run(), 300);
    const poll = setInterval(
      () => {
        if (flowsRef.current !== seen) {
          seen = flowsRef.current;
          void run();
        }
      },
      expr ? 1500 : 3000,
    );
    return () => {
      cancelled = true;
      controller?.abort();
      clearTimeout(first);
      clearInterval(poll);
    };
  }, [active, expr, query, session, key]);

  // While an expression is typed, its last answer stays shown; text ids would add stale matches.
  const usable = expr ? result.key.startsWith(mode) : result.key === key;
  return {
    ids: active && usable ? result.ids : null,
    error: expr && result.key === key ? result.error : null,
  };
}
