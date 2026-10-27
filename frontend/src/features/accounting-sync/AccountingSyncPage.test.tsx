// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The accounting sync screen against a mocked API: the connection list, the
 * mapping table that marks rows without an account code, the sync log with its
 * retry, and the pure rules the screens lean on (which exports a template
 * unlocks, which failures can be retried, what a settings form sends).
 */
import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAuthStore } from '@/stores/useAuthStore';
import { AccountingSyncPage } from './AccountingSyncPage';
import { AccountingSyncCard, lastSyncOf } from './AccountingSyncCard';
import { buildBody } from './ConnectionForm';
import { availableExports } from './ExportsTab';
import { canRetry, exportKindsFor, needsAuthorisation, unmappedAccounts, type Connection } from './api';

const CONNECTION: Connection = {
  id: 'c1',
  name: 'Books EU',
  provider: 'xero',
  country_code: 'DE',
  chart_template: 'skr03',
  base_currency: 'EUR',
  status: 'active',
  is_sandbox: false,
  client_id: 'abc',
  has_client_secret: true,
  is_authorised: true,
  external_tenant_id: 'ten-1',
  lock_date: '2026-03-31',
  project_ids: [],
  settings: { auto_push: true },
  last_sync_at: '2026-10-01T10:00:00Z',
  last_sync_status: 'failed',
  created_at: '2026-09-01T10:00:00Z',
};

const CATALOG = {
  templates: [
    { key: 'skr03', label: 'SKR03', country_code: 'DE', formats: ['datev_extf'] },
    { key: 'generic', label: 'Generic', country_code: null, formats: ['journal'] },
  ],
  categories: ['revenue'],
  tax_codes: [],
  journal_columns: ['entry_no', 'account'],
  export_kinds: ['datev_postings', 'datev_master', 'journal_csv', 'journal_xlsx', 'saft'],
};

const MAPPINGS = {
  chart_template: 'skr03',
  templates: CATALOG.templates,
  tax_codes: [],
  accounts: [
    { category: 'revenue', account_code: '8400', account_name: 'Revenue' },
    { category: 'bank', account_code: '', account_name: '' },
  ],
  taxes: [{ tax_code: 'DE19', direction: 'sales', external_code: '', rate_pct: '19' }],
};

const LOG = {
  total: 2,
  items: [
    {
      id: 'l1', connection_id: 'c1', project_id: null, action: 'push', record_type: 'ar_invoice', record_id: 'r1',
      record_label: 'INV-001', status: 'failed', attempt: 2, error_reason: 'Account not mapped', external_id: null,
      amount: '1190.00', resolved: false, created_at: '2026-10-01T10:00:00Z',
    },
    {
      id: 'l2', connection_id: 'c1', project_id: null, action: 'push', record_type: 'ar_invoice', record_id: 'r2',
      record_label: 'INV-002', status: 'success', attempt: 1, error_reason: null, external_id: 'x1',
      amount: '500.00', resolved: false, created_at: '2026-10-01T09:00:00Z',
    },
  ],
};

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: apiGetMock, apiPost: vi.fn(), apiPut: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn() };
});

function route(path: string): unknown {
  if (path.endsWith('/connections')) return [CONNECTION];
  if (path.includes('/templates')) return CATALOG;
  if (path.endsWith('/mappings')) return MAPPINGS;
  if (path.includes('/findings'))
    return [{ rule_id: 'accounting_sync.unmapped_account', severity: 'error', message: 'No account for bank', element_ref: null, record_id: 'r1' }];
  if (path.includes('/documents'))
    return [{
      record_id: 'r1', record_type: 'ar_invoice', source: 'invoice', number: 'INV-001', doc_date: '2026-09-30',
      counterparty: 'ACME', project_code: 'P1', currency: 'EUR', net_total: '1000.00', tax_total: '190.00',
      gross_total: '1190.00', external_id: null,
    }];
  if (path.includes('/log')) return LOG;
  if (path.endsWith('/status'))
    return {
      connections: [{ id: 'c1', name: 'Books EU', provider: 'xero', status: 'active', last_sync_at: '2026-10-01T10:00:00Z', last_sync_status: 'failed', success: 3, failed: 1, open_failures: 1 }],
      open_failures: 1,
      providers: { api: ['xero', 'qbo'], file: ['datev', 'journal', 'saft'] },
    };
  return [];
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGetMock.mockReset();
  apiGetMock.mockImplementation((path: string) => Promise.resolve(route(path)));
  useAuthStore.setState({ userRole: 'admin', isAuthenticated: true });
});

describe('AccountingSyncPage', () => {
  it('lists the connections and opens the sync tab of a live one', async () => {
    wrap(<AccountingSyncPage />);
    expect(await screen.findByTestId('connection-c1')).toHaveTextContent('Books EU');
    expect(await screen.findByTestId('accounting-sync-findings')).toHaveTextContent('Account not mapped');
    expect(await screen.findByTestId('accounting-sync-docs')).toHaveTextContent('INV-001');
    // Money stays a formatted string of the wire value, never recomputed.
    expect(screen.getByTestId('accounting-sync-docs')).toHaveTextContent('1,190.00');
  });

  it('shows Retry only on an open failure', async () => {
    wrap(<AccountingSyncPage />);
    const failed = await screen.findByTestId('log-row-l1');
    expect(failed).toHaveTextContent('Retry');
    expect(screen.getByTestId('log-row-l2')).not.toHaveTextContent('Retry');
  });

  it('marks mapping rows that have no code', async () => {
    wrap(<AccountingSyncPage />);
    await screen.findByTestId('connection-c1');
    fireEvent.click(screen.getByRole('tab', { name: 'Mapping' }));
    const warning = await screen.findByTestId('accounting-sync-mapping-warning');
    expect(warning).toHaveTextContent('1 accounts, 1 tax codes');
    const bank = await screen.findByTestId('account-row-bank');
    expect(bank.querySelector('input[aria-invalid="true"]')).not.toBeNull();
    expect(screen.getByTestId('account-row-revenue').querySelector('input[aria-invalid="true"]')).toBeNull();
  });

  it('never prefills the client secret', async () => {
    wrap(<AccountingSyncPage />);
    await screen.findByTestId('connection-c1');
    fireEvent.click(screen.getByRole('tab', { name: 'Settings' }));
    const secret = (await screen.findByTestId('accounting-sync-secret')) as HTMLInputElement;
    expect(secret.type).toBe('password');
    expect(secret.value).toBe('');
  });

  it('hides the add button from a non-admin', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    wrap(<AccountingSyncPage />);
    await screen.findByTestId('connection-c1');
    expect(screen.queryByRole('button', { name: 'Add connection' })).toBeNull();
  });
});

describe('AccountingSyncCard', () => {
  it('shows connections, open failures and the last sync time', async () => {
    wrap(<AccountingSyncCard />);
    const card = await screen.findByTestId('accounting-sync-card');
    await waitFor(() => expect(card).toHaveTextContent('Open failures'));
    expect(card).toHaveTextContent('1');
  });

  it('picks the newest sync time', () => {
    expect(lastSyncOf([{ last_sync_at: null }, { last_sync_at: '2026-10-02T00:00:00Z' }, { last_sync_at: '2026-10-01T00:00:00Z' }])).toBe('2026-10-02T00:00:00Z');
    expect(lastSyncOf([])).toBeNull();
  });
});

describe('pure rules', () => {
  it('unlocks the DATEV files from a datev_extf template', () => {
    expect(exportKindsFor(['datev_extf'], CATALOG.export_kinds as never)).toEqual(['datev_postings', 'datev_master']);
    expect(exportKindsFor(undefined, CATALOG.export_kinds as never)).toEqual(CATALOG.export_kinds);
  });

  it('offers a connection only the files its provider produces', () => {
    const kinds = CATALOG.export_kinds as never;
    expect(availableExports({ provider: 'datev', chart_template: 'skr03' }, CATALOG.templates, kinds)).toEqual(['datev_postings', 'datev_master']);
    expect(availableExports({ provider: 'journal', chart_template: 'generic' }, CATALOG.templates, kinds)).toEqual(['journal_csv', 'journal_xlsx']);
    expect(availableExports({ provider: 'saft', chart_template: null }, CATALOG.templates, kinds)).toEqual(['saft']);
  });

  it('retries only unresolved failures of a push or pull', () => {
    expect(canRetry({ status: 'failed', resolved: false, action: 'push' })).toBe(true);
    expect(canRetry({ status: 'failed', resolved: true, action: 'push' })).toBe(false);
    expect(canRetry({ status: 'success', resolved: false, action: 'push' })).toBe(false);
  });

  it('flags an unmapped account and an unauthorised live connection', () => {
    expect(unmappedAccounts(MAPPINGS.accounts)).toHaveLength(1);
    expect(needsAuthorisation({ provider: 'xero', is_authorised: false })).toBe(true);
    expect(needsAuthorisation({ provider: 'datev', is_authorised: false })).toBe(false);
  });

  it('sends the secret only when typed and clears a removed lock date', () => {
    const state = {
      name: 'Books EU', country_code: 'de', chart_template: 'skr03', base_currency: 'eur', is_sandbox: false,
      client_id: 'abc', client_secret: '', external_tenant_id: '', lock_date: '', project_ids: [], auto_push: false,
      consultant_number: '', client_number: '', journal_columns: [],
    };
    const body = buildBody('xero', state, CONNECTION);
    expect(body.client_secret).toBeUndefined();
    expect(body.clear_lock_date).toBe(true);
    expect(body.base_currency).toBe('EUR');
    expect(body.settings?.auto_push).toBe(false);
    expect(buildBody('xero', { ...state, client_secret: 's3cret' }, CONNECTION).client_secret).toBe('s3cret');
  });
});
