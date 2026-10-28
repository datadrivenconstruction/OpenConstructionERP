// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Automation & AI + Integrations + Setup & admin.
// See ../types.ts for the shape + key convention, and
// ../catalog/overview-estimating.ts for a fully-worked example.

import type { ModuleExplanation } from '../types';

export const automationIntegrationsAdminModules: ModuleExplanation[] = [
  /* ── Automation & AI ──────────────────────────────────────────────────── */
  {
    id: 'ai-agents',
    route: '/ai-agents',
    icon: 'Bot',
    category: 'automation',
    beta: true,
    keywords: 'agent automation tool react timeline schedule trigger run',
    titleKey: 'howto.ai-agents.title',
    titleDefault: 'AI Agents',
    summaryKey: 'howto.ai-agents.summary',
    summaryDefault: 'Configurable assistants that run multi-step tasks against your project data.',
    whatKey: 'howto.ai-agents.what',
    whatDefault:
      'AI Agents are assistants that work through a task for you instead of just answering. Each agent is given a set of tools it can call against your real project data, and it decides which steps to take to reach the goal. You pick a ready-made agent from the gallery or build your own, run it, and watch every step as it happens.',
    how: [
      { key: 'howto.ai-agents.how.1', default: 'Open the agent gallery and pick an agent whose job matches what you need done.' },
      { key: 'howto.ai-agents.how.2', default: 'Set the project context and any inputs, then press Run to start it.' },
      { key: 'howto.ai-agents.how.3', default: 'Follow the live timeline as the agent calls each tool, so you can see how it reached its result.' },
      { key: 'howto.ai-agents.how.4', default: 'Review the output and apply the suggested actions, or open a past run from the history list.' },
      { key: 'howto.ai-agents.how.5', default: 'Build a custom agent, or put one on a schedule so it runs automatically on a recurring basis.' },
    ],
    tips: [
      { key: 'howto.ai-agents.tip.1', default: 'An agent only ever proposes changes - you stay in control and confirm before anything is written to a project.' },
    ],
    whenKey: 'howto.ai-agents.when',
    whenDefault: 'Reach for an agent when a task spans several steps or modules and you would rather supervise than do each step by hand.',
  },
  {
    id: 'advisor',
    route: '/advisor',
    icon: 'Brain',
    category: 'automation',
    keywords: 'cost advisor price rate question ask sources cwicr',
    titleKey: 'howto.advisor.title',
    titleDefault: 'AI Cost Advisor',
    summaryKey: 'howto.advisor.summary',
    summaryDefault: 'Ask questions about your cost data and get answers backed by real rates.',
    whatKey: 'howto.advisor.what',
    whatDefault:
      'The AI Cost Advisor lets you ask the cost database a question in plain language - what a item should cost, how rates compare across regions, or which source to trust. It answers in words and shows the actual catalog rates it drew on, so the answer is traceable rather than a guess.',
    how: [
      { key: 'howto.advisor.how.1', default: 'Type a cost question in plain language, for example a rate for a item of work in a given region.' },
      { key: 'howto.advisor.how.2', default: 'Read the answer, then check the cost sources it lists underneath to see the rates behind it.' },
      { key: 'howto.advisor.how.3', default: 'Refine with a follow-up question, or pass a figure into a Quick Estimate to keep working.' },
    ],
    tips: [
      { key: 'howto.advisor.tip.1', default: 'Answers are only as good as the cost data loaded - install the regional catalog for your market for the most relevant rates.' },
    ],
    whenKey: 'howto.advisor.when',
    whenDefault: 'Use it for a fast, sourced sense-check of a rate before you commit it to an estimate.',
  },
  {
    id: 'chat',
    route: '/chat',
    icon: 'MessageCircle',
    category: 'automation',
    keywords: 'assistant conversation ask query tables charts portfolio',
    titleKey: 'howto.chat.title',
    titleDefault: 'AI Chat',
    summaryKey: 'howto.chat.summary',
    summaryDefault: 'Your whole ERP in one conversation: ask in plain language, get interactive answers.',
    whatKey: 'howto.chat.what',
    whatDefault:
      'AI Chat is an in-app assistant that turns plain-language questions into answers built from your live ERP data. Ask about projects, the bill of quantities, schedule, validation, risk or costs, and it renders the result as interactive tables, charts and matrices on the right instead of plain text.',
    how: [
      { key: 'howto.chat.how.1', default: 'Type a question or request in the input box - no special syntax - or click a suggestion chip to start.' },
      { key: 'howto.chat.how.2', default: 'Watch the assistant pick and run tools against live data; each call appears in the conversation as it executes.' },
      { key: 'howto.chat.how.3', default: 'Read the answer in the data panel on the right as interactive grids, schedules, reports and metrics.' },
      { key: 'howto.chat.how.4', default: 'Select a project at the top to focus the assistant, or leave it unset to work across your whole portfolio.' },
    ],
    tips: [
      { key: 'howto.chat.tip.1', default: 'Every conversation is saved - reopen a recent chat to rebuild its messages and data panel exactly as you left them.' },
    ],
    whenKey: 'howto.chat.when',
    whenDefault: 'Use it for quick answers across modules without navigating to each one - find zero-price items, compute totals or compare projects.',
  },
  {
    id: 'pipelines',
    route: '/pipelines',
    icon: 'Workflow',
    category: 'automation',
    beta: true,
    keywords: 'no-code node graph workflow trigger transform validation gate output automation',
    titleKey: 'howto.pipelines.title',
    titleDefault: 'Pipeline Builder',
    summaryKey: 'howto.pipelines.summary',
    summaryDefault: 'A no-code canvas to wire up triggers, transforms, validation gates and outputs.',
    whatKey: 'howto.pipelines.what',
    whatDefault:
      'The Pipeline Builder is a no-code canvas for automating repeatable work. You drag nodes onto the graph and connect them - a trigger to start it, transform steps to reshape data, validation gates to stop bad data, and output steps to deliver the result - then run the pipeline and watch each node light up.',
    how: [
      { key: 'howto.pipelines.how.1', default: 'Drag nodes from the palette onto the canvas and connect them into a flow.' },
      { key: 'howto.pipelines.how.2', default: 'Start with a trigger node, then add transform and validation-gate nodes to shape and check the data.' },
      { key: 'howto.pipelines.how.3', default: 'Select any node to set its options in the inspector panel on the right.' },
      { key: 'howto.pipelines.how.4', default: 'Press Run and follow the run dock as each node executes, then read its output.' },
    ],
    tips: [
      { key: 'howto.pipelines.tip.1', default: 'Put a validation gate before any output step so a pipeline never delivers data that has not passed your checks.' },
    ],
    whenKey: 'howto.pipelines.when',
    whenDefault: 'Use it when you find yourself repeating the same import, clean-up and check by hand and want to wire it together once.',
  },

  /* ── Integrations & exchange ──────────────────────────────────────────── */
  {
    id: 'gaeb-exchange',
    route: '/gaeb-exchange',
    icon: 'FileText',
    category: 'integrations',
    keywords: 'gaeb xml x81 x83 da tender bid leistungsverzeichnis lv dach ava import export',
    titleKey: 'howto.gaeb-exchange.title',
    titleDefault: 'GAEB Exchange',
    summaryKey: 'howto.gaeb-exchange.summary',
    summaryDefault: 'Exchange bill-of-quantities data in the GAEB DA XML format - import X81/X83, export tenders.',
    whatKey: 'howto.gaeb-exchange.what',
    whatDefault:
      'GAEB Exchange moves bill-of-quantities data in and out of the GAEB DA XML format used across the German-speaking market. Import a priceless tender file (X81) or a priced bid (X83) straight into a BOQ, or export your BOQ back out as a tender or bid document in the same format. Imports run through validation on the way in, so the work list arrives structured and checked.',
    how: [
      { key: 'howto.gaeb-exchange.how.1', default: 'Open the Import tab and drop in a GAEB DA XML file - X81 for a priceless tender or X83 for a priced bid.' },
      { key: 'howto.gaeb-exchange.how.2', default: 'Review the preview of parsed positions, then import them into a project BOQ.' },
      { key: 'howto.gaeb-exchange.how.3', default: 'To send work out, switch to the Export tab, pick the BOQ and the GAEB format, and download the file.' },
    ],
    tips: [
      { key: 'howto.gaeb-exchange.tip.1', default: 'Use X81 to issue a tender for others to price, and X83 to return or receive a priced bid.' },
    ],
    whenKey: 'howto.gaeb-exchange.when',
    whenDefault: 'Reach for it whenever you tender or bid with partners who exchange bills of quantities as GAEB files.',
  },
  {
    id: 'integrations',
    route: '/integrations',
    icon: 'Plug',
    category: 'integrations',
    keywords: 'connect notifications webhook chat email automation outbound events connector',
    titleKey: 'howto.integrations.title',
    titleDefault: 'Integrations',
    summaryKey: 'howto.integrations.summary',
    summaryDefault: 'Connect outside systems and services so events flow out of the platform.',
    whatKey: 'howto.integrations.what',
    whatDefault:
      'Integrations connect the platform to the outside tools you already use. Set up connectors for chat and messaging, email or a generic webhook, choose which events should trigger them, and the platform pushes notifications out as those events happen. Other connectors point you to automation and data tools you can wire up.',
    how: [
      { key: 'howto.integrations.how.1', default: 'Browse the available connectors and pick one for the service you want to reach.' },
      { key: 'howto.integrations.how.2', default: 'Fill in its connection details and pick which events should trigger it.' },
      { key: 'howto.integrations.how.3', default: 'Send a test to confirm the connection works, then switch the integration on.' },
    ],
    tips: [
      { key: 'howto.integrations.tip.1', default: 'Use the test action before going live - it confirms credentials and routing without waiting for a real event.' },
    ],
    whenKey: 'howto.integrations.when',
    whenDefault: 'Set these up when your team wants project events to land in the chat, inbox or system they already watch.',
  },

  /* ── Setup & administration ───────────────────────────────────────────── */
  {
    id: 'settings',
    route: '/settings',
    icon: 'Settings',
    category: 'admin',
    keywords: 'preferences profile theme language locale regional ai key backup restore',
    titleKey: 'howto.settings.title',
    titleDefault: 'Settings',
    summaryKey: 'howto.settings.summary',
    summaryDefault: 'Your workspace and account preferences in one place.',
    whatKey: 'howto.settings.what',
    whatDefault:
      'Settings is where you tune the workspace to how you work: your profile and password, light or dark theme, interface language, regional and currency preferences, your AI provider connection, team, dashboard layout and backup or restore. Most options apply to your account; team-wide ones are clearly grouped.',
    how: [
      { key: 'howto.settings.how.1', default: 'Use the tabs to move between profile, appearance, regional, AI and the other settings groups.' },
      { key: 'howto.settings.how.2', default: 'Change a value, then save - the interface updates straight away for things like theme and language.' },
      { key: 'howto.settings.how.3', default: 'Connect your AI provider key here so the assistant, advisor and agents can run.' },
    ],
    tips: [
      { key: 'howto.settings.tip.1', default: 'Set your region and currency early - cost data, formatting and reports all follow these preferences.' },
    ],
    whenKey: 'howto.settings.when',
    whenDefault: 'Visit once when you set up, then whenever you need to change a preference, key or backup.',
  },
  {
    id: 'users',
    route: '/users',
    icon: 'Users',
    category: 'admin',
    keywords: 'user management roles invite access permissions admin manager editor viewer module access',
    titleKey: 'howto.users.title',
    titleDefault: 'User Management',
    summaryKey: 'howto.users.summary',
    summaryDefault: 'Invite people, set their roles and control which modules they can reach.',
    whatKey: 'howto.users.what',
    whatDefault:
      'User Management is the admin panel for your team. Invite new people, set each person a role - administrator, manager, editor or viewer - activate or deactivate accounts, and fine-tune which modules each user can see and how much they can do in each one.',
    how: [
      { key: 'howto.users.how.1', default: 'Click to invite a user by email; they receive an invitation to join the workspace.' },
      { key: 'howto.users.how.2', default: 'Set each person a role to grant a sensible default level of access across the app.' },
      { key: 'howto.users.how.3', default: 'Open a user to adjust their per-module access, or deactivate an account when someone leaves.' },
    ],
    tips: [
      { key: 'howto.users.tip.1', default: 'Give people the lowest role that lets them do their job - you can always raise it, and viewers cannot change data.' },
    ],
    whenKey: 'howto.users.when',
    whenDefault: 'Use it when onboarding the team or whenever someone joins, changes role or leaves.',
  },
  {
    id: 'modules',
    route: '/modules',
    icon: 'Boxes',
    category: 'admin',
    keywords: 'modules enable disable marketplace packs country regional install features',
    titleKey: 'howto.modules.title',
    titleDefault: 'Modules',
    summaryKey: 'howto.modules.summary',
    summaryDefault: 'Turn features on or off and install country and partner packs.',
    whatKey: 'howto.modules.what',
    whatDefault:
      'The Modules page lets you shape the app to your business. Enable or disable individual modules so the sidebar only shows what your team uses, and browse the marketplace to install country and partner packs that add regional cost data, formats and tailored features.',
    how: [
      { key: 'howto.modules.how.1', default: 'Browse the module list and toggle features on or off to fit how your team works.' },
      { key: 'howto.modules.how.2', default: 'Open the marketplace to find a country or partner pack for your market.' },
      { key: 'howto.modules.how.3', default: 'Install a pack to add its data and features, and deactivate it later if you no longer need it.' },
    ],
    tips: [
      { key: 'howto.modules.tip.1', default: 'Turning off modules you do not use keeps the sidebar focused; the data is untouched and the module comes back the moment you re-enable it.' },
    ],
    whenKey: 'howto.modules.when',
    whenDefault: 'Set this up early to trim the app to your workflow, and revisit when you expand into a new region.',
  },
  {
    id: 'governance',
    route: '/governance',
    icon: 'ShieldCheck',
    category: 'admin',
    keywords: 'permissions approvals approval routes validation rules roles policy compliance',
    titleKey: 'howto.governance.title',
    titleDefault: 'Governance',
    summaryKey: 'howto.governance.summary',
    summaryDefault: 'One home for permissions, approval routes and validation rules.',
    whatKey: 'howto.governance.what',
    whatDefault:
      'Governance brings the platform-wide rules together in one place under three tabs: Permissions, which controls who can do what; Approval Routes, which define who must sign off on a step; and Validation Rules, the checks data must pass. It is where an administrator sets the guardrails the rest of the team works inside.',
    how: [
      { key: 'howto.governance.how.1', default: 'Open the Permissions tab to set what each role is allowed to do across modules.' },
      { key: 'howto.governance.how.2', default: 'Use the Approval Routes tab to define who must approve a given step before it can proceed.' },
      { key: 'howto.governance.how.3', default: 'Set up data checks under the Validation Rules tab so submissions are caught before they cause problems.' },
    ],
    tips: [
      { key: 'howto.governance.tip.1', default: 'Each tab is deep-linkable, so you can bookmark or share a direct link to the exact rule set you are configuring.' },
    ],
    whenKey: 'howto.governance.when',
    whenDefault: 'Configure these once the team is set up, and revisit when your sign-off process or policies change.',
  },
  {
    id: 'audit-log',
    route: '/admin/audit-log',
    icon: 'ClipboardCheck',
    category: 'admin',
    keywords: 'audit trail history who did what changes diff export accountability',
    titleKey: 'howto.audit-log.title',
    titleDefault: 'Audit Log',
    summaryKey: 'howto.audit-log.summary',
    summaryDefault: 'The trail of who did what, with a before-and-after view of every change.',
    whatKey: 'howto.audit-log.what',
    whatDefault:
      'The Audit Log is a read-only timeline of every change recorded across the system - who made it, when, from where, and to what. Filter it down to a person, module, action or date range, then open any entry to see a side-by-side before-and-after of exactly what changed.',
    how: [
      { key: 'howto.audit-log.how.1', default: 'Open the log to see the most recent changes first; use the filters to narrow by user, module, action or date.' },
      { key: 'howto.audit-log.how.2', default: 'Search across the entries to find a specific change, then open an entry for its full detail.' },
      { key: 'howto.audit-log.how.3', default: 'Inspect the before-and-after view in the drawer to see precisely what a change altered.' },
      { key: 'howto.audit-log.how.4', default: 'Export the current view to CSV or JSON when you need a record outside the app.' },
    ],
    tips: [
      { key: 'howto.audit-log.tip.1', default: 'The log is read-only and access is reserved for managers and administrators, so the trail itself cannot be edited.' },
    ],
    whenKey: 'howto.audit-log.when',
    whenDefault: 'Turn to it to answer "who changed this and when", or to produce an accountability record for a review.',
  },
];
