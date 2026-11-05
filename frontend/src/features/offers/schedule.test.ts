import { describe, expect, it } from 'vitest';
import { rowsFromTemplate, scheduleBar, syncRows, takeTheRest, type ScheduleRow } from './schedule';

const row = (percent: string, value = '0', kind: ScheduleRow['kind'] = 'progress'): ScheduleRow => ({
  code: '1',
  name: 'x',
  kind,
  percent,
  value,
  due: { type: 'signing' },
  lag_days: 0,
});

describe('schedule arithmetic', () => {
  it('turns a typed percent into an amount and back without floats', () => {
    const rows = syncRows([row('30'), row('0', '0', 'final')], '48350.00', 'EUR', { index: 0, field: 'percent' });
    expect(rows[0]?.value).toBe('14505.00');
    const back = syncRows(rows, '48350.00', 'EUR', { index: 0, field: 'value' });
    expect(back[0]?.percent).toBe('30.0000');
  });

  it('lets the last row take the rounding remainder (33.3333 x 3 of 100.00)', () => {
    const rows = syncRows([row('33.3333'), row('33.3333'), row('33.3333', '0', 'final')], '100.00', 'EUR', { index: 0, field: 'percent' });
    const withSecond = syncRows(rows, '100.00', 'EUR', { index: 1, field: 'percent' });
    expect(withSecond.map((r) => r.value)).toEqual(['33.33', '33.33', '33.34']);
  });

  it('reports the bar state: ok, left and over', () => {
    const ok = rowsFromTemplate('30_40_30', '48350.00', 'EUR');
    expect(scheduleBar(ok, '48350.00', 'EUR').state).toBe('ok');
    const left = [ok[0] as ScheduleRow, { ...(ok[1] as ScheduleRow), value: '10000.00' }];
    expect(scheduleBar(left, '48350.00', 'EUR')).toMatchObject({ state: 'left', amount: '23845.00' });
    const over = [...ok, { ...(ok[0] as ScheduleRow), value: '5802.00' }];
    expect(scheduleBar(over, '48350.00', 'EUR')).toMatchObject({ state: 'over', amount: '5802.00' });
  });

  it('puts the rest on the last instalment', () => {
    const fixed = takeTheRest([row('0', '1000.00'), row('0', '1.00', 'final')], '2500.00', 2);
    expect(fixed[1]?.value).toBe('1500.00');
  });

  it('keeps zero-decimal currencies whole', () => {
    expect(rowsFromTemplate('50_50', '1001', 'JPY').map((r) => r.value)).toEqual(['501', '500']);
  });
});
