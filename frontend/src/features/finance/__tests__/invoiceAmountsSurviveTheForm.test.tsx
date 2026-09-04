// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #466 - the invoice total emptied itself once the figure reached a thousand.
 *
 * The blank field was the visible half. The cause is that the auto-filled
 * total was written through a display formatter: `fmtFixed` groups thousands
 * and writes the reader's decimal mark, a `<input type="number">` refuses any
 * value carrying either, and the same string is what the form reads back when
 * it builds the request. `parseFloat('9,000.00')` is 9 and
 * `parseFloat('900,50')` is 900, so the figure that left the screen was not
 * the figure the person typed.
 *
 * These tests drive the sequence a person performs - open the form, type into
 * a field, press Create - and assert on the request that leaves. Formatting a
 * number and reading it straight back would pass against the broken form,
 * because both halves of that round trip are the formatter.
 *
 * Both conventions are covered on purpose. Under a point-decimal reader the
 * loss starts at a thousand, where grouping begins. Under a comma-decimal
 * reader every invoice with cents loses them, at any size.
 *
 * Run:  npx vitest run src/features/finance/__tests__/invoiceAmountsSurviveTheForm.test.tsx
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { InvoicesTab } from '../FinancePage';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

const harness = vi.hoisted(() => ({
  posted: [] as Record<string, unknown>[],
  patched: [] as { url: string; body: Record<string, unknown> }[],
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

// One canned payload answers every query this tab makes: the invoice register
// reads `items`/`total`, the dashboard reads `currency`. `select` is applied
// where a query declares one, because the register maps its rows through it.
vi.mock('@tanstack/react-query', () => ({
  useQuery: (opts: { select?: (d: unknown) => unknown }) => {
    const raw = { items: [], total: 0, currency: 'EUR' };
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
  apiGet: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  apiPost: vi.fn((_url: string, body: Record<string, unknown>) => {
    harness.posted.push(body);
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

/** The number-format preference `fmtFixed` reads, per test. */
function readAs(locale: 'en-US' | 'de-DE') {
  usePreferencesStore.setState({ numberLocale: locale });
}

async function openTheInvoiceForm() {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <InvoicesTab projectId="proj-1" />
    </MemoryRouter>,
  );
  // The register offers the same action twice while it is empty (toolbar and
  // empty state); either opens the same form.
  const openers = await screen.findAllByRole('button', { name: /new invoice/i });
  await user.click(openers[0] as HTMLElement);
  return user;
}

// The three money fields carry the same placeholder and no label association,
// so they are taken in document order: subtotal, tax, then the total.
const moneyFields = () => screen.getAllByPlaceholderText('0.00') as HTMLInputElement[];
const subtotalField = () => moneyFields()[0] as HTMLInputElement;
const totalField = () => screen.getByLabelText('Total') as HTMLInputElement;
const createButton = () => screen.getByRole('button', { name: /^create$/i });

/**
 * Put a figure in a money field the way a finished edit or a paste arrives.
 *
 * Not keystroke by keystroke. A number field empties itself on an
 * intermediate "900." so a decimal never survives the trip, and under load
 * the controlled value lags far enough behind that characters are dropped -
 * both would make the test measure the harness rather than the form. What
 * this drives is the same handler a person's typing drives.
 */
function enter(field: HTMLInputElement, value: string) {
  fireEvent.change(field, { target: { value } });
}

beforeEach(() => {
  harness.posted.length = 0;
  harness.patched.length = 0;
});

afterEach(() => {
  readAs('en-US');
});

describe('#466 - an invoice is billed for the figure that was typed', () => {
  it('keeps the auto-filled total in a form the field itself accepts', async () => {
    readAs('en-US');
    await openTheInvoiceForm();

    enter(subtotalField(), '9000');

    // Whatever the form put in the total field has to be a number that field
    // can hold. A grouped string is rejected by the control, which is how this
    // reached us: the total looked empty from a thousand upwards.
    await waitFor(() => expect(Number(totalField().value)).toBe(9000));
  });

  it('posts nine thousand when nine thousand was typed', async () => {
    readAs('en-US');
    const user = await openTheInvoiceForm();

    enter(subtotalField(), '9000');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = harness.posted[0] as Record<string, unknown>;
    expect(Number(body.amount_total)).toBe(9000);
    expect(Number(body.amount_subtotal)).toBe(9000);
    // The single lump-sum line the form writes is the same money. A line that
    // disagrees with its own invoice is the shape the server check refuses.
    const lines = body.line_items as { amount: string }[];
    expect(lines).toHaveLength(1);
    expect(Number((lines[0] as { amount: string }).amount)).toBe(9000);
  });

  it('keeps the cents for a reader whose decimal mark is a comma', async () => {
    readAs('de-DE');
    const user = await openTheInvoiceForm();

    enter(subtotalField(), '900.50');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = harness.posted[0] as Record<string, unknown>;
    // 900,50 read back through `parseFloat` is 900. The cents are the whole
    // defect here, and it does not wait for a thousand to show up.
    expect(Number(body.amount_total)).toBeCloseTo(900.5, 2);
    expect(Number(body.amount_subtotal)).toBeCloseTo(900.5, 2);
  });

  it('sends a subtotal when only a total was typed, rather than a zero', async () => {
    readAs('en-US');
    const user = await openTheInvoiceForm();

    enter(totalField(), '9000');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = harness.posted[0] as Record<string, unknown>;
    // The server derives the stored total from subtotal + tax. Posting a
    // subtotal of zero beside a total of nine thousand stored zero, with a
    // nine-thousand line item sitting next to it.
    expect(Number(body.amount_subtotal)).toBe(9000);
    expect(Number(body.amount_total)).toBe(9000);
  });

  it('refuses a hand-typed total that does not agree with subtotal plus tax', async () => {
    readAs('en-US');
    const user = await openTheInvoiceForm();

    enter(subtotalField(), '9000');
    enter(totalField(), '8000');
    await user.click(createButton());

    // Nothing is posted, and the disagreement is named on screen rather than
    // quietly resolved in one direction or the other.
    expect(harness.posted).toHaveLength(0);
    expect(await screen.findByText(/must equal the subtotal plus tax/i)).toBeInTheDocument();
  });

  it('sends a document that adds up when only the tax field was filled', async () => {
    readAs('en-US');
    const user = await openTheInvoiceForm();

    // Tax on its own is an odd thing to enter, and it is the one route through
    // the form that no other test here drives. It used to reach the old
    // `sub > 0 ? sub : total` fallback and post a line item for a figure the
    // subtotal did not claim.
    enter(moneyFields()[1] as HTMLInputElement, '9000');
    await user.click(createButton());

    await waitFor(() => expect(harness.posted).toHaveLength(1));
    const body = harness.posted[0] as Record<string, unknown>;
    // Degenerate but coherent, which is the property the server now enforces:
    // subtotal plus tax is the total, and nothing claims to be a line of a
    // subtotal of zero.
    expect(Number(body.amount_subtotal) + Number(body.tax_amount)).toBeCloseTo(
      Number(body.amount_total),
      2,
    );
    expect(body.line_items).toHaveLength(0);
  });
});
