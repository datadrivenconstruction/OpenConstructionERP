// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// meetingsGuide - "How it works" content for the Meetings module.
// Consumed by <ModuleGuideButton content={meetingsGuide} /> on MeetingsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const meetingsGuide: ModuleGuideContent = {
  titleKey: 'guide.meetings.title',
  titleDefault: 'Meetings',
  introKey: 'guide.meetings.intro',
  introDefault:
    'Meetings is where you schedule, run and document every project meeting so decisions and follow-ups never get lost. Use it for progress reviews, design coordination, safety talks, kickoffs and closeouts, then turn the discussion into tracked action items with an owner and a due date.',
  sections: [
    {
      icon: 'PencilLine',
      titleKey: 'guide.meetings.create.title',
      titleDefault: 'Schedule a meeting',
      bodyKey: 'guide.meetings.create.body',
      bodyDefault:
        'Click New Meeting to pick a type, set the date, time and location, and write the agenda or minutes. Each meeting is numbered and sits under the current project, so the full history stays in one place.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.meetings.people.title',
      titleDefault: 'Chair and attendees',
      bodyKey: 'guide.meetings.people.body',
      bodyDefault:
        'Set a chairperson and add attendees by picking real people from your contacts, with a free-text fallback for guests who are not in the directory. Linked attendees keep a path back to their record, and you can mark each one present, absent or excused on the day.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.meetings.series.title',
      titleDefault: 'Recurring series',
      bodyKey: 'guide.meetings.series.body',
      bodyDefault:
        'For standing site or coordination meetings, use Create recurring series to generate the whole run at once on a weekly or other cadence. Every occurrence lands in the list ready to be filled in as it happens.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.meetings.import.title',
      titleDefault: 'Import a transcript',
      bodyKey: 'guide.meetings.import.body',
      bodyDefault:
        'Already held the meeting elsewhere? Use Import Summary to upload a transcript from Microsoft Teams, Google Meet, Zoom or Webex. AI extracts the title, key topics, attendees and action items into a preview you review and edit before it is saved.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.meetings.actions.title',
      titleDefault: 'Action items flow into Tasks',
      bodyKey: 'guide.meetings.actions.body',
      bodyDefault:
        'Action items captured in a meeting become tracked tasks with an owner and a due date, so follow-ups are visible in the Tasks module and nothing slips. Attach files such as minutes or drawings to keep the supporting documents with the record.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.meetings.track.title',
      titleDefault: 'Find, complete and export',
      bodyKey: 'guide.meetings.track.body',
      bodyDefault:
        'The header shows live counts for total, scheduled, in progress and completed meetings. Search by title, number or chair, filter by type and status, mark a meeting complete, and export the minutes to PDF to share.',
    },
  ],
  ctaKey: 'guide.meetings.cta',
  ctaDefault: 'Schedule your first meeting',
};
