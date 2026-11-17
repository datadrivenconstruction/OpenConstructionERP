// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The print view of a progress statement, from the worked example: agreement
// 100,000 with 5,000 approved changes, retention 10 percent, completed to date
// 75,000, retention held 7,500, previously certified 36,000, current due 31,500.

import { describe, it, expect } from 'vitest';
import { buildStatementHtml, escapeHtml, formatAmount, formatPercent, type StatementLabels } from './statementPrint';
import { toggleRole } from './requiredDocuments';
import type { PayAppStatement } from './api';

const labels: StatementLabels = {
  title: 'Progress statement',
  application: 'Application',
  period: 'Period',
  status: 'Status',
  scheduled_value: 'Scheduled value',
  previous: 'Previous',
  this_period: 'This period',
  total_completed: 'Completed',
  percent_complete: '% complete',
  retention: 'Retention',
  balance_to_finish: 'Balance',
  original_contract_sum: 'Original contract sum',
  change_orders: 'Change orders',
  contract_sum_to_date: 'Contract sum to date',
  completed_to_date: 'Total completed to date',
  retention_held: 'Retention held',
  previous_certified: 'Previously certified',
  current_due: 'Current payment due',
  total: 'Total',
};

const statement: PayAppStatement = {
  payment_application_id: 'pa-4',
  agreement_id: 'ag-1',
  application_number: 'PA-0004',
  status: 'submitted',
  period_start: '2026-11-01',
  period_end: '2026-11-30',
  currency: 'USD',
  override_reason: null,
  lines: [
    {
      work_package_id: 'c',
      name: 'Concrete <b>',
      scheduled_value: '60000.00',
      previous: '30000.00',
      this_period: '15000.00',
      this_period_percent: '25.00',
      total_completed: '45000.00',
      percent_complete: '75.00',
      retention: '4500.00',
      balance_to_finish: '15000.00',
    },
  ],
  summary: {
    original_contract_sum: '95000.00',
    change_orders: '5000.00',
    contract_sum_to_date: '100000.00',
    scheduled_total: '100000.00',
    previous_completed: '40000.00',
    this_period: '35000.00',
    completed_to_date: '75000.00',
    percent_complete: '75.00',
    retention_percent: '10',
    retention_held: '7500.00',
    previous_certified: '36000.00',
    current_due: '31500.00',
    balance_to_finish: '25000.00',
    previous_gross_billed: '40000.00',
    this_gross: '35000.00',
  },
  findings: [],
};

describe('statement print view', () => {
  it('prints the summary figures of the worked example', () => {
    const html = buildStatementHtml(statement, labels, 'Concrete works', 'en-US');
    for (const text of ['$95,000.00', '$5,000.00', '$100,000.00', '$75,000.00', '$7,500.00', '$36,000.00', '$31,500.00']) {
      expect(html).toContain(text);
    }
    expect(html).toContain('PA-0004');
    expect(html).toContain('75.0 %');
  });

  it('never lets a name inject markup', () => {
    const html = buildStatementHtml(statement, labels, '<script>x</script>', 'en-US');
    expect(html).not.toContain('<script>');
    expect(html).toContain('Concrete &lt;b&gt;');
    expect(escapeHtml(`a&b"c'`)).toBe('a&amp;b&quot;c&#39;');
  });

  it('shows a value that is not a number as it came and an empty one as nothing', () => {
    expect(formatAmount('n/a', 'USD')).toBe('n/a');
    expect(formatAmount(null, 'USD')).toBe('');
    expect(formatPercent(undefined)).toBe('');
  });
});

describe('required documents list editing', () => {
  it('adds a role once and removes it on the second toggle', () => {
    const one = toggleRole([], 'safety_plan');
    expect(one).toEqual([{ role: 'safety_plan', signed: false }]);
    expect(toggleRole(one, 'safety_plan')).toEqual([]);
  });
});
