// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a generated screen puts on the wire, and what it refuses to send.
 *
 * These are the rules a generic renderer gets quietly wrong: a money value that
 * went through a float, a cleared field that rewrote a column nobody touched, a
 * "cannot be in the future" rule that fires an hour early for anyone east of
 * UTC. Each of those is a defect a screenshot cannot show, so they are asserted
 * here rather than left to the component tests.
 */
import { describe, it, expect } from 'vitest';

import type { GeneratedRecord, ModuleFieldSpec, ModuleSpec, ModuleRuleSpec } from './api';
import {
  MAX_LIST_COLUMNS,
  NOT_A_NUMBER_CODE,
  REQUIRED_CODE,
  blankValues,
  canSubmit,
  dueState,
  evaluateDraft,
  formatValue,
  isBlank,
  isDoneStatus,
  listColumns,
  statusStates,
  toCreatePayload,
  toLocalInputValue,
  toUpdatePayload,
  valuesFromRecord,
} from './fields';

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
    message: `${over.code} did not hold`,
    min_value: null,
    max_value: null,
    other_field: '',
    severity: 'error',
    ...over,
  };
}

/** A module close to what the wizard actually produces: every field type once. */
function diarySpec(over: Partial<ModuleSpec> = {}): ModuleSpec {
  return {
    key: 'site_diary',
    display_name: 'Site Diary',
    description: 'What happened on site today.',
    category: 'community',
    icon: 'Boxes',
    version: '0.1.0',
    author: '',
    drafted_by: 'wizard',
    entity: {
      name: 'entry',
      display_name: 'Entry',
      plural_name: 'Entries',
      project_scoped: true,
      fields: [
        field({ name: 'reference', label: 'Reference', type: 'text', required: true }),
        field({ name: 'notes', label: 'Notes', type: 'long_text', in_list: false }),
        field({ name: 'crew_size', label: 'Crew size', type: 'integer' }),
        field({ name: 'poured', label: 'Concrete poured', type: 'number', unit: 'm3' }),
        field({ name: 'day_cost', label: 'Cost of the day', type: 'money' }),
        field({ name: 'recorded_on', label: 'Recorded on', type: 'date' }),
        field({ name: 'started_at', label: 'Started at', type: 'datetime' }),
        field({ name: 'signed_off', label: 'Signed off', type: 'boolean' }),
        field({ name: 'weather', label: 'Weather', type: 'select', options: ['dry', 'rain', 'frost'] }),
      ],
    },
    rules: [rule({ code: 'REFERENCE_REQUIRED', kind: 'required', field: 'reference' })],
    ...over,
  };
}

const LABELS = { yes: 'Yes', no: 'No', empty: '—' };

describe('blankValues', () => {
  it('gives every field a value so no input starts uncontrolled', () => {
    const spec = diarySpec();
    const values = blankValues(spec);
    expect(Object.keys(values).sort()).toEqual(spec.entity.fields.map((f) => f.name).sort());
    expect(values.signed_off).toBe(false);
    expect(values.reference).toBe('');
  });
});

describe('listColumns', () => {
  it('takes the fields the spec marked for the list, in spec order', () => {
    const columns = listColumns(diarySpec());
    expect(columns.map((c) => c.name)).toEqual([
      'reference',
      'crew_size',
      'poured',
      'day_cost',
      'recorded_on',
      'started_at',
    ]);
    expect(columns.map((c) => c.name)).not.toContain('notes');
  });

  it('caps the table rather than rendering forty columns', () => {
    const wide = diarySpec();
    wide.entity.fields = Array.from({ length: 40 }, (_, i) => field({ name: `f${i}` }));
    expect(listColumns(wide)).toHaveLength(MAX_LIST_COLUMNS);
  });

  it('falls back to the first fields when the spec marks none', () => {
    const none = diarySpec();
    none.entity.fields = none.entity.fields.map((f) => ({ ...f, in_list: false }));
    const columns = listColumns(none);
    expect(columns.length).toBeGreaterThan(0);
    expect(columns[0]?.name).toBe('reference');
  });
});

describe('toCreatePayload', () => {
  it('keeps money and quantities as strings, exactly as typed', () => {
    const spec = diarySpec();
    const values = { ...blankValues(spec), day_cost: '1234.05', poured: '0.1' };
    const payload = toCreatePayload(spec, values, 'p1');

    expect(payload.day_cost).toBe('1234.05');
    expect(payload.poured).toBe('0.1');
    expect(typeof payload.day_cost).toBe('string');
    expect(typeof payload.poured).toBe('string');
  });

  it('does not lose a value a double cannot hold', () => {
    // 16 significant digits: a JS number rounds this, a Decimal does not. The
    // point of keeping money a string is that this survives the screen.
    const spec = diarySpec();
    const exact = '9007199254740993.01';
    const payload = toCreatePayload(spec, { ...blankValues(spec), day_cost: exact }, 'p1');
    expect(payload.day_cost).toBe(exact);
  });

  it('sends a count as a number and a checkbox as a boolean', () => {
    const spec = diarySpec();
    const values = { ...blankValues(spec), crew_size: '12', signed_off: true };
    const payload = toCreatePayload(spec, values, 'p1');
    expect(payload.crew_size).toBe(12);
    expect(payload.signed_off).toBe(true);
  });

  it('sends the project when the entity is scoped to one', () => {
    const payload = toCreatePayload(diarySpec(), blankValues(diarySpec()), 'proj-7');
    expect(payload.project_id).toBe('proj-7');
  });

  it('sends no project key at all when the entity is not scoped', () => {
    // The generated Create schema is extra="forbid", so an unwanted project_id
    // is a 422 rather than a harmless extra key.
    const spec = diarySpec();
    spec.entity.project_scoped = false;
    const payload = toCreatePayload(spec, blankValues(spec), 'proj-7');
    expect('project_id' in payload).toBe(false);
  });

  it('omits an empty optional field but still names an empty required one', () => {
    const spec = diarySpec();
    const payload = toCreatePayload(spec, blankValues(spec), 'p1');
    expect('crew_size' in payload).toBe(false);
    expect('reference' in payload).toBe(true);
    expect(payload.reference).toBeNull();
  });

  it('sends a datetime as an instant, not as a local wall clock reading', () => {
    // The test process runs in UTC (see src/test/setup.ts), so the local naive
    // string and the instant agree here; what is asserted is the shape - an
    // offset-bearing ISO string rather than the naive one the input produced.
    const spec = diarySpec();
    const payload = toCreatePayload(spec, { ...blankValues(spec), started_at: '2026-08-07T09:30' }, 'p1');
    expect(payload.started_at).toBe('2026-08-07T09:30:00.000Z');
  });

  it('passes text the server can name rather than silently sending zero', () => {
    const spec = diarySpec();
    const payload = toCreatePayload(spec, { ...blankValues(spec), crew_size: 'twelve' }, 'p1');
    expect(payload.crew_size).toBe('twelve');
  });
});

describe('toUpdatePayload', () => {
  const spec = diarySpec();
  const record: GeneratedRecord = {
    id: 'r1',
    project_id: 'p1',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    reference: 'SD-001',
    notes: 'Formwork struck.',
    crew_size: 8,
    poured: '12.50',
    day_cost: '4100.00',
    recorded_on: '2026-08-01',
    started_at: '2026-08-01T07:00:00+00:00',
    signed_off: true,
    weather: 'dry',
  };

  it('sends nothing when nothing changed', () => {
    expect(toUpdatePayload(spec, valuesFromRecord(spec, record), record)).toEqual({});
  });

  it('sends only the field that changed', () => {
    const values = { ...valuesFromRecord(spec, record), crew_size: '9' };
    expect(toUpdatePayload(spec, values, record)).toEqual({ crew_size: 9 });
  });

  it('sends an explicit null for a field the user cleared', () => {
    const values = { ...valuesFromRecord(spec, record), notes: '' };
    expect(toUpdatePayload(spec, values, record)).toEqual({ notes: null });
  });

  it('does not resend a money value just because it round-tripped', () => {
    // '12.50' must come back out of the form as '12.50'. If the form parsed it
    // to a number and rendered it back as '12.5', every save would rewrite the
    // column and every audit trail would show a change nobody made.
    const values = valuesFromRecord(spec, record);
    expect(values.poured).toBe('12.50');
    expect(toUpdatePayload(spec, values, record)).toEqual({});
  });
});

describe('valuesFromRecord', () => {
  const spec = diarySpec();

  it('reads a stored instant back into what the datetime input wants', () => {
    const values = valuesFromRecord(spec, {
      id: 'r1',
      created_at: '',
      updated_at: '',
      started_at: '2026-08-07T09:30:00+00:00',
    });
    expect(values.started_at).toBe('2026-08-07T09:30');
  });

  it('leaves a missing value blank rather than printing null', () => {
    const values = valuesFromRecord(spec, { id: 'r1', created_at: '', updated_at: '', notes: null });
    expect(values.notes).toBe('');
    expect(values.signed_off).toBe(false);
  });

  it('survives a datetime it cannot parse', () => {
    const values = valuesFromRecord(spec, {
      id: 'r1',
      created_at: '',
      updated_at: '',
      started_at: 'not a date',
    });
    expect(values.started_at).toBe('');
  });
});

describe('toLocalInputValue', () => {
  it('pads to the minute so the input accepts it', () => {
    expect(toLocalInputValue('2026-01-02T03:04:00Z')).toBe('2026-01-02T03:04');
  });
});

describe('evaluateDraft', () => {
  const NOW = new Date('2026-08-07T12:00:00Z');

  it('refuses an empty required field before the round trip', () => {
    const spec = diarySpec();
    const findings = evaluateDraft(spec, blankValues(spec), NOW);
    expect(findings.some((f) => f.field === 'reference' && f.code === REQUIRED_CODE)).toBe(true);
    expect(canSubmit(findings)).toBe(false);
  });

  it('shows the module author their own wording, not a platform string', () => {
    const spec = diarySpec();
    const findings = evaluateDraft(spec, blankValues(spec), NOW);
    const fromRule = findings.find((f) => f.code === 'REFERENCE_REQUIRED');
    expect(fromRule?.message).toBe('REFERENCE_REQUIRED did not hold');
    const fromPlatform = findings.find((f) => f.code === REQUIRED_CODE);
    expect(fromPlatform?.message).toBeNull();
  });

  it('catches a quantity that is not a number', () => {
    const spec = diarySpec();
    const findings = evaluateDraft(spec, { ...blankValues(spec), reference: 'a', poured: 'lots' }, NOW);
    expect(findings.some((f) => f.field === 'poured' && f.code === NOT_A_NUMBER_CODE)).toBe(true);
  });

  it('fires a positive rule on zero and a negative, and not on a real amount', () => {
    const spec = diarySpec({ rules: [rule({ code: 'POURED_POSITIVE', kind: 'positive', field: 'poured' })] });
    const base = { ...blankValues(spec), reference: 'a' };
    expect(evaluateDraft(spec, { ...base, poured: '0' }, NOW)).toHaveLength(1);
    expect(evaluateDraft(spec, { ...base, poured: '-3' }, NOW)).toHaveLength(1);
    expect(evaluateDraft(spec, { ...base, poured: '3' }, NOW)).toHaveLength(0);
    // Nothing entered is not a violation; that is what a required rule is for.
    expect(evaluateDraft(spec, { ...base, poured: '' }, NOW)).toHaveLength(0);
  });

  it('fires a range rule on either side and holds inside it', () => {
    const spec = diarySpec({
      rules: [rule({ code: 'CREW_RANGE', kind: 'range', field: 'crew_size', min_value: 1, max_value: 40 })],
    });
    const base = { ...blankValues(spec), reference: 'a' };
    expect(evaluateDraft(spec, { ...base, crew_size: '0' }, NOW)).toHaveLength(1);
    expect(evaluateDraft(spec, { ...base, crew_size: '41' }, NOW)).toHaveLength(1);
    expect(evaluateDraft(spec, { ...base, crew_size: '1' }, NOW)).toHaveLength(0);
    expect(evaluateDraft(spec, { ...base, crew_size: '40' }, NOW)).toHaveLength(0);
  });

  it('fires a one_of rule on a value the list does not know', () => {
    const spec = diarySpec({ rules: [rule({ code: 'WEATHER_KNOWN', kind: 'one_of', field: 'weather' })] });
    const base = { ...blankValues(spec), reference: 'a' };
    expect(evaluateDraft(spec, { ...base, weather: 'hail' }, NOW)).toHaveLength(1);
    expect(evaluateDraft(spec, { ...base, weather: 'frost' }, NOW)).toHaveLength(0);
  });

  it('compares a date against the UTC day, the way the generated validator does', () => {
    const spec = diarySpec({
      rules: [rule({ code: 'NOT_FUTURE', kind: 'not_future', field: 'recorded_on' })],
    });
    const base = { ...blankValues(spec), reference: 'a' };
    expect(evaluateDraft(spec, { ...base, recorded_on: '2026-08-08' }, NOW)).toHaveLength(1);
    // Today is not the future, and neither is any earlier day.
    expect(evaluateDraft(spec, { ...base, recorded_on: '2026-08-07' }, NOW)).toHaveLength(0);
    expect(evaluateDraft(spec, { ...base, recorded_on: '2026-08-06' }, NOW)).toHaveLength(0);
  });

  it('does not call the current minute the future', () => {
    // The wrinkle this guards: the input yields a naive local time and the
    // server reads a naive datetime as UTC. Both sides now speak in instants,
    // so "now" is never a minute ahead of itself.
    const spec = diarySpec({
      rules: [rule({ code: 'STARTED_NOT_FUTURE', kind: 'not_future', field: 'started_at' })],
    });
    const base = { ...blankValues(spec), reference: 'a' };
    expect(evaluateDraft(spec, { ...base, started_at: '2026-08-07T12:00' }, NOW)).toHaveLength(0);
    expect(evaluateDraft(spec, { ...base, started_at: '2026-08-07T12:01' }, NOW)).toHaveLength(1);
  });

  it('fires an order rule only when the pair is the wrong way round', () => {
    const spec = diarySpec({
      rules: [rule({ code: 'ORDER', kind: 'order', field: 'recorded_on', other_field: 'started_at' })],
    });
    const base = { ...blankValues(spec), reference: 'a' };
    expect(
      evaluateDraft(spec, { ...base, recorded_on: '2026-08-09', started_at: '2026-08-08T00:00' }, NOW),
    ).toHaveLength(1);
    expect(
      evaluateDraft(spec, { ...base, recorded_on: '2026-08-07', started_at: '2026-08-08T00:00' }, NOW),
    ).toHaveLength(0);
    // One half missing means the pair says nothing.
    expect(evaluateDraft(spec, { ...base, recorded_on: '2026-08-09' }, NOW)).toHaveLength(0);
  });

  it('lets a warning through and stops on an error', () => {
    const spec = diarySpec({
      rules: [rule({ code: 'SOFT', kind: 'positive', field: 'poured', severity: 'warning' })],
    });
    const findings = evaluateDraft(spec, { ...blankValues(spec), reference: 'a', poured: '0' }, NOW);
    expect(findings).toHaveLength(1);
    expect(canSubmit(findings)).toBe(true);
  });

  it('ignores a rule that names a field the entity does not have', () => {
    const spec = diarySpec({ rules: [rule({ code: 'GHOST', kind: 'required', field: 'nowhere' })] });
    const findings = evaluateDraft(spec, { ...blankValues(spec), reference: 'a' }, NOW);
    expect(findings).toHaveLength(0);
  });
});

describe('formatValue', () => {
  const spec = diarySpec();
  const byName = (name: string) => spec.entity.fields.find((f) => f.name === name)!;

  it('renders a quantity with its unit', () => {
    expect(formatValue(byName('poured'), '12.5', LABELS)).toBe('12.50 m3');
  });

  it('renders a count without decimals', () => {
    expect(formatValue(byName('crew_size'), 8, LABELS)).toBe('8');
  });

  it('names a checkbox rather than printing true', () => {
    expect(formatValue(byName('signed_off'), true, LABELS)).toBe('Yes');
    expect(formatValue(byName('signed_off'), false, LABELS)).toBe('No');
  });

  it('marks an absent value rather than leaving the cell blank', () => {
    expect(formatValue(byName('notes'), null, LABELS)).toBe('—');
    expect(formatValue(byName('recorded_on'), undefined, LABELS)).toBe('—');
  });

  it('keeps a date-only value on its own calendar day', () => {
    // Parsed as UTC midnight and rendered in UTC, so it never slides a day back.
    expect(formatValue(byName('recorded_on'), '2026-08-01', LABELS)).toContain('2026');
    expect(formatValue(byName('recorded_on'), '2026-08-01', LABELS)).toContain('01');
  });

  it('shows a moment with its time', () => {
    const shown = formatValue(byName('started_at'), '2026-08-07T09:30:00+00:00', LABELS);
    expect(shown).toContain('09:30');
  });

  it('shows an unparseable stored value rather than swallowing it', () => {
    expect(formatValue(byName('started_at'), 'whenever', LABELS)).toBe('whenever');
  });
});

describe('isBlank', () => {
  it('treats whitespace as nothing entered and false as an answer', () => {
    expect(isBlank('   ')).toBe(true);
    expect(isBlank('')).toBe(true);
    expect(isBlank(undefined)).toBe(true);
    expect(isBlank(false)).toBe(false);
  });
});

describe('a module that tracks a status', () => {
  const STAGES = {
    status: {
      states: [
        { code: 'open', label: 'Open', done: false },
        { code: 'checked', label: 'Checked', done: false },
        { code: 'closed', label: 'Closed', done: true },
      ],
    },
  };
  const tracked = () => diarySpec({ features: STAGES });

  it('starts a new record in the first stage and sends it', () => {
    const values = blankValues(tracked());
    expect(values.status).toBe('open');
    expect(toCreatePayload(tracked(), { ...values, reference: 'SD-1' })).toMatchObject({ status: 'open' });
  });

  it('sends nothing about a status the module does not track', () => {
    expect(blankValues(diarySpec())).not.toHaveProperty('status');
    expect(toCreatePayload(diarySpec(), { ...blankValues(diarySpec()), reference: 'SD-1', status: 'open' })).not.toHaveProperty('status');
  });

  it('sends a stage change on update, and only when it changed', () => {
    const record = { id: 'r1', reference: 'SD-1', status: 'open' } as unknown as GeneratedRecord;
    const values = valuesFromRecord(tracked(), record);
    expect(values.status).toBe('open');
    expect(toUpdatePayload(tracked(), values, record)).not.toHaveProperty('status');
    expect(toUpdatePayload(tracked(), { ...values, status: 'closed' }, record)).toEqual({ status: 'closed' });
  });

  it('knows which stages count as finished', () => {
    expect(statusStates(tracked()).map((s) => s.code)).toEqual(['open', 'checked', 'closed']);
    expect(isDoneStatus(tracked(), 'closed')).toBe(true);
    expect(isDoneStatus(tracked(), 'checked')).toBe(false);
    expect(isDoneStatus(diarySpec(), 'closed')).toBe(false);
  });
});

describe('a module with a due date', () => {
  const date = field({ name: 'due_on', type: 'date' });
  const at = field({ name: 'due_at', type: 'datetime' });
  const NOW = new Date('2026-10-05T12:00:00Z');

  it('lists the due date even when it was not marked for the list', () => {
    const spec = diarySpec({
      entity: {
        ...diarySpec().entity,
        fields: [...diarySpec().entity.fields, { ...date, in_list: false }],
      },
      features: { due: { field: 'due_on', remind_days_before: 3 } },
    });
    expect(listColumns(spec).map((f) => f.name)).toContain('due_on');
  });

  it('marks a past date overdue and a near one soon, counted in calendar days', () => {
    expect(dueState(date, '2026-10-04', 3, false, NOW)).toBe('overdue');
    // Today is not overdue yet, however late in the day it is.
    expect(dueState(date, '2026-10-05', 3, false, NOW)).toBe('soon');
    expect(dueState(date, '2026-10-08', 3, false, NOW)).toBe('soon');
    expect(dueState(date, '2026-10-09', 3, false, NOW)).toBeNull();
  });

  it('reads a date and time to the minute', () => {
    expect(dueState(at, '2026-10-05T11:00:00Z', 1, false, NOW)).toBe('overdue');
    expect(dueState(at, '2026-10-06T11:00:00Z', 1, false, NOW)).toBe('soon');
  });

  it('never flags a finished record or an empty date', () => {
    expect(dueState(date, '2026-01-01', 3, true, NOW)).toBeNull();
    expect(dueState(date, '', 3, false, NOW)).toBeNull();
    expect(dueState(date, null, 3, false, NOW)).toBeNull();
    expect(dueState(date, 'not a date', 3, false, NOW)).toBeNull();
  });
});
