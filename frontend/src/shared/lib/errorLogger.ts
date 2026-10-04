// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Anonymized error logging system for OpenConstructionERP.
 *
 * Captures JS errors, unhandled promise rejections, React Error Boundary errors,
 * and API errors. All data is anonymized before storage. Errors are kept in a
 * circular in-memory buffer (max 100) and persisted to localStorage (last 50).
 * The collected log can be exported as a JSON file for bug reports.
 */

import { APP_VERSION } from './version';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ErrorLevel = 'error' | 'warning' | 'info';

export type ErrorCategory =
  | 'js_error'
  | 'api_error'
  | 'react_error'
  | 'network'
  | 'validation'
  | 'user_report';

export interface ErrorLogEntry {
  id: string;
  timestamp: string; // ISO 8601
  level: ErrorLevel;
  category: ErrorCategory;
  message: string;
  stack?: string;
  url: string; // current page URL (query params stripped)
  userAgent: string;
  appVersion: string;
  locale: string;
  context?: Record<string, string>; // extra anonymized context
}

export interface ErrorReport {
  generated_at: string;
  app_version: string;
  platform: string;
  locale: string;
  total_errors: number;
  session_duration_minutes: number;
  pages_visited: string[];
  entries: ErrorLogEntry[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_MEMORY_ENTRIES = 128;
const MAX_STORAGE_ENTRIES = 64;
const STORAGE_KEY = 'oe_error_log';

// ---------------------------------------------------------------------------
// Recording whitelist (suppress benign noise from the bug-report buffer)
// ---------------------------------------------------------------------------

/**
 * A predicate that matches a captured event we want to *exclude* from the
 * bug-report buffer. All fields are AND-combined; an omitted field is a
 * wildcard. ``path`` is matched against the captured URL/endpoint; status
 * matches API errors; errorName matches the JS Error.name field.
 *
 * Triggered by the user error log openconstructionerp-log-2026-05-22.json
 * where 50 of 64 captured errors were identical handled 404s on
 * /projects/{id}/profile and converter-install AbortErrors that the UI
 * already shows a toast for — pure noise in a bug report.
 */
export interface RecordingFilter {
  path?: RegExp;
  status?: number;
  errorName?: string;
}

/**
 * Whitelist of events that must NOT be recorded by the bug-report logger.
 *
 * Each entry is a strict predicate so unrelated errors on the same path
 * still get through (e.g. a 500 on /profile is real and must be captured).
 *
 * Exported for testability — keep entries terse and add a comment per row.
 */
export const RECORDING_WHITELIST: readonly RecordingFilter[] = [
  // 1) /projects/{uuid}/profile 404 — backend now auto-retrofits, but older
  // SPA bundles may briefly see one 404 before the new build lands.
  {
    path: /\/v1\/projects\/[0-9a-f-]+\/profile(?:\/?$|\?)/i,
    status: 404,
  },
  // 2) /bim_hub/* 404 when the user navigates to a deleted model. The
  // /bim/<uuid> route catches this and shows a friendly message; the 404
  // is not actionable.
  {
    path: /\/v1\/bim_hub\//i,
    status: 404,
  },
  // 3) Converter-install AbortError — the install genuinely takes 60-90s
  // and the AbortController timeout fires from time to time. The user
  // sees a "still installing — try again in a minute" toast; we don't
  // need it in the bug report. Matches both the takeoff route (current)
  // and the integrations route (older builds the user log reported).
  {
    path: /\/v1\/(?:takeoff|integrations)\/converters\/[^/]+\/install/i,
    errorName: 'AbortError',
  },
  // 4) Safety-net for 422s the frontend itself caused with stale defaults
  // (now fixed: CRM limit 500→200, Users limit 200→100). Keep the catch
  // so a stale tab can't spam the buffer if redeployed mid-session.
  {
    path: /\/v1\/crm\/opportunities\/?\?[^#]*\blimit=(?:[3-9]\d{2,}|\d{4,})\b/i,
    status: 422,
  },
  {
    path: /\/v1\/users\/?\?[^#]*\blimit=(?:1[1-9]\d|[2-9]\d{2,}|\d{4,})\b/i,
    status: 422,
  },
  // 5) /v1/fx/policies/{uuid}/ 404 — a project with no currency policy is the
  // ordinary state of every project until somebody sets one, including the
  // demo project a fresh install ships with. The FX panel renders that 404 as
  // an invitation to set one, and the DELETE returns the same 404 for removing
  // a policy that is already absent, which is equally benign. Anchored on the
  // project id so the /validation/ subpath underneath it is not swallowed: that
  // endpoint answers "nothing examined" with a 200, and a real 404 there would
  // be a routing fault worth capturing.
  {
    path: /\/v1\/fx\/policies\/[0-9a-f-]+\/?(?:$|\?)/i,
    status: 404,
  },
];

/**
 * Internal: return true if the event matches any whitelist entry and
 * therefore must NOT be recorded.
 *
 * Strict matcher: an entry with both ``path`` and ``status`` requires
 * BOTH to match. An entry with only ``path`` matches any status (use
 * sparingly — prefer narrower predicates).
 */
export function shouldSuppress(args: {
  path?: string;
  status?: number;
  errorName?: string;
}): boolean {
  for (const f of RECORDING_WHITELIST) {
    if (f.path !== undefined) {
      if (args.path === undefined) continue;
      if (!f.path.test(args.path)) continue;
    }
    if (f.status !== undefined) {
      if (args.status !== f.status) continue;
    }
    if (f.errorName !== undefined) {
      if (args.errorName !== f.errorName) continue;
    }
    // A predicate must constrain at least one field to be meaningful.
    if (f.path === undefined && f.status === undefined && f.errorName === undefined) {
      continue;
    }
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Network-error noise filter
// ---------------------------------------------------------------------------

/**
 * Network/transport-level error fingerprints that should NEVER drive
 * the "Last error captured" payload of an auto-bug-report.
 *
 * These are not code defects — they happen when the backend is
 * unreachable (offline, dev server down, restart in flight, captive-
 * portal, CORS preflight refused, request aborted by navigation,
 * upstream 502/503/504 etc.).
 *
 * Triggered by GitHub issue #155: a "Failed to fetch" TypeError from a
 * SettingsPage React Query function (backend was simply not running)
 * was filed as an actionable bug.
 *
 * NOTE: Each entry must be a substring or full RegExp match against
 * either the Error.message or the `<endpoint> returned <status>`
 * `api_error` message we synthesise in ``logApiError``.
 */
const NETWORK_ERROR_PATTERNS: readonly RegExp[] = [
  // Chrome / Edge — generic offline / DNS / TLS failure
  /TypeError:\s*Failed to fetch/i,
  /^Failed to fetch$/i,
  // Firefox
  /TypeError:\s*NetworkError when attempting to fetch resource/i,
  /^NetworkError when attempting to fetch resource\.?$/i,
  // Safari
  /TypeError:\s*Load failed/i,
  /^Load failed$/i,
  // Generic / WebKit when the browser is offline
  /TypeError:\s*The Internet connection appears to be offline/i,
  // AbortController-driven (navigation, query cancellation, retry tear-down)
  /AbortError:\s*signal is aborted without reason/i,
  /AbortError:\s*The user aborted a request/i,
  /AbortError:\s*The operation was aborted/i,
  /^The operation was aborted\.?$/i,
];

/**
 * Transient backend status codes that should not block the bug-report
 * picker — these are infrastructure hiccups, not application defects.
 *
 *  - 0   : XHR/fetch resolved with `status: 0` (CORS-preflight failure,
 *          network unreachable, captive portal, DNS).
 *  - 502 : Bad Gateway (LB upstream not ready).
 *  - 503 : Service Unavailable (deploying, draining, rate-limited).
 *  - 504 : Gateway Timeout (slow upstream).
 *
 * A real defect on these endpoints will surface as 4xx/5xx after the
 * blip resolves, so the buffer still sees actionable errors when the
 * connection recovers.
 */
const TRANSIENT_HTTP_STATUSES: readonly number[] = [0, 502, 503, 504];

/** Return true if the message looks like a transport/network error. */
export function isNetworkErrorMessage(message: string | undefined | null): boolean {
  if (!message) return false;
  return NETWORK_ERROR_PATTERNS.some((re) => re.test(message));
}

// ---------------------------------------------------------------------------
// Expected-state noise filter (handled empty states that arrive as js_error)
// ---------------------------------------------------------------------------

/**
 * Message fingerprints for *expected* application states that surface as a
 * thrown Error (and therefore reach us via window.onerror /
 * unhandledrejection as a ``js_error``, bypassing the network whitelist
 * which only matches tracked ``api_error`` events by path+status).
 *
 * Triggered by GitHub issue #168: on lightweight / showcase installs a
 * model can legitimately have no 3D mesh artifact. The geometry endpoint
 * returns 404 ``geometry_missing``; ``ElementManager`` throws a
 * "Failed to fetch geometry (404): ..." Error which the viewer already
 * handles by showing the empty / converting state. Because the throw is not
 * caught as a tracked network event, it leaked into the bug-report buffer
 * and users auto-filed false reports. A missing mesh is an expected empty
 * state, not a defect.
 */
const EXPECTED_STATE_PATTERNS: readonly RegExp[] = [
  // BIM geometry 404 — model has no 3D mesh artifact (lightweight install,
  // metadata-only / showcase model, conversion not run). Matches both the
  // "(404)" and bare ": 404" headline shapes emitted by ElementManager, and
  // the backend ``geometry_missing`` marker if it surfaces in the message.
  /Failed to fetch geometry(?:\s*\(404\)|:\s*404)\b/i,
  /\bgeometry_missing\b/i,
];

/** Return true if the message represents an expected, handled empty state. */
export function isExpectedStateMessage(message: string | undefined | null): boolean {
  if (!message) return false;
  return EXPECTED_STATE_PATTERNS.some((re) => re.test(message));
}

/** Return true if the status code is a transient infrastructure blip. */
export function isTransientHttpStatus(status: number | undefined | null): boolean {
  if (status === undefined || status === null) return false;
  return TRANSIENT_HTTP_STATUSES.includes(status);
}

// ---------------------------------------------------------------------------
// Staleness filter (entries replayed out of localStorage across sessions)
// ---------------------------------------------------------------------------

/**
 * Maximum age of an entry that may still be attached to a bug report.
 *
 * The buffer is deliberately persisted (``loadFromStorage``) so a crash that
 * reloads the page does not lose the very error the user is about to report.
 * That same persistence lets an entry survive for as long as the browser
 * profile does, and the bug-report dialog has no other notion of "recent" —
 * so a week-old error from an unrelated screen gets attached to today's
 * report and reads as the reason the user filed.
 *
 * A day is wide enough to cover the honest cases (the app broke, the user
 * reloaded, filed a report over lunch or the next morning) and narrow enough
 * that an error nobody remembers hitting never leads triage.
 *
 * Triggered by GitHub issue #391: a report filed on 2026-07-25 against
 * 12.6.0 from /match-elements carried an Intl RangeError captured on
 * 2026-07-16, on an earlier build and a different page. The issue was titled
 * and triaged against the wrong surface for it.
 */
const STALE_ERROR_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * Return true when an entry is too old, or from too old a build, to be the
 * representative error of a bug report filed now.
 *
 * Two independent signals, either of which is disqualifying:
 *
 *  - ``appVersion`` differs from the running build. The entry was captured
 *    before an upgrade, so it may well describe something already fixed, and
 *    the report's own "App version" line would misattribute it.
 *  - ``timestamp`` is older than {@link STALE_ERROR_MAX_AGE_MS}, or does not
 *    parse. An unparseable timestamp is treated as stale because we cannot
 *    show the user when it happened either.
 *
 * The entry stays in the buffer and in the exported JSON report — this only
 * governs which one is promoted to the "Last error captured" payload.
 *
 * @param entry The captured entry.
 * @param now Current epoch ms; injectable so tests need no fake timers.
 */
export function isStaleForReport(entry: ErrorLogEntry, now: number = Date.now()): boolean {
  if (entry.appVersion && entry.appVersion !== APP_VERSION) return true;
  const at = Date.parse(entry.timestamp);
  if (Number.isNaN(at)) return true;
  return now - at > STALE_ERROR_MAX_AGE_MS;
}

/**
 * Return true if the entry represents a benign network/transport blip
 * that should not be used as the "Last error captured" payload of a
 * bug report. The entry is still recorded in the buffer (so the user
 * can see the full session log) but it is skipped when picking the
 * representative error.
 */
export function isNetworkBlip(entry: ErrorLogEntry): boolean {
  if (isNetworkErrorMessage(entry.message)) return true;
  // api_error entries carry the HTTP status in context.status.
  const statusStr = entry.context?.status;
  if (statusStr !== undefined) {
    const status = Number.parseInt(statusStr, 10);
    if (!Number.isNaN(status) && isTransientHttpStatus(status)) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Backend reporter circuit-breaker
// ---------------------------------------------------------------------------

/**
 * Lightweight circuit-breaker for the fire-and-forget backend POST.
 *
 * Problem (2026-06-19): the demo VPS is 1 core.  When a page throws errors
 * in a tight loop the reporter fires one fire-and-forget fetch per error.
 * With no fetch timeout each browser request holds a connection open until
 * the OS TCP stack times out (often 90 s+), exhausting the browser's
 * per-origin connection pool and causing subsequent *real* API calls to
 * queue.  A storm of 429 responses made it worse: the backend responded but
 * the client kept firing because the 429 was silently swallowed.
 *
 * Mitigations applied here:
 *  1. ``AbortSignal.timeout(4000)`` — each POST is abandoned after 4 s so
 *     connections are never held open long.
 *  2. Consecutive-failure counter: after ``_CIRCUIT_OPEN_THRESHOLD``
 *     consecutive failures (including 429) the circuit opens and no further
 *     POSTs are sent for ``_CIRCUIT_RESET_MS`` ms.  This bounds the request
 *     rate from a single broken session without silencing the first few
 *     genuine reports.
 *  3. 429 responses explicitly count as failures and open the circuit fast
 *     (the server is telling us to back off).
 */

/** Open the circuit after this many consecutive POST failures. */
const _CIRCUIT_OPEN_THRESHOLD = 3;
/** Keep the circuit open for this long (ms) before allowing one probe. */
const _CIRCUIT_RESET_MS = 60_000; // 1 minute

let _consecutiveFailures = 0;
let _circuitOpenAt = 0; // 0 = closed

// ---------------------------------------------------------------------------
// Internal state
// ---------------------------------------------------------------------------

let memoryBuffer: ErrorLogEntry[] = [];
let initialized = false;
const sessionStart = Date.now();
const pagesVisited = new Set<string>();
let errorCounter = 0;

// ---------------------------------------------------------------------------
// Anonymization
// ---------------------------------------------------------------------------

/**
 * Scrub PII and secrets from arbitrary text.
 *
 * Replaces emails, UUIDs, API keys, Bearer tokens, passwords, numeric IDs
 * longer than 6 digits, and Authorization header values.
 */
export function anonymize(text: string): string {
  if (!text) return text;
  return (
    text
      // Email addresses
      .replace(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g, '[EMAIL]')
      // UUIDs
      .replace(
        /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
        '[UUID]',
      )
      // OpenAI / Anthropic / Groq-style API keys
      .replace(
        /(sk-[a-zA-Z0-9-]{20,}|sk-ant-[a-zA-Z0-9-]+|gsk_[a-zA-Z0-9]+)/g,
        '[API_KEY]',
      )
      // Bearer tokens (Authorization: Bearer <jwt|opaque>)
      .replace(/Bearer\s+[a-zA-Z0-9._-]+/g, 'Bearer [TOKEN]')
      // Bare JWTs (header.payload.signature) NOT behind a "Bearer " prefix.
      // This is our own auth-token format, plus any access/refresh token that
      // reaches an error string on its own — the Bearer rule above misses those.
      .replace(/\beyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{2,}/g, '[JWT]')
      // JSON secret-bearing fields: password / token / secret / key / cookie /
      // session variants. Case-insensitive with optional underscores so
      // "accessToken", "access_token", "Refresh_Token" etc. all match. Covers
      // the old "password" and "api_key" rules plus the auth-token families the
      // login/refresh responses carry.
      .replace(
        /("(?:password|passwd|pwd|(?:access_?|refresh_?|id_?)?token|api_?key|secret|client_?secret|jwt|session_?id|cookie|set-cookie|authorization)"\s*:\s*")[^"]+/gi,
        '$1[REDACTED]',
      )
      // Authorization header values in text
      .replace(/(Authorization:\s*)[^\s\r\n]+/gi, '$1[REDACTED]')
      // Long numeric IDs (> 6 digits) — standalone only
      .replace(/\b\d{7,}\b/g, '[ID]')
      // User-like name patterns in common JSON fields
      .replace(/("(?:user_?name|full_?name|display_?name|first_?name|last_?name)"\s*:\s*")[^"]+/gi, '$1[USER]')
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  errorCounter += 1;
  return `err_${String(errorCounter).padStart(3, '0')}`;
}

/**
 * Public routes whose path segment IS the login (App.tsx `:token` routes).
 * Add a route here when App.tsx gains one.
 */
const TOKEN_PATH_PREFIXES: readonly string[] = ['/share/', '/buyer-portal/', '/tendering/bid/', '/field/'];

/** A path with the credential taken out, so it never reaches an error report. */
export function maskTokenPath(pathname: string): string {
  const prefix = TOKEN_PATH_PREFIXES.find((p) => pathname.startsWith(p));
  if (!prefix) return pathname;
  const rest = pathname.slice(prefix.length);
  const end = rest.search(/[/?#]/);
  if (rest === '' || end === 0) return pathname;
  return `${prefix}:token${end === -1 ? '' : rest.slice(end)}`;
}

/** Return the current page URL without query string or hash (to avoid leaking data). */
function cleanUrl(): string {
  if (typeof window === 'undefined') return '';
  return maskTokenPath(window.location.pathname);
}

function getLocale(): string {
  if (typeof navigator === 'undefined') return 'en';
  return navigator.language || 'en';
}

function getPlatform(): string {
  if (typeof navigator === 'undefined') return 'unknown';
  const ua = navigator.userAgent;

  let os = 'Unknown OS';
  if (ua.includes('Windows NT 10')) os = 'Windows 10/11';
  else if (ua.includes('Windows')) os = 'Windows';
  else if (ua.includes('Mac OS X')) os = 'macOS';
  else if (ua.includes('Linux')) os = 'Linux';
  else if (ua.includes('Android')) os = 'Android';
  else if (ua.includes('iPhone') || ua.includes('iPad')) os = 'iOS';

  let browser = 'Unknown Browser';
  if (ua.includes('Firefox/')) {
    const m = ua.match(/Firefox\/(\d+)/);
    browser = `Firefox ${m?.[1] ?? ''}`;
  } else if (ua.includes('Edg/')) {
    const m = ua.match(/Edg\/(\d+)/);
    browser = `Edge ${m?.[1] ?? ''}`;
  } else if (ua.includes('Chrome/')) {
    const m = ua.match(/Chrome\/(\d+)/);
    browser = `Chrome ${m?.[1] ?? ''}`;
  } else if (ua.includes('Safari/') && !ua.includes('Chrome')) {
    const m = ua.match(/Version\/(\d+)/);
    browser = `Safari ${m?.[1] ?? ''}`;
  }

  return `${os} / ${browser}`;
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

function saveToStorage(): void {
  try {
    const toStore = memoryBuffer.slice(-MAX_STORAGE_ENTRIES);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore));
  } catch {
    // localStorage full or unavailable — silently skip
  }
}

/**
 * Fire-and-forget POST of a single entry to the backend client-error sink.
 *
 * The backend route is unauthenticated and rate-limited at 30 req/min per
 * IP, so we send each entry exactly once at capture time.
 *
 * Disabled by setting ``VITE_ENABLE_ERROR_REPORTING=false`` at build time
 * (e.g. for air-gapped installs). Default is enabled.
 *
 * Anything that goes wrong here is intentionally swallowed — we never
 * want the error reporter itself to surface more errors.
 *
 * Circuit-breaker (2026-06-19): see ``_CIRCUIT_OPEN_THRESHOLD`` /
 * ``_CIRCUIT_RESET_MS`` above.  Each POST that fails (network error, 429,
 * 5xx, or timeout) increments ``_consecutiveFailures``.  Once the threshold
 * is exceeded the circuit opens and no further POSTs are sent until the
 * reset window expires.  A successful 202 resets the counter.
 *
 * ``AbortSignal.timeout(4000)`` caps each POST at 4 s so a slow/backlogged
 * backend never holds connections open.  ``keepalive`` is intentionally
 * omitted: keepalive + AbortSignal.timeout are incompatible in most
 * browsers, and a 4-second hard cap is more important than flush-on-unload
 * for a non-critical reporting channel.
 */
function postToBackend(entry: ErrorLogEntry): void {
  try {
    const flag =
      typeof import.meta !== 'undefined' &&
      typeof (import.meta as { env?: Record<string, string | undefined> }).env !==
        'undefined'
        ? (import.meta as { env: Record<string, string | undefined> }).env
            .VITE_ENABLE_ERROR_REPORTING
        : undefined;
    if (flag === 'false') return;
    if (typeof fetch === 'undefined') return;

    // Circuit-breaker open check.
    const now = Date.now();
    if (_circuitOpenAt > 0) {
      if (now - _circuitOpenAt < _CIRCUIT_RESET_MS) {
        // Circuit still open — drop silently.
        return;
      }
      // Reset window expired — allow one probe; circuit stays open until
      // the probe succeeds.
    }

    const stackLines = (entry.stack ?? '')
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .slice(0, 64);

    const body = JSON.stringify({
      timestamp: entry.timestamp,
      error_id: entry.id,
      message: entry.message,
      stack_lines: stackLines,
      user_agent: entry.userAgent,
      path: entry.url,
    });

    // AbortSignal.timeout is available in all modern browsers (Chrome 103+,
    // Firefox 100+, Safari 16+).  Older browsers that lack it get the
    // unguarded fetch — still correct, just without the 4-s cap.
    const signal =
      typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
        ? AbortSignal.timeout(4000)
        : undefined;

    void fetch('/api/v1/client-errors/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      credentials: 'omit',
      ...(signal !== undefined ? { signal } : {}),
    })
      .then((resp) => {
        if (resp.ok) {
          // Successful delivery — reset the failure counter.
          _consecutiveFailures = 0;
          _circuitOpenAt = 0;
        } else {
          // Server-side rejection (429, 5xx, etc.) — count as failure.
          _consecutiveFailures += 1;
          if (_consecutiveFailures >= _CIRCUIT_OPEN_THRESHOLD) {
            _circuitOpenAt = Date.now();
          }
        }
      })
      .catch(() => {
        // Network error or AbortError (timeout) — count as failure.
        _consecutiveFailures += 1;
        if (_consecutiveFailures >= _CIRCUIT_OPEN_THRESHOLD) {
          _circuitOpenAt = Date.now();
        }
      });
  } catch {
    // ignored — the error reporter must never surface errors
  }
}

function loadFromStorage(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed: ErrorLogEntry[] = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        memoryBuffer = parsed.slice(-MAX_MEMORY_ENTRIES);
        errorCounter = memoryBuffer.length;
      }
    }
  } catch {
    // Corrupt data — start fresh
    memoryBuffer = [];
  }
}

// ---------------------------------------------------------------------------
// Core logging
// ---------------------------------------------------------------------------

function addEntry(entry: ErrorLogEntry): void {
  memoryBuffer.push(entry);
  if (memoryBuffer.length > MAX_MEMORY_ENTRIES) {
    memoryBuffer = memoryBuffer.slice(-MAX_MEMORY_ENTRIES);
  }
  saveToStorage();
  postToBackend(entry);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Log an error (from catch blocks, ErrorBoundary, or manual reports).
 */
export function logError(
  error: Error | string,
  category?: ErrorCategory,
  context?: Record<string, unknown>,
): void {
  const isError = error instanceof Error;
  const message = isError ? error.message : String(error);
  const stack = isError ? error.stack : undefined;

  // Drop errors explicitly flagged as expected by the throwing code (e.g.
  // ElementManager sets ``err.expected = true`` on a geometry 404 when a
  // model has no 3D mesh — an empty state the viewer handles, not a bug),
  // or whose message matches a known expected-state marker. The throw
  // arrives here as a js_error via window.onerror/unhandledrejection, so it
  // bypasses the api_error path+status whitelist — match by flag/message.
  const flaggedExpected =
    isError && (error as Error & { expected?: boolean }).expected === true;
  if (flaggedExpected || isExpectedStateMessage(message)) {
    return;
  }

  // Drop matches against the recording whitelist (handled noise that
  // would otherwise spam the bug-report buffer).
  const errorName = isError ? error.name : undefined;
  const contextPath =
    context && typeof context === 'object' && 'url' in context
      ? String((context as Record<string, unknown>).url ?? '')
      : undefined;
  if (shouldSuppress({ path: contextPath, errorName })) {
    return;
  }

  const anonymizedContext: Record<string, string> | undefined = context
    ? Object.fromEntries(
        Object.entries(context).map(([k, v]) => [k, anonymize(String(v))]),
      )
    : undefined;

  const entry: ErrorLogEntry = {
    id: generateId(),
    timestamp: new Date().toISOString(),
    level: 'error',
    category: category ?? 'js_error',
    message: anonymize(message),
    stack: stack ? anonymize(stack) : undefined,
    url: cleanUrl(),
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
    appVersion: APP_VERSION,
    locale: getLocale(),
    context: anonymizedContext,
  };

  addEntry(entry);

  // Track page
  pagesVisited.add(cleanUrl());
}

/**
 * Log an API error (4xx / 5xx responses).
 */
export function logApiError(
  url: string,
  status: number,
  message: string,
): void {
  // Drop matches against the recording whitelist (handled 4xx/5xx noise
  // that would otherwise spam the bug-report buffer). Whitelist runs on
  // the *raw* URL because anonymisation collapses UUIDs and other tokens
  // a path regex may want to see.
  if (shouldSuppress({ path: url, status })) {
    return;
  }

  const anonymizedUrl = anonymize(url);
  const anonymizedMessage = anonymize(message);

  const entry: ErrorLogEntry = {
    id: generateId(),
    timestamp: new Date().toISOString(),
    level: status >= 500 ? 'error' : 'warning',
    category: 'api_error',
    message: `${anonymizedUrl} returned ${status}`,
    url: cleanUrl(),
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
    appVersion: APP_VERSION,
    locale: getLocale(),
    context: {
      status: String(status),
      endpoint: anonymizedUrl,
      response: anonymizedMessage,
    },
  };

  addEntry(entry);
  pagesVisited.add(cleanUrl());
}

/**
 * Return a copy of all error log entries in memory.
 */
export function getErrorLog(): ErrorLogEntry[] {
  return [...memoryBuffer];
}

/**
 * Return the number of logged errors.
 */
export function getErrorCount(): number {
  return memoryBuffer.length;
}

/**
 * Return the most recent *meaningful* captured error for bug reports.
 *
 * Entries that are stale (see ``isStaleForReport``: captured by an older
 * build, or more than a day ago) are excluded from every pass, so a quiet
 * session yields ``null`` rather than resurrecting week-old noise from
 * localStorage and presenting it as the reason for the report. The dialog
 * already renders "no error captured during this session" for ``null``.
 *
 * Selection rules, in order:
 *   1) prefer the most recent level=error entry that is NOT a network blip
 *      (Failed to fetch / AbortError / 502/503/504 etc — see
 *      ``isNetworkBlip``). Real frontend exceptions (ReferenceError,
 *      undefined-property TypeError, JSON parse failures, runtime panics)
 *      still bubble up — only transport noise is skipped.
 *   2) fall back to the most recent level=error entry (even if it is a
 *      network blip) so users with backend-down sessions still see
 *      something representative.
 *   3) fall back to the most recent entry of any level (preserves prior
 *      behaviour for warning-only sessions; cf. GitHub issue #115).
 *
 * Background: GitHub issues #115 and #155. #115 filtered handled 404s.
 * #155 filed a "Failed to fetch" TypeError from React Query while the
 * backend was simply not running — a network blip, not a code defect.
 *
 * Lookup window: scans the most recent 32 entries.
 *
 * The returned ``url`` is the page the error was captured on, which is not
 * necessarily the page the user is filing from. The report template names
 * the current route, and triage reads the title as the affected surface, so
 * the two have to be shown side by side or an error from another screen gets
 * triaged against the wrong one (#391).
 *
 * The stack is capped at ~2KB so the returned payload stays URL-safe even
 * when concatenated into a GitHub issue body.
 */
export function getLastError(): {
  message: string;
  stack: string;
  at: string;
  url: string;
} | null {
  if (memoryBuffer.length === 0) return null;
  const window = memoryBuffer.slice(-32).filter((e) => e && !isStaleForReport(e));
  if (window.length === 0) return null;
  // Pass 1: the most recent meaningful (non-blip) error.
  let pick: ErrorLogEntry | undefined;
  for (let i = window.length - 1; i >= 0; i--) {
    const e = window[i];
    if (e && e.level === 'error' && !isNetworkBlip(e)) {
      pick = e;
      break;
    }
  }
  // Pass 2: the most recent error of any kind (lets sessions whose only
  // failures are network blips still produce a non-null payload — the UI
  // layer warns the user with ``isLastErrorNetworkOnly()``).
  if (!pick) {
    for (let i = window.length - 1; i >= 0; i--) {
      const e = window[i];
      if (e && e.level === 'error') {
        pick = e;
        break;
      }
    }
  }
  // Pass 3: any most-recent non-stale entry (preserves the warning-only
  // contract from #115 without reaching back past the staleness bound).
  if (!pick) pick = window[window.length - 1];
  if (!pick) return null;
  const stack = pick.stack ?? '';
  const cappedStack = stack.length > 2048 ? stack.slice(0, 2048) + '\n... [truncated]' : stack;
  return {
    message: pick.message,
    stack: cappedStack,
    at: pick.timestamp,
    url: pick.url,
  };
}

/**
 * Return ``true`` when every level=error entry in the recent window is a
 * network blip (or no errors exist at all). This is the signal the
 * bug-report dialog uses to show a "looks like a network issue, not a
 * bug" banner before letting the user file anyway.
 *
 * Mirrors ``getLastError`` window (32) and its staleness bound so the two
 * stay in sync: an entry that can never become the report payload must not
 * drive the banner shown above it either.
 */
export function isLastErrorNetworkOnly(): boolean {
  if (memoryBuffer.length === 0) return false;
  const window = memoryBuffer.slice(-32).filter((e) => e && !isStaleForReport(e));
  let sawError = false;
  for (let i = window.length - 1; i >= 0; i--) {
    const e = window[i];
    if (!e || e.level !== 'error') continue;
    sawError = true;
    if (!isNetworkBlip(e)) return false;
  }
  return sawError;
}

/**
 * Build and return a JSON Blob containing the full error report, ready for download.
 */
export function exportErrorReport(): Blob {
  const report: ErrorReport = {
    generated_at: new Date().toISOString(),
    app_version: APP_VERSION,
    platform: getPlatform(),
    locale: getLocale(),
    total_errors: memoryBuffer.length,
    session_duration_minutes: Math.round((Date.now() - sessionStart) / 60_000),
    pages_visited: Array.from(pagesVisited),
    entries: memoryBuffer.map((e) => ({ ...e })),
  };

  return new Blob([JSON.stringify(report, null, 2)], {
    type: 'application/json',
  });
}

/**
 * Clear all in-memory and persisted error entries.
 */
export function clearErrorLog(): void {
  memoryBuffer = [];
  errorCounter = 0;
  pagesVisited.clear();
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

/**
 * Initialize global error handlers. Call once at app startup (e.g. in App.tsx).
 *
 * Sets up:
 * - window.onerror (unhandled JS errors)
 * - window.onunhandledrejection (unhandled promise rejections)
 * - page navigation tracking
 */
export function initErrorLogger(): void {
  if (initialized) return;
  initialized = true;

  // Load any previously persisted entries
  loadFromStorage();

  // Track current page
  pagesVisited.add(cleanUrl());

  // --- Global JS error handler ---
  const prevOnError = window.onerror;
  window.onerror = (
    messageOrEvent: string | Event,
    source?: string,
    lineno?: number,
    colno?: number,
    error?: Error,
  ) => {
    const msg =
      error?.message ??
      (typeof messageOrEvent === 'string' ? messageOrEvent : 'Unknown error');

    logError(error ?? msg, 'js_error', {
      source: source ?? '',
      line: String(lineno ?? ''),
      col: String(colno ?? ''),
    });

    // Call previous handler if any
    if (typeof prevOnError === 'function') {
      (prevOnError as (
        message: string | Event,
        source?: string,
        lineno?: number,
        colno?: number,
        error?: Error,
      ) => void)(messageOrEvent, source, lineno, colno, error);
    }
  };

  // --- Unhandled promise rejection handler ---
  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    const msg =
      reason instanceof Error
        ? reason.message
        : typeof reason === 'string'
          ? reason
          : 'Unhandled promise rejection';

    logError(reason instanceof Error ? reason : msg, 'js_error', {
      type: 'unhandled_rejection',
    });
  });

  // --- Track page navigations (for pages_visited in report) ---
  // Listen to popstate for SPA navigation tracking
  window.addEventListener('popstate', () => {
    pagesVisited.add(cleanUrl());
  });

  // Patch pushState / replaceState so we capture programmatic navigations
  const originalPushState = history.pushState.bind(history);
  history.pushState = (...args: Parameters<typeof history.pushState>) => {
    originalPushState(...args);
    pagesVisited.add(cleanUrl());
  };

  const originalReplaceState = history.replaceState.bind(history);
  history.replaceState = (...args: Parameters<typeof history.replaceState>) => {
    originalReplaceState(...args);
    pagesVisited.add(cleanUrl());
  };
}
