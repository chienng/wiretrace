import type { AppState } from '../types';

const KEY = 'wiretrace.appHint';
const DISMISSED = 'dismissed';

export const APP_HINT =
  'Started from the Wiretrace app. Change the preset or the device here in the title bar. To stop and save the session, use the Wiretrace menu (the W icon at the top right of the screen).';

export const APP_STOP_TIP = 'Stop and save from the Wiretrace menu (the W icon at the top right of the screen)';

/** The strip under the title bar: an app session, the live one, until Got it. */
export function showAppHint(state: Pick<AppState, 'from_app'> | null, viewing: string | null, dismissed: boolean): boolean {
  return !!state?.from_app && !viewing && !dismissed;
}

/** Got it, in this browser; a refused storage reads as not dismissed. */
export function loadDismissed(storage: Pick<Storage, 'getItem'> | null): boolean {
  try {
    return storage?.getItem(KEY) === DISMISSED;
  } catch {
    return false;
  }
}

export function storeDismissed(storage: Pick<Storage, 'setItem'> | null): void {
  try {
    storage?.setItem(KEY, DISMISSED);
  } catch {
    // Storage full or off: the strip stays hidden until the window reloads.
  }
}
