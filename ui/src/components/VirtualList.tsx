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

  const win = computeWindow({ scrollTop, viewportHeight: height, rowHeight, count, overscan });
  const rows: ReactNode[] = [];
  for (let i = win.start; i < win.end; i++) rows.push(renderRow(i));

  const onKeyDown = (e: KeyboardEvent) => {
    if (!onStep) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      onStep(1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      onStep(-1);
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
