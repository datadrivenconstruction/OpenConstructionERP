// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - Teams (the Team & Plan panel in Settings).
// Hub card only: this is the Team & Plan tab on the Settings page, so the
// entry routes to the host /settings route. The actual member administration
// (invite, roles, per-module access, deactivate) lives in User Management,
// which has its own card at /users. See ../../types.ts for the shape and key
// convention.

import type { ModuleExplanation } from '../../types';

export const teamsModules: ModuleExplanation[] = [
  {
    id: 'teams',
    route: '/settings',
    icon: 'Users',
    category: 'admin',
    keywords:
      'team teams workspace members roles license plan edition agpl version invite manage administrator manager editor viewer settings panel member list active',
    titleKey: 'howto.teams.title',
    titleDefault: 'Team & plan',
    summaryKey: 'howto.teams.summary',
    summaryDefault:
      'See who shares this workspace, the roles they hold, and your edition and license, in the Settings Team & Plan tab.',
    whatKey: 'howto.teams.what',
    whatDefault:
      'The Team & Plan panel in Settings gives you the people picture of your workspace at a glance: how many members there are, how many are active, and how many hold each role from administrator down to viewer. A members list shows each person with their role and active status, and the License & Plan card confirms your edition (Community, AGPL-3.0), version and modules loaded. Administrators and managers see the full team here; everyone else sees their own membership. For inviting people, changing roles and setting per-module access, it links straight to User Management.',
    how: [
      {
        key: 'howto.teams.how.1',
        default:
          'Open Settings and choose the Team & Plan tab to see everyone who shares this workspace.',
      },
      {
        key: 'howto.teams.how.2',
        default:
          'Read the Team & workspace card for the count of total, active, administrator and manager members, with a breakdown of how many people hold each role.',
      },
      {
        key: 'howto.teams.how.3',
        default:
          "Scan the Members list to check each person's name, email, role and whether their account is active. Your own row is marked as you.",
      },
      {
        key: 'howto.teams.how.4',
        default:
          'As an administrator, use Invite User or Manage users to open User Management, where you invite people, change roles, set per-module access and deactivate accounts.',
      },
      {
        key: 'howto.teams.how.5',
        default:
          'Check the License & Plan card for your edition (Community, AGPL-3.0), version and modules loaded, and request a commercial license from there if you need support or an enterprise agreement.',
      },
    ],
    tips: [
      {
        key: 'howto.teams.tip.1',
        default:
          'Administrators and managers see the full member list here, while editors and viewers see only their own membership and role.',
      },
      {
        key: 'howto.teams.tip.2',
        default:
          'This tab is the team overview. The actual inviting, role changes and per-module access happen in User Management, one click away.',
      },
    ],
    whenKey: 'howto.teams.when',
    whenDefault:
      'Reach for it to check who is on the project and what role they hold, confirm your edition and version, or hand off to User Management when someone joins, changes role or leaves.',
  },
];
