// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// carbonGuide - "How it works" content for the Carbon & ESG module.
// Consumed by <ModuleGuideButton content={carbonGuide} /> on CarbonPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const carbonGuide: ModuleGuideContent = {
  titleKey: 'guide.carbon.title',
  titleDefault: 'Carbon & ESG',
  introKey: 'guide.carbon.intro',
  introDefault:
    'Carbon & ESG measures the full footprint of a project: embodied carbon from the materials you build with plus Scope 1, 2 and 3 operational emissions. Use it to track reduction targets and package the numbers as GHG Protocol, GRI or ISSB reports.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.carbon.inventory.title',
      titleDefault: 'Build an inventory',
      bodyKey: 'guide.carbon.inventory.body',
      bodyDefault:
        'An inventory is one footprint snapshot for the project, scoped as cradle-to-gate, cradle-to-grave or operational. Create one, mark it as baseline or current, then open it to add the entries that roll up into its total. Everything else hangs off the inventory.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.carbon.embodied.title',
      titleDefault: 'Embodied carbon from your BOQ',
      bodyKey: 'guide.carbon.embodied.body',
      bodyDefault:
        'Embodied entries multiply a Bill of Quantities position by a material carbon factor to get kg CO2e across lifecycle stages A1 to D. Use Add from BOQ to pull a priced position and pick its factor, or add an entry by hand. The Top emitters list ranks the heaviest items.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.carbon.scopes.title',
      titleDefault: 'Scope 1, 2 and 3',
      bodyKey: 'guide.carbon.scopes.body',
      bodyDefault:
        'Operational emissions split into three scopes: Scope 1 is direct fuel burned on site, Scope 2 is purchased energy such as grid electricity, and Scope 3 is the wider value chain. Add entries with their activity data and emission factors, and the drawer shows the breakdown bar and per-scope totals.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.carbon.epds.title',
      titleDefault: 'EPDs and material factors',
      bodyKey: 'guide.carbon.epds.body',
      bodyDefault:
        'The EPDs tab is your library of Environmental Product Declarations sourced from Okobaudat, ICE, EC3 and custom uploads, each carrying a GWP value per declared unit. Filter by material class or region to find the right factor, and these EPDs feed the embodied calculations.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.carbon.targets.title',
      titleDefault: 'Set reduction targets',
      bodyKey: 'guide.carbon.targets.body',
      bodyDefault:
        'Define a target as an absolute number or an intensity per square metre, with a baseline year and a target year. Each target tracks live progress against the current inventory and flags when it is met, so you can prove your reduction trajectory.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.carbon.reports.title',
      titleDefault: 'Generate GHG reports',
      bodyKey: 'guide.carbon.reports.body',
      bodyDefault:
        'When the numbers are ready, generate a report for a reporting period in the GHG Protocol, GRI or ISSB framework. It pulls the project inventory totals into a shareable record you can keep for disclosure and audit.',
    },
  ],
  ctaKey: 'guide.carbon.cta',
  ctaDefault: 'Create your first inventory',
};
