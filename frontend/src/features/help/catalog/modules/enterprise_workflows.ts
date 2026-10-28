// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - per-module gap-fill: Enterprise Workflows.
// A sub-panel of Governance (host route /governance), surfaced as the
// Approval Routes tab. See ../../types.ts for the ModuleExplanation shape and
// the key convention. English defaults live inline; translators fill the
// other locales later. The glob aggregator in moduleExplanations.ts picks this
// file up automatically, so no edit there is needed.

import type { ModuleExplanation } from '../../types';

export const enterpriseWorkflowsModules: ModuleExplanation[] = [
  {
    id: 'enterprise_workflows',
    route: '/governance',
    icon: 'Workflow',
    category: 'admin',
    keywords:
      'enterprise workflow approval route routing sign-off multi-step ladder template submittal rfi change order markup variation escalation sla delegation out of office ball in court reassign role user majority governance fsm large organisation',
    titleKey: 'howto.enterprise_workflows.title',
    titleDefault: 'Enterprise Workflows',
    summaryKey: 'howto.enterprise_workflows.summary',
    summaryDefault:
      'Configurable multi-step approval routing for large organisations: reusable sign-off ladders applied to submittals, RFIs, change orders and more.',
    whatKey: 'howto.enterprise_workflows.what',
    whatDefault:
      'Enterprise Workflows is the Approval Routes side of Governance, where a large organisation sets up how work gets signed off. You build reusable route templates, each tied to one record type and either global or scoped to a single project, as an ordered ladder of steps. Every step names who approves - a role or a specific person - and how many must agree, with an optional time limit. Once saved, the route runs automatically whenever a matching record needs approval, so the right people sign off in the right order every time, with out-of-office cover and a live view of everything in flight.',
    how: [
      {
        key: 'howto.enterprise_workflows.how.1',
        default: 'Open Governance from the sidebar and switch to the Approval Routes tab.',
      },
      {
        key: 'howto.enterprise_workflows.how.2',
        default:
          'Press New route, give it a name, pick the target kind it applies to (submittals, RFIs, change orders, markups and more) and whether it is global or scoped to one project.',
      },
      {
        key: 'howto.enterprise_workflows.how.3',
        default:
          'Add steps in order; for each step pin an approver as a role or a named user, set the decision mode (All, Any or Majority) and an optional SLA in hours.',
      },
      {
        key: 'howto.enterprise_workflows.how.4',
        default:
          'Save the route; other modules then run it on matching records to collect sign-offs in sequence. You can still rename it, edit its steps or archive it later.',
      },
      {
        key: 'howto.enterprise_workflows.how.5',
        default:
          'Use Out of office to delegate approvals to a stand-in for a date window so a workflow never stalls while an approver is away.',
      },
      {
        key: 'howto.enterprise_workflows.how.6',
        default:
          'Open Running and history to watch every workflow in flight, filter by kind or status, and approve, reject, reassign or cancel a pending step.',
      },
    ],
    tips: [
      {
        key: 'howto.enterprise_workflows.tip.1',
        default:
          'A step pinned to a role clears on the first approval; to require everyone or a majority, pin specific people and set the mode to All or Majority.',
      },
      {
        key: 'howto.enterprise_workflows.tip.2',
        default:
          'Target kind and scope lock once a route is saved, so choose them with care; the name and steps stay editable afterwards.',
      },
      {
        key: 'howto.enterprise_workflows.tip.3',
        default:
          'Set an SLA in hours on the steps that matter so an overdue approval is flagged and can escalate instead of quietly stalling.',
      },
    ],
    whenKey: 'howto.enterprise_workflows.when',
    whenDefault:
      'Reach for it when your organisation needs the same records signed off the same way every time, such as multi-stage submittal reviews, RFI responses or change-order authorisation across many projects and people.',
  },
];
