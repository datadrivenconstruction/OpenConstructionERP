// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';
import {
  buildLinkFromModelUrl,
  buildQuantityRulesUrl,
  elementTypeToPattern,
  readLinkFromModelTarget,
  readQuantityRulesContext,
  rulesTabFromParams,
  suggestQuantitySource,
} from './quantityRuleLinks';
import { fnmatchCI, ruleMatchesElement } from './ruleSandbox';

const query = (url: string) => new URLSearchParams(url.split('?')[1] ?? '');

describe('buildQuantityRulesUrl / readQuantityRulesContext', () => {
  it('lands on the quantity rules tab, never on the requirements mode', () => {
    expect(buildQuantityRulesUrl()).toBe('/bim/rules');
    const url = buildQuantityRulesUrl({ projectId: 'p1', modelId: 'm1' });
    expect(url.startsWith('/bim/rules?')).toBe(true);
    expect(query(url).get('mode')).toBeNull();
  });

  it('round-trips project, model, BOQ and a new rule', () => {
    const url = buildQuantityRulesUrl({
      projectId: 'p1',
      modelId: 'm1',
      boqId: 'b1',
      newRule: { elementType: 'Walls', propKey: 'Phase Created', propValue: 'New Construction', quantitySource: 'Area', unit: 'm²' },
    });
    expect(readQuantityRulesContext(query(url))).toEqual({
      projectId: 'p1',
      modelId: 'm1',
      boqId: 'b1',
      newRule: { elementType: 'Walls', propKey: 'Phase Created', propValue: 'New Construction', quantitySource: 'Area', unit: 'm²' },
    });
  });

  it('opens no editor without new=1', () => {
    const ctx = readQuantityRulesContext(query(buildQuantityRulesUrl({ projectId: 'p1', boqId: 'b1' })));
    expect(ctx.newRule).toBeNull();
    expect(ctx.boqId).toBe('b1');
  });
});

describe('elementTypeToPattern', () => {
  it('keeps a plain type name exact', () => {
    expect(elementTypeToPattern('  Walls ')).toBe('Walls');
  });

  it('selects a bracketed Revit type name the same way in the browser test and on the server', () => {
    const name = 'Basic Wall [300mm], Ext*';
    const pattern = elementTypeToPattern(name);
    expect(pattern).toBe('Basic Wall ?300mm?? Ext?');
    // Browser test: splits on commas, matches literally otherwise.
    expect(fnmatchCI(name, pattern)).toBe(true);
    expect(
      ruleMatchesElement(
        { element_type_filter: pattern, property_filter: {}, quantity_source: 'count', multiplier: '1', waste_factor_pct: '0', unit: 'pcs' },
        { id: 'e', element_type: name },
      ),
    ).toBe(true);
    // Server dialect: no character class and no comma left in the pattern.
    expect(/[[\],*]/.test(pattern)).toBe(false);
  });

  it('cuts an over-long name to the column width and matches it by prefix', () => {
    const pattern = elementTypeToPattern('W'.repeat(140));
    expect(pattern).toHaveLength(100);
    expect(pattern.endsWith('*')).toBe(true);
  });
});

describe('suggestQuantitySource', () => {
  it('prefers area, spelled as the element spells it', () => {
    expect(suggestQuantitySource({ Volume: 3, Area: 12.5 })).toEqual({ quantitySource: 'Area', unit: 'm²' });
    expect(suggestQuantitySource({ area_m2: 4 })).toEqual({ quantitySource: 'area_m2', unit: 'm²' });
  });

  it('falls through zero or missing values to the next quantity, then to a count', () => {
    expect(suggestQuantitySource({ Area: 0, Length: 7 })).toEqual({ quantitySource: 'Length', unit: 'm' });
    expect(suggestQuantitySource({})).toEqual({ quantitySource: 'count', unit: 'pcs' });
    expect(suggestQuantitySource(null)).toEqual({ quantitySource: 'count', unit: 'pcs' });
  });
});

describe('buildLinkFromModelUrl / readLinkFromModelTarget', () => {
  it('puts the model in the path and round-trips the position', () => {
    const url = buildLinkFromModelUrl({ projectId: 'p1', modelId: 'm1', boqId: 'b1', positionId: 'pos1', label: '01.010 Walls' });
    expect(url.startsWith('/projects/p1/bim/m1?')).toBe(true);
    expect(readLinkFromModelTarget(query(url))).toEqual({ positionId: 'pos1', boqId: 'b1', label: '01.010 Walls' });
  });

  it('returns null when the URL carries no target', () => {
    expect(readLinkFromModelTarget(new URLSearchParams('element=x'))).toBeNull();
  });
});

describe('rulesTabFromParams', () => {
  const ALL = { requirements: true, ruleLibrary: true };
  const tab = (qs: string, available = ALL) => rulesTabFromParams(new URLSearchParams(qs), available);

  it('opens the quantity rules unless the URL asks for the other half', () => {
    expect(tab('')).toBe('quantity_rules');
    expect(tab('tab=nonsense')).toBe('quantity_rules');
    expect(tab('tab=requirements')).toBe('requirements');
    expect(tab('tab=rule_library')).toBe('rule_library');
  });

  it('keeps the compliance mode on its own tabs', () => {
    expect(tab('mode=requirements')).toBe('requirements');
    expect(tab('mode=requirements&tab=rule_library')).toBe('rule_library');
    expect(tab('mode=requirements&tab=quantity_rules')).toBe('requirements');
  });

  // Requirements are oe_requirements data, the Rule Library installs through
  // oe_bim_requirements: a tab whose module is off is never the answer.
  it('never answers with a tab whose module is off', () => {
    const noReqs = { requirements: false, ruleLibrary: true };
    expect(tab('tab=requirements', noReqs)).toBe('quantity_rules');
    expect(tab('mode=requirements', noReqs)).toBe('rule_library');
    expect(tab('tab=rule_library', noReqs)).toBe('rule_library');

    const noLibrary = { requirements: true, ruleLibrary: false };
    expect(tab('tab=rule_library', noLibrary)).toBe('quantity_rules');
    expect(tab('mode=requirements&tab=rule_library', noLibrary)).toBe('requirements');
    expect(tab('tab=requirements', noLibrary)).toBe('requirements');

    const none = { requirements: false, ruleLibrary: false };
    expect(tab('mode=requirements', none)).toBe('quantity_rules');
    expect(tab('tab=rule_library', none)).toBe('quantity_rules');
    expect(tab('tab=requirements', none)).toBe('quantity_rules');
  });
});
