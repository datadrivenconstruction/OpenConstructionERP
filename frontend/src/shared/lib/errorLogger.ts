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
      // Bearer tokens
      .replace(/Bearer\s+[a-zA-Z0-9._-]+/g, 'Bearer [TOKEN]')
      // JSON "password" fields
      .replace(/("password"\s*:\s*")[^"]+/g, '$1[REDACTED]')
      // JSON "api_key" fields
      .replace(/("api_key"\s*:\s*")[^"]+/g, '$1[REDACTED]')
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

/** Return the current page URL without query string or hash (to avoid leaking data). */
function cleanUrl(): string {
  if (typeof window === 'undefined') return '';
  return window.location.pathname;
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
