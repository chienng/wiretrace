import { useEffect, useRef, useState } from 'react';
import {
  allowState,
  bannerText,
  gainsAddress,
  loadIgnored,
  moreText,
  proxyBanner,
  storeIgnored,
  tabTitle,
  type ProxyBanner,
} from '../logic/proxyDevices';
import { useStore } from '../store';
import { AllowDeviceDialog } from './AllowDeviceDialog';
import { SwitchClientDialog } from './SwitchDeviceDialog';

/** This tab's sessionStorage, or null where the browser refuses it: Ignore lasts until the tab closes. */
function tabStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function PhoneIcon() {
  return (
    <span className="ask-ico" aria-hidden="true">
      <svg width="12" height="14" viewBox="0 0 12 14">
        <rect x="1.5" y="0.75" width="9" height="12.5" rx="2" fill="none" stroke="#ffb21e" strokeWidth="1.5" />
        <circle cx="6" cy="10.6" r="0.9" fill="#ffb21e" />
      </svg>
    </span>
  );
}

/** Another device was refused by the Wi-Fi proxy: allow it, switch the session to it, or ignore it (specs 021, 022). */
export function ProxyDeviceBanner({ viewing }: { viewing: string | null }) {
  const { appState } = useStore();
  const session = appState?.session ?? '';
  const [ignored, setIgnored] = useState<Set<string>>(() => loadIgnored(tabStorage(), session));
  const [chosen, setChosen] = useState<{ banner: ProxyBanner; action: 'allow' | 'switch' } | null>(null);
  const [pulse, setPulse] = useState(0);
  const seen = useRef<Set<string>>(new Set());

  useEffect(() => {
    setIgnored(loadIgnored(tabStorage(), session));
  }, [session]);

  useEffect(() => {
    if (viewing) setChosen(null);
  }, [viewing]);

  const banner = proxyBanner(appState, viewing, ignored);
  const waiting = banner
    ? (appState?.proxy_waiting ?? []).map((w) => w.address).filter((a) => !banner.accepted.includes(a) && !ignored.has(a))
    : [];
  const waitingKey = waiting.join(' ');

  useEffect(() => {
    const now = waitingKey ? waitingKey.split(' ') : [];
    if (gainsAddress(seen.current, now)) setPulse((p) => p + 1);
    seen.current = new Set(now);
  }, [waitingKey]);

  useEffect(() => {
    document.title = tabTitle(waiting.length);
  }, [waiting.length]);

  const ignore = (address: string) => {
    const next = new Set(ignored).add(address);
    storeIgnored(tabStorage(), session, next);
    setIgnored(next);
  };
  const max = appState?.proxy_max ?? 0;
  const allow = banner ? allowState(banner.accepted, max) : null;

  return (
    <>
      {banner && allow && (
        <div key={pulse} className="banner ask" role="alert">
          <PhoneIcon />
          <span>
            {bannerText(banner)}
            {banner.more > 0 && <b className="more">{moreText(banner.more)}</b>}
          </span>
          <span className="spacer" />
          <button
            type="button"
            className="btn small primary"
            disabled={allow.disabled}
            title={allow.title}
            onClick={() => setChosen({ banner, action: 'allow' })}
          >
            Allow…
          </button>
          <button type="button" className="btn small" onClick={() => setChosen({ banner, action: 'switch' })}>
            Switch to it…
          </button>
          <button type="button" className="btn small" onClick={() => ignore(banner.device.address)}>
            Ignore
          </button>
        </div>
      )}
      {chosen?.action === 'allow' && (
        <AllowDeviceDialog
          address={chosen.banner.device.address}
          accepted={chosen.banner.accepted}
          max={max}
          onClose={() => setChosen(null)}
        />
      )}
      {chosen?.action === 'switch' && appState && (
        <SwitchClientDialog
          address={chosen.banner.device.address}
          accepted={chosen.banner.accepted}
          state={appState}
          onClose={() => setChosen(null)}
        />
      )}
    </>
  );
}
