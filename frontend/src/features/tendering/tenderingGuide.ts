// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// tenderingGuide - "How it works" content for the Tendering module.
// Consumed by <ModuleGuideButton content={tenderingGuide} /> on TenderingPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const tenderingGuide: ModuleGuideContent = {
  titleKey: 'guide.tendering.title',
  titleDefault: 'Tendering',
  introKey: 'guide.tendering.intro',
  introDefault:
    'Tendering takes a priced project BOQ to market and back. Build bid packages, issue them to subcontractors, compare the offers side by side, and award a winner that writes the agreed rates back to the BOQ.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.tendering.packages.title',
      titleDefault: 'Build a package from a BOQ',
      bodyKey: 'guide.tendering.packages.body',
      bodyDefault:
        'A tender package is a scope of work you put out to bid, created straight from a project Bill of Quantities. Click New Tender Package, give it a name, pick the source BOQ and an optional deadline. Each package shows its bid count and status, and opens to a detail view when you select it.',
      spotlightSelector: '[data-guide="tendering-new"]',
    },
    {
      icon: 'Send',
      titleKey: 'guide.tendering.lifecycle.title',
      titleDefault: 'Move it through the lifecycle',
      bodyKey: 'guide.tendering.lifecycle.body',
      bodyDefault:
        'A package runs through Draft, Issued, Collecting, Evaluating and Awarded. The primary button changes with the stage: Issue, then Start Collecting, then Evaluate Bids, then Mark Awarded. Export the source BOQ as GAEB X83 or a tender summary PDF to send the scope to bidders.',
      spotlightSelector: '[data-guide="tendering-packages"]',
      spotlightPosition: 'top',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.tendering.bids.title',
      titleDefault: 'Collect bids',
      bodyKey: 'guide.tendering.bids.body',
      bodyDefault:
        'Use Add Bid to record an offer with the company, contact email and total amount. Select from Subcontractors pulls a bidder straight from the directory and shows its prequalification status so you compare like for like. Every bid received is listed under the package with its amount and status.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.tendering.compare.title',
      titleDefault: 'Compare and level offers',
      bodyKey: 'guide.tendering.compare.body',
      bodyDefault:
        'The Bids and Comparison tab charts each total against the budget and breaks the offers down line by line, with the deviation from your budget rate shown per bidder. Switch to Leveling for a like-for-like matrix and to Addenda to track scope changes issued during the tender. Export the comparison to CSV at any time.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.tendering.recommendation.title',
      titleDefault: 'Read the award recommendation',
      bodyKey: 'guide.tendering.recommendation.body',
      bodyDefault:
        'Once bids are in, the recommendation ranks them by total and tags a confidence level. A clear lowest offer reads high confidence, a narrow gap to the runner-up reads medium, and a bid well below the median is flagged low so you verify scope and pricing before awarding rather than rubber-stamping it.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.tendering.award.title',
      titleDefault: 'Award and hand off',
      bodyKey: 'guide.tendering.award.body',
      bodyDefault:
        'Awarding a bid writes the winning rates back to the BOQ, rejects the other offers and drafts a purchase order in Procurement. From an awarded package you can then formalise the scope as a Contract. This downstream hand-off is what sets Tendering apart from the subcontractor flow in Bid Management.',
    },
  ],
  ctaKey: 'guide.tendering.cta',
  ctaDefault: 'Create your first tender package',
};
