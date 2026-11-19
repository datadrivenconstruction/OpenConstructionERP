// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The global query error handler reports the silent case, once per cause.
 *
 * Three halves. First that a query which fails with no data on screen produces a
 * message at all, because before this handler existed it produced none and the
 * user read an empty table as an empty project. Then that each deliberate silence
 * holds, since the failure mode of a global handler is noise: every skip below has
 * a surface that already reports the same failure, and a second toast for it is
 * the flood `api.ts` was fixed for once already.
 *
 * The third half is the one an owner's network panel asked for. This handler used
 * to keep one clock for everything - a toast at most every twelve seconds, whoever
 * the failure came from - which coalesced a burst and then repeated the same
 * sentence every twelve seconds for as long as the reader stayed. On a fresh
 * install, where forty queries meet a server that has not finished starting, that
 * is one cause arriving again and again before the page has loaded anything, with
 * nothing on it to answer. So the unit of silence is now the cause, the reader is
 * offered a way to ask again, and a server that says it is still starting is not
 * reported as a failure.
 *
 * `i18next` is mocked to answer with the key it was given and to record the default
 * beside it. Asserting the key is the point: a translation is a value in
 * forty-three bundles, and what this handler owns is which of them it asks for.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { useToastStore, type Toast } from '@/stores/useToastStore';

import { ApiError } from './api';
import {
  notifyQueryError,
  resetReportedQueryErrorCauses,
  type FailedQuery,
} from './queryErrorToast';

const { translated } = vi.hoisted(() => ({
  translated: [] as Array<{ key: string; defaultValue: string | undefined }>,
}));

vi.mock('i18next', () => ({
  default: {
    language: 'en',
    exists: () => false,
    on: () => undefined,
    off: () => undefined,
    t: (key: string, options?: { defaultValue?: string }) => {
      translated.push({ key, defaultValue: options?.defaultValue });
      return key;
    },
  },
}));

/** A query that has never resolved: the case a failure leaves blank. */
const EMPTY: FailedQuery = { state: {} };

/** A second query, because one cause is not the same thing as one query. */
const OTHER: FailedQuery = { state: {} };

/**
 * Every message the handler raised, in order.
 *
 * Read off a spy on the store's own `addToast` rather than off the store, for two
 * reasons that both matter here. The store coalesces a toast whose type and title
 * match one still on screen - right for a burst, and it would hide the difference
 * between "one cause reported once" and "four causes collapsed into one bubble" -
 * and it keeps at most 23 history entries, which is fewer than the sixty-four
 * causes one of these cases asks about. The spy sees the call the handler made.
 */
let raised: Array<Omit<Toast, 'id' | 'count'>> = [];

function times(): number {
  return raised.length;
}

/** The payload of one message the handler raised. */
function toast(index: number): Omit<Toast, 'id' | 'count'> | undefined {
  return raised[index];
}

/** The default value the handler asked for under a key, if it asked. */
function defaultValueFor(key: string): string | undefined {
  return translated.find((entry) => entry.key === key)?.defaultValue;
}

// Time is faked so a case can cross an hour on purpose rather than wait one out,
// and each test starts an hour after the last so nothing is handed over through
// the clock. The cause registry is module state too, and is cleared explicitly.
const BASE = new Date('2026-07-26T10:00:00Z').getTime();
let testIndex = 0;

beforeEach(() => {
  vi.useFakeTimers();
  testIndex += 1;
  vi.setSystemTime(BASE + testIndex * 3_600_000);
  resetReportedQueryErrorCauses();
  translated.length = 0;
  raised = [];
  useToastStore.setState({ toasts: [], history: [] });
  // The handler reaches the store through `useToastStore.getState().addToast`, so a
  // spy on that object's method sees every message it raises.
  vi.spyOn(useToastStore.getState(), 'addToast').mockImplementation((payload) => {
    raised.push(payload);
    return 'toast-under-test';
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('notifyQueryError', () => {
  it('reports a server failure that left the screen empty', () => {
    notifyQueryError(
      new ApiError(500, 'Internal Server Error', { detail: 'Database connection refused' }),
      EMPTY,
    );

    expect(times()).toBe(1);
    // Carrying the reason is the point; a bare "something failed" would leave the
    // reader no better off than the empty table did.
    expect(toast(0)).toMatchObject({ type: 'error', message: 'Database connection refused' });
  });

  it('reports a failure that carries no status at all', () => {
    // Unreachable server: no response, so no status to reason about. This is the
    // case a status-only rule would drop, and it is the commonest one on a cold
    // boot, where the port is not open yet and the request is refused.
    notifyQueryError(new TypeError('Failed to fetch'), EMPTY);

    expect(times()).toBe(1);
  });

  it('says one thing when a whole screen of queries fails at once', () => {
    // Forty queries against a server that has not finished starting fail inside the
    // same tick, from two different query objects. This is the owner's sign-in
    // page, and it is one fact about one server.
    for (let index = 0; index < 40; index += 1) {
      notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), index % 2 ? EMPTY : OTHER);
    }

    expect(times()).toBe(1);
  });

  it('does not repeat one cause, however long the reader stays', () => {
    // The contract this replaces allowed the same sentence again every twelve
    // seconds, which is how one cause on a cold start kept arriving. A cause is
    // reported once, and the reader gets the action below instead of a repeat.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);
    vi.setSystemTime(Date.now() + 12_001);
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);
    vi.setSystemTime(Date.now() + 3_600_000);
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    expect(times(), 'the same cause was announced more than once').toBe(1);
  });

  it('reports a second cause beside the first', () => {
    // Silence is per cause and not per handler. A database that refuses connections
    // and then a gateway that gives up are two facts, and hiding the second would
    // leave the reader with a message about the thing that stopped being wrong.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);
    notifyQueryError(new ApiError(502, 'Bad Gateway', undefined), OTHER);

    expect(times()).toBe(2);
  });

  it('keeps a third failure of the first cause silent', () => {
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);
    notifyQueryError(new ApiError(502, 'Bad Gateway', undefined), EMPTY);
    vi.advanceTimersByTime(60_000);
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    expect(times()).toBe(2);
  });

  it('forgets every cause when the reader gets in', () => {
    // A successful sign-in means the server answered, so whatever it was doing is
    // over and the next failure is a new fact about a session that now works.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);
    resetReportedQueryErrorCauses();
    vi.advanceTimersByTime(60_000);
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    expect(times(), 'a cleared registry must let the same cause speak again').toBe(2);
  });

  it('remembers at most sixty-four causes, and forgets the oldest', () => {
    // A bound rather than a policy: a tab nobody closes for a week must not grow a
    // module-level map without limit. The first cause is the one evicted, so it is
    // the one that can be reported again.
    // Seventy distinct causes, which means seventy distinct messages: an ApiError
    // carries the reason a reader is shown in its body, not in its status text, so
    // varying the text alone would be one cause seventy times.
    for (let index = 0; index < 70; index += 1) {
      notifyQueryError(
        new ApiError(500, 'Internal Server Error', { detail: `failure number ${index}` }),
        EMPTY,
      );
    }
    const afterBurst = times();
    expect(afterBurst).toBe(70);

    vi.advanceTimersByTime(60_000);
    notifyQueryError(
      new ApiError(500, 'Internal Server Error', { detail: 'failure number 0' }),
      EMPTY,
    );
    expect(times(), 'the evicted cause was still remembered').toBe(afterBurst + 1);
  });

  it('offers a way to ask again, and it re-runs the queries', () => {
    const onRetry = vi.fn();

    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY, { onRetry });
    expect(times()).toBe(1);
    expect(toast(0)?.action?.label).toBe('common.retry');
    expect(defaultValueFor('common.retry')).toBe('Retry');

    toast(0)?.action?.onClick();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('carries no action when the caller cannot re-ask', () => {
    // A control that does nothing is worse than no control: it is a promise.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    expect(toast(0)?.action).toBeUndefined();
  });

  it('says a server that is still starting is starting, and not that it failed', () => {
    // 503 is what this product answers while it comes up, with a Retry-After beside
    // it. Styled as an error and worded as a failure, it is the first thing a reader
    // meets on a cold boot, and it tells them the install is broken.
    notifyQueryError(new ApiError(503, 'Service Unavailable', undefined), EMPTY);

    expect(times()).toBe(1);
    expect(toast(0)).toMatchObject({ type: 'info', title: 'errors.query_server_starting_title' });
    expect(defaultValueFor('errors.query_server_starting_title')).toBe('Still starting up');
  });

  it('still calls a failure a failure', () => {
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    expect(toast(0)).toMatchObject({ type: 'error', title: 'errors.query_failed_title' });
    expect(defaultValueFor('errors.query_failed_title')).toBe('Could not load data');
  });

  it('stays quiet when the query already has data on screen', () => {
    // A background refetch failing over live data. The numbers are real, only older
    // than the reader thinks, so there is nothing misleading to correct.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), {
      state: { data: [{ id: 1 }] },
    });

    expect(times()).toBe(0);
  });

  it('treats an empty array as data, not as nothing', () => {
    // `[]` is a loaded, genuinely empty list. Reporting it would fire on every
    // refetch failure over an empty table, which is most of them.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), {
      state: { data: [] },
    });

    expect(times()).toBe(0);
  });

  it('honours the same opt-out the mutation handler honours', () => {
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), {
      state: {},
      meta: { suppressGlobalErrorToast: true },
    });

    expect(times()).toBe(0);
  });

  it('leaves timeouts to api.ts, which has already toasted them', () => {
    const timeout = Object.assign(new Error('Request timeout'), { isTimeout: true });

    notifyQueryError(timeout, EMPTY);

    expect(times()).toBe(0);
  });

  it('leaves aborts alone for the same reason', () => {
    const aborted = Object.assign(new Error('The operation was aborted'), {
      name: 'AbortError',
    });

    notifyQueryError(aborted, EMPTY);

    expect(times()).toBe(0);
  });

  it.each([
    [401, 'auth redirects on its own'],
    [403, 'the permission screen says it better'],
    [404, 'features render their own not-found state'],
    [422, 'validation belongs to the form that submitted it'],
    [429, 'api.ts already toasts rate limits'],
  ])('stays quiet on %i, because %s', (status) => {
    notifyQueryError(new ApiError(status, 'Client error', undefined), EMPTY);

    expect(times()).toBe(0);
  });

  it('does not let a skipped failure spend a cause its message', () => {
    // The skips return before the registry is touched. If they did not, one 404
    // would buy permanent silence for the 500 behind it.
    notifyQueryError(new ApiError(404, 'Not Found', undefined), EMPTY);
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    expect(times()).toBe(1);
  });
});
