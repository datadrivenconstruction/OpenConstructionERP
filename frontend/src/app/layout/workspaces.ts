// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Workspaces: what Simple mode shows for a company profile that has one.
//
// Simple mode used to mean one thing for everybody: hide every group flagged
// `hideInSimple` and every row flagged `advancedOnly`. That hid the screens a
// general contractor lives in (subcontractors, change orders, finance,
// schedule, closeout) and kept screens they never open (FX, geo, point cloud,
// e-invoice clearance). A workspace replaces that rule for one profile: the
// sidebar shows exactly these rows, in this order, and puts every other screen
// under "More modules". A profile without an entry here keeps Simple mode as
// it was.
//
// Why this lives in the frontend and not in `onboarding_presets.py`. What has
// to survive a reload and follow the user to another browser is the choice of
// profile, and the server already keeps that (`metadata.onboarding.company_type`,
// read back through `GET /v1/users/me/onboarding/`, see
// `useCompanyWorkspace.ts`). The rows themselves are routes, tab ids, label
// keys and icons, which exist only in this bundle. A copy in Python would need
// a cross-language mirror test to stay honest, and the module list that works
// that way has already drifted three ways. Here the guard test imports the
// menu catalogue directly (`workspaces.test.ts`).
//
// A row is either a menu row (`to` equals a `navCatalog.ts` row, which it
// inherits label, icon and gates from) or a tab of a screen that has a menu
// row (`to` is `<row>?tab=<id>` and it names its own label). A tab row reuses
// the tab's own label key, so the menu says what the page will say, and the
// word is already translated wherever the tab is. The page goes in
// `PAGE_TABS` below with its tab list and default tab, which is how plain
// `/finance` lights the Budgets row.
//
// Adding a workspace for another profile: add an entry keyed by its preset key
// from `backend/app/core/onboarding_presets.py`. Nothing else changes.

import type { LucideIcon } from 'lucide-react';
import { Banknote, FileText, Lock, PiggyBank, Receipt } from 'lucide-react';
import { CONTRACTS_TABS, DEFAULT_CONTRACTS_TAB } from '@/features/contracts/contractsTabs';
import { DEFAULT_FINANCE_TAB, FINANCE_TABS } from '@/features/finance/financeTabs';
import { navGroups, type NavItem } from './navCatalog';

export interface WorkspaceRow {
  /** A menu row's route, or `<menu row route>?tab=<tab id>`. */
  to: string;
  /** Required for a tab row, optional for a menu row (which has its own). */
  labelKey?: string;
  defaultLabel?: string;
  /** Required for a tab row, optional for a menu row. */
  icon?: LucideIcon;
}

/** A run of rows under one small heading. A long workspace is read by its
 *  headings, the way a contractor names the parts of the job; a short one is
 *  a plain list and has none. */
export interface WorkspaceSection {
  /** Heading over the rows. */
  labelKey: string;
  defaultLabel: string;
  /** Stable id, for the test hook and the React key. */
  id: string;
  rows: readonly WorkspaceRow[];
}

export interface Workspace {
  /** Header over the rows. The profile's own name, already translated. */
  labelKey: string;
  defaultLabel: string;
  /** The company preset key this workspace belongs to. */
  presetKey: string;
  /** Every row, in menu order. For a workspace with sections this is the
   *  basics followed by each section's rows (see `sectioned`). */
  rows: readonly WorkspaceRow[];
  /** The headings, when the workspace has them. Their rows are the tail of
   *  `rows`, in the same order. */
  sections?: readonly WorkspaceSection[];
  /** Menu rows this kind of company has no use for. They are left out from
   *  under "More modules" while the workspace is on screen, which is the only
   *  thing that takes a row off the menu for a module nobody can switch off.
   *  Nothing is disabled: search, a link and Advanced mode still reach the
   *  screen, and Edit menu still lists the row. */
  notForProfile?: readonly string[];
}

/** The rows every workspace opens with. Settings, Users, Edit menu and About
 *  are not here because they live in the admin grid at the foot of the
 *  sidebar, which no mode or workspace changes; search and pinned rows sit
 *  above the menu and are untouched as well. */
export const WORKSPACE_BASICS: readonly WorkspaceRow[] = [{ to: '/' }, { to: '/inbox' }];

const GENERAL_CONTRACTOR: Workspace = {
  // Label first: `check_i18n_computed_keys.py` pairs each default with a
  // `*Key` field by source order, and `presetKey` is not an i18n key.
  labelKey: 'onboarding.company_general_contractor',
  defaultLabel: 'General Contractor',
  presetKey: 'general_contractor',
  // The monthly billing cycle, in the order the month runs: the job and its
  // estimate, the budget, the owner contract, the subcontracts, the changes,
  // the pay application, the money in and the money held back, then the
  // schedule and the site records that close the job.
  //
  // Two screens of the cycle are missing on purpose. Lien waivers and
  // insurance certificates are per firm: they sit at the foot of the
  // subcontractor drawer, which one firm at a time opens
  // (`/subcontractors?sub=<id>`), below its tabs rather than behind one of
  // them, so there is no address that shows them across firms and a menu row
  // has nothing to point at until such a register exists. A lender draw has no
  // screen yet; `funding` is public grants and must not stand in for it.
  rows: [
    ...WORKSPACE_BASICS,
    { to: '/projects' },
    { to: '/boq' },
    { to: '/finance?tab=budgets', labelKey: 'finance.budgets', defaultLabel: 'Budgets', icon: PiggyBank },
    { to: '/contracts' },
    { to: '/subcontractors' },
    { to: '/changeorders' },
    {
      to: '/contracts?tab=claims',
      labelKey: 'contracts.tab_claims',
      defaultLabel: 'Progress Claims',
      icon: Receipt,
    },
    { to: '/finance?tab=payments', labelKey: 'finance.payments', defaultLabel: 'Payments', icon: Banknote },
    { to: '/finance?tab=retention', labelKey: 'finance.retention_tab', defaultLabel: 'Retention', icon: Lock },
    { to: '/schedule' },
    { to: '/daily-diary' },
    { to: '/punchlist' },
    { to: '/closeout' },
  ],
};

/** The flat row list of a workspace that is read by headings. */
function sectioned(sections: readonly WorkspaceSection[]): readonly WorkspaceRow[] {
  return [...WORKSPACE_BASICS, { to: '/projects' }, ...sections.flatMap((section) => section.rows)];
}

// What a mechanical, electrical and plumbing contractor opens, under the
// headings such a contractor files the work by. Not the general contractor's
// billing cycle: an installer is usually the party below, so the weight is on
// the records it has to be able to prove (diary, letters, RFIs), on getting
// material and drawings approved before anything is bought, and on being paid
// for change.
//
// Where several screens overlap, one is here and the others stay under "More
// modules". The diary is the signed daily diary, not the second daily report.
// Change is Variations (notice, request, order, daywork, extension of time),
// which is how the party below is paid for it; the budget-side change order
// is the general contractor's row. Quality is the screen that holds
// inspection requests, hold points, material and test records, with the
// plain checklists left out. Buying is purchase orders and requests for
// quotation, of the five sourcing screens.
//
// Extension of time has no row of its own: it is a tab of Variations, and
// that page reads `?tab=` once, when it mounts, so a row pointing at the tab
// would do nothing when clicked from the page itself. Withholding and
// e-invoice clearance are left under "More modules" until they carry a
// Turkish regime; the tax row here is the rate table, which does.
const MEP_SECTIONS: readonly WorkspaceSection[] = [
  {
    labelKey: 'workspace.section.site_records',
    defaultLabel: 'Site records',
    id: 'site_records',
    rows: [
      { to: '/daily-diary' },
      { to: '/correspondence' },
      { to: '/rfi' },
      { to: '/meetings' },
      { to: '/schedule' },
      { to: '/field-time' },
      { to: '/contacts' },
    ],
  },
  {
    labelKey: 'workspace.section.engineering',
    defaultLabel: 'Engineering and approvals',
    id: 'engineering',
    rows: [{ to: '/submittals' }, { to: '/transmittals' }, { to: '/sheets' }, { to: '/files' }],
  },
  {
    labelKey: 'workspace.section.procurement',
    defaultLabel: 'Procurement and logistics',
    id: 'procurement',
    rows: [{ to: '/procurement' }, { to: '/rfq-bidding' }, { to: '/site-logistics' }],
  },
  {
    labelKey: 'workspace.section.commercial',
    defaultLabel: 'Commercial',
    id: 'commercial',
    // Contract, the firms below, what was measured, the claim for it, the
    // change, then the invoice, the money and the tax on it.
    rows: [
      { to: '/contracts' },
      { to: '/subcontractors' },
      { to: '/progress' },
      {
        to: '/contracts?tab=claims',
        labelKey: 'contracts.tab_claims',
        defaultLabel: 'Progress Claims',
        icon: Receipt,
      },
      { to: '/variations' },
      { to: '/finance?tab=invoices', labelKey: 'finance.invoices', defaultLabel: 'Invoices', icon: FileText },
      { to: '/finance?tab=payments', labelKey: 'finance.payments', defaultLabel: 'Payments', icon: Banknote },
      { to: '/tax-rates' },
    ],
  },
  {
    labelKey: 'workspace.section.estimating',
    defaultLabel: 'Cost and estimating',
    id: 'estimating',
    rows: [{ to: '/boq' }, { to: '/quantities' }],
  },
  {
    labelKey: 'workspace.section.quality',
    defaultLabel: 'Quality, testing and commissioning',
    id: 'quality',
    rows: [{ to: '/construction-control' }, { to: '/ncr' }, { to: '/punchlist' }, { to: '/commissioning' }],
  },
  {
    labelKey: 'workspace.section.hse',
    defaultLabel: 'Health and safety',
    id: 'hse',
    rows: [{ to: '/safety' }, { to: '/hse-advanced' }],
  },
  {
    labelKey: 'workspace.section.handover',
    defaultLabel: 'Handover',
    id: 'handover',
    rows: [{ to: '/closeout' }, { to: '/defects-liability' }],
  },
];

const MEP_CONTRACTOR: Workspace = {
  labelKey: 'onboarding.company_mep_contractor',
  defaultLabel: 'MEP / Building Services Contractor',
  presetKey: 'mep_contractor',
  rows: sectioned(MEP_SECTIONS),
  sections: MEP_SECTIONS,
  // Screens for another trade, for the client's or the designer's side, for a
  // developer who sells units, for a public authority, and the tools that
  // build the platform itself.
  notForProfile: [
    '/formwork',
    '/rebar-schedule',
    '/temporary-works',
    '/rom-estimate',
    '/design-options',
    '/property-dev',
    '/property-dev/dashboards',
    '/property-dev/settings/house-types',
    '/property-dev/settings/document-templates',
    '/funding',
    '/payment-clock',
    '/certified-payroll',
    '/carbon',
    '/value',
    '/authority-submissions',
    '/review-authority',
    '/site-supervision',
    '/source-data',
    '/project-route',
    '/geo',
    '/pointcloud',
    '/dashboards',
    '/compliance/builder',
    '/ai-agents',
    '/pipelines',
    '/module-builder',
    '/architecture',
  ],
};

// The registers one person keeps on a site, on any kind of contractor: the
// diary, the letters, the questions, the approvals and the changes, then
// where the files and the people are. A job profile, so it is the choice of
// the person who keeps them and not of the firm; it is also what a company
// starts a pilot on. Short enough to need no headings.
const SITE_RECORDS: Workspace = {
  labelKey: 'onboarding.company_site_records',
  defaultLabel: 'Site Records / Document Control',
  presetKey: 'site_records',
  rows: [
    ...WORKSPACE_BASICS,
    { to: '/projects' },
    { to: '/daily-diary' },
    { to: '/correspondence' },
    { to: '/rfi' },
    { to: '/submittals' },
    { to: '/variations' },
    { to: '/files' },
    { to: '/contacts' },
  ],
};

/** Every workspace, keyed by company preset key. */
export const PRESET_WORKSPACES: Readonly<Record<string, Workspace>> = {
  general_contractor: GENERAL_CONTRACTOR,
  mep_contractor: MEP_CONTRACTOR,
  site_records: SITE_RECORDS,
};

/** The profile whose menu a user sees: their own choice, and until they have
 *  made one, the profile the installation's pack names
 *  (`default_company_profile` in the pack manifest).
 *
 *  That second half is how a company's choice reaches the people who never
 *  run a setup wizard. The admin installs one pack, and everybody who signs
 *  in afterwards opens on its profile's workspace without anything being
 *  written to their account, so the day they pick a profile of their own it
 *  simply wins. A pack default the menu has no workspace for is still
 *  returned: the caller decides what a profile without a workspace means. */
export function effectiveCompanyPresetKey(
  ownKey: string | null | undefined,
  packDefault: string | null | undefined,
): string | null {
  return ownKey || packDefault || null;
}

/** Which section each of a workspace's rows opens, by route: the heading is
 *  drawn above the first row of a section that is on screen. Empty for a
 *  workspace without sections. */
export function workspaceSectionByRoute(workspace: Workspace): ReadonlyMap<string, WorkspaceSection> {
  const byRoute = new Map<string, WorkspaceSection>();
  for (const section of workspace.sections ?? []) {
    for (const row of section.rows) byRoute.set(row.to, section);
  }
  return byRoute;
}

/** The workspace for a preset key, or null when the profile has none (Simple
 *  mode then behaves as it always has). */
export function workspaceFor(presetKey: string | null | undefined): Workspace | null {
  if (!presetKey) return null;
  return Object.prototype.hasOwnProperty.call(PRESET_WORKSPACES, presetKey)
    ? PRESET_WORKSPACES[presetKey]!
    : null;
}

/** Menu rows by route, the lookup a workspace row resolves against. */
export const NAV_ITEM_BY_ROUTE: ReadonlyMap<string, NavItem> = new Map(
  navGroups.flatMap((group) => group.items.map((item) => [item.to, item] as const)),
);

/** Turn one workspace row into the NavItem the sidebar draws, or null when it
 *  names no menu row (the guard test keeps that from shipping).
 *
 *  A menu row comes back as that row, so its module gate, admin gate and tour
 *  hook still apply. A tab row inherits only the gates of the screen it opens:
 *  switching Finance off hides Budgets, Payments and Retention with it. */
export function resolveWorkspaceRow(row: WorkspaceRow): NavItem | null {
  const exact = NAV_ITEM_BY_ROUTE.get(row.to);
  if (exact) {
    return {
      ...exact,
      ...(row.labelKey ? { labelKey: row.labelKey, defaultLabel: row.defaultLabel } : {}),
      ...(row.icon ? { icon: row.icon } : {}),
    };
  }
  const page = NAV_ITEM_BY_ROUTE.get(row.to.split('?')[0]!);
  if (!page || !row.labelKey || !row.icon) return null;
  return {
    labelKey: row.labelKey,
    defaultLabel: row.defaultLabel,
    to: row.to,
    icon: row.icon,
    moduleKey: page.moduleKey,
    roleGate: page.roleGate,
    adminOnly: page.adminOnly,
  };
}

/** The workspace's rows as NavItems, in order, unresolvable rows dropped. */
export function resolveWorkspace(workspace: Workspace): NavItem[] {
  return workspace.rows
    .map(resolveWorkspaceRow)
    .filter((item): item is NavItem => item !== null);
}

/** The tabs of each page a tab row opens, and the tab the page shows when the
 *  address names none or names one it does not have. Both come from the
 *  page's own list, so the sidebar agrees with what the page draws. */
export const PAGE_TABS: ReadonlyMap<string, { tabs: readonly string[]; defaultTab: string }> = new Map([
  ['/contracts', { tabs: CONTRACTS_TABS, defaultTab: DEFAULT_CONTRACTS_TAB }],
  ['/finance', { tabs: FINANCE_TABS, defaultTab: DEFAULT_FINANCE_TAB }],
]);

/** The tab a page shows for this address, which is what the sidebar should
 *  light: plain `/finance` shows Budgets, so it lights the Budgets row, not
 *  the Finance row under "More modules". A page outside `PAGE_TABS` gets the
 *  `?tab=` value as written. */
export function shownTab(pathname: string, params: URLSearchParams): string | null {
  const tab = params.get('tab');
  const page = PAGE_TABS.get(pathname);
  if (!page) return tab;
  return tab !== null && page.tabs.includes(tab) ? tab : page.defaultTab;
}
