// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the wizard refuses before the server has to.
 *
 * Each case here corresponds to a check `spec.py` makes. If one of these ever
 * disagrees with the server the symptom is a person filling in four steps and
 * being told no on the last one, which is exactly what this file exists to
 * prevent - so a failure here is a real defect even though nothing crashes.
 */
import { describe, it, expect } from 'vitest';

import type { ModuleFieldSpec, ModuleSpec, ModuleRuleSpec, Vocabulary } from './api';
import {
  IDENTIFIER_RE,
  PROBLEM_TEXT,
  RULE_CODE_RE,
  addField,
  addRule,
  autoIdentifier,
  defaultPlural,
  emptySpec,
  kindsForType,
  moveField,
  normaliseSpec,
  removeField,
  removeOption,
  setFeatures,
  setOption,
  specProblems,
  suggestIdentifier,
  suggestRuleCode,
  toWireSpec,
  updateField,
  updateRule,
} from './draft';

const VOCABULARY: Vocabulary = {
  field_types: [
    { type: 'text', label: 'Text', hint: '' },
    { type: 'money', label: 'Money', hint: '' },
    { type: 'date', label: 'Date', hint: '' },
  ],
  rule_kinds: [
    { kind: 'required', label: 'Must be filled in', hint: '', applies_to: ['text', 'money', 'date'], needs_other_field: false, needs_bounds: false },
    { kind: 'positive', label: 'Above zero', hint: '', applies_to: ['money'], needs_other_field: false, needs_bounds: false },
    { kind: 'order', label: 'Order', hint: '', applies_to: ['date'], needs_other_field: true, needs_bounds: false },
  ],
  reserved_field_names: ['id', 'metadata', 'project_id'],
  reserved_keys: ['boq', 'costs', 'core'],
  max_fields: 40,
  assistant_available: true,
};

function field(over: Partial<ModuleFieldSpec> & { name: string }): ModuleFieldSpec {
  return {
    label: over.name,
    type: 'text',
    required: false,
    help_text: '',
    unit: '',
    options: [],
    in_list: true,
    ...over,
  };
}

function rule(over: Partial<ModuleRuleSpec> & { code: string; kind: ModuleRuleSpec['kind']; field: string }): ModuleRuleSpec {
  return {
    message: 'Say something useful',
    min_value: null,
    max_value: null,
    other_field: '',
    severity: 'error',
    ...over,
  };
}

/** A spec the server would accept, so each test can break exactly one thing. */
function goodSpec(): ModuleSpec {
  return {
    key: 'pour_register',
    display_name: 'Pour Register',
    description: '',
    category: 'community',
    icon: 'Boxes',
    version: '0.1.0',
    author: '',
    drafted_by: 'wizard',
    entity: {
      name: 'pour',
      display_name: 'Pour',
      plural_name: 'Pours',
      project_scoped: true,
      fields: [
        field({ name: 'reference', label: 'Reference' }),
        field({ name: 'volume', label: 'Volume', type: 'money' }),
        field({ name: 'poured_on', label: 'Poured on', type: 'date' }),
        field({ name: 'checked_on', label: 'Checked on', type: 'date' }),
      ],
    },
    rules: [rule({ code: 'REFERENCE_REQUIRED', kind: 'required', field: 'reference' })],
  };
}

const messages = (spec: ModuleSpec) => specProblems(spec, VOCABULARY).map((p) => p.message);
const codes = (spec: ModuleSpec) => specProblems(spec, VOCABULARY).map((p) => p.code);

describe('suggestIdentifier', () => {
  it('turns a name a person typed into a legal identifier', () => {
    expect(suggestIdentifier('Concrete Pour Register')).toBe('concrete_pour_register');
    expect(suggestIdentifier('  Site   diary  ')).toBe('site_diary');
    expect(suggestIdentifier('RFI-log')).toBe('rfi_log');
  });

  it('produces something the identifier rule actually accepts', () => {
    for (const input of ['Concrete Pour Register', 'Betonier Übersicht', 'ölçüm kaydı', 'A/B test']) {
      const out = suggestIdentifier(input);
      if (out) expect(IDENTIFIER_RE.test(out)).toBe(true);
    }
  });

  it('gives up rather than guessing when nothing is left', () => {
    expect(suggestIdentifier('журнал')).toBe('');
    expect(suggestIdentifier('123')).toBe('');
    expect(suggestIdentifier('...')).toBe('');
  });
});

describe('suggestRuleCode', () => {
  it('produces a code the shape rule accepts', () => {
    expect(RULE_CODE_RE.test(suggestRuleCode('volume', 'positive'))).toBe(true);
    expect(suggestRuleCode('volume', 'positive')).toBe('VOLUME_POSITIVE');
  });

  it('still produces a legal code from an unhelpful field name', () => {
    expect(RULE_CODE_RE.test(suggestRuleCode('a', 'required'))).toBe(true);
  });
});

describe('editing fields', () => {
  it('follows a rename through into the rules that point at the field', () => {
    // A rule names its field by name. Renaming without following would leave the
    // spec referring to a field that no longer exists, and the server would say
    // so at install time rather than here.
    let spec = goodSpec();
    spec = updateField(spec, 0, { name: 'pour_reference' });
    expect(spec.rules[0]?.field).toBe('pour_reference');
    expect(messages(spec)).toEqual([]);
  });

  it('follows a rename into the other half of an order rule', () => {
    let spec = goodSpec();
    spec = addRule(spec, 'order', 'poured_on');
    spec = updateRule(spec, 1, { other_field: 'checked_on', message: 'A pour is checked after it is poured.' });
    spec = updateField(spec, 3, { name: 'inspected_on' });
    expect(spec.rules[1]?.other_field).toBe('inspected_on');
  });

  it('names a new field without claiming the empty second half of every other rule', () => {
    // A new field starts with no name, and so does the second field of every
    // rule that has none. Following that "rename" pointed every such rule at
    // the new field; removing the blank field took them all away.
    let spec = addField(goodSpec());
    const blank = spec.entity.fields.length - 1;
    const rules = spec.rules;
    expect(removeField(spec, blank).rules).toEqual(rules);
    spec = updateField(spec, blank, { name: 'slump', label: 'Slump' });
    expect(spec.rules).toEqual(rules);
  });

  it('takes a field s rules with it when the field goes', () => {
    let spec = goodSpec();
    spec = addRule(spec, 'positive', 'volume');
    expect(spec.rules).toHaveLength(2);
    spec = removeField(spec, 1);
    expect(spec.rules.map((r) => r.field)).toEqual(['reference']);
  });

  it('drops select options when a field stops being a select', () => {
    let spec = goodSpec();
    spec = updateField(spec, 0, { type: 'select', options: ['a', 'b'] });
    expect(spec.entity.fields[0]?.options).toEqual(['a', 'b']);
    spec = updateField(spec, 0, { type: 'text' });
    // A non-select carrying options is refused by the spec, so the change has
    // to bring the options with it.
    expect(spec.entity.fields[0]?.options).toEqual([]);
  });

  it('gives a new select two empty options to fill in', () => {
    const spec = updateField(goodSpec(), 0, { type: 'select' });
    expect(spec.entity.fields[0]?.options).toHaveLength(2);
  });

  it('moves a field without losing one', () => {
    const spec = moveField(goodSpec(), 0, 1);
    expect(spec.entity.fields.map((f) => f.name)).toEqual([
      'volume',
      'reference',
      'poured_on',
      'checked_on',
    ]);
  });

  it('does nothing when the move would fall off either end', () => {
    const spec = goodSpec();
    expect(moveField(spec, 0, -1)).toBe(spec);
    expect(moveField(spec, 3, 1)).toBe(spec);
  });

  it('does not mutate the spec it was given', () => {
    const spec = goodSpec();
    const snapshot = JSON.stringify(spec);
    addField(spec);
    removeField(spec, 0);
    updateField(spec, 0, { name: 'other' });
    moveField(spec, 0, 1);
    expect(JSON.stringify(spec)).toBe(snapshot);
  });
});

describe('specProblems', () => {
  it('says nothing about a spec the server would accept', () => {
    expect(specProblems(goodSpec(), VOCABULARY)).toEqual([]);
  });

  it('refuses a key that a shipped module already owns', () => {
    const spec = { ...goodSpec(), key: 'boq' };
    expect(codes(spec)).toContain('key_shipped');
  });

  it('refuses a key that is not snake_case, or is a Python keyword', () => {
    expect(codes({ ...goodSpec(), key: 'Pour Register' })).toContain('key_snake');
    expect(codes({ ...goodSpec(), key: 'class' })).toContain('key_keyword');
  });

  it('refuses a key too short to recognise', () => {
    expect(codes({ ...goodSpec(), key: 'ab' })).toContain('key_short');
  });

  it('refuses a field name the generated row already uses', () => {
    const spec = goodSpec();
    spec.entity.fields[0] = field({ name: 'metadata', label: 'Notes' });
    expect(codes(spec)).toContain('field_reserved');
  });

  it('names a duplicated field once for each copy', () => {
    const spec = goodSpec();
    spec.entity.fields[1] = field({ name: 'reference', label: 'Second' });
    const said = specProblems(spec, VOCABULARY).filter((p) => p.code === 'field_duplicate');
    expect(said).toHaveLength(2);
    expect(said.map((p) => p.where)).toEqual(['field:0', 'field:1']);
  });

  it('refuses a module with no rules at all', () => {
    const spec = { ...goodSpec(), rules: [] };
    expect(codes(spec)).toContain('no_rules');
  });

  it('refuses a numeric rule on a field that holds text', () => {
    let spec = goodSpec();
    spec = addRule(spec, 'positive', 'reference');
    spec = updateRule(spec, 1, { message: 'Must be above zero.' });
    expect(codes(spec)).toContain('not_number');
  });

  it('refuses a date rule on a field that is not a date', () => {
    let spec = goodSpec();
    spec = addRule(spec, 'not_future', 'reference');
    spec = updateRule(spec, 1, { message: 'Cannot be in the future.' });
    expect(codes(spec)).toContain('not_date');
  });

  it('refuses a range with no bound, and one whose bounds are inverted', () => {
    let spec = goodSpec();
    spec = addRule(spec, 'range', 'volume');
    spec = updateRule(spec, 1, { message: 'Between one and ten.' });
    expect(codes(spec)).toContain('range_bound');
    spec = updateRule(spec, 1, { min_value: 10, max_value: 1 });
    expect(codes(spec)).toContain('range_order');
  });

  it('refuses an order rule that names one field, or names itself', () => {
    let spec = goodSpec();
    spec = addRule(spec, 'order', 'poured_on');
    spec = updateRule(spec, 1, { message: 'Poured before checked.' });
    expect(codes(spec)).toContain('order_one_field');
    spec = updateRule(spec, 1, { other_field: 'poured_on' });
    expect(codes(spec)).toContain('order_self');
  });

  it('refuses a select with fewer than two real choices', () => {
    let spec = goodSpec();
    spec = updateField(spec, 0, { type: 'select', options: ['only'] });
    expect(codes(spec)).toContain('one_option');
  });

  it('refuses a select that lists the same choice twice', () => {
    let spec = goodSpec();
    spec = updateField(spec, 0, { type: 'select', options: ['dry', 'dry'] });
    expect(codes(spec)).toContain('option_twice');
  });

  it('refuses two rules sharing a code', () => {
    const spec = goodSpec();
    spec.rules = [
      rule({ code: 'SAME', kind: 'required', field: 'reference' }),
      rule({ code: 'SAME', kind: 'required', field: 'volume' }),
    ];
    expect(messages(spec).join(' ')).toContain('Two checks have the code SAME');
  });

  it('refuses a version that is not three numbers', () => {
    expect(codes({ ...goodSpec(), version: '1.0' })).toContain('version');
  });

  it('refuses a rule with no message a person could act on', () => {
    const spec = goodSpec();
    spec.rules = [rule({ code: 'REF', kind: 'required', field: 'reference', message: 'no' })];
    expect(codes(spec)).toContain('rule_message');
  });

  it('files each problem where the step that owns it can find it', () => {
    const spec = { ...goodSpec(), key: '', version: 'x' };
    spec.entity.fields[0] = field({ name: '', label: '' });
    const wheres = new Set(specProblems(spec, VOCABULARY).map((p) => p.where));
    expect(wheres.has('module')).toBe(true);
    expect(wheres.has('field:0')).toBe(true);
  });

  it('works with no vocabulary, checking only what it can', () => {
    // The vocabulary is a network call. Its absence must not make the wizard
    // claim a spec is fine when its shape is plainly wrong.
    const spec = { ...goodSpec(), key: 'Not An Identifier' };
    expect(specProblems(spec).some((p) => p.code === 'key_snake')).toBe(true);
  });
});

describe('normaliseSpec', () => {
  it('drops the empty options a half-typed select carries', () => {
    let spec = goodSpec();
    spec = updateField(spec, 0, { type: 'select', options: ['dry', '', 'rain', '  '] });
    expect(normaliseSpec(spec).entity.fields[0]?.options).toEqual(['dry', 'rain']);
  });

  it('fills in the plural the server would have filled in', () => {
    const spec = goodSpec();
    spec.entity.plural_name = '';
    expect(normaliseSpec(spec).entity.plural_name).toBe(defaultPlural('Pour'));
  });

  it('upper-cases a rule code and trims what the user typed', () => {
    const spec = goodSpec();
    spec.rules = [rule({ code: ' ref_required ', kind: 'required', field: ' reference ', message: '  Needed  ' })];
    const out = normaliseSpec(spec).rules[0];
    expect(out?.code).toBe('REF_REQUIRED');
    expect(out?.field).toBe('reference');
    expect(out?.message).toBe('Needed');
  });

  it('does not send bounds on a rule that is not a range', () => {
    const spec = goodSpec();
    spec.rules = [rule({ code: 'REF', kind: 'required', field: 'reference', min_value: 3, max_value: 9 })];
    const out = normaliseSpec(spec).rules[0];
    expect(out?.min_value).toBeNull();
    expect(out?.max_value).toBeNull();
  });

  it('does not send another field on a rule that is not an order', () => {
    const spec = goodSpec();
    spec.rules = [rule({ code: 'REF', kind: 'required', field: 'reference', other_field: 'volume' })];
    expect(normaliseSpec(spec).rules[0]?.other_field).toBe('');
  });
});

describe('kindsForType', () => {
  it('offers only the rules that can apply to the field', () => {
    expect(kindsForType(VOCABULARY, 'money').map((k) => k.kind)).toEqual(['required', 'positive']);
    expect(kindsForType(VOCABULARY, 'text').map((k) => k.kind)).toEqual(['required']);
  });

  it('offers nothing at all before the vocabulary has arrived', () => {
    expect(kindsForType(undefined, 'text')).toEqual([]);
  });
});

describe('option editing', () => {
  it('changes one option without touching the others', () => {
    let spec = updateField(goodSpec(), 0, { type: 'select', options: ['a', 'b', 'c'] });
    spec = setOption(spec, 0, 1, 'B');
    expect(spec.entity.fields[0]?.options).toEqual(['a', 'B', 'c']);
    spec = removeOption(spec, 0, 0);
    expect(spec.entity.fields[0]?.options).toEqual(['B', 'c']);
  });
});

describe('emptySpec', () => {
  it('starts with something to fill in and problems that say what', () => {
    const spec = emptySpec();
    expect(spec.entity.fields).toHaveLength(1);
    expect(specProblems(spec, VOCABULARY).length).toBeGreaterThan(0);
  });
});

describe('autoIdentifier', () => {
  it('turns a name into snake_case', () => {
    expect(autoIdentifier('Concrete Pours', 'register')).toBe('concrete_pours');
  });

  it('falls back to a stable name for a script it cannot spell, rather than an error', () => {
    const first = autoIdentifier('Журнал бетонирования', 'register');
    expect(first).toMatch(IDENTIFIER_RE);
    expect(first.startsWith('register_')).toBe(true);
    // The same text gives the same name while the person keeps typing elsewhere.
    expect(autoIdentifier('Журнал бетонирования', 'register')).toBe(first);
    expect(autoIdentifier('Журнал приёмки', 'register')).not.toBe(first);
  });

  it('steps around names taken and Python keywords', () => {
    expect(autoIdentifier('Pours', 'register', ['pours', 'pours_2'])).toBe('pours_3');
    expect(autoIdentifier('class', 'field')).toBe('class_2');
  });

  it('refuses a name shorter than asked for', () => {
    expect(autoIdentifier('ab', 'register', [], 3)).toMatch(/^register_/);
  });
});

describe('links and functions in the spec', () => {
  const VOCAB_V2: Vocabulary = {
    ...VOCABULARY,
    field_types: [...VOCABULARY.field_types, { type: 'link', label: 'Link', hint: '' }],
    link_targets: [
      { target: 'contract', module: 'oe_contracts', available: true },
      { target: 'document', module: 'oe_documents', available: false },
    ],
    features: ['status', 'due', 'export', 'comments'],
  };
  const where = (spec: ModuleSpec) => specProblems(spec, VOCAB_V2).map((p) => p.where);

  it('asks a link what it points at, and refuses one switched off here', () => {
    const base = goodSpec();
    const noTarget = updateField(base, 0, { type: 'link' });
    expect(noTarget.entity.fields[0]?.target).toBeNull();
    expect(where(noTarget)).toContain('field:0');
    expect(where(updateField(noTarget, 0, { target: 'contract' }))).toEqual([]);
    expect(where(updateField(noTarget, 0, { target: 'document' }))).toContain('field:0');
  });

  it('drops the target when a link becomes something else', () => {
    const link = updateField(updateField(goodSpec(), 0, { type: 'link' }), 0, { target: 'contract' });
    expect(updateField(link, 0, { type: 'text' }).entity.fields[0]).not.toHaveProperty('target');
  });

  it('holds a status to two to eight named, distinct stages and keeps its column free', () => {
    const one = setFeatures(goodSpec(), { status: { states: [{ code: 'open', label: 'Open', done: false }] } });
    expect(where(one)).toContain('status');

    const twoSame = setFeatures(goodSpec(), {
      status: { states: [{ code: 'open', label: 'Open', done: false }, { code: 'open', label: '', done: true }] },
    });
    expect(where(twoSame)).toEqual(expect.arrayContaining(['status', 'state:1']));

    const good = setFeatures(goodSpec(), {
      status: { states: [{ code: 'open', label: 'Open', done: false }, { code: 'done', label: 'Done', done: true }] },
    });
    expect(where(good)).toEqual([]);
    expect(where(updateField(good, 0, { name: 'status' }))).toContain('field:0');
  });

  it('wants a reminder on a date, within thirty days', () => {
    expect(where(setFeatures(goodSpec(), { due: { field: 'poured_on', remind_days_before: 3 } }))).toEqual([]);
    expect(where(setFeatures(goodSpec(), { due: { field: 'reference', remind_days_before: 3 } }))).toContain('due');
    expect(where(setFeatures(goodSpec(), { due: { field: 'poured_on', remind_days_before: 31 } }))).toContain('due');
    expect(where(setFeatures(goodSpec(), { due: { field: '', remind_days_before: 3 } }))).toContain('due');
  });

  it('keeps the reminder on its date through a rename, and drops it with the field', () => {
    const due = setFeatures(goodSpec(), { due: { field: 'poured_on', remind_days_before: 3 } });
    const renamed = updateField(due, 2, { name: 'cast_on' });
    expect(renamed.features?.due?.field).toBe('cast_on');
    expect(removeField(renamed, 2).features?.due).toBeNull();
  });

  it('gives a new rule a code of its own', () => {
    const twice = addRule(addRule(goodSpec(), 'required', 'reference'), 'required', 'reference');
    const codes = twice.rules.map((r) => r.code);
    expect(new Set(codes).size).toBe(codes.length);
    for (const code of codes) expect(code).toMatch(RULE_CODE_RE);
  });
});

describe('toWireSpec', () => {
  function withEverything(): ModuleSpec {
    const link = updateField(updateField(goodSpec(), 0, { type: 'link' }), 0, { target: 'contract' });
    return setFeatures({ ...link, schema_version: 2 }, { export: true });
  }

  it('leaves every new key off for a server from before links and functions', () => {
    const wire = toWireSpec(withEverything(), false);
    expect(wire).not.toHaveProperty('schema_version');
    expect(wire).not.toHaveProperty('features');
    for (const f of wire.entity.fields) expect(f).not.toHaveProperty('target');
  });

  it('sends the functions in full and a target only on a link to a current server', () => {
    const wire = toWireSpec(withEverything(), true);
    expect(wire.schema_version).toBe(2);
    expect(wire.features).toEqual({ status: null, due: null, export: true, comments: false });
    expect(wire.entity.fields[0]?.target).toBe('contract');
    expect(wire.entity.fields[1]).not.toHaveProperty('target');
  });
});

describe('problem wording', () => {
  it('has every problem in en.ts, with the same English', async () => {
    const { existsSync, readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const file = ['src/app/locales/en.ts', 'frontend/src/app/locales/en.ts']
      .map((p) => resolve(process.cwd(), p))
      .find(existsSync);
    expect(file).toBeTruthy();
    const src = readFileSync(file!, 'utf8');
    const differ = Object.entries(PROBLEM_TEXT).filter(([code, text]) => {
      const line = src.match(new RegExp(`"module_builder\.problem\.${code}": (".*"),`));
      return !line || JSON.parse(line[1]!) !== text;
    });
    expect(differ.map(([code]) => code)).toEqual([]);
  });

  it('fills the English in, and hands the values over for translation', () => {
    const spec: ModuleSpec = { ...goodSpec(), rules: [rule({ code: 'SAME', kind: 'required', field: 'reference' }), rule({ code: 'SAME', kind: 'required', field: 'reference' })] };
    const problem = specProblems(spec, VOCABULARY).find((p) => p.code === 'rule_duplicate');
    expect(problem?.params).toEqual({ code: 'SAME' });
    expect(problem?.message).toBe('Two checks have the code SAME.');
  });
});
