// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The report page used to print every row of a report flat, passes first in
// count, so 33 warnings sat among 1471 passes and one rule repeated thirty
// times. These cases pin the shape that replaced it: problems by default,
// one group per rule, worst and largest first, and a finding that names its
// position rather than the id the engine stored.
import { describe, it, expect } from 'vitest';
import {
  countFindings,
  groupFindings,
  matchesFilter,
  resolveScope,
  shortDescription,
  type FindingLike,
} from './validationFindings';
import { humaniseRuleId, mappedRuleIds, ruleTitle } from './ruleTitles';

function row(over: Partial<FindingLike>): FindingLike {
  return {
    rule_id: 'boq_quality.unit_rate_in_range',
    rule_name: 'Unit Rate Anomaly Detection',
    severity: 'warning',
    passed: false,
    message: 'Rate far above median',
    element_ref: null,
    suggestion: null,
    ...over,
  };
}

const report: FindingLike[] = [
  row({ passed: true, message: 'OK', element_ref: 'p1' }),
  row({ element_ref: 'p2' }),
  row({ element_ref: 'p3' }),
  row({ rule_id: 'din276.cost_group_required', severity: 'error', element_ref: 'p2', message: 'No KG' }),
  row({ rule_id: 'project_completeness.planned_dates_set', severity: 'warning', message: 'No dates' }),
  row({ rule_id: 'boq_quality.lump_sum_ratio', severity: 'info', message: 'Many lump sums' }),
  row({ rule_id: 'boq_quality.position_has_quantity', passed: true, message: 'OK', element_ref: 'p1' }),
];

const title = (f: FindingLike) => ruleTitle(f.rule_id, f.rule_name, (_k, o) => String(o?.defaultValue ?? ''));

describe('validation findings', () => {
  it('problems means errors and warnings, never passes or info', () => {
    const shown = report.filter((f) => matchesFilter(f, 'problems'));
    expect(shown).toHaveLength(4);
    expect(shown.every((f) => !f.passed && f.severity !== 'info')).toBe(true);
  });

  it('counts every filter in one pass', () => {
    expect(countFindings(report)).toEqual({
      problems: 4,
      errors: 1,
      warnings: 3,
      info: 1,
      passed: 2,
      all: 7,
    });
  });

  it('groups one rule under one heading, errors first, then the larger group', () => {
    const groups = groupFindings(report, 'problems', { title });
    expect(groups.map((g) => [g.ruleId, g.findings.length])).toEqual([
      ['din276.cost_group_required', 1],
      ['boq_quality.unit_rate_in_range', 2],
      ['project_completeness.planned_dates_set', 1],
    ]);
    expect(groups[1]?.ruleName).toBe('Unusually high unit rate');
  });

  it('puts info after warnings and passes last under all', () => {
    const tones = groupFindings(report, 'all', { title }).map((g) => g.tone);
    expect(tones).toEqual(['error', 'warning', 'warning', 'info', 'passed']);
  });

  it('a rule with a failure and a pass takes the failure as its tone', () => {
    const mixed = groupFindings(report, 'all', { title }).find(
      (g) => g.ruleId === 'boq_quality.unit_rate_in_range',
    );
    expect(mixed?.tone).toBe('warning');
    expect(mixed?.findings).toHaveLength(3);
  });

  it('searches the position ordinal and description, not only the message', () => {
    const positions = new Map([
      ['p2', { ordinal: '01.02.0010', description: 'Concrete C30/37 walls' }],
      ['p3', { ordinal: '01.02.0020', description: 'Formwork' }],
    ]);
    const byOrdinal = groupFindings(report, 'problems', {
      title,
      search: '0020',
      position: (f) => (f.element_ref ? positions.get(f.element_ref) : undefined),
    });
    expect(byOrdinal.flatMap((g) => g.findings.map((f) => f.finding.element_ref))).toEqual(['p3']);
    const byText = groupFindings(report, 'problems', {
      title,
      search: 'concrete',
      position: (f) => (f.element_ref ? positions.get(f.element_ref) : undefined),
    });
    expect(byText.map((g) => g.ruleId).sort()).toEqual([
      'boq_quality.unit_rate_in_range',
      'din276.cost_group_required',
    ]);
  });

  it('lifts a suggestion to the group only when every finding shares it', () => {
    const same = groupFindings(
      [row({ suggestion: 'Check the rate' }), row({ suggestion: 'Check the rate' })],
      'problems',
      { title },
    );
    expect(same[0]?.commonSuggestion).toBe('Check the rate');
    const differ = groupFindings(
      [row({ suggestion: 'Check the rate' }), row({ suggestion: 'Other' })],
      'problems',
      { title },
    );
    expect(differ[0]?.commonSuggestion).toBeNull();
  });
});

describe('resolveScope', () => {
  const positions = new Map([['p1', { ordinal: '01.0010', description: 'Excavation' }]]);
  const boqs = new Map([['boq-1', 'Main bill']]);

  it('names the position, the bill or the project, never the id', () => {
    expect(resolveScope('p1', positions, boqs)).toMatchObject({ kind: 'position', positionId: 'p1' });
    expect(resolveScope('boq-1', positions, boqs)).toMatchObject({ kind: 'boq', name: 'Main bill' });
    expect(resolveScope(null, positions, boqs)).toEqual({ kind: 'project' });
    expect(resolveScope('gone', positions, boqs)).toEqual({ kind: 'missing' });
  });

  it('says loading while positions are not there yet', () => {
    expect(resolveScope('p1', null, boqs)).toEqual({ kind: 'loading' });
  });
});

describe('rule titles', () => {
  const t = (_k: string, o?: Record<string, unknown>) => String(o?.defaultValue ?? '');

  it('maps known rules to a plain title and keeps the engine name for others', () => {
    expect(ruleTitle('project_completeness.bill_base_date_set', 'Every Bill States Its Base Date', t)).toBe(
      'Every BOQ states its base date',
    );
    expect(ruleTitle('pack.custom_rule', 'Custom Pack Rule', t)).toBe('Custom Pack Rule');
  });

  it('turns a bare id into words instead of printing it', () => {
    expect(ruleTitle('pack.missing_unit_price', 'pack.missing_unit_price', t)).toBe('Missing unit price');
    expect(humaniseRuleId('gaeb.lv_structure')).toBe('Lv structure');
  });

  it('covers every rule of the sets the page sends', () => {
    const ids = mappedRuleIds();
    for (const prefix of ['boq_quality.', 'din276.', 'gaeb.', 'nrm.', 'masterformat.', 'project_completeness.']) {
      expect(ids.some((id) => id.startsWith(prefix))).toBe(true);
    }
    expect(ids).toHaveLength(49);
  });

  it('shortens a long description to one line', () => {
    const long = 'Reinforced   concrete\nwall '.repeat(10);
    const short = shortDescription(long, 30);
    expect(short.length).toBeLessThanOrEqual(30);
    expect(short).not.toMatch(/\s{2,}|\n/);
  });
});
