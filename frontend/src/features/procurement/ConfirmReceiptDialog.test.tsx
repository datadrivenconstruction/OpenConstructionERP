// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The confirm dialog shows the certificate check before a delivery counts as
// received: a missing required certificate keeps the confirm button disabled,
// and the approval route and the incoming inspection start only when ticked.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import {
  ConfirmReceiptDialog,
  buildConfirmBody,
  certificateLabel,
  failingFindings,
  type ReceiptReadiness,
} from './ConfirmReceiptDialog';
import { changedRequirements } from './LineRequirements';

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      let s = String(opts?.defaultValue ?? key);
      for (const [k, v] of Object.entries(opts ?? {})) s = s.replace(`{{${k}}}`, String(v));
      return s;
    },
    i18n: { language: 'en' },
  }),
}));

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('@/features/finance/financeQueryKeys', () => ({ invalidateFinanceFigures: vi.fn() }));

const TYPES = [
  { code: 'en10204_3_1', family: 'en10204', rank: 3, label: 'EN 10204 type 3.1' },
  { code: 'en10204_2_2', family: 'en10204', rank: 2, label: 'EN 10204 type 2.2' },
];

function readiness(over: Partial<ReceiptReadiness> = {}): ReceiptReadiness {
  return {
    gr_id: 'gr-1',
    status: 'draft',
    can_confirm: false,
    validation: {
      status: 'errors',
      results: [
        {
          rule_id: 'procurement.receipt_certificate_present',
          severity: 'error',
          passed: false,
          message: 'Line 1 needs an EN 10204 type 3.1 certificate.',
          element_ref: '1',
          suggestion: null,
        },
      ],
    },
    approval_routes: [{ id: 'route-1', name: 'Site approval' }],
    inspection_due: true,
    inspection_lines: ['1 (Rebar B500B 12 mm)'],
    lines: [
      {
        gr_item_id: 'line-1',
        label: '1 (Rebar B500B 12 mm)',
        unit: 't',
        quantity_received: '4',
        batch_lot: 'H-20931',
        required_certificate_type: 'en10204_3_1',
        requires_inspection: true,
        certificates: [],
      },
    ],
    ...over,
  };
}

function mount(data: ReceiptReadiness) {
  apiGet.mockImplementation((url: string) =>
    Promise.resolve(url.includes('certificate-types') ? TYPES : data),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ConfirmReceiptDialog
        receipt={{ id: 'gr-1', gr_reference: 'LS-4711', po_number: 'PO-7', source: 'supplier_portal' }}
        projectId="p-1"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});

describe('ConfirmReceiptDialog helpers', () => {
  it('sends nothing to start unless it was ticked', () => {
    expect(buildConfirmBody({ startRoute: false, routeId: 'r', createInspection: false })).toEqual({
      start_approval_route: false,
      approval_route_id: null,
      create_inspection: false,
    });
    expect(buildConfirmBody({ startRoute: true, routeId: 'r', createInspection: true })).toEqual({
      start_approval_route: true,
      approval_route_id: 'r',
      create_inspection: true,
    });
  });

  it('names a type by the catalogue, or by its code when unknown', () => {
    expect(certificateLabel('en10204_3_1', TYPES)).toBe('EN 10204 type 3.1');
    expect(certificateLabel('custom_x', TYPES)).toBe('custom_x');
    expect(certificateLabel(null, TYPES)).toBe('');
  });

  it('lists errors before warnings and drops passed results', () => {
    const out = failingFindings([
      { rule_id: 'w', severity: 'warning', passed: false, message: 'w', element_ref: null, suggestion: null },
      { rule_id: 'ok', severity: 'error', passed: true, message: 'ok', element_ref: null, suggestion: null },
      { rule_id: 'e', severity: 'error', passed: false, message: 'e', element_ref: null, suggestion: null },
    ]);
    expect(out.map((f) => f.rule_id)).toEqual(['e', 'w']);
  });
});

describe('ConfirmReceiptDialog', () => {
  it('blocks the confirm while a required certificate is missing', async () => {
    mount(readiness());
    expect(await screen.findByText('Line 1 needs an EN 10204 type 3.1 certificate.')).toBeInTheDocument();
    expect(screen.getByTestId('gr-readiness-light').dataset.status).toBe('errors');
    expect(screen.getByText('Submitted by the supplier')).toBeInTheDocument();
    expect(screen.getByText('Order asks for EN 10204 type 3.1')).toBeInTheDocument();
    expect(screen.getByTestId('gr-confirm-submit')).toBeDisabled();
  });

  it('confirms with only what the person ticked', async () => {
    apiPost.mockResolvedValue({});
    mount(readiness({ can_confirm: true, validation: { status: 'passed', results: [] } }));
    const submit = await screen.findByTestId('gr-confirm-submit');
    await waitFor(() => expect(submit).not.toBeDisabled());
    // The due inspection is suggested; the route is not.
    expect(screen.getByTestId('gr-create-inspection')).toBeChecked();
    expect(screen.getByTestId('gr-start-route')).not.toBeChecked();
    fireEvent.click(screen.getByTestId('gr-start-route'));
    fireEvent.click(submit);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    expect(apiPost).toHaveBeenCalledWith('/v1/procurement/goods-receipts/gr-1/confirm/', {
      start_approval_route: true,
      approval_route_id: 'route-1',
      create_inspection: true,
    });
  });
});

describe('changedRequirements', () => {
  const base = [
    {
      id: 'a',
      description: 'Rebar',
      quantity: '10',
      unit: 't',
      unit_rate: '800',
      amount: '8000',
      boq_position_id: null,
      required_certificate_type: '',
      requires_inspection: false,
    },
  ];

  it('reports a line whose requirement changed and nothing else', () => {
    expect(changedRequirements(base, base)).toEqual([]);
    const edited = [{ ...base[0]!, required_certificate_type: 'en10204_3_1', requires_inspection: true }];
    expect(changedRequirements(edited, base)).toEqual([
      { id: 'a', required_certificate_type: 'en10204_3_1', requires_inspection: true },
    ]);
  });

  it('ignores a line that was not saved yet', () => {
    const added = [...base, { ...base[0]!, id: undefined, required_certificate_type: 'en10204_3_1' }];
    expect(changedRequirements(added, base)).toEqual([]);
  });
});
