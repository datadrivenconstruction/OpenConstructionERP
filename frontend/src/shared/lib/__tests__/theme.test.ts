// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { DEFAULT_SCHEDULE, isDarkHour, resolveTheme, sanitizeSchedule } from '../theme';

const env = (o: Partial<{ systemDark: boolean; hour: number }> = {}) => ({
  systemDark: false,
  hour: 12,
  schedule: DEFAULT_SCHEDULE,
  ...o,
});

describe('theme resolution', () => {
  it('light and dark are fixed', () => {
    expect(resolveTheme('light', env({ systemDark: true, hour: 23 }))).toBe('light');
    expect(resolveTheme('dark', env({ hour: 12 }))).toBe('dark');
  });

  it('system follows the OS', () => {
    expect(resolveTheme('system', env({ systemDark: true }))).toBe('dark');
    expect(resolveTheme('system', env())).toBe('light');
  });

  it('schedule is dark inside a window that wraps past midnight', () => {
    const s = { darkFrom: 19, darkTo: 7 };
    expect([18, 19, 23, 0, 6, 7].map((h) => isDarkHour(h, s))).toEqual([false, true, true, true, true, false]);
    expect(resolveTheme('schedule', env({ hour: 22 }))).toBe('dark');
    expect(resolveTheme('schedule', env({ hour: 9, systemDark: true }))).toBe('light');
  });

  it('schedule handles a same-day window and an empty one', () => {
    expect(isDarkHour(13, { darkFrom: 12, darkTo: 14 })).toBe(true);
    expect(isDarkHour(14, { darkFrom: 12, darkTo: 14 })).toBe(false);
    expect(isDarkHour(5, { darkFrom: 8, darkTo: 8 })).toBe(false);
  });

  it('accepts only whole hours 0..23', () => {
    expect(sanitizeSchedule({ darkFrom: 20, darkTo: 6 })).toEqual({ darkFrom: 20, darkTo: 6 });
    expect(sanitizeSchedule({ darkFrom: 24, darkTo: 6 })).toBeNull();
    expect(sanitizeSchedule({ darkFrom: 1.5, darkTo: 6 })).toBeNull();
    expect(sanitizeSchedule('20-6')).toBeNull();
  });
});
