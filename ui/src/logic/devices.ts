import { OFF_WHILE_VIEWING } from './presets';

/** The server's labels (`TARGET_LABELS` in cli/start.py), so the title bar has one before the list loads. */
export const DEVICE_LABELS: Record<string, string> = {
  ios: 'iPhone',
  android: 'Android phone',
  'android-emu': 'Android emulator',
  'ios-sim': 'iOS Simulator',
  device: 'Another device',
};

export function deviceLabel(target: string): string {
  return DEVICE_LABELS[target] ?? target;
}

/** "the iPhone", "the other device": the device in a sentence. */
export function devicePhrase(target: string): string {
  return target === 'device' ? 'the other device' : `the ${deviceLabel(target)}`;
}

export function modeLabel(mode: string): string {
  if (mode === 'wireguard') return 'WireGuard';
  return mode === 'both' ? 'Proxy + WireGuard' : 'Proxy';
}

/** The title bar's device menu: off while a previous session is open, like Setup, Rules and the preset menu. */
export function deviceMenuState(viewing: string | null): { disabled: boolean; title: string } {
  return viewing ? { disabled: true, title: OFF_WHILE_VIEWING } : { disabled: false, title: 'Switch the device' };
}

export const PIN_NOTE = 'the first device that connects is the one accepted.';

/** What the tester does on the phones when the session moves from one device to another. */
export function phoneSteps(mode: string, pinned: boolean, from: string, to: string): string[] {
  const old = devicePhrase(from);
  const next = devicePhrase(to);
  if (mode === 'wireguard') {
    return [`Turn the WireGuard tunnel off on ${old}, then on on ${next}. First time on this phone: scan the QR code in Setup.`];
  }
  const pin = `Remove the Wi-Fi proxy on ${old} first: ${PIN_NOTE}`;
  if (mode === 'proxy') return pinned ? [pin] : [];
  const steps = [`Disconnect ${old} (Wi-Fi proxy off, or tunnel off), then connect ${next} the same way. First time on this phone: follow Setup.`];
  return pinned ? [...steps, pin] : steps;
}

/** The switch dialog's device log line: the server's text is the app name, or "off (why)". */
export function deviceLogsLine(text: string): string {
  return text.startsWith('off (') && text.endsWith(')') ? `Off: ${text.slice(5, -1)}` : `On · ${text}`;
}
