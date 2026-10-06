// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Ticking and unticking a suggestion, as spec edits.
 *
 * Whether a suggestion is on is read off the spec, never kept beside it, so
 * these check the round trip: apply then withdraw returns the spec it started
 * from, and nothing is ever applied that nobody ticked.
 */
import { describe, it, expect } from 'vitest';

import type { ModuleSpec, Suggestion, Vocabulary } from './api';
import { emptySpec, featuresOf, specProblems, toWireSpec } from './draft';
import {
  applyAll,
  applySuggestion,
  blockedBy,
  canApply,
  isApplied,
  mergeSuggestions,
  suggestionSignature,
  toggleSuggestion,
  withdrawSuggestion,
} from './suggestions';

const VOCABULARY: Vocabulary = {
  field_types: [],
  rule_kinds: [],
  reserved_field_names: ['id', 'metadata', 'status'],
  reserved_keys: [],
  max_fields: 4,
  assistant_available: false,
  link_targets: [
    { target: 'contract', module: 'oe_contracts', available: true },
    { target: 'document', module: 'oe_documents', available: false },
  ],
  features: ['status', 'due', 'export', 'comments'],
};

function spec(): ModuleSpec {
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
        { name: 'contract', label: 'Contract reference', type: 'text', required: false, help_text: '', unit: '', options: [], in_list: true },
        { name: 'due_on', label: 'Due on', type: 'date', required: false, help_text: '', unit: '', options: [], in_list: true },
      ],
    },
    rules: [
      { code: 'DUE_REQUIRED', message: 'Give it a date.', kind: 'required', field: 'due_on', min_value: null, max_value: null, other_field: '', severity: 'error' },
    ],
  };
}

const LINK: Suggestion = {
  id: 'link:contract',
  kind: 'link',
  target: 'contract',
  confidence: 'high',
  patch: {
    field: { name: 'contract', label: 'Contract', type: 'link', target: 'contract', required: false, help_text: '', unit: '', options: [], in_list: true },
  },
};

const STATUS: Suggestion = {
  id: 'feature:status',
  kind: 'feature',
  feature: 'status',
  confidence: 'medium',
  patch: { status: { states: [{ code: 'open', label: 'Open', done: false }, { code: 'done', label: 'Done', done: true }] } },
};

const DUE: Suggestion = {
  id: 'feature:due',
  kind: 'feature',
  feature: 'due',
  confidence: 'high',
  patch: { due: { field: 'due_on', remind_days_before: 3 } },
};

const EXPORT: Suggestion = { id: 'feature:export', kind: 'feature', feature: 'export', confidence: 'low', patch: { export: true } };
const COMMENTS: Suggestion = { id: 'feature:comments', kind: 'feature', feature: 'comments', confidence: 'low', patch: { comments: true } };

describe('mergeSuggestions', () => {
  it('keeps the first of each id, in the order the lists were given', () => {
    const fromAi = { ...LINK, reason: 'from the assistant' };
    const merged = mergeSuggestions([fromAi], [LINK, STATUS], undefined, [STATUS]);
    expect(merged.map((s) => s.id)).toEqual(['link:contract', 'feature:status']);
    expect(merged[0]?.reason).toBe('from the assistant');
  });
});

describe('applying a link', () => {
  it('adds the field, under a name that does not collide with one already there', () => {
    const next = applySuggestion(spec(), LINK, VOCABULARY);
    const link = next.entity.fields.find((f) => f.type === 'link');
    expect(link?.target).toBe('contract');
    expect(link?.name).toBe('contract_2');
    expect(isApplied(next, LINK)).toBe(true);
    expect(specProblems(next, VOCABULARY)).toEqual([]);
  });

  it('comes back out cleanly, with any check written about it', () => {
    const applied = applySuggestion(spec(), LINK, VOCABULARY);
    const withRule: ModuleSpec = {
      ...applied,
      rules: [
        ...applied.rules,
        { code: 'CONTRACT_REQUIRED', message: 'Pick a contract.', kind: 'required', field: 'contract_2', min_value: null, max_value: null, other_field: '', severity: 'error' },
      ],
    };
    const back = withdrawSuggestion(withRule, LINK);
    expect(back.entity.fields).toEqual(spec().entity.fields);
    expect(back.rules).toEqual(spec().rules);
  });

  it('is not offered for a module switched off here', () => {
    const doc: Suggestion = { ...LINK, id: 'link:document', target: 'document', patch: { field: { ...LINK.patch.field!, target: 'document' } } };
    expect(canApply(spec(), doc, VOCABULARY)).toBe(false);
    expect(applySuggestion(spec(), doc, VOCABULARY)).toEqual(spec());
  });

  it('is not offered past the field cap', () => {
    const full = { ...spec(), entity: { ...spec().entity, fields: [...spec().entity.fields, ...spec().entity.fields.map((f) => ({ ...f, name: `${f.name}_x` }))] } };
    expect(full.entity.fields).toHaveLength(4);
    expect(canApply(full, LINK, VOCABULARY)).toBe(false);
  });
});

describe('applying a feature', () => {
  it('switches each one on, and off again', () => {
    for (const s of [STATUS, DUE, EXPORT, COMMENTS]) {
      const on = applySuggestion(spec(), s, VOCABULARY);
      expect(isApplied(on, s)).toBe(true);
      const off = withdrawSuggestion(on, s);
      expect(isApplied(off, s)).toBe(false);
      expect(featuresOf(off)).toEqual(featuresOf(spec()));
    }
  });

  it('copies the states rather than sharing them with the suggestion', () => {
    const on = applySuggestion(spec(), STATUS, VOCABULARY);
    const states = on.features?.status?.states ?? [];
    expect(states).toEqual(STATUS.patch.status?.states);
    expect(states[0]).not.toBe(STATUS.patch.status?.states[0]);
  });

  it('leaves a feature without its patch unapplied', () => {
    const empty: Suggestion = { ...STATUS, patch: {} };
    expect(canApply(spec(), empty)).toBe(false);
    expect(applySuggestion(spec(), empty)).toEqual(spec());
  });

  it('lets a due date follow its field and go when the field goes', async () => {
    const { removeField, updateField } = await import('./draft');
    const on = applySuggestion(spec(), DUE, VOCABULARY);
    const renamed = updateField(on, 1, { name: 'deadline' });
    expect(renamed.features?.due?.field).toBe('deadline');
    const removed = removeField(renamed, 1);
    expect(removed.features?.due).toBeNull();
  });
});

describe('toggling and accepting all', () => {
  it('ticks and unticks', () => {
    const on = toggleSuggestion(spec(), EXPORT, true, VOCABULARY);
    expect(on.features?.export).toBe(true);
    expect(toggleSuggestion(on, EXPORT, false, VOCABULARY).features?.export).toBe(false);
  });

  it('applies everything that can apply, once', () => {
    const all = applyAll(spec(), [LINK, STATUS, DUE, EXPORT, COMMENTS, LINK], VOCABULARY);
    expect(all.entity.fields.filter((f) => f.type === 'link')).toHaveLength(1);
    expect(featuresOf(all)).toMatchObject({ export: true, comments: true });
    expect(all.features?.status).toBeTruthy();
    expect(all.features?.due).toEqual({ field: 'due_on', remind_days_before: 3 });
    expect(specProblems(all, VOCABULARY)).toEqual([]);
  });

  it('puts the applied link on the wire with its target', () => {
    const wire = toWireSpec(applySuggestion(spec(), LINK, VOCABULARY), true);
    expect(wire.entity.fields.find((f) => f.type === 'link')?.target).toBe('contract');
  });
});

describe('suggestionSignature', () => {
  it('moves when a field is added, not when a suggestion is accepted', () => {
    const before = suggestionSignature(spec());
    expect(suggestionSignature(applyAll(spec(), [LINK, STATUS], VOCABULARY))).toBe(before);
    const added = { ...spec(), entity: { ...spec().entity, fields: [...spec().entity.fields, { ...spec().entity.fields[0]!, name: 'more' }] } };
    expect(suggestionSignature(added)).not.toBe(before);
  });
});

describe('a link that takes over a field the person already has', () => {
  const OVER: Suggestion = { ...LINK, id: 'link:contract:field', reason_code: 'link_field_name', reason_params: { field: 'Contract reference' } };

  it('turns that field into the link, keeping its label and place', () => {
    const next = applySuggestion(spec(), OVER, VOCABULARY);
    expect(next.entity.fields).toHaveLength(2);
    expect(next.entity.fields[0]).toMatchObject({ name: 'contract', label: 'Contract reference', type: 'link', target: 'contract' });
    expect(isApplied(next, OVER)).toBe(true);
    expect(specProblems(next, VOCABULARY)).toEqual([]);
  });

  it('gives the field back exactly as it was when unticked', () => {
    const back = withdrawSuggestion(applySuggestion(spec(), OVER, VOCABULARY), OVER);
    expect(back.entity.fields).toEqual(spec().entity.fields);
  });

  it('never sends the remembered column to the server', () => {
    const wire = toWireSpec(applySuggestion(spec(), OVER, VOCABULARY), true);
    expect(wire.entity.fields[0]).not.toHaveProperty('replaced');
  });

  it('goes in beside the column when the server proposes a fresh name, and comes out cleanly', () => {
    // A column whose name would make the index too long cannot be converted;
    // the server then proposes a shorter, unused name under the same reason.
    const beside: Suggestion = { ...OVER, patch: { field: { ...LINK.patch.field!, name: 'contract_link' } } };
    const on = applySuggestion(spec(), beside, VOCABULARY);
    expect(on.entity.fields).toHaveLength(3);
    expect(on.entity.fields[0]).toEqual(spec().entity.fields[0]);
    expect(on.entity.fields[2]).toMatchObject({ name: 'contract_link', type: 'link' });
    expect(withdrawSuggestion(on, beside).entity.fields).toEqual(spec().entity.fields);
  });

  it('is not held back by the field cap, since it adds no field', () => {
    const full = { ...spec(), entity: { ...spec().entity, fields: [...spec().entity.fields, ...spec().entity.fields.map((f) => ({ ...f, name: `${f.name}_x` }))] } };
    expect(canApply(full, OVER, VOCABULARY)).toBe(true);
  });
});

describe('what the server refuses', () => {
  it('keeps stages off while a field is already called status', () => {
    const clash = { ...spec(), entity: { ...spec().entity, fields: [...spec().entity.fields, { ...spec().entity.fields[0]!, name: 'status' }] } };
    expect(blockedBy(clash, STATUS, VOCABULARY)).toBe('status_field');
    expect(applySuggestion(clash, STATUS, VOCABULARY)).toEqual(clash);
  });

  it('offers reminders and comments only to a register kept per project', () => {
    const loose = { ...spec(), entity: { ...spec().entity, project_scoped: false } };
    expect(blockedBy(loose, DUE, VOCABULARY)).toBe('needs_project');
    expect(blockedBy(loose, COMMENTS, VOCABULARY)).toBe('needs_project');
    expect(blockedBy(loose, EXPORT, VOCABULARY)).toBeNull();
    expect(blockedBy(spec(), DUE, VOCABULARY)).toBeNull();
  });

  it('names a link to a switched-off module and a full register', () => {
    const doc: Suggestion = { ...LINK, id: 'link:document', target: 'document', patch: { field: { ...LINK.patch.field!, target: 'document' } } };
    expect(blockedBy(spec(), doc, VOCABULARY)).toBe('unavailable');
    const full = { ...spec(), entity: { ...spec().entity, fields: [...spec().entity.fields, ...spec().entity.fields.map((f) => ({ ...f, name: `${f.name}_x` }))] } };
    expect(blockedBy(full, LINK, VOCABULARY)).toBe('full');
  });

  it('reports reminders or comments on a register with no project as a problem too', () => {
    const loose = { ...spec(), entity: { ...spec().entity, project_scoped: false } };
    const on = { ...loose, features: { ...featuresOf(loose), due: { field: 'due_on', remind_days_before: 3 }, comments: true } };
    expect(specProblems(on, VOCABULARY).map((p) => p.code)).toEqual(['due_needs_project', 'comments_needs_project']);
  });
});
