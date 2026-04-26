// @ts-nocheck
/**
 * Tests for CascadeFilterPanel (T04).
 *
 * Covers:
 *   - debounced cascade fetch — typing into a card doesn't fire a
 *     request on every keystroke
 *   - chip add/remove flow — clicking a candidate adds a chip,
 *     clicking the chip's X removes it, both routing through onChange
 *   - "Reset all" wipes every selection and triggers onChange({})
 *   - the live row counter renders the matched/total response
 *   - clearing a single column leaves the other column untouched
 *
 * Note on stubbing: we mock the `../api` module rather than installing
 * MSW. The repo's existing MSW integration suite (`tests/api-mocks`) is
 * skipped because of a known jsdom 29 + Node 24 + MSW 2 fetch / Headers
 * incompatibility — relying on it here would make the test flaky on
 * exactly the platforms developers run locally. `vi.mock` keeps the
 * test deterministic and matches the convention used by the sibling
 * `SmartValueAutocomplete.test.tsx`.
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { useState } from 'react';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getCascadeValues: vi.fn(),
    getCascadeRowCount: vi.fn(),
  };
});

import { getCascadeRowCount, getCascadeValues } from '../api';
import {
  CascadeFilterPanel,
  type CascadeSelection,
} from '../CascadeFilterPanel';

/* ── Fixture stubs ───────────────────────────────────────────────────── */

const SNAPSHOT_ID = 'snap-1';

const cascadeValuesByColumn: Record<
  string,
  Array<{ value: string; count: number }>
> = {
  category: [
    { value: 'Concrete', count: 12 },
    { value: 'Steel', count: 8 },
    { value: 'Wood', count: 1 },
  ],
  supplier: [
    { value: 'AcmeCo', count: 14 },
    { value: 'BetaCo', count: 5 },
  ],
};

beforeEach(() => {
  (getCascadeValues as ReturnType<typeof vi.fn>).mockReset();
  (getCascadeRowCount as ReturnType<typeof vi.fn>).mockReset();

  // Default: filter values by `q` (case-insensitive substring) when
  // present, return everything otherwise. Mirrors what the real
  // backend does after our DuckDB ILIKE.
  (getCascadeValues as ReturnType<typeof vi.fn>).mockImplementation(
    (_snapshotId: string, body: { target_column: string; q?: string }) => {
      const all = cascadeValuesByColumn[body.target_column] ?? [];
      const filtered = body.q
        ? all.filter((v) =>
            v.value.toLowerCase().includes(body.q!.toLowerCase()),
          )
        : all;
      return Promise.resolve({
        snapshot_id: SNAPSHOT_ID,
        target_column: body.target_column,
        q: body.q ?? '',
        values: filtered,
      });
    },
  );

  (getCascadeRowCount as ReturnType<typeof vi.fn>).mockImplementation(
    (_snapshotId: string, selected: Record<string, string[]>) => {
      const total = 21;
      const matched =
        Object.keys(selected).length === 0
          ? total
          : Object.values(selected).reduce(
              (acc, arr) => acc + arr.length * 5,
              0,
            );
      return Promise.resolve({
        snapshot_id: SNAPSHOT_ID,
        matched,
        total,
      });
    },
  );
});

afterEach(() => {
  cleanup();
});

/* ── Test harness ────────────────────────────────────────────────────── */

function renderPanel(initial: CascadeSelection = {}, debounceMs = 30) {
  function Harness() {
    const [value, setValue] = useState<CascadeSelection>(initial);
    return (
      <CascadeFilterPanel
        snapshotId={SNAPSHOT_ID}
        columns={['category', 'supplier']}
        value={value}
        onChange={setValue}
        debounceMs={debounceMs}
      />
    );
  }

  // Each test gets its own QueryClient to avoid cache leakage.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}

/* ── Tests ───────────────────────────────────────────────────────────── */

describe('CascadeFilterPanel', () => {
  it('calls getCascadeRowCount on mount and renders the row counter', async () => {
    renderPanel();
    // The row-count endpoint is called with the empty selection on
    // mount. Once it resolves, the counter element switches off the
    // "loading" state — we assert on the post-resolution textContent
    // having content (the i18n mock returns the literal default-value
    // template, which is still useful: the real app interpolates it
    // server-side via i18next).
    await waitFor(() => {
      expect(getCascadeRowCount).toHaveBeenCalledWith(SNAPSHOT_ID, {});
    });
    await waitFor(() => {
      const text = screen.getByTestId('cascade-row-count').textContent ?? '';
      // After the fetch resolves the loading template ('Counting rows…')
      // must have been swapped for the rows-match template.
      expect(text).not.toMatch(/Counting rows/);
      expect(text).toMatch(/rows match/);
    });
  });

  it('renders a card per column with options from the cascade endpoint', async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId('cascade-card-category')).toBeInTheDocument();
      expect(screen.getByTestId('cascade-card-supplier')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(
        screen.getByTestId('cascade-option-category-Concrete'),
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('cascade-option-supplier-AcmeCo'),
      ).toBeInTheDocument();
    });
  });

  it('clicking a candidate adds it as a chip and the supplier card refetches with the new selection', async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByTestId('cascade-option-category-Concrete'),
      ).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId('cascade-option-category-Concrete'));

    await waitFor(() => {
      expect(
        screen.getByTestId('cascade-chip-category-Concrete'),
      ).toBeInTheDocument();
    });

    // Re-running the supplier card's fetch picks up category=[Concrete]
    // in the `selected` map (the cascade flow).
    await waitFor(() => {
      const supplierCalls = (
        getCascadeValues as ReturnType<typeof vi.fn>
      ).mock.calls.filter((c) => c[1]?.target_column === 'supplier');
      const last = supplierCalls[supplierCalls.length - 1];
      expect(last?.[1]?.selected).toEqual({ category: ['Concrete'] });
    });
  });

  it('removing a chip clears it from the selection', async () => {
    renderPanel({ category: ['Concrete'] });
    await waitFor(() =>
      expect(
        screen.getByTestId('cascade-chip-category-Concrete'),
      ).toBeInTheDocument(),
    );

    fireEvent.click(
      screen.getByTestId('cascade-chip-x-category-Concrete'),
    );

    await waitFor(() => {
      expect(
        screen.queryByTestId('cascade-chip-category-Concrete'),
      ).not.toBeInTheDocument();
    });
  });

  it('Reset all wipes every selection in one click', async () => {
    renderPanel({
      category: ['Concrete', 'Steel'],
      supplier: ['AcmeCo'],
    });

    await waitFor(() => {
      expect(
        screen.getByTestId('cascade-chip-category-Concrete'),
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('cascade-chip-supplier-AcmeCo'),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('cascade-reset-all'));

    await waitFor(() => {
      expect(
        screen.queryByTestId('cascade-chip-category-Concrete'),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('cascade-chip-category-Steel'),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('cascade-chip-supplier-AcmeCo'),
      ).not.toBeInTheDocument();
    });
  });

  it('Clear-on-column wipes only that column', async () => {
    renderPanel({
      category: ['Concrete'],
      supplier: ['AcmeCo'],
    });
    await waitFor(() =>
      expect(
        screen.getByTestId('cascade-chip-category-Concrete'),
      ).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId('cascade-clear-category'));

    await waitFor(() => {
      expect(
        screen.queryByTestId('cascade-chip-category-Concrete'),
      ).not.toBeInTheDocument();
      expect(
        screen.getByTestId('cascade-chip-supplier-AcmeCo'),
      ).toBeInTheDocument();
    });
  });

  it('debounces the cascade fetch — typing fast does not fire a request per keystroke', async () => {
    renderPanel({}, 60);
    // Wait for the initial mount fetches to settle.
    await waitFor(() =>
      expect(
        screen.getByTestId('cascade-option-category-Concrete'),
      ).toBeInTheDocument(),
    );

    const baseline = (getCascadeValues as ReturnType<typeof vi.fn>).mock.calls
      .filter((c) => c[1]?.target_column === 'category')
      .length;

    const input = screen.getByTestId('cascade-input-category');
    fireEvent.change(input, { target: { value: 'c' } });
    fireEvent.change(input, { target: { value: 'co' } });
    fireEvent.change(input, { target: { value: 'con' } });

    // Wait until the debounced fetch with 'con' actually fires.
    await waitFor(
      () => {
        const calls = (
          getCascadeValues as ReturnType<typeof vi.fn>
        ).mock.calls.filter((c) => c[1]?.target_column === 'category');
        const last = calls[calls.length - 1];
        expect(last?.[1]?.q).toBe('con');
      },
      { timeout: 1500 },
    );

    const finalCalls = (
      getCascadeValues as ReturnType<typeof vi.fn>
    ).mock.calls.filter((c) => c[1]?.target_column === 'category');

    // Exactly one new call beyond the baseline — every keystroke
    // restarted the debounce timer, so only the final string fires.
    expect(finalCalls.length).toBe(baseline + 1);
    // Intermediate prefixes never reach the network.
    expect(finalCalls.some((c) => c[1]?.q === 'c')).toBe(false);
    expect(finalCalls.some((c) => c[1]?.q === 'co')).toBe(false);
  });
});
