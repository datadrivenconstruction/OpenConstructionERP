// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// usersGuide - "How it works" content for the User Management module.
// Consumed by <ModuleGuideButton content={usersGuide} /> on
// UserManagementPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const usersGuide: ModuleGuideContent = {
  titleKey: 'guide.users.title',
  titleDefault: 'User Management',
  introKey: 'guide.users.intro',
  introDefault:
    'This is the admin panel for your team. Invite people, give each one a role, and tune exactly which modules they can reach. Use it whenever someone joins, leaves, or needs different access.',
  sections: [
    {
      icon: 'GraduationCap',
      titleKey: 'guide.users.invite.title',
      titleDefault: 'Invite team members',
      bodyKey: 'guide.users.invite.body',
      bodyDefault:
        'Admins use Invite User to add a person with their name, email, a starting role and an initial password. The password must be at least 12 characters and include a letter and a digit. The new user appears in the list right away and can sign in immediately.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.users.roles.title',
      titleDefault: 'Roles and what they grant',
      bodyKey: 'guide.users.roles.body',
      bodyDefault:
        'Every user holds one of four roles: Admin for full access, Manager for project management, Editor to create and edit, and Viewer for read-only. Change a role from the dropdown in the role column. Lowering a role asks you to confirm first, since the person loses the higher access at once.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.users.access.title',
      titleDefault: 'Per-user module access',
      bodyKey: 'guide.users.access.body',
      bodyDefault:
        'Click Access on any row to open the module matrix. For each module you set whether it is visible and an access level of none, view, edit or full. Presets like All, Viewer and Minimal set everything in one click, and a custom role name labels the mix you build.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.users.find.title',
      titleDefault: 'Find and filter people',
      bodyKey: 'guide.users.find.body',
      bodyDefault:
        'The stat cards across the top show totals for all users, active accounts, admins and managers. Search by name or email, and use the All, Active and Inactive filter to focus the table on the people you need.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.users.lifecycle.title',
      titleDefault: 'Activate and deactivate',
      bodyKey: 'guide.users.lifecycle.body',
      bodyDefault:
        'Deactivate revokes a person access at once while keeping their record, so you can reactivate them later if they return. You cannot change your own role or deactivate your own account, which prevents an accidental lockout.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.users.governance.title',
      titleDefault: 'Governance and the audit log',
      bodyKey: 'guide.users.governance.body',
      bodyDefault:
        'Roles set here decide what each person sees and can do across the platform. For the rules and approval steps behind those roles open Governance, and to review who changed what open the Audit Log, both linked from the intro panel.',
    },
  ],
  ctaKey: 'guide.users.cta',
  ctaDefault: 'Invite your first user',
};
