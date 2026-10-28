// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// notificationsGuide - "How it works" content for the Notifications module.
// Consumed by <ModuleGuideButton content={notificationsGuide} /> on
// NotificationsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const notificationsGuide: ModuleGuideContent = {
  titleKey: 'guide.notifications.title',
  titleDefault: 'Notifications',
  introKey: 'guide.notifications.intro',
  introDefault:
    'The notification inbox collects every alert the platform raises into one place: finished imports, validation results, safety events, approvals and system messages. Use it to stay on top of what needs your attention and to control which events reach you on which channel.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.notifications.inbox.title',
      titleDefault: 'Your inbox',
      bodyKey: 'guide.notifications.inbox.body',
      bodyDefault:
        'The Inbox tab lists every notification newest first, with a colored icon for its category and a count of how many are unread. Unread items are highlighted so you can scan what is new at a glance.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.notifications.read.title',
      titleDefault: 'Read, navigate and clear',
      bodyKey: 'guide.notifications.read.body',
      bodyDefault:
        'Click a notification to mark it read and jump straight to the record it points at, such as the import, BOQ or risk that raised it. Use Mark all read to clear the unread badge in one step, or the trash icon on a row to remove a single message.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.notifications.filter.title',
      titleDefault: 'Filter and page',
      bodyKey: 'guide.notifications.filter.body',
      bodyDefault:
        'The filter switches the list between all, unread only and read only so you can focus on what is still outstanding. When there is more than a page of history, use the pager at the bottom to move through older items.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.notifications.preferences.title',
      titleDefault: 'Channel preferences',
      bodyKey: 'guide.notifications.preferences.body',
      bodyDefault:
        'The Preferences tab is a matrix of event types against channels. For each event you can turn in-app, email and webhook delivery on or off, and pick a digest of realtime, hourly or daily. Changes save automatically as you make them.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.notifications.sources.title',
      titleDefault: 'Where alerts come from',
      bodyKey: 'guide.notifications.sources.body',
      bodyDefault:
        'Most notifications are raised automatically as work happens across the platform. Threshold alerts from BI Dashboards and outbound rules from Notification Webhooks both flow through this same inbox, so one place shows everything.',
    },
  ],
  ctaKey: 'guide.notifications.cta',
  ctaDefault: 'Open your inbox',
};
