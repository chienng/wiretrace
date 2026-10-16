import type { PresetInfo } from '../types';

/** Why Setup, Rules and the preset menu are off while a previous session is open. */
export const OFF_WHILE_VIEWING = 'Off while a previous session is open';

/** The title bar's preset menu: off while a previous session is open, like Setup and Rules. */
export function presetMenuState(viewing: string | null): { disabled: boolean; title: string } {
  return viewing ? { disabled: true, title: OFF_WHILE_VIEWING } : { disabled: false, title: 'Switch the preset' };
}

/** The switch dialog's device log line for this preset and the session's target. */
export function deviceLogsText(preset: PresetInfo, target: string): string {
  if (preset.device_logs && preset.app) return `On · ${preset.app}`;
  if (target === 'device') return 'Off: --target device has no device log';
  const key = target.startsWith('android') ? 'android_package' : 'ios_process';
  return `Off: the preset has no app.${key}`;
}
