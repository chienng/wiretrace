// Dev only: replaces the WebSocket for /api/updates with a fake that emits one flow and one
// log line per second. Served by dev/fixture-plugin.mjs; never part of the build.
import { liveFlow, liveLines } from '/__dev/live.mjs';

const EPOCH = __EPOCH__;
const NativeWebSocket = window.WebSocket;
const sockets = new Set();
let last = Math.floor(Date.now() / 1000 - EPOCH);

class FakeSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.onopen = this.onmessage = this.onclose = this.onerror = null;
    sockets.add(this);
    setTimeout(() => {
      if (this.readyState !== 0) return;
      this.readyState = 1;
      this.onopen?.({});
    }, 50);
  }
  send() {}
  addEventListener(type, fn) {
    const prev = this['on' + type];
    this['on' + type] = prev ? (e) => (prev(e), fn(e)) : fn;
  }
  close() {
    if (this.readyState === 3) return;
    this.readyState = 3;
    sockets.delete(this);
    this.onclose?.({});
  }
  emit(message) {
    if (this.readyState === 1) this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function broadcast(message) {
  for (const s of sockets) s.emit(message);
}

setInterval(() => {
  if (sockets.size === 0) return;
  const n = Math.floor(Date.now() / 1000 - EPOCH);
  for (; last < n; ) {
    last++;
    const k = last;
    broadcast({ type: 'flows', flows: [liveFlow(k, EPOCH, false)] });
    setTimeout(() => broadcast({ type: 'flows', flows: [liveFlow(k, EPOCH, true)] }), 350);
    const { device, app } = liveLines(k, EPOCH);
    broadcast({ type: 'logs', lines: app ? [device, app] : [device] });
  }
}, 250);

window.WebSocket = function (url, protocols) {
  if (String(url).endsWith('/api/updates')) return new FakeSocket(url);
  return new NativeWebSocket(url, protocols);
};
window.WebSocket.CONNECTING = 0;
window.WebSocket.OPEN = 1;
window.WebSocket.CLOSING = 2;
window.WebSocket.CLOSED = 3;

// Console helpers: __wiretraceFake.drop() tries the reconnect path; __wiretraceFake.state() sends the
// fixture's state as the server does after a change such as a decrypted host.
window.__wiretraceFake = {
  drop: () => [...sockets].forEach((s) => s.close()),
  state: async () => broadcast({ type: 'state', state: await (await fetch('/api/state')).json() }),
};
