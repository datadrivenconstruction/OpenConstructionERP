// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// changeIntelligenceGuide - "How it works" content for the Change Intelligence
// module. Consumed by <ModuleGuideButton content={changeIntelligenceGuide} />
// on ChangeIntelligencePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too. No spotlight
// selectors are set because the page exposes no stable [data-testid] hooks,
// so each card renders centred.

import type { ModuleGuideContent } from '@/shared/ui';

export const changeIntelligenceGuide: ModuleGuideContent = {
  titleKey: 'guide.change-intelligence.title',
  titleDefault: 'Change Intelligence',
  introKey: 'guide.change-intelligence.intro',
  introDefault:
    'Change Intelligence reads every change on the project in one place - change orders, variations, management-of-change entries, approvals and the correspondence around them - and turns them into co-pilots that tell you what to act on, what it has cost and what to recover. Each tab is a focused view; pick a project first and the page fills in.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.change-intelligence.scope.title',
      titleDefault: 'Pick a project, read the whole picture',
      bodyKey: 'guide.change-intelligence.scope.body',
      bodyDefault:
        'Everything here is scoped to one project. Choose a project and the co-pilots read its change orders, variations, management-of-change entries and correspondence together, so you stop hopping between modules to understand where the change picture stands.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.change-intelligence.act.title',
      titleDefault: 'Act first, then see who holds the ball',
      bodyKey: 'guide.change-intelligence.act.body',
      bodyDefault:
        'The Act first tab ranks open change items by urgency and names the recommended next action and the party the ball sits with. Waiting on whom ages every open item by responsible party, and Correspondence groups letters and emails into threads and flags the ones still awaiting your reply.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.change-intelligence.impact.title',
      titleDefault: 'Total what the changes have committed',
      bodyKey: 'guide.change-intelligence.impact.body',
      bodyDefault:
        'Impact sums the committed cost and schedule days of approved changes, broken down by kind and kept honest across currencies. Decision impact previews what approving one more candidate change would add on top of that baseline, before you commit to it.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.change-intelligence.recovery.title',
      titleDefault: 'Recover what others owe',
      bodyKey: 'guide.change-intelligence.recovery.body',
      bodyDefault:
        'Cost recovery is the one place you write to. Record a back-charge against the party at fault, set the gross amount and the share you judge chargeable, and split it across several parties when responsibility is shared. The recovery rate is reported by how provable each owner is, so well-evidenced charges show their stronger return.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.change-intelligence.risk.title',
      titleDefault: 'Get ahead of dispute, delay and scope risk',
      bodyKey: 'guide.change-intelligence.risk.body',
      bodyDefault:
        'Dispute risk ranks which open change is most likely to escalate and names the cure. Delay risk scores which items will overrun their response window. Scope risk grades your BOQ lines for vague wording before work starts, and Watch surfaces changes quietly drifting toward stalled, incomplete or lost.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.change-intelligence.notice.title',
      titleDefault: 'Never miss a contractual notice deadline',
      bodyKey: 'guide.change-intelligence.notice.body',
      bodyDefault:
        'The Time bar tab turns the event date already on each change, variation and extension-of-time claim into a countdown against the notice period for your contract standard (FIDIC, NEC, JCT, AIA or ConsensusDocs), worst-first. A red chip is overdue, amber is due soon, green is upcoming or met. When a required notice has nothing on file or the bar has lapsed, the row is flagged entitlement at risk, so a claim is not quietly forfeited. Override the standard from the filter when a record follows a different form.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.change-intelligence.clarifier.title',
      titleDefault: 'Turn rough notes into structured requests',
      bodyKey: 'guide.change-intelligence.clarifier.body',
      bodyDefault:
        'The Clarifier takes a rough change note, normalizes it, detects its classification, lists the missing details to ask for and suggests the contract clause and route. Intake maps a foreign record, such as a tracker row or an email form, into a clean draft. Both only preview, so nothing is saved until you decide.',
    },
  ],
  ctaKey: 'guide.change-intelligence.cta',
  ctaDefault: 'Open a project to begin',
};
