// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// portalGuide - "How it works" content for the Client & Partner Portal module.
// Consumed by <ModuleGuideButton content={portalGuide} /> on PortalPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const portalGuide: ModuleGuideContent = {
  titleKey: 'guide.portal.title',
  titleDefault: 'Client & Partner Portal',
  introKey: 'guide.portal.intro',
  introDefault:
    'The portal lets you bring outside parties such as clients, investors, consultants and subcontractors into a project without giving them your full system. You invite them with a magic link, grant access to one resource at a time, and every view, download and signature is recorded.',
  sections: [
    {
      icon: 'Send',
      titleKey: 'guide.portal.invite.title',
      titleDefault: 'Invite external users',
      bodyKey: 'guide.portal.invite.body',
      bodyDefault:
        'Click Invite User to send a magic-link invite to a client, investor, consultant, subcontractor, supplier or building user. The role you pick drives their default scope, and they set their own password on first login. The Users tab lists everyone you have invited with their status and last login.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.portal.access.title',
      titleDefault: 'Grant scoped access',
      bodyKey: 'guide.portal.access.body',
      bodyDefault:
        'Nothing is visible until you explicitly grant it. On the Access Rules tab use Grant Access to create one rule per resource, picking a single project, development, document, service ticket or invoice and one permission: view, comment, submit or sign.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.portal.audit.title',
      titleDefault: 'Audit who saw what',
      bodyKey: 'guide.portal.audit.body',
      bodyDefault:
        'The Audit Log tab records every view, download and signature a portal user makes, with the document, action, IP address and timestamp. Open a user from the Users tab to see their recent access inline, so you always know who accessed which document and when.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.portal.progress.title',
      titleDefault: 'Share progress reports',
      bodyKey: 'guide.portal.progress.body',
      bodyDefault:
        'The Progress Reports tab is where you publish status updates to invited parties per project. Use it to keep clients and investors informed without exposing the underlying working data.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.portal.manage.title',
      titleDefault: 'Manage and revoke',
      bodyKey: 'guide.portal.manage.body',
      bodyDefault:
        'Open any user to resend their invite, suspend a user who should no longer have access, or reactivate a suspended one. Revoke an access rule the moment a resource should be hidden again; the change takes effect on the user next login.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.portal.connect.title',
      titleDefault: 'Connected to the rest of the system',
      bodyKey: 'guide.portal.connect.body',
      bodyDefault:
        'A subcontractor can be invited straight from the Subcontractors page, and every granted project, document, ticket or invoice links back to where it lives in the app. Progress claims flow in from Contracts, so the portal stays in step with the work it exposes.',
    },
  ],
  ctaKey: 'guide.portal.cta',
  ctaDefault: 'Invite your first user',
};
