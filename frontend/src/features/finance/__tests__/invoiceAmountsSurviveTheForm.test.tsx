// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The invoice form bills the lines that were typed, with VAT per line.
 *
 * #466 was the first half: the auto-filled total went through a display
 * formatter, `parseFloat('9,000.00')` is 9 and `parseFloat('900,50')` is 900,
 * so the figure that left the screen was not the figure the person typed. The
 * form now takes lines (quantity, unit rate, VAT %) and derives Net, VAT and
 * Gross from them, so these tests type into the line editor and assert on the
 * request that leaves, never on a formatter round trip.
 *
 * Both number conventions are covered on purpose: under a comma-decimal reader
 * every invoice with cents lost them, at any size.
 *
 * The same harness drives Mark Paid, which has to write a payment row for what
 * is still open before it moves the status; `/pay/` alone left the payments
 * list, the cash flow and the statements at zero.
 *
 * Run:  npx vitest run src/features/finance/__tests__/invoiceAmountsSurviveTheForm.test.tsx
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { InvoicesTab } from '../FinancePage';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useAuthStore } from '@/stores/useAuthStore';

const harness = vi.hoisted(() => ({
  posted: [] as { url: string; body: Record<string, unknown> | undefined }[],
  patched: [] as { url: string; body: Record<string, unknown> }[],
  invoices: [] as Record<string, unknown>[],
  payments: [] as Record<string, unknown>[],
  country: null as string | null,
  taxRows: [] as Record<string, unknown>[],
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string } & Record<string, unknown>) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in opts) {
        let dv = String(opts.defaultValue ?? '');
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue' || k === 'defaultValue_plural') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return key;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: unknown }) => children,
  Trans: ({ children }: { children?: unknown }) => children ?? null,
}));

// Queries answer by the head of their key: the project (for its country), the
// country's tax configurations, the invoice register, and a canned payload for
// everything else. `select` is applied where a query declares one, because the
// register maps its rows through it.
vi.mock('@tanstack/react-query', () => ({
  useQuery: (opts: { queryKey?: unknown[]; select?: (d: unknown) => unknown }) => {
    const head = opts?.queryKey?.[0];
    let raw: unknown = { items: [], total: 0, currency: 'EUR' };
    if (head === 'project') raw = { id: 'proj-1', country_code: harness.country };
    else if (head === 'i18n-tax-configs') raw = { items: harness.taxRows, total: harness.taxRows.length };
    else if (head === 'finance-invoices') raw = { items: harness.invoices, total: harness.invoices.length };
    return {
      data: opts?.select ? opts.select(raw) : raw,
      isLoading: false,
      isError: false,
      isSuccess: true,
      error: null,
      refetch: vi.fn(),
    };
  },
  useMutation: (opts: { mutationFn?: (v: unknown) => unknown; onSuccess?: (d: unknown) => void }) => ({
    // The real mutation runs its `mutationFn`, which is where the request body
    // is assembled. A stub that only records the call would test nothing.
    mutate: (vars: unknown) => {
      Promise.resolve(opts?.mutationFn?.(vars)).then(
        (d) => opts?.onSuccess?.(d),
        () => undefined,
      );
    },
    mutateAsync: (vars: unknown) => Promise.resolve(opts?.mutationFn?.(vars)),
    isPending: false,
    isError: false,
    isSuccess: false,
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn(), setQueryData: vi.fn() }),
}));

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn((url: string) =>
    Promise.resolve(
      url.startsWith('/v1/finance/payments/')
        ? { items: harness.payments, total: harness.payments.length }
        : { items: [], total: 0 },
    ),
  ),
  apiPost: vi.fn((url: string, body?: Record<string, unknown>) => {
    harness.posted.push({ url, body });
    return Promise.resolve({ id: 'inv-1' });
  }),
  apiPatch: vi.fn((url: string, body: Record<string, unknown>) => {
    harness.patched.push({ url, body });
    return Promise.resolve({ id: 'inv-1' });
  }),
  apiPut: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
  downloadWithAuth: vi.fn(),
  fetchBlobWithAuth: vi.fn(),
  triggerDownload: vi.fn(),
  extractErrorMessageFromBody: () => null,
  getErrorMessage: (e: unknown) => String(e),
  isTruncated: () => false,
  API_BASE: '/api',
  getAuthToken: () => 'tok',
  ApiError: class ApiError extends Error {},
}));

// The confirm dialog answers yes, so Mark Paid runs the way a click through
// the dialog runs it.
vi.mock('@/shared/hooks/useConfirm', () => ({
  useConfirm: () => ({
    open: false,
    title: '',
    message: '',
    variant: 'danger',
    loading: false,
    onConfirm: () => undefined,
    onCancel: () => undefined,
    confirm: () => Promise.resolve(true),
    setLoading: () => undefined,
  }),
}));

/** The number-format preference the form's figures follow, per test. */
function readAs(locale: 'en-US' | 'de-DE') {
  usePreferencesStore.setState({ numberLocale: locale });
}

function renderTab() {
  render(
    <MemoryRouter>
      <InvoicesTab projectId="proj-1" />
    </MemoryRouter>,
  );
}

async function openTheInvoiceForm() {
  const user = userEvent.setup();
  renderTab();
  // The register offers the same action twice while it is empty (toolbar and
  // empty state); either opens the same form.
  const openers = await screen.findAllByRole('button', { name: /new invoice/i });
  await user.click(openers[0] as HTMLElement);
  return user;
}

const lineRows = () => screen.getAllByTestId('invoice-line');
const field = (label: string, row = 0) =>
  (screen.getAllByLabelText(label) as HTMLInputElement[])[row] as HTMLInputElement;
const createButton = () => screen.getByRole('button', { name: /^create$/i });

/** The last create request (a POST without a sub-path). */
function createdBody(): Record<string, unknown> {
  const hit = harness.posted.filter((p) => p.url.startsWith('/v1/finance/') && !p.url.includes('/pay'));
  return (hit[hit.length - 1]?.body ?? {}) as Record<string, unknown>;
}

/**
 * Put a figure in a field the way a finished edit or a paste arrives.
 *
 * Not keystroke by keystroke. A number field empties itself on an
 * intermediate "900." so a decimal never survives the trip, and under load
 * the controlled value lags far enough behind that characters are dropped -
 * both would make the test measure the harness rather than the form.
 */
function enter(input: HTMLInputElement, value: string) {
  fireEvent.change(input, { target: { value } });
}

beforeEach(() => {
  harness.posted.length = 0;
  harness.patched.length = 0;
  harness.invoices = [];
  harness.payments = [];
  harness.country = null;
  harness.taxRows = [];
});

afterEach(() => {
  readAs('en-US');
});

describe('#466 - an invoice is billed for the figure that was typed', () => {
  it('posts nine thousand when nine thousand was typed', async () => {
    readAs('en-US');
    const user = await openTheInvoiceForm();

    enter(field('Unit rate'), '9000');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = createdBody();
    expect(Number(body.amount_total)).toBe(9000);
    expect(Number(body.amount_subtotal)).toBe(9000);
    const lines = body.line_items as { amount: string }[];
    expect(lines).toHaveLength(1);
    expect(Number((lines[0] as { amount: string }).amount)).toBe(9000);
  });

  it('keeps the cents for a reader whose decimal mark is a comma', async () => {
    readAs('de-DE');
    const user = await openTheInvoiceForm();

    enter(field('Unit rate'), '900.50');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = createdBody();
    expect(Number(body.amount_total)).toBeCloseTo(900.5, 2);
    expect(Number(body.amount_subtotal)).toBeCloseTo(900.5, 2);
  });
});

describe('the invoice form takes lines with VAT per line', () => {
  it('adds VAT per line into Net, VAT and Gross and posts them', async () => {
    const user = await openTheInvoiceForm();

    enter(field('Quantity'), '2');
    enter(field('Unit rate'), '4500');
    enter(field('VAT %'), '25');
    await user.click(screen.getByRole('button', { name: /add line/i }));
    expect(lineRows()).toHaveLength(2);
    enter(field('Unit rate', 1), '1000');
    enter(field('VAT %', 1), '5');

    expect(screen.getByTestId('invoice-total-net').textContent).toMatch(/10,000/);
    expect(screen.getByTestId('invoice-total-gross').textContent).toMatch(/12,300/);

    await user.click(createButton());
    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = createdBody();
    expect(Number(body.amount_subtotal)).toBe(10000);
    expect(Number(body.tax_amount)).toBe(2300);
    expect(Number(body.amount_total)).toBe(12300);
    const lines = body.line_items as { amount: string; vat_rate: string | null; quantity: string }[];
    expect(lines.map((l) => [Number(l.amount), l.vat_rate])).toEqual([
      [9000, '25'],
      [1000, '5'],
    ]);
    expect(lines[0]?.quantity).toBe('2');
  });

  it('sends a typed 0 as 0 and an empty VAT field as null', async () => {
    const user = await openTheInvoiceForm();

    enter(field('Unit rate'), '100');
    enter(field('VAT %'), '0');
    await user.click(screen.getByRole('button', { name: /add line/i }));
    enter(field('Unit rate', 1), '200');
    enter(field('VAT %', 1), '');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const lines = createdBody().line_items as { vat_rate: string | null }[];
    // 0 is exempt or reverse-charged work; null asks the server for the
    // country's rate. Collapsing either into the other bills the wrong tax.
    expect(lines[0]?.vat_rate).toBe('0');
    expect(lines[1]?.vat_rate).toBeNull();
  });

  it('starts a line at the project country standard rate', async () => {
    harness.country = 'HR';
    harness.taxRows = [
      { rate_pct: '13.00', is_default: false, subdivision_code: null },
      { rate_pct: '25.00', is_default: true, subdivision_code: null },
      { rate_pct: '5.00', is_default: false, subdivision_code: null },
    ];
    const user = await openTheInvoiceForm();

    await waitFor(() => expect(field('VAT %').value).toBe('25'));
    enter(field('Unit rate'), '9000');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = createdBody();
    expect(Number(body.tax_amount)).toBe(2250);
    expect(Number(body.amount_total)).toBe(11250);
  });

  it('posts the supplier invoice number that was typed', async () => {
    const user = await openTheInvoiceForm();

    enter(screen.getByLabelText('Supplier invoice number') as HTMLInputElement, 'RE-2026-0415');
    enter(field('Unit rate'), '10');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    expect(createdBody().invoice_number).toBe('RE-2026-0415');
  });

  it('refuses an invoice whose lines carry no money', async () => {
    const user = await openTheInvoiceForm();

    expect(createButton()).toBeDisabled();
    await user.click(createButton());
    expect(harness.posted).toHaveLength(0);

    enter(field('Unit rate'), '10');
    expect(createButton()).toBeEnabled();
  });
});

describe('editing a stored invoice', () => {
  const stored = {
    id: 'inv-7',
    project_id: 'proj-1',
    invoice_number: 'RE-7',
    invoice_direction: 'payable',
    invoice_date: '2026-09-01',
    amount_subtotal: '1500.00',
    tax_amount: '300.00',
    amount_total: '1800.00',
    currency_code: 'EUR',
    status: 'approved',
    line_items: [
      { description: 'Rebar', quantity: '10', unit: 't', unit_rate: '100.00', amount: '1000.00', vat_rate: '20', cost_line_id: 'cl-1', wbs_id: 'w-1', cost_category: 'material', sort_order: 0 },
      { description: 'Crane', quantity: '1', unit: 'd', unit_rate: '500.00', amount: '500.00', vat_rate: '20', cost_line_id: null, wbs_id: 'w-2', cost_category: 'equipment', sort_order: 1 },
    ],
  };

  it('loads every stored line and sends no money when none of it changed', async () => {
    harness.invoices = [stored];
    harness.country = 'DE';
    harness.taxRows = [{ rate_pct: '19.00', is_default: true, subdivision_code: null }];
    const user = userEvent.setup();
    renderTab();

    await user.click(screen.getAllByRole('button', { name: /edit invoice/i })[0] as HTMLElement);
    expect(lineRows()).toHaveLength(2);
    // The stored rate stays, the country default does not overwrite it.
    expect(field('VAT %', 0).value).toBe('20');
    expect(screen.getByTestId('invoice-total-gross').textContent).toMatch(/1,800/);

    await user.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(harness.patched).toHaveLength(1));
    const body = harness.patched[0]?.body as Record<string, unknown>;
    expect(body).not.toHaveProperty('line_items');
    expect(body).not.toHaveProperty('amount_total');
  });

  it('keeps a line linked to its cost line when the lines are edited', async () => {
    harness.invoices = [stored];
    const user = userEvent.setup();
    renderTab();

    await user.click(screen.getAllByRole('button', { name: /edit invoice/i })[0] as HTMLElement);
    enter(field('Quantity', 1), '2');
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => expect(harness.patched).toHaveLength(1));
    const body = harness.patched[0]?.body as Record<string, unknown>;
    const lines = body.line_items as Record<string, unknown>[];
    expect(lines[0]).toMatchObject({ cost_line_id: 'cl-1', wbs_id: 'w-1', cost_category: 'material', amount: '1000.00' });
    expect(lines[1]).toMatchObject({ wbs_id: 'w-2', amount: '1000.00' });
    expect(Number(body.amount_subtotal)).toBe(2000);
    expect(Number(body.amount_total)).toBe(2400);
  });
});

describe('Mark Paid writes the payment before it closes the invoice', () => {
  it('records the open balance under a stable key, then pays', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    harness.invoices = [
      {
        id: 'inv-9',
        invoice_number: 'RE-9',
        invoice_direction: 'payable',
        invoice_date: '2026-09-01',
        amount_total: '1000.00',
        currency_code: 'EUR',
        status: 'approved',
        line_items: [],
      },
    ];
    harness.payments = [{ amount: '400.00', withholding_amount: '0', is_refund: false }];
    const user = userEvent.setup();
    renderTab();

    await user.click(screen.getAllByRole('button', { name: /^mark paid$/i })[0] as HTMLElement);

    await waitFor(() => expect(harness.posted.map((p) => p.url)).toEqual([
      '/v1/finance/invoices/inv-9/record-payment/',
      '/v1/finance/inv-9/pay/',
    ]));
    expect(harness.posted[0]?.body).toMatchObject({
      amount: '600.00',
      currency_code: 'EUR',
      idempotency_key: 'markpaid:inv-9',
    });
  });
});
