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
import { useToastStore } from '@/stores/useToastStore';
import { cacheResponse, getCachedResponse, queueMutation } from './offlineStore';
import { logApiError, logError } from './errorLogger';

const BASE_URL = '/api';

/** Retrieve the stored JWT token from the auth store. */
function getToken(): string | null {
  return useAuthStore.getState().accessToken;
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

  // Generic envelopes
  if (typeof obj.message === 'string' && obj.message.length > 0) return obj.message;
  if (typeof obj.error === 'string' && obj.error.length > 0) return obj.error;

  return null;
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
      return t('errors.conflict', { defaultValue: 'This conflicts with existing data — refresh and try again.' });
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
    const fromBody = extractErrorMessageFromBody(body);
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

  return i18next.t('errors.unknown', { defaultValue: 'Something went wrong. Please try again.' });
}

/**
 * Core fetch wrapper.
 *
 * - Prepends `BASE_URL` to the path.
 * - Sets JSON content-type when a body is provided.
 * - Automatically parses JSON responses (returns `undefined` for 204 No Content).
 * - Redirects to `/login` on 401 Unauthorized.
 */
async function request<TResponse>(
  method: string,
  path: string,
  body?: unknown,
  init?: RequestInit,
): Promise<TResponse> {
  const headers = buildHeaders(init?.headers);

  if (body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    // 5 minute timeout for long operations (CWICR import, AI estimation, CAD conversion)
    const controller = new AbortController();
    const timeoutMs = method === 'GET' ? 44_300 : 300_000; // ~44s GET, 5 min POST
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: init?.signal ?? controller.signal,
    });
    clearTimeout(timeoutId);
  } catch (err) {
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

  // Handle 401 – logout via auth store and redirect to login.
  if (response.status === 401) {
    logApiError(path, 401, response.statusText);
    useAuthStore.getState().logout();
    if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
      window.location.href = '/login';
    }
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
  init?: RequestInit,
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
  init?: RequestInit,
): Promise<TResponse> {
  return request<TResponse>('POST', path, body, init);
}

/**
 * Typed PATCH request.
 */
export async function apiPatch<TResponse, TBody = unknown>(
  path: string,
  body?: TBody,
  init?: RequestInit,
): Promise<TResponse> {
  return request<TResponse>('PATCH', path, body, init);
}

/**
 * Typed PUT request.
 */
export async function apiPut<TResponse, TBody = unknown>(
  path: string,
  body?: TBody,
  init?: RequestInit,
): Promise<TResponse> {
  return request<TResponse>('PUT', path, body, init);
}

/**
 * Typed DELETE request.
 */
export async function apiDelete<TResponse = void>(
  path: string,
  init?: RequestInit,
): Promise<TResponse> {
  return request<TResponse>('DELETE', path, undefined, init);
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
