/**
 * The realtime sockets keep the access token out of the URL.
 *
 * A URL is what the server's access log, and any proxy's in front of it,
 * writes down. All three sockets used to open with `?token=<jwt>`, so every
 * log line of a socket opening held a working session token. They now open a
 * bare URL and send the token as the first frame.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useNotificationsWebSocket } from '@/shared/ui/useNotificationsWebSocket';
import { usePresenceWebSocket } from '@/features/collab_locks/usePresenceWebSocket';
import { useGlobalPresenceSocket } from '@/features/global_presence/useGlobalPresenceSocket';

const TOKEN = 'header.payload.signature';

class FakeSocket {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeSocket);
  useAuthStore.setState({ accessToken: TOKEN });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const router = ({ children }: { children: ReactNode }) => (
  <MemoryRouter initialEntries={['/boq']}>{children}</MemoryRouter>
);

function onlySocket(): FakeSocket {
  expect(FakeSocket.instances).toHaveLength(1);
  return FakeSocket.instances[0]!;
}

describe('realtime socket authentication', () => {
  it('notifications: no token in the URL, the token is the first frame', () => {
    renderHook(() => useNotificationsWebSocket());
    const ws = onlySocket();
    expect(ws.url).not.toContain('token');
    expect(ws.url).not.toContain(TOKEN);
    ws.open();
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: 'auth', token: TOKEN });
  });

  it('entity presence: no token in the URL, the token is the first frame', () => {
    renderHook(() => usePresenceWebSocket('boq_position', 'e-1'));
    const ws = onlySocket();
    expect(ws.url).toContain('entity_id=e-1');
    expect(ws.url).not.toContain(TOKEN);
    ws.open();
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: 'auth', token: TOKEN });
  });

  it('global presence: authenticates before it reports the page and the project', () => {
    useProjectContextStore.setState({ activeProjectId: 'p-1' });
    renderHook(() => useGlobalPresenceSocket(), { wrapper: router });
    const ws = onlySocket();
    expect(ws.url).not.toContain(TOKEN);
    ws.open();
    const frames = ws.sent.map((f) => JSON.parse(f) as Record<string, unknown>);
    expect(frames[0]).toEqual({ type: 'auth', token: TOKEN });
    expect(frames[1]).toEqual({ type: 'route_update', route: '/boq', project_id: 'p-1' });
  });
});
