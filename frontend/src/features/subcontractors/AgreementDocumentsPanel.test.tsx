// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the agreement documents panel and the statement dialog.
// The panel shows the gaps against the required list before anyone hits a
// refusal, and an upload carries the role and dates the person picked.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    listAgreementDocuments: vi.fn(),
    getRequiredDocumentStatus: vi.fn(),
    getPayAppStatement: vi.fn(),
  };
});

import { AgreementDocumentsPanel } from './AgreementDocumentsPanel';
import { PayAppStatementDialog } from './PayAppStatementDialog';
import * as api from './api';

const agreement = { id: 'ag-1', title: 'Concrete works' } as api.Agreement;
const fetchMock = vi.fn();

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.mocked(api.listAgreementDocuments).mockResolvedValue([]);
  vi.mocked(api.getRequiredDocumentStatus).mockResolvedValue({
    agreement_id: 'ag-1',
    enforcement: 'warn',
    required: [{ role: 'safety_plan', signed: false }],
    gaps: [{ role: 'safety_plan', state: 'missing' }],
  });
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('AgreementDocumentsPanel', () => {
  it('lists a required document that is missing', async () => {
    wrap(<AgreementDocumentsPanel agreement={agreement} />);
    const gaps = await screen.findByTestId('required-gaps');
    expect(gaps.textContent).toContain('safety plan');
  });

  it('uploads with the role and dates picked', async () => {
    wrap(<AgreementDocumentsPanel agreement={agreement} />);
    fireEvent.change(screen.getByTestId('doc-role'), { target: { value: 'insurance' } });
    const file = new File(['%PDF-1.4'], 'cert.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByTestId('doc-file'), { target: { files: [file] } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/agreements/ag-1/documents');
    const body = (init as RequestInit).body as FormData;
    expect(body.get('doc_role')).toBe('insurance');
    expect((body.get('file') as File).name).toBe('cert.pdf');
  });
});

describe('PayAppStatementDialog', () => {
  it('shows the worked example summary and the rule findings', async () => {
    vi.mocked(api.getPayAppStatement).mockResolvedValue({
      payment_application_id: 'pa-4',
      agreement_id: 'ag-1',
      application_number: 'PA-0004',
      status: 'submitted',
      period_start: null,
      period_end: null,
      currency: 'USD',
      override_reason: null,
      lines: [],
      summary: {
        original_contract_sum: '95000', change_orders: '5000', contract_sum_to_date: '100000',
        scheduled_total: '100000', previous_completed: '40000', this_period: '35000',
        completed_to_date: '75000', percent_complete: '75', retention_percent: '10',
        retention_held: '7500', previous_certified: '36000', current_due: '31500',
        balance_to_finish: '25000', previous_gross_billed: '40000', this_gross: '35000',
      },
      findings: [
        { rule_id: 'subcontract.pay_app_over_complete', severity: 'warning', passed: false, message: 'Steel is 107.50 percent billed' },
      ],
    });
    wrap(<PayAppStatementDialog payment={{ id: 'pa-4', application_number: 'PA-0004' } as api.PaymentApplication} onClose={() => {}} />);
    const summary = await screen.findByTestId('statement-summary');
    expect(summary.textContent).toContain('31,500');
    expect(summary.textContent).toContain('7,500');
    expect(screen.getByTestId('statement-findings').textContent).toContain('107.50');
  });
});
