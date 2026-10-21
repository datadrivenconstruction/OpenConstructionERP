// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// #436 - "Request timeout after 45000ms: POST /v1/costs/vector/index/". The
// 45s was ours: `api.ts` gives every call the default mutation budget unless
// the caller opts into `longRunning`. Vector indexing can spend 30s loading
// the embedding model before it embeds the first of ~55K items, so 45s is
// unwinnable at any catalogue size - and the server has no disconnect
// cancellation on that route, so it finishes and commits work the user was
// told had failed.
//
// This guard asserts the budget at EVERY call site, not at one of them. The
// count assertion is the load-bearing half: a regex that looks for
// `longRunning: true` near the endpoint passes silently when the matcher
// misses a site, so the census is pinned to a number and the named list is
// printed on failure. If you legitimately add or remove a call site, change
// EXPECTED_SITES here and confirm your new site carries the flag - that edit
// is the review this ratchet exists to force.
//
// Run: npx vitest run --pool=forks src/features/costs/__tests__/vectorIndexLongBudget.test.ts

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join, relative, sep } from 'node:path';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiPost, type ApiRequestInit } from '@/shared/lib/api';
import { useToastStore, type Toast } from '@/stores/useToastStore';

const SRC = resolve(__dirname, '..', '..', '..');
const SELF = resolve(__dirname, 'vectorIndexLongBudget.test.ts');

/** Every call site that POSTs the vector index endpoint. */
const EXPECTED_SITES = 7;

/** A quoted (or backticked) occurrence of the endpoint path - i.e. a real
 *  argument, never the path as it appears in prose inside a comment. */
const SITE_RE = /(['"`])\/v1\/costs\/vector\/index\//g;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if (/\.(ts|tsx)$/.test(entry) && full !== SELF) {
      out.push(full);
    }
  }
  return out;
}

interface CallSite {
  where: string;
  callee: string;
  args: string;
}

/**
 * Slice out the call expression that encloses `at` - the callee text just
 * before its opening paren, and everything between the parens.
 */
function enclosingCall(source: string, at: number): { callee: string; args: string } {
  let depth = 0;
  let open = -1;
  for (let i = at; i >= 0; i--) {
    const ch = source[i];
    if (ch === ')') depth++;
    else if (ch === '(') {
      if (depth === 0) {
        open = i;
        break;
      }
      depth--;
    }
  }
  if (open < 0) return { callee: '', args: '' };

  let d = 1;
  let close = source.length;
  for (let i = open + 1; i < source.length; i++) {
    const ch = source[i];
    if (ch === '(') d++;
    else if (ch === ')') {
      d--;
      if (d === 0) {
        close = i;
        break;
      }
    }
  }
  return {
    callee: source.slice(Math.max(0, open - 80), open),
    args: source.slice(open + 1, close),
  };
}

function collectSites(): CallSite[] {
  const sites: CallSite[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, 'utf-8');
    SITE_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = SITE_RE.exec(source)) !== null) {
      const line = source.slice(0, match.index).split('\n').length;
      const { callee, args } = enclosingCall(source, match.index);
      sites.push({
        where: `${relative(SRC, file).split(sep).join('/')}:${line}`,
        callee,
        args,
      });
    }
  }
  return sites;
}

describe('POST /v1/costs/vector/index/ runs on the long budget', () => {
  const sites = collectSites();
  const listed = sites.map((s) => s.where).join('\n  ');

  it('finds every known call site - the census the flag check is measured against', () => {
    expect(
      sites.length,
      `Expected ${EXPECTED_SITES} vector-index call sites, found ${sites.length}:\n  ${listed}\n` +
        'A LOWER number means this test\'s matcher went blind, not that the code got cleaner.',
    ).toBe(EXPECTED_SITES);
  });

  it('routes every call site through the api wrapper, never a raw fetch', () => {
    for (const site of sites) {
      expect(
        /\bapiPost\b[^(]*$/.test(site.callee),
        `${site.where} does not POST through apiPost. A raw fetch() carries no client ` +
          'timeout at all and skips the 401 refresh, so it hangs instead of failing.',
      ).toBe(true);
    }
  });

  it('opts every call site into longRunning, so the budget is 5 min and not 45 s', () => {
    const missing = sites.filter((s) => !s.args.includes('longRunning: true')).map((s) => s.where);
    expect(
      missing,
      `These vector-index calls fall back to the 45s default budget: ${missing.join(', ')}. ` +
        'Indexing outlives 45s at any catalogue size (GitHub #436).',
    ).toEqual([]);
  });

  it('leaves no raw /api/ fetch of the endpoint anywhere in the tree', () => {
    const offenders = walk(SRC)
      .filter((file) => readFileSync(file, 'utf-8').includes('/api/v1/costs/vector/index/'))
      .map((file) => relative(SRC, file).split(sep).join('/'));
    expect(offenders).toEqual([]);
  });
});

/**
 * Capture the signal `api.ts` attaches to the request under test, and reject
 * the way fetch does on abort.
 *
 * Only the vector-index request is recorded. A client timeout also makes the
 * error reporter fire its own POST to /api/v1/client-errors/ through this same
 * global, so recording every call would report two requests where the test
 * started one - and a test that counts requests would then count the reporter
 * as a second attempt. Everything else is answered and dropped.
 */
function stubHangingFetch(): AbortSignal[] {
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      if (!String(url).includes('/v1/costs/vector/index/')) {
        return Promise.resolve({ ok: true, status: 204, statusText: 'No Content' } as Response);
      }
      return new Promise<Response>((_resolve, reject) => {
        const signal = init.signal as AbortSignal;
        signals.push(signal);
        signal.addEventListener('abort', () => {
          const err = new Error('The operation was aborted.');
          err.name = 'AbortError';
          reject(err);
        });
      });
    }),
  );
  return signals;
}

/** The signal of the one request under test - absent means fetch was never
 *  reached, which would make every abort assertion below vacuous. */
function only(signals: AbortSignal[]): AbortSignal {
  const signal = signals[0];
  if (!signal) throw new Error('apiPost never called fetch - nothing to time.');
  return signal;
}

describe('the flag is not a token - longRunning really buys the long budget', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('holds the vector-index request open past 45 s and aborts at 5 min', async () => {
    vi.useFakeTimers();
    const signals = stubHangingFetch();
    const settled = apiPost('/v1/costs/vector/index/', undefined, { longRunning: true }).then(
      () => 'resolved',
      () => 'rejected',
    );

    await vi.advanceTimersByTimeAsync(45_000);
    expect(
      only(signals).aborted,
      'The 45s default killed a long-running request - the reported bug (GitHub #436).',
    ).toBe(false);

    await vi.advanceTimersByTimeAsync(299_000 - 45_000);
    expect(only(signals).aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(only(signals).aborted).toBe(true);
    await expect(settled).resolves.toBe('rejected');
  });

  it('still aborts the same request at 90 s without the flag', async () => {
    // The control: without `longRunning` the budget really is the short one, so
    // the test above is measuring the flag and not some ambient default.
    vi.useFakeTimers();
    const signals = stubHangingFetch();
    const settled = apiPost('/v1/costs/vector/index/').then(
      () => 'resolved',
      () => 'rejected',
    );

    await vi.advanceTimersByTimeAsync(89_000);
    expect(only(signals).aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(only(signals).aborted).toBe(true);
    await expect(settled).resolves.toBe('rejected');
  });
});

// The half of #436 the long budget does not reach. When even 5 min runs out,
// the server is still embedding and still commits, so the caller keeps
// watching the vector count and announces the success that lands about a
// minute later. Meanwhile `api.ts` had already raised its own global "Request
// timed out" banner on the way out, so the user read a failure and then a
// success for one action. `suppressTimeoutToast` hands that one call's
// reporting to the caller - and only that call's.
describe('the global timeout toast defers to a caller that reports the timeout itself', () => {
  /** Mirrors TIMEOUT_TOAST_THROTTLE_MS in api.ts, which does not export it. */
  const THROTTLE_WINDOW_MS = 30_000;

  // api.ts coalesces timeout toasts behind a module-global timestamp that
  // outlives a single test, so a case inherits whatever the previous one
  // stamped. Left alone that decides these tests instead of the flag doing it:
  // the "still toasts" case fails for an unrelated reason and the "stays
  // silent" case passes without proving anything. Every case therefore starts
  // an hour past both the previous clock and the real one.
  let clock = 0;
  function freshWindow(): void {
    clock = Math.max(clock, Date.now()) + 300 * THROTTLE_WINDOW_MS;
    vi.setSystemTime(clock);
  }

  const realAddToast = useToastStore.getState().addToast;
  let toasted: Array<Omit<Toast, 'id'>>;

  beforeEach(() => {
    toasted = [];
    useToastStore.setState({
      addToast: (toast: Omit<Toast, 'id'>) => {
        toasted.push(toast);
        return 'test-toast';
      },
    });
  });

  afterEach(() => {
    useToastStore.setState({ addToast: realAddToast });
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /** Run one vector-index POST to its 5-min abort and report how it settled. */
  async function timeOutOnce(init: ApiRequestInit): Promise<string> {
    const signals = stubHangingFetch();
    const settled = apiPost('/v1/costs/vector/index/', undefined, init).then(
      () => 'resolved',
      () => 'rejected',
    );
    await vi.advanceTimersByTimeAsync(301_000);
    expect(only(signals).aborted, 'the request never aborted - nothing was reported').toBe(true);
    return settled;
  }

  it('stays silent for the call that opted out', async () => {
    vi.useFakeTimers();
    freshWindow();

    await expect(
      timeOutOnce({ longRunning: true, suppressTimeoutToast: true }),
    ).resolves.toBe('rejected');

    expect(
      toasted,
      'The wrapper announced a failure for a call whose own handler is still ' +
        'watching the count and is about to announce success (GitHub #436).',
    ).toEqual([]);
  });

  it('still shows it for the same call without the opt-out', async () => {
    // The control. Without it the assertion above proves only that this test
    // file cannot make a toast appear at all.
    vi.useFakeTimers();
    freshWindow();

    await expect(timeOutOnce({ longRunning: true })).resolves.toBe('rejected');

    expect(toasted).toHaveLength(1);
    expect(toasted[0]?.type).toBe('error');
  });

  it('does not spend the coalescing window on a toast nobody saw', async () => {
    // Suppressing must skip the window, not consume it. Guarding the addToast
    // call from inside the window instead would stamp the timestamp and then
    // show nothing, silencing every other request on the screen for the next
    // 12s - the screen would just stop, with no explanation anywhere.
    //
    // Both requests are started together and abort in the same instant, which
    // is the case the coalescer exists for and the only way to land two aborts
    // inside one window: advancing the clock between them would move it past
    // THROTTLE_WINDOW_MS and make the assertion vacuous.
    vi.useFakeTimers();
    freshWindow();
    const signals = stubHangingFetch();

    const suppressed = apiPost('/v1/costs/vector/index/', undefined, {
      longRunning: true,
      suppressTimeoutToast: true,
    }).then(() => 'resolved', () => 'rejected');
    const plain = apiPost('/v1/costs/vector/index/', undefined, { longRunning: true }).then(
      () => 'resolved',
      () => 'rejected',
    );

    await vi.advanceTimersByTimeAsync(301_000);
    expect(signals).toHaveLength(2);
    expect(signals.every((s) => s.aborted)).toBe(true);
    await expect(suppressed).resolves.toBe('rejected');
    await expect(plain).resolves.toBe('rejected');

    expect(
      toasted,
      'The suppressed call ate the coalescing window, so the request that had ' +
        'nothing else to say about itself went unreported.',
    ).toHaveLength(1);
    expect(toasted[0]?.type).toBe('error');
  });

  it('keeps coalescing bursts for everyone else', async () => {
    // The opt-out must not be a way to turn the throttle off either: two
    // ordinary calls aborting together still produce one toast, not two.
    vi.useFakeTimers();
    freshWindow();
    const signals = stubHangingFetch();

    const first = apiPost('/v1/costs/vector/index/', undefined, { longRunning: true }).then(
      () => 'resolved',
      () => 'rejected',
    );
    const second = apiPost('/v1/costs/vector/index/', undefined, { longRunning: true }).then(
      () => 'resolved',
      () => 'rejected',
    );

    await vi.advanceTimersByTimeAsync(301_000);
    expect(signals).toHaveLength(2);
    await expect(first).resolves.toBe('rejected');
    await expect(second).resolves.toBe('rejected');
    expect(toasted).toHaveLength(1);
  });
});

/**
 * The shipping files only. A test file is allowed to call these helpers any
 * way it likes - counting its calls as call sites would make both censuses
 * below meaningless the moment a test explores a shape the product must not
 * have.
 */
function productionFiles(): string[] {
  return walk(SRC).filter((file) => !file.includes(`${sep}__tests__${sep}`) && !/\.test\.tsx?$/.test(file));
}

// The opt-out is only defensible where the global toast would say something
// the caller can better, so it is pinned to the sites that qualify. Two shapes
// do: a call that reports the timeout itself, and a probe whose failure is a
// designed non-event. A call that is neither must keep the global toast; with
// neither, the screen stops and says nothing, which is worse than the
// contradiction this fixes.
describe('only the vector calls that own their reporting opt out of the toast', () => {
  // Was 12 until 62c64bed2 deleted fetchVectorReadiness, which was exported and
  // called from nowhere and carried one of the two match-elements probes with
  // it. The deletion was right and this census simply did not follow it, which
  // is the failure mode the closing sentence below asks a reader to avoid: a
  // number that names a population stops being true the moment the population
  // moves, and nothing about deleting dead code makes a census recount itself.
  // The two BIM model status polls retry on the next tick, so a slow poll has nothing to report.
  const EXPECTED_OPT_OUTS = 13;

  it('suppresses the global toast at exactly the thirteen sites that replace it', () => {
    const sites: string[] = [];
    for (const file of productionFiles()) {
      const where = relative(SRC, file).split(sep).join('/');
      readFileSync(file, 'utf-8')
        .split('\n')
        .forEach((line, i) => {
          if (line.includes('suppressTimeoutToast: true')) sites.push(`${where}:${i + 1}`);
        });
    }
    expect(
      sites.length,
      `Expected ${EXPECTED_OPT_OUTS} opt-out sites, found ${sites.length}:\n  ${sites.join('\n  ')}\n` +
        'Seven vector-index POSTs, the status read the poll makes while it is ' +
        'proving the index landed, the one match-elements readiness probe ' +
        'whose card renders nothing on failure by design, and the two ' +
        'snapshot-restore POSTs, which answer their own abort by saying the ' +
        'restore is still running on the server, and the two BIM model status ' +
        'polls, which retry on the next tick. A new one belongs here only if ' +
        'it reports the timeout itself or has nothing to report; if it does, ' +
        'change this number deliberately.',
    ).toBe(EXPECTED_OPT_OUTS);
  });
});

// The readiness threshold only protects a user at the sites that pass it. Two
// of the three polls were passing `{ baseline }` alone, so on the import
// screen the first committed batch read as a finished index while the BOQ
// editor, reading the very same number, still called that index unusable. The
// behaviour of the threshold is proved in vectorIndexPollFallback.test.ts;
// what is proved here is that every caller actually holds it.
describe('every poll of the vector count holds the readiness threshold', () => {
  const EXPECTED_POLL_SITES = 3;
  const POLL_CALL = 'pollVectorIndexLanded(';

  it('passes minCount at all three sites, and finds all three', () => {
    const sites: string[] = [];
    const missing: string[] = [];
    for (const file of productionFiles()) {
      const source = readFileSync(file, 'utf-8');
      let at = source.indexOf(POLL_CALL);
      while (at !== -1) {
        // Skip the declaration itself; only calls are call sites.
        const isDeclaration = /\bfunction\s*$/.test(source.slice(Math.max(0, at - 24), at));
        if (!isDeclaration) {
          const where = `${relative(SRC, file).split(sep).join('/')}:${
            source.slice(0, at).split('\n').length
          }`;
          sites.push(where);
          const { args } = enclosingCall(source, at + POLL_CALL.length);
          if (!args.includes('minCount: VECTOR_READY_MIN_COUNT')) missing.push(where);
        }
        at = source.indexOf(POLL_CALL, at + POLL_CALL.length);
      }
    }

    expect(
      sites.length,
      `Expected ${EXPECTED_POLL_SITES} poll call sites, found ${sites.length}:\n  ${sites.join(
        '\n  ',
      )}\nA LOWER number means this census went blind, not that a site was removed.`,
    ).toBe(EXPECTED_POLL_SITES);
    expect(
      missing,
      `These polls would announce success below the readiness threshold: ${missing.join(', ')}. ` +
        'The user is told the index is ready while indexing is still running.',
    ).toEqual([]);
  });
});
