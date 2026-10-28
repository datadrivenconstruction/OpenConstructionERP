// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// crmGuide - "How it works" content for the CRM module.
// Consumed by <ModuleGuideButton content={crmGuide} /> on CRMPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const crmGuide: ModuleGuideContent = {
  titleKey: 'guide.crm.title',
  titleDefault: 'CRM',
  introKey: 'guide.crm.intro',
  introDefault:
    'CRM is your sales pipeline for winning new work. Qualify leads, track deals as they move stage by stage on a Kanban board, log every call and email, and hand a won deal straight to delivery. Use it from first enquiry to signed contract.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.crm.pipeline.title',
      titleDefault: 'The pipeline board',
      bodyKey: 'guide.crm.pipeline.body',
      bodyDefault:
        'The Pipeline tab is a Kanban board where each column is a stage and each card is a deal. Drag a card to another column to move its stage in one click. Every column header shows the deal count and the total value, split per currency so mixed-currency rollups stay honest.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.crm.leads.title',
      titleDefault: 'Leads come first',
      bodyKey: 'guide.crm.leads.body',
      bodyDefault:
        'A lead is an inbound enquiry that is not yet a real opportunity. Open the Leads tab, qualify the promising ones and disqualify the rest, then convert a qualified lead into a deal that lands on the pipeline board ready to work.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.crm.deals.title',
      titleDefault: 'Deals and their numbers',
      bodyKey: 'guide.crm.deals.body',
      bodyDefault:
        'Each deal carries an estimated value, a currency and a probability that comes from its stage. The weighted value is value times probability, so the board shows both the full and the realistic figure. Switch to the Deals tab for a sortable list view of the same opportunities.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.crm.activities.title',
      titleDefault: 'Log every touch',
      bodyKey: 'guide.crm.activities.body',
      bodyDefault:
        'Open a deal and log a quick note, or use the Activities tab to record calls, meetings, emails and tasks against a deal or lead. A clear activity trail is what keeps deals from slipping between the cracks.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.crm.linked.title',
      titleDefault: 'Linked contacts and projects',
      bodyKey: 'guide.crm.linked.body',
      bodyDefault:
        'CRM does not duplicate your address book. A deal links to a person in the Contacts module and to a delivery project in Projects, and the deal drawer resolves and deep-links to both. Attach or change those links right from the drawer.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.crm.close.title',
      titleDefault: 'Close it, then hand it on',
      bodyKey: 'guide.crm.close.body',
      bodyDefault:
        'Open a deal and use Win or Lose to close it, recording a win or loss reason for later analysis. A won deal links on to Bid Management and Contracts, and the Insights tab turns your win and loss history into rates, cycle times and reasons.',
    },
  ],
  ctaKey: 'guide.crm.cta',
  ctaDefault: 'Create your first deal',
};
