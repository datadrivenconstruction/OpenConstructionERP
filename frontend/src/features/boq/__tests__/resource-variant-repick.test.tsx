// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// EditableResourceRow contract tests for the v2.6.26 per-resource variant
// re-pick pill:
//   • Pill visible when `available_variants` is cached on the resource entry
//   • Pill hidden when `available_variants` missing or has < 2 entries
//   • Clicking the pill opens the inline `VariantPicker` portal
//   • Provenance bar tone follows variant_default vs explicit pick
//
// These exercise only the visibility branch of EditableResourceRow against
// pre-baked grid context, NOT the full BOQGrid render pipeline. The picker's
// own contract (radio selection, default index resolution) is covered by
// `variant-picker.test.tsx`.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EditableResourceRow } from '../grid/cellRenderers';
import type { CostVariant, VariantStats } from '../../costs/api';

/* ── Test helpers ──────────────────────────────────────────────────────── */

const STATS: VariantStats = {
  min: 165,
  max: 215,
  mean: 188,
  median: 185,
  unit: 'm3',
  group: 'concrete',
  count: 3,
};

const VARIANTS: CostVariant[] = [
  { index: 0, label: 'C25/30', price: 165, price_per_unit: null },
  { index: 1, label: 'C30/37', price: 185, price_per_unit: null },
  { index: 2, label: 'C35/45', price: 215, price_per_unit: null },
];

const COL_WIDTHS = {
  leftPad: 0,
  ordinal: 60,
  bimLink: 28,
  classification: 0,
  unit: 60,
  bimQty: 28,
  quantity: 80,
  unitRate: 100,
  total: 100,
  actions: 60,
};

function renderRow({
  resourceData = {},
  ctx = {},
}: {
  resourceData?: Record<string, unknown>;
  ctx?: Record<string, unknown>;
} = {}) {
  const data: Record<string, unknown> = {
    _isResource: true,
    _parentPositionId: 'pos-1',
    _resourceIndex: 0,
    _resourceName: 'Concrete',
    _resourceType: 'material',
    _resourceUnit: 'm3',
    _resourceQty: 1,
    _resourceRate: 185,
    _resourceCode: 'BET.C30',
    ...resourceData,
  };
  const onRepickResourceVariant = vi.fn();
  const fullCtx = {
    currencySymbol: '€',
    currencyCode: 'EUR',
    locale: 'en-US',
    fmt: new Intl.NumberFormat('en-US', { minimumFractionDigits: 2 }),
    fxRates: [],
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts && typeof opts === 'object' && 'defaultValue' in opts) {
        let str = String(opts.defaultValue);
        for (const k of Object.keys(opts)) {
          if (k === 'defaultValue') continue;
          str = str.replace(new RegExp(`{{${k}}}`, 'g'), String(opts[k]));
        }
        return str;
      }
      return key;
    },
    onUpdateResource: vi.fn(),
    onUpdateResourceFields: vi.fn(),
    onRemoveResource: vi.fn(),
    onSaveResourceToCatalog: vi.fn(),
    onShowContextMenu: vi.fn(),
    onRepickResourceVariant,
    ...ctx,
  };
  render(
    // EditableResourceRow expects a ctx typed as FullGridContext but only reads
    // the fields above — cast loosely so tests stay legible.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    <EditableResourceRow data={data} ctx={fullCtx as any} colWidths={COL_WIDTHS} />,
  );
  return { onRepickResourceVariant };
}

/* ── Tests ─────────────────────────────────────────────────────────────── */

describe('EditableResourceRow — variant re-pick pill (v2.6.26)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the re-pick pill when available_variants has 2+ entries', () => {
    renderRow({
      resourceData: {
        _resourceAvailableVariants: VARIANTS,
        _resourceAvailableVariantStats: STATS,
        _resourceVariant: { label: 'C30/37', price: 185, index: 1 },
      },
    });
    const pill = screen.getByTestId('resource-variant-pill-0');
    expect(pill).toBeInTheDocument();
    // Pill text reflects the option count.
    expect(pill.textContent).toContain('3');
  });

  it('hides the re-pick pill when available_variants is missing', () => {
    renderRow({
      resourceData: {
        // No _resourceAvailableVariants — legacy row.
      },
    });
    expect(screen.queryByTestId('resource-variant-pill-0')).toBeNull();
  });

  it('hides the re-pick pill when available_variants has < 2 entries', () => {
    renderRow({
      resourceData: {
        _resourceAvailableVariants: [VARIANTS[0]],
        _resourceAvailableVariantStats: { ...STATS, count: 1 },
      },
    });
    expect(screen.queryByTestId('resource-variant-pill-0')).toBeNull();
  });

  it('hides the re-pick pill when onRepickResourceVariant callback is not wired', () => {
    renderRow({
      resourceData: {
        _resourceAvailableVariants: VARIANTS,
        _resourceAvailableVariantStats: STATS,
      },
      ctx: { onRepickResourceVariant: undefined },
    });
    // Graceful degrade — the row should still render without crashing.
    expect(screen.queryByTestId('resource-variant-pill-0')).toBeNull();
  });

  it('opens the VariantPicker portal when the pill is clicked', () => {
    renderRow({
      resourceData: {
        _resourceAvailableVariants: VARIANTS,
        _resourceAvailableVariantStats: STATS,
        _resourceVariant: { label: 'C30/37', price: 185, index: 1 },
      },
    });
    const pill = screen.getByTestId('resource-variant-pill-0');
    fireEvent.click(pill);
    // VariantPicker exposes its Apply button via data-testid.
    expect(screen.getByTestId('variant-picker-apply')).toBeInTheDocument();
  });

  it('calls onRepickResourceVariant with the chosen variant label on Apply', () => {
    const { onRepickResourceVariant } = renderRow({
      resourceData: {
        _resourceAvailableVariants: VARIANTS,
        _resourceAvailableVariantStats: STATS,
        _resourceVariant: { label: 'C30/37', price: 185, index: 1 },
      },
    });
    fireEvent.click(screen.getByTestId('resource-variant-pill-0'));
    // Pick the third variant.
    fireEvent.click(screen.getByTestId('variant-row-2'));
    fireEvent.click(screen.getByTestId('variant-picker-apply'));
    expect(onRepickResourceVariant).toHaveBeenCalledTimes(1);
    expect(onRepickResourceVariant).toHaveBeenCalledWith('pos-1', 0, 'C35/45');
  });

  it('renders a blue provenance bar for an explicit variant pick', () => {
    renderRow({
      resourceData: {
        _resourceAvailableVariants: VARIANTS,
        _resourceAvailableVariantStats: STATS,
        _resourceVariant: { label: 'C30/37', price: 185, index: 1 },
      },
    });
    expect(screen.getByTestId('resource-variant-bar-0-blue')).toBeInTheDocument();
    expect(screen.queryByTestId('resource-variant-bar-0-amber')).toBeNull();
  });

  it('renders an amber provenance bar for an auto-default pick', () => {
    renderRow({
      resourceData: {
        _resourceAvailableVariants: VARIANTS,
        _resourceAvailableVariantStats: STATS,
        _resourceVariantDefault: 'mean',
      },
    });
    expect(screen.getByTestId('resource-variant-bar-0-amber')).toBeInTheDocument();
    expect(screen.queryByTestId('resource-variant-bar-0-blue')).toBeNull();
  });

  it('renders no provenance bar when no variant marker is set', () => {
    renderRow({
      resourceData: {
        _resourceAvailableVariants: VARIANTS,
        _resourceAvailableVariantStats: STATS,
      },
    });
    expect(screen.queryByTestId('resource-variant-bar-0-blue')).toBeNull();
    expect(screen.queryByTestId('resource-variant-bar-0-amber')).toBeNull();
  });

  /* ── Multi-resource variant pickers (v2.6.30+) ─────────────────────
   *  A single position may carry MANY variant resources (e.g. concrete
   *  grade + rebar diameter + formwork type). Each resource row reads
   *  its own ``_resourceAvailableVariants`` slice, so each pill opens
   *  the picker scoped to that resource — picking on one does not
   *  affect the others. The rows are independent: picking on resource
   *  index 1 forwards (positionId, 1, label) to the repick callback,
   *  not (positionId, 0, label). */
  it('forwards the resource index when multiple variant resources are on the same position', () => {
    const REBAR_VARIANTS: CostVariant[] = [
      { index: 0, label: 'Ø 8mm', price: 950, price_per_unit: null },
      { index: 1, label: 'Ø 12mm', price: 1100, price_per_unit: null },
    ];
    const REBAR_STATS: VariantStats = {
      min: 950,
      max: 1100,
      mean: 1025,
      median: 1025,
      unit: 't',
      group: 'rebar',
      count: 2,
    };

    // Render the SECOND variant resource on the position (resource_idx=1).
    const { onRepickResourceVariant } = renderRow({
      resourceData: {
        _parentPositionId: 'pos-multi',
        _resourceIndex: 1,
        _resourceName: 'Rebar',
        _resourceUnit: 't',
        _resourceQty: 1,
        _resourceRate: 1025,
        _resourceCode: 'STL.B500',
        _resourceAvailableVariants: REBAR_VARIANTS,
        _resourceAvailableVariantStats: REBAR_STATS,
        _resourceVariantDefault: 'median',
      },
    });
    // Pill addresses the right resource via testid (-1 suffix).
    const pill = screen.getByTestId('resource-variant-pill-1');
    expect(pill).toBeInTheDocument();
    fireEvent.click(pill);
    fireEvent.click(screen.getByTestId('variant-row-1'));
    fireEvent.click(screen.getByTestId('variant-picker-apply'));
    // Critical: index 1 (the rebar resource), NOT 0 (the concrete one).
    expect(onRepickResourceVariant).toHaveBeenCalledWith('pos-multi', 1, 'Ø 12mm');
  });
});
