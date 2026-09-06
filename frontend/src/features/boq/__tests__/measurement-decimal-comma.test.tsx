// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A dimension typed with a decimal comma has to measure as that number.
 *
 * The take-off sheet's arithmetic is done on the server, and the server reads
 * every dimension with a helper that answers 0 for anything `Decimal()` will
 * not accept, and 1 for a factor. It does that silently: the formula evaluator
 * validates the EXPRESSION, so `L * B` over `{L: "3,5", B: "2"}` parses fine,
 * the line carries no error, and `has_errors` on the sheet stays false. The
 * panel would then show a total that is finite, plausible and short by a row,
 * with nothing on screen suggesting anything went wrong.
 *
 * Who types a decimal comma is not an edge case. It is Spain, Germany, France,
 * Italy, Brazil, Russia and most of the rest of the markets this ships in, and
 * the user whose question led to this panel wrote from one of them.
 *
 * So the assertion is on the REQUEST, not on the rendered total. A test that
 * only read the total would pass against a server stub that happens to echo
 * something sensible, and the defect being guarded here is precisely that the
 * wrong number looks right. The two directions are covered separately: a
 * number written the way half the world writes it must arrive canonicalised,
 * and something that is not a number at all must not be sent, because a
 * request built from it comes back looking like an answer.
 *
 * Real timers throughout. Faking them stalls the query that fills the columns,
 * so every one of these passes through an empty table and asserts nothing.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/** Only the parts of a line this test reads back. */
interface SentLine {
  formula: string;
  variables: Record<string, string>;
  factor: string;
  sign: string;
}

// Declared through vi.hoisted because vi.mock is lifted above them: a factory
// closing over plain consts would run before they are initialised. The
// parameters are typed so mock.calls keeps its shape; an untyped vi.fn infers
// a zero-argument call and every assertion about the request stops compiling.
const { computeMeasurement, getMeasurement } = vi.hoisted(() => {
  const sheet = (total: string) => ({
    item_ref: '01.01',
    description: 'Wall',
    unit: 'm2',
    lines: [],
    total_quantity: total,
    has_errors: false,
  });
  return {
    computeMeasurement: vi.fn(
      async (_positionId: string, _body: { lines: SentLine[]; unit?: string }) => sheet('7'),
    ),
    getMeasurement: vi.fn(async (_positionId: string) => sheet('0')),
  };
});

vi.mock('../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../api');
  return { ...actual, boqApi: { computeMeasurement, getMeasurement } };
});

import { MeasurementDrawer } from '../MeasurementDrawer';
import type { Position } from '../api';

const position = {
  id: 'pos-1',
  ordinal: '01.01',
  description: 'Wall',
  unit: 'm2',
  quantity: 7,
} as unknown as Position;

function renderDrawer() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MeasurementDrawer position={position} onClose={() => {}} onSave={() => {}} />
    </QueryClientProvider>,
  );
}

/** The four numeric inputs of the sheet's first row. */
interface FirstRow {
  units: HTMLInputElement;
  length: HTMLInputElement;
  width: HTMLInputElement;
  height: HTMLInputElement;
}

/**
 * Render, wait for the columns to fill, and hand back the first row's inputs.
 *
 * They are found by `inputMode="decimal"` rather than by a test id, so the
 * test breaks if the columns stop being editable, which is the thing it is
 * really guarding.
 */
async function openSheet(): Promise<FirstRow> {
  renderDrawer();
  await waitFor(() => expect(screen.getAllByRole('textbox').length).toBeGreaterThan(0));
  const [units, length, width, height] = screen
    .getAllByRole('textbox')
    .filter((el) => el.getAttribute('inputmode') === 'decimal') as HTMLInputElement[];
  if (!units || !length || !width || !height) {
    throw new Error('the sheet did not render a full row of numeric columns');
  }
  return { units, length, width, height };
}

/** Wait past the panel's 350ms debounce and let the request settle. */
async function settleDebounce() {
  await new Promise((resolve) => setTimeout(resolve, 450));
  await waitFor(() => expect(true).toBe(true));
}

/** The first line of the last request the panel sent. */
function lastFirstLine(): SentLine {
  const line = computeMeasurement.mock.calls.at(-1)?.[1].lines[0];
  if (!line) throw new Error('the panel sent no measurement line');
  return line;
}

/** The button that writes the measured total back onto the position. */
function applyButton(): HTMLButtonElement {
  // Located by the translation key: these tests run without locale resources,
  // so i18next echoes the key rather than the English.
  const found = screen
    .getAllByRole('button')
    .find((b) => b.textContent === 'boq.measurement.apply');
  if (!found) throw new Error('the sheet has no apply button');
  return found as HTMLButtonElement;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('a dimension typed with a decimal comma', () => {
  it('reaches the server as a dot decimal, not as zero', async () => {
    const row = await openSheet();
    fireEvent.change(row.length, { target: { value: '3,5' } });
    fireEvent.change(row.width, { target: { value: '2' } });
    await settleDebounce();

    expect(computeMeasurement).toHaveBeenCalled();
    const line = lastFirstLine();
    expect(line.variables.L).toBe('3.5');
    expect(line.variables.B).toBe('2');
    // The formula names exactly the dimensions that were filled in. If it were
    // to carry an H the server would reject the line as an unknown variable,
    // which is the one case where this defect would have been visible.
    expect(line.formula).toBe('L * B');
  });

  it('carries a grouped thousands separator through as one number', async () => {
    const row = await openSheet();
    fireEvent.change(row.length, { target: { value: '1.234,56' } });
    await settleDebounce();

    expect(lastFirstLine().variables.L).toBe('1234.56');
  });

  it('repeats a line by a factor written with a comma', async () => {
    const row = await openSheet();
    fireEvent.change(row.units, { target: { value: '2,5' } });
    fireEvent.change(row.length, { target: { value: '4' } });
    await settleDebounce();

    // Sent as "2,5" the server's factor helper falls back to 1, so the line
    // would have been counted once instead of two and a half times.
    expect(lastFirstLine().factor).toBe('2.5');
  });
});

describe('a dimension that is not a number at all', () => {
  it('is never sent, so no total can be built from it', async () => {
    const row = await openSheet();
    fireEvent.change(row.length, { target: { value: '4' } });
    await settleDebounce();
    const callsWithGoodInput = computeMeasurement.mock.calls.length;
    expect(callsWithGoodInput).toBeGreaterThan(0);

    fireEvent.change(row.width, { target: { value: '10abc' } });
    await settleDebounce();

    // No new request. The previous total stays on screen rather than being
    // replaced by one silently missing this row.
    expect(computeMeasurement.mock.calls.length).toBe(callsWithGoodInput);
  });

  it('marks the field it is in, and only that field', async () => {
    const row = await openSheet();
    fireEvent.change(row.length, { target: { value: '4' } });
    fireEvent.change(row.width, { target: { value: 'wide' } });
    await settleDebounce();

    expect(row.width.getAttribute('aria-invalid')).toBe('true');
    expect(row.length.getAttribute('aria-invalid')).toBeNull();
  });

  it('stops the sheet from being applied to the quantity', async () => {
    const row = await openSheet();
    fireEvent.change(row.length, { target: { value: '4' } });
    await settleDebounce();

    const apply = applyButton();
    await waitFor(() => expect(apply.disabled).toBe(false));

    fireEvent.change(row.width, { target: { value: '??' } });
    await settleDebounce();
    expect(apply.disabled).toBe(true);
  });

  it('lets a half-typed number through, so the row does not flash red', async () => {
    const row = await openSheet();
    // What the field holds after the comma keystroke of "3,5".
    fireEvent.change(row.length, { target: { value: '3,' } });
    await settleDebounce();

    expect(row.length.getAttribute('aria-invalid')).toBeNull();
    expect(lastFirstLine().variables.L).toBe('3.');
  });
});
