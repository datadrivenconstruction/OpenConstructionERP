// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';

const api = vi.hoisted(() => ({
  payments: [] as Record<string, unknown>[],
  posted: [] as { url: string; body?: Record<string, unknown> }[],
}));

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(() => Promise.resolve({ items: api.payments })),
  apiPost: vi.fn((url: string, body?: Record<string, unknown>) => {
    api.posted.push({ url, body });
    return Promise.resolve({});
  }),
}));

import { apiGet } from '@/shared/lib/api';
import { remainingSettlement, settleAndMarkPaid } from '../markInvoicePaid';

beforeEach(() => {
  api.payments = [];
  api.posted.length = 0;
});

describe('remainingSettlement', () => {
  it('subtracts cash and withholding already recorded, and adds refunds back', () => {
    const left = remainingSettlement({ id: 'i', amount_total: '1000.00' }, [
      { amount: '300.00', withholding_amount: '50.00' },
      { amount: '100.00', is_refund: true },
    ]);
    expect(left).toEqual({ gross: 750, cash: 750, withheld: 0 });
  });

  it('holds back only the retainage not withheld yet', () => {
    const left = remainingSettlement({ id: 'i', amount_total: '1000', retention_amount: '100' }, [
      { amount: '460', withholding_amount: '40' },
    ]);
    expect(left).toEqual({ gross: 500, cash: 440, withheld: 60 });
  });
});

describe('settleAndMarkPaid', () => {
  it('records the open balance with a stable key before moving the status', async () => {
    await settleAndMarkPaid({ id: 'inv-1', amount_total: '1210.00', currency_code: 'EUR' }, '2026-09-25');
    expect(api.posted.map((p) => p.url)).toEqual([
      '/v1/finance/invoices/inv-1/record-payment/',
      '/v1/finance/inv-1/pay/',
    ]);
    expect(api.posted[0]?.body).toEqual({
      payment_date: '2026-09-25',
      amount: '1210.00',
      withholding_amount: '0.00',
      currency_code: 'EUR',
      idempotency_key: 'markpaid:inv-1',
    });
  });

  it('records nothing more for an invoice already paid in full', async () => {
    api.payments = [{ amount: '1210.00' }];
    await settleAndMarkPaid({ id: 'inv-1', amount_total: '1210.00', currency_code: 'EUR' }, '2026-09-25');
    expect(api.posted.map((p) => p.url)).toEqual(['/v1/finance/inv-1/pay/']);
  });

  it('reads every page of earlier payments before working out what is open', async () => {
    const first = Array.from({ length: 100 }, () => ({ amount: '10.00' }));
    vi.mocked(apiGet)
      .mockResolvedValueOnce({ items: first, total: 101, offset: 0, limit: 100 })
      .mockResolvedValueOnce({ items: [{ amount: '10.00' }], total: 101, offset: 100, limit: 100 });
    await settleAndMarkPaid({ id: 'inv-1', amount_total: '1010.00', currency_code: 'EUR' }, '2026-09-25');
    expect(vi.mocked(apiGet).mock.calls.at(-1)?.[0]).toContain('offset=100');
    expect(api.posted.map((p) => p.url)).toEqual(['/v1/finance/inv-1/pay/']);
  });
});
