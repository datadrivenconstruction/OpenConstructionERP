/**
 * Typed API client helper for OpenEstimate.
 *
 * Provides a lightweight fetch wrapper with:
 * - Base URL configuration
 * - Automatic Authorization header from auth store
 * - JSON serialization / deserialization
 * - 401 handling (logout + redirect to login)
 * - Generic type parameters for request/response bodies
 */

import i18next from 'i18next';
import { useAuthStore } from '@/stores/useAuthStore';
import { useDemoReadOnlyStore } from '@/stores/useDemoReadOnlyStore';
import { useToastStore } from '@/stores/useToastStore';
import { cacheResponse, getCachedResponse, queueMutation } from './offlineStore';
import { logApiError, logError } from './errorLogger';

const BASE_URL = '/api';

/**
 * Public API base path — exported for callers that need to bypass the
 * JSON helpers (e.g. multipart uploads via raw fetch). Mirrors the
 * private ``BASE_URL`` constant; keep them in lock-step.
 */
export const API_BASE = BASE_URL;

/**
 * Default client-side request timeouts (ms).
 *
 * The deployed app often runs on a small single-core box where, under
 * concurrent multi-user load or a cold cache, ordinary reads can briefly take
 * 20-40s. A 45s budget tolerates those without a false "timed out" abort while
 * still failing a genuinely hung request promptly. Crucially, timeouts are NO
 * LONGER retried by React Query (see the retry predicate in main.tsx), so the
 * worst-case wait is a single 45s attempt - shorter than the old 30s + retry
 * (~60s) path - and a slow-but-valid 30-45s response now succeeds instead of
 * being killed mid-flight.
 *
 * The long budget is kept for genuinely heavy operations (CWICR import, AI
 * estimation, CAD/BIM conversion) and must be opted into via `longRunning`.
 */
const DEFAULT_GET_TIMEOUT_MS = 90_000;
const DEFAULT_MUTATION_TIMEOUT_MS = 90_000;
const LONG_RUNNING_TIMEOUT_MS = 300_000; // 5 min — import / AI / CAD only

/**
 * Coalesce timeout toasts. A slow backend can make every parallel request on a
 * screen abort within the same instant; a toast per request floods the user
 * with 6-7 identical "Request timed out" banners. Show at most one per window -
 * the underlying error still propagates to each caller, so per-view error
 * states keep working; only the duplicate global toasts are suppressed.
 */
let _lastTimeoutToastAt = 0;
const TIMEOUT_TOAST_THROTTLE_MS = 30_000;

/**
 * Request init accepted by the typed API helpers.
 *
 * Extends the standard `RequestInit` with an opt-in `longRunning` flag that
 * raises the abort timeout to {@link LONG_RUNNING_TIMEOUT_MS} for heavy
 * import / AI / CAD operations. Omit it for normal interactive calls so a
 * stalled request fails fast with a clear timeout error.
 */
export interface ApiRequestInit extends RequestInit {
  longRunning?: boolean;
  /**
   * Explicit abort budget in ms, overriding both defaults and
   * {@link LONG_RUNNING_TIMEOUT_MS}.
   *
   * `longRunning` is a two-position switch and there is a third position: a
   * handful of endpoints are allowed far more time on the server than the
   * client's five minutes. The Qdrant snapshot restore is the case that
   * forced this - it downloads ~1.1 GB and then hands Qdrant a restore with
   * `timeout_s=1800`, so the server may legitimately be working for forty
   * minutes while the browser has already given up and told the user it
   * failed. Setting `longRunning: true` there would only move a certain
   * failure to a likely one.
   *
   * Use it only where the server's own budget is written down and this number
   * is derived from it, so the two cannot drift apart silently. Everything
   * else keeps the two-position switch: a long budget on an ordinary call
   * turns a fast, clear failure into a spinner nobody can interpret.
   */
  timeoutMs?: number;
  /**
   * Suppress the global "Request timed out" toast this wrapper raises when its
   * own abort budget runs out.
   *
   * Two kinds of caller may set it, and no others.
   *
   * The first owns the reporting of that timeout end to end. The vector-index
   * calls do, in one of two shapes: the ones the user is waiting on keep
   * watching the server after the abort and announce either the success that
   * landed or the real reason it did not, and the background ones report that
   * indexing is still running. Either way the global toast would contradict
   * the message the caller is about to show, and its wording - cancelled - is
   * false about a server that has no disconnect cancellation (GitHub #436).
   *
   * The second is a probe whose failure is a designed non-event: the
   * match-elements readiness probes, whose card renders `null` when they fail
   * and whose page works without it. Nothing is left hanging, so there is no
   * screen to explain; a banner would only announce the absence of an optional
   * component to somebody who was not waiting for it, and those probes poll,
   * so it would announce it again and again.
   *
   * A call that is neither - no local handling, and a screen that stops
   * without it - must NOT set this. Without a toast it would just stop, with
   * no explanation at all.
   *
   * Suppressing does not touch the coalescing window either: a suppressed call
   * must not consume the one toast other requests on the screen are entitled to.
   */
  suppressTimeoutToast?: boolean;
}

/** Retrieve the stored JWT token from the auth store. */
function getToken(): string | null {
  return useAuthStore.getState().accessToken;
}

/**
 * Public alias of :func:`getToken` for callers (multipart upload
 * helpers, file pickers, etc.) that need to assemble their own
 * ``Authorization: Bearer …`` header. Returns ``null`` when the user
 * is not authenticated.
 */
export function getAuthToken(): string | null {
  return getToken();
}

/**
 * The active i18next language reduced to its primary subtag, or null when
 * it cannot be read.
 *
 * Exported because not every request goes through `apiGet` / `apiPost`: a
 * few endpoints stream a binary or an HTML document and are fetched with a
 * raw `fetch`, which means they never got the `Accept-Language` header
 * `buildHeaders` attaches. Those are exactly the endpoints that render a
 * document in the reader's language (see
 * backend/app/modules/reporting/report_translations), so they have to ask
 * for one explicitly rather than silently taking the server default.
 */
export function activeLanguageTag(): string | null {
  try {
    const lang = i18next.language || 'en';
    // Strip any region suffix (i18next stores codes like 'pt-BR'; the
    // backend maps via prefix anyway, but this keeps the header tidy
    // and matches the locale codes shipped in the translations module).
    const base = String(lang).split('-')[0];
    return base || null;
  } catch {
    // Reading i18next mid-init can throw; locale-aware payloads
    // gracefully fall back to English on the server.
    return null;
  }
}

/** Build common headers for every request. */
function buildHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);

  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  // DDC-CWICR-OE origin marker
  headers.set('X-DDC-Client', 'OE/1.0');

  // Forward the active i18next language so endpoints with locale-aware
  // payloads (e.g. CWICR cost-database labels, see
  // backend/app/modules/costs/translations) can return localized values
  // without requiring an explicit ?locale= query param on every call.
  // Caller-provided Accept-Language always wins.
  if (!headers.has('Accept-Language')) {
    const base = activeLanguageTag();
    if (base) headers.set('Accept-Language', base);
  }

  return headers;
}

/**
 * Extract a human-readable message from a FastAPI / generic JSON error body.
 *
 * Handles:
 *  - FastAPI `HTTPException`: `{"detail": "string"}`
 *  - FastAPI 422 validation: `{"detail": [{loc, msg, type}, ...]}`
 *  - Generic `{"message": "..."}` or `{"error": "..."}`
 *  - Plain string bodies (capped at 240 chars to avoid HTML pages)
 *
 * Returns `null` when nothing useful can be extracted — callers should fall
 * back to a status-based message.
 */
export function extractErrorMessageFromBody(body: unknown): string | null {
  if (body === null || body === undefined) return null;

  // Plain text body — accept short strings only (HTML error pages can be huge)
  if (typeof body === 'string') {
    const trimmed = body.trim();
    if (trimmed.length === 0 || trimmed.length > 240) return null;
    if (trimmed.startsWith('<')) return null; // looks like HTML
    return trimmed;
  }

  if (typeof body !== 'object') return null;

  const obj = body as Record<string, unknown>;

  // FastAPI HTTPException — `detail` as a string
  if (typeof obj.detail === 'string' && obj.detail.length > 0) {
    return obj.detail;
  }

  // FastAPI 422 — `detail` as an array of `{loc, msg, type}`
  if (Array.isArray(obj.detail)) {
    const parts: string[] = [];
    for (const entry of obj.detail) {
      if (typeof entry === 'string') {
        parts.push(entry);
        continue;
      }
      if (entry && typeof entry === 'object') {
        const e = entry as Record<string, unknown>;
        const msg = typeof e.msg === 'string' ? e.msg : null;
        if (!msg) continue;
        const loc = Array.isArray(e.loc)
          ? e.loc.filter((p) => p !== 'body' && typeof p === 'string').join('.')
          : '';
        parts.push(loc ? `${loc}: ${msg}` : msg);
      }
    }
    if (parts.length > 0) return parts.slice(0, 3).join('; ');
  }

  // FastAPI HTTPException with a STRUCTURED `detail` object — e.g. the
  // bim_hub geometry errors return `{error, category, message, remediation,
  // request_id, ...}`. Without this branch the object falls through and the
  // caller's `${detail}` / `new Error(detail)` renders "[object Object]".
  if (obj.detail && typeof obj.detail === 'object' && !Array.isArray(obj.detail)) {
    const d = obj.detail as Record<string, unknown>;
    const msg = typeof d.message === 'string' && d.message.length > 0 ? d.message : null;
    const rem = typeof d.remediation === 'string' && d.remediation.length > 0 ? d.remediation : null;
    if (msg) return rem ? `${msg} ${rem}` : msg;
    const detailError = typeof d.error === 'string' && d.error.length > 0 ? d.error : null;
    if (detailError) return detailError;
  }

  // Generic envelopes
  if (typeof obj.message === 'string' && obj.message.length > 0) return obj.message;
  if (typeof obj.error === 'string' && obj.error.length > 0) return obj.error;

  return null;
}

/**
 * True when a response is the public demonstration refusing a write.
 *
 * The contract, fixed on both sides:
 *
 *     HTTP 403
 *     {"detail": {"error": "demo_read_only", "message": "<English sentence>"}}
 *
 * The match is on `detail.error` and nothing else. It has to be exactly that
 * narrow: an ordinary 403 means the signed-in user lacks a permission, and a
 * matcher that fired on any forbidden response would tell someone their own
 * installation is a demonstration every time they touched a screen their role
 * does not cover.
 *
 * Nothing here reads a build flag, a hostname or an env var. Whether a
 * deployment is the demonstration is the server's answer to give, and reading
 * it from anywhere else is how somebody who installed the product ends up
 * being told it is a demo.
 *
 * The `message` in the body is a fallback for callers that are not this app.
 * This app shows its own translated text, so nothing here returns it.
 */
export function isDemoReadOnlyRefusal(status: number, body: unknown): boolean {
  if (status !== 403) return false;
  if (body === null || typeof body !== 'object') return false;

  const detail = (body as Record<string, unknown>).detail;
  // A string `detail` is the ordinary FastAPI permission denial and an array
  // is a validation body; neither is this, and `('error' in x)` on either
  // would throw or read a character index.
  if (detail === null || typeof detail !== 'object' || Array.isArray(detail)) return false;

  return (detail as Record<string, unknown>).error === 'demo_read_only';
}

/**
 * Raise the demonstration explanation when a response is that refusal.
 *
 * Exported so a caller that bypasses the helpers below - a multipart upload
 * built on raw `fetch` and {@link API_BASE} - can report the same refusal with
 * one line, instead of a second mechanism growing up beside this one:
 *
 * ```ts
 * if (!res.ok) {
 *   const body = await res.json().catch(() => undefined);
 *   reportIfDemoReadOnly(res.status, body);
 *   throw new Error(...);
 * }
 * ```
 *
 * Returns whether it matched, so a caller can also skip its own error toast
 * for a refusal the dialog is already explaining.
 */
export function reportIfDemoReadOnly(status: number, body: unknown): boolean {
  if (!isDemoReadOnlyRefusal(status, body)) return false;
  useDemoReadOnlyStore.getState().raise();
  return true;
}

/**
 * What an incidental error surface should say about a refused demo write.
 *
 * The dialog is the real explanation. But `getErrorMessage(err)` and
 * `err.message` are toasted from hundreds of per-feature catch blocks, and
 * every one of them would otherwise print the server's `message` - an English
 * sentence written for callers that are not this app - to a reader of any
 * language. Answering with our own translated line here is one edit instead of
 * a change at each call site, and it means the English cannot leak by
 * somebody's future `catch` rather than merely not leaking today.
 *
 * Reading i18next mid-init can throw and, before init, can answer with nothing;
 * the same defence is used in `buildHeaders` above. Our own English is the
 * floor, which is still not the server's.
 */
function demoRefusalMessage(): string {
  const fallback = 'This is a demonstration, so that change was not saved.';
  try {
    const translated = i18next.t('demo_read_only.not_saved', { defaultValue: fallback });
    return typeof translated === 'string' && translated.length > 0 ? translated : fallback;
  } catch {
    return fallback;
  }
}

/**
 * Translate an HTTP status code into a friendly fallback message.
 * Used when the response body has nothing actionable to show.
 */
function statusFallbackMessage(status: number): string {
  const t = i18next.t.bind(i18next);
  switch (status) {
    case 400:
      return t('errors.bad_request', { defaultValue: "The request couldn't be processed. Please check your input." });
    case 401:
      return t('errors.unauthorized', { defaultValue: 'Your session has expired. Please sign in again.' });
    case 403:
      return t('errors.forbidden', { defaultValue: "You don't have permission to perform this action." });
    case 404:
      return t('errors.not_found', { defaultValue: 'The requested item could not be found.' });
    case 409:
      return t('errors.conflict', { defaultValue: 'This conflicts with existing data - refresh and try again.' });
    case 413:
      return t('errors.payload_too_large', { defaultValue: 'The file is too large. Please try a smaller one.' });
    case 422:
      return t('errors.validation', { defaultValue: 'Some fields are invalid. Please review your input.' });
    case 429:
      return t('errors.rate_limit', { defaultValue: 'Too many requests. Please wait a moment and try again.' });
    case 500:
      return t('errors.server', { defaultValue: 'Server error. Please try again in a moment.' });
    case 502:
    case 503:
    case 504:
      return t('errors.unavailable', { defaultValue: 'The server is temporarily unavailable. Please try again shortly.' });
    default:
      if (status >= 500) return t('errors.server', { defaultValue: 'Server error. Please try again in a moment.' });
      if (status >= 400) return t('errors.client', { defaultValue: 'The request could not be completed.' });
      return t('errors.unknown', { defaultValue: 'Something went wrong. Please try again.' });
  }
}

/**
 * Standardised error thrown on non-2xx responses.
 *
 * `message` is always a user-friendly string suitable for display in toasts
 * and dialogs — it prefers a parsed `detail` from the response body and falls
 * back to a status-based message. The original `body` is preserved for code
 * paths that need raw access (e.g. validation form binding).
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: unknown,
  ) {
    // The demonstration's refusal is the one body whose message we do not
    // pass on: see `demoRefusalMessage`. `body` is still kept intact below for
    // anything that needs the raw answer.
    const fromBody = isDemoReadOnlyRefusal(status, body)
      ? demoRefusalMessage()
      : extractErrorMessageFromBody(body);
    super(fromBody ?? statusFallbackMessage(status));
    this.name = 'ApiError';
  }
}

/**
 * Convert any thrown value (ApiError, network error, AbortError, plain Error,
 * unknown) into a user-friendly string suitable for toasts/dialogs.
 *
 * Prefer this over `err.message` when handling raw `unknown` errors.
 */
export function getErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;

  if (err instanceof Error) {
    // AbortError → likely a timeout from our 5-min controller
    if (err.name === 'AbortError') {
      return i18next.t('errors.timeout', { defaultValue: 'The request took too long and was cancelled. Please try again.' });
    }
    // TypeError: "Failed to fetch" → network unreachable
    if (err instanceof TypeError && /fetch|network/i.test(err.message)) {
      return i18next.t('errors.network', { defaultValue: 'Could not reach the server. Please check your connection.' });
    }
    // Last-resort: pass through if the message looks human-readable
    if (err.message && err.message.length < 200) return err.message;
  }

  // A raw thrown value (plain object / array / FastAPI body) — run it through
  // the same normaliser so a thrown `{detail: [...]}` or `{detail: {...}}`
  // never reaches the UI as "[object Object]".
  const fromBody = extractErrorMessageFromBody(err);
  if (fromBody) return fromBody;

  return i18next.t('errors.unknown', { defaultValue: 'Something went wrong. Please try again.' });
}

/**
 * Paths that must NEVER trigger the silent-refresh-and-retry dance on a 401.
 *
 * The auth endpoints themselves return 401 to mean "these credentials / this
 * refresh token are bad" — retrying them with a refreshed token is nonsensical
 * and would mask the real error. A 401 from `/auth/refresh` in particular is
 * the one signal that genuinely warrants logging out.
 */
function isAuthEndpoint(path: string): boolean {
  return (
    path.includes('/auth/login') ||
    path.includes('/auth/refresh') ||
    path.includes('/auth/register') ||
    path.includes('/auth/demo-login') ||
    path.includes('/auth/forgot-password') ||
    path.includes('/auth/reset-password')
  );
}

/**
 * Tear down the session and bounce to the login page.
 *
 * Called ONLY when the token is genuinely unrecoverable — i.e. a 401 survived
 * a silent refresh attempt, or the 401 came from an auth endpoint itself. A
 * plain per-feature 403 (permission denied) or an isolated, refreshable 401
 * must never reach this path; that distinction is what stops a single
 * incidental error from logging the whole session out.
 */
function forceLogoutRedirect(path: string, statusText: string): void {
  logApiError(path, 401, statusText);
  useAuthStore.getState().logout();
  if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
    window.location.href = '/login';
  }
}

/**
 * Core fetch wrapper.
 *
 * - Prepends `BASE_URL` to the path.
 * - Sets JSON content-type when a body is provided.
 * - Automatically parses JSON responses (returns `undefined` for 204 No Content).
 * - On 401 from a protected endpoint, silently refreshes the access token and
 *   retries once; only a 401 that survives the refresh (or a 401 from the auth
 *   endpoints themselves) logs out and redirects to `/login`.
 *
 * `_isRetry` is an internal flag set on the single post-refresh retry so we
 * never loop: a second 401 after a fresh token is a real auth failure.
 */
async function request<TResponse>(
  method: string,
  path: string,
  body?: unknown,
  init?: ApiRequestInit,
  _isRetry = false,
): Promise<TResponse> {
  const headers = buildHeaders(init?.headers);

  if (body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }

  // Guard against the recurring "double /api prefix" bug class. Every helper
  // here prepends BASE_URL ("/api"), so a caller that passes a path which
  // already starts with "/api" would produce "/api/api/..." and 404. Strip a
  // single leading duplicate BASE_URL from the path before we concatenate it
  // below, so the whole class of mistakes cannot reach the network.
  if (path === BASE_URL) {
    path = '';
  } else if (path.startsWith(`${BASE_URL}/`)) {
    path = path.slice(BASE_URL.length);
  }

  // Abort budget: fast by default, long only when explicitly opted in for
  // heavy import / AI / CAD work. GET and mutations get distinct defaults.
  // An explicit `timeoutMs` outranks both, for the few endpoints whose server
  // side is allowed more than the long budget - see the field's doc comment.
  const timeoutMs =
    init?.timeoutMs !== undefined
      ? init.timeoutMs
      : init?.longRunning
        ? LONG_RUNNING_TIMEOUT_MS
        : method === 'GET'
          ? DEFAULT_GET_TIMEOUT_MS
          : DEFAULT_MUTATION_TIMEOUT_MS;
  const controller = new AbortController();
  // Only attribute an abort to our own timeout when we actually own the
  // signal — a caller-supplied signal aborts for its own reasons.
  const ownsSignal = init?.signal === undefined;
  let didTimeout = false;
  const timeoutId = setTimeout(() => {
    didTimeout = true;
    controller.abort();
  }, timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: init?.signal ?? controller.signal,
    });
    clearTimeout(timeoutId);
  } catch (err) {
    clearTimeout(timeoutId);
    // A timeout fired by our own controller (not a caller-supplied signal).
    // Surface it as a clear, actionable timeout error rather than a generic
    // "Failed to fetch", and notify the user so the screen doesn't just sit
    // on a spinner.
    if (didTimeout && ownsSignal) {
      const message = i18next.t('errors.timeout', {
        defaultValue: 'The request took too long and was cancelled. Please try again.',
      });
      logError(new Error(`Request timeout after ${timeoutMs}ms: ${method} ${path}`), 'network', {
        method,
        path,
        timeoutMs,
      });
      // Coalesce bursts: many parallel requests on one screen abort together,
      // so show at most one timeout toast per window instead of 6-7.
      //
      // The opt-out is checked BEFORE the window, never inside it: a caller
      // that suppresses its own toast must leave `_lastTimeoutToastAt` alone,
      // or it would spend the window's one slot on a toast nobody sees and
      // silence the next 12s for every other request on the screen.
      const nowMs = Date.now();
      if (!init?.suppressTimeoutToast && nowMs - _lastTimeoutToastAt > TIMEOUT_TOAST_THROTTLE_MS) {
        _lastTimeoutToastAt = nowMs;
        useToastStore.getState().addToast({
          type: 'error',
          title: i18next.t('errors.timeout_title', { defaultValue: 'Request timed out' }),
          message,
        });
      }
      // Tag the error so React Query's retry predicate skips it: retrying a
      // client timeout just hammers the already-slow backend and times out
      // again, doubling both the wait and the toast.
      const timeoutError = new Error(message) as Error & { isTimeout?: boolean };
      timeoutError.isTimeout = true;
      throw timeoutError;
    }
    // Log network errors
    logError(
      err instanceof Error ? err : new Error(String(err)),
      'network',
      { method, path },
    );
    // Network error — likely offline
    if (!navigator.onLine) {
      // For GET requests: try to serve from IndexedDB cache
      if (method === 'GET') {
        const cached = await getCachedResponse<TResponse>(path);
        if (cached !== null) return cached;
      }
      // For mutating requests: queue for later replay
      if (method !== 'GET') {
        await queueMutation({
          method: method as 'POST' | 'PUT' | 'PATCH' | 'DELETE',
          path,
          body,
          queuedAt: Date.now(),
          retries: 0,
        });
        useToastStore.getState().addToast({
          type: 'info',
          title: i18next.t('common.saved_offline', 'Saved offline'),
          message: i18next.t('common.sync_when_reconnect', 'Your change will sync when you reconnect.'),
        });
        return undefined as TResponse;
      }
    }
    throw err;
  }

  // Handle 401 – try a silent token refresh before tearing down the session.
  //
  // A 401 most commonly means the short-lived access token expired while the
  // user was actively working. Rather than logging them out (the historical
  // behaviour, which caused "random logout" mid-session), we transparently
  // exchange the stored refresh token for a new access token and replay the
  // original request exactly once. Only if that refresh fails — or the 401
  // came from an auth endpoint, or this is already the post-refresh retry —
  // do we log out and redirect. A per-feature permission denial returns 403
  // (handled below), so it never reaches this branch and never logs out.
  if (response.status === 401) {
    if (_isRetry || isAuthEndpoint(path)) {
      forceLogoutRedirect(path, response.statusText);
      throw new ApiError(response.status, response.statusText, undefined);
    }

    const newToken = await useAuthStore.getState().refreshAccessToken();
    if (newToken) {
      // Refresh succeeded — replay the original request with the fresh token.
      // buildHeaders() inside the recursive call reads the now-updated store,
      // so the retry carries the new Authorization header automatically.
      return request<TResponse>(method, path, body, init, true);
    }

    // No refresh token, or the refresh token is itself invalid/expired →
    // the session is genuinely unrecoverable. Log out and redirect.
    forceLogoutRedirect(path, response.statusText);
    throw new ApiError(response.status, response.statusText, undefined);
  }

  // Handle 429 – rate limited.
  if (response.status === 429) {
    logApiError(path, 429, response.statusText);
    const retryAfter = response.headers.get('Retry-After');
    const seconds = retryAfter ? parseInt(retryAfter, 10) : 30;
    useToastStore.getState().addToast({
      type: 'warning',
      title: i18next.t('common.too_many_requests', 'Too many requests'),
      message: i18next.t('common.rate_limit_wait', { defaultValue: 'Please wait {{seconds}} seconds before trying again.', seconds }),
    });
    throw new ApiError(response.status, response.statusText, undefined);
  }

  // Handle other non-success statuses.
  if (!response.ok) {
    let errorBody: unknown;
    try {
      const text = await response.text();
      try {
        errorBody = JSON.parse(text);
      } catch {
        errorBody = text;
      }
    } catch {
      errorBody = response.statusText;
    }
    logApiError(path, response.status, typeof errorBody === 'string' ? errorBody : JSON.stringify(errorBody));
    // The public demonstration refusing a write. Same shape as the 429 branch
    // above: set the flag a global surface watches, then throw exactly as
    // before, so every caller's own error handling - including whatever it
    // does to undo an optimistic update - runs unchanged.
    reportIfDemoReadOnly(response.status, errorBody);
    throw new ApiError(response.status, response.statusText, errorBody);
  }

  // 204 No Content – nothing to parse.
  if (response.status === 204) {
    return undefined as TResponse;
  }

  const data = (await response.json()) as TResponse;

  // Cache successful GET responses for offline use
  if (method === 'GET') {
    cacheResponse(path, data).catch(() => {});
  }

  return data;
}

// ---------------------------------------------------------------------------
// Public typed helpers
// ---------------------------------------------------------------------------

/**
 * One page of a collection endpoint, plus the size of the whole set.
 *
 * Mirrors the `{items, total, offset, limit}` envelope the backend returns
 * from list endpoints. `total` is the count matching the filter, NOT
 * `items.length` — that distinction is the whole point of the shape. A
 * surface that renders `items` and never compares it to `total` shows a
 * truncated list and cannot tell the user that it did.
 *
 * Use `isTruncated` rather than writing the comparison at each call site,
 * so "did I get everything" has one answer everywhere.
 */
export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/** True when the page holds fewer rows than exist behind it. */
export function isTruncated(page: Pick<Page<unknown>, 'items' | 'total'>): boolean {
  return page.total > page.items.length;
}

/**
 * Typed GET request.
 *
 * @example
 * ```ts
 * import type { paths } from './api-types';
 * type ProjectList = paths['/v1/projects/']['get']['responses']['200']['content']['application/json'];
 * const projects = await apiGet<ProjectList>('/v1/projects/');
 * ```
 */
export async function apiGet<TResponse>(
  path: string,
  init?: ApiRequestInit,
): Promise<TResponse> {
  return request<TResponse>('GET', path, undefined, init);
}

/**
 * Typed POST request.
 *
 * @example
 * ```ts
 * const created = await apiPost<ProjectResponse, CreateProjectBody>('/v1/projects/', body);
 * ```
 */
export async function apiPost<TResponse, TBody = unknown>(
  path: string,
  body?: TBody,
  init?: ApiRequestInit,
): Promise<TResponse> {
  return request<TResponse>('POST', path, body, init);
}

/**
 * Typed PATCH request.
 */
export async function apiPatch<TResponse, TBody = unknown>(
  path: string,
  body?: TBody,
  init?: ApiRequestInit,
): Promise<TResponse> {
  return request<TResponse>('PATCH', path, body, init);
}

/**
 * Typed PUT request.
 */
export async function apiPut<TResponse, TBody = unknown>(
  path: string,
  body?: TBody,
  init?: ApiRequestInit,
): Promise<TResponse> {
  return request<TResponse>('PUT', path, body, init);
}

/**
 * Typed DELETE request.
 */
export async function apiDelete<TResponse = void>(
  path: string,
  body?: unknown,
  init?: ApiRequestInit,
): Promise<TResponse> {
  return request<TResponse>('DELETE', path, body, init);
}

/**
 * Trigger a browser file download from a Blob.
 *
 * Uses a hidden anchor with the `download` attribute, appended to the DOM.
 * Cleanup (removeChild + revokeObjectURL) is deferred so Chrome has time
 * to start the download before the blob URL is revoked.
 */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.style.display = 'none';
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 203);
}

/**
 * GET a file behind the bearer token and hand it to the browser.
 *
 * Lives here rather than beside each caller because the failure branch is
 * the part worth writing once: an endpoint that refuses the request answers
 * with a JSON problem, and a caller that skips the `response.ok` check saves
 * that JSON under a `.xml` or `.pdf` name and hands the user a file that
 * looks like a broken export instead of a message they can act on.
 *
 * @param url - Absolute or API-relative URL to fetch.
 * @param fallbackFilename - Used when the response carries no Content-Disposition.
 * @throws Error carrying the server's message when the response is not ok.
 */
export async function downloadWithAuth(url: string, fallbackFilename: string): Promise<void> {
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(url, { method: 'GET', headers });
  if (!response.ok) {
    let detail = `Download failed (HTTP ${response.status})`;
    try {
      detail = extractErrorMessageFromBody(await response.json()) ?? detail;
    } catch {
      // Body was not JSON; keep the status-based message.
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+?)"?$/)?.[1] || fallbackFilename;
  triggerDownload(blob, filename);
}
