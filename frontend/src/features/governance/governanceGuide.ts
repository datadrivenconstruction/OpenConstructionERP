// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// governanceGuide - "How it works" content for the Governance module.
// Consumed by <ModuleGuideButton content={governanceGuide} /> on GovernancePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const governanceGuide: ModuleGuideContent = {
  titleKey: 'guide.governance.title',
  titleDefault: 'Governance',
  introKey: 'guide.governance.intro',
  introDefault:
    'Governance is the one admin home for three platform controls: who can do what, who signs off on records, and which standards a project is checked against. Set them here once and the rest of the modules enforce them.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.governance.overview.title',
      titleDefault: 'Three controls, three tabs',
      bodyKey: 'guide.governance.overview.body',
      bodyDefault:
        'This page gathers three settings surfaces behind tabs: Permissions, Approval Routes and Validation Rules. Each tab is the full admin page mounted in place, so you switch between them without leaving Governance.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.governance.permissions.title',
      titleDefault: 'Permissions',
      bodyKey: 'guide.governance.permissions.body',
      bodyDefault:
        'The Permissions tab is a role-by-action matrix that sets which role can do what across the platform. Grant or revoke a capability per role and it applies everywhere that capability is checked.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.governance.approvals.title',
      titleDefault: 'Approval routes',
      bodyKey: 'guide.governance.approvals.body',
      bodyDefault:
        'The Approval Routes tab defines who signs off, and in what order, on records such as RFIs, submittals and change requests. These routes drive the sign-off steps and approval badges those modules display.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.governance.validation.title',
      titleDefault: 'Validation rules',
      bodyKey: 'guide.governance.validation.body',
      bodyDefault:
        'The Validation Rules tab picks which standards a project is checked against, such as DIN 276, NRM, GAEB and BOQ quality. Your selection decides which checks run when data is imported and estimates are validated.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.governance.deeplink.title',
      titleDefault: 'Deep links and history',
      bodyKey: 'guide.governance.deeplink.body',
      bodyDefault:
        'The active tab lives in the page address, so you can bookmark or share a link straight to Permissions, Approval Routes or Validation Rules. Browser back and forward move between the tabs you visited.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.governance.enforcement.title',
      titleDefault: 'What it drives elsewhere',
      bodyKey: 'guide.governance.enforcement.body',
      bodyDefault:
        'Nothing here is cosmetic. What you set in these three tabs feeds the access checks, sign-off badges and validation results enforced across the other modules, so this is where you tune how strict the platform behaves.',
    },
  ],
  ctaKey: 'guide.governance.cta',
  ctaDefault: 'Review your permissions',
};
