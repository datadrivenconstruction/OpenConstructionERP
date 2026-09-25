// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for what <LienWaiverPanel> sends with an upload.
//
// A waiver releases work up to a date, and the GC claim rollup compares that
// date with the pay application's period end. So the upload has to carry the
// date a person entered, and a W-9 / W-8 tax form, which releases nothing,
// must never carry one.
//
// The payment release gate counts a waiver only when it is filed against the
// pay application with an amount that reaches its net. So a payment waiver
// picked for a pay application has to carry its id, the amount and the pay
// application's currency, and a tax form none of them.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return {
    ...actual,
    apiGet: vi.fn().mockResolvedValue([]),
    apiDelete: vi.fn(),
    getAuthToken: () => 'token',
  };
});

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

import { LienWaiverPanel } from './LienWaiverPanel';
import { apiGet } from '@/shared/lib/api';
import type { PaymentApplication } from './api';

const fetchMock = vi.fn();

let payApps: PaymentApplication[] = [];

function payApp(over: Partial<PaymentApplication> = {}): PaymentApplication {
  return {
    id: 'pa-1',
    agreement_id: 'ag-1',
    application_number: 'PA-1',
    period_start: '2026-04-01',
    period_end: '2026-04-30',
    gross_amount: '2000.00',
    retention_amount: '200.00',
    net_amount: '1800.00',
    currency: 'USD',
    status: 'finance_approved',
    ...over,
  } as PaymentApplication;
}

// The W-9 / W-8 cases below need a US subcontractor: the forms are offered
// nowhere else.
function renderPanel(country: string | null = 'US') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <LienWaiverPanel subcontractorId="sub-1" country={country} />
    </QueryClientProvider>,
  );
}

function sentForm(): FormData {
  const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
  return init.body as FormData;
}

function upload() {
  const file = new File(['%PDF-1.4'], 'waiver.pdf', { type: 'application/pdf' });
  fireEvent.change(screen.getByLabelText('Lien waiver file'), { target: { files: [file] } });
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
  payApps = [];
  // One agreement for the sub whenever the test has pay applications for it.
  vi.mocked(apiGet).mockImplementation(async (url: string) => {
    if (url.includes('/agreements/')) return payApps.length ? [{ id: 'ag-1' }] : [];
    if (url.includes('/payment-applications/')) return payApps;
    return [];
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LienWaiverPanel through-date', () => {
  it('sends the date the waiver releases work through', async () => {
    renderPanel();
    fireEvent.change(await screen.findByTestId('waiver-through-date'), { target: { value: '2026-04-30' } });
    upload();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentForm().get('through_date')).toBe('2026-04-30');
    expect(sentForm().get('waiver_type')).toBe('conditional_partial');
  });

  it('sends no through-date when none was entered', async () => {
    renderPanel();
    await screen.findByTestId('waiver-through-date');
    upload();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentForm().has('through_date')).toBe(false);
  });

  it('never attaches a through-date to a tax form', async () => {
    renderPanel();
    fireEvent.change(await screen.findByTestId('waiver-through-date'), { target: { value: '2026-04-30' } });
    fireEvent.change(screen.getByLabelText('Waiver type'), { target: { value: 'w9' } });
    expect(screen.queryByTestId('waiver-through-date')).toBeNull();
    upload();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentForm().has('through_date')).toBe(false);
  });
});

describe('LienWaiverPanel pay application', () => {
  it("files a payment waiver against the chosen pay application with its net, currency and period end", async () => {
    payApps = [payApp()];
    renderPanel();
    fireEvent.change(await screen.findByTestId('waiver-pay-app'), { target: { value: 'pa-1' } });
    expect((screen.getByTestId('waiver-amount') as HTMLInputElement).value).toBe('1800.00');
    expect((screen.getByTestId('waiver-through-date') as HTMLInputElement).value).toBe('2026-04-30');
    upload();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentForm().get('payment_application_id')).toBe('pa-1');
    expect(sentForm().get('amount')).toBe('1800.00');
    expect(sentForm().get('currency')).toBe('USD');
    expect(sentForm().get('through_date')).toBe('2026-04-30');
  });

  it('sends the amount as the person corrected it', async () => {
    payApps = [payApp()];
    renderPanel();
    fireEvent.change(await screen.findByTestId('waiver-pay-app'), { target: { value: 'pa-1' } });
    fireEvent.change(screen.getByTestId('waiver-amount'), { target: { value: '900' } });
    upload();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentForm().get('amount')).toBe('900');
  });

  it('offers no rejected pay application, since it is never paid', async () => {
    payApps = [payApp(), payApp({ id: 'pa-2', application_number: 'PA-2', status: 'rejected' })];
    renderPanel();
    const select = await screen.findByTestId('waiver-pay-app');
    const values = Array.from((select as HTMLSelectElement).options).map((o) => o.value);
    expect(values).toEqual(['', 'pa-1']);
  });

  it('sends no pay application with a waiver not tied to one', async () => {
    payApps = [payApp()];
    renderPanel();
    await screen.findByTestId('waiver-pay-app');
    upload();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentForm().has('payment_application_id')).toBe(false);
    expect(sentForm().has('amount')).toBe(false);
  });

  it('never ties a tax form to a pay application', async () => {
    payApps = [payApp()];
    renderPanel();
    fireEvent.change(await screen.findByTestId('waiver-pay-app'), { target: { value: 'pa-1' } });
    fireEvent.change(screen.getByLabelText('Waiver type'), { target: { value: 'w8' } });
    expect(screen.queryByTestId('waiver-pay-app')).toBeNull();
    upload();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentForm().has('payment_application_id')).toBe(false);
    expect(sentForm().has('amount')).toBe(false);
    expect(sentForm().has('currency')).toBe(false);
  });
});

describe('LienWaiverPanel outside the US', () => {
  it.each([['HR'], [null]])('offers no US tax form to a subcontractor in %s', async (country) => {
    renderPanel(country);
    const select = (await screen.findByLabelText('Waiver type')) as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(['conditional_partial', 'conditional_final', 'unconditional_partial', 'unconditional_final']);
    expect(screen.queryByText(/W-9/)).toBeNull();
  });
});
