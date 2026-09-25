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
