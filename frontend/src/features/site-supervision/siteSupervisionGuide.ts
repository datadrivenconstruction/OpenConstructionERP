// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// siteSupervisionGuide - "How it works" content for the Site Supervision
// module. Consumed by <ModuleGuideButton content={siteSupervisionGuide} />
// on SiteSupervisionPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const siteSupervisionGuide: ModuleGuideContent = {
  titleKey: 'guide.site_supervision.title',
  titleDefault: 'Site Supervision',
  introKey: 'guide.site_supervision.intro',
  introDefault:
    'Plan and record the design team’s visits to site, log what was observed, and keep every hidden-works acceptance and instruction traceable back to the visit that raised it.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.site_supervision.visits.title',
      titleDefault: 'Plan and conduct visits',
      bodyKey: 'guide.site_supervision.visits.body',
      bodyDefault:
        'Create a visit with a planned date, a discipline (architecture, structure, MEP, geotech) and a visitor. A visit moves through planned → conducted → reported: mark it conducted once you have actually been on site, then reported once the write-up is finished.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.site_supervision.entries.title',
      titleDefault: 'Log observations',
      bodyKey: 'guide.site_supervision.entries.body',
      bodyDefault:
        'Each visit holds a log of entries: conformance notes, deviations from the design, hidden-works acceptance items, instructions issued to the contractor, and motivated refusals. Refusing an entry requires a written reason, so the record always explains why.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.site_supervision.hidden.title',
      titleDefault: 'Hidden works before cover-up',
      bodyKey: 'guide.site_supervision.hidden.body',
      bodyDefault:
        'Work that will be covered (reinforcement, buried services, waterproofing) belongs in the hidden-works register. Use it to confirm the item was inspected and accepted before it disappears behind the next layer of work.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.site_supervision.change.title',
      titleDefault: 'Plan vs fact and change links',
      bodyKey: 'guide.site_supervision.change.body',
      bodyDefault:
        'The Plan vs Fact panel shows how many visits were planned, conducted and reported, and flags overdue ones. Instructions and deviations that reference a change can be tracked through to the project’s change route from the Change Links panel.',
    },
  ],
};
