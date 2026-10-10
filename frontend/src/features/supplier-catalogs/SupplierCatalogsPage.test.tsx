// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <SupplierCatalogsPage /> - the two halves of deleting a record.
//
// Until this batch the page could add vendors, items and warehouses and do
// nothing else with them, so both behaviours below are new and both are the
// kind that goes wrong quietly.
//
//   1. The confirmation has to be the shared ConfirmDialog and it has to stand
//      between the button and the request. `window.confirm` would also "ask
//      first", and it would be unstyled, untranslated and unable to name the
//      record, so the assertion is that the dialog rendered AND that nothing
//      was sent until it was confirmed.
//
//   2. A refused delete has to show the reason the server sent. The backend
//      answers a held record with 409 and a structured body naming what holds
//      it and what to do instead; the page must not replace that with a
//      generic failure, because the generic one leaves the buyer with nowhere
//      to go. The rejection below is a real `ApiError` built from the real
//      409 body rather than a plain Error, so the assertion exercises the same
//      `getErrorMessage` path the browser takes - a plain Error would pass
//      while proving nothing about the body.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

/* ── i18n ──────────────────────────────────────────────────────────────────
   The page calls `t(key, { defaultValue })` throughout, and the shared chrome
   it renders inside reaches the real i18n singleton. Replacing the module
   here renders every defaultValue verbatim, which is what lets the assertions
   below quote English prose. Interpolation is filled the way i18next fills
   it, because the delete dialog puts the record's name in `{{name}}`. */
vi.mock('react-i18next', () => {
  type Opts = Record<string, unknown>;
  const fill = (template: string, opts?: Opts): string => {
    if (!opts) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
      opts[name] === undefined ? `{{${name}}}` : String(opts[name]),
    );
  };
  return {
    useTranslation: () => ({
      t: (key: string, second?: string | Opts, third?: Opts) => {
        if (typeof second === 'string') return fill(second, third);
        const dflt = second?.defaultValue;
        return fill(typeof dflt === 'string' ? dflt : key, second);
      },
      i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
    Trans: ({ children }: { children?: unknown }) => children ?? null,
    initReactI18next: { type: '3rdParty', init: () => undefined },
    I18nextProvider: ({ children }: { children?: unknown }) => children ?? null,
  };
});

const { addToast } = vi.hoisted(() => ({ addToast: vi.fn() }));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector?: (s: { addToast: typeof addToast }) => unknown) => {
    const state = { addToast };
    return selector ? selector(state) : state;
  },
}));

/* Spread the real module: the page imports types and helpers from it as well
   as the calls stubbed here, and a hand-written export list that forgets one
   fails at runtime rather than as a type error. */
vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    listVendors: vi.fn(),
    listCatalogItems: vi.fn(),
    listWarehouses: vi.fn(),
    listWarehouseBalances: vi.fn(),
    comparePrices: vi.fn(),
    createVendor: vi.fn(),
    createCatalogItem: vi.fn(),
    createWarehouse: vi.fn(),
    updateVendor: vi.fn(),
    updateCatalogItem: vi.fn(),
    updateWarehouse: vi.fn(),
    deleteVendor: vi.fn(),
    deleteCatalogItem: vi.fn(),
    deleteWarehouse: vi.fn(),
    suspendVendor: vi.fn(),
    blacklistVendor: vi.fn(),
    rateVendor: vi.fn(),
  };
});

import { ApiError } from '@/shared/lib/api';
import { deleteVendor, listVendors, type Vendor } from './api';
import { SupplierCatalogsPage } from './SupplierCatalogsPage';

/* ── Fixtures ──────────────────────────────────────────────────────────── */

function makeVendor(over: Partial<Vendor> = {}): Vendor {
  return {
    id: 'vendor-1',
    code: 'ACME-01',
    name: 'Acme Building Supplies',
    legal_name: null,
    tax_id: null,
    contact_id: null,
    status: 'active',
    currency: 'EUR',
    payment_terms_days: 30,
    rating: 4,
    country_code: 'DE',
    region: null,
    categories_json: [],
    preferred_for_json: [],
    contacts_json: [],
    notes: null,
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
    ...over,
  };
}

/** The body a held vendor comes back with, byte for byte as the service builds it. */
const HELD_BODY = {
  detail: {
    code: 'vendor_in_use',
    message:
      "Vendor 'ACME-01' cannot be deleted because 2 purchase orders and 1 KYC document still reference it.",
    remediation:
      'Suspend the vendor to stop it being ordered from while the open records are settled, or blacklist it to close it permanently. Both keep the purchase history intact.',
    holders: [
      { kind: 'purchase_order', count: 2 },
      { kind: 'kyc_document', count: 1 },
    ],
  },
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/supplier-catalogs']}>
        <SupplierCatalogsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Open the confirmation for the one vendor in the fixture. */
async function clickDelete() {
  const row = await screen.findByText('Acme Building Supplies');
  expect(row).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
}

beforeEach(() => {
  vi.mocked(listVendors).mockResolvedValue({
    items: [makeVendor()],
    total: 1,
    offset: 0,
    limit: 200,
  });
  vi.mocked(deleteVendor).mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SupplierCatalogsPage deletion', () => {
  it('asks in a dialog before it deletes anything', async () => {
    renderPage();
    await clickDelete();

    // The shared ConfirmDialog, not a native prompt: it is a real element in
    // the document, it carries the alertdialog role, and it names the record.
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText('Delete this vendor?')).toBeInTheDocument();
    expect(screen.getByText(/ACME-01 - Acme Building Supplies/)).toBeInTheDocument();

    // Nothing has been sent yet. This is the half that a `window.confirm`
    // rewrite would still pass, so it is asserted before the confirm click.
    expect(deleteVendor).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));
    await waitFor(() => expect(deleteVendor).toHaveBeenCalledWith('vendor-1'));
  });

  it('leaves the record alone when the dialog is cancelled', async () => {
    renderPage();
    await clickDelete();

    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(deleteVendor).not.toHaveBeenCalled();
  });

  it("shows the server's reason when the delete is refused with 409", async () => {
    vi.mocked(deleteVendor).mockRejectedValue(new ApiError(409, 'Conflict', HELD_BODY));

    renderPage();
    await clickDelete();
    fireEvent.click(await screen.findByTestId('confirm-dialog-confirm'));

    await waitFor(() => expect(addToast).toHaveBeenCalled());
    // Destructure and check rather than assert non-null: under
    // noUncheckedIndexedAccess an index read is `T | undefined`, and a `!`
    // here would silence the compiler while turning a missing call into a
    // confusing runtime failure instead of this sentence.
    const [firstCall] = vi.mocked(addToast).mock.calls;
    if (!firstCall) throw new Error('addToast was never called');
    const [toast] = firstCall;
    expect(toast.type).toBe('error');
    // The counts and the kinds the server named, not a generic failure.
    expect(toast.title).toContain('2 purchase orders and 1 KYC document');
    // And what to do instead, which is the whole point of refusing this way.
    expect(toast.title).toContain('Suspend the vendor');
  });
});

describe('SupplierCatalogsPage embedded in Procurement', () => {
  it('shows the one tab it was given, without the page header or the other tabs', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/procurement']}>
          <SupplierCatalogsPage embeddedTab="vendors" />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Acme Building Supplies')).toBeInTheDocument();
    // The standalone page keeps these; inside Procurement they would be a
    // second tab bar and a second guide on one screen.
    expect(screen.queryByRole('button', { name: /Warehouses/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Catalog$/ })).not.toBeInTheDocument();
  });
});
