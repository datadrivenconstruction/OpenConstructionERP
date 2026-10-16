// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Unit tests for the RFI edit-flow wire helpers (Wave 7, frontend wiring).
 *
 * ``buildUpdatePayload`` turns the shared create/edit form state into the
 * exact ``UpdateRFIPayload`` the PATCH /v1/rfi/{id} endpoint expects, and
 * ``formFromRfi`` seeds that form from an existing RFI so an edit opens
 * pre-filled. These are the only new pure units in the wave; the rest of
 * the wiring is React glue covered by the holistic gate.
 *
 * Coverage:
 *   1. buildUpdatePayload sends cleared optional values as ``null`` (so the
 *      backend unsets them) rather than dropping the key.
 *   2. buildUpdatePayload only forwards cost / schedule sub-values when the
 *      corresponding toggle is on, and parses the day count to a number.
 *   3. buildUpdatePayload trims the cost value and rejects a blank one.
 *   4. formFromRfi round-trips through buildUpdatePayload without mutating
 *      the meaningful fields of an existing RFI.
 */

import { describe, it, expect } from 'vitest';
import { buildUpdatePayload, formFromRfi, type RFIFormData } from '../RFIPage';
import type { RFI } from '../api';

function form(partial: Partial<RFIFormData>): RFIFormData {
  return {
    subject: 'S',
    question: 'Q',
    ball_in_court: '',
    ball_in_court_name: '',
    assigned_to: '',
    assigned_to_name: '',
    due_date: '',
    cost_impact: false,
    cost_impact_value: '',
    schedule_impact: false,
    schedule_impact_days: '',
    priority: 'normal',
    discipline: '',
    linked_drawing_ids: [],
    ...partial,
  };
}

function rfi(partial: Partial<RFI>): RFI {
  return {
    id: 'r1',
    project_id: 'p1',
    rfi_number: 'RFI-001',
    request_type: 'RFI',
    subject: 'subject',
    question: 'question',
    official_response: null,
    status: 'open',
    raised_by: 'u-raised',
    assigned_to: null,
    ball_in_court: null,
    responded_by: null,
    responded_at: null,
    cost_impact: false,
    cost_impact_value: null,
    schedule_impact: false,
    schedule_impact_days: null,
    date_required: null,
    response_due_date: null,
    linked_drawing_ids: [],
    attachments: [],
    change_order_id: null,
    created_by: null,
    priority: null,
    discipline: null,
    metadata: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    is_overdue: false,
    days_open: 0,
    ...partial,
  };
}

describe('buildUpdatePayload', () => {
  it('sends cleared optional fields as null (not undefined / dropped)', () => {
    const p = buildUpdatePayload(form({}));
    // The keys are present so the backend unsets the old value.
    expect(p).toHaveProperty('ball_in_court', null);
    expect(p).toHaveProperty('assigned_to', null);
    expect(p).toHaveProperty('response_due_date', null);
    expect(p).toHaveProperty('discipline', null);
    // Impact off -> sub-values null.
    expect(p.cost_impact).toBe(false);
    expect(p).toHaveProperty('cost_impact_value', null);
    expect(p.schedule_impact).toBe(false);
    expect(p).toHaveProperty('schedule_impact_days', null);
  });

  it('forwards required body fields verbatim', () => {
    const p = buildUpdatePayload(
      form({ subject: 'New subject', question: 'New question', priority: 'high' }),
    );
    expect(p.subject).toBe('New subject');
    expect(p.question).toBe('New question');
    expect(p.priority).toBe('high');
  });

  it('only forwards cost value when cost_impact is on, trimmed', () => {
    const off = buildUpdatePayload(form({ cost_impact: false, cost_impact_value: ' 15000 ' }));
    expect(off.cost_impact_value).toBeNull();

    const on = buildUpdatePayload(form({ cost_impact: true, cost_impact_value: ' 15000 ' }));
    expect(on.cost_impact).toBe(true);
    expect(on.cost_impact_value).toBe('15000');

    // Toggle on but blank value -> null (do not send an empty string).
    const blank = buildUpdatePayload(form({ cost_impact: true, cost_impact_value: '   ' }));
    expect(blank.cost_impact_value).toBeNull();
  });

  it('parses schedule days to a number only when the toggle is on and valid', () => {
    const on = buildUpdatePayload(
      form({ schedule_impact: true, schedule_impact_days: '5' }),
    );
    expect(on.schedule_impact).toBe(true);
    expect(on.schedule_impact_days).toBe(5);

    // Negative / non-numeric -> null even when the toggle is on.
    const bad = buildUpdatePayload(
      form({ schedule_impact: true, schedule_impact_days: 'abc' }),
    );
    expect(bad.schedule_impact_days).toBeNull();

    const off = buildUpdatePayload(
      form({ schedule_impact: false, schedule_impact_days: '5' }),
    );
    expect(off.schedule_impact_days).toBeNull();
  });

  it('passes the value through as a string (Decimal-as-string contract)', () => {
    const p = buildUpdatePayload(form({ cost_impact: true, cost_impact_value: '1234.56' }));
    expect(typeof p.cost_impact_value).toBe('string');
    expect(p.cost_impact_value).toBe('1234.56');
  });
});

describe('formFromRfi', () => {
  it('seeds the form from an existing RFI', () => {
    const source = rfi({
      subject: 'Foundation depth',
      question: 'What depth at grid A-3?',
      ball_in_court: 'u-bic',
      assigned_to: 'u-assignee',
      response_due_date: '2026-07-01',
      cost_impact: true,
      cost_impact_value: '15000',
      schedule_impact: true,
      schedule_impact_days: 5,
      priority: 'high',
      discipline: 'structural',
      linked_drawing_ids: ['d1', 'd2'],
    });
    const f = formFromRfi(source);
    expect(f.subject).toBe('Foundation depth');
    expect(f.question).toBe('What depth at grid A-3?');
    expect(f.ball_in_court).toBe('u-bic');
    expect(f.assigned_to).toBe('u-assignee');
    expect(f.due_date).toBe('2026-07-01');
    expect(f.cost_impact).toBe(true);
    expect(f.cost_impact_value).toBe('15000');
    expect(f.schedule_impact).toBe(true);
    expect(f.schedule_impact_days).toBe('5');
    expect(f.priority).toBe('high');
    expect(f.discipline).toBe('structural');
    expect(f.linked_drawing_ids).toEqual(['d1', 'd2']);
  });

  it('falls back to sensible defaults for an empty RFI', () => {
    const f = formFromRfi(rfi({}));
    expect(f.priority).toBe('normal');
    expect(f.discipline).toBe('');
    expect(f.due_date).toBe('');
    expect(f.schedule_impact_days).toBe('');
    expect(f.cost_impact_value).toBe('');
    expect(f.linked_drawing_ids).toEqual([]);
  });

  it('round-trips an existing RFI through the form into a clean payload', () => {
    const source = rfi({
      subject: 'Edit me',
      question: 'Body',
      cost_impact: true,
      cost_impact_value: '900',
      schedule_impact: true,
      schedule_impact_days: 3,
      priority: 'critical',
      discipline: 'mep',
      response_due_date: '2026-08-15',
    });
    const payload = buildUpdatePayload(formFromRfi(source));
    expect(payload.subject).toBe('Edit me');
    expect(payload.question).toBe('Body');
    expect(payload.cost_impact).toBe(true);
    expect(payload.cost_impact_value).toBe('900');
    expect(payload.schedule_impact).toBe(true);
    expect(payload.schedule_impact_days).toBe(3);
    expect(payload.priority).toBe('critical');
    expect(payload.discipline).toBe('mep');
    expect(payload.response_due_date).toBe('2026-08-15');
  });
});
