// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - Compliance Rule Builder.
// See ../../types.ts for the ModuleExplanation shape + key convention, and
// ../overview-estimating.ts for a fully-worked example. This file is picked
// up automatically by the catalog/modules/*.ts glob in moduleExplanations.ts,
// so no edit to that aggregator is needed.

import type { ModuleExplanation } from '../../types';

export const complianceModules: ModuleExplanation[] = [
  {
    id: 'compliance-builder',
    route: '/compliance/builder',
    // No `spotlightRoute`. The builder has its own sidebar row now (Quality
    // group, beside Validation), so the spotlight lands on the screen the
    // "Open module" button opens. It used to point at `/validation` because
    // the sub-route had no row of its own, which sent the tour to a neighbour.
    icon: 'Wand2',
    category: 'quality',
    keywords:
      'compliance rule builder natural language plain language dsl yaml validation governance author check pattern',
    titleKey: 'howto.compliance-builder.title',
    titleDefault: 'Compliance Rule Builder',
    summaryKey: 'howto.compliance-builder.summary',
    summaryDefault:
      'Describe a check in plain language and turn it into a validation rule you can review and save.',
    whatKey: 'howto.compliance-builder.what',
    whatDefault:
      'The Compliance Rule Builder lets you write a validation rule in plain English, German or Russian instead of code. You type what the data must satisfy, the builder matches it to a known rule pattern and generates the rule as readable DSL, and once you save it the rule joins the rule sets that run under Validation and Governance against your BOQ and imported data.',
    how: [
      {
        key: 'howto.compliance-builder.how.1',
        default:
          'Pick the input language, then describe the rule in the text box, for example "all walls must have fire_rating".',
      },
      {
        key: 'howto.compliance-builder.how.2',
        default:
          'Press Generate (or Ctrl/Cmd+Enter) to convert the sentence into rule DSL; the pattern matcher does this on its own, and AI fallback is an opt-in checkbox that is skipped when no API key is set.',
      },
      {
        key: 'howto.compliance-builder.how.3',
        default:
          'Read the generated DSL in the preview pane and check the confidence badge and matched pattern; a low-confidence result is flagged so you review it before trusting it.',
      },
      {
        key: 'howto.compliance-builder.how.4',
        default:
          'Use the supported-patterns list on the right to see the forms the builder understands, and click an example to drop it straight into the box.',
      },
      {
        key: 'howto.compliance-builder.how.5',
        default:
          'Save as Compliance Rule to compile and store it as an active rule, ready to run with your other validation checks.',
      },
    ],
    tips: [
      {
        key: 'howto.compliance-builder.tip.1',
        default:
          'Keep each sentence to one condition; complex rules read better and parse more reliably when split into several simple rules.',
      },
      {
        key: 'howto.compliance-builder.tip.2',
        default:
          'If nothing matches, the builder suggests close patterns - rephrase to one of those forms rather than fighting the wording.',
      },
    ],
    whenKey: 'howto.compliance-builder.when',
    whenDefault:
      'Reach for it when you need a project or client-specific check that the built-in standards do not already cover.',
  },
];
