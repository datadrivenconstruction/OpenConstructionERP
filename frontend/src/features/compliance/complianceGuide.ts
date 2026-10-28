// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// complianceGuide - "How it works" content for the Compliance Rule Builder.
// Consumed by <ModuleGuideButton content={complianceGuide} /> on the
// NlRuleBuilderPanel page.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.
//
// Spotlight selectors reuse the panel's stable data-testid hooks so each
// highlight survives styling churn and button reorders.

import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

export const complianceGuide: ModuleGuideContent = {
  titleKey: 'guide.compliance.title',
  titleDefault: 'Compliance Rule Builder',
  introKey: 'guide.compliance.intro',
  introDefault:
    'This builder turns a plain sentence into a validation rule. You describe what the data must satisfy, it generates the rule as readable DSL, and once you save it the rule runs alongside your other checks under Validation and Governance.',
  sections: [
    {
      icon: 'PencilLine',
      titleKey: 'guide.compliance.describe.title',
      titleDefault: 'Describe the rule in words',
      bodyKey: 'guide.compliance.describe.body',
      bodyDefault:
        'Pick the input language - English, German or Russian - and type the rule as one plain sentence, such as "all walls must have fire_rating" or "every position must have quantity greater than 0". One condition per sentence parses most reliably.',
      spotlightSelector: '[data-testid="nl-input"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.compliance.generate.title',
      titleDefault: 'Generate the rule',
      bodyKey: 'guide.compliance.generate.body',
      bodyDefault:
        'Press Generate, or Ctrl/Cmd+Enter, to convert your sentence into rule DSL. A deterministic pattern matcher does this on its own. AI fallback is an opt-in checkbox for wording the patterns miss, and it is quietly skipped when no API key is configured, so the builder never blocks.',
      spotlightSelector: '[data-testid="nl-generate"]',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.compliance.review.title',
      titleDefault: 'Review the generated DSL',
      bodyKey: 'guide.compliance.review.body',
      bodyDefault:
        'The preview pane shows the rule as readable YAML. Check the method and confidence badges and the matched pattern name. A low-confidence result is flagged with a warning so you read it carefully, and any parse errors or suggestions appear beneath the input.',
      spotlightSelector: '[data-testid="dsl-preview"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.compliance.patterns.title',
      titleDefault: 'Lean on the supported patterns',
      bodyKey: 'guide.compliance.patterns.body',
      bodyDefault:
        'The list on the right shows every form the builder understands - must have, must not have, value comparisons and count checks. Click any example to drop it straight into the box, then edit the property and value to fit your project.',
      spotlightSelector: '[data-testid="nl-pattern-hints"]',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.compliance.save.title',
      titleDefault: 'Save it as a compliance rule',
      bodyKey: 'guide.compliance.save.body',
      bodyDefault:
        'When the DSL looks right, Save as Compliance Rule compiles and stores it as an active rule. From there it runs with your other validation checks, so the same rule is applied every time you validate a BOQ or imported data.',
      spotlightSelector: '[data-testid="nl-save"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.compliance.where.title',
      titleDefault: 'Where the rule runs',
      bodyKey: 'guide.compliance.where.body',
      bodyDefault:
        'Saved rules are not one-off checks. They join the rule sets that the Validation dashboard runs over an estimate and that Governance manages across the project, so a rule you write here keeps working long after you leave this screen.',
    },
  ],
  ctaKey: 'guide.compliance.cta',
  ctaDefault: 'Write your first rule',
};
