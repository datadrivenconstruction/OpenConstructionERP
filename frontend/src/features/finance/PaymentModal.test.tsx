// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { webcrypto } from 'node:crypto';
import { PaymentModal } from './PaymentModal';
import { apiPost } from '@/shared/lib/api';

vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => {
      const labels: Record<string, string> = {
        'finance.payment.record': 'Record payment',
        'finance.payment.cashPaid': 'Cash paid',
        'finance.payment.gross': 'Gross settled',
      };
      return options?.defaultValue ?? labels[key] ?? key;
    },
    i18n: { language: 'en', resolvedLanguage: 'en' },
  }),
}));

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiPost: vi.fn(),
}));

const INVOICE_ID = 'b7e53ca8-1ad2-4cc3-8598-b91873d61920';

function postedKey(index: number) {
  const body = vi.mocked(apiPost).mock.calls[index]?.[1];
  return typeof body === 'object' && body !== null && 'idempotency_key' in body ? body.idempotency_key : undefined;
}

function open(total: string, withheld: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <PaymentModal open onClose={vi.fn()} invoiceId={INVOICE_ID} amountTotal={total}
      retentionAmount={withheld} currency="USD" />
  </QueryClientProvider>);
}

beforeEach(() => {
  vi.mocked(apiPost).mockReset();
  vi.mocked(apiPost).mockResolvedValue({});
  vi.stubGlobal('crypto', webcrypto);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('payment withholding keeps canonical decimal amounts', () => {
  it.each([
    ['9007199254740993.00', '9007199254740992.00', '9007199254740992.00'],
    ['9007199254740993.00', '9007199254740993.00', '9007199254740993.00'],
    ['123.40', '23.4000', '23.4000'],
    ['123.40', '-2.00', '0'],
    ['123.40', '150.00', '123.40'],
    ['123.40', '', '0'],
    ['2000.00', '1e3', '1000'],
    ['9007199254740993.00', '9.007199254740993e15', '9007199254740993'],
    ['123.40', '2.34e1', '23.4'],
    ['123.40', '0e999999999999999999999999999999', '0'],
  ])('posts exact clamped withholding for gross %s and input %s', async (total, entered, expected) => {
    open(total, entered);
    fireEvent.click(screen.getByRole('button', { name: 'Record payment' }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(apiPost).toHaveBeenCalledWith(`/api/v1/finance/invoices/${INVOICE_ID}/record-payment/`, expect.objectContaining({
      withholding_amount: expected,
      idempotency_key: expect.any(String),
    }));
    expect(String(postedKey(0)).length).toBeLessThanOrEqual(64);
  });

  it('keeps a long key stable on retry and changes it for different withholding', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('Retryable network failure'));
    open('9007199254740993.00', '9007199254740992.00');
    const button = screen.getByRole('button', { name: 'Record payment' });
    fireEvent.click(button);
    await screen.findByText('Retryable network failure');
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(button).toBeEnabled());
    const first = postedKey(0);
    expect(first).toMatch(/^[a-f0-9]{64}$/);
    expect(postedKey(1)).toBe(first);
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '9007199254740991.00' } });
    fireEvent.click(button);
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(3));
    expect(postedKey(2)).not.toBe(first);
  });

  it('shows one dollar of cash between two adjacent large canonical totals', () => {
    open('9007199254740993.00', '9007199254740992.00');
    expect(screen.getByText('Cash paid').nextElementSibling).toHaveTextContent('$1.00');
    expect(screen.getByText('Gross settled').nextElementSibling).toHaveTextContent('$9,007,199,254,740,993.00');
  });

  it.each([['Infinity', '1'], ['123.40', 'NaN'], ['123.40', '1e50'], ['123.40', '1e-49'], ['bad', '0']])(
    'does not post unavailable amounts (%s / %s)', (total, withheld) => {
      open(total, withheld);
      expect(screen.getByRole('button', { name: 'Record payment' })).toBeDisabled();
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid form');
      fireEvent.click(screen.getByRole('button', { name: 'Record payment' }));
      expect(apiPost).not.toHaveBeenCalled();
    },
  );
  it('distinguishes bad numeric input from a genuinely empty optional field', async () => {
    open('123.40', '');
    const input = screen.getByRole('spinbutton');
    const button = screen.getByRole('button', { name: 'Record payment' });
    Object.defineProperty(input, 'validity', { configurable: true, value: { badInput: true } });
    fireEvent.input(input);
    expect(button).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid form');
    fireEvent.click(button);
    expect(apiPost).not.toHaveBeenCalled();
    Object.defineProperty(input, 'validity', { configurable: true, value: { badInput: false } });
    fireEvent.input(input);
    expect(button).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(apiPost).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ withholding_amount: '0' }));
  });

  it('shows an error without posting when a long key cannot be hashed', async () => {
    vi.stubGlobal('crypto', undefined);
    open('9007199254740993.00', '9007199254740992.00');
    fireEvent.click(screen.getByRole('button', { name: 'Record payment' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Error');
    expect(apiPost).not.toHaveBeenCalled();
  });

});
