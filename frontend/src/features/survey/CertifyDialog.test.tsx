// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Survey to payment, lessons 1 and 4 of the Riverside Yard course: the
 * certificate preview shows what would be billed before anything is written,
 * a locked certificate keeps Confirm off, and the hauled vs excavated panel
 * shows the 14.29 % difference over the 10 % threshold.
 */
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { HauledVsExcavated, MeasuredPreview } from './volumesApi';

const hauled = vi.fn();
vi.mock('./volumesApi', async (orig) => ({
  ...(await orig<typeof import('./volumesApi')>()),
  searchBoqPositions: vi.fn(async () => [
    { id: 'pos1', ordinal: '1.02', description: 'Bulk excavation', quantity: 1500, unit: 'm3' },
  ]),
  hauledVsExcavated: (...a: unknown[]) => hauled(...a),
}));

const { CertifyDialog } = await import('./CertifyDialog');
const { HauledVsExcavatedPanel } = await import('./HauledVsExcavatedPanel');

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const lesson1: MeasuredPreview = {
  boq_position_id: 'pos1',
  ordinal: '1.02',
  description: 'Bulk excavation',
  boq_quantity: '1500.0000',
  boq_unit: 'm3',
  quantity: '1470.000',
  unit: 'm3',
  quantity_kind: 'cut',
  contract: { id: 'c1', code: 'RY-SUB-EW-01', title: 'Earthworks subcontract', currency: 'EUR' },
  line: { id: 'l1', code: '1.02', description: 'Bulk excavation', unit: 'm3', quantity: '1500', unit_rate: '9.5', total_value: '14250' },
  claim: { id: 'pc1', number: 'PC-01', status: 'draft', currency: 'EUR', gross_amount: null, retention_amount: null, net_due: null },
  figures: {
    percent_to_date: '98.0000',
    capped: false,
    period_qty: '1470.0000',
    period_value: '13965.0000',
    prior_value: '0',
    cumulative_value: '13965.0000',
  },
  findings: [],
  can_commit: true,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('CertifyDialog', () => {
  it('previews the cut against the open certificate and commits only on confirm', async () => {
    const preview = vi.fn(async () => lesson1);
    const commit = vi.fn(async () => lesson1);
    wrap(
      <CertifyDialog
        open
        projectId="p1"
        source="V-001"
        amounts={{ cut: 1470, fill: 270, net: 1200, loose_cut: 1470 }}
        initialPositionId="pos1"
        preview={preview}
        commit={commit}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByTestId('certify-preview')).toBeTruthy();
    expect(preview).toHaveBeenCalledWith({ position_id: 'pos1', quantity: 'cut' });
    expect(screen.getByTestId('certify-period-value').textContent).toContain('13,965.00');
    expect(commit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('certify-kind-loose_cut'));
    await waitFor(() => expect(preview).toHaveBeenLastCalledWith({ position_id: 'pos1', quantity: 'loose_cut' }));
    // Confirm waits for the preview of the quantity now chosen.
    const confirm = screen.getByTestId('certify-confirm') as HTMLButtonElement;
    await waitFor(() => expect(confirm.disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect(commit).toHaveBeenCalledWith({ position_id: 'pos1', quantity: 'loose_cut' }));
  });

  it('keeps Confirm off when the certificate is locked', async () => {
    const locked: MeasuredPreview = {
      ...lesson1,
      claim: { ...lesson1.claim!, status: 'submitted' },
      findings: [
        {
          rule_id: 'MQ-003',
          severity: 'error',
          message: 'Certificate PC-01 is submitted: it can no longer change.',
          key: 'certificate_locked',
          params: { number: 'PC-01', status: 'submitted' },
        },
      ],
      can_commit: false,
    };
    wrap(
      <CertifyDialog
        open
        projectId="p1"
        source="V-001"
        amounts={{ cut: 1470 }}
        initialPositionId="pos1"
        preview={async () => locked}
        commit={vi.fn()}
        onClose={() => {}}
      />,
    );
    expect((await screen.findByTestId('certify-findings')).textContent).toContain('MQ-003');
    expect((screen.getByTestId('certify-confirm') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('HauledVsExcavatedPanel', () => {
  const bank: HauledVsExcavated = {
    target: 'volume',
    target_id: 'v1',
    code: 'V-001',
    name: 'Platform earthworks',
    excavated_m3: '1470.000',
    excavated_basis: 'bank_cut',
    swell_factor: '1',
    hauled_m3: '1680.000',
    tickets: 10,
    loads: 120,
    by_basis: [
      { basis: 'weighbridge', tickets: 3, loads: 32, hauled_m3: '448.000' },
      { basis: 'capacity', tickets: 7, loads: 88, hauled_m3: '1232.000' },
    ],
    difference_m3: '210.000',
    difference_pct: '14.29',
    threshold_pct: 10,
    within_threshold: false,
    findings: [{ rule_id: 'haul_variance.hauled_vs_excavated', severity: 'warning', message: '' }],
  };

  it('shows the difference and flags it over the threshold', async () => {
    hauled.mockResolvedValue(bank);
    wrap(<HauledVsExcavatedPanel projectId="p1" volumeId="v1" />);
    expect((await screen.findByTestId('haulvx-difference')).textContent).toContain('+14.29 %');
    expect(screen.getByTestId('haulvx-hauled').textContent).toContain('1,680.0');
    expect(hauled).toHaveBeenCalledWith('p1', { volume_id: 'v1' });
  });

  it('stays out of the way when no ticket is linked', async () => {
    hauled.mockResolvedValue({ ...bank, tickets: 0, by_basis: [], difference_pct: null, within_threshold: null });
    const { container } = wrap(<HauledVsExcavatedPanel projectId="p1" stockpileId="s1" />);
    await waitFor(() => expect(hauled).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="hauled-vs-excavated"]')).toBeNull();
  });
});
