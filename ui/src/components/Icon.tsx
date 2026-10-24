import type { ReactNode } from 'react';

export type IconName = 'preset' | 'phone' | 'pause' | 'play' | 'clear' | 'rules' | 'setup' | 'bug';

/** 16 × 16 line icons drawn in `currentColor`; the knobs of `rules` are filled white. */
const PATHS: Record<IconName, ReactNode> = {
  preset: (
    <>
      <path d="M8 2l6 3-6 3-6-3z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M2 8.2l6 3 6-3M2 11.2l6 3 6-3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </>
  ),
  phone: (
    <>
      <rect x="4.5" y="1.5" width="7" height="13" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M7 12.2h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </>
  ),
  pause: <path d="M5.5 3.5v9M10.5 3.5v9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />,
  play: <path d="M5 3.5l7 4.5-7 4.5z" fill="currentColor" />,
  clear: (
    <>
      <circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M4.2 11.8l7.6-7.6" stroke="currentColor" strokeWidth="1.5" />
    </>
  ),
  rules: (
    <>
      <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <g fill="#fff" stroke="currentColor" strokeWidth="1.4">
        <circle cx="10.5" cy="4.5" r="1.6" />
        <circle cx="5.5" cy="8" r="1.6" />
        <circle cx="9" cy="11.5" r="1.6" />
      </g>
    </>
  ),
  setup: (
    <path
      d="M2.5 4.2l1.3 1.3 2.2-2.5M2.5 10.2l1.3 1.3 2.2-2.5M8 4.5h5.5M8 10.5h5.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
  bug: (
    <>
      <path d="M5.5 5.5a2.5 2.5 0 015 0" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <rect x="4.5" y="5.5" width="7" height="8" rx="3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M8 7.5v5M2.5 8.5h2M11.5 8.5h2M3 12.5l1.8-1M13 12.5l-1.8-1M3 4.5l1.8 1.2M13 4.5l-1.8 1.2"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </>
  ),
};

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={`icon${className ? ` ${className}` : ''}`} viewBox="0 0 16 16" width={14} height={14} aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}
