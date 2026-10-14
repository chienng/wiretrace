export interface WindowInput {
  scrollTop: number;
  viewportHeight: number;
  rowHeight: number;
  count: number;
  overscan: number;
}

export interface WindowRange {
  /** First rendered index (inclusive). */
  start: number;
  /** One past the last rendered index. */
  end: number;
  offsetTop: number;
  totalHeight: number;
}

export function computeWindow({ scrollTop, viewportHeight, rowHeight, count, overscan }: WindowInput): WindowRange {
  const totalHeight = count * rowHeight;
  if (count <= 0 || rowHeight <= 0) return { start: 0, end: 0, offsetTop: 0, totalHeight: 0 };
  const top = Math.min(Math.max(0, scrollTop), Math.max(0, totalHeight - viewportHeight));
  const first = Math.floor(top / rowHeight);
  const last = Math.ceil((top + Math.max(0, viewportHeight)) / rowHeight);
  const start = Math.max(0, first - overscan);
  const end = Math.min(count, last + overscan);
  return { start, end, offsetTop: start * rowHeight, totalHeight };
}

/** Smallest scrollTop that makes `index` fully visible; unchanged when it already is. */
export function scrollTopToReveal(
  index: number,
  rowHeight: number,
  viewportHeight: number,
  scrollTop: number,
): number {
  const rowTop = index * rowHeight;
  const rowBottom = rowTop + rowHeight;
  if (rowTop < scrollTop) return rowTop;
  if (rowBottom > scrollTop + viewportHeight) return Math.max(0, rowBottom - viewportHeight);
  return scrollTop;
}

export function isNearBottom(scrollTop: number, viewportHeight: number, totalHeight: number, slack = 4): boolean {
  return scrollTop + viewportHeight >= totalHeight - slack;
}
