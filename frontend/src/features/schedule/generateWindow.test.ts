// @ts-nocheck
import { describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  scheduleApi: { updateSchedule: vi.fn().mockResolvedValue({}), generateFromBOQ: vi.fn().mockResolvedValue([]) },
}));

import { scheduleApi } from './api';
import { generateInWindow, projectWindowDays } from './generateWindow';

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
  it('sends the project window as total_project_days after setting the start', async () => {
    await generateInWindow('s1', 'b1', '2026-05-04', '2026-10-31');
    expect(scheduleApi.updateSchedule).toHaveBeenCalledWith('s1', { start_date: '2026-05-04' });
    expect(scheduleApi.generateFromBOQ).toHaveBeenCalledWith('s1', 'b1', 181);
  });

  it('refuses to generate without an end date', async () => {
    vi.mocked(scheduleApi.generateFromBOQ).mockClear();
    await expect(generateInWindow('s1', 'b1', '2026-05-04', '')).rejects.toThrow();
    expect(scheduleApi.generateFromBOQ).not.toHaveBeenCalled();
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
