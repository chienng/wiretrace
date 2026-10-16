import type { FlowDetail, FlowSummary, Headers } from '../types';
import { flowUrl } from './filters';

/** POSIX single-quote escaping: close the quote, add an escaped quote, reopen. */
export function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/** Headers curl must manage itself: a copied value yields an undecoded body or a wrong length. */
const CURL_MANAGED = new Set(['accept-encoding', 'content-length']);

export function buildCurl(detail: Pick<FlowDetail, 'summary' | 'request'>): string {
  const { summary, request } = detail;
  const parts = ['curl', '-X', shellQuote(summary.method), shellQuote(flowUrl(summary))];
  const headers: Headers = request.headers.filter(([name]) => !name.startsWith(':'));
  for (const [name, value] of headers) {
    if (!CURL_MANAGED.has(name.toLowerCase())) parts.push('-H', shellQuote(`${name}: ${value}`));
  }
  if (headers.some(([name]) => name.toLowerCase() === 'accept-encoding')) parts.push('--compressed');
  const text = request.body.text;
  if (text !== null && text !== '') parts.push('--data-raw', shellQuote(text));
  return parts.join(' ');
}

/** `<mocks_dir>/<METHOD><path without query>.json`, used when the server sends no `mock_path`. */
export function mockFilePath(mocksDir: string, flow: Pick<FlowSummary, 'method' | 'path'>): string {
  const path = flow.path.split(/[?#]/)[0] ?? '';
  const dir = mocksDir.replace(/\/+$/, '');
  return `${dir}/${flow.method.toUpperCase()}${path.startsWith('/') ? path : `/${path}`}.json`;
}
