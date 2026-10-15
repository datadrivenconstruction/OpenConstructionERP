// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';

import de from '@/app/locales/de';
import en from '@/app/locales/en';

import { dutyWord, groupByTopic, isOpen, itemTitle, labelOf, progress, readinessDetail } from '../labels';

const EN = (en as { translation: Record<string, string> }).translation;
const DE = (de as { translation: Record<string, string> }).translation;

const DYNAMIC: Record<string, string[]> = {
  'hseFrame.plan': ['not_started', 'draft', 'issued', 'in_force'],
  'hseFrame.later': ['not_started', 'draft', 'complete'],
  'hseFrame.duty': ['yes', 'no', 'unknown'],
  'hseFrame.state': ['draft', 'in_review', 'approved', 'binding', 'revising'],
  'hseFrame.item_status': ['open', 'in_progress', 'met', 'waived', 'not_applicable'],
  'hseFrame.link_kind': [
    'permit_condition',
    'safety_incident',
    'safety_observation',
    'hse_ptw',
    'hse_jsa',
    'hse_audit',
    'hse_capa',
    'quality_inspection',
    'cc_inspection',
  ],
  'hseFrame.role_status': ['proposed', 'appointed', 'ended'],
  'hseFrame.role_required': ['yes', 'no', 'unknown'],
  'hse_frame.evidence': [
    'hse_requirements_issued',
    'environmental_assessment_done',
    'site_clearances_on_file',
    'permit_conditions',
    'energy_and_climate_targets_set',
    'sustainability_targets_set',
    'safety_coordination_appointed',
    'security_concept_approved',
    'unresolved',
  ],
};

describe('hse_frame labels', () => {
  it('prefers the reader language, then English, then the code', () => {
    const entry = { code: 'x', labels: { en: 'Plan', de: 'Plan DE' } };
    expect(labelOf(entry, 'de-AT')).toBe('Plan DE');
    expect(labelOf(entry, 'fr')).toBe('Plan');
    expect(labelOf({ code: 'x', labels: {} }, 'de')).toBe('x');
    expect(labelOf(null, 'de', 'none')).toBe('none');
  });

  it('names a missing role by its label instead of its code', () => {
    const catalogue = { role_kinds: [{ code: 'safety_coordinator_execution', labels: { en: 'Safety coordinator (execution)', de: 'SiGeKo Ausführung' } }] };
    const t = ((key: string, options: { defaultValue: string }) => (key === 'hseFrame.readiness.no_conditions' ? 'none' : options.defaultValue)) as never;
    expect(readinessDetail('safety_coordinator_execution', catalogue as never, 'de', t)).toBe('SiGeKo Ausführung');
    expect(readinessDetail('safety_coordinator_execution,unknown_role', catalogue as never, 'en', t)).toBe('Safety coordinator (execution), unknown_role');
    expect(readinessDetail('no_conditions', catalogue as never, 'de', t)).toBe('none');
    expect(readinessDetail('3/5', catalogue as never, 'de', t)).toBe('3/5');
  });

  it('keeps an undecided duty apart from a duty that does not apply', () => {
    expect(dutyWord(true)).toBe('yes');
    expect(dutyWord(false)).toBe('no');
    expect(dutyWord(null)).toBe('unknown');
  });

  it('lists a topic with no item and appends unknown topics', () => {
    const grouped = groupByTopic([{ topic: 'b' }, { topic: 'z' }], ['a', 'b']);
    expect(grouped.map(([c, rows]) => [c, rows.length])).toEqual([
      ['a', 0],
      ['b', 1],
      ['z', 1],
    ]);
  });

  it('counts only mandatory items towards progress', () => {
    expect(
      progress([
        { obligation: 'mandatory', status: 'met' },
        { obligation: 'mandatory', status: 'open' },
        { obligation: 'recommended', status: 'met' },
      ]),
    ).toEqual({ done: 1, total: 2 });
    expect(isOpen('in_progress')).toBe(true);
    expect(isOpen('waived')).toBe(false);
  });
});

describe('itemTitle', () => {
  const catalogue = { templates: [{ code: 'tpl', labels: { en: 'Advance notice', de: 'Vorankündigung' } }] } as never;
  it('translates a template row and leaves an edited title alone', () => {
    expect(itemTitle({ title: 'Advance notice', template_code: 'tpl' }, catalogue, 'de')).toBe('Vorankündigung');
    expect(itemTitle({ title: 'My own wording', template_code: 'tpl' }, catalogue, 'de')).toBe('My own wording');
    expect(itemTitle({ title: 'Free row', template_code: null }, catalogue, 'de')).toBe('Free row');
  });
});

describe('hse_frame translations', () => {
  it('has an English and a German entry for every dynamic key', () => {
    for (const [prefix, values] of Object.entries(DYNAMIC)) {
      for (const v of values) {
        expect(EN[`${prefix}.${v}`], `en ${prefix}.${v}`).toBeTruthy();
        expect(DE[`${prefix}.${v}`], `de ${prefix}.${v}`).toBeTruthy();
      }
    }
  });

  it('translates every hseFrame key into German', () => {
    const keys = Object.keys(EN).filter((k) => k.startsWith('hseFrame.') || k.startsWith('hse_frame.'));
    expect(keys.length).toBeGreaterThan(100);
    expect(keys.filter((k) => !DE[k])).toEqual([]);
  });
});
