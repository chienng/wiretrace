import { describe, expect, it } from 'vitest';
import { computeWindow, isNearBottom, scrollTopToReveal } from './virtual';

const base = { rowHeight: 20, overscan: 2 };

describe('computeWindow', () => {
  it('covers the viewport plus overscan', () => {
    const w = computeWindow({ ...base, scrollTop: 200, viewportHeight: 100, count: 1000 });
    // rows 10..14 are visible; two extra on each side
    expect(w).toEqual({ start: 8, end: 17, offsetTop: 160, totalHeight: 20000 });
  });
  it('clamps at the start and the end', () => {
    expect(computeWindow({ ...base, scrollTop: 0, viewportHeight: 100, count: 1000 }).start).toBe(0);
    const end = computeWindow({ ...base, scrollTop: 19_900, viewportHeight: 100, count: 1000 });
    expect(end.end).toBe(1000);
  });
  it('handles an empty list and a short list', () => {
    expect(computeWindow({ ...base, scrollTop: 0, viewportHeight: 100, count: 0 })).toEqual({ start: 0, end: 0, offsetTop: 0, totalHeight: 0 });
    expect(computeWindow({ ...base, scrollTop: 0, viewportHeight: 500, count: 3 })).toMatchObject({ start: 0, end: 3 });
  });
  it('clamps a scrollTop beyond the content', () => {
    const w = computeWindow({ ...base, scrollTop: 999_999, viewportHeight: 100, count: 50 });
    expect(w.end).toBe(50);
    expect(w.start).toBeLessThan(w.end);
  });
  it('renders a bounded number of rows for 10,000 flows', () => {
    const w = computeWindow({ rowHeight: 28, overscan: 8, scrollTop: 140_000, viewportHeight: 600, count: 10_000 });
    expect(w.end - w.start).toBeLessThan(50);
  });
});

describe('scrollTopToReveal', () => {
  it('leaves the scroll position when the row is visible', () => {
    expect(scrollTopToReveal(12, 20, 100, 200)).toBe(200);
  });
  it('scrolls up or down by the least amount', () => {
    expect(scrollTopToReveal(5, 20, 100, 200)).toBe(100);
    expect(scrollTopToReveal(30, 20, 100, 200)).toBe(520);
  });
});

describe('isNearBottom', () => {
  it('is true at the bottom, false above', () => {
    expect(isNearBottom(900, 100, 1000)).toBe(true);
    expect(isNearBottom(500, 100, 1000)).toBe(false);
  });
});
