// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ColDef } from 'ag-grid-community';
import { applyColumnPrefs, boqColumnPref } from '../grid/columnPrefs';
import { BOQColumnPicker } from '../BOQColumnPicker';

const defs = (): ColDef[] => [
  { colId: '_checkbox' },
  { field: 'ordinal' },
  { field: 'description' },
  { field: 'classification' },
  { field: 'unit' },
  { field: 'quantity' },
  { field: 'unit_rate' },
  { field: 'net_cost_rate', hide: true },
  { field: 'total' },
  { colId: 'resource_split_labor', hide: true },
  { colId: 'custom_phase' },
  { field: '_actions' },
];
const ids = (d: ColDef[]) => d.map((c) => c.colId ?? c.field);

beforeEach(() => {
  localStorage.clear();
  boqColumnPref.reset();
});

describe('applyColumnPrefs', () => {
  it('returns the same list when nothing is chosen', () => {
    const d = defs();
    expect(applyColumnPrefs(d, boqColumnPref.read())).toBe(d);
  });

  it('reorders only the movable columns and leaves the fixed slots alone', () => {
    const out = applyColumnPrefs(defs(), { visible: {}, order: ['total', 'custom_phase', 'quantity'] });
    expect(ids(out)).toEqual([
      '_checkbox', 'ordinal', 'description',
      'total', 'custom_phase', 'quantity', 'classification', 'unit', 'unit_rate',
      'resource_split_labor', 'net_cost_rate', '_actions',
    ]);
  });

  it('shows a column hidden by default and hides one shown by default', () => {
    const out = applyColumnPrefs(defs(), { visible: { net_cost_rate: true, classification: false }, order: [] });
    expect(out.find((c) => c.field === 'net_cost_rate')!.hide).toBe(false);
    expect(out.find((c) => c.field === 'classification')!.hide).toBe(true);
    expect(out.find((c) => c.field === 'unit_rate')!.hide).toBeUndefined();
  });

  it('never lets a stored value hide quantity, unit or total, or touch unknown ids', () => {
    localStorage.setItem('oe_boq_columns_v1', JSON.stringify({ visible: { total: false, ordinal: false, x: true }, order: ['bogus', 'unit'] }));
    const stop = boqColumnPref.subscribe(() => {});
    window.dispatchEvent(new StorageEvent('storage', { key: 'oe_boq_columns_v1' }));
    stop();
    const p = boqColumnPref.read();
    expect(p.visible).toEqual({});
    expect(p.order).toEqual(['unit']);
  });
});

describe('<BOQColumnPicker>', () => {
  it('hides a column, moves another and resets to the default', () => {
    render(<BOQColumnPicker customColumns={[{ name: 'phase', display_name: 'Phase' }]} />);
    expect(boqColumnPref.read().visible).toEqual({});
    fireEvent.click(screen.getByTestId('boq-column-picker-button'));

    fireEvent.click(screen.getByRole('button', { name: 'Show Code' }));
    expect(boqColumnPref.read().visible).toEqual({ classification: false });
    fireEvent.click(screen.getByRole('button', { name: 'Show Sale Rate' }));
    expect(boqColumnPref.read().visible).toEqual({ classification: false, sale_rate: true });

    fireEvent.click(screen.getByRole('button', { name: 'Move Phase left' }));
    const order = boqColumnPref.read().order;
    expect(order.indexOf('custom_phase')).toBe(order.length - 2);

    expect((screen.getByRole('button', { name: 'Show Qty' }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Reset to default' }));
    expect(boqColumnPref.read()).toEqual({ visible: {}, order: [] });
  });

  it('puts a column back to the default without keeping a redundant entry', () => {
    render(<BOQColumnPicker />);
    fireEvent.click(screen.getByTestId('boq-column-picker-button'));
    fireEvent.click(screen.getByRole('button', { name: 'Show Code' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show Code' }));
    expect(boqColumnPref.read().visible).toEqual({});
  });
});
