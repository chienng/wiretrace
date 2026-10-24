import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { initialStore, type Store } from '../store';
import type { AppState } from '../types';
import { TitleBar } from './TitleBar';

const fixture = vi.hoisted(() => ({ store: null as unknown as Store, viewing: null as string | null }));

vi.mock('../store', async (original) => {
  const actual = await original<typeof import('../store')>();
  return {
    ...actual,
    useStore: () => fixture.store,
    useData: () => ({ flows: fixture.store.flows, tunnels: [], logs: fixture.store.logs, viewing: fixture.viewing }),
    useDispatch: () => () => undefined,
  };
});

const appState = {
  version: '0.10.1',
  preset: 'staging-example',
  target: 'pixel-example',
  mode: 'both',
  started_at: 1791900000,
  device_logs: 'android',
  device_logs_off: null,
  device_status: null,
  proxy_waiting: [],
  paused_count: 0,
  rules_on: 2,
  from_app: false,
  flow_count: 3,
} as unknown as AppState;

const render = (newCount = 0) => renderToStaticMarkup(createElement(TitleBar, { newCount }));

/** The opening tag of the first button whose attributes contain `needle`. */
const button = (html: string, needle: string) => html.match(new RegExp(`<button[^>]*${needle}[^>]*>`))?.[0] ?? '';

describe('TitleBar', () => {
  beforeEach(() => {
    fixture.store = { ...initialStore, loaded: true, phase: 'live', appState };
    fixture.viewing = null;
  });

  it('names the icon-only Pause and Clear buttons while recording', () => {
    const html = render();
    expect(button(html, 'aria-label="Pause"')).toContain('title="Pause the list"');
    expect(button(html, 'aria-label="Pause"')).toContain('aria-pressed="false"');
    expect(button(html, 'aria-label="Clear"')).toContain('title="Clear: hide what is listed now"');
    const icons = html.match(/<svg[^>]*>/g) ?? [];
    expect(icons.length).toBeGreaterThan(0);
    for (const icon of icons) expect(icon).toContain('aria-hidden="true"');
  });

  it('carries the new count in the Resume button while paused', () => {
    fixture.store = { ...fixture.store, ui: { ...fixture.store.ui, frozen: new Set() } };
    const html = render(12);
    const resume = button(html, 'aria-label="Resume, 12 new requests"');
    expect(resume).toContain('aria-pressed="true"');
    expect(resume).toContain('title="Resume the list"');
    expect(html).toContain('12 new</span>');
    expect(html).toContain('List paused');
  });

  it('names the preset and device menus', () => {
    const html = render();
    expect(button(html, 'aria-label="Preset: staging-example"')).toContain('aria-haspopup="menu"');
    expect(html).toMatch(/aria-label="Device: [^"]+"/);
    expect(html).toContain('title="2 rules on"');
  });

  it('shows Report bug as a plain button', () => {
    const html = render();
    const report = html.match(/<button[^>]*>(?:(?!<\/button>).)*Report bug<\/button>/)?.[0] ?? '';
    expect(report).not.toBe('');
    expect(report).not.toMatch(/class="[^"]*primary/);
  });

  it('has no Pause or Clear while a previous session is open, and turns the menus, Rules and Setup off', () => {
    fixture.viewing = '2026-10-13_example';
    const html = render();
    expect(html).not.toContain('aria-label="Pause"');
    expect(html).not.toContain('aria-label="Clear"');
    expect(button(html, 'aria-label="Preset: ')).toContain('disabled=""');
    expect(button(html, 'aria-label="Device: ')).toContain('disabled=""');
    expect(button(html, 'aria-pressed="false"')).toContain('disabled=""');
    const setup = html.match(/<button[^>]*>(?:(?!<\/button>).)*Setup<\/button>/)?.[0] ?? '';
    expect(setup).toContain('disabled=""');
  });
});
