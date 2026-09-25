// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { invalidateFinanceFigures, isFinanceFigureKey } from '../financeQueryKeys';

describe('finance figures invalidation', () => {
  it('matches the KPI, register and purchase-order keys and nothing else', () => {
    expect(isFinanceFigureKey(['finance', 'dashboard', 'p'])).toBe(true);
    expect(isFinanceFigureKey(['finance-invoices', 'p', 'payable'])).toBe(true);
    expect(isFinanceFigureKey(['finance-budgets', 'p'])).toBe(true);
    expect(isFinanceFigureKey(['procurement-po', 'p'])).toBe(true);
    expect(isFinanceFigureKey(['project', 'p'])).toBe(false);
    expect(isFinanceFigureKey(['financeX'])).toBe(false);
    expect(isFinanceFigureKey([{ scope: 'finance' }])).toBe(false);
  });

  it('marks the dashboard stale after a mutation', async () => {
    const client = new QueryClient();
    client.setQueryData(['finance', 'dashboard', 'p'], { total: 1 });
    client.setQueryData(['project', 'p'], { id: 'p' });
    await invalidateFinanceFigures(client);
    expect(client.getQueryState(['finance', 'dashboard', 'p'])?.isInvalidated).toBe(true);
    expect(client.getQueryState(['project', 'p'])?.isInvalidated).toBe(false);
  });
});
