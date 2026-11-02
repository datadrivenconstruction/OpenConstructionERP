// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { describe, it, expect, vi, afterEach } from 'vitest';
import { currentLevels, documentOrder, pastedStructure, recurringLines, suggestLevels } from './boqStructure';
import { boqApi } from './api';

const row = (id: string, ordinal: string, unit: string, extra: Record<string, unknown> = {}) => ({
  id,
  ordinal,
  unit,
  parent_id: null as string | null,
  sort_order: 0,
  quantity: 1,
  unit_rate: 0,
  description: id,
  ...extra,
});

afterEach(() => vi.restoreAllMocks());

describe('structure helpers on odd bills', () => {
  it('an empty bill has no order, no levels, nothing recurring', () => {
    expect(documentOrder([])).toEqual([]);
    expect(currentLevels([])).toEqual([]);
    expect(suggestLevels([])).toEqual([]);
    expect(recurringLines([])).toEqual([]);
  });

  it('a row whose parent is missing is treated as top level, not lost', () => {
    expect(documentOrder([row('x', '1', 'm', { parent_id: 'gone' })]).map((r) => r.id)).toEqual(['x']);
  });

  it('a parent cycle does not loop forever or duplicate rows', () => {
    const rows = [
      row('a', '1', 'section', { parent_id: 'b', quantity: 0 }),
      row('b', '2', 'section', { parent_id: 'a', quantity: 0 }),
    ];
    const ordered = documentOrder(rows);
    expect(new Set(ordered.map((r) => r.id)).size).toBe(ordered.length);
    expect(currentLevels(rows).every((l) => l <= 32)).toBe(true);
  });

  it('sibling order follows sort_order, not the arrival order', () => {
    const rows = [row('b', '2', 'm', { sort_order: 2 }), row('a', '1', 'm', { sort_order: 1 })];
    expect(documentOrder(rows).map((r) => r.id)).toEqual(['a', 'b']);
  });

  it('a section that carries a rate is a priced line, level 0', () => {
    expect(currentLevels([row('s', '1', 'section', { quantity: 2, unit_rate: 5 })])).toEqual([0]);
  });

  it('recurring lines ignore blank descriptions and handle thousands of rows', () => {
    const many = Array.from({ length: 3000 }, (_, i) => ({
      id: String(i),
      description: 'Béton',
      unit: 'm3',
      quantity: 1,
      unit_rate: 100,
    }));
    const blank = [
      { id: 'z', description: '  ', unit: 'm', quantity: 1, unit_rate: 1 },
      { id: 'y', description: '  ', unit: 'm', quantity: 1, unit_rate: 2 },
    ];
    const lines = recurringLines([...many, ...blank]);
    expect(lines).toHaveLength(1);
    expect(lines[0]!.ids).toHaveLength(3000);
    expect(lines[0]!.drifting).toBe(false);
  });

  it('a one-cent difference counts as drifting', () => {
    const lines = recurringLines([
      { id: '1', description: 'A', unit: 'm', quantity: 1, unit_rate: 10 },
      { id: '2', description: 'A', unit: 'm', quantity: 1, unit_rate: 10.01 },
    ]);
    expect(lines[0]!.drifting).toBe(true);
  });

  it('pasted rows follow the existing rows, which keep their levels', async () => {
    vi.spyOn(boqApi, 'get').mockResolvedValue({
      positions: [
        row('s', '1', 'section', { quantity: 0 }),
        row('l', '1.1', 'm3', { parent_id: 's' }),
        row('n1', '9', 'm'),
        row('n2', '9.1', 'm'),
      ],
    } as never);
    const out = await pastedStructure('b', [{ id: 'n1' }, { id: 'n2' }], [{ level: 1 }, { level: 0 }]);
    expect(out).toEqual([
      { position_id: 's', level: 1 },
      { position_id: 'l', level: 0 },
      { position_id: 'n1', level: 1 },
      { position_id: 'n2', level: 0 },
    ]);
  });

  it('pasted rows with no level in the preview default to positions', async () => {
    vi.spyOn(boqApi, 'get').mockResolvedValue({ positions: [row('n1', '1', 'm')] } as never);
    expect(await pastedStructure('b', [{ id: 'n1' }], [])).toEqual([{ position_id: 'n1', level: 0 }]);
  });
});
