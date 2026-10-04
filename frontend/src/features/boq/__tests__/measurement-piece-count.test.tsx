// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A row with only a count measures that many pieces.
 *
 * Doors, WC cubicles and anchors are counted, not measured: the estimator
 * types 64 into the count column and nothing into length, width or height.
 * The row used to go out as `0` times 64, so a counted position saved a
 * quantity of zero over the bill quantity it replaced. The count now goes
 * out as `1` times 64, and a sheet saved that way reads back into the count
 * column instead of loading as an empty row.
 *
 * Also held here: the figures the server sends back are written the way the
 * reader writes numbers, and the unit the way the bill editor writes it.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

interface SentLine {
  formula: string;
  variables: Record<string, string>;
  factor: string;
  sign: string;
}

const { computeMeasurement, getMeasurement } = vi.hoisted(() => {
  const sheet = (total: string, lines: unknown[] = []) => ({
    item_ref: '340.10',
    description: 'WC cubicles',
    unit: 'pcs',
    lines,
    total_quantity: total,
    has_errors: false,
    reconciliation: { matches: false, difference: '1002.5' },
  });
  return {
    computeMeasurement: vi.fn(
      async (_positionId: string, _body: { lines: SentLine[]; unit?: string }) => sheet('10602.5'),
    ),
    getMeasurement: vi.fn(async (_positionId: string) => sheet('0')),
    sheet,
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
  ordinal: '340.10',
  description: 'WC cubicles',
  unit: 'm2',
  quantity: 9600,
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

async function numericInputs(): Promise<HTMLInputElement[]> {
  renderDrawer();
  await waitFor(() => expect(screen.getAllByRole('textbox').length).toBeGreaterThan(0));
  return screen
    .getAllByRole('textbox')
    .filter((el) => el.getAttribute('inputmode') === 'decimal') as HTMLInputElement[];
}

/** Wait past the panel's 350ms debounce and let the request settle. */
async function settleDebounce() {
  await new Promise((resolve) => setTimeout(resolve, 450));
  await waitFor(() => expect(true).toBe(true));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  usePreferencesStore.setState({ numberLocale: 'en-US' });
});

describe('a row with only a count', () => {
  it('goes out as that many pieces, not as that many times zero', async () => {
    const [units] = await numericInputs();
    fireEvent.change(units!, { target: { value: '64' } });
    await settleDebounce();

    const line = computeMeasurement.mock.calls.at(-1)?.[1].lines[0];
    expect(line?.formula).toBe('1');
    expect(line?.factor).toBe('64');
  });

  it('reads a saved count back into the count column', async () => {
    getMeasurement.mockResolvedValueOnce({
      item_ref: '340.10',
      description: 'WC cubicles',
      unit: 'pcs',
      lines: [{ description: 'Per floor', formula: '1', variables: {}, factor: '64', sign: '+', quantity: '64' }],
      total_quantity: '64',
      has_errors: false,
    } as never);
    const [units, length] = await numericInputs();
    await waitFor(() => expect(units!.value).toBe('64'));
    expect(length!.value).toBe('');
    expect(length!.disabled).toBe(false);
  });

  it('a row with nothing typed still measures nothing', async () => {
    const [, length] = await numericInputs();
    fireEvent.change(length!, { target: { value: '2' } });
    fireEvent.change(length!, { target: { value: '' } });
    await settleDebounce();

    expect(computeMeasurement.mock.calls.at(-1)?.[1].lines[0]?.formula).toBe('0');
  });
});

describe('the figures the server sends back', () => {
  it('are written in the reader locale, with the unit as the bill writes it', async () => {
    usePreferencesStore.setState({ numberLocale: 'de-DE' });
    const [, length] = await numericInputs();
    fireEvent.change(length!, { target: { value: '4' } });
    await settleDebounce();

    await waitFor(() => expect(document.body.textContent).toContain('10.602,5 m²'));
    expect(document.body.textContent).toContain('9.600 m²');
    expect(document.body.textContent).not.toContain('10602.5');
  });
});
