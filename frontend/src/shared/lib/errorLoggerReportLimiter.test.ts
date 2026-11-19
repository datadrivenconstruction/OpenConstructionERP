// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How often the error reporter is allowed to speak to the backend.
 *
 * The reporter already had a circuit breaker, and the circuit breaker already had
 * a comment explaining the defect it was for: a page throwing in a tight loop on a
 * one-core server, one fire-and-forget POST per error. What it bounded was a loop
 * whose reports were FAILING. A loop whose reports were succeeding was unbounded -
 * every 200 reset the failure counter, so the reporter kept one POST per error for
 * as long as the loop ran. An owner counting the requests a single load of the
 * sign-in page made found `client-errors/` among the endpoints asked over and over.
 *
 * These cases are about the three things that now bound it: a sliding allowance per
 * minute, one report per distinct error, and silence for a failure to reach the
 * server on the two pages where that failure is the ordinary state of a first boot.
 * The last of those is the one that matters most to a new install, because the
 * sign-in page is exactly where a person is standing while the backend is busiest.
 *
 * Every case counts POSTs rather than reading the buffer: an entry that is recorded
 * locally and not sent is the intended behaviour, and asserting on the buffer would
 * not be able to tell the two apart.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { logError, logApiError, resetBackendReportLimiter } from './errorLogger';

const REPORT_ENDPOINT = '/api/v1/client-errors/';

let posts: string[] = [];

/** How many reports reached the endpoint, of however many fetches happened. */
function reports(): number {
  return posts.filter((url) => url.includes(REPORT_ENDPOINT)).length;
}

/** Move the reader to a path, which is what the auth-page rule reads. */
function at(path: string): void {
  window.history.pushState({}, '', path);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-23T10:00:00Z').getTime());
  resetBackendReportLimiter();
  posts = [];
  at('/dashboard');
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      posts.push(String(input));
      // Answering 200 is the point: the circuit breaker cannot see this case.
      return Promise.resolve({ ok: true, status: 200 });
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  at('/');
});

describe('the backend error reporter', () => {
  it('reports at most five a minute while every report succeeds', () => {
    for (let i = 0; i < 8; i += 1) {
      logError(new Error(`a distinct defect number ${i}`), 'js_error');
    }

    expect(reports()).toBe(5);

    // The window slides rather than resets: a minute after the FIRST report, the
    // allowance is available again, and one more is let through.
    vi.advanceTimersByTime(60_001);
    logError(new Error('a defect a minute later'), 'js_error');
    expect(reports()).toBe(6);
  });

  it('reports one identical error once, and a different one beside it', () => {
    logError(new Error('cannot read the plan'), 'js_error');
    logError(new Error('cannot read the plan'), 'js_error');
    logError(new Error('cannot read the plan'), 'js_error');
    expect(reports()).toBe(1);

    logError(new Error('cannot read the estimate'), 'js_error');
    expect(reports()).toBe(2);
  });

  it('tells one endpoint failing apart from another, at the same status', () => {
    // The signature carries the endpoint and the status, so two API errors that
    // differ only in where they happened are two facts and not one.
    logApiError('/api/v1/projects/', 500, 'boom');
    logApiError('/api/v1/boq/', 500, 'boom');

    expect(reports()).toBe(2);
  });

  it('says nothing about a failure to reach the server from the sign-in page', () => {
    at('/login');
    logError(new TypeError('Failed to fetch'), 'js_error');
    expect(reports(), 'a boot in progress was reported as a defect').toBe(0);

    // And the same failure on any other page is still reported: the rule is about
    // where the reader is standing, not about the message.
    at('/dashboard');
    logError(new TypeError('Failed to fetch'), 'js_error');
    expect(reports()).toBe(1);
  });

  it('says nothing about a transient status from the sign-up page either', () => {
    at('/register');
    // 503 is what the API answers while it is still starting, and `isNetworkBlip`
    // already classified it as transient before this rule existed.
    logApiError('/api/v1/users/auth/register/', 503, 'Service Unavailable');
    expect(reports()).toBe(0);
  });

  it('still reports a real defect from the sign-in page', () => {
    at('/login');
    // Not a network blip: a fault in the page, on the page where a person is most
    // likely to meet it during a first boot. Silencing this would be the change
    // that hides the defect the report channel exists for.
    logError(new Error('cannot read properties of undefined'), 'js_error');

    expect(reports()).toBe(1);
  });

  it('does not let a dropped report spend the allowance', () => {
    at('/login');
    for (let i = 0; i < 10; i += 1) logError(new TypeError('Failed to fetch'), 'js_error');
    expect(reports()).toBe(0);

    at('/dashboard');
    for (let i = 0; i < 8; i += 1) logError(new Error(`a distinct defect number ${i}`), 'js_error');
    // All five of the allowance is still here: the ten dropped above were dropped
    // before the counters were touched, so they bought no silence for these.
    expect(reports()).toBe(5);
  });
});
