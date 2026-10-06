// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { repointedMetadata } from '../repointedMetadata';

const linkedToA = {
  cost_item_id: 'a',
  cost_item_code: 'TOS25_01.A03.001.001',
  prezzario: { region: 'Toscana', edition: '2025' },
  cost_shares: { labour: '0.4' },
  xpwe_ep_id: '12',
  safety_item: true,
  resources: [{ name: 'Operaio' }],
  bim_qty_source: { model: 'm1' },
};

describe('repointedMetadata', () => {
  it('links the line to the picked item and drops what said the old item priced it', () => {
    const meta = repointedMetadata(linkedToA, { id: 'b', code: 'LAZ23_A.1' });
    expect(meta.cost_item_id).toBe('b');
    expect(meta.cost_item_code).toBe('LAZ23_A.1');
    expect(meta.source).toBe('cost_database');
    for (const key of ['prezzario', 'cost_shares', 'xpwe_ep_id', 'safety_item']) expect(meta).not.toHaveProperty(key);
    // What belongs to the line itself stays.
    expect(meta.bim_qty_source).toEqual({ model: 'm1' });
  });

  it('keeps the block when the same item is picked again', () => {
    const meta = repointedMetadata(linkedToA, { id: 'a', code: 'TOS25_01.A03.001.001' });
    expect(meta.prezzario).toEqual(linkedToA.prezzario);
    expect(meta.cost_item_id).toBe('a');
  });

  it('without an id from the server, keeps the block for the same code and unlinks for another', () => {
    expect(repointedMetadata(linkedToA, { code: 'TOS25_01.A03.001.001' }).prezzario).toEqual(linkedToA.prezzario);
    const other = repointedMetadata(linkedToA, { code: 'LAZ23_A.1' });
    expect(other).not.toHaveProperty('cost_item_id');
    expect(other).not.toHaveProperty('prezzario');
  });

  it('starts from empty metadata', () => {
    expect(repointedMetadata(null, { id: 'b', code: 'X' })).toEqual({
      cost_item_code: 'X',
      source: 'cost_database',
      cost_item_id: 'b',
    });
  });
});
