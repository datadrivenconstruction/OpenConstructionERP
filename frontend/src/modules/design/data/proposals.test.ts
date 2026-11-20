import { describe, expect, it } from 'vitest';
import { applySummary, fromExtraction, fromValues } from './proposals';
import type { BriefDoc } from './briefModel';

const BASE: BriefDoc = { schema: 'ddc-brief/1', brief_id: 'b', project_id: 'p', version: 2, use: {}, massing: {}, programme: {},
  provenance: { '/name': { status: 'confirmed' } }, name: 'Haus' };

const DRAFT: BriefDoc = {
  ...BASE,
  massing: { floors_above: 5, floor_height_m: 3.1 },
  use: { category: 'residential_multi' },
  provenance: {
    '/name': { status: 'confirmed' },
    '/massing/floors_above': { status: 'proposed', sources: [{ kind: 'text', quote: 'five storeys' }] },
    '/massing/floor_height_m': { status: 'proposed', sources: [{ kind: 'text' }] },
    '/use/category': { status: 'proposed', sources: [{ kind: 'document', document_id: 'd1', page: 2, quote: 'Mehrfamilienhaus' }] },
  },
  questions: [{ id: 'q', pointer: '/use/category', text: 'Which use?', options: [] }],
};
const PROPOSED = ['/massing/floors_above', '/massing/floor_height_m', '/use/category'];

describe('one summary for every proposal', () => {
  it('marks a value without a quote, or one the AI asked about, as doubtful and lists those first', () => {
    const set = fromExtraction('text', DRAFT, PROPOSED, ['Which use?']);
    expect(set.items.map((i) => [i.pointer, i.doubt])).toEqual([
      ['/massing/floor_height_m', 'no_quote'], ['/use/category', 'question'], ['/massing/floors_above', null],
    ]);
    expect(set.items[1]!.source).toMatchObject({ document_id: 'd1', page: 2 });
  });

  it('keeps every value the person did not leave out; corrected ones get the person as source', () => {
    const set = fromExtraction('text', DRAFT, PROPOSED, []);
    const { doc, pointers } = applySummary(set, new Set(['/use/category']), { '/massing/floor_height_m': 3.0 });
    expect(pointers.sort()).toEqual(['/massing/floor_height_m', '/massing/floors_above']);
    expect(doc.massing).toEqual({ floors_above: 5, floor_height_m: 3.0 });
    expect(doc.use).toEqual({});
    expect(doc.provenance?.['/massing/floor_height_m']).toEqual({ status: 'proposed', sources: [{ kind: 'user' }] });
    expect(doc.provenance?.['/use/category']).toBeUndefined();
    expect(doc.provenance?.['/name']).toEqual({ status: 'confirmed' }); // what was confirmed before stays
  });

  it('a template or the map proposes into the current brief, typical values doubtful', () => {
    const set = fromValues('template', BASE, [
      { pointer: '/use/category', value: 'school', source: { kind: 'user' } },
      { pointer: '/massing/floor_height_m', value: 3.6, doubtful: true, source: { kind: 'user' }, note: 'Template school' },
    ]);
    expect(set.items.map((i) => i.doubt)).toEqual(['typical', null]);
    expect(set.draft.provenance?.['/massing/floor_height_m']).toEqual({ status: 'proposed', sources: [{ kind: 'user' }], note: 'Template school' });
    expect(BASE.massing).toEqual({}); // the base is not touched
    const { doc, pointers } = applySummary(set, new Set(), {});
    expect(pointers).toEqual(['/massing/floor_height_m', '/use/category']);
    expect(doc.name).toBe('Haus');
  });
});
