// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// reviewAuthorityGuide - "How it works" content for the Review Authority
// module. Consumed by <ModuleGuideButton content={reviewAuthorityGuide} />
// on ReviewAuthorityPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const reviewAuthorityGuide: ModuleGuideContent = {
  titleKey: 'guide.review_authority.title',
  titleDefault: 'Review Authority',
  introKey: 'guide.review_authority.intro',
  introDefault:
    'Review Authority tracks the review cycle a project runs with an external approving body: state expertise, building control, an authority having jurisdiction, or a technical review board. It records the submission, the document version the authority actually reviewed, every remark they raise, your responses, and the final decision.',
  sections: [
    {
      icon: 'FolderOpen',
      titleKey: 'guide.review_authority.open.title',
      titleDefault: 'Open a cycle',
      bodyKey: 'guide.review_authority.open.body',
      bodyDefault:
        'Start a cycle for the authority you are submitting to, set an SLA in days, then Submit to freeze the document version being reviewed and start the clock.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.review_authority.transition.title',
      titleDefault: 'Move it through its stages',
      bodyKey: 'guide.review_authority.transition.body',
      bodyDefault:
        'A cycle walks a fixed sequence: submitted, under review, remarks issued, responding, resubmitted, then approved, rejected or withdrawn. Only the next legal step is offered, so the record always reflects what actually happened.',
    },
    {
      icon: 'MessageSquareWarning',
      titleKey: 'guide.review_authority.remarks.title',
      titleDefault: 'Log remarks and respond',
      bodyKey: 'guide.review_authority.remarks.body',
      bodyDefault:
        'Add each remark the authority raises with its severity and, where one exists, the norm it cites. A remark without a cited norm is flagged for a human to confirm whether it is contestable; the platform never decides that on its own. Respond, then record the final decision.',
    },
    {
      icon: 'ShieldAlert',
      titleKey: 'guide.review_authority.insights.title',
      titleDefault: 'Stale remarks and the repeat radar',
      bodyKey: 'guide.review_authority.insights.body',
      bodyDefault:
        'If the project moves the document on after a remark was pinned, that remark is flagged stale so nobody chases an outdated point. The repeat radar also flags a new remark that closely matches one already accepted, in case the authority is re-raising a settled item.',
    },
  ],
  ctaKey: 'guide.review_authority.cta',
  ctaDefault: 'Open your first review cycle',
};
