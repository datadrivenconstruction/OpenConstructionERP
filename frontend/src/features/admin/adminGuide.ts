// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// adminGuide - "How it works" content for the Admin / Audit Log module.
// Consumed by <ModuleGuideButton content={adminGuide} /> on AuditLogPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const adminGuide: ModuleGuideContent = {
  titleKey: 'guide.admin.title',
  titleDefault: 'Audit Log',
  introKey: 'guide.admin.intro',
  introDefault:
    'The audit log is a read-only timeline of every recorded change across the platform: who did it, on which record, and when. Use it to investigate a dispute or satisfy a compliance audit; access is limited to Manager and above.',
  sections: [
    {
      icon: 'FileSearch',
      titleKey: 'guide.admin.timeline.title',
      titleDefault: 'A read-only change timeline',
      bodyKey: 'guide.admin.timeline.body',
      bodyDefault:
        'Every audit-bearing action lands here as a row you can read but never edit. Each entry captures the timestamp, the actor and their IP address, the action verb, and the target entity, so the history is a trustworthy record of what happened.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.admin.filters.title',
      titleDefault: 'Filter and search the trail',
      bodyKey: 'guide.admin.filters.body',
      bodyDefault:
        'The filter bar narrows the timeline by user, module or entity, action, and date range, with quick Today, Last 7d and Last 30d presets. The free-text search box scans the actor, entity, IP and payload of the current page so you can find a specific event fast.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.admin.severity.title',
      titleDefault: 'Severity and sorting',
      bodyKey: 'guide.admin.severity.body',
      bodyDefault:
        'Each row is tagged Info, Warning or Critical, derived from the action so a delete stands out from a routine update. Use the severity chips to focus on risky changes, and click the Timestamp header to sort newest or oldest first.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.admin.detail.title',
      titleDefault: 'Open a row for the full payload',
      bodyKey: 'guide.admin.detail.body',
      bodyDefault:
        'Click any row to open the detail drawer. It shows the actor, and when the change carries a before and after snapshot it renders them side by side so you can see exactly which fields moved, with the complete raw payload below.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.admin.export.title',
      titleDefault: 'Export for evidence',
      bodyKey: 'guide.admin.export.body',
      bodyDefault:
        'Export CSV or Export JSON downloads the rows currently in view, with the actor email materialised alongside the user id so the file stands on its own. Adjust the page size and step through pages to capture the slice you need for a report.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.admin.access.title',
      titleDefault: 'Access and related controls',
      bodyKey: 'guide.admin.access.body',
      bodyDefault:
        'The log is gated to Manager and above and is read-only by design, so the record cannot be tampered with. To change who can do what, head to User Management for accounts and Governance for permissions and approval routes.',
    },
  ],
  ctaKey: 'guide.admin.cta',
  ctaDefault: 'Browse the audit trail',
};
