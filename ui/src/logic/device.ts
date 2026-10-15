import type { AppState, DeviceStatus } from '../types';

export type Tone = 'ok' | 'wait' | 'off' | 'bad';

export interface LogSourceInfo {
  id: 'android' | 'ios' | 'ios-sim';
  name: string;
  tool: string;
  target: string;
}

export const LOG_SOURCES: LogSourceInfo[] = [
  { id: 'android', name: 'Android device', tool: 'adb logcat', target: 'android' },
  { id: 'ios', name: 'iPhone', tool: 'pymobiledevice3 syslog', target: 'ios' },
  { id: 'ios-sim', name: 'iOS Simulator', tool: 'simctl log stream', target: 'ios-sim' },
];

export const STATE_LABELS: Record<DeviceStatus['state'], string> = {
  waiting: 'Waiting',
  streaming: 'Streaming',
  several: 'More than one device',
  stopped: 'Stopped',
  error: 'Error',
};

const TONES: Record<DeviceStatus['state'], Tone> = { waiting: 'wait', streaming: 'ok', several: 'wait', stopped: 'off', error: 'bad' };

export function sourceInfo(id: string | null | undefined): LogSourceInfo | null {
  return LOG_SOURCES.find((s) => s.id === id) ?? null;
}

/** How the device is reached for its log: a cable, or not at all for the Simulator and the emulator. */
export function linkName(target: string): string {
  if (target === 'ios-sim') return 'Simulator';
  if (target === 'android-emu') return 'Emulator';
  return 'USB';
}

export interface Pill {
  text: string;
  tone: Tone;
  title: string;
}

/** The title bar pill, e.g. "Pixel 8 · Android 15 · USB", green while streaming. */
export function devicePill(state: Pick<AppState, 'device_logs' | 'device_logs_off' | 'device_status' | 'target'>): Pill {
  const source = sourceInfo(state.device_logs);
  if (!source) {
    return { text: 'Device logs off', tone: 'off', title: state.device_logs_off ? `Device logs are off: ${state.device_logs_off}` : 'Device logs are off' };
  }
  const status = state.device_status;
  if (!status) return { text: `${source.name} · starting`, tone: 'wait', title: `Device logs: ${source.tool}` };
  const device = status.model ? [status.model, status.os].filter(Boolean).join(' · ') : source.name;
  return {
    text: `${device} · ${linkName(state.target)}`,
    tone: TONES[status.state],
    title: `Device logs: ${STATE_LABELS[status.state]}${status.message ? ` (${status.message})` : ''}`,
  };
}
