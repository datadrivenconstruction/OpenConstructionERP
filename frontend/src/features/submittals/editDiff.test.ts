// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The submittal edit form carried two defects that compound each other.
//
// It PATCHed every field on every save, so correcting a spec section also
// rewrote the description as it stood when the list was last read, undoing
// anyone else's edit to it without a word.
//
// And it mapped an emptied field to `undefined`, which JSON.stringify drops
// from the body entirely. Clearing the description or the date therefore did
// nothing at all: the value came straight back on the next read. The date is
// the sharper case, because the backend field sits behind a
// `^\d{4}-\d{2}-\d{2}$` pattern, so '' would not have worked either. Only
// `null` clears it.
//
// These tests hold the payload builder to both: untouched fields stay out of
// the body, cleared fields go in with a value the wire can actually carry.

import { describe, it, expect } from 'vitest';

import { submittalFormData, buildSubmittalPatch } from './SubmittalsPage';
import { LEGACY_REGISTER_FIELDS, type Submittal } from './api';

const SUBMITTAL: Submittal = {
  ...LEGACY_REGISTER_FIELDS,
  id: 's1',
  project_id: 'p1',
  submittal_number: 'SUB-001',
  title: 'Curtain wall shop drawings',
  spec_section: '08 44 13',
  type: 'shop_drawing',
  status: 'draft',
  ball_in_court: null,
  ball_in_court_name: null,
  revision: 1,
  date_submitted: null,
  date_required: '2026-09-01',
  description: 'Glazing layout for the north elevation.',
  review_notes: null,
  linked_boq_item_ids: [],
  metadata: {},
  created_by: null,
  created_at: '2026-07-01T09:00:00',
  updated_at: '2026-07-01T09:00:00',
};

/** The page's own payload builder, so a regression there fails these tests. */
const buildPatch = buildSubmittalPatch;

describe('the submittal edit payload', () => {
  it('is empty when the user opens the form and saves without touching it', () => {
    const base = submittalFormData(SUBMITTAL);
    expect(buildPatch(base, base)).toEqual({});
  });

  it('carries the edited field and leaves the rest out', () => {
    const base = submittalFormData(SUBMITTAL);
    const form = { ...base, spec_section: '08 44 26' };

    const patch = buildPatch(form, base);

    expect(patch).toEqual({ spec_section: '08 44 26' });
    // The description the user never opened must not be in the body, so a
    // concurrent edit to it survives this save.
    expect(patch).not.toHaveProperty('description');
  });

  it('actually clears a description instead of dropping the key', () => {
    const base = submittalFormData(SUBMITTAL);
    const form = { ...base, description: '' };

    const patch = buildPatch(form, base);

    expect(patch).toHaveProperty('description');
    expect(patch.description).toBe('');
    // `undefined` is what the old code sent, and JSON.stringify removes it,
    // which is why clearing the field silently did nothing.
    expect(patch.description).not.toBeUndefined();
  });

  it('clears a date with null, which is the only value the backend accepts', () => {
    const base = submittalFormData(SUBMITTAL);
    const form = { ...base, date_required: '' };

    const patch = buildPatch(form, base);

    expect(patch.date_required).toBeNull();
    expect(patch.date_required).not.toBe('');
  });

  it('clears a spec section rather than leaving the old one in place', () => {
    const base = submittalFormData(SUBMITTAL);
    const form = { ...base, spec_section: '' };

    expect(buildPatch(form, base)).toEqual({ spec_section: '' });
  });

  it('leaves an untouched date out of the body entirely', () => {
    const base = submittalFormData(SUBMITTAL);
    const form = { ...base, title: 'Curtain wall shop drawings rev B' };

    expect(buildPatch(form, base)).not.toHaveProperty('date_required');
  });

  it('renames the type field to what the API expects', () => {
    const base = submittalFormData(SUBMITTAL);
    const form = { ...base, type: 'product_data' as const };

    const patch = buildPatch(form, base);

    expect(patch).toEqual({ submittal_type: 'product_data' });
    expect(patch).not.toHaveProperty('type');
  });

  it('normalises a missing spec section and date to empty strings', () => {
    // Both are nullable on the wire. If the baseline kept null while the form
    // held '', every save would report them as changed and put them back.
    const base = submittalFormData({
      ...SUBMITTAL,
      spec_section: null,
      date_required: null,
    });

    expect(base.spec_section).toBe('');
    expect(base.date_required).toBe('');
    expect(buildPatch(base, base)).toEqual({});
  });
});
