// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import {
  ImportJobFailedError,
  importProgressText,
  isImportJob,
  waitForImportJob,
  type ImportJobView,
  type ImportProgress,
} from './importJob';

const t = (key: string, opts?: Record<string, unknown>) =>
  `${key}${opts && 'percent' in opts ? `:${String(opts.percent)}` : ''}`;

function answers(...views: (ImportJobView | number | Error)[]): typeof fetch {
  const queue = [...views];
  return vi.fn(async () => {
    const next = queue.length > 1 ? queue.shift()! : queue[0]!;
    if (next instanceof Error) throw next;
    if (typeof next === 'number') return new Response('{}', { status: next });
    return new Response(JSON.stringify(next), { status: 200 });
  }) as unknown as typeof fetch;
}

const noSleep = async () => {};

describe('waitForImportJob', () => {
  it('reports every phase and resolves with the result of the succeeded job', async () => {
    const seen: ImportProgress[] = [];
    const result = await waitForImportJob({
      boqId: 'b1',
      jobId: 'j1',
      headers: {},
      t,
      sleep: noSleep,
      onProgress: (p) => seen.push(p),
      fetchImpl: answers(
        { job_id: 'j1', status: 'pending', progress_percent: 0, phase: null },
        { job_id: 'j1', status: 'started', progress_percent: 40, phase: 'writing' },
        { job_id: 'j1', status: 'success', progress_percent: 85, phase: 'validating', result: { created: 11 } },
      ),
    });
    expect(result).toEqual({ created: 11 });
    expect(seen.map((p) => p.phase)).toEqual([null, 'writing', 'validating']);
    // A finished job reads as done, whatever the last phase recorded.
    expect(seen.at(-1)?.percent).toBe(100);
  });

  it('polls the job of its own bill', async () => {
    const fetchImpl = answers({ job_id: 'j1', status: 'success', progress_percent: 100, result: {} });
    await waitForImportJob({ boqId: 'b1', jobId: 'j1', headers: { A: '1' }, t, sleep: noSleep, fetchImpl });
    expect(vi.mocked(fetchImpl).mock.calls[0]![0]).toBe('/api/v1/boq/boqs/b1/import/jobs/j1/');
  });

  it("passes on the server's reason when the file was refused", async () => {
    const wait = waitForImportJob({
      boqId: 'b1',
      jobId: 'j1',
      headers: {},
      t,
      sleep: noSleep,
      fetchImpl: answers({ job_id: 'j1', status: 'failed', progress_percent: 5, error: 'Kein XPWE-Dokument' }),
    });
    await expect(wait).rejects.toThrow(new ImportJobFailedError('Kein XPWE-Dokument'));
  });

  it('words a coded refusal from the code, not from the server text', async () => {
    const wait = waitForImportJob({
      boqId: 'b1',
      jobId: 'j1',
      headers: {},
      t,
      sleep: noSleep,
      fetchImpl: answers({
        job_id: 'j1',
        status: 'failed',
        progress_percent: 5,
        error: 'The XPWE file is not well-formed XML: unclosed token',
        error_code: 'xpwe_not_well_formed',
        error_params: { line: 2, column: 1 },
      }),
    });
    await expect(wait).rejects.toThrow('boq.import_error.xpwe_not_well_formed');
  });

  it('words an internal failure itself', async () => {
    const wait = waitForImportJob({
      boqId: 'b1',
      jobId: 'j1',
      headers: {},
      t,
      sleep: noSleep,
      fetchImpl: answers({ job_id: 'j1', status: 'failed', progress_percent: 40, error: null }),
    });
    await expect(wait).rejects.toThrow('boq.import_job_failed');
  });

  it('rides out a dropped poll and goes on waiting', async () => {
    const result = await waitForImportJob({
      boqId: 'b1',
      jobId: 'j1',
      headers: {},
      t,
      sleep: noSleep,
      fetchImpl: answers(
        new TypeError('Failed to fetch'),
        502,
        { job_id: 'j1', status: 'success', progress_percent: 100, result: { created: 3 } },
      ),
    });
    expect(result).toEqual({ created: 3 });
  });

  it.each([['offline', new TypeError('Failed to fetch')], ['failing', 503]] as const)(
    'gives up with a reason after the server stays %s',
    async (_name, failure) => {
      const wait = waitForImportJob({
        boqId: 'b1',
        jobId: 'j1',
        headers: {},
        t,
        sleep: noSleep,
        fetchImpl: answers(failure),
      });
      await expect(wait).rejects.toThrow('boq.import_job_unreachable');
    },
  );

  it('says so when the job is gone', async () => {
    const wait = waitForImportJob({ boqId: 'b1', jobId: 'j1', headers: {}, t, sleep: noSleep, fetchImpl: answers(404) });
    await expect(wait).rejects.toThrow('boq.import_job_lost');
  });

  it('stops waiting when told to', async () => {
    const stop = new AbortController();
    stop.abort();
    const wait = waitForImportJob({
      boqId: 'b1',
      jobId: 'j1',
      headers: {},
      t,
      sleep: noSleep,
      signal: stop.signal,
      fetchImpl: answers({ job_id: 'j1', status: 'started', progress_percent: 40 }),
    });
    await expect(wait).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('isImportJob', () => {
  it('tells a job from a synchronous result', () => {
    expect(isImportJob({ job_id: 'j1', status: 'pending', progress_percent: 0 })).toBe(true);
    expect(isImportJob({ imported: 3, errors: [] })).toBe(false);
    expect(isImportJob(null)).toBe(false);
  });
});

describe('importProgressText', () => {
  it('names the phase and a whole percentage', () => {
    expect(importProgressText({ percent: 40.4, phase: 'writing' }, t)).toBe('boq.import_job_writing:40');
    expect(importProgressText({ percent: 140, phase: 'validating' }, t)).toBe('boq.import_job_validating:100');
    expect(importProgressText({ percent: 0, phase: null }, t)).toBe('boq.import_job_queued:0');
  });
});
