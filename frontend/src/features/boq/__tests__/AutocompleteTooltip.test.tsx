// @ts-nocheck
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AutocompleteTooltip } from '../AutocompleteTooltip';
import type { CostAutocompleteItem } from '../api';

function makeRect(overrides: Partial<DOMRect> = {}): DOMRect {
  const base: DOMRect = {
    left: 100,
    top: 200,
    right: 580,
    bottom: 240,
    width: 480,
    height: 40,
    x: 100,
    y: 200,
    toJSON() {
      return {};
    },
  };
  return { ...base, ...overrides } as DOMRect;
}

function makeItem(overrides: Partial<CostAutocompleteItem> = {}): CostAutocompleteItem {
  return {
    code: 'CW-CONC-30',
    description: 'Reinforced concrete wall C30/37, 24cm, with formwork and rebar',
    unit: 'm3',
    rate: 180.0,
    currency: 'EUR',
    region: 'DE_BERLIN',
    classification: {
      collection: 'Buildings',
      department: 'Concrete',
      section: 'Walls',
      subsection: 'Reinforced',
    },
    components: [],
    cost_breakdown: {
      labor_cost: 45.5,
      material_cost: 110.0,
      equipment_cost: 24.5,
    },
    metadata_: {
      variant_count: 3,
      variant_stats: { unit: 'm³', group: 'Concrete' },
    },
    ...overrides,
  };
}

beforeEach(() => {
  // Default to a wide viewport so the tooltip stays on the right side.
  Object.defineProperty(window, 'innerWidth', { value: 1280, configurable: true });
  Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
});

describe('AutocompleteTooltip', () => {
  it('renders the full description, code, region, rate, and unit', () => {
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );

    expect(screen.getByTestId('autocomplete-tooltip')).toBeTruthy();
    expect(
      screen.getByText('Reinforced concrete wall C30/37, 24cm, with formwork and rebar'),
    ).toBeTruthy();
    expect(screen.getByText('CW-CONC-30')).toBeTruthy();
    expect(screen.getByTestId('autocomplete-tooltip-region').textContent).toBe('DE_BERLIN');
    // Rate + unit
    expect(screen.getByText(/180\.00/)).toBeTruthy();
    expect(screen.getByText(/m3/)).toBeTruthy();
  });

  it('renders the labor / material / equipment breakdown', () => {
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );

    const breakdown = screen.getByTestId('autocomplete-tooltip-breakdown');
    expect(breakdown).toBeTruthy();
    expect(breakdown.textContent).toMatch(/Labor/);
    expect(breakdown.textContent).toMatch(/Material/);
    expect(breakdown.textContent).toMatch(/Equipment/);
    expect(breakdown.textContent).toMatch(/45\.50/);
    expect(breakdown.textContent).toMatch(/110\.00/);
    expect(breakdown.textContent).toMatch(/24\.50/);
  });

  it('hides breakdown section when no breakdown data is present', () => {
    render(
      <AutocompleteTooltip
        item={makeItem({ cost_breakdown: undefined })}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );

    expect(screen.queryByTestId('autocomplete-tooltip-breakdown')).toBeNull();
  });

  it('renders the classification path when present', () => {
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );

    const cls = screen.getByTestId('autocomplete-tooltip-classification');
    expect(cls.textContent).toMatch(/Buildings/);
    expect(cls.textContent).toMatch(/Concrete/);
    expect(cls.textContent).toMatch(/Walls/);
  });

  it('shows variants indicator when variant_count >= 2', () => {
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );

    const variants = screen.getByTestId('autocomplete-tooltip-variants');
    expect(variants).toBeTruthy();
    expect(variants.textContent).toMatch(/3/);
  });

  it('hides variant indicator when variant_count < 2', () => {
    render(
      <AutocompleteTooltip
        item={makeItem({ metadata_: { variant_count: 1 } })}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );

    expect(screen.queryByTestId('autocomplete-tooltip-variants')).toBeNull();
  });

  it('renders the "Tab to insert" hint at the bottom', () => {
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );
    expect(screen.getByText(/Tab or Enter to insert/)).toBeTruthy();
  });

  it('uses pointer-events: none so it never steals input from the dropdown', () => {
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );
    const node = screen.getByTestId('autocomplete-tooltip');
    expect((node as HTMLElement).style.pointerEvents).toBe('none');
  });

  it('positions the tooltip to the right of the anchor by default', () => {
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect({ right: 580 })}
        currencySymbol="€"
      />,
    );
    const node = screen.getByTestId('autocomplete-tooltip') as HTMLElement;
    // 580 (anchor.right) + 8 (gutter) = 588.
    expect(node.style.left).toBe('588px');
  });

  it('auto-flips to the left side when the right edge would overflow', () => {
    // Narrow viewport: right side won't fit a 320 px tooltip with gutter.
    Object.defineProperty(window, 'innerWidth', { value: 800, configurable: true });
    render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect({ left: 480, right: 750 })}
        currencySymbol="€"
      />,
    );
    const node = screen.getByTestId('autocomplete-tooltip') as HTMLElement;
    // Right side: 750 + 8 = 758, plus 320 width = 1078 > 800 → flip.
    // Flipped left = max(12, 480 - 320 - 8) = 152.
    const left = parseInt(node.style.left, 10);
    // The flipped position must be on the left of the anchor.
    expect(left).toBeLessThan(480);
    // And clamped to the viewport-padding minimum.
    expect(left).toBeGreaterThanOrEqual(12);
  });

  it('renders into document.body via a portal', () => {
    const { container } = render(
      <AutocompleteTooltip
        item={makeItem()}
        anchorRect={makeRect()}
        currencySymbol="€"
      />,
    );
    // The tooltip lives in document.body, NOT inside the test container.
    expect(container.querySelector('[data-testid="autocomplete-tooltip"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="autocomplete-tooltip"]')).not.toBeNull();
  });
});
