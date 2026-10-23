import { api, ForbiddenError, socketUrl } from './api';
import type { AppState, FlowSummary, LogLine, Phase, ServerMessage, TunnelRow } from './types';

export interface InitialData {
  state: AppState;
  flows: FlowSummary[];
  device: LogLine[];
  app: LogLine[];
  tunnels: TunnelRow[];
}

export interface ConnectionHandlers {
  onPhase(phase: Phase): void;
  /** Initial (or reload) data plus the socket messages that arrived while it was loading. */
  onLoaded(data: InitialData, buffered: ServerMessage[]): void;
  onMessage(message: ServerMessage): void;
}

export const BACKOFF_START_MS = 500;
export const BACKOFF_MAX_MS = 5000;

export function backoffDelay(attempt: number): number {
  return Math.min(BACKOFF_START_MS * 2 ** attempt, BACKOFF_MAX_MS);
}

/**
 * CONNECTING → LOADING → LIVE → (dropped) RECONNECTING → LOADING → LIVE.
 * Data is fetched only after the socket is open; socket messages are buffered until then.
 */
export class Connection {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private attempt = 0;
  private generation = 0;

  constructor(private readonly handlers: ConnectionHandlers) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.generation++;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.detach();
  }

  private detach(): void {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try {
      ws.close();
    } catch {
      // already closed
    }
  }

  private connect(): void {
    if (this.stopped) return;
    const gen = ++this.generation;
    this.handlers.onPhase(this.attempt === 0 ? 'connecting' : 'reconnecting');
    let opened = false;
    let buffer: ServerMessage[] = [];
    let live = false;

    const ws = new WebSocket(socketUrl());
    this.ws = ws;

    ws.onopen = () => {
      if (gen !== this.generation) return;
      opened = true;
      this.handlers.onPhase('loading');
      void this.load(gen, () => {
        const pending = buffer;
        buffer = [];
        live = true;
        return pending;
      });
    };
    ws.onmessage = (ev: MessageEvent) => {
      if (gen !== this.generation) return;
      let message: ServerMessage;
      try {
        message = JSON.parse(String(ev.data)) as ServerMessage;
      } catch {
        return;
      }
      if (live) this.handlers.onMessage(message);
      else buffer.push(message);
    };
    const dropped = () => {
      if (gen !== this.generation || this.stopped) return;
      this.generation++;
      this.detach();
      void this.afterDrop(opened);
    };
    ws.onclose = dropped;
    ws.onerror = dropped;
  }

  private async load(gen: number, takeBuffer: () => ServerMessage[]): Promise<void> {
    try {
      const [state, flows, device, app, tunnels] = await Promise.all([
        api.state(),
        api.flows(),
        api.logs('device'),
        api.logs('app'),
        api.tunnels(),
      ]);
      if (gen !== this.generation) return;
      this.handlers.onLoaded({ state, flows, device, app, tunnels }, takeBuffer());
      this.attempt = 0;
      this.handlers.onPhase('live');
    } catch (e) {
      if (gen !== this.generation) return;
      if (e instanceof ForbiddenError) {
        this.forbid();
        return;
      }
      this.generation++;
      this.detach();
      this.schedule();
    }
  }

  /** A socket that never opened may have been refused with 403; probe with a plain fetch. */
  private async afterDrop(wasOpen: boolean): Promise<void> {
    this.handlers.onPhase('reconnecting');
    if (!wasOpen) {
      try {
        await api.state();
      } catch (e) {
        if (e instanceof ForbiddenError) {
          this.forbid();
          return;
        }
      }
    }
    if (this.stopped) return;
    this.schedule();
  }

  private forbid(): void {
    this.stopped = true;
    this.generation++;
    this.detach();
    this.handlers.onPhase('forbidden');
  }

  private schedule(): void {
    if (this.stopped) return;
    this.handlers.onPhase('reconnecting');
    const delay = backoffDelay(this.attempt);
    this.attempt++;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }
}
