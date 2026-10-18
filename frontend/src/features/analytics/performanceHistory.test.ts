// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import {
  NULL_GROUP_KEY,
  buildCompareMatrix,
  drillDimensions,
  matrixToCsv,
  sortTableRows,
  type PerformanceCompareResponse,
  type PerformanceGroup,
  type PerformanceTableRow,
} from './performance';
import { prettyUnit } from './performanceFormat';

const byName = (a: string, b: string) => a.localeCompare(b);

function row(name: string, value: string | null): PerformanceTableRow {
  return {
    projectId: name,
    name,
    row:
      value === null
        ? null
        : { project_id: name, value, numerator: null, denominator: null, records: 1, unavailable_reason: null },
  };
}

function group(dimensions: Record<string, string | null>, values: Record<string, string>): PerformanceGroup {
  return {
    key: Object.values(dimensions).join('|'),
    dimensions,
    rows: Object.entries(values).map(([project_id, value]) => ({
      project_id,
      value,
      numerator: null,
      denominator: null,
      records: 1,
      unavailable_reason: null,
    })),
    benchmark: {
      weighted: '1.6',
      weighted_unavailable_reason: null,
      median: '1.75',
      p25: '1.5',
      p75: '2',
      min: '1.5',
      max: '2',
    },
    evidence: { projects_with_data: 2, projects_with_value: 2, records: 2 },
    coverage: '1',
    headline: '1.6',
  };
}

describe('sortTableRows', () => {
  const rows = [row('B', '1.5'), row('A', null), row('C', '2'), row('D', '1.5')];

  it('sorts by value either way and always puts a missing value last', () => {
    expect(sortTableRows(rows, 'value_desc', byName).map((r) => r.name)).toEqual(['C', 'B', 'D', 'A']);
    expect(sortTableRows(rows, 'value_asc', byName).map((r) => r.name)).toEqual(['B', 'D', 'C', 'A']);
  });

  it('sorts by name and leaves the input untouched', () => {
    expect(sortTableRows(rows, 'name', byName).map((r) => r.name)).toEqual(['A', 'B', 'C', 'D']);
    expect(rows.map((r) => r.name)).toEqual(['B', 'A', 'C', 'D']);
  });
});

describe('drillDimensions', () => {
  it('asks for the group value plus every unit and currency converted into it', () => {
    const g = group({ currency: 'EUR', unit: 'm2' }, {});
    const dims = drillDimensions(g, {
      project_id: 'a',
      value: '1',
      numerator: null,
      denominator: null,
      records: 3,
      unavailable_reason: null,
      converted_from: ['ft2'],
      converted_from_currency: ['USD'],
    });
    expect(dims).toEqual({ currency: ['EUR', 'USD'], unit: ['m2', 'ft2'] });
  });

  it('turns the null group key back into a null to match', () => {
    const g = group({ 'classification.din276': NULL_GROUP_KEY, unit: 'm2' }, {});
    const dims = drillDimensions(g, {
      project_id: 'a',
      value: '1',
      numerator: null,
      denominator: null,
      records: 1,
      unavailable_reason: null,
    });
    expect(dims['classification.din276']).toEqual([null]);
  });
});

describe('buildCompareMatrix', () => {
  const data: PerformanceCompareResponse = {
    projects_selected: 2,
    projects: [
      { project_id: 'a', name: 'Alpha', currency: 'EUR', client: 'Acme', region: null, status: 'completed' },
      { project_id: 'b', name: '=Bad', currency: 'EUR' },
    ],
    columns: [
      { kpi: 'labour_hours_per_installed_unit', aggregation: 'ratio', group: group({ unit: 'm2' }, { a: '2' }) },
      { kpi: 'approved_labour_hours', aggregation: 'sum', group: group({}, { a: '100', b: '308' }) },
    ],
  };
  const labels = {
    project: 'Project',
    client: 'Client',
    region: 'Region',
    status: 'Status',
    column: (c: { kpi: string }) => c.kpi,
    benchmark: 'Benchmark',
  };

  it('writes one line per project, a missing value as empty and never as 0, then the benchmarks', () => {
    const m = buildCompareMatrix(data, labels);
    expect(m[0]).toEqual(['Project', 'Client', 'Region', 'Status', 'labour_hours_per_installed_unit', 'approved_labour_hours']);
    expect(m[1]).toEqual(['Alpha', 'Acme', '', 'completed', 2, 100]);
    expect(m[2]).toEqual(['=Bad', '', '', '', null, 308]);
    expect(m[3]).toEqual(['Benchmark', '', '', '', 1.6, 1.6]);
  });

  it('defuses a project name a spreadsheet would run as a formula', () => {
    const csv = matrixToCsv(buildCompareMatrix(data, labels));
    expect(csv.split('\r\n')[2]).toBe("'=Bad,,,,,308");
  });
});

describe('prettyUnit', () => {
  it('raises the exponent on each side of a compound unit', () => {
    expect(prettyUnit('h/m2')).toBe('h/m²');
    expect(prettyUnit('EUR/m3')).toBe('EUR/m³');
    expect(prettyUnit('pcs/h')).toBe('pcs/h');
    expect(prettyUnit(null)).toBe('');
  });
});
