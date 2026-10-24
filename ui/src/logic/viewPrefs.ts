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

export type BodyViewChoice = 'json' | 'text';
const BODY_KEY = 'wiretrace.body.view';

/** How a JSON body is shown, in every body view: the foldable tree unless stored as text. */
export function loadBodyView(storage: Reader): BodyViewChoice {
  return isStored(storage, BODY_KEY, 'text') ? 'text' : 'json';
}

export function storeBodyView(storage: Writer, view: BodyViewChoice): void {
  storeChoice(storage, BODY_KEY, 'text', view === 'text');
}

export type TrafficLayout = 'list' | 'tree';
const LAYOUT_KEY = 'wiretrace.pane.traffic.layout';

/** Traffic as the flat list unless stored as tree. */
export function loadLayout(storage: Reader): TrafficLayout {
  return isStored(storage, LAYOUT_KEY, 'tree') ? 'tree' : 'list';
}

export function storeLayout(storage: Writer, layout: TrafficLayout): void {
  storeChoice(storage, LAYOUT_KEY, 'tree', layout === 'tree');
}
