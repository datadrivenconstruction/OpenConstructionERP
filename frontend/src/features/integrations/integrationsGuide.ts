// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// integrationsGuide - "How it works" content for the Integrations module.
// Consumed by <ModuleGuideButton content={integrationsGuide} /> on
// IntegrationsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const integrationsGuide: ModuleGuideContent = {
  titleKey: 'guide.integrations.title',
  titleDefault: 'Integrations',
  introKey: 'guide.integrations.intro',
  introDefault:
    'Integrations push your project events into the tools your team already uses. Connect a chat app, email or a signed webhook, choose which events trigger a message, and let the rest of your stack react automatically.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.integrations.catalog.title',
      titleDefault: 'A catalog of connectors',
      bodyKey: 'guide.integrations.catalog.body',
      bodyDefault:
        'The page lists every connector as a card, grouped into three categories: Notifications, Automation, and Data and Analytics. Each card shows a short description and a badge telling you whether it is ready to connect, already connected, or a guide-only reference.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.integrations.notifications.title',
      titleDefault: 'Connect a notification channel',
      bodyKey: 'guide.integrations.notifications.body',
      bodyDefault:
        'Microsoft Teams, Slack, Telegram, Discord and email (SMTP) deliver project alerts straight to your inbox or chat. Click Connect, follow the numbered setup steps, paste the webhook URL or credentials, and save.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.integrations.events.title',
      titleDefault: 'Pick the events that matter',
      bodyKey: 'guide.integrations.events.body',
      bodyDefault:
        'A webhook can subscribe to specific events such as tasks created, RFIs answered, invoices approved, document uploads and BOQ changes. Tick the events you want, or select all, so you only receive the signals you care about.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.integrations.test.title',
      titleDefault: 'Test before you rely on it',
      bodyKey: 'guide.integrations.test.body',
      bodyDefault:
        'Use Test Connection to send a sample message and confirm the channel is wired correctly before saving. Connected integrations keep a test button and an active or inactive indicator, and can be disconnected at any time.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.integrations.automation.title',
      titleDefault: 'Automation and webhooks',
      bodyKey: 'guide.integrations.automation.body',
      bodyDefault:
        'A signed webhook sends events to any URL as an HTTP POST with optional HMAC signing. Point n8n, Zapier or Make at that endpoint to wire OpenConstructionERP into thousands of other apps through a single trigger node.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.integrations.data.title',
      titleDefault: 'Calendar feed and the REST API',
      bodyKey: 'guide.integrations.data.body',
      bodyDefault:
        'Copy the iCal feed URL to subscribe to project due dates in Google Calendar or Outlook. For everything else, connect BI tools like Power BI or Tableau, or build your own integration, against the full REST API documented at /api/docs.',
    },
  ],
  ctaKey: 'guide.integrations.cta',
  ctaDefault: 'Connect your first tool',
};
