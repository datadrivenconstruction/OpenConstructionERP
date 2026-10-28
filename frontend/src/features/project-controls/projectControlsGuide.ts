// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// projectControlsGuide - "How it works" content for the Project Controls
// module. Consumed by <ModuleGuideButton content={projectControlsGuide} />
// on ProjectControlsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const projectControlsGuide: ModuleGuideContent = {
  titleKey: 'guide.project_controls.title',
  titleDefault: 'Project Controls',
  introKey: 'guide.project_controls.intro',
  introDefault:
    'Project Controls is the executive cockpit that pulls cost, schedule, quality, safety, risk and change KPIs onto one screen. Use it to spot a project slipping early and to trace any number straight back to the records behind it.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.project_controls.domains.title',
      titleDefault: 'Six domains, one screen',
      bodyKey: 'guide.project_controls.domains.body',
      bodyDefault:
        'The dashboard groups every metric into six domains: Cost, Schedule, Quality, Safety, Risk and Changes. Each domain is its own card so you read the health of the whole project at a glance without opening six different modules.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.project_controls.tiles.title',
      titleDefault: 'Status-banded KPI tiles',
      bodyKey: 'guide.project_controls.tiles.body',
      bodyDefault:
        'Every KPI is a tile that is banded green, amber or red against its target, so on-track and off-track numbers separate themselves. The chips above the cards summarise how many domains and KPIs are tracked and how many are on track or critical right now.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.project_controls.scope.title',
      titleDefault: 'Project or portfolio scope',
      bodyKey: 'guide.project_controls.scope.body',
      bodyDefault:
        'The view follows the project picker in the top bar. Pick a project to scope every figure to it, or clear the selection to roll the numbers up across the whole portfolio. The scope chip in the header always shows which you are looking at.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.project_controls.drill.title',
      titleDefault: 'Drill back to the source',
      bodyKey: 'guide.project_controls.drill.body',
      bodyDefault:
        'No number is a dead end. Click any tile to open the drill drawer and trace the figure back to the module that owns it, such as Finance, Risks or Change Orders, with the underlying records that make it up.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.project_controls.alerts.title',
      titleDefault: 'Alerts that need attention',
      bodyKey: 'guide.project_controls.alerts.body',
      bodyDefault:
        'When KPIs breach their thresholds a banner lists them, with critical breaches flagged ahead of warnings. It tells you exactly which numbers need attention so you act on the worst problems first.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.project_controls.refresh.title',
      titleDefault: 'Live and consolidated',
      bodyKey: 'guide.project_controls.refresh.body',
      bodyDefault:
        'Every tile is built from a single consolidated snapshot, so the domains stay consistent with each other. Hit Refresh in the header to pull the latest figures whenever the underlying modules have moved on.',
    },
  ],
  ctaKey: 'guide.project_controls.cta',
  ctaDefault: 'Open a tile to trace a number',
};
