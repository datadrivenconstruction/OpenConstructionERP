import { describe, expect, it } from 'vitest';
import example from './fixtures/brief.de-residential.json';
import {
  BRIEF_SCHEMA,
  SECTIONS,
  SPACE_FIELDS,
  UNIT_FIELDS,
  addItem,
  citeDocument,
  documentCitations,
  briefErrors,
  editField,
  errorsAt,
  fieldSpec,
  formatValue,
  getAt,
  labelKey,
  newBrief,
  normaliseLocale,
  parseInput,
  removeItem,
  roomKinds,
  serverErrors,
  setAt,
  statusOf,
  tidy,
  unconfirmed,
  valuePointers,
  type BriefDoc,
} from './briefModel';
import { schemaAt, validate } from './schemaCheck';

const EXAMPLE = example as unknown as BriefDoc;
const PROJECT = { id: '746402cb-14a8-430c-b3b9-9c6908fa75d7', country_code: 'de', locale: 'de_DE', name: 'Wohnhaus' };
const BRIEF_ID = 'd687671c-a6c3-4a73-8aa1-230664a927be';

/** Every leaf the schema defines for a person to fill, as a pointer pattern with `*` for list items. */
function schemaLeaves(pointer = ''): string[] {
  if (pointer === '/site/plot') return [pointer]; // drawn on the map as one value
  const s = schemaAt(BRIEF_SCHEMA, pointer.replace(/\*/g, '0'));
  if (!s) return [];
  const props = s.properties as Record<string, unknown> | undefined;
  if (props) return Object.keys(props).flatMap((k) => schemaLeaves(`${pointer}/${k}`));
  const items = s.items as Record<string, unknown> | undefined;
  if (s.type === 'array' && items && (items.properties || items.$ref)) {
    const inner = schemaAt(BRIEF_SCHEMA, `${pointer.replace(/\*/g, '0')}/0`);
    if (inner?.properties) return schemaLeaves(`${pointer}/*`);
  }
  return [pointer];
}

function formPatterns(): Set<string> {
  const out = new Set<string>(SECTIONS.flatMap((s) => s.fields));
  out.add('/site/plot');
  for (const f of UNIT_FIELDS) out.add(`/programme/units/*/${f}`);
  for (const f of SPACE_FIELDS) {
    out.add(`/programme/units/*/rooms/*/${f}`);
    out.add(`/programme/spaces/*/${f}`);
  }
  return out;
}

describe('form ↔ schema', () => {
  it('shows every value field of ddc-brief/1', () => {
    // Owned by the ERP (envelope), by the extraction card (questions) or by the generator pin.
    const notInForm = /^\/(schema|brief_id|project_id|version|provenance|questions|generator)(\/|$)/;
    const missing = schemaLeaves().filter((p) => !notInForm.test(p) && !formPatterns().has(p));
    expect(missing).toEqual([]);
  });

  it('reads the input kind, limits and required flag from the schema', () => {
    expect(fieldSpec('/massing/floors_above')).toMatchObject({ kind: 'integer', required: true, min: 1, max: 200 });
    expect(fieldSpec('/massing/floor_height_m')).toMatchObject({ kind: 'number', unit: 'm', min: 2.2, max: 12 });
    expect(fieldSpec('/use/category').options).toContain('residential_multi');
    expect(fieldSpec('/structure/system').options).not.toContain(null);
    expect(fieldSpec('/massing/lift').kind).toBe('boolean');
    expect(fieldSpec('/programme/spaces/0/floors').kind).toBe('integer_list');
    expect(fieldSpec('/programme/units/3/rooms/1/adjacent_to').kind).toBe('text_list');
    expect(fieldSpec('/programme/units/0/area_m2').unit).toBe('m²');
    expect(fieldSpec('/site/setbacks_m/front').unit).toBe('m');
    expect(fieldSpec('/envelope/roof_slope_deg').unit).toBe('°');
    expect(fieldSpec('/budget/currency').required).toBe(true);
    expect(roomKinds()).toEqual(expect.arrayContaining(['living', 'bedroom', 'kitchen', 'bath', 'technical']));
    expect(labelKey('/programme/units/2/rooms/0/kind')).toBe('design.field.programme.units.rooms.kind');
  });

  it('round-trips every value of the example through its input', () => {
    const pointers = valuePointers(EXAMPLE);
    expect(pointers.length).toBeGreaterThan(30);
    for (const p of pointers) {
      if (p === '/site/plot') continue;
      const value = getAt(EXAMPLE, p);
      const parsed = parseInput(fieldSpec(p), formatValue(value));
      expect(parsed, p).toEqual({ ok: true, value });
    }
  });

  it('rebuilds the example by typing it into a new brief, and the result satisfies the contract', () => {
    let doc = newBrief(PROJECT, BRIEF_ID);
    for (const p of valuePointers(EXAMPLE)) doc = editField(doc, p, structuredClone(getAt(EXAMPLE, p)));
    for (const k of ['country', 'locale', 'name', 'norm_pack', 'depth_level', 'use', 'site', 'massing', 'programme',
      'structure', 'envelope', 'quality_level', 'budget']) {
      expect(doc[k], k).toEqual(EXAMPLE[k]);
    }
    expect(validate(doc, BRIEF_SCHEMA)).toEqual([]);
    // Typed values are the person's own, still to be confirmed.
    expect(statusOf(doc, '/massing/floors_above')).toBe('proposed');
    expect(doc.provenance?.['/site/plot']?.sources).toEqual([{ kind: 'user' }]);
    expect(unconfirmed(doc)).toEqual(valuePointers(doc));
  });
});

describe('new brief', () => {
  it('prefills from the project as defaults and leaves decisions empty', () => {
    const doc = newBrief(PROJECT, BRIEF_ID);
    expect(doc.country).toBe('DE');
    expect(doc.locale).toBe('de-DE');
    expect(statusOf(doc, '/country')).toBe('default');
    const errors = briefErrors(doc);
    expect(Object.keys(errors).sort()).toEqual(['/depth_level', '/massing/floors_above', '/use/category']);
    expect(errors['/use/category']![0]!.code).toBe('required');
  });

  it('skips project values the schema would refuse', () => {
    const doc = newBrief({ id: PROJECT.id, country_code: 'Germany', locale: 'german' }, BRIEF_ID);
    expect(doc.country).toBeUndefined();
    expect(doc.locale).toBeUndefined();
    expect(normaliseLocale('EN')).toBe('en');
    expect(normaliseLocale('pt-br')).toBe('pt-BR');
  });
});

describe('editing', () => {
  it('drops a confirmation when its value changes, also the one of an enclosing value', () => {
    let doc = structuredClone(EXAMPLE);
    expect(statusOf(doc, '/site/plot')).toBe('confirmed');
    doc = editField(doc, '/site/plot/coordinates/0/1/0', 12.3706);
    expect(statusOf(doc, '/site/plot')).toBe('proposed');
    doc = editField(doc, '/massing/floors_above', 5); // unchanged value: nothing happens
    expect(statusOf(doc, '/massing/floors_above')).toBe('confirmed');
    doc = editField(doc, '/massing/floors_above', 6);
    expect(doc.provenance?.['/massing/floors_above']).toEqual({ status: 'proposed', sources: [{ kind: 'user' }] });
  });

  it('clears a value with its provenance and prunes empty sections', () => {
    let doc = structuredClone(EXAMPLE);
    doc = editField(doc, '/structure/system', undefined);
    expect(getAt(doc, '/structure/system')).toBeUndefined();
    expect(doc.provenance?.['/structure/system']).toBeUndefined();
    doc = editField(doc, '/structure/foundation', undefined);
    expect('structure' in doc).toBe(false);
    doc = editField(doc, '/use/category', undefined);
    expect(doc.use).toEqual({ detail: 'Mehrfamilienhaus, ein Treppenhaus' });
    doc = editField(doc, '/use/detail', undefined);
    expect(doc.use).toEqual({}); // required section stays
  });

  it('moves provenance with list items when one is removed', () => {
    let doc = structuredClone(EXAMPLE);
    doc = editField(doc, '/programme/units/1/name', '3-Zi');
    doc = editField(doc, '/programme/units/1/rooms/1/count', 3);
    doc = addItem(doc, '/programme/units', { name: '4-Zimmer', count: 2, rooms: [{ kind: 'living' }] });
    doc = editField(doc, '/programme/units/2/count', 3);
    doc = removeItem(doc, '/programme/units', 0);
    expect((doc.programme as { units: unknown[] }).units).toHaveLength(2);
    expect(Object.keys(doc.provenance ?? {}).filter((p) => p.startsWith('/programme')).sort()).toEqual([
      '/programme/units/0/name', '/programme/units/0/rooms/1/count', '/programme/units/1/count',
    ]);
    expect(validate(tidy(doc), BRIEF_SCHEMA)).toEqual([]);
  });

  it('removing the last item removes the list', () => {
    let doc = structuredClone(EXAMPLE);
    doc = removeItem(doc, '/programme/spaces', 0);
    expect(getAt(doc, '/programme/spaces')).toBeUndefined();
  });

  it('setAt leaves the input untouched and creates parents', () => {
    const doc = { a: 1 };
    const out = setAt(doc, '/b/c', 2);
    expect(doc).toEqual({ a: 1 });
    expect(out).toEqual({ a: 1, b: { c: 2 } });
  });
});

describe('input parsing', () => {
  it('turns text into typed values and refuses what does not fit', () => {
    expect(parseInput(fieldSpec('/massing/floors_above'), ' 5 ')).toEqual({ ok: true, value: 5 });
    expect(parseInput(fieldSpec('/massing/floors_above'), '5.5')).toEqual({ ok: false, code: 'not_an_integer' });
    expect(parseInput(fieldSpec('/massing/floor_height_m'), '3,05')).toEqual({ ok: true, value: 3.05 });
    for (const bad of ['0x10', '1e2', '1E2', 'Infinity', '1_000', '--1', '1.2.3']) {
      expect(parseInput(fieldSpec('/massing/floor_height_m'), bad), bad).toEqual({ ok: false, code: 'not_a_number' });
      expect(parseInput(fieldSpec('/massing/floors_above'), bad).ok, bad).toBe(false);
    }
    expect(parseInput(fieldSpec('/massing/floor_height_m'), '-.5')).toEqual({ ok: true, value: -0.5 });
    expect(parseInput(fieldSpec('/massing/floor_height_m'), 'abc')).toEqual({ ok: false, code: 'not_a_number' });
    expect(parseInput(fieldSpec('/massing/floor_height_m'), '')).toEqual({ ok: true, value: undefined });
    expect(parseInput(fieldSpec('/massing/lift'), 'false')).toEqual({ ok: true, value: false });
    expect(parseInput(fieldSpec('/programme/spaces/0/floors'), '-1, 0 2')).toEqual({ ok: true, value: [-1, 0, 2] });
    expect(parseInput(fieldSpec('/programme/spaces/0/adjacent_to'), 'hall; kitchen')).toEqual({
      ok: true, value: ['hall', 'kitchen'],
    });
  });
});

describe('validation messages', () => {
  it('names the field that is wrong, including list items', () => {
    let doc = structuredClone(EXAMPLE);
    doc = editField(doc, '/massing/floor_height_m', 1.5);
    doc = editField(doc, '/programme/units/0/rooms/0/kind', undefined);
    doc = editField(doc, '/budget/currency', 'eur');
    const errors = briefErrors(doc);
    expect(errors['/massing/floor_height_m']![0]).toMatchObject({ code: 'minimum', param: 2.2 });
    expect(errors['/programme/units/0/rooms/0/kind']![0]!.code).toBe('required');
    expect(errors['/budget/currency']![0]!.code).toBe('pattern');
    expect(errorsAt(errors, '/programme/units/0')).toHaveLength(1);
  });

  it('reads the server error list', () => {
    const map = serverErrors({ detail: { errors: [{ pointer: '/massing/floors_above', message: 'must be >= 1' }] } });
    expect(map['/massing/floors_above']![0]).toMatchObject({ code: 'server', param: 'must be >= 1' });
    expect(serverErrors(null)).toEqual({});
  });
});

describe('document citations', () => {
  const DOC_ID = '2344d010-88d8-4e0c-811d-219134150421';
  const typed = () => editField(newBrief(PROJECT, BRIEF_ID), '/massing/floors_above', 5);

  it('replaces the typed-by-user source with the document and keeps the status', () => {
    const out = citeDocument(typed(), '/massing/floors_above', { document_id: DOC_ID, page: 2, quote: '  fünf Vollgeschosse ' });
    expect(out.provenance?.['/massing/floors_above']).toEqual({
      status: 'proposed',
      sources: [{ kind: 'document', document_id: DOC_ID, page: 2, quote: 'fünf Vollgeschosse' }],
    });
  });

  it('does not duplicate the same citation and does not confirm', () => {
    const once = citeDocument(typed(), '/massing/floors_above', { document_id: DOC_ID, page: 2 });
    const twice = citeDocument(once, '/massing/floors_above', { document_id: DOC_ID, page: 2 });
    expect(twice.provenance?.['/massing/floors_above']?.sources).toHaveLength(1);
    expect(statusOf(twice, '/massing/floors_above')).toBe('proposed');
  });

  it('ignores a value that is not set and counts citations per document', () => {
    const base = typed();
    expect(citeDocument(base, '/massing/floors_below', { document_id: DOC_ID })).toBe(base);
    const out = citeDocument(citeDocument(base, '/massing/floors_above', { document_id: DOC_ID, page: 1 }),
      '/massing/floors_above', { document_id: DOC_ID, page: 3 });
    expect(documentCitations(out)).toEqual({ [DOC_ID]: 1 });
  });

  it('a cited example still validates against the contract schema', () => {
    const out = citeDocument(EXAMPLE, '/massing/floors_above', { document_id: DOC_ID, page: 4, quote: 'x' });
    expect(validate(out, BRIEF_SCHEMA)).toEqual([]);
  });
});
