// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// buildBoqPositionDraft — full-fidelity carry-over of resources + variants
// when a cost item is added from /costs into a BOQ. Founder bug 2026-06-06:
// the /costs add path used the lite list row (components: [], no variants)
// and dropped every resource and the variant reference. The fix fetches the
// full item and runs it through this helper.

import { describe, it, expect } from 'vitest';
import { buildBoqPositionDraft, type FullCostItem } from './addToBoqHelpers';
import type { CostVariant, VariantStats } from './api';

const LABELS = { labor: 'Labor', material: 'Material', equipment: 'Equipment' };

function baseItem(over: Partial<FullCostItem> = {}): FullCostItem {
  return {
    id: 'item-1',
    code: 'C-001',
    description: 'Concrete C30/37 wall',
    unit: 'm3',
    rate: 320,
    currency: 'EUR',
    region: 'DE_BERLIN',
    classification: { collection: 'Concrete' },
    components: [],
    metadata_: {},
    source: 'cwicr',
    ...over,
  };
}

describe('buildBoqPositionDraft', () => {
  it('carries ALL components as metadata.resources', () => {
    const item = baseItem({
      components: [
        { name: 'Concrete C30/37', code: 'BET', type: 'material', unit: 'm3', quantity: 1, unit_rate: 185, cost: 185 },
        { name: 'Rebar 8mm', code: 'REB', type: 'material', unit: 'kg', quantity: 90, unit_rate: 1.5, cost: 135 },
        { name: 'Formwork labour', code: 'LAB', type: 'labor', unit: 'h', quantity: 4, unit_rate: 32.5, cost: 130 },
      ],
    });
    const { metadata, unitRate } = buildBoqPositionDraft(item, 'EUR', LABELS);
    const resources = metadata.resources as Array<Record<string, unknown>>;
    expect(resources).toHaveLength(3);
    expect(resources.map((r) => r.name)).toEqual([
      'Concrete C30/37',
      'Rebar 8mm',
      'Formwork labour',
    ]);
    // unit_rate = sum of resource totals = 185 + 135 + 130 = 450.
    expect(unitRate).toBe(450);
    // Each resource carries the resolved currency.
    expect(resources.every((r) => r.currency === 'EUR')).toBe(true);
    // Cost breakdown summary by type.
    expect(metadata.cost_breakdown).toEqual({ material: 320, labor: 130 });
    expect(metadata.resource_count).toBe(3);
    expect(metadata.cost_item_id).toBe('item-1');
  });

  it('auto-defaults a variant-bearing component to the mean rate and carries its catalog', () => {
    const variants: CostVariant[] = [
      { index: 0, label: 'C25/30', price: 165, price_per_unit: null },
      { index: 1, label: 'C30/37', price: 185, price_per_unit: null },
      { index: 2, label: 'C35/45', price: 215, price_per_unit: null },
    ];
    const stats: VariantStats = {
      min: 165,
      max: 215,
      mean: 188,
      median: 185,
      unit: 'm3',
      group: '',
      count: 3,
      common_start: 'Ready-mix concrete',
    };
    const item = baseItem({
      components: [
        {
          name: 'Ready-mix concrete',
          code: 'BET',
          type: 'material',
          unit: 'm3',
          quantity: 1,
          unit_rate: 0,
          available_variants: variants,
          available_variant_stats: stats,
        },
      ],
    });
    const { metadata, unitRate } = buildBoqPositionDraft(item, 'EUR', LABELS);
    const resources = metadata.resources as Array<Record<string, unknown>>;
    expect(resources).toHaveLength(1);
    const r = resources[0]!;
    expect(r.variant_default).toBe('mean');
    expect(r.unit_rate).toBe(188); // mean
    expect(r.available_variants).toEqual(variants);
    expect(r.available_variant_stats).toEqual(stats);
    expect(unitRate).toBe(188);
  });

  it('appends a top-level abstract-resource variant set as one resource line', () => {
    const variants: CostVariant[] = [
      { index: 0, label: 'delivered', price: 180, price_per_unit: null },
      { index: 1, label: 'pumped', price: 200, price_per_unit: null },
    ];
    const stats: VariantStats = {
      min: 180,
      max: 200,
      mean: 190,
      median: 190,
      unit: 'm3',
      group: '',
      count: 2,
      common_start: 'Concrete delivery',
    };
    const item = baseItem({ components: [], metadata_: { variants, variant_stats: stats } });
    const { metadata, unitRate } = buildBoqPositionDraft(item, 'EUR', LABELS);
    const resources = metadata.resources as Array<Record<string, unknown>>;
    expect(resources).toHaveLength(1);
    const top = resources[0]!;
    expect(top.variant_default).toBe('mean');
    expect(top.unit_rate).toBe(190);
    expect(top.name).toBe('Concrete delivery');
    expect(unitRate).toBe(190);
    // Variant catalog cached at the top level for the inline re-pick.
    expect(metadata.cost_item_variant_count).toBe(2);
    expect(metadata.variant_default).toBe('mean');
    // The heavy variants array is NOT duplicated at the top level.
    expect(metadata.variants).toBeUndefined();
  });

  it('does NOT double-count a top-level variant mirrored on a component', () => {
    const variants: CostVariant[] = [
      { index: 0, label: 'C25/30', price: 165, price_per_unit: null },
      { index: 1, label: 'C30/37', price: 185, price_per_unit: null },
    ];
    const stats: VariantStats = {
      min: 165, max: 185, mean: 175, median: 175, unit: 'm3', group: '', count: 2,
    };
    const item = baseItem({
      components: [
        {
          name: 'Ready-mix concrete',
          code: 'BET',
          type: 'material',
          unit: 'm3',
          quantity: 1,
          unit_rate: 0,
          available_variants: variants,
          available_variant_stats: stats,
        },
      ],
      metadata_: { variants, variant_stats: stats },
    });
    const { metadata } = buildBoqPositionDraft(item, 'EUR', LABELS);
    const resources = metadata.resources as Array<Record<string, unknown>>;
    // Only the component line — no synthetic top-level duplicate.
    expect(resources).toHaveLength(1);
  });

  it('synthesizes labor/material/equipment lines when no components but cost summary present', () => {
    const item = baseItem({
      components: [],
      metadata_: { labor_cost: 50, material_cost: 120, equipment_cost: 30 },
    });
    const { metadata, unitRate } = buildBoqPositionDraft(item, 'EUR', LABELS);
    const resources = metadata.resources as Array<Record<string, unknown>>;
    expect(resources).toHaveLength(3);
    expect(resources.map((r) => r.type)).toEqual(['labor', 'material', 'equipment']);
    expect(unitRate).toBe(200);
  });

  it('falls back to the catalog rate when there is no breakdown at all', () => {
    const item = baseItem({ components: [], metadata_: {}, rate: 99 });
    const { metadata, unitRate } = buildBoqPositionDraft(item, 'EUR', LABELS);
    expect(metadata.resources).toBeUndefined();
    expect(unitRate).toBe(99);
  });

  it('stamps the resolved currency onto metadata for the FX rollup', () => {
    const item = baseItem({ currency: 'AED', region: 'AE_DUBAI' });
    const { metadata } = buildBoqPositionDraft(item, 'AED', LABELS);
    expect(metadata.currency).toBe('AED');
    expect(metadata.cost_item_currency).toBe('AED');
  });
});
