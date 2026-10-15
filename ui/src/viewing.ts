import type { Dispatch } from 'react';
import { api, ApiError } from './api';
import { mergeFlows, mergeLogSets } from './logic/merge';
import type { Action } from './store';

function failed(dispatch: Dispatch<Action>, e: unknown, fallback: string): void {
  dispatch({ type: 'toast', text: e instanceof ApiError ? e.message : fallback });
}

/** Open a previous session read-only: the server reads it, then its flows and logs are loaded. */
export async function openSession(dispatch: Dispatch<Action>, name: string): Promise<boolean> {
  let opened;
  try {
    opened = await api.view(name);
  } catch (e) {
    failed(dispatch, e, 'Could not open that session');
    return false;
  }
  if (opened.viewing !== name) return false;
  try {
    const [flows, device, app] = await Promise.all([api.flows(name), api.logs('device', name), api.logs('app', name)]);
    dispatch({
      type: 'viewOpened',
      view: { name, flows: mergeFlows([], flows), logs: mergeLogSets({ device: [], app: [] }, [...device, ...app]), cutOff: !!opened.cut_off },
    });
    return true;
  } catch (e) {
    // The server already holds this session open and refuses live-only actions until it is closed.
    failed(dispatch, e, 'Could not open that session');
    await api.view(null).catch(() => undefined);
    dispatch({ type: 'viewClosed' });
    return false;
  }
}

export async function backToLive(dispatch: Dispatch<Action>): Promise<void> {
  try {
    await api.view(null);
  } catch (e) {
    failed(dispatch, e, 'Could not go back to the live session');
    return;
  }
  dispatch({ type: 'viewClosed' });
}
