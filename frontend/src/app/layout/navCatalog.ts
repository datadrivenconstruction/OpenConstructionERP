// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The app's screen catalogue: every route the sidebar exposes, its label key,
// its icon and the group it belongs to.
//
// This lived inside Sidebar.tsx, which made it private to the component that
// happened to render it first. It is not sidebar data, it is the list of
// screens the product has, and three surfaces need it: the sidebar, the
// route-to-icon map, and the case editor's screen picker. A list restated in
// three places drifts in three directions, so it lives here and they import
// it.
//
// Adding a screen: add it to exactly one group. Every consumer picks it up.

import type { LucideIcon } from 'lucide-react';

import {
  Bookmark,
  GitCompare,
  LayoutDashboard,
  FolderOpen,
  Table2,
  CalendarDays,
  Database,
  Bot,
  Layers,
  Boxes,
  Compass,
  Box,
  ShieldCheck,
  FileText,
  FileBarChart,
  Package,
  TrendingUp,
  Activity,
  Phone,
  Ruler,
  Scissors,
  Sparkles,
  MessageSquare,
  FileEdit,
  Replace,
  ShieldAlert,
  ClipboardCheck,
  ClipboardList,
  PenTool,
  PencilRuler,
  ListChecks,
  Camera,
  ScanLine,
  TableProperties,
  Wallet,
  HardHat,
  Users,
  HelpCircle,
  Route,
  AlertOctagon,
  CircleDot,
  FileCheck,
  Mail,
  Send,
  BrainCircuit,
  SlidersHorizontal,
  FileSearch,
  HardDrive,
  Mailbox,
  Inbox,
  Link2,
  Timer,
  Truck,
  Factory,
  BookOpen,
  Globe,
  Globe2,
  FileSignature,
  Briefcase,
  Scale,
  Percent,
  Landmark,
  Stamp,
  GitBranch,
  Building2,
  ShoppingCart,
  BadgeCheck,
  Shield,
  Leaf,
  BarChart3,
  LineChart,
  Radar,
  Network,
  CalendarRange,
  Gauge,
  Wand2,
  PackageCheck,
  PackageOpen,
  ScanEye,
  AlarmClock,
  Warehouse,
  Construction,
  Handshake,
  FileWarning,
  Flag,
  Wrench,
  MonitorPlay,
  GraduationCap,
  KeyRound,
} from 'lucide-react';


export interface NavItem {
  labelKey: string;
  /** Human English fallback shown until the `labelKey` locale string is
   *  added, passed to i18next as `defaultValue` so the row never renders a
   *  raw key (mirrors `NavGroup.defaultLabel`). */
  defaultLabel?: string;
  to: string;
  icon: LucideIcon;
  badge?: string;
  highlight?: boolean;
  moduleKey?: string;
  advancedOnly?: boolean; // Hidden in simple mode
  tourId?: string; // data-tour attribute for onboarding
  /** Optional "when to use this" one-liner. Surfaced in the row's hover
   *  tooltip after the label so look-alike modules (the three procurement
   *  flows, see #280) are easy to tell apart at a glance. `defaultHelp` is
   *  the English fallback shown until the `helpKey` lands in every locale. */
  helpKey?: string;
  defaultHelp?: string;
  /** Optional role gate — hide the entry unless the JWT role matches.
   *  Used for admin-only items like the Audit Log (`audit.view`
   *  permission, MANAGER+ on the backend). */
  roleGate?: ('admin' | 'manager' | 'editor' | 'viewer')[];
  /** Hide entirely unless the current JWT role is `admin`. Distinct
   *  from `roleGate` (which is a multi-role allow-list) — `adminOnly`
   *  is the simple "developer / internal tool" gate matched to the
   *  `<AdminOnly>` route wrapper in App.tsx. Used for surfaces like
   *  the Architecture Map that should never appear in a customer's
   *  sidebar. */
  adminOnly?: boolean;
}

export interface NavGroup {
  id: string;
  labelKey: string;
  /** Human English fallback shown until the `labelKey` locale string is
   *  added (the locale keys for the v6.10.0 group labels are wired in a
   *  later i18n pass). Passed to i18next as `defaultValue` so the header
   *  never renders a raw key. */
  defaultLabel?: string;
  descriptionKey?: string;
  /** English fallback for `descriptionKey`, shown as a small note under the
   *  group header until the locale string is added (mirrors `defaultLabel`).
   *  Used by the Procurement group to explain which sourcing flow to pick. */
  defaultDescription?: string;
  items: NavItem[];
  defaultOpen: boolean;
  hideInSimple?: boolean; // Entire group hidden in simple mode
  /** Render a thin horizontal divider above this group. No group uses it now. */
  separator?: boolean;
  /** Registry key used to pull dynamic module nav items into this group,
   *  when it differs from `id`: `getModuleNavItems(group.dynamicGroupKey ?? group.id)`.
   *  `grp_coordination` keeps the `reality` key of the spatial rows it holds. */
  dynamicGroupKey?: string;
  /** Captions over runs of `items`; see `NavSection`. */
  sections?: readonly NavSection[];
}

/** A run of rows under a small caption inside a group. The group keeps the
 *  flat `items` list every consumer reads; `sections` only adds the captions. */
export interface NavSection {
  id: string;
  labelKey: string;
  defaultLabel: string;
  /** Routes of the section's rows, in menu order. */
  routes: readonly string[];
}

/** The Learn group's id: the sidebar draws it apart from the loop and stores
 *  its hidden state under this key in `hiddenGroups`. */
export const LEARN_GROUP_ID = 'grp_learn';

/** The Assistant group's id: drawn as one entry under search, never as a
 *  section, so nobody has to build a group of their own to find the chat. */
export const ASSISTANT_GROUP_ID = 'grp_assistant';

interface SectionSpec {
  id: string;
  labelKey: string;
  defaultLabel: string;
  items: NavItem[];
}

function withSections(group: Omit<NavGroup, 'items' | 'sections'>, sections: SectionSpec[]): NavGroup {
  return {
    ...group,
    items: sections.flatMap((section) => section.items),
    sections: sections.map(({ items, ...section }) => ({ ...section, routes: items.map((item) => item.to) })),
  };
}

// Navigation groups, in the order a job runs: win and price it, buy and plan
// it, build and check it, pay for it, keep its records. Every route lives in
// exactly one group; long groups are read by their section captions.
//
// Ids are stable storage keys (collapsed state, hidden sections, demo
// profiles, ZIP module `ui.group`). A group that was folded into another
// keeps working through `NAV_GROUP_ALIASES` below.
//
// Rows that moved from a group hidden in Simple mode into one that is not
// carry `advancedOnly`, so a regrouping never changes who sees a row.
export const navGroups: NavGroup[] = [
  // Videos, courses, cases and packs: drawn as its own card above everything.
  {
    id: LEARN_GROUP_ID,
    labelKey: 'sidebar.group.learn',
    defaultLabel: 'Learn',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.videos', defaultLabel: 'Video guides', to: '/videos', icon: MonitorPlay },
      { labelKey: 'nav.courses', defaultLabel: 'Courses and guides', to: '/courses', icon: GraduationCap },
      { labelKey: 'nav.cases', to: '/cases', icon: Route },
      { labelKey: 'nav.packs', defaultLabel: 'Packs', to: '/packs', icon: PackageOpen },
    ],
  },
  {
    id: ASSISTANT_GROUP_ID,
    labelKey: 'sidebar.group.assistant',
    defaultLabel: 'Assistant',
    defaultOpen: true,
    items: [{ labelKey: 'nav.erp_chat', to: '/chat', icon: Sparkles }],
  },
  {
    id: 'grp_overview',
    labelKey: 'sidebar.group.overview',
    defaultLabel: 'Overview',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.dashboard', to: '/', icon: LayoutDashboard },
      { labelKey: 'projects.title', to: '/projects', icon: FolderOpen, tourId: 'projects' },
      // Documents stays here by founder ruling, visible in Simple mode.
      { labelKey: 'nav.documents', to: '/files', icon: HardDrive },
      { labelKey: 'nav.inbox', defaultLabel: 'Inbox', to: '/inbox', icon: Inbox },
      { labelKey: 'nav.timeline', defaultLabel: 'Timeline', to: '/timeline', icon: Activity },
      { labelKey: 'tasks.title', to: '/tasks', icon: ClipboardList, advancedOnly: true },
    ],
  },
  withSections(
    { id: 'grp_estimating', labelKey: 'sidebar.group.estimating', defaultLabel: 'Estimating', defaultOpen: true },
    [
      {
        id: 'takeoff',
        labelKey: 'sidebar.group.takeoff',
        defaultLabel: 'Takeoff',
        items: [
          { labelKey: 'nav.pdf_measurements', to: '/takeoff?tab=measurements', icon: Ruler },
          { labelKey: 'nav.dwg_takeoff', to: '/dwg-takeoff', icon: PencilRuler },
          { labelKey: 'nav.bim_viewer', to: '/bim', icon: Box },
          { labelKey: 'nav.quantity_rules', defaultLabel: 'Quantity Rules', to: '/bim/rules', icon: SlidersHorizontal },
          { labelKey: 'nav.quantities', to: '/quantities', icon: Ruler },
          { labelKey: 'nav.rebar_schedule', defaultLabel: 'Rebar Schedule', to: '/rebar-schedule', icon: Construction, advancedOnly: true },
        ],
      },
      {
        id: 'boq',
        labelKey: 'sidebar.section.boq',
        defaultLabel: 'Bill of quantities',
        items: [
          { labelKey: 'boq.title', to: '/boq', icon: Table2, tourId: 'boq' },
          { labelKey: 'nav.boq_templates', to: '/templates', icon: FileText },
          {
            // Keep each key directly above its own default: the computed-key
            // gate pairs them by source order, and `moduleKey` is not an i18n key.
            labelKey: 'nav.exchange_hub',
            defaultLabel: 'Import / Export',
            helpKey: 'nav.exchange_hub_help',
            defaultHelp: "Move a bill of quantities in or out in your market's own format",
            to: '/regional-exchange',
            icon: Globe2,
            moduleKey: 'regional-exchange',
          },
          { labelKey: 'nav.match_elements', to: '/match-elements', icon: Link2, badge: 'BETA' },
          { labelKey: 'nav.estimation_dashboard', to: '/project-intelligence', icon: BrainCircuit },
          { labelKey: 'nav.rom_estimate', to: '/rom-estimate', icon: Gauge },
          { labelKey: 'nav.methodologies', to: '/methodologies', icon: SlidersHorizontal, moduleKey: 'methodology' },
          { labelKey: 'nav.estimate_basis', to: '/estimate-basis', icon: FileText, advancedOnly: true },
          { labelKey: 'nav.preliminaries', to: '/preliminaries', icon: ClipboardList, advancedOnly: true },
          { labelKey: 'nav.allowances', to: '/allowances', icon: Wallet, advancedOnly: true },
          { labelKey: 'nav.design_options', to: '/design-options', icon: Scale, advancedOnly: true },
          { labelKey: 'formwork.title', to: '/formwork', icon: Boxes, advancedOnly: true, defaultLabel: 'Formwork' },
        ],
      },
      {
        id: 'ai_drafting',
        labelKey: 'sidebar.section.ai_drafting',
        defaultLabel: 'AI drafting',
        items: [
          { labelKey: 'nav.ai_estimate', to: '/ai-estimate', icon: Sparkles, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.ai_estimator', to: '/ai-estimator', icon: Wand2, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.estimate_copilot', to: '/estimate-copilot', icon: Bot, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.ai_advisor', to: '/advisor', icon: MessageSquare, advancedOnly: true },
        ],
      },
      {
        id: 'bids',
        labelKey: 'sidebar.section.bids',
        defaultLabel: 'Bids and clients',
        items: [
          { labelKey: 'nav.crm', to: '/crm', icon: Briefcase, advancedOnly: true },
          {
            labelKey: 'nav.win_loss',
            defaultLabel: 'Bid outcomes',
            to: '/win-loss',
            icon: Scale,
            advancedOnly: true,
            helpKey: 'sidebar.help.win_loss',
            defaultHelp: 'How each bid ended: winning price, money left on the table, hit rate by client, trade and size.',
          },
        ],
      },
    ],
  ),
  withSections(
    { id: 'grp_cost_data', labelKey: 'sidebar.group.cost_data', defaultLabel: 'Cost Data', defaultOpen: true },
    [
      {
        id: 'databases',
        labelKey: 'sidebar.section.databases',
        defaultLabel: 'Cost databases',
        items: [
          { labelKey: 'costs.title', to: '/costs', icon: Database, tourId: 'costs' },
          { labelKey: 'catalog.title', to: '/catalog', icon: Boxes },
          { labelKey: 'nav.cost_explorer', to: '/cost-explorer', icon: Compass },
          { labelKey: 'nav.assemblies', to: '/assemblies', icon: Layers },
          { labelKey: 'nav.cost_match', to: '/cost-match', icon: Link2 },
          { labelKey: 'nav.fx', to: '/fx', icon: Wallet },
          { labelKey: 'nav.benchmarks', to: '/benchmarks', icon: BarChart3, moduleKey: 'cost-benchmark', advancedOnly: true },
          { labelKey: 'nav.cost_benchmarks', to: '/cost-benchmarks', icon: BarChart3, advancedOnly: true },
        ],
      },
      {
        // Ordered as the build-up flows: norm, rate, waste, escalation, summary.
        id: 'rate_buildup',
        labelKey: 'sidebar.group.rate_buildup',
        defaultLabel: 'Rate Build-up',
        items: [
          { labelKey: 'nav.norm_expansion', to: '/norm-expansion', icon: ListChecks, advancedOnly: true },
          { labelKey: 'nav.labor_rates', to: '/labor-rates', icon: HardHat, advancedOnly: true },
          { labelKey: 'nav.waste_factors', to: '/waste-factors', icon: Ruler, advancedOnly: true },
          { labelKey: 'nav.cutting', to: '/cutting', icon: Scissors, advancedOnly: true },
          { labelKey: 'nav.price_index', to: '/price-index', icon: TrendingUp, advancedOnly: true },
          { labelKey: 'nav.resource_summary', to: '/resource-summary', icon: Package, advancedOnly: true },
        ],
      },
    ],
  ),
  // The three sourcing flows, lightest to most formal, each labelled for when
  // to use it, plus the supplier price book they draw from (#280).
  {
    id: 'grp_procurement',
    labelKey: 'sidebar.group.procurement',
    defaultLabel: 'Procurement',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      {
        labelKey: 'procurement.title',
        to: '/procurement',
        icon: Package,
        advancedOnly: true,
        helpKey: 'sidebar.help.procurement',
        defaultHelp: 'Quick vendor quotes (RFQ) through to purchase orders.',
      },
      {
        labelKey: 'nav.subcontract_packages',
        defaultLabel: 'Subcontract packages',
        to: '/bid-management',
        icon: Scale,
        helpKey: 'sidebar.help.subcontract_packages',
        defaultHelp:
          'Trade and supply packages: invite bidders, level bids with plugs, award to a subcontract or a purchase order.',
      },
      {
        labelKey: 'nav.supplier_rfq',
        defaultLabel: 'Supplier RFQ',
        to: '/rfq-bidding',
        icon: Scale,
        advancedOnly: true,
        helpKey: 'sidebar.help.supplier_rfq',
        defaultHelp: 'Ask suppliers for quotes on materials and services and award to a purchase order.',
      },
      {
        labelKey: 'nav.main_contract_tender',
        defaultLabel: 'Main contract tender',
        to: '/tendering',
        icon: FileText,
        moduleKey: 'tendering',
        advancedOnly: true,
        helpKey: 'sidebar.help.main_contract_tender',
        defaultHelp:
          'Tender the main contract from the bill of quantities; the winning rates go back into the BOQ.',
      },
      {
        labelKey: 'nav.quote_capture',
        defaultLabel: 'Quote capture',
        to: '/quotes',
        icon: FileText,
        moduleKey: 'quote_capture',
        advancedOnly: true,
        helpKey: 'sidebar.help.quote_capture',
        defaultHelp:
          'Read supplier quotes, check them against the document, level and confirm.',
      },
      {
        labelKey: 'nav.supplier_catalogs',
        to: '/supplier-catalogs',
        icon: ShoppingCart,
        helpKey: 'sidebar.help.supplier_catalogs',
        defaultHelp: 'Vendor price lists that the quotes and bids draw from.',
      },
      { labelKey: 'nav.subcontractors', to: '/subcontractors', icon: HardHat, advancedOnly: true },
    ],
  },
  // Contracts stay visible in Simple mode: a user once read a hidden group as
  // "there is no contracts module".
  withSections(
    {
      id: 'grp_commercial',
      labelKey: 'sidebar.group.contracts_change',
      defaultLabel: 'Contracts & change',
      defaultOpen: true,
    },
    [
      {
        id: 'contracts',
        labelKey: 'sidebar.section.contracts',
        defaultLabel: 'Contracts',
        items: [
          { labelKey: 'nav.contracts', to: '/contracts', icon: FileSignature },
          { labelKey: 'nav.payment_clock', to: '/payment-clock', icon: Scale },
        ],
      },
      {
        id: 'change',
        labelKey: 'sidebar.group.change',
        defaultLabel: 'Change',
        items: [
          { labelKey: 'nav.variations', to: '/variations', icon: GitBranch, advancedOnly: true },
          { labelKey: 'moc.title', to: '/moc', icon: Replace, advancedOnly: true },
          { labelKey: 'nav.change_orders', to: '/changeorders', icon: FileEdit, advancedOnly: true },
          { labelKey: 'nav.change_intelligence', to: '/change-intelligence', icon: BrainCircuit, advancedOnly: true },
          { labelKey: 'nav.claims_evidence', to: '/claims-evidence', icon: ShieldCheck, advancedOnly: true },
          { labelKey: 'nav.value', to: '/value', icon: TrendingUp, advancedOnly: true },
        ],
      },
    ],
  ),
  withSections(
    {
      id: 'grp_scheduling',
      labelKey: 'sidebar.group.plan',
      defaultLabel: 'Planning & resources',
      defaultOpen: true,
      hideInSimple: true,
    },
    [
      {
        id: 'schedule',
        labelKey: 'sidebar.group.scheduling',
        defaultLabel: 'Scheduling',
        items: [
          { labelKey: 'schedule.title', to: '/schedule', icon: CalendarDays, moduleKey: 'schedule' },
          { labelKey: 'nav.schedule_advanced', to: '/schedule-advanced', icon: LineChart, advancedOnly: true },
          { labelKey: 'nav.takt', to: '/takt', icon: GitBranch, advancedOnly: true },
          { labelKey: 'portfolio.title', to: '/portfolio', icon: Network, advancedOnly: true },
          { labelKey: 'capital_plan.title', to: '/capital-plan', icon: Wallet, advancedOnly: true },
        ],
      },
      {
        id: 'resources',
        labelKey: 'sidebar.group.resources',
        defaultLabel: 'Resources & Assets',
        items: [
          { labelKey: 'nav.resources', to: '/resources', icon: Users },
          { labelKey: 'nav.dispatch', to: '/dispatch', icon: CalendarRange },
          { labelKey: 'nav.capacity_planning', to: '/portfolio/capacity', icon: CalendarRange, advancedOnly: true },
          { labelKey: 'nav.resource_leveling', to: '/portfolio/leveling', icon: Scale, advancedOnly: true },
          { labelKey: 'nav.equipment', to: '/equipment', icon: Truck },
          { labelKey: 'nav.haul_tickets', to: '/haul-tickets', icon: Truck },
          { labelKey: 'nav.assets', to: '/assets', icon: Package },
          {
            labelKey: 'nav.credentials',
            defaultLabel: 'Credentials',
            to: '/credentials',
            icon: BadgeCheck,
            advancedOnly: true,
          },
          { labelKey: 'nav.prefab', to: '/prefab', icon: Factory, advancedOnly: true },
        ],
      },
    ],
  ),
  // The day on site. /portal/payments is left out on purpose: it is the
  // magic-link surface subcontractors reach from their invitation email.
  {
    id: 'grp_site',
    labelKey: 'sidebar.group.site',
    defaultLabel: 'Site',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.daily_diary', to: '/daily-diary', icon: BookOpen },
      { labelKey: 'nav.photos', to: '/photos', icon: Camera },
      { labelKey: 'nav.field_reports', to: '/field-reports', icon: ClipboardList, advancedOnly: true },
      { labelKey: 'nav.field_time', to: '/field-time', icon: Timer, advancedOnly: true },
      { labelKey: 'site_prep.title', to: '/site-prep', icon: Flag },
      { labelKey: 'nav.site_logistics', to: '/site-logistics', icon: Truck },
      { labelKey: 'site_inventory.title', to: '/site-inventory', icon: Warehouse },
      { labelKey: 'site_supervision.title', to: '/site-supervision', icon: HardHat, advancedOnly: true },
      { labelKey: 'nav.site_sensors', to: '/site-sensors', icon: Gauge, advancedOnly: true },
      { labelKey: 'nav.service', to: '/service', icon: Wrench },
      { labelKey: 'nav.portal', to: '/portal', icon: Globe },
    ],
  },
  withSections(
    {
      id: 'grp_quality',
      labelKey: 'sidebar.group.quality_safety',
      defaultLabel: 'Quality & safety',
      defaultOpen: true,
      hideInSimple: true,
    },
    [
      {
        id: 'quality',
        labelKey: 'sidebar.group.quality',
        defaultLabel: 'Quality',
        items: [
          { labelKey: 'nav.issues', to: '/issues', icon: CircleDot },
          { labelKey: 'validation.title', to: '/validation', icon: ShieldCheck, moduleKey: 'validation' },
          // The rule builder authors what Validation runs, so it sits beside it.
          { labelKey: 'nav.compliance_rule_builder', to: '/compliance/builder', icon: Wand2 },
          { labelKey: 'inspections.title', to: '/inspections', icon: ClipboardCheck },
          { labelKey: 'construction_control.title', to: '/construction-control', icon: ClipboardList },
          { labelKey: 'ncr.title', to: '/ncr', icon: AlertOctagon },
          { labelKey: 'nav.punchlist', to: '/punchlist', icon: ListChecks },
          { labelKey: 'deadlines.title', to: '/deadlines', icon: AlarmClock, defaultLabel: 'Deadlines' },
          { labelKey: 'review_authority.title', to: '/review-authority', icon: FileCheck, advancedOnly: true },
          { labelKey: 'nav.qms', to: '/qms', icon: BadgeCheck, advancedOnly: true },
        ],
      },
      {
        id: 'safety',
        labelKey: 'sidebar.section.safety',
        defaultLabel: 'Health and safety',
        items: [
          { labelKey: 'safety.title', to: '/safety', icon: HardHat },
          { labelKey: 'nav.hse_advanced', to: '/hse-advanced', icon: Shield, advancedOnly: true },
          { labelKey: 'temporary_works.title', to: '/temporary-works', icon: Construction },
        ],
      },
      {
        id: 'handover',
        labelKey: 'sidebar.group.handover',
        defaultLabel: 'Handover & Commissioning',
        items: [
          { labelKey: 'nav.commissioning', to: '/commissioning', icon: ClipboardCheck },
          { labelKey: 'closeout.title', to: '/closeout', icon: PackageCheck },
          { labelKey: 'defects_liability.title', to: '/defects-liability', icon: FileWarning },
          { labelKey: 'guarantees.title', to: '/portfolio/guarantees/register', icon: Landmark },
          { labelKey: 'condition.title', to: '/condition', icon: Gauge },
          { labelKey: 'nav.forms', to: '/forms', icon: ClipboardList },
        ],
      },
    ],
  ),
  // Tax, withholding and e-invoice rows stay visible in Simple mode, as they
  // were under Commercial; the cost-control rows keep their Advanced audience.
  withSections(
    { id: 'grp_finance', labelKey: 'sidebar.group.cost_finance', defaultLabel: 'Cost control & finance', defaultOpen: true },
    [
      {
        id: 'cost_control',
        labelKey: 'sidebar.group.cost_control',
        defaultLabel: 'Cost Control & Risk',
        items: [
          { labelKey: 'nav.cost_control', to: '/cost-control', icon: Scale, moduleKey: '5d', advancedOnly: true },
          { labelKey: 'nav.5d_cost_model', to: '/5d', icon: TrendingUp, moduleKey: '5d', advancedOnly: true },
          { labelKey: 'nav.progress', to: '/progress', icon: Activity, advancedOnly: true },
          { labelKey: 'nav.measurement_book', to: '/measurement-book', icon: Ruler, advancedOnly: true },
          { labelKey: 'nav.full_evm', to: '/full-evm', icon: LineChart, advancedOnly: true },
          { labelKey: 'nav.risk_register', to: '/risks', icon: ShieldAlert, advancedOnly: true },
          { labelKey: 'nav.cvr', to: '/cvr', icon: Scale, advancedOnly: true },
          { labelKey: 'wip_report.title', to: '/portfolio/wip', icon: FileBarChart, advancedOnly: true },
          { labelKey: 'postcalc.title', to: '/postcalc', icon: Gauge, advancedOnly: true },
        ],
      },
      {
        id: 'accounts',
        labelKey: 'sidebar.section.accounts',
        defaultLabel: 'Accounts and tax',
        items: [
          { labelKey: 'finance.title', to: '/finance', icon: Wallet, advancedOnly: true },
          {
            labelKey: 'funding.title',
            to: '/funding',
            icon: Landmark,
            moduleKey: 'funding',
            advancedOnly: true,
            helpKey: 'sidebar.help.funding',
            defaultHelp:
              'Grants and subsidies: what was awarded, what has been drawn, and every deadline that follows.',
          },
          { labelKey: 'accountingSync.title', to: '/accounting-sync', icon: BookOpen, advancedOnly: true },
          { labelKey: 'nav.payroll', to: '/payroll', icon: Wallet, advancedOnly: true },
          // The weekly payroll a public works contract is certified with.
          { labelKey: 'nav.certified_payroll', to: '/certified-payroll', icon: FileCheck, advancedOnly: true },
          { labelKey: 'nav.tax_withholding', to: '/tax-withholding', icon: Percent },
          { labelKey: 'nav.tax_rates', to: '/tax-rates', icon: Landmark },
          { labelKey: 'nav.einvoice_clearance', to: '/einvoice-clearance', icon: Stamp },
          { labelKey: 'nav.legal_entities', to: '/admin/legal-entities', icon: Building2, advancedOnly: true },
        ],
      },
    ],
  ),
  // Drawings stay visible in Simple mode, as they were; the outgoing paperwork
  // and the communication registers keep their Advanced audience.
  withSections(
    { id: 'grp_documents', labelKey: 'sidebar.group.documents', defaultLabel: 'Documents', defaultOpen: true },
    [
      {
        id: 'drawings',
        labelKey: 'sidebar.group.drawings',
        defaultLabel: 'Drawings & Files',
        items: [
          { labelKey: 'sheets.page_title', to: '/sheets', icon: FileText },
          { labelKey: 'nav.plan_room', to: '/plan-room', icon: Layers, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.drawing_compare', to: '/drawing-compare', icon: GitCompare, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.markups', to: '/markups', icon: PenTool, advancedOnly: true },
          { labelKey: 'cde.title', to: '/cde', icon: Database, advancedOnly: true },
          { labelKey: 'source_data.title', to: '/source-data', icon: Database, advancedOnly: true },
        ],
      },
      {
        id: 'outgoing',
        labelKey: 'sidebar.section.outgoing',
        defaultLabel: 'Submittals and signing',
        items: [
          { labelKey: 'submittals.title', to: '/submittals', icon: FileCheck, advancedOnly: true },
          { labelKey: 'transmittals.title', to: '/transmittals', icon: Send, advancedOnly: true },
          { labelKey: 'signing.title', to: '/signing', icon: PenTool, advancedOnly: true },
        ],
      },
      {
        id: 'communication',
        labelKey: 'sidebar.group.communication',
        defaultLabel: 'Communication',
        items: [
          { labelKey: 'contacts.title', to: '/contacts', icon: Users, advancedOnly: true },
          // Teams is the access side of "who is on this project".
          {
            labelKey: 'teams.title',
            defaultLabel: 'Teams and visibility',
            to: '/teams',
            icon: ShieldCheck,
            advancedOnly: true,
          },
          { labelKey: 'meetings.title', to: '/meetings', icon: CalendarDays, advancedOnly: true },
          { labelKey: 'rfi.title', to: '/rfi', icon: HelpCircle, advancedOnly: true },
          { labelKey: 'correspondence.title', to: '/correspondence', icon: Mail, advancedOnly: true },
          { labelKey: 'interface_management.title', to: '/interface-management', icon: Handshake, advancedOnly: true },
          { labelKey: 'authority_submission.title', to: '/authority-submissions', icon: Send, advancedOnly: true },
          { labelKey: 'nav.collaboration', to: '/collaboration', icon: Users, moduleKey: 'collaboration', advancedOnly: true },
          { labelKey: 'nav.phone_log', to: '/phone-log', icon: Phone, advancedOnly: true },
        ],
      },
    ],
  ),
  // Geo and point cloud stay visible in Simple mode, as they were; model
  // coordination, reports and ESG keep their Advanced audience.
  // `dynamicGroupKey: 'reality'` is the registry key a manifest can publish
  // spatial rows under.
  withSections(
    {
      id: 'grp_coordination',
      labelKey: 'sidebar.group.bim_data',
      defaultLabel: 'BIM, data & reports',
      dynamicGroupKey: 'reality',
      defaultOpen: true,
    },
    [
      {
        id: 'models',
        labelKey: 'sidebar.group.coordination',
        defaultLabel: 'Model Coordination',
        items: [
          { labelKey: 'nav.coordination_hub', to: '/coordination', icon: LayoutDashboard, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.model_review', to: '/model-review', icon: ScanEye, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.bim_federations', to: '/bim/federations', icon: Layers, advancedOnly: true },
          { labelKey: 'nav.clash_detection', to: '/clash', icon: Radar, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.model_issues', to: '/bcf', icon: MessageSquare, badge: 'BETA', advancedOnly: true },
          { labelKey: 'nav.bim_rules', to: '/bim/rules?mode=requirements', icon: SlidersHorizontal, advancedOnly: true },
          { labelKey: 'nav.eir_matrix', to: '/requirements/matrix', icon: FileCheck, advancedOnly: true, badge: 'BETA' },
        ],
      },
      {
        id: 'reality',
        labelKey: 'sidebar.group.reality',
        defaultLabel: 'Reality Capture & 3D',
        items: [
          { labelKey: 'sidebar.geo_hub', to: '/geo', icon: Globe, badge: 'BETA' },
          { labelKey: 'nav.point_cloud', to: '/pointcloud', icon: ScanLine, badge: 'BETA' },
          { labelKey: 'nav.cad_bim_explorer', to: '/data-explorer', icon: TableProperties, advancedOnly: true },
        ],
      },
      {
        id: 'reports',
        labelKey: 'sidebar.group.controls_bi',
        defaultLabel: 'Controls & BI',
        items: [
          { labelKey: 'nav.reports', to: '/reports', icon: FileBarChart, advancedOnly: true },
          { labelKey: 'nav.reporting_dashboards', to: '/reporting', icon: BarChart3, advancedOnly: true },
          { labelKey: 'nav.analytics', to: '/analytics', icon: LineChart, advancedOnly: true },
          { labelKey: 'nav.project_controls', to: '/project-controls', icon: Gauge, advancedOnly: true },
          { labelKey: 'nav.bi_dashboards', to: '/bi-dashboards', icon: BarChart3, advancedOnly: true },
          { labelKey: 'nav.snapshots', to: '/dashboards', icon: TrendingUp, advancedOnly: true },
        ],
      },
      {
        id: 'esg',
        labelKey: 'sidebar.group.esg',
        defaultLabel: 'ESG & Carbon',
        items: [
          { labelKey: 'nav.carbon', to: '/carbon', icon: Leaf, advancedOnly: true },
          { labelKey: 'nav.sustainability', to: '/sustainability', icon: Leaf, moduleKey: 'sustainability', advancedOnly: true },
          { labelKey: 'nav.esg', to: '/esg', icon: Leaf, advancedOnly: true },
        ],
      },
    ],
  ),
  {
    id: 'grp_real_estate',
    labelKey: 'sidebar.group.real_estate',
    defaultLabel: 'Real Estate',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.property_dev', to: '/property-dev', icon: Building2 },
      { labelKey: 'nav.accommodation', to: '/accommodation', icon: Building2, badge: 'BETA' },
      { labelKey: 'nav.leasing', to: '/leasing', icon: KeyRound },
      { labelKey: 'nav.service_charges', to: '/service-charges', icon: Scale },
      { labelKey: 'nav.property_dev_dashboards', to: '/property-dev/dashboards', icon: BarChart3, advancedOnly: true },
      { labelKey: 'nav.property_dev_house_types', to: '/property-dev/settings/house-types', icon: Building2, advancedOnly: true },
      { labelKey: 'nav.property_dev_doc_templates', to: '/property-dev/settings/document-templates', icon: FileText, advancedOnly: true },
    ],
  },
  // Agents, automation, the inbound feeds and the platform's own tools. Last,
  // by founder request.
  withSections(
    {
      id: 'grp_automation_ai',
      labelKey: 'sidebar.group.automation_admin',
      defaultLabel: 'AI, automation & admin',
      defaultOpen: true,
      hideInSimple: true,
    },
    [
      {
        id: 'ai_agents',
        labelKey: 'sidebar.section.ai_agents',
        defaultLabel: 'AI agents',
        items: [
          { labelKey: 'nav.ai_agents', to: '/ai-agents', icon: Bot, badge: 'BETA' },
          { labelKey: 'nav.project_agents', defaultLabel: 'Project Agents', to: '/ai-agents/catalogue', icon: Bot, moduleKey: 'ai_agents', badge: 'BETA' },
          { labelKey: 'nav.doc_assistant', defaultLabel: 'Document Assistant', to: '/document-assistant', icon: MessageSquare, moduleKey: 'doc_assistant' },
        ],
      },
      {
        id: 'records',
        labelKey: 'sidebar.group.records',
        defaultLabel: 'Records & Capture',
        items: [
          { labelKey: 'nav.connectors', to: '/connectors', icon: HardDrive, advancedOnly: true },
          { labelKey: 'nav.reconciliation', to: '/reconciliation', icon: Link2, advancedOnly: true },
          { labelKey: 'nav.inbound_capture', to: '/inbound', icon: Mailbox, advancedOnly: true, adminOnly: true },
          { labelKey: 'nav.inbound_email', to: '/inbound-email', icon: Inbox, advancedOnly: true },
          { labelKey: 'nav.find_records', to: '/find', icon: FileSearch, advancedOnly: true },
          { labelKey: 'nav.saved_views', defaultLabel: 'Saved Views', to: '/saved-views', icon: Bookmark, advancedOnly: true },
        ],
      },
      {
        id: 'workflows',
        labelKey: 'sidebar.section.workflows',
        defaultLabel: 'Workflows and rules',
        items: [
          { labelKey: 'nav.workflows', defaultLabel: 'Approval Workflows', to: '/workflows', icon: ListChecks, advancedOnly: true },
          { labelKey: 'nav.pipelines', to: '/pipelines', icon: GitBranch, moduleKey: 'pipelines', advancedOnly: true, badge: 'BETA' },
          { labelKey: 'project_route.title', to: '/project-route', icon: SlidersHorizontal, advancedOnly: true },
          {
            labelKey: 'nav.governance',
            defaultLabel: 'Governance',
            helpKey: 'nav.governance_help',
            defaultHelp: 'Permissions, approval routes, and validation rule configuration',
            to: '/governance',
            icon: Scale,
          },
        ],
      },
      {
        id: 'platform',
        labelKey: 'sidebar.section.platform',
        defaultLabel: 'Platform',
        items: [
          // Readable by anyone; the page's build and remove controls are admin-only.
          { labelKey: 'nav.module_builder', to: '/module-builder', icon: Wand2, advancedOnly: true },
          { labelKey: 'nav.background_jobs', defaultLabel: 'Background Jobs', to: '/jobs', icon: Wrench, advancedOnly: true, adminOnly: true },
          { labelKey: 'nav.architecture_map', to: '/architecture', icon: GitBranch, advancedOnly: true, adminOnly: true },
        ],
      },
    ],
  ),
];

/** Group ids folded into another group, and the group that holds their rows
 *  now. Stored state, tour steps and ZIP module manifests may still name them. */
export const NAV_GROUP_ALIASES: Readonly<Record<string, string>> = {
  grp_takeoff: 'grp_estimating',
  grp_estimate_detail: 'grp_estimating',
  grp_estimating_ai: 'grp_estimating',
  grp_rate_buildup: 'grp_cost_data',
  grp_change: 'grp_commercial',
  grp_resources: 'grp_scheduling',
  grp_field: 'grp_site',
  grp_safety: 'grp_quality',
  grp_handover: 'grp_quality',
  grp_cost_control: 'grp_finance',
  grp_drawings: 'grp_documents',
  grp_communication: 'grp_documents',
  grp_reality: 'grp_coordination',
  grp_controls_bi: 'grp_coordination',
  grp_esg: 'grp_coordination',
  grp_records: 'grp_automation_ai',
  // Pre-v6.10 ids the product tour still dispatches.
  property: 'grp_real_estate',
  cad_bim_analytics: 'grp_coordination',
};

/** The current group id for any id a caller holds, old or new. */
export function canonicalGroupId(id: string): string {
  return NAV_GROUP_ALIASES[id] ?? id;
}

/** Which section caption each route of a group sits under. Empty for a group
 *  without sections. */
export function navSectionByRoute(group: NavGroup): ReadonlyMap<string, NavSection> {
  const byRoute = new Map<string, NavSection>();
  for (const section of group.sections ?? []) {
    for (const route of section.routes) byRoute.set(route, section);
  }
  return byRoute;
}
