/** View choices remembered by the browser (spec 028). Each key holds only the non-default value. */

type Reader = Pick<Storage, 'getItem'> | null;
type Writer = Pick<Storage, 'setItem' | 'removeItem'> | null;

function isStored(storage: Reader, key: string, value: string): boolean {
  try {
    return storage?.getItem(key) === value;
  } catch {
    return false;
  }
}

function storeChoice(storage: Writer, key: string, value: string, on: boolean): void {
  try {
    if (on) storage?.setItem(key, value);
    else storage?.removeItem(key);
  } catch {
    // Storage full or off: the choice lasts until the window closes.
  }
}

const SIDEBAR_KEY = 'wiretrace.pane.traffic.sidebar.state';

/** Whether the tester hid the Traffic sidebar; shown unless stored as hidden. */
export function loadSidebarHidden(storage: Reader): boolean {
  return isStored(storage, SIDEBAR_KEY, 'hidden');
}

export function storeSidebarHidden(storage: Writer, hidden: boolean): void {
  storeChoice(storage, SIDEBAR_KEY, 'hidden', hidden);
}
