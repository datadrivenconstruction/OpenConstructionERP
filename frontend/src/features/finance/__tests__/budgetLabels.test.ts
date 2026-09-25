// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import type { TFunction } from 'i18next';
import { budgetCategoryLabel, wbsLabel, type WbsNode } from '../budgetLabels';

const t = ((key: string, opts?: { defaultValue?: string }) => `${key}|${opts?.defaultValue ?? ''}`) as unknown as TFunction;

describe('wbsLabel', () => {
  const id = '3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d';
  const nodes = new Map<string, WbsNode>([[id, { id, code: '02.100', name: 'Earthworks' }]]);

  it('names a project WBS node by code and name, keeping the id as a tooltip', () => {
    expect(wbsLabel(id, nodes)).toEqual({ text: '02.100 Earthworks', title: id });
  });

  it('shortens an id nothing can name instead of printing 36 characters', () => {
    const other = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
    expect(wbsLabel(other, nodes)).toEqual({ text: 'aaaaaaaa…', title: other });
  });

  it("prefers the server's name, which also covers bill sections", () => {
    const sectionId = '5b0c7f7e-1d2a-4f67-9d1e-3a2b1c0d9e8f';
    expect(wbsLabel(sectionId, nodes, '02 Concrete works')).toEqual({ text: '02 Concrete works', title: sectionId });
  });

  it('shows a typed code as it is, and nothing for no WBS', () => {
    expect(wbsLabel('300.10', nodes)).toEqual({ text: '300.10' });
    expect(wbsLabel(null, nodes)).toEqual({ text: '' });
  });
});

describe('budgetCategoryLabel', () => {
  it('maps both spellings of the vocabulary to one translated label', () => {
    expect(budgetCategoryLabel(t, 'Material')).toBe('finance.cat_material|Material');
    expect(budgetCategoryLabel(t, 'material')).toBe('finance.cat_material|Material');
    expect(budgetCategoryLabel(t, 'subcontractor')).toBe('finance.cat_subcontract|Subcontract');
    expect(budgetCategoryLabel(t, 'contingency')).toBe('finance.cat_contingency|Contingency');
    expect(budgetCategoryLabel(t, 'estimate')).toBe('finance.cat_estimate|Bill of quantities');
    expect(budgetCategoryLabel(t, '')).toBe('finance.cat_other|Other');
  });

  it('shows a value outside the vocabulary as stored, not as "Other"', () => {
    expect(budgetCategoryLabel(t, 'Formwork')).toBe('Formwork');
  });
});
