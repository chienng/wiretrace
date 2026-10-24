import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { computeWindow, isNearBottom, scrollTopToReveal } from '../logic/virtual';

interface Props {
  count: number;
  rowHeight: number;
  overscan?: number;
  renderRow: (index: number) => ReactNode;
  /** Keep the view pinned to the newest row. */
  follow: boolean;
  onFollowChange?: (follow: boolean) => void;
  /** Scrolls the row into view whenever `revealKey` changes. */
  revealIndex?: number | null;
  revealKey?: unknown;
  /** Arrow keys move the selection: -1 or +1. */
  onStep?: (delta: number) => void;
  /** Any other key while the list has focus. */
  onKey?: (e: KeyboardEvent) => void;
  /** The first and last row on screen, whenever they change; -1, -1 when there are none. */
  onRange?: (first: number, last: number) => void;
  className?: string;
  label: string;
}

export function VirtualList({
  count,
  rowHeight,
  overscan = 8,
  renderRow,
  follow,
  onFollowChange,
  revealIndex = null,
  revealKey,
  onStep,
  onKey,
  onRange,
  className,
  label,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(0);
  const followRef = useRef(follow);
  followRef.current = follow;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setHeight(el.clientHeight);
    const ro = new ResizeObserver(() => setHeight(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setScrollTop(el.scrollTop);
    const near = isNearBottom(el.scrollTop, el.clientHeight, el.scrollHeight);
    if (near !== followRef.current) onFollowChange?.(near);
  }, [onFollowChange]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el && follow) el.scrollTop = el.scrollHeight;
  }, [count, follow, height]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || revealIndex === null || revealIndex < 0) return;
    el.scrollTop = scrollTopToReveal(revealIndex, rowHeight, el.clientHeight, el.scrollTop);
    // Only a new reveal request moves the view.
  }, [revealKey]);

  const first = count === 0 ? -1 : Math.min(count - 1, Math.floor(scrollTop / rowHeight));
  const last = count === 0 ? -1 : Math.min(count - 1, Math.max(first, Math.ceil((scrollTop + height) / rowHeight) - 1));
  useEffect(() => {
    onRange?.(first, last);
  }, [first, last, onRange]);

  const win = computeWindow({ scrollTop, viewportHeight: height, rowHeight, count, overscan });
  const rows: ReactNode[] = [];
  for (let i = win.start; i < win.end; i++) rows.push(renderRow(i));

  const onKeyDown = (e: KeyboardEvent) => {
    if (onStep && e.key === 'ArrowDown') {
      e.preventDefault();
      onStep(1);
    } else if (onStep && e.key === 'ArrowUp') {
      e.preventDefault();
      onStep(-1);
    } else {
      onKey?.(e);
    }
  };

  return (
    <div
      ref={ref}
      className={`vlist ${className ?? ''}`}
      onScroll={onScroll}
      onKeyDown={onKeyDown}
      tabIndex={0}
      role="listbox"
      aria-label={label}
    >
      <div style={{ height: win.totalHeight, position: 'relative' }}>
        <div style={{ transform: `translateY(${win.offsetTop}px)` }}>{rows}</div>
      </div>
    </div>
  );
}
