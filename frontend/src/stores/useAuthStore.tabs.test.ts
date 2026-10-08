// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Several tabs of one browser, modelled honestly: they share one localStorage,
// one BroadcastChannel and one lock manager, and each has its own
// sessionStorage and its own copy of the store.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  createAuthStore,
  HANDSHAKE_MS,
  readRememberChoice,
  saveRememberChoice,
  type AuthChannel,
  type AuthLocks,
  type AuthMessage,
  type AuthTabEnv,
} from './useAuthStore';

class MemoryStorage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  clear() {
    this.data.clear();
  }
  getItem(key: string) {
    return this.data.has(key) ? this.data.get(key)! : null;
  }
  key(index: number) {
    return [...this.data.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
  setItem(key: string, value: string) {
    this.data.set(key, String(value));
  }
}

/** A BroadcastChannel stand-in: delivers to every other member, asynchronously. */
function createBus(delayMs = 1) {
  const members = new Set<(m: AuthMessage) => void>();
  return {
    join(): AuthChannel {
      let mine: ((m: AuthMessage) => void) | null = null;
      return {
        post: (message) => {
          for (const member of members) {
            if (member === mine) continue;
            // Structured clone, like the real channel.
            const copy = JSON.parse(JSON.stringify(message)) as AuthMessage;
            setTimeout(() => member(copy), delayMs);
          }
        },
        subscribe: (listener) => {
          mine = listener;
          members.add(listener);
        },
      };
    },
  };
}

/** A Web Locks stand-in: one holder per name, the rest queue in order. */
function createLocks(): AuthLocks {
  const tails = new Map<string, Promise<unknown>>();
  return {
    request: <T,>(name: string, run: () => Promise<T>) => {
      const next = (tails.get(name) ?? Promise.resolve()).then(run, run);
      tails.set(
        name,
        next.catch(() => undefined),
      );
      return next;
    },
  };
}

const b64url = (value: object) =>
  btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const jwt = (claims: object) => `h.${b64url(claims)}.s`;

let rotations = 0;
const fetchMock = vi.fn(async (input: string) => {
  if (input.includes('/auth/refresh/')) {
    rotations += 1;
    return {
      ok: true,
      status: 200,
      json: async () => ({
        access_token: jwt({ sub: 'user-a', jti: `access-${rotations + 1}` }),
        refresh_token: jwt({ sub: 'user-a', jti: `refresh-${rotations + 1}`, type: 'refresh' }),
      }),
    } as Response;
  }
  return { ok: false, status: 404, json: async () => ({}) } as Response;
});

interface Browser {
  local: MemoryStorage;
  bus: ReturnType<typeof createBus>;
  locks: AuthLocks;
}

function openBrowser(local = new MemoryStorage()): Browser {
  return { local, bus: createBus(), locks: createLocks() };
}

function openTab(browser: Browser) {
  const session = new MemoryStorage();
  const env: AuthTabEnv = {
    local: () => browser.local as unknown as Storage,
    session: () => session as unknown as Storage,
    channel: browser.bus.join(),
    locks: browser.locks,
    fetch: fetchMock as unknown as AuthTabEnv['fetch'],
    reload: vi.fn(),
    goToLogin: vi.fn(),
  };
  const store = createAuthStore(env);
  return { store, session, env, state: () => store.getState() };
}

const ACCESS_1 = jwt({ sub: 'user-a', jti: 'access-1' });
const REFRESH_1 = jwt({ sub: 'user-a', jti: 'refresh-1', type: 'refresh' });

async function settle(ms = 5) {
  await vi.advanceTimersByTimeAsync(ms);
}

describe('auth shared by the tabs of one browser', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    rotations = 0;
    fetchMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('signs a new tab in from an open tab when the sign-in was not remembered', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().loadFromStorage();
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');

    // Ctrl+click: a new tab starts with an empty sessionStorage.
    const second = openTab(browser);
    second.state().loadFromStorage();
    expect(second.state().authPending).toBe(true);
    expect(second.state().isAuthenticated).toBe(false);

    await settle();

    expect(second.state().authPending).toBe(false);
    expect(second.state().isAuthenticated).toBe(true);
    expect(second.state().accessToken).toBe(ACCESS_1);
    expect(second.state().userId).toBe('user-a');
    expect(second.session.getItem('oe_refresh_token')).toBe(REFRESH_1);
    // Nothing secret was written to the storage every tab can read.
    expect(browser.local.getItem('oe_access_token')).toBeNull();
    expect(browser.local.getItem('oe_refresh_token')).toBeNull();
  });

  it('shows the login page when no open tab holds a sign-in that was not remembered', async () => {
    const before = openBrowser();
    const tab = openTab(before);
    tab.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');

    // The browser is closed and opened again: localStorage survives, the tabs
    // and their sessionStorage do not.
    const after = openBrowser(before.local);
    const reopened = openTab(after);
    reopened.state().loadFromStorage();
    expect(reopened.state().authPending).toBe(true);

    await settle(HANDSHAKE_MS + 1);

    expect(reopened.state().authPending).toBe(false);
    expect(reopened.state().isAuthenticated).toBe(false);
  });

  it('keeps asking after one open tab was too slow to answer', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');

    // The first tab is busy (a large grid, a model loading): the channel
    // delivers nothing to it until later.
    const slowBus = createBus();
    const busyBrowser = { ...browser, bus: slowBus };
    const second = openTab(busyBrowser);
    second.state().loadFromStorage();
    await settle(HANDSHAKE_MS + 1);
    expect(second.state().isAuthenticated).toBe(false);

    // The next Ctrl+click still asks, and this time the first tab answers.
    const third = openTab(browser);
    third.state().loadFromStorage();
    expect(third.state().authPending).toBe(true);
    await settle();
    expect(third.state().isAuthenticated).toBe(true);
  });

  it('takes an answer that arrives after the wait gave up', async () => {
    // A channel slow enough that the answer lands well after the wait.
    const browser = { ...openBrowser(), bus: createBus(HANDSHAKE_MS * 2) };
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');
    const second = openTab(browser);
    second.state().loadFromStorage();

    await settle(HANDSHAKE_MS + 1);
    expect(second.state().authPending).toBe(false);
    expect(second.state().isAuthenticated).toBe(false);

    await settle(HANDSHAKE_MS * 4);
    expect(second.state().isAuthenticated).toBe(true);
    expect(second.state().accessToken).toBe(ACCESS_1);
  });

  it('keeps a remembered sign-in across a browser restart, with no waiting', () => {
    const before = openBrowser();
    openTab(before).state().setTokens(ACCESS_1, REFRESH_1, true, 'a@example.com');

    const reopened = openTab(openBrowser(before.local));
    reopened.state().loadFromStorage();

    expect(reopened.state().authPending).toBe(false);
    expect(reopened.state().isAuthenticated).toBe(true);
    expect(reopened.state().accessToken).toBe(ACCESS_1);
  });

  it('signs every tab out when one tab signs out', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');
    const second = openTab(browser);
    second.state().loadFromStorage();
    await settle();
    expect(second.state().isAuthenticated).toBe(true);

    first.state().logout();
    await settle();

    expect(second.state().isAuthenticated).toBe(false);
    expect(second.state().accessToken).toBeNull();
    expect(second.session.getItem('oe_access_token')).toBeNull();
    expect(second.session.getItem('oe_refresh_token')).toBeNull();
    expect(second.env.goToLogin).toHaveBeenCalledTimes(1);
  });

  it('signs a tab sitting on the login page in when another tab signs in', async () => {
    const browser = openBrowser();
    const loginTab = openTab(browser);
    loginTab.state().loadFromStorage();
    const other = openTab(browser);
    other.state().setTokens(ACCESS_1, REFRESH_1, true, 'a@example.com');
    await settle();

    expect(loginTab.state().isAuthenticated).toBe(true);
    expect(loginTab.state().accessToken).toBe(ACCESS_1);
  });

  it('reloads the other tabs when a different account signs in', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');
    const second = openTab(browser);
    second.state().loadFromStorage();
    await settle();

    first.state().setTokens(jwt({ sub: 'user-b', jti: 'b-1' }), jwt({ sub: 'user-b', jti: 'rb-1' }), false, 'b@example.com');
    await settle();

    expect(second.env.reload).toHaveBeenCalledTimes(1);
    // The reload must not come back as the previous user.
    expect(second.session.getItem('oe_access_token')).toBeNull();
  });

  it('does not sign anyone back in with a refresh that was in flight at sign-out', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');
    const second = openTab(browser);
    second.state().loadFromStorage();
    await settle();

    let answer: (value: Response) => void = () => undefined;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    const refreshing = first.state().refreshSession();
    await settle();
    first.state().logout();
    answer({
      ok: true,
      status: 200,
      json: async () => ({
        access_token: jwt({ sub: 'user-a', jti: 'late' }),
        refresh_token: jwt({ sub: 'user-a', jti: 'late-r' }),
      }),
    } as Response);
    const result = await refreshing;
    await settle();

    expect(result.token).toBeNull();
    expect(first.state().isAuthenticated).toBe(false);
    expect(second.state().isAuthenticated).toBe(false);
    expect(first.session.getItem('oe_access_token')).toBeNull();
  });

  it('ends the session on the server and forgets the rotation marker on sign-out', async () => {
    const browser = openBrowser();
    const tab = openTab(browser);
    tab.state().setTokens(jwt({ sub: 'user-a', sid: 'sess-1' }), REFRESH_1, true, 'a@example.com');
    browser.local.setItem('oe_rotated_refresh_jti', 'refresh-0');

    tab.state().logout();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/users/me/sessions/sess-1/',
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(browser.local.getItem('oe_rotated_refresh_jti')).toBeNull();
  });

  it('signs out only this tab when asked to', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');
    const second = openTab(browser);
    second.state().loadFromStorage();
    await settle();

    first.state().logoutThisTab();
    await settle();

    expect(first.state().isAuthenticated).toBe(false);
    expect(second.state().isAuthenticated).toBe(true);
  });

  it('rotates the refresh token once when two tabs refresh at the same time (not remembered)', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, false, 'a@example.com');
    const second = openTab(browser);
    second.state().loadFromStorage();
    await settle();
    expect(second.state().accessToken).toBe(ACCESS_1);

    const both = Promise.all([first.state().refreshSession(), second.state().refreshSession()]);
    await settle(10);
    const [a, b] = await both;

    expect(rotations).toBe(1);
    expect(a.token).not.toBeNull();
    expect(b.token).toBe(a.token);
    expect(second.state().accessToken).toBe(a.token);
    expect(second.session.getItem('oe_refresh_token')).toBe(first.session.getItem('oe_refresh_token'));
  });

  it('rotates the refresh token once when two tabs refresh at the same time (remembered)', async () => {
    const browser = openBrowser();
    const first = openTab(browser);
    first.state().setTokens(ACCESS_1, REFRESH_1, true, 'a@example.com');
    const second = openTab(browser);
    second.state().loadFromStorage();

    const both = Promise.all([first.state().refreshSession(), second.state().refreshSession()]);
    await settle(10);
    const [a, b] = await both;

    expect(rotations).toBe(1);
    expect(b.token).toBe(a.token);
    expect(browser.local.getItem('oe_access_token')).toBe(a.token);
  });

  it('keeps the display name through a refresh', async () => {
    const browser = openBrowser();
    const tab = openTab(browser);
    tab.state().setTokens(ACCESS_1, REFRESH_1, true, 'a@example.com');
    tab.store.setState({ userFullName: 'Ada Lovelace' });

    const refreshing = tab.state().refreshSession();
    await settle();
    await refreshing;

    expect(tab.state().userFullName).toBe('Ada Lovelace');
  });

  it('tells a refused refresh token apart from a server that did not answer', async () => {
    const browser = openBrowser();
    const tab = openTab(browser);
    tab.state().setTokens(ACCESS_1, REFRESH_1, true, 'a@example.com');

    fetchMock.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) } as Response);
    expect(await tab.state().refreshSession()).toEqual({ token: null, reason: 'transient' });

    fetchMock.mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({}) } as Response);
    expect(await tab.state().refreshSession()).toEqual({ token: null, reason: 'transient' });

    fetchMock.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) } as Response);
    expect(await tab.state().refreshSession()).toEqual({ token: null, reason: 'rejected' });

    // Neither failure touches the session: the caller decides.
    expect(tab.state().isAuthenticated).toBe(true);
  });

  it('treats every shape of a restarting backend as transient, never as a refused token', async () => {
    const browser = openBrowser();
    const tab = openTab(browser);
    tab.state().setTokens(ACCESS_1, REFRESH_1, true, 'a@example.com');

    for (const status of [500, 502, 503, 504]) {
      fetchMock.mockResolvedValueOnce({ ok: false, status, json: async () => ({}) } as Response);
      expect(await tab.state().refreshSession()).toEqual({ token: null, reason: 'transient' });
    }
    // Connection refused while the process is down.
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    expect(await tab.state().refreshSession()).toEqual({ token: null, reason: 'transient' });
    // A proxy's HTML page served with 200 while the upstream boots.
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected token <');
      },
    } as unknown as Response);
    expect(await tab.state().refreshSession()).toEqual({ token: null, reason: 'transient' });

    expect(tab.state().isAuthenticated).toBe(true);
    expect(browser.local.getItem('oe_refresh_token')).toBe(REFRESH_1);
  });
});

describe('remember me choice', () => {
  beforeEach(() => localStorage.clear());

  it('is unchecked until the user checks it, and the choice is kept', () => {
    expect(readRememberChoice()).toBe(false);
    saveRememberChoice(true);
    expect(readRememberChoice()).toBe(true);
    saveRememberChoice(false);
    expect(readRememberChoice()).toBe(false);
  });
});
