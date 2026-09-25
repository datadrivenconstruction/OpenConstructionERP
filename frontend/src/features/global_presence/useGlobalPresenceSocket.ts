// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * useGlobalPresenceSocket -- app-wide presence WebSocket.
 *
 * Connects to /api/v1/global_presence/ws/, sends the JWT as the first frame
 * (`shared/lib/socketAuth`, never in the URL), and keeps the presence store
 * in sync with the roster of the project this tab is working in. Sends
 * `route_update` with the active project on pathname and project changes,
 * and `status_update` when the tab becomes hidden or the user goes idle for
 * 3 minutes.
 *
 * The server only shows a tab the people in the same project, and only when
 * the user may open that project. Without an active project the roster is
 * empty, which is the point: the header used to show every signed-in account
 * on the server to every other one.
 *
 * Unlike the per-entity usePresenceWebSocket (collab_locks), this hook:
 *   - auto-reconnects with jittered exponential backoff,
 *   - tracks idle/active status from visibility + input events,
 *   - is designed to be mounted once at the AppLayout level.
 *
 * Graceful: if the WS never connects nothing renders.
 */

import { useEffect, useRef, useCallback } from 'react';
import { useLocation } from 'react-router-dom';

import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { authFrame, socketUrl } from '@/shared/lib/socketAuth';
import {
  useGlobalPresenceStore,
  type GlobalPresenceUser,
} from '@/stores/useGlobalPresenceStore';

/* ── Protocol messages ─────────────────────────────────────────────── */

/**
 * One user as the server sends it (``app/modules/global_presence``): flat on
 * a join or update message, one per entry in a snapshot. The server has no
 * ``last_active``; the message timestamp stands in for it.
 */
export interface WirePresenceUser {
  user_id: string;
  user_name?: string;
  route?: string;
  status?: string;
  connected_at?: string;
}

interface PresenceSnapshot {
  event: 'presence_snapshot';
  users: WirePresenceUser[];
  ts?: string;
}

interface PresenceJoin extends WirePresenceUser {
  event: 'presence_join';
  ts?: string;
}

interface PresenceLeave {
  event: 'presence_leave';
  user_id: string;
}

interface PresenceUpdate extends WirePresenceUser {
  event: 'presence_update';
  ts?: string;
}

interface Pong {
  event: 'pong';
}

type ServerMessage =
  | PresenceSnapshot
  | PresenceJoin
  | PresenceLeave
  | PresenceUpdate
  | Pong;

/* ── Constants ─────────────────────────────────────────────────────── */

/** Base delay for the first reconnect attempt (ms). */
const BASE_DELAY_MS = 1_000;
/** Maximum backoff ceiling (ms). */
const MAX_DELAY_MS = 30_000;
/** User is considered idle after this much inactivity (ms). */
const IDLE_TIMEOUT_MS = 3 * 60 * 1_000;
/** How often we ping to keep the connection alive (ms). */
const PING_INTERVAL_MS = 25_000;

/* ── Helpers ───────────────────────────────────────────────────────── */

/**
 * The store's user from what the server sent, or ``null`` without an id.
 *
 * Join and update messages carry the user's fields at the top level. This
 * hook used to read them from a nested ``user`` object the server never
 * sends, so every join threw a TypeError on ``user_id`` and nobody but the
 * first snapshot ever showed up.
 */
export function presenceUserFromWire(wire: WirePresenceUser, ts?: string): GlobalPresenceUser | null {
  if (!wire || typeof wire.user_id !== 'string' || wire.user_id === '') return null;
  return {
    user_id: wire.user_id,
    user_name: wire.user_name ?? '',
    route: wire.route ?? '/',
    status: wire.status === 'idle' ? 'idle' : 'active',
    last_active: ts ?? wire.connected_at ?? new Date().toISOString(),
  };
}

/** Exponential backoff with full jitter: `random(0, min(cap, base * 2^attempt))`. */
function jitteredBackoff(attempt: number): number {
  const ceiling = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
  return Math.random() * ceiling;
}

/* ── Hook ──────────────────────────────────────────────────────────── */

/**
 * Mount once at AppLayout level. The hook is a pure side-effect -- it
 * returns nothing. All state is written to `useGlobalPresenceStore`.
 */
export function useGlobalPresenceSocket(): void {
  const location = useLocation();
  const pathnameRef = useRef(location.pathname);
  pathnameRef.current = location.pathname;
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectRef = useRef(activeProjectId);
  projectRef.current = activeProjectId;

  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isIdleRef = useRef(false);
  const mountedRef = useRef(true);

  const { setUsers, upsertUser, removeUser, setWsStatus, clear } =
    useGlobalPresenceStore.getState();

  /* ── Send helper (safe even when socket is not open) ─────────── */
  const send = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }, []);

  /* ── Idle detection ──────────────────────────────────────────── */
  const resetIdleTimer = useCallback(() => {
    if (idleTimerRef.current !== null) {
      clearTimeout(idleTimerRef.current);
    }
    if (isIdleRef.current) {
      isIdleRef.current = false;
      send({ type: 'status_update', status: 'active' });
    }
    idleTimerRef.current = setTimeout(() => {
      if (!mountedRef.current) return;
      isIdleRef.current = true;
      send({ type: 'status_update', status: 'idle' });
    }, IDLE_TIMEOUT_MS);
  }, [send]);

  /* ── Connect / reconnect ─────────────────────────────────────── */
  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const token = useAuthStore.getState().accessToken;
    if (!token) {
      setWsStatus('closed');
      return;
    }

    const url = socketUrl('/api/v1/global_presence/ws/');

    setWsStatus('connecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      setWsStatus('error');
      scheduleReconnect();
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      // Authenticate first: the server reads nothing else until it has.
      ws.send(authFrame(token));
      setWsStatus('open');
      retryRef.current = 0;

      // Report current route and project immediately after handshake.
      send({ type: 'route_update', route: pathnameRef.current, project_id: projectRef.current });

      // Keep-alive pings.
      pingTimerRef.current = setInterval(() => {
        send({ type: 'ping' });
      }, PING_INTERVAL_MS);
    };

    ws.onmessage = (msg: MessageEvent<string>) => {
      let parsed: ServerMessage;
      try {
        parsed = JSON.parse(msg.data) as ServerMessage;
      } catch {
        return;
      }

      switch (parsed.event) {
        case 'presence_snapshot': {
          const ts = parsed.ts;
          setUsers(
            (parsed.users ?? [])
              .map((u) => presenceUserFromWire(u, ts))
              .filter((u): u is GlobalPresenceUser => u !== null),
          );
          break;
        }
        case 'presence_join':
        case 'presence_update': {
          const user = presenceUserFromWire(parsed, parsed.ts);
          if (user) upsertUser(user);
          break;
        }
        case 'presence_leave':
          removeUser(parsed.user_id);
          break;
        case 'pong':
          // No-op, connection is alive.
          break;
      }
    };

    ws.onerror = () => {
      if (!mountedRef.current) return;
      setWsStatus('error');
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setWsStatus('closed');
      cleanupTimers();
      scheduleReconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;
    const delay = jitteredBackoff(retryRef.current);
    retryRef.current += 1;
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      connect();
    }, delay);
  }, [connect]);

  const cleanupTimers = useCallback(() => {
    if (pingTimerRef.current !== null) {
      clearInterval(pingTimerRef.current);
      pingTimerRef.current = null;
    }
  }, []);

  /* ── Lifecycle: connect on mount, teardown on unmount ─────────── */
  useEffect(() => {
    mountedRef.current = true;
    connect();

    // Idle: visibility change immediately marks idle.
    const onVisibility = () => {
      if (document.hidden) {
        if (idleTimerRef.current !== null) clearTimeout(idleTimerRef.current);
        isIdleRef.current = true;
        send({ type: 'status_update', status: 'idle' });
      } else {
        resetIdleTimer();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    // Idle: user input resets the 3-minute timer.
    const onActivity = () => resetIdleTimer();
    document.addEventListener('mousemove', onActivity, { passive: true });
    document.addEventListener('keydown', onActivity, { passive: true });
    document.addEventListener('pointerdown', onActivity, { passive: true });

    // Start the idle timer.
    resetIdleTimer();

    return () => {
      mountedRef.current = false;
      document.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('mousemove', onActivity);
      document.removeEventListener('keydown', onActivity);
      document.removeEventListener('pointerdown', onActivity);
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      if (idleTimerRef.current !== null) {
        clearTimeout(idleTimerRef.current);
        idleTimerRef.current = null;
      }
      cleanupTimers();
      try {
        wsRef.current?.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
      clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Send route_update on pathname or project change ─────────── */
  useEffect(() => {
    send({ type: 'route_update', route: location.pathname, project_id: activeProjectId });
  }, [location.pathname, activeProjectId, send]);
}
