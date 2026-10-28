// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// bidManagementGuide - "How it works" content for the Bid Management module.
// Consumed by <ModuleGuideButton content={bidManagementGuide} /> on
// BidManagementPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const bidManagementGuide: ModuleGuideContent = {
  titleKey: 'guide.bid_management.title',
  titleDefault: 'Bid Management',
  introKey: 'guide.bid_management.intro',
  introDefault:
    'Bid Management runs tendering from end to end on one project: bundle scope into packages, invite subcontractors, collect their priced submissions, handle Q and A, then level the bids side by side and award the best one. Use it when you want to compare subcontractor offers like for like before committing.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.bid_management.packages.title',
      titleDefault: 'Bundle scope into packages',
      bodyKey: 'guide.bid_management.packages.body',
      bodyDefault:
        'A bid package is a slice of work you put out to tender, with a code, a title, a scope description, a budget estimate and a submission deadline. Click New Package to create one. Each package moves through a clear status from draft to published, open, closed and finally awarded.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.bid_management.invitations.title',
      titleDefault: 'Invite bidders',
      bodyKey: 'guide.bid_management.invitations.body',
      bodyDefault:
        'On the Invitations tab you ask firms to bid. Invite straight from the Subcontractor Directory so you pick prequalified companies and the invitation reaches their primary contact, or add a company by hand. The Sent and Responded counts on each package track who has replied.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.bid_management.submissions.title',
      titleDefault: 'Collect submissions',
      bodyKey: 'guide.bid_management.submissions.body',
      bodyDefault:
        'The Submissions tab gathers the priced offers bidders return against your scope lines. Only valid bids are carried forward into the comparison: those that arrive on time, are complete, and are quoted in the package currency. Late, incomplete or foreign-currency bids are held out so you never compare apples with oranges.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.bid_management.qa.title',
      titleDefault: 'Handle questions and answers',
      bodyKey: 'guide.bid_management.qa.body',
      bodyDefault:
        'The Q and A tab is the clarification channel for a package. Bidders post questions and you answer them; replies are shared with every bidder by default so the whole field works from the same information. This keeps the tender fair and your answers on the record.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.bid_management.leveling.title',
      titleDefault: 'Level the bids',
      bodyKey: 'guide.bid_management.leveling.body',
      bodyDefault:
        'Bid leveling lays the valid offers out as a matrix, line by line, and flags the lowest competitive price on each row. Click Compute Leveling to rank bidders on penalty-adjusted totals and commercial scores, with the recommended bidder highlighted, so the best overall offer is easy to spot.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.bid_management.award.title',
      titleDefault: 'Award the winner',
      bodyKey: 'guide.bid_management.award.body',
      bodyDefault:
        'When you are ready, award the package to a bidder. Confirm the awarded amount and record a decision summary explaining the choice. Awarding is final, the package moves to Awarded and the result flows straight into Contracts to manage the scope from there.',
    },
  ],
  ctaKey: 'guide.bid_management.cta',
  ctaDefault: 'Create your first package',
};
