// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// safetyGuide - "How it works" content for the Safety module.
// Consumed by <ModuleGuideButton content={safetyGuide} /> on SafetyPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const safetyGuide: ModuleGuideContent = {
  titleKey: 'guide.safety.title',
  titleDefault: 'Safety',
  introKey: 'guide.safety.intro',
  introDefault:
    'Safety is where you report what already went wrong and record the hazards you spot before anyone gets hurt. Use it to keep a compliant record of incidents and observations, and to watch site safety trends across the project.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.safety.overview.title',
      titleDefault: 'The safety dashboard',
      bodyKey: 'guide.safety.overview.body',
      bodyDefault:
        'The tiles at the top roll up open incidents, pending inspections, open NCRs and open defects for the project. Each tile is a shortcut: click it to jump straight into that filtered register, or into the incidents list below.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.safety.incidents.title',
      titleDefault: 'Report incidents',
      bodyKey: 'guide.safety.incidents.body',
      bodyDefault:
        'An incident is something that already happened: an injury, near-miss, property damage, environmental spill or fire. Report Incident captures the date, type, description, severity and treatment, and records the working days lost so the record stands up for compliance reporting.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.safety.observations.title',
      titleDefault: 'Record observations',
      bodyKey: 'guide.safety.observations.body',
      bodyDefault:
        'Observations are hazards you catch before harm, plus positive practices worth reinforcing. Pick the type, then rate severity and likelihood on a 1 to 5 scale; the module multiplies them into a risk score so the most dangerous conditions stand out.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.safety.escalate.title',
      titleDefault: 'Investigate and escalate',
      bodyKey: 'guide.safety.escalate.body',
      bodyDefault:
        'A serious incident does not stop here. Investigate opens a formal HSE Advanced investigation for root-cause analysis, while a high-risk observation prompts you to schedule an inspection. The links keep safety connected to inspections, NCRs and the punch list.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.safety.trends.title',
      titleDefault: 'Trends and thresholds',
      bodyKey: 'guide.safety.trends.body',
      bodyDefault:
        'The Trends tab charts incidents and observations over time and checks them against your safety thresholds. Use it to spot a rising pattern early and to confirm the days-without-incident metric is holding.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.safety.export.title',
      titleDefault: 'Export the record',
      bodyKey: 'guide.safety.export.body',
      bodyDefault:
        'Both the incidents and observations lists export to Excel in one click, so you can hand a complete, auditable safety log to a client, an authority or your HSE team whenever it is needed.',
    },
  ],
  ctaKey: 'guide.safety.cta',
  ctaDefault: 'Report your first incident',
};
