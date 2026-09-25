// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * usePresenceWebSocket — live roster + lock-event stream for one entity.
 *
 * Connects to /api/v1/collaboration_locks/presence/?entity_type=...&entity_id=...
 * and sends the JWT as the first frame (`shared/lib/socketAuth`), never in
 * the URL, where every access log would write it down.
 *
 * The hook is purely *observational* — it does not acquire or
 * release locks.  Pair it with useEntityLock for the holder; use
 * this hook alone in list views that want to show "3 people viewing".
 */

import { useEffect, useRef, useState } from 'react';

import { useAuthStore } from '@/stores/useAuthStore';
import { authFrame, socketUrl } from '@/shared/lib/socketAuth';

export interface PresenceUser {
  user_id: string;
  user_name: string;
}

export type PresenceStatus =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'closed'
  | 'error';

export interface PresenceEvent {
  event:
    | 'presence_snapshot'
    | 'presence_join'
    | 'presence_leave'
    | 'lock_acquired'
    | 'lock_heartbeat'
    | 'lock_released'
    | 'lock_expired'
    | 'pong';
  users?: PresenceUser[];
  lock?: {
    id: string;
    entity_type: string;
    entity_id: string;
    user_id: string;
    user_name: string;
    expires_at: string;
    remaining_seconds: number;
  } | null;
  lock_id?: string;
  user_id?: string;
  user_name?: string;
  expires_at?: string;
  ts?: string;
}

export interface UsePresenceWebSocketResult {
  status: PresenceStatus;
  users: PresenceUser[];
  lastEvent: PresenceEvent | null;
}

/** Connect a live presence channel for the given entity. */
export function usePresenceWebSocket(
  entityType: string,
  entityId: string | null,
  enabled: boolean = true,
): UsePresenceWebSocketResult {
  const [status, setStatus] = useState<PresenceStatus>('idle');
  const [users, setUsers] = useState<PresenceUser[]>([]);
  const [lastEvent, setLastEvent] = useState<PresenceEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled || entityId === null) {
      setStatus('idle');
      setUsers([]);
      return;
    }
    const token = useAuthStore.getState().accessToken;
    if (!token) {
      setStatus('closed');
      return;
    }

    const url = socketUrl(
      `/api/v1/collaboration_locks/presence/` +
        `?entity_type=${encodeURIComponent(entityType)}` +
        `&entity_id=${encodeURIComponent(entityId)}`,
    );

    let closed = false;
    setStatus('connecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      setStatus('error');
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      if (closed) return;
      ws.send(authFrame(token));
      setStatus('open');
    };

    ws.onmessage = (msg: MessageEvent<string>) => {
      let parsed: PresenceEvent;
      try {
        parsed = JSON.parse(msg.data) as PresenceEvent;
      } catch {
        return;
      }
      setLastEvent(parsed);

      switch (parsed.event) {
        case 'presence_snapshot':
          setUsers(parsed.users ?? []);
          break;
        case 'presence_join':
          if (parsed.user_id && parsed.user_name) {
            const joiner: PresenceUser = {
              user_id: parsed.user_id,
              user_name: parsed.user_name,
            };
            setUsers((prev) =>
              prev.some((u) => u.user_id === joiner.user_id)
                ? prev
                : [...prev, joiner],
            );
          }
          break;
        case 'presence_leave':
          if (parsed.user_id) {
            setUsers((prev) => prev.filter((u) => u.user_id !== parsed.user_id));
          }
          break;
        default:
          // lock_* events — caller can react via lastEvent
          break;
      }
    };

    ws.onerror = () => {
      if (closed) return;
      setStatus('error');
    };

    ws.onclose = () => {
      if (closed) return;
      setStatus('closed');
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
  }, [enabled, entityType, entityId]);

  return { status, users, lastEvent };
}
