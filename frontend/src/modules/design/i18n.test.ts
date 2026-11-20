import { describe, expect, it } from 'vitest';
import { DE, EN, RU } from './testStrings';
import { ApiError } from '@/shared/lib/api';
import { noWorkerText } from './BriefFields';
import { manifest } from './manifest';
import { SECTIONS, SPACE_FIELDS, UNIT_FIELDS, fieldSpec, labelKey } from './data/briefModel';

const FORM_POINTERS = [
  ...SECTIONS.flatMap((s) => s.fields),
  '/site/plot',
  ...UNIT_FIELDS.map((f) => `/programme/units/0/${f}`),
  ...SPACE_FIELDS.map((f) => `/programme/units/0/rooms/0/${f}`),
  ...SPACE_FIELDS.map((f) => `/programme/spaces/0/${f}`),
];

const OTHER_MODULE = /^design\.(catalogue|cde_state|common|errors|evidence|independent_check|permit_item|purpose|report_state|ui)\./;
const MODULE_KEYS = Object.keys(EN).filter((k) => k.startsWith('design.') && !OTHER_MODULE.test(k));
const BANNED = /autodesk|revit|archicad|graphisoft|bentley|openai|anthropic|claude|gpt|gemini|mapbox|google/i;

describe('module strings', () => {
  it('label every field, section and choice in English', () => {
    const keys = [
      ...FORM_POINTERS.map(labelKey),
      ...SECTIONS.map((s) => `design.section.${s.id}`),
      // what a template proposes (design/start_api.py), shown on the summary screen
      'design.field.generator.template',
      ...['house', 'apartment_section', 'office', 'school', 'universal'].map((o) => `design.option.${o}`),
      ...FORM_POINTERS.flatMap((p) => fieldSpec(p).options.map((o) => `design.option.${o}`)),
      ...['button', 'title', 'document', 'choose', 'page', 'quote', 'add', 'cancel', 'no_documents', 'load_failed',
        'cited_documents', 'unknown_document', 'values_n'].map((k) => `design.cite.${k}`),
      ...['title', 'subtitle', 'empty', 'list', 'pick', 'element', 'added_n', 'removed_n', 'changed_n', 'unchanged_n',
        'status.shared', 'status.published', 'status.rejected', 'status.archived'].map((k) => `design.revisions.${k}`),
      ...['proposed', 'confirmed', 'default', 'none'].map((s) => `design.status.${s}`),
      ...['document', 'drawing', 'sketch', 'text', 'map', 'user'].map((s) => `design.source.${s}`),
      ...['too_few_points', 'degenerate', 'self_intersecting', 'out_of_range', 'too_large'].map((p) => `design.plot.problem.${p}`),
      ...['required', 'type', 'enum', 'const', 'minimum', 'maximum', 'exclusive_minimum', 'exclusive_maximum',
        'min_length', 'max_length', 'pattern', 'min_items', 'max_items', 'not_allowed', 'date_time',
        'not_a_number', 'not_an_integer', 'server'].map((c) => `design.error.${c}`),
    ];
    expect(keys.filter((k) => !EN[k])).toEqual([]);
  });

  it('manifest names keys the locale bundles carry, and the section is on by default', () => {
    expect(manifest.defaultEnabled).toBe(true);
    for (const key of [manifest.name, manifest.description, ...manifest.routes.map((r) => r.title),
      ...manifest.navItems.map((n) => n.labelKey)]) {
      expect(EN[key], key).toBeTruthy();
    }
    expect(manifest.translations).toBeUndefined();
  });

  it('names no vendor or product in English strings', () => {
    expect(MODULE_KEYS.filter((k) => BANNED.test(EN[k]!))).toEqual([]);
  });
});

describe('translations in the app bundles', () => {
  const ph = (v: string) => (v.match(/\{\{\w+\}\}/g) ?? []).sort().join();

  for (const [code, bundle] of [['ru', RU], ['de', DE]] as const) {
    it(`${code} has every module key with the English placeholders, and names no vendor`, () => {
      expect(MODULE_KEYS.filter((k) => !bundle[k])).toEqual([]);
      for (const k of MODULE_KEYS) expect(ph(bundle[k] ?? ''), k).toBe(ph(EN[k]!));
      expect(MODULE_KEYS.filter((k) => BANNED.test(bundle[k] ?? ''))).toEqual([]);
    });
  }
});

describe('no worker refusal', () => {
  const t = ((k: string) => EN[k] ?? k) as never;
  const err = new ApiError(503, 'Service Unavailable', { detail: { code: 'no_worker', message: 'x' } });

  it('is told with the module string', () => {
    expect(noWorkerText(err, t)).toBe(EN['design.generate.no_worker']);
  });

  it('leaves other errors alone', () => {
    expect(noWorkerText(new ApiError(503, 'x', { detail: 'queue down' }), t)).toBeNull();
    expect(noWorkerText(new ApiError(409, 'x', { detail: { code: 'no_worker' } }), t)).toBeNull();
    expect(noWorkerText(new Error('x'), t)).toBeNull();
  });
});
