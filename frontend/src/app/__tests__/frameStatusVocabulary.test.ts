// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every frame document says the same thing in the same word. The stored codes
// differ from module to module (`revising`, `reopened`, `proposed`,
// `approved_at_gate`) and stay as they are, so installed projects keep working;
// what a reader sees is one vocabulary, in the two languages the screens ship
// with first.

import { describe, expect, it } from 'vitest';

import de from '@/app/locales/de';
import en from '@/app/locales/en';

type Step = 'draft' | 'in_review' | 'approved' | 'binding' | 'reopened';

const WORDS: Record<'en' | 'de', Record<Step, string>> = {
  en: { draft: 'Draft', in_review: 'In review', approved: 'Approved', binding: 'Binding', reopened: 'Reopened' },
  de: { draft: 'Entwurf', in_review: 'In Prüfung', approved: 'Freigegeben', binding: 'Verbindlich', reopened: 'Wieder geöffnet' },
};

/** The label key each module shows for each step; the module's own code is the last segment. */
const KEYS: Record<string, Partial<Record<Step, string>>> = {
  staffing: {
    draft: 'staffing.plan.status.draft',
    in_review: 'staffing.plan.status.in_review',
    approved: 'staffing.plan.status.approved',
    binding: 'staffing.plan.status.binding',
    reopened: 'staffing.plan.status.revising',
  },
  quality_concept: {
    draft: 'qualityConcept.conceptState.draft',
    in_review: 'qualityConcept.conceptState.in_review',
    approved: 'qualityConcept.conceptState.approved',
    binding: 'qualityConcept.conceptState.binding',
    reopened: 'qualityConcept.conceptState.revising',
  },
  procurement_concept: {
    draft: 'procurement_concept.concept_state.draft',
    in_review: 'procurement_concept.concept_state.in_review',
    approved: 'procurement_concept.concept_state.approved',
    binding: 'procurement_concept.concept_state.binding',
    reopened: 'procurement_concept.concept_state.reopened',
  },
  delivery_model: {
    draft: 'delivery_model.ui.model_status.draft',
    in_review: 'delivery_model.ui.model_status.proposed',
    approved: 'delivery_model.ui.model_status.approved',
    binding: 'delivery_model.ui.model_status.binding',
    reopened: 'delivery_model.ui.model_status.reopened',
  },
  project_governance: {
    draft: 'governance.project.document_status.draft',
    in_review: 'governance.project.document_status.in_review',
    approved: 'governance.project.document_status.approved_at_gate',
    binding: 'governance.project.document_status.binding',
  },
};

describe('frame document status vocabulary', () => {
  for (const [lang, table] of [
    ['en', en.translation],
    ['de', de.translation],
  ] as const) {
    for (const [module, steps] of Object.entries(KEYS)) {
      it(`${module} words every step the same way in ${lang}`, () => {
        for (const [step, key] of Object.entries(steps) as [Step, string][]) {
          expect(table[key], `${key} in ${lang}`).toBe(WORDS[lang][step]);
        }
      });
    }
  }
});
