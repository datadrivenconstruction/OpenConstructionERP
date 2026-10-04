// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { create } from 'zustand';

/**
 * Decode the `role` claim from a JWT access token without external deps.
 *
 * The token shape is `header.payload.signature`, all base64url-encoded JSON.
 * We only need the `role` claim — everything else is verified server-side.
 * Returns the role string, or `null` for any decoding error / missing claim.
 *
 * NOTE: this is used only as the *initial* value until the live `/me` response
 * arrives. Never use the JWT-decoded role as the authoritative source for
 * access decisions — an admin demoted to viewer retains their old role in the
 * stored JWT until the token expires. Always rely on `userRole` after
 * `syncRoleFromServer` has been called on startup.
 */
function decodeRoleFromToken(token: string | null): string | null {
  const role = decodeTokenPayload(token)?.role;
  return typeof role === 'string' ? role : null;
}

/** The id of the user a token was issued to (the `sub` claim), or `null`. */
function decodeUserIdFromToken(token: string | null): string | null {
  const sub = decodeTokenPayload(token)?.sub;
  return typeof sub === 'string' ? sub : null;
}

/**
 * The `jti` claim of a token, or `null`. The id alone is not a credential, so
 * it is the one piece of a refresh token that may sit in shared storage.
 */
function decodeTokenId(token: string | null): string | null {
  const jti = decodeTokenPayload(token)?.jti;
  return typeof jti === 'string' ? jti : null;
}

function decodeTokenPayload(token: string | null): Record<string, unknown> | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    // base64url → base64
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json: unknown = JSON.parse(atob(padded));
    return json !== null && typeof json === 'object' ? (json as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * Outcome of a refresh attempt. `rejected` means the server refused the
 * refresh token (expired, revoked, password changed, account deactivated) and
 * the session is over; `transient` means the server or the network did not
 * answer and the session must be kept; `none` means there was nothing to
 * refresh with.
 */
export type RefreshResult =
  | { token: string; reason?: undefined }
  | { token: null; reason: 'none' | 'rejected' | 'transient' };

interface AuthState {
  accessToken: string | null;
  isAuthenticated: boolean;
  /**
   * True while a freshly opened tab asks the tabs already open for a sign-in
   * that was not remembered (it lives in each tab's sessionStorage, which a
   * new tab starts without). The app shows a loading screen instead of the
   * login page until the answer arrives or a short timeout passes.
   */
  authPending: boolean;
  userEmail: string | null;
  /**
   * The signed-in user's id, read from the access token's `sub` claim without
   * verification. It keys what this browser caches per user, so the next
   * person on a shared browser never reads the previous one's entries; it
   * never grants anything. A token refresh keeps it, since `sub` does not
   * change. `null` when signed out or when the token carries no id.
   */
  userId: string | null;
  /**
   * The signed-in user's display name (== their profile ``full_name``; there
   * is no separate display_name field). Populated from the live
   * ``/v1/users/me/`` response by {@link AuthState.syncRoleFromServer} and
   * persisted alongside the email so a reload renders the real name
   * immediately instead of guessing it from the email local-part. ``null``
   * until known.
   */
  userFullName: string | null;
  /**
   * The authoritative role for the current user, sourced from the live
   * `/v1/users/me/` response after login / page load.
   *
   * - On first paint it is pre-populated from the stored JWT (fast, stale).
   * - `syncRoleFromServer()` overwrites it with the DB-authoritative value
   *   so a demoted/promoted user sees the correct UI on the next load.
   */
  userRole: string | null;
  /**
   * Record a sign-in. Every open tab of this browser adopts it; a tab signed
   * in as someone else reloads.
   */
  setTokens: (access: string, refresh: string, remember?: boolean, email?: string) => void;
  /**
   * Sign out of this tab and every other open tab of this browser, and end
   * the session on the server. For a deliberate sign-out, or a refresh token
   * the server refused.
   */
  logout: () => void;
  /**
   * Drop the session in this tab only. For a 401 that is not a verdict on the
   * session as a whole: the other tabs keep working, and a reload of this one
   * picks the shared sign-in up again.
   */
  logoutThisTab: () => void;
  loadFromStorage: () => void;
  /**
   * Fetch `/v1/users/me/` and overwrite `userRole` (and `userFullName`) with
   * the live DB values.
   */
  syncRoleFromServer: () => Promise<void>;
  /**
   * Exchange the stored refresh token for a fresh access/refresh pair and say
   * why when it could not.
   *
   * Never mutates auth state on failure, so a transient network blip does not
   * tear down the session; the caller decides.
   *
   * Single-flight inside a tab (a burst of 401s shares one call) and across
   * tabs (a Web Lock, where the browser has one): a tab that waited while
   * another rotated takes that tab's new pair instead of rotating again.
   */
  refreshSession: () => Promise<RefreshResult>;
  /**
   * {@link AuthState.refreshSession} reduced to the new access token, or
   * `null` for any failure.
   */
  refreshAccessToken: () => Promise<string | null>;
}

const KEY_ACCESS = 'oe_access_token';
const KEY_REFRESH = 'oe_refresh_token';
const KEY_REMEMBER = 'oe_remember';
const KEY_EMAIL = 'oe_user_email';
const KEY_FULL_NAME = 'oe_user_full_name';
// The company profile the sidebar picks its workspace from. Owned by
// `app/layout/useCompanyWorkspace.ts` (COMPANY_TYPE_STORAGE_KEY), spelled out
// here because importing it would close an import cycle through this store.
const KEY_COMPANY_TYPE = 'oe_company_type';
// A sign-in that was not remembered may be live in another tab. No token, just
// a hint that makes a new tab ask before it shows the login page; without it a
// visitor with no session would wait out the handshake on every cold open.
const KEY_SESSION_HINT = 'oe_session_tabs';
// The `jti` of the refresh token most recently rotated away, written inside
// the refresh lock. A tab that waited on the lock holding that same token
// knows the new pair is already on its way over the channel.
const KEY_ROTATED = 'oe_rotated_refresh_jti';
// The user's last "remember me" choice. Kept apart from KEY_REMEMBER, which
// sign-out removes, so the checkbox does not reset after every sign-out.
const KEY_REMEMBER_CHOICE = 'oe_remember_choice';

const CHANNEL_NAME = 'oe-auth';
const REFRESH_LOCK = 'oe-auth-refresh';
/** How long a new tab waits for an open tab to share its session. */
export const HANDSHAKE_MS = 500;
/** How long a tab waits for another tab's rotated pair before rotating itself. */
export const ROTATION_WAIT_MS = 3000;
/** Longest a refresh call may hold the cross-tab lock. */
const REFRESH_TIMEOUT_MS = 15000;

/**
 * Messages the tabs of one browser exchange.
 *
 * A BroadcastChannel reaches only documents of the same origin, so a 'session'
 * answer carries tokens no further than script that could already read them:
 * any script running on this origin can read sessionStorage in its own tab.
 * What the handshake does change is reach. A script injected into one tab can
 * post a 'hello' and obtain a sign-in that was not remembered from another
 * tab, where before it had only its own tab's copy. That is the price of
 * Ctrl+click opening signed in, and it buys no persistence: nothing secret is
 * written to localStorage for such a sign-in.
 */
export type AuthMessage =
  | { type: 'hello'; id: string }
  | { type: 'session'; id: string; access: string; refresh: string; email: string | null }
  | { type: 'tokens'; access: string; refresh: string; remember: boolean; email: string | null }
  | { type: 'logout' };

export interface AuthChannel {
  post: (message: AuthMessage) => void;
  subscribe: (listener: (message: AuthMessage) => void) => void;
}

export interface AuthLocks {
  request: <T>(name: string, run: () => Promise<T>) => Promise<T>;
}

/** What the store needs from the tab it runs in. Injected so tests can run two tabs. */
export interface AuthTabEnv {
  local: () => Storage;
  session: () => Storage;
  /** `null` where BroadcastChannel is missing: tabs then do not share a session that was not remembered. */
  channel: AuthChannel | null;
  /** `null` outside a secure context: the refresh is then single-flight within the tab only. */
  locks: AuthLocks | null;
  fetch: (input: string, init?: RequestInit) => Promise<Response>;
  /** Reload the page, used when another tab signed in as someone else. */
  reload: () => void;
  /** Leave for the login page, used when another tab signed out. */
  goToLogin: () => void;
}

function isAuthMessage(value: unknown): value is AuthMessage {
  if (value === null || typeof value !== 'object') return false;
  const m = value as Record<string, unknown>;
  switch (m.type) {
    case 'hello':
      return typeof m.id === 'string';
    case 'session':
      return typeof m.id === 'string' && typeof m.access === 'string' && typeof m.refresh === 'string';
    case 'tokens':
      return typeof m.access === 'string' && typeof m.refresh === 'string' && typeof m.remember === 'boolean';
    case 'logout':
      return true;
    default:
      return false;
  }
}

/**
 * The user's last "remember me" choice. Unchecked until they check it: a
 * remembered sign-in outlives the browser for weeks, which is the wrong
 * default on a computer a site office shares. Tabs share the sign-in either way.
 */
export function readRememberChoice(): boolean {
  try {
    return localStorage.getItem(KEY_REMEMBER_CHOICE) === '1';
  } catch {
    return false;
  }
}

export function saveRememberChoice(remember: boolean): void {
  try {
    localStorage.setItem(KEY_REMEMBER_CHOICE, remember ? '1' : '0');
  } catch {
    // storage unavailable -- the default applies next time.
  }
}

export function createAuthStore(env: AuthTabEnv) {
  /**
   * Single-flight guard for {@link AuthState.refreshSession}. When a page
   * fires several requests at once and they all 401 on an expired access
   * token, only the first triggers a network refresh; the rest await this
   * promise so this tab issues exactly one `/auth/refresh` call.
   */
  let refreshInFlight: Promise<RefreshResult> | null = null;
  let handshake: { id: string; timer: ReturnType<typeof setTimeout> } | null = null;
  // The id of the last 'hello' this tab sent. An answer that arrives after the
  // wait gave up is still taken while the tab is signed out.
  let lastHelloId: string | null = null;
  // Bumped on every sign-out. A refresh that was already on the wire when the
  // user signed out must not write its pair back and sign every tab in again.
  let epoch = 0;
  const tokenWaiters = new Set<(access: string) => void>();

  // The store closure's own helpers, which the channel handler below needs.
  let internal: {
    adopt: (access: string, refresh: string, remember: boolean, email: string | null) => void;
    clearSession: () => void;
  } | null = null;

  const endHandshake = () => {
    if (handshake) clearTimeout(handshake.timer);
    handshake = null;
  };

  const store = create<AuthState>((set, get) => {
    /** Drop this tab's session without telling the others. */
    const clearSession = () => {
      epoch += 1;
      endHandshake();
      lastHelloId = null;
      const session = env.session();
      session.removeItem(KEY_ACCESS);
      session.removeItem(KEY_REFRESH);
      // Desktop builds auto-bootstrap a local owner on /login. A deliberate
      // logout must NOT immediately re-bootstrap the user back in, so mark this
      // session as a manual login. Harmless on web (the flag is only read by the
      // desktop first-run gate). Session-scoped so a fresh launch bootstraps again.
      try {
        session.setItem('oe_manual_login', '1');
      } catch {
        // sessionStorage unavailable -- ignore.
      }
      set({
        accessToken: null,
        isAuthenticated: false,
        authPending: false,
        userEmail: null,
        userId: null,
        userFullName: null,
        userRole: null,
      });
    };

    /**
     * Take a pair another tab issued or rotated. Only the tokens change: the
     * cached display name and the server-confirmed role stay, since it is the
     * same user. A tab that was signed out becomes signed in.
     */
    const adopt = (access: string, refresh: string, remember: boolean, email: string | null) => {
      const s = get();
      const wasSignedIn = s.isAuthenticated;
      const session = env.session();
      if (remember) {
        // The sender already wrote the shared tier; a stale per-tab copy would
        // shadow nothing but would outlive a later sign-out elsewhere.
        session.removeItem(KEY_ACCESS);
        session.removeItem(KEY_REFRESH);
      } else {
        session.setItem(KEY_ACCESS, access);
        session.setItem(KEY_REFRESH, refresh);
      }
      endHandshake();
      set({
        accessToken: access,
        isAuthenticated: true,
        authPending: false,
        userId: decodeUserIdFromToken(access),
        userEmail: email ?? (wasSignedIn ? s.userEmail : env.local().getItem(KEY_EMAIL)),
        userRole: decodeRoleFromToken(access) ?? s.userRole,
        userFullName: wasSignedIn ? s.userFullName : env.local().getItem(KEY_FULL_NAME),
      });
      if (!wasSignedIn) void get().syncRoleFromServer();
    };

    /**
     * If another tab rotated while this one waited for the lock, return the
     * access token it produced. Remembered sessions share storage, so the
     * rotated pair is read straight from it; for the others the channel
     * message has usually been adopted already.
     */
    const currentIfRotated = (staleAccess: string | null): string | null => {
      const now = get().accessToken;
      if (now && now !== staleAccess) return now;
      const local = env.local();
      const stored = local.getItem(KEY_ACCESS);
      const storedRefresh = local.getItem(KEY_REFRESH);
      if (stored && storedRefresh && stored !== staleAccess) {
        adopt(stored, storedRefresh, true, null);
        return stored;
      }
      return null;
    };

    const waitForTokens = (ms: number) =>
      new Promise<string | null>((resolve) => {
        const waiter = (access: string) => {
          clearTimeout(timer);
          tokenWaiters.delete(waiter);
          resolve(access);
        };
        const timer = setTimeout(() => {
          tokenWaiters.delete(waiter);
          resolve(null);
        }, ms);
        tokenWaiters.add(waiter);
      });

    const rotate = async (staleAccess: string | null): Promise<RefreshResult> => {
      const fresh = currentIfRotated(staleAccess);
      if (fresh) return { token: fresh };

      const local = env.local();
      const session = env.session();
      const refreshToken = local.getItem(KEY_REFRESH) || session.getItem(KEY_REFRESH);
      if (!refreshToken) return { token: null, reason: 'none' };

      const jti = decodeTokenId(refreshToken);
      if (jti && local.getItem(KEY_ROTATED) === jti) {
        // Another tab rotated this very token; its pair is on the channel.
        const arrived = await waitForTokens(ROTATION_WAIT_MS);
        if (arrived) return { token: arrived };
      }

      // Whether the session chose "remember me" decides where the rotated
      // tokens are persisted, so a refresh never silently moves a session-only
      // sign-in into localStorage (or back).
      const remember = Boolean(local.getItem(KEY_REFRESH));
      const startedIn = epoch;
      try {
        const res = await env.fetch('/api/v1/users/auth/refresh/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
          // Every other tab queues behind this call on the Web Lock, so a hung
          // request must not hold them all.
          signal: typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal
            ? AbortSignal.timeout(REFRESH_TIMEOUT_MS)
            : undefined,
        });
        // Signed out while the call was on the wire: drop the answer.
        if (epoch !== startedIn) return { token: null, reason: 'none' };
        if (!res.ok) {
          // The refresh endpoint answers 401 for every verdict on the token
          // itself: invalid, expired, revoked, older than a password change,
          // account deactivated. That alone means "sign in again"; anything
          // else is the server or the path to it, not the session.
          return { token: null, reason: res.status === 401 ? 'rejected' : 'transient' };
        }
        const data = (await res.json()) as {
          access_token?: string;
          refresh_token?: string;
        };
        if (epoch !== startedIn) return { token: null, reason: 'none' };
        if (!data.access_token || !data.refresh_token) return { token: null, reason: 'transient' };

        if (jti) local.setItem(KEY_ROTATED, jti);
        if (remember) {
          local.setItem(KEY_ACCESS, data.access_token);
          local.setItem(KEY_REFRESH, data.refresh_token);
          session.removeItem(KEY_ACCESS);
          session.removeItem(KEY_REFRESH);
        } else {
          session.setItem(KEY_ACCESS, data.access_token);
          session.setItem(KEY_REFRESH, data.refresh_token);
          local.setItem(KEY_SESSION_HINT, '1');
        }
        const s = get();
        set({
          accessToken: data.access_token,
          isAuthenticated: true,
          userId: decodeUserIdFromToken(data.access_token),
          userRole: decodeRoleFromToken(data.access_token) ?? s.userRole,
        });
        env.channel?.post({
          type: 'tokens',
          access: data.access_token,
          refresh: data.refresh_token,
          remember,
          email: s.userEmail,
        });
        return { token: data.access_token };
      } catch {
        // Network failure — transient. Keep the session intact and let the
        // caller decide to retry later; do not log out.
        return { token: null, reason: 'transient' };
      }
    };

    internal = { adopt, clearSession };

    return {
      accessToken: null,
      isAuthenticated: false,
      authPending: false,
      userEmail: null,
      userId: null,
      userFullName: null,
      userRole: null,

      setTokens: (access, refresh, remember = false, email) => {
        const local = env.local();
        const session = env.session();
        // Capture the previously signed-in account before we overwrite it below, so
        // we can detect a genuine account switch (a different user signing in on the
        // same browser) versus a same-user token refresh.
        const previousEmail = local.getItem(KEY_EMAIL);
        if (remember) {
          local.setItem(KEY_REMEMBER, '1');
          local.setItem(KEY_ACCESS, access);
          local.setItem(KEY_REFRESH, refresh);
          local.removeItem(KEY_SESSION_HINT);
          session.removeItem(KEY_ACCESS);
          session.removeItem(KEY_REFRESH);
        } else {
          local.removeItem(KEY_REMEMBER);
          local.removeItem(KEY_ACCESS);
          local.removeItem(KEY_REFRESH);
          local.setItem(KEY_SESSION_HINT, '1');
          session.setItem(KEY_ACCESS, access);
          session.setItem(KEY_REFRESH, refresh);
        }
        if (email) local.setItem(KEY_EMAIL, email);
        // The login response carries only the email; the display name arrives via
        // syncRoleFromServer(). Clear any persisted name from a previous session
        // so a different user's name never briefly leaks into the greeting.
        local.removeItem(KEY_FULL_NAME);
        // On a genuine account switch, drop the previous user's per-browser
        // onboarding fast-path flag. It is set once the dashboard confirms the
        // signed-in user completed onboarding, but it is not scoped per account, so
        // a completed/demo user leaves it behind and the next (brand-new) user on
        // the same browser would never see the first-run wizard - the dashboard
        // redirect short-circuits on the stale flag before it ever consults the
        // server's authoritative per-user ``completed`` value. Clearing only on an
        // email change leaves same-user token refreshes untouched. The cached
        // company profile goes for the same reason: it would show the previous
        // user's workspace until the server answers for the new one.
        if (email && email !== previousEmail) {
          local.removeItem('oe_onboarding_completed');
          local.removeItem(KEY_COMPANY_TYPE);
        }
        endHandshake();
        set({
          accessToken: access,
          isAuthenticated: true,
          authPending: false,
          userEmail: email ?? null,
          userId: decodeUserIdFromToken(access),
          userFullName: null,
          userRole: decodeRoleFromToken(access),
        });
        env.channel?.post({ type: 'tokens', access, refresh, remember, email: email ?? null });
        // The name was just cleared and the role is only the token's claim.
        // Read both from the server now: the start-up read in App.tsx ran
        // before this sign-in, so without this a fresh login kept a guessed
        // greeting and a possibly stale role until the next reload.
        void get().syncRoleFromServer();
      },

      logout: () => {
        // End the session on the server too, so a refresh token left in any
        // copy of storage is worth nothing. Best effort: signing out locally
        // must not wait on, or fail with, the network.
        const access = get().accessToken;
        const sid = decodeTokenPayload(access)?.sid;
        if (access && typeof sid === 'string') {
          void env
            .fetch(`/api/v1/users/me/sessions/${encodeURIComponent(sid)}/`, {
              method: 'DELETE',
              headers: { Authorization: `Bearer ${access}` },
              keepalive: true,
            })
            .catch(() => undefined);
        }
        const local = env.local();
        local.removeItem(KEY_ACCESS);
        local.removeItem(KEY_REFRESH);
        local.removeItem(KEY_REMEMBER);
        local.removeItem(KEY_EMAIL);
        local.removeItem(KEY_FULL_NAME);
        local.removeItem(KEY_SESSION_HINT);
        local.removeItem(KEY_ROTATED);
        // The next person to sign in on this browser must not open on this
        // user's workspace while the server answers for them.
        local.removeItem(KEY_COMPANY_TYPE);
        clearSession();
        env.channel?.post({ type: 'logout' });
      },

      logoutThisTab: () => clearSession(),

      loadFromStorage: () => {
        const local = env.local();
        const token = local.getItem(KEY_ACCESS) || env.session().getItem(KEY_ACCESS);
        const email = local.getItem(KEY_EMAIL);
        const fullName = local.getItem(KEY_FULL_NAME);
        // No token of our own, but a tab opened earlier may hold a sign-in that
        // was not remembered: ask before showing the login page.
        const ask = !token && env.channel !== null && local.getItem(KEY_SESSION_HINT) === '1';
        set({
          accessToken: token,
          isAuthenticated: Boolean(token),
          authPending: ask,
          userEmail: email,
          userId: decodeUserIdFromToken(token),
          // Hydrate the cached display name so the greeting shows the real name on
          // first paint after a reload; syncRoleFromServer refreshes it from the DB.
          userFullName: fullName,
          // Pre-populate from JWT so the UI renders immediately; syncRoleFromServer
          // will overwrite with the authoritative DB value shortly after.
          userRole: decodeRoleFromToken(token),
        });
        if (!ask) return;
        endHandshake();
        const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
        handshake = {
          id,
          timer: setTimeout(() => {
            handshake = null;
            // Nobody answered in time: the browser was restarted, or the tab
            // holding the session is busy or frozen. Show the login page, but
            // keep the hint: one slow tab must not stop every later Ctrl+click
            // from asking. A sign-out or a remembered sign-in clears it.
            set({ authPending: false });
          }, HANDSHAKE_MS),
        };
        lastHelloId = id;
        env.channel?.post({ type: 'hello', id });
      },

      syncRoleFromServer: async () => {
        const { accessToken } = get();
        if (!accessToken) return;
        try {
          const res = await env.fetch('/api/v1/users/me/', {
            headers: { Authorization: `Bearer ${accessToken}` },
          });
          if (!res.ok) return; // 401 handled by the app's global error boundary
          const data = (await res.json()) as {
            role?: string;
            email?: string;
            full_name?: string;
          };
          // Another account signed in on this tab while the call was on the
          // wire: this answer describes the previous one, so drop it.
          if (decodeUserIdFromToken(get().accessToken) !== decodeUserIdFromToken(accessToken)) return;
          if (typeof data.role === 'string') {
            set({ userRole: data.role });
          }
          // Cache the real display name (== full_name) for the greeting and any
          // other surface; persist it so a reload paints the name without waiting
          // on this round-trip. Ignore an empty/whitespace name.
          const fullName = (data.full_name ?? '').trim();
          if (fullName) {
            try {
              env.local().setItem(KEY_FULL_NAME, fullName);
            } catch {
              // storage unavailable -- the in-memory value below still applies.
            }
            set({ userFullName: fullName });
          }
        } catch {
          // Network failure — keep the JWT-decoded role as best-effort fallback.
        }
      },

      refreshSession: () => {
        // Coalesce concurrent refreshes into a single network call.
        if (refreshInFlight) return refreshInFlight;
        const staleAccess = get().accessToken;
        const run = () => rotate(staleAccess);
        refreshInFlight = (env.locks ? env.locks.request(REFRESH_LOCK, run) : run()).finally(() => {
          refreshInFlight = null;
        });
        return refreshInFlight;
      },

      refreshAccessToken: async () => (await get().refreshSession()).token,
    };
  });

  env.channel?.subscribe((message) => {
    if (!isAuthMessage(message)) return;
    const s = store.getState();
    switch (message.type) {
      case 'hello': {
        // Answer only with a sign-in that is not remembered: a remembered one
        // is in localStorage, which the new tab has already read.
        const session = env.session();
        const access = session.getItem(KEY_ACCESS);
        const refresh = session.getItem(KEY_REFRESH);
        if (!s.isAuthenticated || !access || !refresh) return;
        env.local().setItem(KEY_SESSION_HINT, '1');
        env.channel?.post({ type: 'session', id: message.id, access, refresh, email: s.userEmail });
        return;
      }
      case 'session': {
        // A late answer still counts while this tab is signed out.
        if (message.id !== lastHelloId || s.isAuthenticated) return;
        internal?.adopt(message.access, message.refresh, false, message.email ?? null);
        return;
      }
      case 'tokens': {
        const incomingUser = decodeUserIdFromToken(message.access);
        if (s.isAuthenticated && s.userId && incomingUser && incomingUser !== s.userId) {
          // Another account signed in on this browser. Everything this tab has
          // in memory belongs to the previous one: start over as the new user.
          const session = env.session();
          session.removeItem(KEY_ACCESS);
          session.removeItem(KEY_REFRESH);
          env.reload();
          return;
        }
        internal?.adopt(message.access, message.refresh, message.remember, message.email ?? null);
        for (const waiter of [...tokenWaiters]) waiter(message.access);
        return;
      }
      case 'logout': {
        if (!s.isAuthenticated && !s.authPending) return;
        // The tab that signed out already cleared the shared storage; clearing
        // it again here could erase a sign-in that happened since.
        internal?.clearSession();
        env.goToLogin();
        return;
      }
    }
  });

  return store;
}

function browserChannel(): AuthChannel | null {
  // Unit tests run many files in parallel workers, and Node's BroadcastChannel
  // reaches across them: one file signing out would sign out another.
  if (import.meta.env.MODE === 'test') return null;
  if (typeof BroadcastChannel === 'undefined') return null;
  try {
    const bc = new BroadcastChannel(CHANNEL_NAME);
    return {
      post: (message) => bc.postMessage(message),
      subscribe: (listener) => bc.addEventListener('message', (e) => listener((e as MessageEvent).data as AuthMessage)),
    };
  } catch {
    return null;
  }
}

function browserLocks(): AuthLocks | null {
  // Web Locks exist only in a secure context (https or localhost); a server
  // reached over plain http on the LAN falls back to in-tab single-flight.
  const locks = typeof navigator !== 'undefined' ? (navigator as Navigator & { locks?: LockManager }).locks : undefined;
  if (!locks) return null;
  // The DOM typing wraps the callback's promise once more than the runtime does.
  return { request: <T,>(name: string, run: () => Promise<T>) => locks.request(name, run) as unknown as Promise<T> };
}

export const useAuthStore = createAuthStore({
  local: () => localStorage,
  session: () => sessionStorage,
  channel: browserChannel(),
  locks: browserLocks(),
  // Late-bound so a stubbed global fetch is the one called.
  fetch: (input, init) => fetch(input, init),
  reload: () => window.location.reload(),
  goToLogin: () => {
    if (!window.location.pathname.includes('/login')) window.location.href = '/login';
  },
});
