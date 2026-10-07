// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// errorLogger contract tests — focused on the bug-report flow.
//
// Background: GitHub issue #115 was filed because a benign 404 from
// the BIM auto-detect path got captured as the "last error" by the
// in-app bug-report dialog. The page handled the 404 gracefully via
// toast, but the warning entry still leaked into the report template.
//
// `getLastError()` now prefers the most recent level=error entry over
// warning-level noise. These tests lock that contract in.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import {
  getLastError,
  logApiError,
  logError,
  clearErrorLog,
  getErrorLog,
  shouldSuppress,
  isLastErrorNetworkOnly,
  isNetworkErrorMessage,
  isStaleForReport,
  isTransientHttpStatus,
  anonymize,
  type ErrorLogEntry,
} from './errorLogger';
import { APP_VERSION } from './version';

describe('errorLogger.getLastError - bug-report payload selection', () => {
  beforeEach(() => {
    clearErrorLog();
  });

  it('returns null when nothing has been logged', () => {
    expect(getLastError()).toBeNull();
  });

  it('returns the most recent entry when only warnings exist', () => {
    logApiError('/v1/foo/', 404, 'not found');
    logApiError('/v1/bar/', 404, 'not found');
    const last = getLastError();
    expect(last).not.toBeNull();
    expect(last!.message).toContain('/v1/bar/');
  });

  it('prefers a level=error entry over a more recent warning', () => {
    // 500 → level=error
    logApiError('/v1/important/', 500, 'oops');
    // 404 → level=warning, but the 500 was the real problem
    logApiError('/v1/bim_hub/abc-123/', 404, 'not found');
    const last = getLastError();
    expect(last!.message).toContain('/v1/important/');
    expect(last!.message).not.toContain('/v1/bim_hub/');
  });

  it('falls back to most recent warning when no error exists in the window', () => {
    logApiError('/v1/some/', 404, 'not found');
    const last = getLastError();
    expect(last!.message).toContain('/v1/some/');
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Recording whitelist — observability noise filters
//
// Source defect: user error log openconstructionerp-log-2026-05-22.json
// captured 50 of 64 errors as the same handled /profile 404 plus a
// handful of converter-install AbortErrors. None of those are
// actionable — they spam the bug-report buffer and bury the real
// errors. The whitelist drops them at recording time.

describe('errorLogger recording whitelist', () => {
  beforeEach(() => {
    clearErrorLog();
  });

  it('drops /v1/projects/{uuid}/profile 404 (handled by backend retrofit)', () => {
    logApiError(
      '/v1/projects/0e92b341-7af3-4d4c-bd2c-a6f7a8f01234/profile',
      404,
      'no setup profile yet',
    );
    expect(getErrorLog()).toHaveLength(0);
    expect(getLastError()).toBeNull();
  });

  it('drops /v1/bim_hub/* 404 (user navigated to a deleted model)', () => {
    logApiError(
      '/v1/bim_hub/models/0e92b341-7af3-4d4c-bd2c-a6f7a8f01234/elements',
      404,
      'model not found',
    );
    expect(getErrorLog()).toHaveLength(0);
  });

  it('drops AbortError from POST /v1/takeoff/converters/{id}/install', () => {
    const e = new Error('aborted');
    e.name = 'AbortError';
    logError(e, 'api_error', {
      url: '/v1/takeoff/converters/rvt/install/',
    });
    expect(getErrorLog()).toHaveLength(0);
  });

  it('drops 422 on /v1/crm/opportunities with the stale oversized limit', () => {
    logApiError(
      '/v1/crm/opportunities/?limit=500',
      422,
      'Input should be less than or equal to 200',
    );
    expect(getErrorLog()).toHaveLength(0);
  });

  it('drops 422 on /v1/users with the stale oversized limit', () => {
    logApiError(
      '/v1/users/?limit=200',
      422,
      'Input should be less than or equal to 100',
    );
    expect(getErrorLog()).toHaveLength(0);
  });

  it('drops /v1/fx/policies/{uuid}/ 404 (project has no currency policy yet)', () => {
    logApiError(
      '/v1/fx/policies/f1a95000-0001-4a00-8b00-000000000001/',
      404,
      'No FX policy is configured for project f1a95000-0001-4a00-8b00-000000000001',
    );
    expect(getErrorLog()).toHaveLength(0);
  });

  it('does NOT suppress a 404 on the FX policy validation subpath', () => {
    // /validation/ answers with a 200 and an empty report when there is no
    // policy, so a 404 there is a routing fault and must be recorded.
    logApiError(
      '/v1/fx/policies/f1a95000-0001-4a00-8b00-000000000001/validation/',
      404,
      'Not Found',
    );
    expect(getErrorLog().length).toBeGreaterThanOrEqual(1);
  });

  it('does NOT suppress a 500 on /v1/fx/policies/{uuid}/ (real failure)', () => {
    logApiError('/v1/fx/policies/f1a95000-0001-4a00-8b00-000000000001/', 500, 'oops');
    expect(getErrorLog().length).toBeGreaterThanOrEqual(1);
  });

  it('does NOT suppress unrelated 404s on the same modules', () => {
    // A genuine 404 on /v1/projects/{id}/boqs/ is unrelated to the
    // profile-retrofit issue — must still be recorded.
    logApiError(
      '/v1/projects/0e92b341-7af3-4d4c-bd2c-a6f7a8f01234/boqs/',
      404,
      'boq not found',
    );
    expect(getErrorLog().length).toBeGreaterThanOrEqual(1);
  });

  it('does NOT suppress 500 on /v1/projects/{id}/profile (real failure)', () => {
    // A 500 on the profile endpoint is a real bug — must surface.
    logApiError(
      '/v1/projects/0e92b341-7af3-4d4c-bd2c-a6f7a8f01234/profile',
      500,
      'oops',
    );
    expect(getErrorLog().length).toBeGreaterThanOrEqual(1);
  });

  it('shouldSuppress predicate handles each whitelist field independently', () => {
    // Path-only whitelist hit (any status counts → bim_hub 404).
    expect(shouldSuppress({ path: '/v1/bim_hub/x', status: 404 })).toBe(true);
    // Path matches but status doesn't (we whitelisted only 404 → 500
    // must still pass through).
    expect(
      shouldSuppress({
        path: '/v1/projects/00000000-0000-0000-0000-000000000000/profile',
        status: 500,
      }),
    ).toBe(false);
    // errorName predicate requires the right name.
    expect(
      shouldSuppress({
        path: '/v1/takeoff/converters/rvt/install/',
        errorName: 'AbortError',
      }),
    ).toBe(true);
    expect(
      shouldSuppress({
        path: '/v1/takeoff/converters/rvt/install/',
        errorName: 'TypeError',
      }),
    ).toBe(false);
    // Empty input never matches.
    expect(shouldSuppress({})).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Expected missing claim invoice — the lookup documents this one 404 as empty.
describe('expected missing claim invoice reporting', () => {
  const claimId = 'f1a95000-0001-4a00-8b00-000000000001';
  const endpoint = `/v1/finance/claims/${claimId}/receivable-invoice/`;
  const detail = 'No receivable invoice exists for this claim';
  const fetchSpy = vi.fn<typeof fetch>();
  let reporter: typeof import('./errorLogger');

  beforeAll(async () => {
    // The earlier buffer tests can open their module's transport circuit
    // through the generic fetch mock. Give these transport assertions a
    // fresh reporter instead of changing the production circuit breaker.
    vi.resetModules();
    reporter = await import('./errorLogger');
  });

  beforeEach(() => {
    reporter.clearErrorLog();
    vi.stubEnv('VITE_ENABLE_ERROR_REPORTING', 'true');
    fetchSpy.mockReset().mockResolvedValue(new Response('{}', { status: 202 }));
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it.each([
    endpoint,
    endpoint.slice(0, -1),
    `/api${endpoint}`,
    `${endpoint}?lookup=1`,
    endpoint.replace(claimId, claimId.toUpperCase()),
  ])('does not record or send the documented absence at %s', async (path) => {
    reporter.logApiError(path, 404, JSON.stringify({ detail }));
    expect(reporter.getErrorLog()).toHaveLength(0);
    expect(reporter.getLastError()).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    await Promise.resolve();
  });

  it.each([
    ['permission refusal', endpoint, 403, JSON.stringify({ detail })],
    ['server failure', endpoint, 500, JSON.stringify({ detail })],
    ['generic routing miss', endpoint, 404, JSON.stringify({ detail: 'Not Found' })],
    ['different detail', endpoint, 404, JSON.stringify({ detail: 'Invoice lookup failed' })],
    ['missing detail', endpoint, 404, '{}'],
    ['malformed body', endpoint, 404, '{'],
    ['plain text', endpoint, 404, detail],
    ['array body', endpoint, 404, JSON.stringify([{ detail }])],
    ['null body', endpoint, 404, 'null'],
    ['other endpoint', `/v1/finance/claims/${claimId}/`, 404, JSON.stringify({ detail })],
    ['child route', `${endpoint}details/`, 404, JSON.stringify({ detail })],
    ['invalid UUID', endpoint.replace(claimId, 'not-a-uuid'), 404, JSON.stringify({ detail })],
    ['duplicate API prefix', `/api/api${endpoint}`, 404, JSON.stringify({ detail })],
  ] as const)('keeps %s observable', async (_case, path, status, message) => {
    reporter.logApiError(path, status, message);
    expect(reporter.getErrorLog()).toHaveLength(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/client-errors/', expect.objectContaining({ method: 'POST' }),
    );
    await Promise.resolve();
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Network-blip filter — GitHub issue #155
//
// User Mourdi59 filed "Failed to fetch" TypeError from a SettingsPage
// React Query function while the backend was simply not running. That's
// not a code defect — getLastError() must skip transport-level blips
// (Failed to fetch / NetworkError / Load failed / AbortError / 0 /
// 502 / 503 / 504) when picking the representative error for the
// auto-bug-report payload.

describe('errorLogger network-blip filter (#155)', () => {
  beforeEach(() => {
    clearErrorLog();
  });

  it('isNetworkErrorMessage matches all browser dialects', () => {
    // Chrome / Edge
    expect(isNetworkErrorMessage('TypeError: Failed to fetch')).toBe(true);
    expect(isNetworkErrorMessage('Failed to fetch')).toBe(true);
    // Firefox
    expect(
      isNetworkErrorMessage(
        'TypeError: NetworkError when attempting to fetch resource.',
      ),
    ).toBe(true);
    // Safari
    expect(isNetworkErrorMessage('TypeError: Load failed')).toBe(true);
    expect(isNetworkErrorMessage('Load failed')).toBe(true);
    // AbortController
    expect(
      isNetworkErrorMessage('AbortError: signal is aborted without reason'),
    ).toBe(true);
    expect(
      isNetworkErrorMessage('AbortError: The user aborted a request'),
    ).toBe(true);
    expect(isNetworkErrorMessage('The operation was aborted.')).toBe(true);
    // Real defects must NOT match
    expect(
      isNetworkErrorMessage("TypeError: Cannot read properties of undefined (reading 'id')"),
    ).toBe(false);
    expect(isNetworkErrorMessage('ReferenceError: foo is not defined')).toBe(false);
    expect(isNetworkErrorMessage('SyntaxError: Unexpected token < in JSON at position 0')).toBe(false);
    expect(isNetworkErrorMessage(null)).toBe(false);
    expect(isNetworkErrorMessage('')).toBe(false);
  });

  it('isTransientHttpStatus flags only the documented codes', () => {
    expect(isTransientHttpStatus(0)).toBe(true);
    expect(isTransientHttpStatus(502)).toBe(true);
    expect(isTransientHttpStatus(503)).toBe(true);
    expect(isTransientHttpStatus(504)).toBe(true);
    // Real failures — NOT transient
    expect(isTransientHttpStatus(400)).toBe(false);
    expect(isTransientHttpStatus(401)).toBe(false);
    expect(isTransientHttpStatus(404)).toBe(false);
    expect(isTransientHttpStatus(422)).toBe(false);
    expect(isTransientHttpStatus(500)).toBe(false);
    expect(isTransientHttpStatus(undefined)).toBe(false);
    expect(isTransientHttpStatus(null)).toBe(false);
  });

  it('getLastError skips a "Failed to fetch" blip in favour of a real error', () => {
    // Real defect captured first (e.g. undefined-property read in a
    // BOQ row renderer).
    logError(
      new TypeError("Cannot read properties of undefined (reading 'rows')"),
    );
    // Backend then went down — multiple Failed to fetch errors filed
    // after the real one. The picker must STILL surface the real bug.
    logError(new TypeError('Failed to fetch'), 'network');
    logError(new TypeError('Failed to fetch'), 'network');
    logError(new TypeError('Failed to fetch'), 'network');

    const last = getLastError();
    expect(last).not.toBeNull();
    expect(last!.message).toContain('Cannot read properties of undefined');
    expect(last!.message).not.toContain('Failed to fetch');
  });

  it('getLastError skips a transient 503 in favour of a real 500', () => {
    logApiError('/v1/projects/abc/boqs/', 500, 'internal error');
    logApiError('/v1/projects/abc/boqs/', 503, 'service unavailable');
    logApiError('/v1/projects/abc/boqs/', 503, 'service unavailable');
    const last = getLastError();
    expect(last).not.toBeNull();
    expect(last!.message).toContain('returned 500');
  });

  it('getLastError falls back to a network blip when nothing else is available', () => {
    // Backend-down session — nothing but Failed to fetch. The picker
    // returns the blip (so the report has *something* to show) but the
    // UI calls isLastErrorNetworkOnly() to decide whether to warn.
    logError(new TypeError('Failed to fetch'), 'network');
    const last = getLastError();
    expect(last).not.toBeNull();
    expect(last!.message).toContain('Failed to fetch');
  });

  it('isLastErrorNetworkOnly is false when no errors exist', () => {
    expect(isLastErrorNetworkOnly()).toBe(false);
  });

  it('isLastErrorNetworkOnly is true when all level=error are network blips', () => {
    logError(new TypeError('Failed to fetch'), 'network');
    logApiError('/v1/foo/', 503, 'unavailable');
    expect(isLastErrorNetworkOnly()).toBe(true);
  });

  it('isLastErrorNetworkOnly is false when a real exception is mixed in', () => {
    logError(new ReferenceError('foo is not defined'));
    logError(new TypeError('Failed to fetch'), 'network');
    expect(isLastErrorNetworkOnly()).toBe(false);
  });

  it('isLastErrorNetworkOnly ignores warning-level entries', () => {
    // Warnings (handled 4xx) should not flip the predicate.
    logApiError('/v1/projects/abc/boqs/', 404, 'not found');
    expect(isLastErrorNetworkOnly()).toBe(false);
    // Now add a network blip → all *error*-level entries are blips → true.
    logError(new TypeError('Failed to fetch'), 'network');
    expect(isLastErrorNetworkOnly()).toBe(true);
  });

  it('preserves the user-override escape hatch by still recording blips', () => {
    // The entries themselves must still hit the buffer — the user can
    // still file the report after clicking "Report anyway", and the
    // downloaded JSON log should contain the blips so support can
    // diagnose connectivity issues. We only filter the *picker*.
    logError(new TypeError('Failed to fetch'), 'network');
    logError(new TypeError('Failed to fetch'), 'network');
    expect(getErrorLog().length).toBeGreaterThanOrEqual(2);
  });
});

describe('errorLogger.anonymize - secret scrubbing before persistence', () => {
  // Everything the buffer persists to localStorage (and everything
  // exportErrorReport() hands to the user) runs through anonymize().
  // These lock in that no auth material survives the scrub — the app's
  // own JWT is the primary thing we must never leak into a bug report.

  const SAMPLE_JWT =
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
    'eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.' +
    'SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';

  it('redacts a bare JWT that is not behind a Bearer prefix', () => {
    const out = anonymize(`token expired: ${SAMPLE_JWT} please re-login`);
    expect(out).not.toContain(SAMPLE_JWT);
    expect(out).not.toContain('eyJhbGci');
    expect(out).toContain('[JWT]');
  });

  it('redacts a JWT carried in an Authorization: Bearer header', () => {
    const out = anonymize(`Authorization: Bearer ${SAMPLE_JWT}`);
    expect(out).not.toContain(SAMPLE_JWT);
    expect(out).not.toContain('eyJhbGci');
    // The Bearer, JWT and Authorization-header rules all target this; any
    // one of them leaves a redaction marker and none leave the payload.
    expect(out).toMatch(/\[REDACTED\]|\[TOKEN\]|\[JWT\]/);
  });

  it('redacts token-family JSON fields regardless of case or underscores', () => {
    const payload = JSON.stringify({
      access_token: 'ory_at_abc123secretvalue',
      refreshToken: 'ory_rt_zzz999secretvalue',
      Client_Secret: 'cs_live_topsecret',
      id_token: SAMPLE_JWT,
    });
    const out = anonymize(payload);
    expect(out).not.toContain('ory_at_abc123secretvalue');
    expect(out).not.toContain('ory_rt_zzz999secretvalue');
    expect(out).not.toContain('cs_live_topsecret');
    expect(out).toContain('[REDACTED]');
  });

  it('still redacts the legacy password and api_key JSON fields', () => {
    const out = anonymize(
      '{"password":"hunter2","api_key":"kbc_9f8e7d6c5b4a"}',
    );
    expect(out).not.toContain('hunter2');
    expect(out).not.toContain('kbc_9f8e7d6c5b4a');
    expect(out).toContain('[REDACTED]');
  });

  it('redacts session and cookie JSON fields', () => {
    const out = anonymize('{"session_id":"sess_abc123","cookie":"sid=deadbeef"}');
    expect(out).not.toContain('sess_abc123');
    expect(out).not.toContain('sid=deadbeef');
    expect(out).toContain('[REDACTED]');
  });

  it('keeps scrubbing the identifiers it already handled', () => {
    const out = anonymize(
      'user a@b.com id 0e92b341-1111-2222-3333-444455556666 key sk-ant-abcdefghijklmnop',
    );
    expect(out).toContain('[EMAIL]');
    expect(out).toContain('[UUID]');
    expect(out).toContain('[API_KEY]');
  });

  it('does not mangle an ordinary error message', () => {
    const msg = 'Failed to load project BOQ: section 03.20 has no unit rate';
    expect(anonymize(msg)).toBe(msg);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Staleness filter (#391)
//
// The buffer is persisted to localStorage and replayed on the next boot,
// which is what lets a crash-and-reload still report the crash. Nothing
// bounded how far back that replay could reach, so issue #391 was filed on
// 2026-07-25 against 12.6.0 from /match-elements carrying an Intl
// RangeError captured on 2026-07-16, on an earlier build and a different
// screen. The report was titled after the wrong surface and triaged there.
//
// getLastError() now skips entries from an older build or older than a day,
// and returns null rather than promoting one.
// ─────────────────────────────────────────────────────────────────────────

describe('errorLogger staleness filter (#391)', () => {
  const DAY_MS = 24 * 60 * 60 * 1000;

  /** Build an entry directly so age and build can be set independently. */
  const entry = (over: Partial<ErrorLogEntry> = {}): ErrorLogEntry => ({
    id: 'err_001',
    timestamp: new Date().toISOString(),
    level: 'error',
    category: 'js_error',
    message: 'Computed minimumFractionDigits is larger than maximumFractionDigits',
    url: '/dashboard',
    userAgent: 'test',
    appVersion: APP_VERSION,
    locale: 'en',
    ...over,
  });

  beforeEach(() => {
    clearErrorLog();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearErrorLog();
  });

  it('keeps an entry from this build captured just now', () => {
    expect(isStaleForReport(entry())).toBe(false);
  });

  it('keeps an entry from earlier today, so crash-then-reload still reports', () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    expect(isStaleForReport(entry({ timestamp: twoHoursAgo }))).toBe(false);
  });

  it('drops an entry older than a day', () => {
    const nineDaysAgo = new Date(Date.now() - 9 * DAY_MS).toISOString();
    expect(isStaleForReport(entry({ timestamp: nineDaysAgo }))).toBe(true);
  });

  it('drops a fresh entry captured by a different build', () => {
    expect(isStaleForReport(entry({ appVersion: '12.5.0' }))).toBe(true);
  });

  it('drops an entry whose timestamp does not parse', () => {
    expect(isStaleForReport(entry({ timestamp: 'not a date' }))).toBe(true);
  });

  it('judges age against the injected clock, not the wall clock', () => {
    const at = new Date('2026-07-16T01:00:55.859Z').toISOString();
    const e = entry({ timestamp: at });
    expect(isStaleForReport(e, Date.parse('2026-07-16T03:00:00Z'))).toBe(false);
    expect(isStaleForReport(e, Date.parse('2026-07-25T00:08:25Z'))).toBe(true);
  });

  it('getLastError returns null when the only error is nine days old', () => {
    // Capture the way a real session would, then come back nine days later
    // and open the bug-report dialog. This is issue #391 end to end.
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T01:00:55.859Z'));
    logError(
      new RangeError('Computed minimumFractionDigits is larger than maximumFractionDigits'),
      'js_error',
    );
    expect(getLastError()).not.toBeNull();

    vi.setSystemTime(new Date('2026-07-25T00:08:25.000Z'));
    expect(getLastError()).toBeNull();
    // The entry is only hidden from the picker, never dropped from the log
    // the user can still download and attach.
    expect(getErrorLog().length).toBe(1);
  });

  it('carries the page the error happened on, not just the message', () => {
    // The report template names the current route and titles the issue after
    // it. An error from another screen has to arrive with its own page
    // attached or triage reads the stack as belonging to the named surface,
    // which is how #391 ended up titled after CAD-BIM Match to Cost.
    logError(new RangeError('boom'), 'js_error');
    const last = getLastError();
    expect(last).not.toBeNull();
    expect(last!.url).toBe(window.location.pathname);
  });

  it('getLastError still prefers a fresh error over a stale one', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T01:00:55.859Z'));
    logApiError('/v1/stale/', 500, 'old news');

    vi.setSystemTime(new Date('2026-07-25T00:08:25.000Z'));
    logApiError('/v1/fresh/', 500, 'happening now');

    const last = getLastError();
    expect(last).not.toBeNull();
    expect(last!.message).toContain('/v1/fresh/');
    expect(last!.message).not.toContain('/v1/stale/');
  });

  it('isLastErrorNetworkOnly ignores stale entries so the banner matches the payload', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T01:00:55.859Z'));
    logError(new TypeError('Failed to fetch'), 'network');

    vi.setSystemTime(new Date('2026-07-25T00:08:25.000Z'));
    // Nothing recent at all: no payload, so no "looks like a network issue"
    // banner either.
    expect(getLastError()).toBeNull();
    expect(isLastErrorNetworkOnly()).toBe(false);
  });
});
