// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// authoritySubmissionGuide - "How it works" content for the Authority
// Submission Factory. Consumed by <ModuleGuideButton content={...} /> on
// AuthoritySubmissionPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const authoritySubmissionGuide: ModuleGuideContent = {
  titleKey: 'guide.authority_submission.title',
  titleDefault: 'Authority Submission Factory',
  introKey: 'guide.authority_submission.intro',
  introDefault:
    'Build the structured document an authority expects, from a jurisdiction-neutral profile, and take it through validation before it is sent. One payload drives both the machine-readable XML and the human-readable review.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.authority_submission.what.title',
      titleDefault: 'What a profile is',
      bodyKey: 'guide.authority_submission.what.body',
      bodyDefault:
        'A profile is a data-driven schema, not code: a root element, a field list and a schema version. Built-in profiles ship jurisdiction-neutral (a generic document, a tender-exchange pattern, an asset-handover register); a regional pack can add a national dialect as another profile row.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.authority_submission.create.title',
      titleDefault: 'Start a submission',
      bodyKey: 'guide.authority_submission.create.body',
      bodyDefault:
        'Pick a profile and give the submission a title. It opens in Draft. Fill the payload as JSON matching the profile field set; editing the payload later always resets the submission back to Draft so nothing goes out unreviewed.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.authority_submission.validate.title',
      titleDefault: 'Validate the payload',
      bodyKey: 'guide.authority_submission.validate.body',
      bodyDefault:
        'Run Validate to check the payload against the profile: required fields present, types correct. A clean report moves a Draft to Validated; a report with errors pulls it back to Draft so it cannot be submitted on a stale pass.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.authority_submission.generate.title',
      titleDefault: 'Generate XML and review',
      bodyKey: 'guide.authority_submission.generate.body',
      bodyDefault:
        'Generate XML builds the deterministic machine document from the same payload. Render shows the human-readable side of that same data, so what you review is exactly what gets sent, never a second copy that can drift.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.authority_submission.submit.title',
      titleDefault: 'Submit',
      bodyKey: 'guide.authority_submission.submit.body',
      bodyDefault:
        'Submit is only available once the stored validation report is clean and the submission is Validated or Awaiting signature. It records the submission time and moves the record to Submitted, then Accepted or Rejected as the authority responds.',
    },
  ],
  ctaKey: 'guide.authority_submission.cta',
  ctaDefault: 'Start your first submission',
};
