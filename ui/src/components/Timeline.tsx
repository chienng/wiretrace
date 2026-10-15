import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { formatTime } from '../logic/format';
import {
  bucket,
  columnOf,
  LOG_ERROR,
  LOG_WARN,
  REQ_CLIENT,
  REQ_OK,
  REQ_SERVER,
  ticks,
  timeAt,
  timeRange,
  type Range,
} from '../logic/timeline';
import type { FlowSummary, LogLine } from '../types';

interface Props {
  flows: readonly FlowSummary[];
  lines: readonly LogLine[];
  /** The time span of the log rows on screen, shaded. */
  shown: Range | null;
  selected: number | null;
  onPick: (ts: number) => void;
}

const HEIGHT = 44;
const REQ_Y = 11;
const LOG_Y = 30;

function colors(): { green: string; orange: string; red: string; faint: string; line: string } {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim() || '#999';
  return { green: v('--green'), orange: v('--orange'), red: v('--red'), faint: v('--faint'), line: v('--line-strong') };
}

/** Requests and log lines on one time axis, one column per pixel; a click selects the line or request at that time. */
export function Timeline({ flows, lines, shown, selected, onPick }: Props) {
  const area = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    observer.observe(el);
    setWidth(Math.floor(el.clientWidth));
    return () => observer.disconnect();
  }, []);

  const range = useMemo(() => timeRange(flows, lines), [flows, lines]);
  const buckets = useMemo(() => (range && width > 0 ? bucket(flows, lines, range, width) : null), [flows, lines, range, width]);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext('2d');
    if (!el || !ctx) return;
    const ratio = window.devicePixelRatio || 1;
    el.width = Math.max(1, width) * ratio;
    el.height = HEIGHT * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, HEIGHT);
    if (!buckets) return;
    const c = colors();
    for (let x = 0; x < buckets.columns; x++) {
      const req = buckets.requests[x] as number;
      if (req) {
        ctx.fillStyle = req === REQ_SERVER ? c.red : req === REQ_CLIENT ? c.orange : req === REQ_OK ? c.green : c.faint;
        ctx.beginPath();
        ctx.arc(x + 0.5, REQ_Y, req >= REQ_CLIENT ? 3.5 : 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
      const log = buckets.logs[x] as number;
      if (log) {
        ctx.fillStyle = log === LOG_ERROR ? c.red : log === LOG_WARN ? c.orange : c.line;
        const h = log === LOG_ERROR ? 12 : 8;
        ctx.fillRect(x, LOG_Y - h / 2, 1, h);
      }
      if (buckets.crashes[x]) {
        ctx.fillStyle = c.red;
        ctx.fillRect(x - 1, LOG_Y - 9, 3, 18);
      }
    }
  }, [buckets, width]);

  if (!range) return <div className="timeline empty">The timeline shows requests and log lines once there are some.</div>;

  const left = (ts: number) => columnOf(ts, range, Math.max(1, width));
  const pick = (e: MouseEvent<HTMLDivElement>) => {
    const x = e.clientX - e.currentTarget.getBoundingClientRect().left;
    onPick(timeAt(Math.floor(x), range, Math.max(1, width)));
  };

  return (
    <div className="timeline">
      <div className="tl-labels">
        <span>Requests</span>
        <span>Logs</span>
      </div>
      <div className="tl-area" ref={area} onClick={pick} title="Click to jump to that time">
        <canvas ref={canvas} style={{ width: `${width}px`, height: `${HEIGHT}px` }} aria-label="Requests and log lines over time" />
        {shown && <div className="tl-shown" style={{ left: left(shown.start), width: Math.max(2, left(shown.end) - left(shown.start) + 1) }} />}
        {selected !== null && <div className="tl-mark" style={{ left: left(selected) }} />}
        <div className="tl-axis">
          {ticks(range, width).map((t) => (
            <span key={t} style={{ left: left(t) }}>
              {formatTime(t).slice(0, 8)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
