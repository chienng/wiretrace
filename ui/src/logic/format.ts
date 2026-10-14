const pad = (n: number, w = 2) => String(n).padStart(w, '0');

/** Unix seconds → HH:MM:SS.mmm in local time. */
export function formatTime(ts: number | null | undefined): string {
  if (ts === null || ts === undefined) return '';
  const d = new Date(ts * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1) return '<1 ms';
  return `${Math.round(ms).toLocaleString('en-US')} ms`;
}

export function formatSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Seconds → HH:MM:SS for the recording timer. */
export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

export type StatusClass = 's2' | 's3' | 's4' | 's5' | 'ws' | 'none';

export function statusClass(status: number | null): StatusClass {
  if (status === null) return 'none';
  if (status === 101) return 'ws';
  if (status >= 500) return 's5';
  if (status >= 400) return 's4';
  if (status >= 300) return 's3';
  if (status >= 200) return 's2';
  return 'none';
}

export function methodClass(method: string): string {
  switch (method.toUpperCase()) {
    case 'GET':
      return 'get';
    case 'POST':
      return 'post';
    case 'PUT':
    case 'PATCH':
      return 'put';
    case 'DELETE':
      return 'del';
    default:
      return '';
  }
}

export function methodLabel(method: string): string {
  return method.toUpperCase() === 'DELETE' ? 'DEL' : method.toUpperCase();
}
