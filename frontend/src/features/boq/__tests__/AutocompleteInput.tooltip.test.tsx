// @ts-nocheck
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';

// Hoisted mocks — must come before the component import so the dynamic
// `import('@/stores/useCostDatabaseStore')` inside AutocompleteInput is
// intercepted at module-resolution time.
vi.mock('@/stores/useCostDatabaseStore', () => ({
  useCostDatabaseStore: {
    getState: () => ({ activeRegion: undefined }),
  },
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    boqApi: {
      ...actual.boqApi,
      autocomplete: vi.fn(),
    },
  };
});

import { AutocompleteInput } from '../AutocompleteInput';
import { boqApi } from '../api';

const sampleItems = [
  {
    code: 'CW-CONC-30',
    description: 'Reinforced concrete wall C30/37',
    unit: 'm3',
    rate: 180.0,
    currency: 'EUR',
    region: 'DE_BERLIN',
    classification: { collection: 'Buildings', section: 'Walls' },
    components: [],
    cost_breakdown: { labor_cost: 45.5, material_cost: 110.0, equipment_cost: 24.5 },
    metadata_: { variant_count: 3 },
  },
  {
    code: 'CW-PLAIN',
    description: 'Plain concrete wall',
    unit: 'm3',
    rate: 120.0,
    currency: 'EUR',
    region: 'DE_BERLIN',
    classification: { collection: 'Buildings' },
    components: [],
    cost_breakdown: undefined,
    metadata_: undefined,
  },
];

beforeEach(() => {
  // Hover-capable device by default.
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: query.includes('hover: hover'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });

  (boqApi.autocomplete as any).mockReset();
  (boqApi.autocomplete as any).mockResolvedValue(sampleItems);

  Object.defineProperty(window, 'innerWidth', { value: 1280, configurable: true });
  Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
});

afterEach(() => {
  vi.useRealTimers();
});

/** Open the dropdown by typing a query and waiting for the debounce + fetch. */
async function openDropdown() {
  const onCommit = vi.fn();
  const onSelect = vi.fn();
  const onCancel = vi.fn();
  const utils = render(
    <AutocompleteInput
      value=""
      onCommit={onCommit}
      onSelectSuggestion={onSelect}
      onCancel={onCancel}
    />,
  );
  const input = screen.getByRole('textbox') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'concrete' } });
  // Debounce + dynamic import + resolved fetch — all on real timers.
  // ``findAllByTestId`` polls until the dropdown rows show up.
  await screen.findAllByTestId('autocomplete-suggestion');
  return { input, onCommit, onSelect, onCancel, ...utils };
}

describe('AutocompleteInput hover tooltip', () => {
  it('shows the tooltip after a 300ms hover delay', async () => {
    await openDropdown();
    const rows = screen.getAllByTestId('autocomplete-suggestion');
    expect(rows.length).toBeGreaterThan(0);

    vi.useFakeTimers();
    fireEvent.mouseEnter(rows[0]);
    // Below threshold — no tooltip yet.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();

    // Cross the threshold — tooltip appears synchronously after the timer.
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).not.toBeNull();
    vi.useRealTimers();
  });

  it('clears the tooltip on mouseleave', async () => {
    await openDropdown();
    const rows = screen.getAllByTestId('autocomplete-suggestion');

    vi.useFakeTimers();
    fireEvent.mouseEnter(rows[0]);
    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).not.toBeNull();

    fireEvent.mouseLeave(rows[0]);
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();
    vi.useRealTimers();
  });

  it('cancels a pending hover when mouseleave fires before the 300ms delay', async () => {
    await openDropdown();
    const rows = screen.getAllByTestId('autocomplete-suggestion');

    vi.useFakeTimers();
    fireEvent.mouseEnter(rows[0]);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    fireEvent.mouseLeave(rows[0]);
    // Even if we wait past 300ms now, the timer was cancelled.
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();
    vi.useRealTimers();
  });

  it('does not show the tooltip on keyboard arrow navigation', async () => {
    const { input } = await openDropdown();

    vi.useFakeTimers();
    // ArrowDown to highlight the first suggestion via keyboard.
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();
    vi.useRealTimers();
  });

  it('clears the tooltip when a key is pressed', async () => {
    const { input } = await openDropdown();
    const rows = screen.getAllByTestId('autocomplete-suggestion');

    vi.useFakeTimers();
    fireEvent.mouseEnter(rows[0]);
    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).not.toBeNull();

    // Any key clears the tooltip — keyboard navigation must take precedence.
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();
    vi.useRealTimers();
  });

  it('Tab on a hovered+selected suggestion picks it without race', async () => {
    const { input, onSelect } = await openDropdown();
    const rows = screen.getAllByTestId('autocomplete-suggestion');

    vi.useFakeTimers();
    // Hover triggers selection of index 0; let the tooltip render.
    fireEvent.mouseEnter(rows[0]);
    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).not.toBeNull();

    // Tab — must pick the highlighted suggestion AND clear the tooltip.
    fireEvent.keyDown(input, { key: 'Tab' });
    vi.useRealTimers();

    await waitFor(() => expect(onSelect).toHaveBeenCalledTimes(1));
    expect(onSelect.mock.calls[0][0].code).toBe('CW-CONC-30');
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();
  });

  it('skips the tooltip entirely on touch / no-hover devices', async () => {
    // Simulate a touch device: matchMedia('(hover: hover)') returns false.
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: () => ({
        matches: false,
        media: '',
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });

    await openDropdown();
    const rows = screen.getAllByTestId('autocomplete-suggestion');

    vi.useFakeTimers();
    fireEvent.mouseEnter(rows[0]);
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(document.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();
    vi.useRealTimers();
  });
});
