import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { dragWidth, keyWidth, type Pane } from '../logic/paneWidth';

interface Props {
  label: string;
  /** `start`: the pane left of the handle (the sidebar). `end`: the pane right of it (a detail panel). */
  edge: 'start' | 'end';
  pane: Pane;
}

/** The border between two panes, dragged or moved with the arrow keys (spec 024). */
export function Splitter({ label, edge, pane }: Props) {
  const grow = edge === 'start' ? 1 : -1;
  const drag = useRef<{ x: number; width: number; last: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => () => document.body.classList.remove('resizing'), []);

  const end = () => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    document.body.classList.remove('resizing');
    setDragging(false);
    if (d.last !== d.width) pane.choose(d.last);
    else pane.release();
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, width: pane.width, last: pane.width };
    document.body.classList.add('resizing');
    setDragging(true);
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    // A button released outside the window may not send pointerup.
    if (e.buttons === 0) return end();
    d.last = dragWidth(d.width, e.clientX - d.x, grow, pane);
    pane.preview(d.last);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = keyWidth(e.key, e.shiftKey, pane.width, grow, pane);
    if (next === null) return;
    e.preventDefault();
    if (next === 'reset') pane.reset();
    else if (next !== pane.width) pane.choose(next);
  };

  return (
    <div
      className={`splitter ${edge}${dragging ? ' dragging' : ''}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={pane.width}
      aria-valuemin={pane.min}
      aria-valuemax={pane.max}
      tabIndex={0}
      title="Drag to resize. Double-click for the default width."
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onDoubleClick={pane.reset}
      onKeyDown={onKeyDown}
    />
  );
}
