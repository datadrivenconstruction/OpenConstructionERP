// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The quantity-rule sandbox selects what the server apply selects.
 *
 * Runs the shared case table (fixtures/ruleMatchingParity.json) through
 * ruleMatchesElement. The backend twin, tests/unit/test_rule_matching_parity.py,
 * runs the same table through BIMHubService._rule_matches_element, so a case
 * added to the table is pinned on both engines at once.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  extractRawQuantity,
  ruleMatchesElement,
  type SandboxElement,
  type SandboxRule,
} from '../ruleSandbox';

interface ParityCase {
  name: string;
  rule: Pick<SandboxRule, 'element_type_filter' | 'property_filter'>;
  expected: string[];
}

interface QuantityCase {
  name: string;
  source: string;
  element: Pick<SandboxElement, 'properties' | 'quantities'>;
  expected: number | null;
}

interface SingleCase {
  name: string;
  element: Pick<SandboxElement, 'element_type' | 'properties'>;
  rule: ParityCase['rule'];
  expected: boolean;
}

const table = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'ruleMatchingParity.json'), 'utf8')) as {
  elements: SandboxElement[];
  cases: ParityCase[];
  single_cases: SingleCase[];
  quantity_cases: QuantityCase[];
};

const draft = (rule: ParityCase['rule']): SandboxRule => ({
  ...rule,
  quantity_source: 'count',
  multiplier: '1',
  waste_factor_pct: '0',
  unit: 'pcs',
});

describe('rule matching parity with the server', () => {
  it('has cases to run', () => {
    expect(table.cases.length).toBeGreaterThanOrEqual(10);
  });

  for (const c of table.cases) {
    it(c.name, () => {
      const selected = table.elements.filter((el) => ruleMatchesElement(draft(c.rule), el)).map((el) => el.id);
      expect(selected).toEqual(c.expected);
    });
  }

  for (const c of table.single_cases) {
    it(c.name, () => {
      const element = { id: c.name, ...c.element } as SandboxElement;
      expect(ruleMatchesElement(draft(c.rule), element)).toBe(c.expected);
    });
  }
});

describe('quantity extraction parity with the server', () => {
  it('has cases to run', () => {
    expect(table.quantity_cases.length).toBeGreaterThanOrEqual(10);
  });

  for (const c of table.quantity_cases) {
    it(c.name, () => {
      const element = { id: c.name, element_type: '', ...c.element } as SandboxElement;
      const qty = extractRawQuantity(element, c.source);
      if (c.expected === null) expect(qty).toBeNull();
      else expect(qty).toBeCloseTo(c.expected, 9);
    });
  }
});
