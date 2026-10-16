// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure unit tests for the RFI UX-overhaul helpers.
 *
 * Coverage:
 *   1. ``ballInCourtSide`` returns ``you`` only when the RFI is in the
 *      viewer's lap AND still actionable (draft / open).
 *   2. ``ballInCourtSide`` returns ``them`` for unowned-by-viewer rows
 *      and ``answered`` / ``closed`` for terminal states.
 *   3. ``ballInCourtSide`` falls back to ``assigned_to`` when
 *      ``ball_in_court`` is null (legacy rows pre-BIC column).
 *   4. ``daysOverdue`` returns ``null`` for missing due dates, a
 *      negative number for future-dated rows, and a positive integer
 *      for past-due rows — with midnight-to-midnight rounding so the
 *      number does not flip just because the clock crossed 00:00.
 *   5. ``BIC_SIDE_CFG`` exposes all four sides with i18n keys.
 */

import { describe, it, expect } from 'vitest';
import {
  ballInCourtSide,
  BIC_SIDE_CFG,
  daysOverdue,
} from '../RFIPage';
import type { RFI } from '../api';

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

describe('ballInCourtSide', () => {
  it('returns "you" when BIC matches viewer and status is actionable', () => {
    expect(
      ballInCourtSide(
        rfi({ status: 'open', ball_in_court: 'user-1' }),
        'user-1',
      ),
    ).toBe('you');
  });

  it('returns "you" via assigned_to fallback when ball_in_court is null', () => {
    expect(
      ballInCourtSide(
        rfi({ status: 'open', assigned_to: 'user-2', ball_in_court: null }),
        'user-2',
      ),
    ).toBe('you');
  });

  it('returns "them" when the viewer does not own the next move', () => {
    expect(
      ballInCourtSide(
        rfi({ status: 'open', ball_in_court: 'someone-else' }),
        'user-1',
      ),
    ).toBe('them');
  });

  it('returns "them" for anonymous viewers (no JWT sub)', () => {
    expect(
      ballInCourtSide(rfi({ status: 'open', ball_in_court: 'u' }), null),
    ).toBe('them');
  });

  it('returns "answered" regardless of viewer identity', () => {
    expect(
      ballInCourtSide(
        rfi({ status: 'answered', ball_in_court: 'user-1' }),
        'user-1',
      ),
    ).toBe('answered');
  });

  it('returns "closed" for both closed and void terminal states', () => {
    expect(ballInCourtSide(rfi({ status: 'closed' }), 'user-1')).toBe('closed');
    expect(ballInCourtSide(rfi({ status: 'void' }), 'user-1')).toBe('closed');
  });

  it('returns "you" for draft RFIs the viewer was tagged as BIC on', () => {
    expect(
      ballInCourtSide(
        rfi({ status: 'draft', ball_in_court: 'user-1' }),
        'user-1',
      ),
    ).toBe('you');
  });
});

describe('daysOverdue', () => {
  /**
   * Build a YYYY-MM-DD string ``delta`` days offset from *today*'s LOCAL
   * midnight. The production helper parses ``new Date('YYYY-MM-DD')``
   * which is interpreted as UTC midnight, so we mirror that round-trip
   * here by going through ``Date.UTC`` to avoid local-timezone drift on
   * the test boundary.
   */
  function isoDaysFromNow(delta: number): string {
    const now = new Date();
    const utc = new Date(
      Date.UTC(now.getFullYear(), now.getMonth(), now.getDate() + delta),
    );
    return utc.toISOString().slice(0, 10);
  }

  it('returns null for missing or malformed due dates', () => {
    expect(daysOverdue(null)).toBeNull();
    expect(daysOverdue('not a date')).toBeNull();
  });

  it('returns a finite integer for any past date', () => {
    expect(Number.isInteger(daysOverdue(isoDaysFromNow(-3)))).toBe(true);
  });

  it('past-due rows have a positive delta', () => {
    expect(daysOverdue(isoDaysFromNow(-3))!).toBeGreaterThan(0);
    expect(daysOverdue(isoDaysFromNow(-30))!).toBeGreaterThan(0);
  });

  it('future rows have a non-positive delta (still has time)', () => {
    expect(daysOverdue(isoDaysFromNow(5))!).toBeLessThanOrEqual(0);
  });

  it('ranks "today + 30 past" as more overdue than "today + 3 past"', () => {
    const far = daysOverdue(isoDaysFromNow(-30))!;
    const near = daysOverdue(isoDaysFromNow(-3))!;
    expect(far).toBeGreaterThan(near);
  });

  it('returns the exact integer day count (no off-by-one)', () => {
    // The helper must read the bare YYYY-MM-DD due date on the same
    // calendar basis it parses it (UTC), so a due date is never shifted a
    // day earlier in negative-offset timezones. A date N days in the past
    // is exactly +N overdue; today is exactly 0.
    expect(daysOverdue(isoDaysFromNow(0))).toBe(0);
    expect(daysOverdue(isoDaysFromNow(-1))).toBe(1);
    expect(daysOverdue(isoDaysFromNow(-7))).toBe(7);
    expect(daysOverdue(isoDaysFromNow(1))).toBe(-1);
  });
});

describe('BIC_SIDE_CFG', () => {
  it('exposes a config entry for every BallInCourtSide value', () => {
    for (const side of ['you', 'them', 'answered', 'closed'] as const) {
      const cfg = BIC_SIDE_CFG[side];
      expect(cfg.cls).toBeTruthy();
      expect(cfg.key).toMatch(/^rfi\.bic_/);
      expect(cfg.fallback).toBeTruthy();
    }
  });

  it('uses distinct CSS classes per side so the visual differs', () => {
    const cls = new Set(
      (['you', 'them', 'answered', 'closed'] as const).map(
        (s) => BIC_SIDE_CFG[s].cls,
      ),
    );
    expect(cls.size).toBe(4);
  });
});
