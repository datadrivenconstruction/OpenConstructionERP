import { describe, expect, it } from 'vitest';
import {
  activeFilterCount,
  bboxStyle,
  editedPayload,
  filtersFromParams,
  filtersToParams,
  filtersToQuery,
  parseView,
  sliderKeyStep,
  sliderPercent,
  suggestionText,
} from '../model';

describe('filter state', () => {
  it('turns the filter bar into the API query with whole UTC days', () => {
    const query = new URLSearchParams(
      filtersToQuery({ q: 'slab', from: '2026-10-01', to: '2026-10-31', source: 'punchlist', hasGps: true }),
    );
    expect(query.get('q')).toBe('slab');
    expect(query.get('from')).toBe('2026-10-01T00:00:00Z');
    expect(query.get('to')).toBe('2026-10-31T23:59:59Z');
    expect(query.get('source')).toBe('punchlist');
    expect(query.get('has_gps')).toBe('true');
    expect(filtersToQuery({})).toBe('');
  });

  it('only sends a target filter when both kind and id are known', () => {
    expect(filtersToQuery({ targetKind: 'punch_item' })).toBe('');
    const q = new URLSearchParams(filtersToQuery({ targetKind: 'punch_item', targetId: 'abc' }));
    expect([q.get('target_kind'), q.get('target_id')]).toEqual(['punch_item', 'abc']);
  });

  it('round-trips through the URL, keeps the view and drops malformed values', () => {
    const base = new URLSearchParams('view=map&from=yesterday&source=nowhere');
    expect(filtersFromParams(base)).toEqual({});
    const next = filtersToParams({ tag: 'rebar', from: '2026-10-01', hasGps: true }, base);
    expect(next.get('view')).toBe('map');
    expect(filtersFromParams(next)).toEqual({ tag: 'rebar', from: '2026-10-01', hasGps: true });
    expect(activeFilterCount(filtersFromParams(next))).toBe(3);
  });

  it('falls back to the grid for an unknown view', () => {
    expect(parseView('timeline')).toBe('timeline');
    expect(parseView('carousel')).toBe('grid');
    expect(parseView(null)).toBe('grid');
  });
});

describe('before / after slider maths', () => {
  it('clamps the pointer position to the box', () => {
    expect(sliderPercent(150, 100, 200)).toBe(25);
    expect(sliderPercent(0, 100, 200)).toBe(0);
    expect(sliderPercent(999, 100, 200)).toBe(100);
    expect(sliderPercent(10, 0, 0)).toBe(50);
  });

  it('steps with the keyboard and ignores other keys', () => {
    expect(sliderKeyStep('ArrowRight', 50)).toBe(52);
    expect(sliderKeyStep('PageDown', 5)).toBe(0);
    expect(sliderKeyStep('End', 10)).toBe(100);
    expect(sliderKeyStep('a', 10)).toBeNull();
  });
});

describe('AI suggestion editing', () => {
  it('shows and re-reads each kind of payload', () => {
    expect(suggestionText('tags', { tags: ['rebar', 'slab'] })).toBe('rebar, slab');
    expect(editedPayload('tags', {}, ' Rebar, rebar , formwork ')).toEqual({ tags: ['rebar', 'formwork'] });
    expect(editedPayload('caption', {}, '  ')).toBeNull();
    const progress = { target_kind: 'boq_position', target_id: 'p1', percent_observed: 40 };
    expect(suggestionText('progress', progress)).toBe('40');
    expect(editedPayload('progress', progress, '55,5')).toEqual({ ...progress, percent_observed: 55.5 });
    expect(editedPayload('progress', progress, '140')).toBeNull();
  });

  it('places a hazard box only for a valid fraction box', () => {
    expect(bboxStyle([0.1, 0.2, 0.3, 0.4])).toEqual({ left: '10%', top: '20%', width: '30%', height: '40%' });
    expect(bboxStyle([0.1, 0.2, 3, 0.4])).toBeNull();
    expect(bboxStyle('x')).toBeNull();
  });
});
