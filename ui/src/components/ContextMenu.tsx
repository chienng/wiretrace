import { useEffect, useRef } from 'react';

export interface MenuItem {
  label: string;
  onSelect: () => void;
  /** Why the item is off; the item is disabled when set. */
  disabledReason?: string;
  /** A separator above this item. */
  divided?: boolean;
}

export interface MenuAt {
  x: number;
  y: number;
}

/** A right-click menu at the pointer; any click outside, Escape, scrolling or resizing closes it. */
export function ContextMenu({ at, items, label, onClose }: { at: MenuAt; items: MenuItem[]; label: string; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onClose);
    window.addEventListener('scroll', onClose, true);
    ref.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    return () => {
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onClose);
      window.removeEventListener('scroll', onClose, true);
    };
  }, [onClose]);

  const left = Math.min(at.x, window.innerWidth - 260);
  const top = Math.min(at.y, window.innerHeight - 34 * items.length - 16);

  return (
    <div ref={ref} className="ctxmenu" role="menu" aria-label={label} style={{ left: Math.max(4, left), top: Math.max(4, top) }}>
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          className={`ctx-i${item.divided ? ' divided' : ''}`}
          disabled={item.disabledReason !== undefined}
          title={item.disabledReason}
          onClick={() => {
            onClose();
            item.onSelect();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
