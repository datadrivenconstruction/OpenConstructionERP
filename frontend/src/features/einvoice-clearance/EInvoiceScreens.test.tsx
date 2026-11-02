// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The e-invoice screens: setup card (Settings > Market & standards), invoice status card
 * and the Finance "E-invoices" list. Pins visibility by market, one primary action per
 * state, deadline wording, export banner, live-mode confirm, empty / loading / error
 * states and that identifiers stay left-to-right in an RTL locale.
 *
 * Run:  npx vitest run src/features/einvoice-clearance/EInvoiceScreens.test.tsx
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { EInvoiceCard } from './EInvoiceCard';
import { EInvoicesTab } from './EInvoicesTab';
import { EInvoiceSetupCard } from './EInvoiceSetupCard';
import type { DocumentLifecycle, EInvoiceSetupRow, OverviewRow } from './lifecycleApi';

const mocks = vi.hoisted(() => ({
  lang: 'en',
  getEInvoiceSetup: vi.fn(),
  getDocumentLifecycle: vi.fn(),
  getDocumentsOverview: vi.fn(),
  listProfiles: vi.fn(),
  updateProfile: vi.fn(),
  listDocuments: vi.fn(),
  validateDocument: vi.fn(),
  submitDocument: vi.fn(),
  fetchDocumentPayload: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const text = String(opts?.defaultValue ?? key);
      return text.replace(/\{\{(\w+)\}\}/g, (_m, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: mocks.lang },
  }),
}));

vi.mock('./lifecycleApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./lifecycleApi')>()),
  getEInvoiceSetup: mocks.getEInvoiceSetup,
  getDocumentLifecycle: mocks.getDocumentLifecycle,
  getDocumentsOverview: mocks.getDocumentsOverview,
}));

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  listProfiles: mocks.listProfiles,
  updateProfile: mocks.updateProfile,
  listDocuments: mocks.listDocuments,
  validateDocument: mocks.validateDocument,
  submitDocument: mocks.submitDocument,
  fetchDocumentPayload: mocks.fetchDocumentPayload,
}));

vi.mock('@/features/market/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/market/api')>()),
  useMarketScope: () => ({
    isLoading: false,
    data: {
      markets: ['DE', 'SA', 'MY', 'PL'],
      expanded_markets: ['DE', 'SA', 'MY', 'PL'],
      all_markets: false,
      hidden_modules: [],
      module_markets: { einvoice_clearance: ['DE', 'SA', 'MY', 'PL', 'IT'] },
    },
  }),
}));

function market(country: string, platform: string, over: Partial<EInvoiceSetupRow> = {}): EInvoiceSetupRow {
  return {
    country,
    platform,
    label: platform,
    profile_id: `p-${country}`,
    mode: 'export',
    ready: true,
    missing: [],
    has_consolidation: false,
    ...over,
  };
}

const SA = market('SA', 'ZATCA');
const DE = market('DE', 'XRechnung / Peppol', { ready: false, missing: ['network_participant_id'] });
const MY = market('MY', 'MyInvois', { has_consolidation: true });

function profile(country: string, platform: string, over: Record<string, unknown> = {}) {
  return {
    id: `p-${country}`,
    company_key: 'acme',
    country,
    regime: 'clearance',
    platform,
    tax_registration_id: '310122393500003',
    network_participant_id: '',
    certificate_reference: 'vault://csid/egs-1234',
    adapter_key: 'reference',
    sandbox: true,
    mode: 'export',
    is_active: true,
    settings: {},
    notes: '',
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    ...over,
  };
}

function lifecycle(over: Partial<DocumentLifecycle> = {}): DocumentLifecycle {
  return {
    document_id: 'doc-1',
    country: 'SA',
    platform: 'ZATCA',
    status: 'validated',
    mode: 'sandbox',
    document_kind: 'simplified',
    identifier_label: 'UUID',
    authority_identifier: '',
    deadlines: [],
    allowed_actions: ['send', 'download'],
    findings: [],
    has_consolidation: false,
    ...over,
  };
}

function overviewRow(over: Partial<OverviewRow> = {}): OverviewRow {
  return {
    id: 'o-1',
    invoice_id: 'i-1',
    invoice_number: 'SIM-0001',
    invoice_date: '2026-03-10',
    buyer_name: 'Acme Retail',
    currency_code: 'SAR',
    total_amount: '5290.00',
    country: 'SA',
    status: 'validated',
    document_kind: 'simplified',
    deadline: null,
    blocking: 0,
    ...over,
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  Object.values(mocks).forEach((m) => typeof m === 'function' && 'mockReset' in m && m.mockReset());
  mocks.lang = 'en';
  mocks.getEInvoiceSetup.mockResolvedValue([SA, DE]);
  mocks.listProfiles.mockResolvedValue([profile('SA', 'ZATCA'), profile('DE', 'XRechnung / Peppol')]);
  mocks.listDocuments.mockResolvedValue([{ id: 'doc-1' }]);
  mocks.getDocumentLifecycle.mockResolvedValue(lifecycle());
  mocks.getDocumentsOverview.mockResolvedValue([]);
  mocks.updateProfile.mockResolvedValue({});
  mocks.validateDocument.mockResolvedValue({});
  mocks.submitDocument.mockResolvedValue({});
});

// ── Setup card ───────────────────────────────────────────────────────────────

describe('EInvoiceSetupCard', () => {
  it('shows no market rows for a tenant without an e-invoicing market', async () => {
    mocks.getEInvoiceSetup.mockResolvedValue([]);
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText('E-invoicing');
    await waitFor(() => expect(mocks.getEInvoiceSetup).toHaveBeenCalled());
    expect(screen.queryByText(/ZATCA/)).toBeNull();
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('reads a failing setup endpoint as "no markets" without crashing', async () => {
    mocks.getEInvoiceSetup.mockRejectedValue(new Error('403'));
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText('E-invoicing');
    await waitFor(() => expect(mocks.getEInvoiceSetup).toHaveBeenCalled());
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('lists one row per market with ready and missing states', async () => {
    wrap(<EInvoiceSetupCard canEdit />);
    expect(await screen.findByText(/\[SA\] ZATCA/)).toBeTruthy();
    expect(screen.getByText(/\[DE\] XRechnung/)).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText(/Missing: network_participant_id/)).toBeTruthy();
  });

  it('never prints the whole certificate reference', async () => {
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText(/\[SA\]/);
    expect(screen.queryByText(/vault:\/\/csid/)).toBeNull();
    expect(screen.getAllByText(/••••1234/).length).toBeGreaterThan(0);
  });

  it('is read-only for a non-admin', async () => {
    wrap(<EInvoiceSetupCard canEdit={false} />);
    await screen.findByText(/\[SA\]/);
    screen.getAllByRole('combobox').forEach((el) => expect((el as HTMLSelectElement).disabled).toBe(true));
    screen.getAllByRole('textbox').forEach((el) => expect((el as HTMLInputElement).disabled).toBe(true));
  });

  it('keeps the seller id left-to-right', async () => {
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText(/\[SA\]/);
    screen.getAllByRole('textbox').forEach((el) => expect(el.getAttribute('dir')).toBe('ltr'));
  });

  it('switches to sandbox in one step', async () => {
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText(/\[SA\]/);
    fireEvent.change(screen.getAllByRole('combobox')[0]!, { target: { value: 'sandbox' } });
    await waitFor(() => expect(mocks.updateProfile).toHaveBeenCalled());
    expect(mocks.updateProfile.mock.calls[0]![0]).toBe('p-SA');
    expect(mocks.updateProfile.mock.calls[0]![1]).toMatchObject({ mode: 'sandbox', country: 'SA' });
  });

  it('disables Live until a sandbox run succeeded and a certificate exists', async () => {
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText(/\[SA\]/);
    const live = screen.getAllByRole('option', { name: /live/i })[0] as HTMLOptionElement;
    expect(live.disabled).toBe(true);
  });

  it('asks for confirmation before Live, focuses Cancel, and saves only on confirm', async () => {
    mocks.listProfiles.mockResolvedValue([
      profile('SA', 'ZATCA', { settings: { sandbox_success_at: '2026-11-01T10:00:00Z' } }),
    ]);
    mocks.getEInvoiceSetup.mockResolvedValue([SA]);
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText(/\[SA\]/);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'live' } });
    expect(await screen.findByText(/legally binding invoices to ZATCA/)).toBeTruthy();
    const dialog = screen.getByRole('dialog');
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    expect(cancel).toBeTruthy();
    expect(mocks.updateProfile).not.toHaveBeenCalled();
    fireEvent.click(cancel);
    expect(mocks.updateProfile).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'live' } });
    const again = await screen.findByRole('dialog');
    const buttons = within(again).getAllByRole('button');
    fireEvent.click(buttons[buttons.length - 1]!);
    await waitFor(() => expect(mocks.updateProfile).toHaveBeenCalledTimes(1));
    expect(mocks.updateProfile.mock.calls[0]![1]).toMatchObject({ mode: 'live' });
  });
});

describe('EInvoiceSetupCard live confirm focus', () => {
  it('opens the live confirm with focus on Cancel', async () => {
    mocks.listProfiles.mockResolvedValue([
      profile('SA', 'ZATCA', { settings: { sandbox_success_at: '2026-11-01T10:00:00Z' } }),
    ]);
    mocks.getEInvoiceSetup.mockResolvedValue([SA]);
    wrap(<EInvoiceSetupCard canEdit />);
    await screen.findByText(/\[SA\]/);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'live' } });
    const dialog = await screen.findByRole('dialog');
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    await waitFor(() => expect(document.activeElement).toBe(cancel));
  });
});

// ── Invoice status card ──────────────────────────────────────────────────────

const HOUR = 3600;

describe('EInvoiceCard', () => {
  it('renders nothing for a seller country outside the tenant markets', async () => {
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="US" />);
    await waitFor(() => expect(mocks.getEInvoiceSetup).toHaveBeenCalled());
    expect(mocks.listDocuments).not.toHaveBeenCalled();
    expect(document.body.textContent).toBe('');
  });

  it('renders nothing when the setup call fails (module or permission missing)', async () => {
    mocks.getEInvoiceSetup.mockRejectedValue(new Error('403'));
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    await waitFor(() => expect(mocks.getEInvoiceSetup).toHaveBeenCalled());
    expect(mocks.listDocuments).not.toHaveBeenCalled();
    expect(document.body.textContent).toBe('');
  });

  it('renders nothing when the invoice has no e-invoice document yet', async () => {
    mocks.listDocuments.mockResolvedValue([]);
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    await waitFor(() => expect(mocks.listDocuments).toHaveBeenCalled());
    expect(mocks.getDocumentLifecycle).not.toHaveBeenCalled();
    expect(document.body.textContent).toBe('');
  });

  it('renders nothing when the lifecycle call fails', async () => {
    mocks.getDocumentLifecycle.mockRejectedValue(new Error('500'));
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    await waitFor(() => expect(mocks.getDocumentLifecycle).toHaveBeenCalled());
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('shows status, platform, a deadline badge as text and ONE primary action', async () => {
    mocks.getDocumentLifecycle.mockResolvedValue(
      lifecycle({
        deadlines: [{ id: 'report', action: 'submit', starts_at: 'a', due_at: '2026-03-11T09:00:00Z', state: 'warning', seconds_left: 21 * HOUR }],
      }),
    );
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    expect(await screen.findByText(/E-invoice · ZATCA/)).toBeTruthy();
    expect(screen.getAllByText('validated').length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/Report within 21 hours/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Send to ZATCA' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Download file/ })).toBeTruthy();
    expect(screen.getAllByRole('button').filter((b) => /Send|Validate|Cancel|Check/.test(b.textContent ?? ''))).toHaveLength(1);
  });

  it('words an overdue deadline as passed, in days', async () => {
    mocks.getDocumentLifecycle.mockResolvedValue(
      lifecycle({
        deadlines: [{ id: 'irp', action: 'submit', starts_at: 'a', due_at: 'b', state: 'overdue', seconds_left: -3 * 86400 }],
      }),
    );
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    expect(await screen.findByLabelText('Deadline passed 3 days ago')).toBeTruthy();
  });

  it('marks exactly the current step in the stepper', async () => {
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    const list = (await screen.findByText(/E-invoice · ZATCA/)).closest('div')!.parentElement!.querySelector('ol')!;
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(5);
    expect(items.filter((li) => li.getAttribute('aria-current') === 'step')).toHaveLength(1);
    expect(items[1]!.getAttribute('aria-current')).toBe('step');
  });

  it('shows the export banner with the link to the single setup place', async () => {
    mocks.getDocumentLifecycle.mockResolvedValue(lifecycle({ mode: 'export', allowed_actions: ['download'] }));
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    expect(await screen.findByText(/Export only: download the file and upload it to ZATCA yourself/)).toBeTruthy();
    const link = screen.getByRole('link', { name: 'Set up in Market & standards' });
    expect(link.getAttribute('href')).toBe('/settings?tab=market');
    expect(screen.queryByRole('button', { name: /Send to/ })).toBeNull();
  });

  it('shows a rejected banner with the rule id left-to-right and offers revalidate', async () => {
    mocks.getDocumentLifecycle.mockResolvedValue(
      lifecycle({
        status: 'rejected',
        allowed_actions: ['validate', 'download'],
        findings: [{ rule_id: 'EINV-SA-001', severity: 'error', message: 'Previous invoice hash missing', params: {} }],
      }),
    );
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('EINV-SA-001');
    expect(alert.textContent).toContain('Previous invoice hash missing');
    expect(alert.textContent).toContain('Fix and revalidate');
    expect(within(alert).getByText('EINV-SA-001').getAttribute('dir')).toBe('ltr');
    expect(screen.getByRole('button', { name: 'Validate' })).toBeTruthy();
  });

  it('offers only a corrective invoice (disabled placeholder) where withdrawal is not possible', async () => {
    mocks.getEInvoiceSetup.mockResolvedValue([market('PL', 'KSeF')]);
    mocks.getDocumentLifecycle.mockResolvedValue(
      lifecycle({ country: 'PL', platform: 'KSeF', status: 'cleared', mode: 'live', allowed_actions: ['correct', 'download'] }),
    );
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="PL" />);
    const correct = await screen.findByRole('button', { name: 'Issue corrective invoice' });
    expect((correct as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
  });

  it('validates a draft and sends a validated document through the API', async () => {
    mocks.getDocumentLifecycle.mockResolvedValue(lifecycle({ status: 'draft', allowed_actions: ['validate', 'download'] }));
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Validate' }));
    await waitFor(() => expect(mocks.validateDocument).toHaveBeenCalledWith('doc-1'));
    expect(mocks.submitDocument).not.toHaveBeenCalled();
  });

  it('cannot fire a second send while the first is in flight', async () => {
    let release: () => void = () => {};
    mocks.submitDocument.mockImplementation(() => new Promise<void>((res) => (release = res)));
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    const send = await screen.findByRole('button', { name: 'Send to ZATCA' });
    fireEvent.click(send);
    await waitFor(() => expect(mocks.submitDocument).toHaveBeenCalledTimes(1));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Send to ZATCA' }) as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: 'Send to ZATCA' }));
    expect(mocks.submitDocument).toHaveBeenCalledTimes(1);
    release();
  });

  it('folds the details and shows the authority identifier left-to-right when opened', async () => {
    mocks.getDocumentLifecycle.mockResolvedValue(
      lifecycle({ status: 'cleared', authority_identifier: 'UUID-9f2', allowed_actions: ['cancel', 'download'] }),
    );
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    const toggle = await screen.findByRole('button', { name: /Details/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('UUID-9f2')).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('UUID-9f2').getAttribute('dir')).toBe('ltr');
  });

  it('does not throw in an RTL locale and keeps IDs left-to-right', async () => {
    mocks.lang = 'ar';
    mocks.getDocumentLifecycle.mockResolvedValue(
      lifecycle({
        status: 'rejected',
        allowed_actions: ['validate', 'download'],
        deadlines: [{ id: 'd', action: 'submit', starts_at: 'a', due_at: 'b', state: 'warning', seconds_left: 5 * HOUR }],
        findings: [{ rule_id: 'EINV-CORE-004', severity: 'error', message: 'x', params: {} }],
      }),
    );
    wrap(<EInvoiceCard projectId="pr" invoiceId="i-1" sellerCountry="SA" />);
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('EINV-CORE-004').getAttribute('dir')).toBe('ltr');
  });
});

// ── Finance > E-invoices ─────────────────────────────────────────────────────

describe('EInvoicesTab', () => {
  it('shows the loading skeleton while the list loads', async () => {
    mocks.getDocumentsOverview.mockReturnValue(new Promise(() => {}));
    wrap(<EInvoicesTab projectId="pr" />);
    await waitFor(() => expect(mocks.getDocumentsOverview).toHaveBeenCalledWith('pr'));
    expect(screen.queryByText(/No e-invoices yet/)).toBeNull();
    expect(screen.queryByText('Could not load e-invoices')).toBeNull();
  });

  it('shows the empty state with a way to the invoices', async () => {
    wrap(<EInvoicesTab projectId="pr" />);
    expect(await screen.findByText('No e-invoices yet. Issue an invoice to create one.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Go to invoices' }).getAttribute('href')).toBe('/finance?tab=invoices');
  });

  it('shows an inline error with Retry that asks again', async () => {
    mocks.getDocumentsOverview.mockRejectedValueOnce(new Error('500'));
    wrap(<EInvoicesTab projectId="pr" />);
    expect(await screen.findByText('Could not load e-invoices')).toBeTruthy();
    mocks.getDocumentsOverview.mockResolvedValue([overviewRow()]);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('SIM-0001')).toBeTruthy();
    expect(mocks.getDocumentsOverview).toHaveBeenCalledTimes(2);
  });

  it('lists rows with exact money and the invoice currency', async () => {
    mocks.getDocumentsOverview.mockResolvedValue([overviewRow({ total_amount: '1437500.00', currency_code: 'SAR' })]);
    wrap(<EInvoicesTab projectId="pr" />);
    const cell = (await screen.findByText('SIM-0001')).closest('tr')!;
    expect(cell.textContent).toMatch(/1[,.\s\u00a0\u202f]?437[,.\s\u00a0\u202f]?500/);
    expect(cell.textContent).toContain('SAR');
  });

  it('filters by due soon and by search', async () => {
    mocks.getDocumentsOverview.mockResolvedValue([
      overviewRow({ id: 'a', invoice_number: 'A-1', deadline: { id: 'd', action: 'submit', starts_at: '', due_at: '', state: 'ok', seconds_left: 99 * HOUR } }),
      overviewRow({ id: 'b', invoice_number: 'B-2', buyer_name: 'Zeta', deadline: { id: 'd', action: 'submit', starts_at: '', due_at: '', state: 'overdue', seconds_left: -HOUR } }),
    ]);
    wrap(<EInvoicesTab projectId="pr" />);
    await screen.findByText('A-1');
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.queryByText('A-1')).toBeNull();
    expect(screen.getByText('B-2')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zeta' } });
    expect(screen.queryByText('A-1')).toBeNull();
    expect(screen.getByText('B-2')).toBeTruthy();
  });

  it('offers only the tenant markets in the country filter', async () => {
    wrap(<EInvoicesTab projectId="pr" />);
    await screen.findByText('No e-invoices yet. Issue an invoice to create one.');
    const select = screen.getByRole('combobox', { name: 'Country' });
    const options = within(select).getAllByRole('option').map((o) => o.getAttribute('value'));
    expect(options).toEqual(['', 'SA', 'DE']);
  });

  it('offers the consolidated wizard only for a market with a grouping rule', async () => {
    wrap(<EInvoicesTab projectId="pr" />);
    await screen.findByText(/No e-invoices yet/);
    expect(screen.queryByRole('button', { name: /Create consolidated/ })).toBeNull();
    cleanup();
    mocks.getEInvoiceSetup.mockResolvedValue([MY]);
    wrap(<EInvoicesTab projectId="pr" />);
    expect(await screen.findByRole('button', { name: /Create consolidated/ })).toBeTruthy();
  });
});
