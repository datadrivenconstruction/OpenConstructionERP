import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import { bimLinkState, bimLinkTooltip, readBimLinkRecord } from '../bimLinkProvenance';

const t = ((_key: string, opts: Record<string, unknown>) =>
  String(opts.defaultValue).replace(/\{\{(\w+)\}\}/g, (_, k: string) => String(opts[k]))) as unknown as TFunction;

const synced = {
  status: 'ok',
  method: 'sum',
  formula: 'sum(volume_m3) x 1 [m3 -> m3]',
  quantity: '4.0000',
  applied_quantity: '4.0000',
  manual_kept: false,
  element_count: 2,
  missing_count: 0,
  unit: 'm3',
  models: [{ model_id: 'm1', name: 'Tower', version: '3', elements: 2 }],
};

describe('bim link provenance', () => {
  it('reads the record from position metadata', () => {
    expect(readBimLinkRecord({ bim_link_quantity: synced })).toEqual(synced);
    expect(readBimLinkRecord({})).toBeNull();
  });

  it('a synced figure is a model quantity with model, version and formula', () => {
    expect(bimLinkState(synced)).toBe('model');
    expect(bimLinkTooltip(synced, t)).toBe('Model Tower v3, elements: 2\nFormula: sum(volume_m3) x 1 [m3 -> m3]');
  });

  it('a kept manual quantity says what the model gives', () => {
    const rec = { ...synced, manual_kept: true, model_quantity: '5.0000' };
    expect(bimLinkState(rec)).toBe('manual_kept');
    expect(bimLinkTooltip(rec, t)).toContain('Your quantity is kept. The model gives 5.0000.');
  });

  it('a unit the model cannot supply is flagged, never shown as a model figure', () => {
    const rec = { status: 'unit_unsupported', method: 'none', unit: 'h', applied_quantity: null, models: [] };
    expect(bimLinkState(rec)).toBe('no_quantity');
    expect(bimLinkTooltip(rec, t)).toContain('no value in h');
  });
});
