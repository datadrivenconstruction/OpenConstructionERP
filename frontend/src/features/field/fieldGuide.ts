// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fieldGuide - "How it works" content for the Field (mobile field-worker)
// shell. Consumed by <ModuleGuideButton content={fieldGuide} /> in the
// FieldShellPage header.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const fieldGuide: ModuleGuideContent = {
  titleKey: 'guide.field.title',
  titleDefault: 'Field',
  introKey: 'guide.field.intro',
  introDefault:
    'Field is the lightweight mobile screen for workers on site. Open it from the SMS link to log your hours, capture daily diary entries and punch your crew in and out, even with no signal.',
  sections: [
    {
      icon: 'Send',
      titleKey: 'guide.field.signin.title',
      titleDefault: 'Sign in from the SMS link',
      bodyKey: 'guide.field.signin.body',
      bodyDefault:
        'You reach this screen by tapping the link in your text message and entering your PIN. No account or password is needed. Once in, the four tabs along the bottom, Today, Capture, Crew and Me, are all you need for the day.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.field.today.title',
      titleDefault: "Today's diary",
      bodyKey: 'guide.field.today.body',
      bodyDefault:
        'The Today tab shows the diary entries already logged for the current day on your project. Pull to refresh to pick up the latest. If it is empty, head to Capture to record your first entry.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.field.capture.title',
      titleDefault: 'Log your time',
      bodyKey: 'guide.field.capture.body',
      bodyDefault:
        'On the Capture tab pick the task you worked on, set your start and end time and add an optional note. The hours are worked out for you, and Save time records the entry against today.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.field.crew.title',
      titleDefault: 'Punch the crew in and out',
      bodyKey: 'guide.field.crew.body',
      bodyDefault:
        'The Crew tab lets a foreman track a whole team. Add each member by name, pick their task, then punch them In when they start and Out when they finish. Each punch is saved as a timed activity on the diary.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.field.offline.title',
      titleDefault: 'Works offline',
      bodyKey: 'guide.field.offline.body',
      bodyDefault:
        'Site connections drop, so every tap is saved on the device first. The badge in the header shows Online, Offline or how many changes are still to sync. When signal returns your entries upload automatically.',
    },
  ],
  ctaKey: 'guide.field.cta',
  ctaDefault: 'Log your time',
};
