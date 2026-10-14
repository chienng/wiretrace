import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { isServerExpr } from './logic/filters';
import type { FlowSummary } from './types';

export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

interface ServerFilterResult {
  expr: string;
  ids: ReadonlySet<string> | null;
  error: string | null;
}

/**
 * Evaluates a `~`/`!` expression on the server: debounced while typing, then refreshed
 * every 1.5 s while new or changed flows have arrived.
 */
export function useServerFilter(search: string, flows: FlowSummary[]) {
  const active = isServerExpr(search);
  const expr = search.trim();
  const [result, setResult] = useState<ServerFilterResult>({ expr: '', ids: null, error: null });
  const flowsRef = useRef(flows);
  flowsRef.current = flows;

  useEffect(() => {
    if (!active) {
      setResult((r) => (r.ids === null && r.error === null ? r : { expr: '', ids: null, error: null }));
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
        const ids = await api.filter(expr, mine.signal);
        if (!cancelled && !mine.signal.aborted) setResult({ expr, ids: new Set(ids), error: null });
      } catch (e) {
        if (cancelled || mine.signal.aborted) return;
        if (e instanceof ApiError && e.status === 400) setResult({ expr, ids: null, error: e.message });
      }
    };

    const first = setTimeout(() => void run(), 300);
    const poll = setInterval(() => {
      if (flowsRef.current !== seen) {
        seen = flowsRef.current;
        void run();
      }
    }, 1500);
    return () => {
      cancelled = true;
      controller?.abort();
      clearTimeout(first);
      clearInterval(poll);
    };
  }, [active, expr]);

  return {
    ids: active ? result.ids : null,
    error: active && result.expr === expr ? result.error : null,
  };
}
