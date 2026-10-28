// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// hseAdvancedGuide - "How it works" content for the HSE Advanced module.
// Consumed by <ModuleGuideButton content={hseAdvancedGuide} /> on
// HSEAdvancedPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const hseAdvancedGuide: ModuleGuideContent = {
  titleKey: 'guide.hse_advanced.title',
  titleDefault: 'HSE Advanced',
  introKey: 'guide.hse_advanced.intro',
  introDefault:
    'HSE Advanced is the formal health, safety and environment workspace that carries a finding from "something happened" all the way to "fixed and verified". Use it when a safety issue needs more than a log entry: an investigation, a planned high-risk task, a permit, an audit or a tracked corrective action.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.hse_advanced.overview.title',
      titleDefault: 'KPIs and the seven registers',
      bodyKey: 'guide.hse_advanced.overview.body',
      bodyDefault:
        'A KPI strip across the top gives instant site health: open investigations, overdue CAPAs, active permits and days since the last lost-time incident. Below it, seven tabs hold the registers: Incidents, JSAs, Permits, Toolbox, PPE, Audits and CAPA. Pick a project from the header first, then work the tab you need.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.hse_advanced.investigations.title',
      titleDefault: 'Incident investigations',
      bodyKey: 'guide.hse_advanced.investigations.body',
      bodyDefault:
        'When a safety incident needs root-cause analysis, open an investigation against it and choose a method: 5-Whys, fishbone, timeline or SWOT. Link it to the originating incident from the Safety module, record findings and recommendations, and work it through to completion.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.hse_advanced.jsa.title',
      titleDefault: 'Job Safety Analyses',
      bodyKey: 'guide.hse_advanced.jsa.body',
      bodyDefault:
        'A Job Safety Analysis breaks a high-risk task into steps, names the hazard on each step and lists the controls, with a rolled-up risk score. Create one before the work begins and drive it through real approval states, from draft through review and approval to active, so nothing goes live without the right sign-off.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.hse_advanced.permits.title',
      titleDefault: 'Permits to work',
      bodyKey: 'guide.hse_advanced.permits.body',
      bodyDefault:
        'Raise a permit to work for hot work, confined space and similar high-risk activities, with its prerequisites and work window. Each permit follows a controlled lifecycle: requested, approved, active, suspended and closed or cancelled, with expiry tracked, so the right state always reflects what is happening on site.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.hse_advanced.frontline.title',
      titleDefault: 'Toolbox talks, PPE and audits',
      bodyKey: 'guide.hse_advanced.frontline.body',
      bodyDefault:
        'Record the day-to-day safety paper trail: toolbox talks delivered to the crew, PPE issued to workers, and site safety audits that generate findings by category and severity. Each audit finding can become a corrective action so nothing spotted on a walk is left to drift.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.hse_advanced.capa.title',
      titleDefault: 'CAPAs and OSHA 300 export',
      bodyKey: 'guide.hse_advanced.capa.body',
      bodyDefault:
        'The CAPA register tracks every corrective and preventive action to close-out, links each one back to its source incident, audit, JSA or permit, captures 5-Whys, and flags anything overdue. Use the OSHA 300 export at the top to download the incident log as CSV for the required retention period.',
    },
  ],
  ctaKey: 'guide.hse_advanced.cta',
  ctaDefault: 'Open your first register',
};
