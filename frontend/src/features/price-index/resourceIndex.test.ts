// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Unit tests for the pure resource-index helpers: quarter handling, the
// region/quarter pickers, the missing-index pre-check, string-only money
// formatting (a kopeck is never rounded by a float) and reading the server's
// structured refusal.
import { describe, it, expect, vi } from 'vitest';

import { ApiError } from '@/shared/lib/api';
import {
  RESOURCE_GROUPS,
  collectPages,
  formatAmount,
  formatFactorString,
  missingGroups,
  normaliseQuarter,
  quartersOf,
  refusalOf,
  regionsOf,
  workedExamplePositions,
  type ListPage,
  type ResourceIndexValue,
} from './resourceIndexApi';

function idx(region: string, quarter: string, group: ResourceIndexValue['resource_group']): ResourceIndexValue {
  return {
    id: `${region}-${quarter}-${group}`,
    region_code: region,
    quarter,
    resource_group: group,
    index_value: '1.25',
    source: '',
    is_sample: false,
    created_at: '',
    updated_at: '',
  };
}

describe('normaliseQuarter', () => {
  it('accepts and upper-cases a year and quarter', () => {
    expect(normaliseQuarter('2026-Q1')).toBe('2026-Q1');
    expect(normaliseQuarter(' 2025-q4 ')).toBe('2025-Q4');
  });
  it('rejects anything else', () => {
    expect(normaliseQuarter('2026-Q5')).toBeNull();
    expect(normaliseQuarter('2026-01')).toBeNull();
    expect(normaliseQuarter('')).toBeNull();
    expect(normaliseQuarter(null)).toBeNull();
  });
});

describe('regions, quarters and the missing-index pre-check', () => {
  const data = [
    idx('RU-SPE', '2026-Q1', 'labor'),
    idx('RU-MOW', '2025-Q4', 'labor'),
    idx('RU-MOW', '2026-Q1', 'labor'),
    idx('RU-MOW', '2026-Q1', 'material'),
  ];

  it('lists regions sorted and quarters newest first', () => {
    expect(regionsOf(data)).toEqual(['RU-MOW', 'RU-SPE']);
    expect(quartersOf(data, 'RU-MOW')).toEqual(['2026-Q1', '2025-Q4']);
    expect(quartersOf(data, 'RU-XXX')).toEqual([]);
  });

  it('names the groups with no index for exactly that region and quarter', () => {
    expect(missingGroups(data, 'RU-MOW', '2026-Q1')).toEqual(['machine', 'operator_wages']);
    // Another quarter of the same region does not count.
    expect(missingGroups(data, 'RU-MOW', '2025-Q4')).toEqual(['machine', 'operator_wages', 'material']);
    // Another region's index for the same quarter does not count either.
    expect(missingGroups(data, 'RU-SPE', '2026-Q1')).toEqual(['machine', 'operator_wages', 'material']);
  });

  it('keeps the four groups in smeta order', () => {
    expect(RESOURCE_GROUPS).toEqual(['labor', 'machine', 'operator_wages', 'material']);
  });
});

describe('formatAmount', () => {
  it('groups thousands and keeps every digit', () => {
    expect(formatAmount('58242.70')).toBe('58 242.70');
    expect(formatAmount('1234567.005')).toBe('1 234 567.005');
    expect(formatAmount('999.99')).toBe('999.99');
    expect(formatAmount('0.00')).toBe('0.00');
  });
  it('handles a sign, an integer and blanks', () => {
    expect(formatAmount('-12500.00')).toBe('-12 500.00');
    expect(formatAmount('16400')).toBe('16 400');
    expect(formatAmount('')).toBe('');
    expect(formatAmount(null)).toBe('');
  });
});

describe('formatFactorString', () => {
  it('trims trailing zeros only after a decimal point', () => {
    expect(formatFactorString('1.250000')).toBe('1.25');
    expect(formatFactorString('103.0000')).toBe('103');
    expect(formatFactorString('22.0')).toBe('22');
    expect(formatFactorString('100')).toBe('100');
    expect(formatFactorString('0.000000')).toBe('0');
  });
});

describe('refusalOf', () => {
  it('reads the structured 422 the server sends for a missing index', () => {
    const err = new ApiError(422, 'Unprocessable', {
      detail: {
        code: 'missing_index',
        message: 'no index',
        groups: ['material'],
        region_code: 'RU-MOW',
        quarter: '2026-Q1',
      },
    });
    const r = refusalOf(err);
    expect(r).not.toBeNull();
    expect(r!.code).toBe('missing_index');
    expect(r!.groups).toEqual(['material']);
    expect(r!.region_code).toBe('RU-MOW');
  });

  it('reads the positions a machine without an operator line was refused for', () => {
    const err = new ApiError(422, 'Unprocessable', {
      detail: { code: 'missing_operator_wages', message: 'no operator', positions: ['1', '4.2'] },
    });
    const r = refusalOf(err);
    expect(r).not.toBeNull();
    expect(r!.code).toBe('missing_operator_wages');
    expect(r!.positions).toEqual(['1', '4.2']);
  });

  it('ignores other failures', () => {
    expect(refusalOf(new ApiError(500, 'Server', { detail: { code: 'x' } }))).toBeNull();
    expect(refusalOf(new ApiError(422, 'Unprocessable', { detail: [{ loc: ['body'], msg: 'bad' }] }))).toBeNull();
    expect(refusalOf(new ApiError(422, 'Unprocessable', { detail: 'plain' }))).toBeNull();
    expect(refusalOf(new Error('boom'))).toBeNull();
  });
});

describe('workedExamplePositions', () => {
  it('carries a machine operator line and the chosen work types', () => {
    const labels = {
      concreteBlinding: 'cb',
      handExcavation: 'he',
      workersGrade35: 'w35',
      workersGrade2: 'w2',
      concretePump: 'pump',
      pumpOperator: 'op',
      concrete: 'c',
      sand: 's',
      gravel: 'g',
      manHour: 'mh',
      machineHour: 'mch',
    };
    const positions = workedExamplePositions('a', 'b', labels);
    expect(positions.map((p) => p.description)).toEqual(['cb', 'he']);
    expect(positions[0]!.resources.map((r) => r.name)).toEqual(['w35', 'pump', 'op', 'c']);
    expect(positions.map((p) => p.work_type)).toEqual(['a', 'b']);
    expect(positions[0]!.resources.map((r) => r.kind)).toEqual(['labor', 'machine', 'operator', 'material']);
  });
});

describe('collectPages', () => {
  it('reads every page until the total, not just the first', async () => {
    const pages: Record<number, ListPage<string>> = {
      0: { items: ['a', 'b'], total: 5, offset: 0, limit: 2 },
      2: { items: ['c', 'd'], total: 5, offset: 2, limit: 2 },
      4: { items: ['e'], total: 5, offset: 4, limit: 2 },
    };
    const fetchPage = vi.fn(async (offset: number) => pages[offset]);
    expect(await collectPages(fetchPage)).toEqual(['a', 'b', 'c', 'd', 'e']);
    expect(fetchPage.mock.calls.map((c) => c[0])).toEqual([0, 2, 4]);
  });

  it('stops on an empty page even when the total says there is more', async () => {
    const fetchPage = vi.fn(async (offset: number): Promise<ListPage<string>> =>
      offset === 0 ? { items: ['a'], total: 3, offset: 0, limit: 1 } : { items: [], total: 3, offset, limit: 1 },
    );
    expect(await collectPages(fetchPage)).toEqual(['a']);
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
});
