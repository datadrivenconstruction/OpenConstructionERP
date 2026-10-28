// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// projectRouteGuide - "How it works" content for the Work-type Route
// Classifier module. Consumed by <ModuleGuideButton content={projectRouteGuide} />
// on ProjectRoutePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const projectRouteGuide: ModuleGuideContent = {
  titleKey: 'guide.project_route.title',
  titleDefault: 'Work-type Route Classifier',
  introKey: 'guide.project_route.intro',
  introDefault:
    'Given the type of work a project is doing, the classifier suggests which delivery, permitting or approval route it needs, so the team can confirm the right process before design and procurement get underway.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.project_route.what.title',
      titleDefault: 'What this classifier is for',
      bodyKey: 'guide.project_route.what.body',
      bodyDefault:
        'Every jurisdiction sorts construction work into different delivery and approval routes. This tool asks a few generic questions about the work and proposes a route with a confidence score and a plain-language rationale - a starting point for a human decision, not an automatic ruling.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.project_route.classify.title',
      titleDefault: 'Run a classification',
      bodyKey: 'guide.project_route.classify.body',
      bodyDefault:
        'Pick the work type - new build, reconstruction, capital repair, re-equipment, maintenance, demolition or change of use - and answer the criteria toggles. The classifier returns a suggested route instantly, without saving anything.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.project_route.save.title',
      titleDefault: 'Save it as an assessment',
      bodyKey: 'guide.project_route.save.body',
      bodyDefault:
        'Save a classification against the project to keep a record. Editing the work type or criteria later re-runs the classifier automatically and returns the assessment to draft.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.project_route.confirm.title',
      titleDefault: 'Confirm the route',
      bodyKey: 'guide.project_route.confirm.body',
      bodyDefault:
        'AI proposes, a person confirms. Confirming locks in the route the project proceeds under and records who confirmed it and when - the gate before the team commits to that path.',
    },
  ],
  ctaKey: 'guide.project_route.cta',
  ctaDefault: 'Classify your first work type',
};
