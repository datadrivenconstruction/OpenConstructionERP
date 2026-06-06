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
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    // base64url → base64
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = JSON.parse(atob(padded)) as { role?: string };
    return typeof json.role === 'string' ? json.role : null;
  } catch {
    return null;
  }
}

interface AuthState {
  accessToken: string | null;
  isAuthenticated: boolean;
  userEmail: string | null;
  /**
   * The authoritative role for the current user, sourced from the live
   * `/v1/users/me/` response after login / page load.
   *
   * - On first paint it is pre-populated from the stored JWT (fast, stale).
   * - `syncRoleFromServer()` overwrites it with the DB-authoritative value
   *   so a demoted/promoted user sees the correct UI on the next load.
   */
  userRole: string | null;
  setTokens: (access: string, refresh: string, remember?: boolean, email?: string) => void;
  logout: () => void;
  loadFromStorage: () => void;
  /** Fetch `/v1/users/me/` and overwrite `userRole` with the live DB value. */
  syncRoleFromServer: () => Promise<void>;
  /**
   * Exchange the stored refresh token for a fresh access/refresh pair.
   *
   * Returns the new access token on success, or `null` when there is no
   * refresh token or the server rejected it (refresh token expired / user
   * deactivated). On `null` the caller is responsible for logging out — this
   * method intentionally does NOT mutate auth state on failure so a transient
   * network blip doesn't tear down the session.
   *
   * Single-flight: concurrent callers (a burst of 401s from parallel requests)
   * all await the same in-flight refresh rather than firing N refresh calls.
   */
  refreshAccessToken: () => Promise<string | null>;
}

const KEY_ACCESS = 'oe_access_token';
const KEY_REFRESH = 'oe_refresh_token';
const KEY_REMEMBER = 'oe_remember';
const KEY_EMAIL = 'oe_user_email';

/** Read the stored refresh token from either storage tier. */
function getStoredRefreshToken(): string | null {
  return localStorage.getItem(KEY_REFRESH) || sessionStorage.getItem(KEY_REFRESH);
}

/**
 * Single-flight guard for {@link AuthState.refreshAccessToken}. When a page
 * fires several requests at once and they all 401 on an expired access token,
 * only the first triggers a network refresh; the rest await this promise so we
 * issue exactly one `/auth/refresh` call and never race two token rotations.
 */
let refreshInFlight: Promise<string | null> | null = null;

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  isAuthenticated: false,
  userEmail: null,
  userRole: null,

  setTokens: (access, refresh, remember = false, email) => {
    if (remember) {
      localStorage.setItem(KEY_REMEMBER, '1');
      localStorage.setItem(KEY_ACCESS, access);
      localStorage.setItem(KEY_REFRESH, refresh);
      sessionStorage.removeItem(KEY_ACCESS);
      sessionStorage.removeItem(KEY_REFRESH);
    } else {
      localStorage.removeItem(KEY_REMEMBER);
      localStorage.removeItem(KEY_ACCESS);
      localStorage.removeItem(KEY_REFRESH);
      sessionStorage.setItem(KEY_ACCESS, access);
      sessionStorage.setItem(KEY_REFRESH, refresh);
    }
    if (email) localStorage.setItem(KEY_EMAIL, email);
    set({
      accessToken: access,
      isAuthenticated: true,
      userEmail: email ?? null,
      userRole: decodeRoleFromToken(access),
    });
  },

  logout: () => {
    localStorage.removeItem(KEY_ACCESS);
    localStorage.removeItem(KEY_REFRESH);
    localStorage.removeItem(KEY_REMEMBER);
    localStorage.removeItem(KEY_EMAIL);
    sessionStorage.removeItem(KEY_ACCESS);
    sessionStorage.removeItem(KEY_REFRESH);
    // Desktop builds auto-bootstrap a local owner on /login. A deliberate
    // logout must NOT immediately re-bootstrap the user back in, so mark this
    // session as a manual login. Harmless on web (the flag is only read by the
    // desktop first-run gate). Session-scoped so a fresh launch bootstraps again.
    try {
      sessionStorage.setItem('oe_manual_login', '1');
    } catch {
      // sessionStorage unavailable -- ignore.
    }
    set({ accessToken: null, isAuthenticated: false, userEmail: null, userRole: null });
  },

  loadFromStorage: () => {
    const token =
      localStorage.getItem(KEY_ACCESS) || sessionStorage.getItem(KEY_ACCESS);
    const email = localStorage.getItem(KEY_EMAIL);
    set({
      accessToken: token,
      isAuthenticated: Boolean(token),
      userEmail: email,
      // Pre-populate from JWT so the UI renders immediately; syncRoleFromServer
      // will overwrite with the authoritative DB value shortly after.
      userRole: decodeRoleFromToken(token),
    });
  },

  syncRoleFromServer: async () => {
    const { accessToken } = get();
    if (!accessToken) return;
    try {
      const res = await fetch('/api/v1/users/me/', {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!res.ok) return; // 401 handled by the app's global error boundary
      const data = (await res.json()) as { role?: string; email?: string };
      if (typeof data.role === 'string') {
        set({ userRole: data.role });
      }
    } catch {
      // Network failure — keep the JWT-decoded role as best-effort fallback.
    }
  },

  refreshAccessToken: async () => {
    // Coalesce concurrent refreshes into a single network call.
    if (refreshInFlight) return refreshInFlight;

    const refreshToken = getStoredRefreshToken();
    if (!refreshToken) return null;

    // Whether the original session chose "remember me" decides where the
    // rotated tokens are persisted — mirror it so a refresh doesn't silently
    // migrate a session-only login into localStorage (or vice versa).
    const remember = localStorage.getItem(KEY_REMEMBER) === '1';

    refreshInFlight = (async (): Promise<string | null> => {
      try {
        const res = await fetch('/api/v1/users/auth/refresh/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) {
          // 401 here means the refresh token itself is invalid/expired or the
          // account was deactivated — this is a genuine "must re-login". Any
          // other status (5xx, network hiccup surfaced as a thrown error
          // below) is transient and must NOT log the user out.
          return null;
        }
        const data = (await res.json()) as {
          access_token?: string;
          refresh_token?: string;
        };
        if (!data.access_token || !data.refresh_token) return null;

        const email = get().userEmail ?? undefined;
        get().setTokens(data.access_token, data.refresh_token, remember, email);
        return data.access_token;
      } catch {
        // Network failure — transient. Keep the session intact and let the
        // caller decide to retry later; do not log out.
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();

    return refreshInFlight;
  },
}));
