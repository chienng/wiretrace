export interface CertStep {
  text: string;
  /** A command or a path, shown in monospace with a copy button. */
  code?: string;
}

export interface CertGroup {
  platform: string;
  steps: CertStep[];
}

const CA_PEM = '~/.mitmproxy/mitmproxy-ca-cert.pem';
const CA_CER = '~/.mitmproxy/mitmproxy-ca-cert.cer';

function iphone(connected: string): CertGroup {
  return {
    platform: 'iPhone',
    steps: [
      { text: `${connected}, open http://mitm.it in Safari. Other browsers cannot install a profile.` },
      { text: 'Under iOS, tap "Get mitmproxy-ca-cert.pem", then Allow. The profile is downloaded, not installed yet.' },
      {
        text:
          'Install it: Settings → General → VPN & Device Management → mitmproxy (under Downloaded Profile) → Install, ' +
          'and enter the passcode. A "Profile Downloaded" row at the top of Settings leads there too.',
      },
      {
        text:
          'Trust it: Settings → General → About → Certificate Trust Settings → turn on mitmproxy. ' +
          'The switch appears only after the profile is installed; without it HTTPS still fails.',
      },
    ],
  };
}

function android(connected: string): CertGroup {
  return {
    platform: 'Android',
    steps: [
      { text: `${connected}, open http://mitm.it in Chrome.` },
      { text: 'Under Android, tap "Get mitmproxy-ca-cert.cer" to download it.' },
      {
        text:
          'Settings → Security → Encryption & credentials → Install a certificate → CA certificate, and pick the ' +
          'file. The menu names vary by phone maker.',
      },
      { text: 'Only a QA build of the app that trusts user CAs uses this certificate; store builds ignore it.' },
    ],
  };
}

/** The certificate steps for a `--target`, in order. `wireguard` picks how the phone is connected. */
export function certificateSteps(target: string, wireguard: boolean): CertGroup[] {
  const connected = wireguard ? 'With the WireGuard tunnel on' : 'With the Wi-Fi proxy set';
  switch (target) {
    case 'ios':
      return [iphone(connected)];
    case 'android':
      return [android(connected)];
    case 'ios-sim':
      return [
        {
          platform: 'iOS Simulator',
          steps: [
            { text: 'Boot the Simulator, then run this in the Mac\'s Terminal:', code: `xcrun simctl keychain booted add-root-cert ${CA_PEM}` },
            { text: 'Restart the app in the Simulator.' },
          ],
        },
      ];
    case 'android-emu':
      return [
        {
          platform: 'Android emulator',
          steps: [
            { text: 'With the emulator running, copy the certificate to it from the Mac\'s Terminal:', code: `adb push ${CA_CER} /sdcard/Download/` },
            ...android(connected).steps.slice(2),
          ],
        },
      ];
    default:
      return [iphone(connected), android(connected)];
  }
}
