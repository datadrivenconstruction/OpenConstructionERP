// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  deadlineVariant,
  durationParts,
  einvoiceVisible,
  formatDuration,
  isDueSoon,
  lastMonth,
  primaryAction,
  primaryDeadline,
  stepIndex,
} from './lifecycleView';
import type { EInvoiceSetupRow, LifecycleDeadline } from './lifecycleApi';

const row = (country: string): EInvoiceSetupRow => ({
  country,
  platform: 'X',
  label: 'X',
  profile_id: 'p',
  mode: 'export',
  ready: true,
  missing: [],
  has_consolidation: false,
});

const deadline = (due_at: string, state: LifecycleDeadline['state']): LifecycleDeadline => ({
  id: 'd',
  action: 'submit',
  starts_at: '2026-03-10T09:00:00+00:00',
  due_at,
  state,
  seconds_left: 0,
});

describe('e-invoice lifecycle view', () => {
  it('places each status on the stepper', () => {
    expect(stepIndex('draft')).toBe(0);
    expect(stepIndex('validated')).toBe(1);
    expect(stepIndex('submitted')).toBe(2);
    expect(stepIndex('reported')).toBe(3);
    expect(stepIndex('delivered')).toBe(4);
  });

  it('maps deadline state to a badge tone', () => {
    expect(deadlineVariant('ok')).toBe('neutral');
    expect(deadlineVariant('warning')).toBe('warning');
    expect(deadlineVariant('overdue')).toBe('error');
  });

  it('reads 1.5 h left (SA worked example) as one hour, and days for long windows', () => {
    expect(durationParts(5400)).toEqual({ value: 1, unit: 'hour' });
    expect(durationParts(-3 * 86400)).toEqual({ value: 3, unit: 'day' });
    expect(formatDuration(21 * 3600, 'en')).toBe('21 hours');
  });

  it('shows nothing without an e-invoicing market, and narrows by seller country', () => {
    expect(einvoiceVisible(undefined)).toBe(false);
    expect(einvoiceVisible([])).toBe(false);
    expect(einvoiceVisible([row('SA')])).toBe(true);
    expect(einvoiceVisible([row('SA')], 'de')).toBe(false);
    expect(einvoiceVisible([row('SA')], 'sa')).toBe(true);
  });

  it('picks the earliest deadline and the first non-download action', () => {
    const d = primaryDeadline([deadline('2026-03-12T00:00:00', 'ok'), deadline('2026-03-11T09:00:00', 'warning')]);
    expect(d?.due_at).toBe('2026-03-11T09:00:00');
    expect(isDueSoon(d)).toBe(true);
    expect(primaryAction(['download'])).toBeNull();
    expect(primaryAction(['correct', 'download'])).toBe('correct');
  });

  it('defaults the consolidation period to last month', () => {
    expect(lastMonth(new Date(Date.UTC(2026, 10, 2)))).toBe('2026-10');
    expect(lastMonth(new Date(Date.UTC(2027, 0, 5)))).toBe('2026-12');
  });
});
