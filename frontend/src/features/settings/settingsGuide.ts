// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// settingsGuide - "How it works" content for the Settings module.
// Consumed by <ModuleGuideButton content={settingsGuide} /> on SettingsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const settingsGuide: ModuleGuideContent = {
  titleKey: 'guide.settings.title',
  titleDefault: 'Settings',
  introKey: 'guide.settings.intro',
  introDefault:
    'Settings is where you set the platform up once for your whole workspace. The page is split into tabs down the left side, and the choices you make here flow into every module for this workspace.',
  sections: [
    {
      icon: 'PencilLine',
      titleKey: 'guide.settings.general.title',
      titleDefault: 'General: profile, theme and mode',
      bodyKey: 'guide.settings.general.body',
      bodyDefault:
        'The General tab holds your profile, where you edit your full name and see your email, role and account status. From here you also pick a light, dark or system color scheme and switch the interface between Simple, with the essential estimation tools, and Advanced, with the full professional toolset.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.settings.regional.title',
      titleDefault: 'Regional formats',
      bodyKey: 'guide.settings.regional.body',
      bodyDefault:
        'The Regional tab sets your language, timezone and number, date and currency formats. These choices control how figures and dates are displayed across every module, so set them to match how your team works.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.settings.ai.title',
      titleDefault: 'Connect an AI provider',
      bodyKey: 'guide.settings.ai.body',
      bodyDefault:
        'The AI tab is where you choose a provider such as Anthropic Claude, OpenAI or a local runtime, and paste the API key that powers estimation and analysis. Your key is encrypted and stored securely. Use Test Connection to confirm it works, and set a model name override if a provider renames or retires a model.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.settings.integrations.title',
      titleDefault: 'Integrations and converters',
      bodyKey: 'guide.settings.integrations.body',
      bodyDefault:
        'The Integrations tab wires up Slack, Teams, Telegram and inbound webhooks so the platform can talk to the tools your team already uses. The Converters tab shows the installed DDC converter versions and their GitHub sources, which handle turning CAD and BIM files into estimable data.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.settings.advanced.title',
      titleDefault: 'Advanced: backup and setup',
      bodyKey: 'guide.settings.advanced.body',
      bodyDefault:
        'The Advanced tab covers backup and restore plus the database setup wizard. The Dashboard tab lets you reorder, show or hide the sections on your personal dashboard, saved to this browser.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.settings.account.title',
      titleDefault: 'Account security',
      bodyKey: 'guide.settings.account.body',
      bodyDefault:
        'The Account tab is where you change your password and sign out of all sessions. The Danger Zone groups sensitive actions, including erasing your personal data, and admins can remove the seeded demo projects from here without affecting their own work.',
    },
  ],
  ctaKey: 'guide.settings.cta',
  ctaDefault: 'Set up your workspace',
};
