import { describe, expect, it } from 'vitest';
import { DEFAULT_PORT, freeLine, parsePort, PORT_HINT, portProblem, restartNote } from './port';

// Spec 022, slice B.

describe('the port field', () => {
  it('reads whole numbers of up to 5 digits only', () => {
    expect(parsePort(' 8890 ')).toBe(8890);
    for (const text of ['', 'abc', '88.9', '-8890', '123456', '8 890', '٨٨٩٠']) expect(parsePort(text)).toBeNull();
  });
  it('says why a port cannot be the next one, like the window does', () => {
    expect(portProblem('8890', 8889)).toBeNull();
    expect(portProblem('8888', 8889)).toBeNull();
    expect(portProblem('x', 8889)).toBe('The port must be a whole number.');
    expect(portProblem('1023', 8889)).toBe('The port must be 1024–65535.');
    expect(portProblem('65536', 8889)).toBe('The port must be 1024–65535.');
    expect(portProblem('8081', 8889)).toBe("Port 8081 is the Wiretrace window's port.");
    expect(portProblem('51820', 8889)).toBe("Port 51820 is the WireGuard tunnel's port.");
    expect(portProblem('8889', 8889)).toBe('That is the port this session already uses.');
  });
  it('texts', () => {
    expect(DEFAULT_PORT).toBe(8889);
    expect(PORT_HINT).toBe('1024–65535. Not 8081 (this window) or a port another app uses.');
    expect(freeLine(8890, true)).toBe('Port 8890 is free.');
    expect(freeLine(8890, false)).toBe('Port 8890 is in use by another app.');
    expect(restartNote(8890, '192.168.1.20')).toBe(
      'This session is saved and a new one starts on port 8890. Then set the Wi-Fi proxy on every phone to 192.168.1.20:8890. Wiretrace keeps this port for the next sessions.',
    );
    expect(restartNote(8890, null)).toContain('<Mac IP>:8890');
  });
});
