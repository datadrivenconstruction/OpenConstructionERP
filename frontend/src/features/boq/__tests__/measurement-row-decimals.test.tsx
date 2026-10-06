// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The drawer totals a sheet with the line rounding saved on it.
 *
 * A sheet can carry `row_decimals`: every line is rounded to that many
 * decimals before the lines are added, the way the file it came from was
 * totalled. The server does the arithmetic, so the drawer has to send the
 * rule with every recompute. Without it, ten lines of 1.005 under a
 * two-decimal rule show 10.05 in the drawer while the position holds 10.10,
 * and the reconcile reports a difference that is not there.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

interface SentBody {
  lines: unknown[];
  unit?: string;
  row_decimals?: number | null;
}

const { computeMeasurement, getMeasurement, sheet } = vi.hoisted(() => {
  const sheet = (extra: Record<string, unknown> = {}) => ({
    item_ref: '1',
    description: 'Plaster',
    unit: 'm2',
    lines: [{ description: 'Wall', formula: 'L', variables: { L: '1.005' }, factor: '1', sign: '+', quantity: '1.01' }],
    total_quantity: '1.01',
    has_errors: false,
    reconciliation: { matches: true, difference: '0' },
    ...extra,
  });
  return {
    computeMeasurement: vi.fn(async (_positionId: string, _body: SentBody) => sheet()),
    getMeasurement: vi.fn(async (_positionId: string) => sheet()),
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
  ordinal: '1',
  description: 'Plaster',
  unit: 'm2',
  quantity: 1.01,
} as unknown as Position;

async function typeIntoTheFirstRow() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MeasurementDrawer position={position} onClose={() => {}} onSave={() => {}} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getAllByRole('textbox').length).toBeGreaterThan(0));
  const inputs = screen
    .getAllByRole('textbox')
    .filter((el) => el.getAttribute('inputmode') === 'decimal') as HTMLInputElement[];
  fireEvent.change(inputs[1]!, { target: { value: '2' } });
  // Past the panel's 350ms debounce.
  await new Promise((resolve) => setTimeout(resolve, 450));
  await waitFor(() => expect(computeMeasurement).toHaveBeenCalled());
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('a sheet with a line rounding rule', () => {
  it('sends the rule with every recompute', async () => {
    getMeasurement.mockResolvedValueOnce(sheet({ row_decimals: 2 }));
    await typeIntoTheFirstRow();
    expect(computeMeasurement.mock.calls.at(-1)?.[1].row_decimals).toBe(2);
  });

  it('sends no rule for a sheet that has none', async () => {
    getMeasurement.mockResolvedValueOnce(sheet({ row_decimals: null }));
    await typeIntoTheFirstRow();
    expect(computeMeasurement.mock.calls.at(-1)?.[1].row_decimals ?? null).toBeNull();
  });
});
