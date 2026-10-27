// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { countBySeverity, markFindings, openFindings, type CheckFinding } from '../checks';

const f = (over: Partial<CheckFinding & { passed: boolean }>): CheckFinding & { passed?: boolean } => ({
  rule_id: 'boq.qty',
  rule_name: 'Quantity set',
  severity: 'warning',
  message: 'Quantity is zero',
  element_ref: 'p1',
  suggestion: null,
  ...over,
});

describe('openFindings', () => {
  it('drops passes, infos and duplicates and puts errors first', () => {
    const out = openFindings([
      f({}),
      f({}),
      f({ passed: true, element_ref: 'p2' }),
      f({ severity: 'info', element_ref: 'p3' }),
      f({ rule_id: 'boq.rate', severity: 'error', element_ref: 'p2', message: 'No rate' }),
    ]);
    expect(out.map((x) => x.message)).toEqual(['No rate', 'Quantity is zero']);
    expect(countBySeverity(out)).toEqual({ error: 1, warning: 1 });
  });
});

describe('markFindings', () => {
  it('marks rows and fields by id with the worst severity and clears stale marks', () => {
    document.body.innerHTML = `
      <table><tbody><tr data-position-id="p1"><td>1</td></tr><tr data-position-id="p2"><td>2</td></tr></tbody></table>
      <input data-check-ref="p2" />`;
    markFindings([f({}), f({ element_ref: 'p2', severity: 'error', message: 'No rate' })]);
    const p1 = document.querySelector<HTMLElement>('[data-position-id="p1"]')!;
    const input = document.querySelector<HTMLElement>('input')!;
    expect(p1.dataset.oeCheck).toBe('warning');
    expect(p1.title).toBe('Quantity is zero');
    expect(input.dataset.oeCheck).toBe('error');
    markFindings([f({ element_ref: 'p2' })]);
    expect(p1.dataset.oeCheck).toBeUndefined();
    expect(p1.hasAttribute('title')).toBe(false);
  });
});
