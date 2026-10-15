import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import type { Action } from './store';
import { openSession } from './viewing';

const NAME = '2026-10-15_080000_myapp_android';

afterEach(() => vi.restoreAllMocks());

describe('openSession', () => {
  it('opens the session when the server and every read succeed', async () => {
    vi.spyOn(api, 'view').mockResolvedValue({ viewing: NAME, cut_off: false, requests: 0 });
    vi.spyOn(api, 'flows').mockResolvedValue([]);
    vi.spyOn(api, 'logs').mockResolvedValue([]);
    const actions: Action[] = [];
    expect(await openSession((a) => actions.push(a), NAME)).toBe(true);
    expect(actions.map((a) => a.type)).toEqual(['viewOpened']);
  });

  it('sends the server back to live when the reads fail after it opened the session', async () => {
    const view = vi.spyOn(api, 'view').mockResolvedValue({ viewing: NAME, cut_off: false, requests: 0 });
    vi.spyOn(api, 'flows').mockRejectedValue(new ApiError(500, 'Could not read that session'));
    vi.spyOn(api, 'logs').mockResolvedValue([]);
    const actions: Action[] = [];
    expect(await openSession((a) => actions.push(a), NAME)).toBe(false);
    expect(view.mock.calls).toEqual([[NAME], [null]]);
    expect(actions.map((a) => a.type)).toEqual(['toast', 'viewClosed']);
  });

  it('still closes the page view when going back to live fails too', async () => {
    const view = vi.spyOn(api, 'view').mockImplementation(async (s) => {
      if (s === null) throw new ApiError(500, 'down');
      return { viewing: NAME, cut_off: false, requests: 0 };
    });
    vi.spyOn(api, 'flows').mockRejectedValue(new ApiError(500, 'down'));
    vi.spyOn(api, 'logs').mockResolvedValue([]);
    const actions: Action[] = [];
    expect(await openSession((a) => actions.push(a), NAME)).toBe(false);
    expect(view).toHaveBeenCalledTimes(2);
    expect(actions.map((a) => a.type)).toEqual(['toast', 'viewClosed']);
  });

  it('leaves the server alone when it refused to open the session', async () => {
    const view = vi.spyOn(api, 'view').mockRejectedValue(new ApiError(404, 'No such session'));
    const actions: Action[] = [];
    expect(await openSession((a) => actions.push(a), NAME)).toBe(false);
    expect(view.mock.calls).toEqual([[NAME]]);
    expect(actions.map((a) => a.type)).toEqual(['toast']);
  });
});
