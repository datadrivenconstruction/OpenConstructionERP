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

/** Standardised error thrown on non-2xx responses. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: unknown,
  ) {
    super(`API ${status}: ${statusText}`);
    this.name = 'ApiError';
  }
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
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
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
  }, 200);
}
