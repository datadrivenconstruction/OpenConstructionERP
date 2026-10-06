// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What an upgrade adds, and the guard that it takes nothing away.
 */
import { describe, it, expect } from 'vitest';

import type { ModuleSpec } from './api';
import { addField, addRule, emptySpec, removeField, setFeatures, updateField } from './draft';
import {
  additionsOf,
  baselineOf,
  editableFrom,
  hasAdditions,
  isLockedFeature,
  isLockedField,
  isLockedRule,
  keepsBaseline,
  withRecordCount,
} from './upgrade';

function installed(): ModuleSpec {
  const base = emptySpec();
  return {
    ...base,
    key: 'pours',
    display_name: 'Pours',
    entity: {
      ...base.entity,
      name: 'pour',
      display_name: 'Pour',
      plural_name: 'Pours',
      fields: [
        { name: 'reference', label: 'Reference', type: 'text', required: true, help_text: '', unit: '', options: [], in_list: true },
        { name: 'poured_on', label: 'Poured on', type: 'date', required: false, help_text: '', unit: '', options: [], in_list: true },
      ],
    },
    rules: [
      { code: 'REFERENCE_REQUIRED', message: 'Give it a reference.', kind: 'required', field: 'reference', min_value: null, max_value: null, other_field: '', severity: 'error' },
    ],
    features: { status: null, due: null, export: true, comments: false },
  };
}

describe('the baseline', () => {
  it('locks the installed fields and checks by name', () => {
    const baseline = baselineOf(installed());
    expect(isLockedField(baseline, { name: 'reference' })).toBe(true);
    expect(isLockedField(baseline, { name: 'volume' })).toBe(false);
    expect(isLockedRule(baseline, { code: 'reference_required' })).toBe(true);
    expect(isLockedField(null, { name: 'reference' })).toBe(false);
  });

  it('drops the stamps the server adds and fills the functions in', () => {
    const spec = editableFrom({ ...installed(), features: undefined, generated_at: 'x', generator: 'y' });
    expect(spec).not.toHaveProperty('generated_at');
    expect(spec).not.toHaveProperty('generator');
    expect(spec.features).toEqual({ status: null, due: null, export: false, comments: false });
  });
});

describe('what an upgrade adds', () => {
  it('is nothing until something is added', () => {
    const baseline = baselineOf(installed());
    expect(hasAdditions(additionsOf(baseline, installed()))).toBe(false);
  });

  it('names new fields, links, checks and functions apart', () => {
    const baseline = baselineOf(installed());
    let spec = updateField(addField(installed()), 2, { name: 'volume', label: 'Volume', type: 'number' });
    spec = updateField(addField(spec), 3, { name: 'contract', label: 'Contract', type: 'link', target: 'contract' });
    spec = addRule(spec, 'positive', 'volume', 'Must be above zero.');
    spec = setFeatures(spec, { comments: true });
    const added = additionsOf(baseline, spec);
    expect(added.fields.map((f) => f.name)).toEqual(['volume']);
    expect(added.links.map((f) => f.name)).toEqual(['contract']);
    expect(added.rules.map((r) => r.code)).toEqual(['VOLUME_POSITIVE']);
    // Export was on already; only comments is new.
    expect(added.features).toEqual(['comments']);
    expect(keepsBaseline(baseline, spec)).toBe(true);
  });
});

describe('keepsBaseline', () => {
  const baseline = baselineOf(installed());

  it('refuses a removed field, a changed type, a dropped check or function, and a new key', () => {
    expect(keepsBaseline(baseline, removeField(installed(), 1))).toBe(false);
    expect(keepsBaseline(baseline, updateField(installed(), 1, { type: 'text' }))).toBe(false);
    expect(keepsBaseline(baseline, { ...installed(), rules: [] })).toBe(false);
    expect(keepsBaseline(baseline, setFeatures(installed(), { export: false }))).toBe(false);
    expect(keepsBaseline(baseline, { ...installed(), key: 'pours_2' })).toBe(false);
  });

  it('refuses a renamed field, which reads as one removed and one added', () => {
    expect(keepsBaseline(baseline, updateField(installed(), 0, { name: 'ref' }))).toBe(false);
  });

  it('refuses a check that would check something else, but not one reworded', () => {
    const [rule] = installed().rules;
    expect(keepsBaseline(baseline, { ...installed(), rules: [{ ...rule!, field: 'poured_on' }] })).toBe(false);
    expect(keepsBaseline(baseline, { ...installed(), rules: [{ ...rule!, message: 'A pour needs a reference.' }] })).toBe(
      true,
    );
  });

  it('refuses a project scope switched, which would orphan or claim every entry', () => {
    const spec = installed();
    expect(keepsBaseline(baseline, { ...spec, entity: { ...spec.entity, project_scoped: !spec.entity.project_scoped } })).toBe(
      false,
    );
  });
});

describe('choices and stages', () => {
  const STATES = [
    { code: 'planned', label: 'Planned', done: false },
    { code: 'poured', label: 'Poured', done: true },
  ];

  function withGrade(options: string[], states = STATES): ModuleSpec {
    const spec = installed();
    return setFeatures(
      {
        ...spec,
        entity: {
          ...spec.entity,
          fields: [
            ...spec.entity.fields,
            { name: 'grade', label: 'Grade', type: 'select', required: false, help_text: '', unit: '', options, in_list: true },
          ],
        },
      },
      { status: { states } },
    );
  }

  const baseline = baselineOf(withGrade(['C25/30', 'C30/37']));

  it('takes a new choice after the kept ones, and names it', () => {
    const spec = withGrade(['C25/30', 'C30/37', 'C35/45']);
    expect(keepsBaseline(baseline, spec)).toBe(true);
    expect(additionsOf(baseline, spec).choices).toEqual([{ field: 'Grade', choice: 'C35/45' }]);
  });

  it('refuses a kept choice removed or reworded, since entries may hold it', () => {
    expect(keepsBaseline(baseline, withGrade(['C25/30']))).toBe(false);
    expect(keepsBaseline(baseline, withGrade(['C25/30', 'C30-37']))).toBe(false);
  });

  it('takes a new stage and a renamed one, and refuses a kept stage removed', () => {
    const more = withGrade(['C25/30', 'C30/37'], [...STATES, { code: 'cured', label: 'Cured', done: true }]);
    expect(keepsBaseline(baseline, more)).toBe(true);
    expect(additionsOf(baseline, more).stages).toEqual(['Cured']);

    const renamed = withGrade(['C25/30', 'C30/37'], [{ ...STATES[0]!, label: 'Booked' }, STATES[1]!]);
    expect(keepsBaseline(baseline, renamed)).toBe(true);
    expect(additionsOf(baseline, renamed).reworded).toBe(true);
    expect(hasAdditions(additionsOf(baseline, renamed))).toBe(true);

    expect(keepsBaseline(baseline, withGrade(['C25/30', 'C30/37'], [STATES[0]!, { code: 'done', label: 'Poured', done: true }]))).toBe(
      false,
    );
  });

  it('takes a change to what counts as finished, since no stored value changes', () => {
    const flipped = withGrade(['C25/30', 'C30/37'], [{ ...STATES[0]!, done: true }, STATES[1]!]);
    expect(keepsBaseline(baseline, flipped)).toBe(true);
    expect(additionsOf(baseline, flipped).reworded).toBe(true);
  });

  it('counts wording on what is already there as an update, and nothing changed as none', () => {
    expect(hasAdditions(additionsOf(baseline, withGrade(['C25/30', 'C30/37'])))).toBe(false);
    const relabelled = updateField(withGrade(['C25/30', 'C30/37']), 1, { label: 'Cast on', in_list: false });
    expect(additionsOf(baseline, relabelled).reworded).toBe(true);
    expect(keepsBaseline(baseline, relabelled)).toBe(true);
  });
});

describe('a register with nothing recorded yet', () => {
  const locked = baselineOf(installed());
  const empty = withRecordCount(locked, 0);

  it('unlocks every part once the server says there are no records, and only then', () => {
    expect(withRecordCount(locked, 4)).toBe(locked);
    const [field] = installed().entity.fields;
    const [rule] = installed().rules;
    expect(isLockedField(empty, field!)).toBe(false);
    expect(isLockedRule(empty, rule!)).toBe(false);
    expect(isLockedFeature(empty, 'export')).toBe(false);
    expect(isLockedField(locked, field!)).toBe(true);
  });

  it('takes a removed or retyped field, a dropped check or function and a new scope', () => {
    const spec = installed();
    expect(keepsBaseline(empty, removeField(spec, 1))).toBe(true);
    expect(keepsBaseline(empty, updateField(spec, 1, { type: 'text' }))).toBe(true);
    expect(keepsBaseline(empty, { ...spec, rules: [] })).toBe(true);
    expect(keepsBaseline(empty, setFeatures(spec, { export: false }))).toBe(true);
    expect(keepsBaseline(empty, { ...spec, entity: { ...spec.entity, project_scoped: !spec.entity.project_scoped } })).toBe(
      true,
    );
  });

  it('still refuses a new key or a new internal name for the entries', () => {
    const spec = installed();
    expect(keepsBaseline(empty, { ...spec, key: 'pours_2' })).toBe(false);
    expect(keepsBaseline(empty, { ...spec, entity: { ...spec.entity, name: 'casting' } })).toBe(false);
  });

  it('names the fields taken away and counts any other change as one', () => {
    const removed = additionsOf(empty, removeField(installed(), 1));
    expect(removed.removed).toEqual(['Poured on']);
    expect(hasAdditions(removed)).toBe(true);
    const retyped = additionsOf(empty, updateField(installed(), 1, { type: 'text' }));
    expect(retyped.reworded).toBe(true);
    expect(hasAdditions(additionsOf(empty, installed()))).toBe(false);
  });
});
