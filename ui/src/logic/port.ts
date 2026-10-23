// Spec 022, slice B: the Wi-Fi proxy port. The window checks again; these texts only guide typing.

export const DEFAULT_PORT = 8889;
const UI_PORT = 8081;
const WIREGUARD_PORT = 51820;

export const PORT_HINT = '1024–65535. Not 8081 (this window) or a port another app uses.';

/** The typed port, or null when it is not a whole number of at most 5 digits. */
export function parsePort(text: string): number | null {
  const t = text.trim();
  return /^\d{1,5}$/.test(t) ? Number(t) : null;
}

/** Why the typed port cannot be the next one, before the window is asked; null when it may be. */
export function portProblem(text: string, current: number): string | null {
  const port = parsePort(text);
  if (port === null) return 'The port must be a whole number.';
  if (port < 1024 || port > 65535) return 'The port must be 1024–65535.';
  if (port === UI_PORT) return "Port 8081 is the Wiretrace window's port.";
  if (port === WIREGUARD_PORT) return "Port 51820 is the WireGuard tunnel's port.";
  if (port === current) return 'That is the port this session already uses.';
  return null;
}

export function freeLine(port: number, free: boolean): string {
  return free ? `Port ${port} is free.` : `Port ${port} is in use by another app.`;
}

export function restartNote(port: number, macIp: string | null): string {
  return (
    `This session is saved and a new one starts on port ${port}. ` +
    `Then set the Wi-Fi proxy on every phone to ${macIp ?? '<Mac IP>'}:${port}. ` +
    'Wiretrace keeps this port for the next sessions.'
  );
}
