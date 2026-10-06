// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Test this rule" runs the unsaved rule on the server through the apply
 * engine. The page used to run a browser copy on the skeleton element list,
 * which carries no properties, so a property filter matched nothing in the
 * test while Apply matched. The client only sends the draft and reshapes the
 * reply for the existing result panel.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiPost = vi.fn();

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, apiPost: (...args: unknown[]) => apiPost(...args) };
});

import { applyQuantityMaps, previewQuantityRule } from '../api';
import type { SandboxRule } from '../ruleSandbox';

const RULE: SandboxRule = {
  element_type_filter: 'Wall*',
  property_filter: { 'Phase Created': 'Progetto' },
  quantity_source: 'area',
  multiplier: '1',
  waste_factor_pct: '5',
  unit: 'm2',
};

describe('previewQuantityRule', () => {
  beforeEach(() => apiPost.mockReset());

  it('binds an apply to the reviewed model, target and server fingerprint', async () => {
    apiPost.mockResolvedValue({});
    await applyQuantityMaps('model-1', false, 'bill-2', 'f'.repeat(64));
    expect(apiPost).toHaveBeenCalledWith('/v1/bim_hub/quantity-maps/apply/', {
      model_id: 'model-1', target_boq_id: 'bill-2', dry_run: false, preview_fingerprint: 'f'.repeat(64),
    });
  });

  it('sends the draft rule and the model to the preview endpoint', async () => {
    apiPost.mockResolvedValue({ matches: [], skips: [], matched_types: [], total_adjusted: 0, scanned: 0 });
    await previewQuantityRule('model-1', RULE);
    expect(apiPost).toHaveBeenCalledWith('/v1/bim_hub/quantity-maps/preview/', { model_id: 'model-1', rule: RULE });
  });

  it('reshapes the reply into the sandbox result the panel renders', async () => {
    const match = {
      element_id: 'e1',
      stable_id: 's1',
      element_type: 'Walls',
      name: 'Muro 30',
      raw_quantity: 10,
      adjusted_quantity: 10.5,
    };
    const skip = { element_id: 'e2', stable_id: 's2', element_type: 'Walls', reason: 'missing_property' };
    apiPost.mockResolvedValue({
      matches: [match],
      skips: [skip],
      match_count: 640,
      skip_count: 3,
      matched_types: ['Walls'],
      total_adjusted: 10.5,
      scanned: 7,
      sidecar: 'rebuilt',
    });
    await expect(previewQuantityRule('model-1', RULE)).resolves.toEqual({
      matches: [match],
      skips: [skip],
      matchCount: 640,
      skipCount: 3,
      matchedTypes: ['Walls'],
      totalAdjusted: 10.5,
      scanned: 7,
      sidecar: 'rebuilt',
    });
  });

  it('reads an older reply without counts as complete lists from a full sidecar', async () => {
    apiPost.mockResolvedValue({ matches: [], skips: [], matched_types: [], total_adjusted: 0, scanned: 2 });
    await expect(previewQuantityRule('model-1', RULE)).resolves.toMatchObject({
      matchCount: 0,
      skipCount: 0,
      sidecar: 'full',
    });
  });
});
