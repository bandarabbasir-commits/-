export type WsConnectionStatus = 'connected' | 'connecting' | 'disconnected';

export interface WsServerEvent {
  v?: number;
  event_id?: number;
  type: string;
  channel?: string;
  created_at?: string;
  payload?: Record<string, unknown>;
  reason?: string;
}

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private stopped = true;
  private retryAttempt = 0;
  private lastEventId = 0;
  private statusListeners = new Set<(status: WsConnectionStatus) => void>();
  private eventListeners = new Set<(event: WsServerEvent) => void>();
  private status: WsConnectionStatus = 'disconnected';

  onStatusChange(fn: (status: WsConnectionStatus) => void): () => void {
    this.statusListeners.add(fn);
    fn(this.status);
    return () => this.statusListeners.delete(fn);
  }

  onEvent(fn: (event: WsServerEvent) => void): () => void {
    this.eventListeners.add(fn);
    return () => this.eventListeners.delete(fn);
  }

  private setStatus(next: WsConnectionStatus) {
    this.status = next;
    this.statusListeners.forEach((fn) => fn(next));
  }

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    this.retryAttempt = 0;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.ws) {
      const sock = this.ws;
      this.ws = null;
      sock.onopen = null;
      sock.onmessage = null;
      sock.onclose = null;
      sock.onerror = null;
      try {
        if (sock.readyState === WebSocket.OPEN || sock.readyState === WebSocket.CONNECTING) {
          sock.close(1000, 'client_stop');
        }
      } catch {
        // Ignore close errors during teardown
      }
    }
    this.setStatus('disconnected');
  }

  private connect() {
    if (this.stopped || typeof window === 'undefined') return;
    this.setStatus('connecting');

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const sinceParam = this.lastEventId > 0 ? `?since_event_id=${this.lastEventId}` : '';
    const url = `${proto}//${window.location.host}/api/v1/ws${sinceParam}`;

    const socket = new WebSocket(url);
    let revokedEmitted = false;
    this.ws = socket;

    socket.onopen = () => {
      if (this.stopped || this.ws !== socket) return;
      this.retryAttempt = 0;
      this.setStatus('connected');
      if (this.pingTimer !== null) window.clearInterval(this.pingTimer);
      this.pingTimer = window.setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 25000);
    };

    socket.onmessage = (msgEvent) => {
      if (this.stopped || this.ws !== socket) return;
      try {
        const data = JSON.parse(msgEvent.data) as WsServerEvent;
        if (typeof data.event_id === 'number' && data.event_id > this.lastEventId) {
          this.lastEventId = data.event_id;
        }
        if (data.type === 'session.revoked') {
          if (revokedEmitted) return;
          revokedEmitted = true;
        }
        this.eventListeners.forEach((fn) => fn(data));
      } catch {
        // Ignore malformed frame
      }
    };

    socket.onclose = (closeEvent) => {
      if (this.pingTimer !== null) {
        window.clearInterval(this.pingTimer);
        this.pingTimer = null;
      }
      if (this.ws === socket) {
        this.ws = null;
      }
      this.setStatus('disconnected');

      if (this.stopped) {
        return;
      }

      // 4001/4003 means unauthorized/session revoked -> do not reconnect aggressively
      if (closeEvent.code === 4001 || closeEvent.code === 4003) {
        if (closeEvent.code === 4001 && !revokedEmitted) {
          revokedEmitted = true;
          this.eventListeners.forEach((fn) =>
            fn({ type: 'session.revoked', reason: closeEvent.reason || 'unauthorized' })
          );
        }
        return;
      }

      const baseDelay = Math.min(20000, 1000 * Math.pow(2, this.retryAttempt));
      const jitter = Math.floor(Math.random() * 700);
      this.retryAttempt += 1;
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, baseDelay + jitter);
    };

    socket.onerror = () => {
      // onclose handles reconnect
    };
  }
}

export const realtimeClient = new RealtimeClient();
