import { useEffect, useState } from 'react';
import { bannerText, loadIgnored, moreText, proxyBanner, storeIgnored } from '../logic/proxyDevices';
import { useStore } from '../store';
import type { ProxyWaiting } from '../types';
import { SwitchClientDialog } from './SwitchDeviceDialog';

/** This tab's sessionStorage, or null where the browser refuses it: Ignore lasts until the tab closes. */
function tabStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Another device was refused by the Wi-Fi proxy: switch the session to it, or ignore it (spec 021). */
export function ProxyDeviceBanner({ viewing }: { viewing: string | null }) {
  const { appState } = useStore();
  const session = appState?.session ?? '';
  const [ignored, setIgnored] = useState<Set<string>>(() => loadIgnored(tabStorage(), session));
  const [chosen, setChosen] = useState<{ device: ProxyWaiting; accepted: string } | null>(null);

  useEffect(() => {
    setIgnored(loadIgnored(tabStorage(), session));
  }, [session]);

  useEffect(() => {
    if (viewing) setChosen(null);
  }, [viewing]);

  const banner = proxyBanner(appState, viewing, ignored);
  const ignore = (address: string) => {
    const next = new Set(ignored).add(address);
    storeIgnored(tabStorage(), session, next);
    setIgnored(next);
  };

  return (
    <>
      {banner && (
        <div className="banner proxy" role="status">
          <span>
            {bannerText(banner)}
            {banner.more > 0 && <b className="more">{moreText(banner.more)}</b>}
          </span>
          <span className="spacer" />
          <button type="button" className="btn small" onClick={() => setChosen({ device: banner.device, accepted: banner.accepted })}>
            Switch to it…
          </button>
          <button type="button" className="btn small" onClick={() => ignore(banner.device.address)}>
            Ignore
          </button>
        </div>
      )}
      {chosen && appState && (
        <SwitchClientDialog address={chosen.device.address} accepted={chosen.accepted} state={appState} onClose={() => setChosen(null)} />
      )}
    </>
  );
}
