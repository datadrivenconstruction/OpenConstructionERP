// @ts-nocheck
import { describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  scheduleApi: {
    updateSchedule: vi.fn().mockResolvedValue({}),
    generateFromBOQ: vi.fn().mockResolvedValue([]),
    previewGenerateFromBOQ: vi.fn().mockResolvedValue({}),
  },
}));

import { scheduleApi } from './api';
import { generateInWindow, previewInWindow, projectWindowDays } from './generateWindow';

describe('projectWindowDays', () => {
  it('counts both ends', () => {
    expect(projectWindowDays('2026-05-04', '2026-05-04')).toBe(1);
    expect(projectWindowDays('2026-01-01', '2026-12-31')).toBe(365);
  });

  it('is null for a missing, unreadable or reversed window', () => {
    expect(projectWindowDays('', '2026-12-31')).toBeNull();
    expect(projectWindowDays('2026-05-04', '')).toBeNull();
    expect(projectWindowDays('04.05.2026', '2026-12-31')).toBeNull();
    expect(projectWindowDays('2026-12-31', '2026-01-01')).toBeNull();
  });
});

describe('generateInWindow', () => {
  it('sends the start and the window in the request and saves nothing first', async () => {
    await generateInWindow('s1', 'b1', '2026-05-04', '2026-10-31');
    expect(scheduleApi.updateSchedule).not.toHaveBeenCalled();
    expect(scheduleApi.generateFromBOQ).toHaveBeenCalledWith('s1', 'b1', {
      startDate: '2026-05-04',
      totalProjectDays: 181,
      replace: false,
    });
  });

  it('asks the server to replace the existing activities only when told to', async () => {
    vi.mocked(scheduleApi.generateFromBOQ).mockClear();
    await generateInWindow('s1', 'b1', '2026-05-04', '2026-10-31', true);
    expect(scheduleApi.generateFromBOQ).toHaveBeenCalledWith('s1', 'b1', {
      startDate: '2026-05-04',
      totalProjectDays: 181,
      replace: true,
    });
  });

  it('generates without a window when no end date is given', async () => {
    vi.mocked(scheduleApi.generateFromBOQ).mockClear();
    await generateInWindow('s1', 'b1', '2026-05-04', '');
    expect(scheduleApi.generateFromBOQ).toHaveBeenCalledWith('s1', 'b1', { startDate: '2026-05-04', replace: false });
  });

  it('refuses an end before the start', async () => {
    vi.mocked(scheduleApi.generateFromBOQ).mockClear();
    await expect(generateInWindow('s1', 'b1', '2026-10-31', '2026-05-04')).rejects.toThrow();
    expect(scheduleApi.generateFromBOQ).not.toHaveBeenCalled();
  });

  it('sends workers per position only when there is a number', async () => {
    vi.mocked(scheduleApi.generateFromBOQ).mockClear();
    await generateInWindow('s1', 'b1', '2026-05-04', '2026-10-31', false, 6);
    expect(scheduleApi.generateFromBOQ).toHaveBeenCalledWith('s1', 'b1', {
      startDate: '2026-05-04',
      totalProjectDays: 181,
      replace: false,
      workersPerPosition: 6,
    });
    await previewInWindow('s1', 'b1', '2026-05-04', '2026-10-31', 6);
    expect(scheduleApi.previewGenerateFromBOQ).toHaveBeenLastCalledWith('s1', 'b1', {
      startDate: '2026-05-04',
      totalProjectDays: 181,
      workersPerPosition: 6,
    });
  });

  it('previews the same window', async () => {
    await previewInWindow('s1', 'b1', '2026-05-04', '2026-10-31');
    expect(scheduleApi.previewGenerateFromBOQ).toHaveBeenCalledWith('s1', 'b1', {
      startDate: '2026-05-04',
      totalProjectDays: 181,
    });
  });
});

describe('generationWorkers', () => {
  it('gives back the workers a person asked for last time, and nothing the generator chose', async () => {
    const { generationWorkers } = await import('./generateWindow');
    const record = (r: unknown) => ({ metadata_: { boq_generation: r } });
    expect(generationWorkers(record({ workers_per_position: 6, workers_assumed: false }))).toBe(6);
    expect(generationWorkers(record({ workers_per_position: 6, workers_assumed: true }))).toBeNull();
    expect(generationWorkers(record({ workers_per_position: 25, workers_assumed: false }))).toBeNull();
    expect(generationWorkers(record({ workers_per_position: '6', workers_assumed: false }))).toBeNull();
    expect(generationWorkers(null)).toBeNull();
  });
});

describe('generationWarnings', () => {
  it('reads the warnings the last generation left on the schedule', async () => {
    const { generationWarnings } = await import('./generateWindow');
    const warning = { code: 'plan_exceeds_window', planned_end: '2027-03-01', requested_end: '2026-10-31' };
    expect(
      generationWarnings({ metadata_: { boq_generation: { generated_at: 'x', warnings: [warning, 'junk', null] } } }),
    ).toEqual([warning]);
    // The unaliased name is read as well.
    expect(generationWarnings({ metadata: { boq_generation: { warnings: [warning] } } })).toEqual([warning]);
  });

  it('is empty when the schedule was never generated or the record is malformed', async () => {
    const { generationWarnings } = await import('./generateWindow');
    expect(generationWarnings(undefined)).toEqual([]);
    expect(generationWarnings({})).toEqual([]);
    expect(generationWarnings({ metadata: { boq_generation: 'nope' } })).toEqual([]);
    expect(generationWarnings({ metadata: { boq_generation: { warnings: 'nope' } } })).toEqual([]);
  });
});

describe('refreshAfterGenerate', () => {
  it('resolves only once the new plan has been fetched', async () => {
    const { QueryClient, QueryObserver } = await import('@tanstack/react-query');
    const { refreshAfterGenerate } = await import('./generateWindow');
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    let answer: (value: string[]) => void = () => {};
    let calls = 0;
    const observer = new QueryObserver(qc, {
      queryKey: ['gantt', 's1'],
      queryFn: () => {
        calls += 1;
        if (calls === 1) return Promise.resolve([]);
        return new Promise<string[]>((resolve) => {
          answer = resolve;
        });
      },
    });
    const unsubscribe = observer.subscribe(() => {});
    await vi.waitFor(() => expect(qc.getQueryData(['gantt', 's1'])).toEqual([]));

    let done = false;
    const pending = refreshAfterGenerate(qc, 's1').then(() => {
      done = true;
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(done).toBe(false);

    answer(['generated activity']);
    await pending;
    expect(qc.getQueryData(['gantt', 's1'])).toEqual(['generated activity']);
    unsubscribe();
  });
});
