// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * useNotificationsWebSocket — real-time push channel for the bell.
 *
 * Epic B / B10. Opens a WebSocket against /api/v1/notifications/ws/
 * and sends the JWT as the first frame (`shared/lib/socketAuth`), never
 * in the URL, where every access log would write it down.
 *
 * On any incoming notification the hook invokes `onNotification` so
 * the caller (NotificationBell) can invalidate its React Query cache
 * — replacing the 30s polling cadence with sub-second push without
 * breaking the existing data-flow.
 *
 * The hook is best-effort: a missing token or a closed socket leaves
 * the bell on its polling cadence, never crashes the UI.
 */

import { useEffect, useRef } from 'react';

import { useAuthStore } from '@/stores/useAuthStore';
import { authFrame, socketUrl } from '@/shared/lib/socketAuth';

export type NotificationsWsStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

export interface NotificationsWsEvent {
  event: 'notifications.hello' | 'notification.created' | 'pong' | string;
  data?: Record<string, unknown>;
  user_id?: string;
  ts?: string;
}

export interface UseNotificationsWebSocketOptions {
  enabled?: boolean;
  onNotification?: (event: NotificationsWsEvent) => void;
}

/**
 * Subscribe to the notifications WS channel for the current user.
 *
 * Returns nothing — the side effects (cache invalidation, optimistic
 * UI) live in the caller-provided `onNotification` callback so this
 * hook stays decoupled from React Query.
 */
export function useNotificationsWebSocket(
  options: UseNotificationsWebSocketOptions = {},
): void {
  const { enabled = true, onNotification } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const callbackRef = useRef(onNotification);

  // Keep the latest callback in a ref so the WebSocket effect doesn't
  // tear down + recreate every render when the parent's handler
  // identity changes.
  useEffect(() => {
    callbackRef.current = onNotification;
  }, [onNotification]);

  useEffect(() => {
    if (!enabled) return;
    const token = useAuthStore.getState().accessToken;
    if (!token) return;

    const url = socketUrl('/api/v1/notifications/ws/');

    let closed = false;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      // Best-effort — bell continues to poll if the socket cannot open.
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      if (closed) return;
      ws.send(authFrame(token));
    };

    ws.onmessage = (msg: MessageEvent<string>) => {
      if (closed) return;
      let parsed: NotificationsWsEvent;
      try {
        parsed = JSON.parse(msg.data) as NotificationsWsEvent;
      } catch {
        return;
      }
      callbackRef.current?.(parsed);
    };

    ws.onerror = () => {
      // Stay quiet — React Query polling is the fallback.
    };

    return () => {
      closed = true;
      try {
        ws.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    };
  }, [enabled]);
}
