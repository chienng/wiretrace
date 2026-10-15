import type { FlowSummary } from '../types';

export type DeviceKind = 'iphone' | 'android' | 'ios-sim' | 'android-emu';

export interface DeviceChoice {
  id: DeviceKind;
  label: string;
  sub: string;
  /** The `--target` that collects this device's logs. */
  target: string;
}

export const DEVICES: DeviceChoice[] = [
  { id: 'iphone', label: 'iPhone', sub: 'Physical device', target: 'ios' },
  { id: 'android', label: 'Android', sub: 'Physical device', target: 'android' },
  { id: 'ios-sim', label: 'iOS Simulator', sub: 'Needs Mac proxy', target: 'ios-sim' },
  { id: 'android-emu', label: 'Android emulator', sub: 'WireGuard / 10.0.2.2', target: 'android-emu' },
];

/** How the Android emulator reaches the Mac. */
export const EMULATOR_HOST = '10.0.2.2';
/** After this long on the Connect step without a connection, the guest Wi-Fi hint shows. */
export const NO_CONNECTION_HINT_S = 30;
const ONBOARDING_HOST = 'mitm.it';

export function deviceFromTarget(target: string): DeviceKind {
  switch (target) {
    case 'android':
      return 'android';
    case 'ios-sim':
      return 'ios-sim';
    case 'android-emu':
      return 'android-emu';
    default:
      return 'iphone';
  }
}

export function deviceChoice(kind: DeviceKind): DeviceChoice {
  return DEVICES.find((d) => d.id === kind) as DeviceChoice;
}

/** The `Endpoint` of a WireGuard configuration: the Mac's address and UDP port. */
export function endpointOf(conf: string | null): { host: string; port: string } | null {
  if (!conf) return null;
  const found = /^[ \t]*Endpoint[ \t]*=[ \t]*(.+):(\d+)[ \t]*$/m.exec(conf);
  if (!found) return null;
  return { host: (found[1] as string).replace(/^\[(.*)\]$/, '$1'), port: found[2] as string };
}

/** The same configuration with the emulator's address of the Mac as its endpoint, port kept. */
export function emulatorConf(conf: string): string {
  return conf.replace(/^([ \t]*Endpoint[ \t]*=[ \t]*).+:(\d+)([ \t]*)$/m, `$1${EMULATOR_HOST}:$2$3`);
}

/** The command that starts Wiretrace again in proxy mode for this device. */
export function proxyCommand(preset: string, kind: DeviceKind): string {
  return `./wiretrace start --preset ${preset || '<preset>'} --target ${deviceChoice(kind).target} --mode proxy --ui wiretrace`;
}

/** A device cannot use the WireGuard tunnel at all (no VPN app). */
export function needsProxy(kind: DeviceKind): boolean {
  return kind === 'ios-sim';
}

export interface Step {
  text: string;
  /** A command, an address or a file name, shown in monospace with a copy button. */
  code?: string;
}

export function tunnelSteps(kind: DeviceKind): Step[] {
  switch (kind) {
    case 'iphone':
      return [
        { text: 'Install WireGuard from the App Store.' },
        { text: 'Open WireGuard → Add a tunnel → Create from QR code, and scan this code.' },
        { text: 'Name the tunnel "Wiretrace" and allow adding the VPN configuration.' },
        { text: 'Switch the tunnel on.' },
      ];
    case 'android':
      return [
        { text: 'Install WireGuard from Google Play.' },
        { text: 'Open WireGuard → + → Scan from QR code, and scan this code.' },
        { text: 'Name the tunnel "Wiretrace" and allow the VPN connection request.' },
        { text: 'Switch the tunnel on.' },
      ];
    case 'android-emu':
      return [
        { text: 'Install WireGuard in the emulator from Google Play (a system image with Google Play).' },
        { text: 'Save the configuration text below as wiretrace.conf, then copy it to the emulator:', code: 'adb push wiretrace.conf /sdcard/Download/' },
        { text: 'In WireGuard tap + → Import from file or archive, and pick Download/wiretrace.conf.' },
        { text: 'Switch the tunnel on, then delete wiretrace.conf from the Mac: it holds the private key.' },
      ];
    case 'ios-sim':
      return [];
  }
}

export function proxySteps(kind: DeviceKind, macIp: string, port: number): Step[] {
  switch (kind) {
    case 'iphone':
      return [
        { text: 'Connect the iPhone to the same Wi-Fi network as this Mac.' },
        { text: 'Settings → Wi-Fi → (i) next to the network → Configure Proxy → Manual.' },
        { text: `Server ${macIp}, port ${port}, no authentication. Save.` },
        { text: 'Apps that ignore the proxy setting are not captured in this mode.' },
      ];
    case 'android':
      return [
        { text: 'Connect the phone to the same Wi-Fi network as this Mac.' },
        { text: 'Settings → Network & internet → Internet → the network\'s settings → Edit → Advanced options → Proxy → Manual.' },
        { text: `Proxy hostname ${macIp}, port ${port}. Save.` },
        { text: 'Apps that ignore the proxy setting are not captured in this mode.' },
      ];
    case 'ios-sim':
      return [
        { text: 'The Simulator uses this Mac\'s proxy settings. Turn on the web proxy for Wi-Fi:', code: `networksetup -setwebproxy Wi-Fi 127.0.0.1 ${port}` },
        { text: 'And the secure web proxy:', code: `networksetup -setsecurewebproxy Wi-Fi 127.0.0.1 ${port}` },
        { text: 'When you are done, turn both off again:', code: 'networksetup -setwebproxystate Wi-Fi off; networksetup -setsecurewebproxystate Wi-Fi off' },
      ];
    case 'android-emu':
      return [
        { text: 'With the emulator running, set its proxy from the Mac\'s Terminal:', code: `adb shell settings put global http_proxy ${EMULATOR_HOST}:${port}` },
        { text: 'When you are done, remove it again:', code: 'adb shell settings put global http_proxy :0' },
      ];
  }
}

/** The steps of the Device logs step: how the device gets connected for its system log. */
export function deviceLogSteps(kind: DeviceKind): string[] {
  switch (kind) {
    case 'iphone':
      return ['Connect the iPhone to this Mac with a USB cable.', 'Unlock it and tap "Trust This Computer".'];
    case 'android':
      return ['Turn on Developer options → USB debugging on the phone.', 'Connect it with a USB cable and allow USB debugging for this Mac.'];
    case 'ios-sim':
      return ['Boot the Simulator. Its log is read on the Mac; no cable is needed.'];
    case 'android-emu':
      return ['Start the emulator. adb sees it without a cable.'];
  }
}

/** The first request that reached an API host: only API hosts and mitm.it are decrypted, the receiver is never listed. */
export function firstApiFlow(flows: readonly FlowSummary[]): FlowSummary | null {
  return flows.find((f) => f.host.toLowerCase().replace(/\.$/, '') !== ONBOARDING_HOST) ?? null;
}
