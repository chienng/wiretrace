import type { AppState, FlowSummary } from '../types';

export type DeviceKind = 'iphone' | 'android' | 'ios-sim' | 'android-emu';

export interface DeviceChoice {
  id: DeviceKind;
  label: string;
  sub: string;
  /** The `--target` that collects this device's logs. */
  target: string;
}

export const DEVICES: DeviceChoice[] = [
  { id: 'iphone', label: 'iPhone', sub: 'a real iPhone', target: 'ios' },
  { id: 'android', label: 'Android', sub: 'a real Android phone', target: 'android' },
  { id: 'ios-sim', label: 'iOS Simulator', sub: 'on this Mac', target: 'ios-sim' },
  { id: 'android-emu', label: 'Android emulator', sub: 'on this Mac', target: 'android-emu' },
];

/** How the Android emulator reaches the Mac. */
export const EMULATOR_HOST = '10.0.2.2';
/** After this long on the Connect step without a connection, the guest Wi-Fi hint shows. */
export const NO_CONNECTION_HINT_S = 30;
/** After this long on the Trust step with the device connected but no request to mitm.it, the address hint shows. */
export const NO_PAGE_HINT_S = 60;
/** After this long on the Check step with the device connected but no API request and no TLS failure, the checks show. */
export const NO_APP_TRAFFIC_HINT_S = 30;
const ONBOARDING_HOST = 'mitm.it';
const CERT_PATH = '/cert/';

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
        {
          text:
            'Open the network\'s proxy setting. Most phones: Settings → Network & internet → Internet → the ' +
            'network\'s settings → Edit → Advanced options → Proxy → Manual. Samsung: Settings → Connections → ' +
            'Wi-Fi → the gear next to the network → View more → Proxy → Manual. Not there? Search Settings for "Proxy".',
        },
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
  return flows.find((f) => !isOnboarding(f)) ?? null;
}

function isOnboarding(f: FlowSummary): boolean {
  return f.host.toLowerCase().replace(/\.$/, '') === ONBOARDING_HOST;
}

export interface OnboardingProgress {
  /** Any request to mitm.it. */
  pageOpened: boolean;
  /** A request to mitm.it for a certificate file. */
  certDownloaded: boolean;
}

/**
 * The first two items of the Trust checklist. An API request proves both, so they stay ticked when
 * the mitm.it requests were dropped by the 10,000-request cap.
 */
export function onboardingProgress(flows: readonly FlowSummary[]): OnboardingProgress {
  if (firstApiFlow(flows)) return { pageOpened: true, certDownloaded: true };
  const page = flows.filter(isOnboarding);
  return { pageOpened: page.length > 0, certDownloaded: page.some((f) => f.path.startsWith(CERT_PATH)) };
}

/** The certificate is fetched from mitm.it on the device itself; the Simulator and the emulator get it from the Mac. */
export function usesOnboardingPage(kind: DeviceKind): boolean {
  return kind === 'iphone' || kind === 'android';
}

export type StepKey = 'device' | 'connect' | 'trust' | 'check' | 'logs';
/** Choosing the device has nothing to check. */
export type CheckedStep = Exclude<StepKey, 'device'>;

/** Whether a step's live check passes. */
export function stepDone(step: CheckedStep, state: AppState, flows: readonly FlowSummary[]): boolean {
  switch (step) {
    case 'connect':
      return state.device_seen_at !== null;
    case 'trust':
    case 'check':
      return firstApiFlow(flows) !== null;
    case 'logs':
      return state.device_logs !== null;
  }
}

export const STEP_LABELS: Record<StepKey, string> = {
  device: 'Choose device',
  connect: 'Connect to this Mac',
  trust: 'Trust Wiretrace',
  check: 'Check the app',
  logs: 'Device logs',
};

/** The Next button: it says so when the current step's check passed. */
export function nextLabel(done: boolean, next: StepKey): string {
  return `${done ? 'Done — ' : ''}Next: ${STEP_LABELS[next]}`;
}

export type TrustHint = 'not-trusted' | 'no-page' | null;

/** TLS failures to API hosts first; else, for a phone, no mitm.it request NO_PAGE_HINT_S after the step opened while connected. */
export function trustHint(kind: DeviceKind, state: AppState, flows: readonly FlowSummary[], sinceMs: number, now: number): TrustHint {
  if (firstApiFlow(flows)) return null;
  if (state.tls_failures > 0) return 'not-trusted';
  if (!usesOnboardingPage(kind) || state.device_seen_at === null) return null;
  if (onboardingProgress(flows).pageOpened) return null;
  return now - sinceMs >= NO_PAGE_HINT_S * 1000 ? 'no-page' : null;
}

export type AppHint = 'not-trusted' | 'no-traffic' | null;

/** TLS failures to API hosts; else nothing from the app NO_APP_TRAFFIC_HINT_S after the step opened while connected. */
export function appHint(state: AppState, flows: readonly FlowSummary[], sinceMs: number, now: number): AppHint {
  if (firstApiFlow(flows)) return null;
  if (state.tls_failures > 0) return 'not-trusted';
  if (state.device_seen_at === null) return null;
  return now - sinceMs >= NO_APP_TRAFFIC_HINT_S * 1000 ? 'no-traffic' : null;
}

function noun(kind: DeviceKind): string {
  switch (kind) {
    case 'iphone':
    case 'android':
      return 'phone';
    case 'ios-sim':
      return 'Simulator';
    case 'android-emu':
      return 'emulator';
  }
}

/** The device connects through the WireGuard tunnel rather than a proxy setting. */
export function usesTunnel(kind: DeviceKind, wireguard: boolean): boolean {
  return wireguard && !needsProxy(kind);
}

/** What the Connect step's first mention of WireGuard or the proxy is for. */
export function connectWhy(kind: DeviceKind, wireguard: boolean): string {
  if (usesTunnel(kind, wireguard)) {
    return `WireGuard is a free VPN app. Here it only sends the ${noun(kind)}'s traffic to this Mac, on any Wi-Fi network.`;
  }
  if (kind === 'ios-sim') return 'The Simulator has no VPN app. It uses this Mac\'s proxy setting, which sends web traffic through Wiretrace.';
  if (kind === 'android-emu') return 'A proxy is a setting that sends the emulator\'s web traffic through Wiretrace on this Mac.';
  return `A Wi-Fi proxy is a setting on the ${noun(kind)} that sends its web traffic through this Mac. Both must be on the same Wi-Fi network.`;
}

export const CERTIFICATE_WHY =
  'A certificate makes the device trust Wiretrace, so Wiretrace can read the app\'s HTTPS requests. Only the API hosts of your preset are read.';

/** Step 1's Before you start box. */
export function beforeYouStart(kind: DeviceKind, wireguard: boolean): { needs: string[]; once: string } {
  const device: Record<DeviceKind, string> = {
    iphone: 'The iPhone, unlocked.',
    android: 'The Android phone, unlocked.',
    'ios-sim': 'The iOS Simulator, on this Mac.',
    'android-emu': 'The Android emulator, on this Mac.',
  };
  const again = usesTunnel(kind, wireguard) ? 'switch the tunnel on' : 'set the proxy again';
  return {
    needs: [device[kind], 'A QA build of the app. A store build hides its traffic from Wiretrace.', 'About five minutes.'],
    once: `You do this once per ${noun(kind)}. Next time, you only ${again} (step 2 shows how).`,
  };
}

/** The checklist of the Trust step, in order. */
export function trustChecklist(kind: DeviceKind, flows: readonly FlowSummary[]): { label: string; done: boolean }[] {
  const trusted = { label: 'Trusted: the first request to an API host arrived', done: firstApiFlow(flows) !== null };
  if (!usesOnboardingPage(kind)) return [trusted];
  const p = onboardingProgress(flows);
  return [
    { label: 'Page opened on the phone', done: p.pageOpened },
    { label: 'Certificate downloaded', done: p.certDownloaded },
    trusted,
  ];
}

export function noPageHint(kind: DeviceKind, wireguard: boolean): string {
  const browser = kind === 'iphone' ? ' in Safari' : ' in Chrome';
  const link = usesTunnel(kind, wireguard) ? 'with the WireGuard tunnel on' : 'with the Wi-Fi proxy set';
  return `Nothing from the page yet. On the phone, type http://mitm.it exactly (not https)${browser}, ${link}.`;
}

export const STORE_BUILD_NOTE = 'A store build of the app never trusts this certificate on Android: use a QA build.';

/** What to check when the app sends nothing Wiretrace can see. */
export function appChecks(kind: DeviceKind, wireguard: boolean, preset: string, apiHosts: readonly string[]): string[] {
  const hosts = apiHosts.length ? apiHosts.join(', ') : 'the API hosts in your preset file';
  const link = usesTunnel(kind, wireguard) ? 'The WireGuard tunnel is still on.' : 'The proxy is still set.';
  return [
    `The app is a QA build for the environment of the preset ${preset || 'you started with'}.`,
    `It talks to the preset's API hosts: ${hosts}.`,
    'You are on a screen of the app that loads data (pull to refresh, or open another screen).',
    link,
  ];
}

/** The last step's summary: what is set up. */
export function setupSummary(kind: DeviceKind, state: AppState, flows: readonly FlowSummary[]): { label: string; done: boolean }[] {
  const via = usesTunnel(kind, state.mode === 'wireguard') ? 'through WireGuard' : 'through the proxy';
  return [
    { label: `${deviceChoice(kind).label} connected to this Mac ${via}`, done: stepDone('connect', state, flows) },
    { label: 'Wiretrace trusted, and the app\'s requests arrive', done: stepDone('check', state, flows) },
    { label: state.device_logs ? 'Device logs on' : 'Device logs off (optional)', done: stepDone('logs', state, flows) },
  ];
}

export function nextTime(kind: DeviceKind, wireguard: boolean): string {
  const again = usesTunnel(kind, wireguard)
    ? 'switch the WireGuard tunnel on'
    : kind === 'iphone' || kind === 'android'
      ? 'set the Wi-Fi proxy again'
      : 'set the proxy again with the commands of step 2';
  return `Next time: ${again}, then start Wiretrace. The certificate stays installed.`;
}
