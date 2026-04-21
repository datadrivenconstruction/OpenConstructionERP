import { describe, it, expect } from 'vitest';
import {
  computeGroupSummaries,
  formatGroupTotal,
  ANNOTATION_TYPES,
} from '../lib/takeoff-groups';
import type { Measurement } from '../lib/takeoff-types';

const GROUP_COLORS: Record<string, string> = {
  General: '#3B82F6',
  Structural: '#EF4444',
  Electrical: '#F59E0B',
};

function m(partial: Partial<Measurement>): Measurement {
  return {
    id: partial.id ?? Math.random().toString(36).slice(2),
    type: partial.type ?? 'distance',
    points: partial.points ?? [],
    value: partial.value ?? 0,
    unit: partial.unit ?? 'm',
    label: partial.label ?? '',
    annotation: partial.annotation ?? '',
    page: partial.page ?? 1,
    group: partial.group ?? 'General',
    ...partial,
  };
}

describe('computeGroupSummaries', () => {
  it('returns one row per group present', () => {
    const measurements = [
      m({ group: 'General', value: 1 }),
      m({ group: 'Structural', value: 2 }),
    ];
    const result = computeGroupSummaries(measurements, GROUP_COLORS);
    expect(result).toHaveLength(2);
    expect(result.map((r) => r.name).sort()).toEqual(['General', 'Structural']);
  });

  it('sums total value per group', () => {
    const measurements = [
      m({ group: 'Structural', value: 5, unit: 'm' }),
      m({ group: 'Structural', value: 10, unit: 'm' }),
      m({ group: 'Structural', value: 3, unit: 'm' }),
    ];
    const result = computeGroupSummaries(measurements, GROUP_COLORS);
    expect(result).toHaveLength(1);
    expect(result[0]!.total).toBe(18);
    expect(result[0]!.count).toBe(3);
  });

  it('applies the color map', () => {
    const measurements = [m({ group: 'Structural', value: 1 })];
    const result = computeGroupSummaries(measurements, GROUP_COLORS);
    expect(result[0]!.color).toBe('#EF4444');
  });

  it('falls back to default color for unknown groups', () => {
    const measurements = [m({ group: 'CustomGroup', value: 1 })];
    const result = computeGroupSummaries(measurements, GROUP_COLORS, '#999999');
    expect(result[0]!.color).toBe('#999999');
  });

  it('excludes annotation types from total but counts them', () => {
    const measurements = [
      m({ group: 'General', value: 10, type: 'distance' }),
      m({ group: 'General', value: 5, type: 'cloud' }), // annotation
      m({ group: 'General', value: 2, type: 'rectangle' }), // annotation
    ];
    const result = computeGroupSummaries(measurements, GROUP_COLORS);
    expect(result).toHaveLength(1);
    expect(result[0]!.count).toBe(3);
    // Only the distance (10) contributes to total; cloud/rectangle are annotations.
    expect(result[0]!.total).toBe(10);
  });

  it('picks the most common unit', () => {
    const measurements = [
      m({ group: 'General', value: 1, unit: 'm' }),
      m({ group: 'General', value: 1, unit: 'm' }),
      m({ group: 'General', value: 1, unit: 'm2' }),
    ];
    const result = computeGroupSummaries(measurements, GROUP_COLORS);
    expect(result[0]!.unit).toBe('m');
  });

  it('defaults group name to General when blank', () => {
    const measurements = [m({ group: '', value: 1 })];
    const result = computeGroupSummaries(measurements, GROUP_COLORS);
    expect(result[0]!.name).toBe('General');
  });

  it('returns empty array for no measurements', () => {
    expect(computeGroupSummaries([], GROUP_COLORS)).toEqual([]);
  });

  it('returns summaries in stable (alphabetical) order', () => {
    const measurements = [
      m({ group: 'Structural', value: 1 }),
      m({ group: 'Electrical', value: 1 }),
      m({ group: 'General', value: 1 }),
    ];
    const result = computeGroupSummaries(measurements, GROUP_COLORS);
    expect(result.map((r) => r.name)).toEqual([
      'Electrical',
      'General',
      'Structural',
    ]);
  });
});

describe('formatGroupTotal', () => {
  it('formats small numbers with 3 decimals', () => {
    expect(formatGroupTotal(0.123, 'm')).toBe('0.123 m');
  });

  it('formats medium numbers with 2 decimals', () => {
    expect(formatGroupTotal(12.345, 'm')).toBe('12.35 m');
  });

  it('formats large numbers with 1 decimal', () => {
    expect(formatGroupTotal(1234.56, 'm')).toBe('1234.6 m');
  });

  it('omits unit when empty', () => {
    expect(formatGroupTotal(5, '')).toBe('5');
  });
});

describe('ANNOTATION_TYPES', () => {
  it('includes all decorative tool types', () => {
    expect(ANNOTATION_TYPES.has('cloud')).toBe(true);
    expect(ANNOTATION_TYPES.has('arrow')).toBe(true);
    expect(ANNOTATION_TYPES.has('text')).toBe(true);
    expect(ANNOTATION_TYPES.has('rectangle')).toBe(true);
    expect(ANNOTATION_TYPES.has('highlight')).toBe(true);
  });

  it('excludes measurement tool types', () => {
    expect(ANNOTATION_TYPES.has('distance')).toBe(false);
    expect(ANNOTATION_TYPES.has('area')).toBe(false);
    expect(ANNOTATION_TYPES.has('volume')).toBe(false);
  });
});
