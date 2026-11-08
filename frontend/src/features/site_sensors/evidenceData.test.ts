// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Claim evidence and BIM picker helper tests.
import { describe, expect, it } from 'vitest';
import { filterElements, shortHash, windowAround, windowIsValid } from './evidenceData';

describe('windowAround', () => {
  it('spans an hour either side of the alert', () => {
    const w = windowAround('2026-10-20T08:00:00Z');
    expect(w).toEqual({ from: '2026-10-20T07:00:00.000Z', to: '2026-10-20T09:00:00.000Z' });
  });
  it('gives nothing for an unreadable time', () => {
    expect(windowAround('soon')).toBeNull();
  });
});

describe('windowIsValid', () => {
  it('needs both ends, forward, within a year', () => {
    expect(windowIsValid('2026-10-20T07:00:00Z', '2026-10-20T09:00:00Z')).toBe(true);
    expect(windowIsValid('2026-10-20T09:00:00Z', '2026-10-20T07:00:00Z')).toBe(false);
    expect(windowIsValid('2026-10-20T09:00:00Z', '2026-10-20T09:00:00Z')).toBe(false);
    expect(windowIsValid('2025-10-20T00:00:00Z', '2026-10-22T00:00:00Z')).toBe(false);
    expect(windowIsValid(null, '2026-10-20T09:00:00Z')).toBe(false);
  });
});

describe('shortHash', () => {
  it('keeps the first 16 characters', () => {
    expect(shortHash('0123456789abcdef0123')).toBe('0123456789abcdef');
  });
});

describe('filterElements', () => {
  const els = [
    { id: '1', name: 'Wall A', element_type: 'Wall', storey: 'L1' },
    { id: '2', name: 'Slab B', element_type: 'Slab', storey: 'L2' },
    { id: '3', name: 'Wall type', element_type: 'Wall', is_type_definition: true },
  ];
  it('matches name, type or storey and skips type definitions', () => {
    expect(filterElements(els, 'wall').items.map((e) => e.id)).toEqual(['1']);
    expect(filterElements(els, 'l2').items.map((e) => e.id)).toEqual(['2']);
    expect(filterElements(els, '').items).toHaveLength(2);
  });
  it('reports when the list was cut', () => {
    const r = filterElements(els, '', 1);
    expect(r.items).toHaveLength(1);
    expect(r.truncated).toBe(true);
  });
});
