// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// cdeGuide - "How it works" content for the Common Data Environment module.
// Consumed by <ModuleGuideButton content={cdeGuide} /> on CDEPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const cdeGuide: ModuleGuideContent = {
  titleKey: 'guide.cde.title',
  titleDefault: 'Common Data Environment',
  introKey: 'guide.cde.intro',
  introDefault:
    'The Common Data Environment is the single agreed home for project documents, structured into ISO 19650 information containers. Use it to keep every revision on a controlled path so the whole team always works off the right version.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.cde.containers.title',
      titleDefault: 'Information containers',
      bodyKey: 'guide.cde.containers.body',
      bodyDefault:
        'A container is a managed slot for one deliverable, identified by a container code, a title, a discipline such as architecture or MEP, and an optional classification. Click New Container to create one, then promote and revise it over the life of the project.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.cde.states.title',
      titleDefault: 'The ISO 19650 states',
      bodyKey: 'guide.cde.states.body',
      bodyDefault:
        'Every container moves through four states: Work in Progress while it is being authored, Shared for team review, Published once formally approved and issued, then Archived when it is superseded. The state badge and suitability code show exactly where each one sits.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.cde.browse.title',
      titleDefault: 'Find and filter containers',
      bodyKey: 'guide.cde.browse.body',
      bodyDefault:
        'The summary cards count how many containers sit in each state. Use the state tabs to narrow the list to WIP, Shared, Published or Archived, and the search box to match by code, title or classification. Expand any row to see its revision history.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.cde.revisions.title',
      titleDefault: 'Link documents and revisions',
      bodyKey: 'guide.cde.revisions.body',
      bodyDefault:
        'Upload documents in Files first, then expand a container and choose Link Document to attach them as revisions. Each linked revision references the real file and is recorded with its code, date and change summary, so the container always reflects the current issue.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.cde.gates.title',
      titleDefault: 'Promote through the gates',
      bodyKey: 'guide.cde.gates.body',
      bodyDefault:
        'Promoting a container crosses a gate that depends on your role: a project manager or admin can move it from WIP to Shared and on to Published, and an admin archives it. Publishing from Shared requires a signed approval, which is captured in the audit log.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.cde.distribute.title',
      titleDefault: 'Distribute and track history',
      bodyKey: 'guide.cde.distribute.body',
      bodyDefault:
        'From an expanded row you can send a container via Transmittal, raise a Submittal for formal approval, or open History to review every state transition. This closes the loop from organised documents to controlled issue and a full audit trail.',
    },
  ],
  ctaKey: 'guide.cde.cta',
  ctaDefault: 'Create your first container',
};
