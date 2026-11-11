// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #559 — input tax on assembly components is offered only for a project
// that switched it on; with the switch off the editor looks and behaves as before.

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ComponentRow } from '../AssemblyEditorPage';
import { ComponentTaxFields } from '../ComponentTaxFields';
import { assemblyTaxTotals, componentTaxSplit, isAssemblyApproved } from '../componentTax';
import type { AssemblyComponent } from '../api';

function makeComponent(overrides: Partial<AssemblyComponent> = {}): AssemblyComponent {
  return {
    id: 'cmp-1',
    assembly_id: 'asm-1',
    cost_item_id: null,
    catalog_resource_id: null,
    description: 'Cement',
    resource_type: 'material',
    factor: 1,
    quantity: 1,
    quantity_formula: null,
    unit: 't',
    unit_cost: 1000,
    total: 1180,
    sort_order: 0,
    metadata: {},
    ...overrides,
  };
}

function renderRow(component: AssemblyComponent, taxEnabled: boolean, onUpdate = vi.fn()) {
  render(
    <table>
      <tbody>
        <ComponentRow
          component={component}
          isDragOver={false}
          onDragStart={vi.fn()}
          onDragOver={vi.fn()}
          onDragEnd={vi.fn()}
          onDragLeave={vi.fn()}
          onUpdate={onUpdate}
          onDelete={vi.fn()}
          fmt={(n: number) => n.toFixed(2)}
          taxEnabled={taxEnabled}
        />
      </tbody>
    </table>,
  );
  return onUpdate;
}

const SPLIT = {
  status: 'taxable',
  rate_pct: '18',
  treatment: 'cost_incorporated',
  net: '1000.00',
  tax: '180.00',
  tax_in_cost: '180.00',
  tax_recoverable: '0.00',
  cost: '1180.00',
  gross_outlay: '1180.00',
};

function openDetails() {
  const toggle = document.querySelector('button[aria-expanded]') as HTMLButtonElement;
  fireEvent.click(toggle);
}

describe('component tax columns in the editor', () => {
  it('shows no tax controls and no split while the project switch is off', () => {
    renderRow(makeComponent({ metadata: { tax: SPLIT } }), false);
    openDetails();
    expect(screen.queryByTestId('tax-status')).toBeNull();
    expect(screen.queryByTestId('component-tax-split')).toBeNull();
  });

  it('shows the net / tax split under the total and the tax fields in the details when on', () => {
    renderRow(makeComponent({ metadata: { tax: SPLIT } }), true);
    expect(screen.getByTestId('component-tax-split').textContent).toContain('1000.00');
    expect(screen.getByTestId('component-tax-split').textContent).toContain('180.00');
    openDetails();
    expect(screen.getByTestId('tax-status')).toBeTruthy();
    expect(screen.getByTestId('tax-rate')).toBeTruthy();
    expect(screen.getByTestId('tax-code')).toBeTruthy();
    expect(screen.getByTestId('tax-treatment')).toBeTruthy();
    expect(screen.getByTestId('tax-inclusive')).toBeTruthy();
  });

  it('an unclassified component has no split line even with the switch on', () => {
    renderRow(makeComponent(), true);
    expect(screen.queryByTestId('component-tax-split')).toBeNull();
  });

  it('saves a changed status, a rate and the inclusive flag as a patch', () => {
    const onUpdate = renderRow(makeComponent(), true);
    openDetails();
    fireEvent.change(screen.getByTestId('tax-status'), { target: { value: 'taxable' } });
    expect(onUpdate).toHaveBeenLastCalledWith({ tax_status: 'taxable' });
    const rate = screen.getByTestId('tax-rate');
    fireEvent.change(rate, { target: { value: '18' } });
    fireEvent.blur(rate);
    expect(onUpdate).toHaveBeenLastCalledWith({ tax_rate: '18' });
    fireEvent.click(screen.getByTestId('tax-inclusive'));
    expect(onUpdate).toHaveBeenLastCalledWith({ price_includes_tax: true });
  });
});

describe('ComponentTaxFields', () => {
  it('clears a field to null and treats the empty treatment as the project default', () => {
    const onChange = vi.fn();
    render(
      <ComponentTaxFields
        profile={{ tax_status: 'exempt', tax_rate: '5', input_tax_treatment: 'recoverable' }}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByTestId('tax-status'), { target: { value: '' } });
    expect(onChange).toHaveBeenLastCalledWith({ tax_status: null });
    fireEvent.change(screen.getByTestId('tax-treatment'), { target: { value: '' } });
    expect(onChange).toHaveBeenLastCalledWith({ input_tax_treatment: null });
    const rate = screen.getByTestId('tax-rate');
    fireEvent.change(rate, { target: { value: '' } });
    fireEvent.blur(rate);
    expect(onChange).toHaveBeenLastCalledWith({ tax_rate: null });
  });
});

describe('reading what the server stored', () => {
  it('returns the split only when it is complete', () => {
    expect(componentTaxSplit(makeComponent({ metadata: { tax: SPLIT } }))?.tax).toBe('180.00');
    expect(componentTaxSplit(makeComponent({ metadata: { tax: { status: 'taxable' } } }))).toBeNull();
    expect(componentTaxSplit(makeComponent())).toBeNull();
  });

  it('reads assembly totals and the approved state', () => {
    expect(assemblyTaxTotals({ metadata: { tax_totals: { net: '1', cost: '2' } } })?.cost).toBe('2');
    expect(assemblyTaxTotals({ metadata: {} })).toBeNull();
    expect(isAssemblyApproved({ metadata: { status: 'Approved' } })).toBe(true);
    expect(isAssemblyApproved({ metadata: { approved: true } })).toBe(true);
    expect(isAssemblyApproved({ metadata: { status: 'draft' } })).toBe(false);
    expect(isAssemblyApproved({})).toBe(false);
  });
});
