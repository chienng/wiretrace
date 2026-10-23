import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../api';
import { copyText } from '../clipboard';
import { formatSize, formatTime } from '../logic/format';
import {
  HEX_DUMP_BYTES,
  MAX_KEPT,
  OVERSIZE,
  PAGE_LIMIT,
  acceptLoad,
  connectionHeader,
  continueFrom,
  followAfter,
  hexDump,
  matchLabel,
  mergeMessages,
  newestNote,
  olderFrom,
  oldestIndex,
  sortedMessages,
  startLoad,
  tailFrom,
  trimWindow,
  type LoadToken,
} from '../logic/wsMessages';
import { useDispatch } from '../store';
import type { Body, FlowSummary, WsDirection, WsMessageContent, WsMessagePage, WsMessageSummary } from '../types';
import { BodyView } from './BodyView';
import { VirtualList } from './VirtualList';

export const WS_ROW_HEIGHT = 28;

const DIRS: { id: WsDirection; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'sent', label: 'Sent' },
  { id: 'received', label: 'Received' },
];

function stopped(error: unknown, signal: AbortSignal): boolean {
  return signal.aborted || (error instanceof DOMException && error.name === 'AbortError');
}

export function WsMessages({ flow, session }: { flow: FlowSummary; session: string | null }) {
  const dispatch = useDispatch();
  const [dir, setDir] = useState<WsDirection>('all');
  const [q, setQ] = useState('');
  const [applied, setApplied] = useState('');
  const [messages, setMessages] = useState<Map<number, WsMessageSummary>>(() => new Map());
  const [matched, setMatched] = useState(0);
  const [total, setTotal] = useState(flow.ws_messages ?? 0);
  const [selected, setSelected] = useState<number | null>(null);
  const [follow, setFollow] = useState(true);
  const [content, setContent] = useState<WsMessageContent | null>(null);
  const gen = useRef(0);
  const covered = useRef(-1);
  const triedOlder = useRef<number | null>(null);
  const loadingOlder = useRef(false);
  const totalRef = useRef(flow.ws_messages ?? 0);
  totalRef.current = flow.ws_messages ?? 0;

  const id = flow.id;
  const filtering = dir !== 'all' || applied !== '';

  useEffect(() => {
    const timer = setTimeout(() => setApplied(q.slice(0, 200)), 200);
    return () => clearTimeout(timer);
  }, [q]);

  const take = useCallback(
    (page: WsMessagePage, side: 'newest' | 'oldest') => {
      setTotal(page.total);
      setMatched(page.matched);
      setMessages((prev) => trimWindow(mergeMessages(prev, page.messages), MAX_KEPT, side));
    },
    [],
  );

  useEffect(() => {
    const started = startLoad(id, gen.current);
    gen.current = started.generation;
    const token = started.token;
    covered.current = -1;
    triedOlder.current = null;
    setMessages(new Map());
    setSelected(null);
    setFollow(true);
    setContent(null);
    const ac = new AbortController();
    let stoppedLoad = false;

    const load = async () => {
      let from = tailFrom(totalRef.current);
      for (let guard = 0; guard < 50; guard++) {
        if (stoppedLoad || !acceptLoad(token, gen.current)) return;
        const page = await api.wsMessages(id, { from, limit: PAGE_LIMIT, dir, q: applied }, ac.signal, session);
        if (stoppedLoad || !acceptLoad(token, gen.current)) return;
        take(page, 'newest');
        if (from < tailFrom(page.total) && page.messages.length >= PAGE_LIMIT) {
          from = tailFrom(page.total);
          setMessages(new Map());
          continue;
        }
        const last = page.messages.length > 0 ? page.messages[page.messages.length - 1]!.index : null;
        const next = continueFrom(last, page.messages.length, page.total);
        if (next !== null && next > from) {
          from = next;
          continue;
        }
        if (page.messages.length === 0 && from > 0) {
          from = Math.max(0, from - PAGE_LIMIT);
          continue;
        }
        covered.current = page.total;
        if (totalRef.current > page.total) {
          from = page.total;
          continue;
        }
        return;
      }
    };

    load().catch((e: unknown) => {
      if (stoppedLoad || stopped(e, ac.signal) || !acceptLoad(token, gen.current)) return;
      dispatch({ type: 'toast', text: e instanceof ApiError ? e.message : 'Could not load messages' });
    });
    return () => {
      stoppedLoad = true;
      ac.abort();
    };
  }, [id, dir, applied, session, dispatch, take]);

  useEffect(() => {
    const count = flow.ws_messages ?? 0;
    if (covered.current < 0 || covered.current >= count) return;
    const token: LoadToken = { id, generation: gen.current };
    const ac = new AbortController();
    let stoppedLoad = false;

    const loadNew = async () => {
      // A live trim can drop messages the tester had scrolled to, so the next scroll up may fetch them again.
      triedOlder.current = null;
      let from = covered.current;
      for (let guard = 0; guard < 50; guard++) {
        if (stoppedLoad || !acceptLoad(token, gen.current) || from < 0) return;
        const page = await api.wsMessages(id, { from, limit: PAGE_LIMIT, dir, q: applied }, ac.signal, session);
        if (stoppedLoad || !acceptLoad(token, gen.current)) return;
        // New messages are the newest. Keeping those, even while scrolled up, is the 5,000 cap.
        take(page, 'newest');
        const last = page.messages.length > 0 ? page.messages[page.messages.length - 1]!.index : null;
        const next = continueFrom(last, page.messages.length, page.total);
        covered.current = Math.max(covered.current, next === null ? page.total : (last ?? from) + 1);
        if (next === null || next <= from) return;
        from = next;
      }
    };

    loadNew().catch((e: unknown) => {
      if (stoppedLoad || stopped(e, ac.signal) || !acceptLoad(token, gen.current)) return;
      dispatch({ type: 'toast', text: e instanceof ApiError ? e.message : 'Could not load messages' });
    });
    return () => {
      stoppedLoad = true;
      ac.abort();
    };
  }, [flow.ws_messages, id, dir, applied, session, dispatch, take]);

  useEffect(() => {
    if (selected === null) {
      setContent(null);
      return;
    }
    const token: LoadToken = { id, generation: gen.current };
    const index = selected;
    const ac = new AbortController();
    api
      .wsMessage(id, index, ac.signal, session)
      .then((body) => {
        if (acceptLoad(token, gen.current)) setContent(body);
      })
      .catch((e: unknown) => {
        if (stopped(e, ac.signal) || !acceptLoad(token, gen.current)) return;
        dispatch({ type: 'toast', text: e instanceof ApiError ? e.message : 'Could not load the message' });
      });
    return () => ac.abort();
  }, [id, selected, session, dispatch]);

  const rows = useMemo(() => sortedMessages(messages), [messages]);
  const oldest = oldestIndex(messages);
  const note = newestNote(flow.ws_messages ?? total, rows.length, oldest ?? 0);
  const header = connectionHeader(flow.ws_closed_by, flow.ws_close_code, flow.ws_close_reason, flow.ws_messages ?? total);

  const loadOlder = useCallback(() => {
    let from = olderFrom(oldest);
    if (from === null || loadingOlder.current || triedOlder.current === from) return;
    loadingOlder.current = true;
    const token: LoadToken = { id, generation: gen.current };
    const walk = async () => {
      for (let guard = 0; guard < 20 && from !== null; guard++) {
        if (triedOlder.current === from || !acceptLoad(token, gen.current)) return;
        triedOlder.current = from;
        const page = await api.wsMessages(id, { from, limit: PAGE_LIMIT, dir, q: applied }, undefined, session);
        if (!acceptLoad(token, gen.current)) return;
        take(page, 'oldest');
        if (page.messages.length > 0 || from === 0) return;
        from = Math.max(0, from - PAGE_LIMIT);
      }
    };
    walk()
      .catch(() => {
        triedOlder.current = null;
      })
      .finally(() => {
        loadingOlder.current = false;
      });
  }, [oldest, id, dir, applied, session, take]);

  const onRange = useCallback(
    (first: number) => {
      if (first === 0 && !follow) loadOlder();
    },
    [follow, loadOlder],
  );

  const select = (index: number) => {
    setSelected(index);
    setFollow(followAfter('select', follow));
  };

  const copy = async () => {
    if (!content) return;
    const text = content.type === 'binary' ? (content.hex ?? '') : (content.text ?? '');
    const ok = await copyText(text);
    dispatch({ type: 'toast', text: ok ? 'Message copied' : 'Copy failed' });
  };

  const shown = content && content.index === selected ? content : null;
  const textBody: Body | null =
    shown && shown.type === 'text' ? { text: shown.text, size: shown.size, truncated: false, binary: false } : null;

  return (
    <div className="ws-pane">
      <div className="ws-head">{header}</div>
      <div className="ws-bar">
        <input
          className="textin"
          type="search"
          placeholder="Filter messages…"
          value={q}
          maxLength={200}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Filter messages"
        />
        <div className="seg" role="group" aria-label="Direction">
          {DIRS.map((item) => (
            <button key={item.id} type="button" className={dir === item.id ? 'on' : ''} aria-pressed={dir === item.id} onClick={() => setDir(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
        {filtering && <span className="ws-count">{matchLabel(matched, total)}</span>}
      </div>
      {note && <div className="ws-note">{note}</div>}
      <div className="ws-list">
        {rows.length === 0 && <div className="empty">{filtering ? 'No messages match.' : 'No messages yet.'}</div>}
        <VirtualList
          label="WebSocket messages"
          count={rows.length}
          rowHeight={WS_ROW_HEIGHT}
          follow={follow}
          onFollowChange={(next) => setFollow(followAfter(next ? 'scroll-bottom' : 'scroll-up', follow))}
          onRange={onRange}
          renderRow={(i) => {
            const message = rows[i]!;
            const on = selected === message.index;
            return (
              <div
                key={message.index}
                className={`ws-row${on ? ' sel' : ''}`}
                style={{ height: WS_ROW_HEIGHT }}
                role="option"
                aria-selected={on}
                onClick={() => select(message.index)}
              >
                <span className={`ws-dir ${message.from_client ? 'up' : 'down'}`} aria-label={message.from_client ? 'Sent' : 'Received'}>
                  {message.from_client ? '↑' : '↓'}
                </span>
                <span className="c-time">{formatTime(message.ts)}</span>
                <span className="ws-type">{message.type}</span>
                <span className="c-num">{formatSize(message.size)}</span>
                <span className="ws-preview" title={message.preview.length > 300 ? message.preview.slice(0, 300) : message.preview}>
                  {message.preview}
                </span>
                <span className="c-badges">
                  {message.dropped && <span className="tag fault">dropped</span>}
                  {message.injected && <span className="tag edited">injected</span>}
                </span>
              </div>
            );
          }}
        />
      </div>
      {selected !== null && (
        <div className="ws-view">
          <div className="codehead">
            <span>{shown ? `${shown.type} · ${formatSize(shown.size)}` : 'Loading…'}</span>
            <button type="button" className="btn small" onClick={() => void copy()} disabled={!shown}>
              Copy
            </button>
          </div>
          {!shown && <div className="note">Loading…</div>}
          {shown?.truncated && <div className="note warn">{OVERSIZE}</div>}
          {shown?.type === 'binary' && shown.size > HEX_DUMP_BYTES && <div className="note">Showing the first 4 KiB.</div>}
          {textBody && <BodyView body={textBody} label="Message" />}
          {shown?.type === 'binary' && <pre className="hexdump">{hexDump(shown.hex ?? '')}</pre>}
        </div>
      )}
    </div>
  );
}
