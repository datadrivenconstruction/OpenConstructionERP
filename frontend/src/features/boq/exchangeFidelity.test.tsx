// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Exchange report: the filter keeps what the reader asked for, the kind list
// is ordered by frequency, the export headers are read back, and the report
// view counts by severity, narrows by a severity click and offers the
// download only for a stored report.

import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  fetchWithAuth: vi.fn(),
}));

import type { FidelityItem, FidelityReport } from './exchangeFidelityApi';
import { reportFromHeaders } from './exchangeFidelityApi';
import {
  EMPTY_FILTER,
  fieldLabel,
  filterFidelityItems,
  kindLabel,
  kindsInReport,
  needsAttention,
} from './exchangeFidelityText';
import { FidelityReportView } from './FidelityReportView';

const t = (_key: string, opts?: Record<string, unknown>) => String(opts?.defaultValue ?? _key);

function item(over: Partial<FidelityItem>): FidelityItem {
  return {
    severity: 'warning',
    kind: 'truncated_text',
    field: 'unit',
    position_ref: '01.0010',
    position_id: null,
    original: 'pallets',
    written: 'pall',
    count: 1,
    detail: '',
    params: {},
    ...over,
  };
}

function report(items: FidelityItem[], id: string | null = 'r1'): FidelityReport {
  const by_severity = { error: 0, warning: 0, info: 0 };
  const by_kind: Record<string, number> = {};
  for (const it of items) {
    by_severity[it.severity] += 1;
    by_kind[it.kind] = (by_kind[it.kind] ?? 0) + 1;
  }
  return {
    id,
    direction: 'export',
    format_id: 'gaeb_xml',
    variant: 'x83',
    roundtrip: true,
    summary: { total: items.length, by_severity, by_kind, critical: by_severity.error, lossless: items.length === 0 },
    items,
  };
}

const ITEMS = [
  item({}),
  item({ severity: 'error', kind: 'value_out_of_range', field: 'quantity', position_ref: '02.0010', original: '-5', written: '0' }),
  item({ severity: 'info', kind: 'rounded_value', field: 'quantity', position_ref: '03.0010', original: '1.23456', written: '1.235' }),
  item({ severity: 'info', kind: 'rounded_value', field: 'unit_rate', position_ref: '03.0020' }),
];

describe('filterFidelityItems', () => {
  it('narrows by severity, kind and text in position, field or values', () => {
    expect(filterFidelityItems(ITEMS, { ...EMPTY_FILTER, severity: 'info' })).toHaveLength(2);
    expect(filterFidelityItems(ITEMS, { ...EMPTY_FILTER, kind: 'value_out_of_range' })).toHaveLength(1);
    expect(filterFidelityItems(ITEMS, { ...EMPTY_FILTER, query: '1.235' })).toHaveLength(1);
    expect(filterFidelityItems(ITEMS, { ...EMPTY_FILTER, query: '02.00' })[0]!.kind).toBe('value_out_of_range');
    expect(filterFidelityItems(ITEMS, EMPTY_FILTER)).toHaveLength(4);
  });

  it('lists kinds most frequent first and flags reports with errors or warnings', () => {
    expect(kindsInReport(report(ITEMS))[0]).toBe('rounded_value');
    expect(needsAttention(report(ITEMS).summary)).toBe(true);
    expect(needsAttention(report([item({ severity: 'info' })]).summary)).toBe(false);
    expect(needsAttention(null)).toBe(false);
  });

  it('words known codes and shows unknown ones as they came', () => {
    expect(kindLabel(t, 'markup_not_representable')).toBe('Markup not representable');
    expect(kindLabel(t, 'something_new')).toBe('something_new');
    expect(fieldLabel(t, 'CtlgAssign')).toBe('CtlgAssign');
    expect(fieldLabel(t, 'unit_rate')).toBe('Unit rate');
  });
});

describe('reportFromHeaders', () => {
  it('reads the report id and the counts of an export response', () => {
    const headers = new Headers({ 'X-Exchange-Report-Id': 'abc', 'X-Exchange-Fidelity': '1,2,3' });
    expect(reportFromHeaders(headers)).toEqual({ id: 'abc', errors: 1, warnings: 2, notes: 3 });
    expect(reportFromHeaders(new Headers())).toBeNull();
  });
});

describe('FidelityReportView', () => {
  it('says so when nothing was lost', () => {
    render(<FidelityReportView report={report([])} boqId="b1" />);
    expect(screen.getByText(/Nothing was lost/)).toBeInTheDocument();
  });

  it('counts by severity, narrows on a severity click, and shows the round-trip badge', () => {
    render(<FidelityReportView report={report(ITEMS)} boqId="b1" />);
    expect(screen.getByText('Round trip checked')).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(5);
    fireEvent.click(screen.getByRole('button', { name: /Critical: 1/ }));
    expect(screen.getAllByRole('row')).toHaveLength(2);
    expect(screen.getByText('02.0010')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'CSV' })).toBeInTheDocument();
  });

  it('offers no download for a report that is not stored', () => {
    render(<FidelityReportView report={report(ITEMS, null)} boqId="b1" />);
    expect(screen.queryByRole('button', { name: 'CSV' })).not.toBeInTheDocument();
  });
});
