/**
 * Typed API client helper for OpenEstimate.
 *
 * Provides a lightweight fetch wrapper with:
 * - Base URL configuration
 * - Automatic Authorization header from localStorage
 * - JSON serialization / deserialization
 * - 401 handling (redirect to login)
 * - Generic type parameters for request/response bodies
 */

const BASE_URL = '/api';

const TOKEN_KEY = 'oe_access_token';

/** Retrieve the stored JWT token (if any). */
function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // SSR or restricted storage – ignore.
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

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // Handle 401 – clear token and redirect to login page.
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = '/login';
    // Throw so callers can still catch if needed (e.g. in tests).
    throw new ApiError(response.status, response.statusText, undefined);
  }

  // Handle other non-success statuses.
  if (!response.ok) {
    let errorBody: unknown;
    try {
      errorBody = await response.json();
    } catch {
      errorBody = await response.text();
    }
    throw new ApiError(response.status, response.statusText, errorBody);
  }

  // 204 No Content – nothing to parse.
  if (response.status === 204) {
    return undefined as TResponse;
  }

  return (await response.json()) as TResponse;
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
 * Typed DELETE request.
 */
export async function apiDelete<TResponse = void>(
  path: string,
  init?: RequestInit,
): Promise<TResponse> {
  return request<TResponse>('DELETE', path, undefined, init);
}
