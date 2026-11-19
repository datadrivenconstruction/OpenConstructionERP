// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How often the sign-in page asks a server that has not finished starting.
 *
 * An owner installing this product watched one load of `/login` on a clean data
 * folder and counted 585 requests, 6.4 MB and about 140 seconds, with `health`
 * among the endpoints asked over and over. The page's probe was the part that
 * never stopped: it asked every three seconds and kept asking, whether or not
 * anybody was still watching, and it had nothing to show for the wait - a reader
 * could not tell a page that was polling from a page that had hung.
 *
 * `backend/app/main.py` measures the thing being waited for: a cold boot reaches
 * an open port in about 143 seconds, and the longest single phase in it is the
 * route table at 32 seconds on a quiet machine and 59 under load. So the schedule
 * has to span that, and it does not have to ask forty times to cover it.
 *
 * These cases read the schedule the page publishes and then run the page against
 * it, because the claim is about behaviour and not about a constant: that the
 * waits double and then cap, that the last wait is followed by a state on the
 * screen rather than by silence, and that the state carries a control which
 * starts the schedule again.
 *
 * `t` echoes its key, as in the neighbouring test, so an assertion names the
 * branch that ran instead of a sentence a locale change could move.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/app/i18n', () => ({
  SUPPORTED_LANGUAGES: [{ code: 'en', name: 'English', flag: 'gb', country: 'gb' }],
}));

vi.mock('../AuthBackground', () => ({
  AuthBackground: () => null,
}));

import { LoginPage, HEALTH_PROBE_DELAYS_MS } from '../LoginPage';

/** Every URL this page asked for, in order. */
let asked: string[] = [];

/** How many of those were the health probe. */
function healthCalls(): number {
  return asked.filter((url) => url.includes('/api/health')).length;
}

/**
 * Mount the page against a health endpoint that refuses to answer.
 *
 * Refuses rather than never settles: the probe schedules its next attempt from
 * the rejection, which is what a busy boot looks like from the browser - the
 * `fetch` is aborted and rejects, as `LoginPage`'s own comment records.
 */
function mountAgainstAStartingServer() {
  asked = [];
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    asked.push(url);
    if (url.includes('/api/health')) {
      return Promise.reject(new TypeError('Failed to fetch'));
    }
    if (url.includes('/auth/first-run')) {
      return Promise.resolve({ ok: true, json: async () => ({ demo_enabled: false }) });
    }
    if (url.includes('/oidc/config/')) {
      return Promise.resolve({ ok: true, json: async () => ({ enabled: false }) });
    }
    return Promise.resolve({ ok: true, json: async () => ({}) });
  });
  vi.stubGlobal('fetch', fetchMock);
  const view = render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
  return { ...view, fetchMock };
}

/** Move the clock and let whatever it fired finish.
 *
 * The async variant, and the difference is not cosmetic: the probe schedules its
 * next attempt from a rejected promise, so the timer for attempt N+1 is created in
 * a microtask that runs *after* a synchronous `advanceTimersByTime` has already
 * returned. Advancing without flushing microtasks therefore fires one timer less
 * than the schedule holds, and the ceiling this file exists to prove is never
 * reached - the run ends one attempt short and the page looks like a poll that
 * stopped quietly, which is exactly the defect under test.
 */
async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Run the whole schedule out, one wait at a time. */
async function exhaustTheSchedule(): Promise<void> {
  for (const delay of HEALTH_PROBE_DELAYS_MS) {
    await advance(delay);
  }
  await advance(1_000);
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the health probe schedule', () => {
  it('backs off, then caps, and spans the boot it is waiting for', () => {
    // Published rather than computed inside the effect, so this is a claim about
    // what the page will do and not about a number a reader cannot see.
    expect(HEALTH_PROBE_DELAYS_MS).toEqual([
      3_000, 6_000, 12_000, 24_000, 30_000, 30_000, 30_000, 30_000,
    ]);

    // Doubling, which is the part that makes the later waits cheap.
    for (let index = 1; index < 4; index += 1) {
      expect(HEALTH_PROBE_DELAYS_MS[index]).toBe((HEALTH_PROBE_DELAYS_MS[index - 1] ?? 0) * 2);
    }
    // And capped, so a reader is never left waiting two minutes for the next
    // word from a page that may already have given up.
    for (const delay of HEALTH_PROBE_DELAYS_MS.slice(4)) {
      expect(delay).toBe(30_000);
    }

    // Nine attempts over 165 seconds. main.py measures a cold boot reaching an
    // open port in about 143 seconds, so the ceiling sits above the worst boot
    // it documents - and the fixed three-second poll it replaced sat below it in
    // span while asking four times as often.
    const span = HEALTH_PROBE_DELAYS_MS.reduce((total, delay) => total + delay, 0);
    expect(HEALTH_PROBE_DELAYS_MS).toHaveLength(8);
    expect(span).toBeGreaterThanOrEqual(150_000);
  });

  it('asks on that schedule and then stops asking', async () => {
    vi.useFakeTimers();
    mountAgainstAStartingServer();
    await advance(0);
    expect(healthCalls()).toBe(1);

    for (const [index, delay] of HEALTH_PROBE_DELAYS_MS.entries()) {
      await advance(delay);
      expect(healthCalls(), `after the wait of ${delay}ms`).toBe(index + 2);
    }

    // The schedule is the whole of the polling. Ten minutes more produces no
    // tenth attempt, which is the difference between a ceiling and a loop.
    await advance(600_000);
    expect(healthCalls()).toBe(HEALTH_PROBE_DELAYS_MS.length + 1);
  });

  it('says the server is still starting, and offers a way back, once the schedule is spent', async () => {
    vi.useFakeTimers();
    mountAgainstAStartingServer();
    await exhaustTheSchedule();

    const ceiling = screen.getByTestId('login-still-starting');
    // Announced as a status rather than as an error: the server has not failed,
    // the reader arrived early, and the wording is the one this page already uses
    // while it waits - which all 45 locales answer, so it ships translated.
    expect(ceiling.getAttribute('role')).toBe('status');
    expect(ceiling.textContent).toContain('auth.preparing_workspace');
    expect(screen.getByTestId('login-retry-health').textContent).toContain('common.retry');

    // And the wait was not turned into a failure anywhere on the page.
    expect(screen.queryByTestId('login-error')).toBeNull();
    expect(healthCalls()).toBe(HEALTH_PROBE_DELAYS_MS.length + 1);
  });

  it('starts the schedule again when the reader asks it to', async () => {
    vi.useFakeTimers();
    mountAgainstAStartingServer();
    await exhaustTheSchedule();
    const spent = healthCalls();

    fireEvent.click(screen.getByTestId('login-retry-health'));
    await advance(0);

    // One attempt immediately, the ceiling notice gone while it waits, and the
    // schedule running from the top rather than repeating its last wait.
    expect(healthCalls()).toBe(spent + 1);
    expect(screen.queryByTestId('login-still-starting')).toBeNull();

    await advance(HEALTH_PROBE_DELAYS_MS[0] ?? 0);
    expect(healthCalls()).toBe(spent + 2);
  });
});
