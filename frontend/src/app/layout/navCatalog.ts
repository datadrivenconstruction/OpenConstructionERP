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
  ScanEye,
  AlarmClock,
  Warehouse,
  Construction,
  Handshake,
  FileWarning,
  Flag,
  Wrench,
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
  /** Render a thin horizontal divider above this group. This used to name
   *  Regional, Modules and Settings as the users, peeling the setup
   *  surfaces off the project work above; none of the three is a nav group
   *  any more (Settings survives as an `adminGridItems` tile).
   *  `grp_rate_buildup` is the only group carrying it now, where it opens
   *  the rate build-up run rather than a setup block. */
  separator?: boolean;
  /** Registry key used to pull dynamic module nav items into this group,
   *  when it differs from `id`. The render loop calls
   *  `getModuleNavItems(group.dynamicGroupKey ?? group.id)`. Used by
   *  `grp_reality`, whose stable internal id is `grp_reality` but whose
   *  module-injection contract is the shorter `reality` key from the
   *  point-cloud plan (`internal design note POINTCLOUD_AND_SPATIAL_PLAN`,
   *  section 4). The contract is reserved, not in use: this used to add
   *  "so `oe_pointcloud`'s manifest can add its own row", and no such
   *  frontend manifest exists — `oe_pointcloud` is backend-only. */
  dynamicGroupKey?: string;
}

// Navigation groups — collapsible thematic sections (v6.10.0 redesign).
//
// The flat / oversized menu was regrouped into 19 thematic groups of
// 3-5 routes each, collapsed by default. Every route the app exposes
// lands in exactly one group — no route is lost. The group containing
// the active route auto-expands; per-group open/closed state persists
// to localStorage (see COLLAPSED_KEY).
//
// Source-of-truth audit: every `to` here is cross-checked against both places
// a route can come from, the `App.tsx` <Route path="…"/> list and the manifests
// under `src/modules`, which `ModuleRoutes` mounts only while their module is
// enabled. Checking App.tsx alone reports the module-owned screens as broken
// links when they are not, so `navCatalog.test.ts` reads both and also asserts
// that a row whose screen only a module provides names that module in
// `moduleKey` — without it the row outlives its own route. Two routes the
// old flat menu had dropped (`/benchmarks` Cost Benchmarks, and
// `/collaboration`) are re-surfaced here, along with the module-registry
// surface that never had a sidebar home because its manifest declared a
// `tools` group that did not exist (`/sustainability`), now a static row
// with module-key gating. (`/risk-analysis` was a third such surface but
// was retired in the Monte Carlo IA merge #71 and now redirects to /risks.)
//
// Group ids are deliberately unique and do NOT reuse the old `ai` / `tools`
// ids that module manifests inject into via `getModuleNavItems(group.id)`.
// Those manifest items (pipelines, sustainability) are now listed statically
// instead, so there is no dynamic duplication. The one dynamic group kept
// verbatim is `regional` (Regional Exchange) — it still pulls its rows from
// the module registry and keeps its conditional render.
//
// Group labels use `t('sidebar.group.<slug>', { defaultValue: '<EN>' })`.
// The locale keys are added by a later pass; until then the English
// default renders. Item labelKeys reuse the existing locale strings.
export const navGroups: NavGroup[] = [
  // ── 1. OVERVIEW (always visible) ───────────────────────────────────
  // The few entry points every user touches every session.
  {
    id: 'grp_overview',
    labelKey: 'sidebar.group.overview',
    defaultLabel: 'Overview',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.dashboard', to: '/', icon: LayoutDashboard },
      { labelKey: 'projects.title', to: '/projects', icon: FolderOpen, tourId: 'projects' },
      // Cases (playbooks) - guided, cross-module worked examples. Sits in
      // Overview so the "learn by example" entry is discoverable from the top,
      // and above Project files so the "learn by example" entry is seen first.
      { labelKey: 'nav.cases', to: '/cases', icon: Route },
      // Documents is back in Overview by founder request. It carries no
      // hideInSimple and no advancedOnly, which is what keeps it reachable in
      // Simple mode; the sheet register and the drawing surfaces stay behind
      // in Drawings & Files, which now sits below Estimating.
      //
      // This module is named Documents everywhere, by founder ruling. Three
      // keys that used to name it are now unreferenced and are kept on
      // purpose: 'nav.project_files', 'files.title' and
      // 'files.approvals.mod_files'. Each carries a real translated value in
      // all 40 locales, so deleting them to satisfy an orphan sweep trades a
      // harmless unused key for a wide blast radius. Retire them only
      // together with a decision about the name itself.
      { labelKey: 'nav.documents', to: '/files', icon: HardDrive },
    ],
  },
  // ── 2. TAKEOFF ─────────────────────────────────────────────────────
  // Quantity extraction across every source: 2D drawings (quantities, PDF
  // measurements, DWG takeoff) and the 3D BIM model (BIM 3D Takeoff). Comes
  // before Estimating - you measure quantities first, then price them. The
  // pure spatial surfaces (geo, point cloud, CAD-BIM explorer) stay in the
  // "Reality Capture & 3D" group below.
  {
    id: 'grp_takeoff',
    labelKey: 'sidebar.group.takeoff',
    defaultLabel: 'Takeoff',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.pdf_measurements', to: '/takeoff?tab=measurements', icon: Ruler },
      { labelKey: 'nav.dwg_takeoff', to: '/dwg-takeoff', icon: PencilRuler },
      { labelKey: 'nav.bim_viewer', to: '/bim', icon: Box },
      { labelKey: 'nav.quantities', to: '/quantities', icon: Ruler },
    ],
  },
  // ── 3. COST DATA ───────────────────────────────────────────────────
  // Cross-project reference data: cost databases, catalogues, assemblies,
  // and the cost-benchmark surface (re-added - it was dropped before).
  // Sits ahead of Estimating for the same reason Takeoff does: the rates and
  // catalogues have to be in place before there is anything to price a
  // quantity against, so the menu reads in the order the work happens.
  {
    id: 'grp_cost_data',
    labelKey: 'sidebar.group.cost_data',
    defaultLabel: 'Cost Data',
    defaultOpen: true,
    items: [
      { labelKey: 'costs.title', to: '/costs', icon: Database, tourId: 'costs' },
      { labelKey: 'nav.cost_explorer', to: '/cost-explorer', icon: Compass },
      { labelKey: 'nav.cost_match', to: '/cost-match', icon: Link2 },
      // Dropped for this workspace: Resource Catalog and Assemblies (generic
      // construction reference data an electrical contractor never uses -
      // their seed data was removed too) and FX (this deployment is
      // single-currency AUD end to end). Routes still exist; only the
      // menu rows are gone, so nothing breaks if a link is followed.
      { labelKey: 'nav.benchmarks', to: '/benchmarks', icon: BarChart3, moduleKey: 'cost-benchmark', advancedOnly: true },
    ],
  },
  // ── 4. ESTIMATING ──────────────────────────────────────────────────
  // The project's cost work-product: BOQ, the BIM↔catalogue match, the
  // AI estimate and the estimation intelligence dashboard.
  {
    id: 'grp_estimating',
    labelKey: 'sidebar.group.estimating',
    defaultLabel: 'Estimating',
    defaultOpen: true,
    items: [
      { labelKey: 'boq.title', to: '/boq', icon: Table2, tourId: 'boq' },
      { labelKey: 'nav.match_elements', to: '/match-elements', icon: Link2, badge: 'BETA' },
      { labelKey: 'nav.estimation_dashboard', to: '/project-intelligence', icon: BrainCircuit },
      { labelKey: 'nav.rom_estimate', to: '/rom-estimate', icon: Gauge },
      { labelKey: 'nav.methodologies', to: '/methodologies', icon: SlidersHorizontal, moduleKey: 'methodology' },
    ],
  },
  // ── 4b. DRAWINGS & FILES ───────────────────────────────────────────
  // Where a drawing lives and how you get to it: the sheet index, the plan
  // room that opens a sheet with its overlays, and the markups drawn on top.
  // Founder-requested position, below Estimating rather than up beside
  // Overview.
  //
  // Project files used to lead this group and is back in Overview, so what
  // is left here is the drawing surfaces themselves.
  //
  // Named for its contents rather than "Documents", because `grp_documents`
  // below already carries that label: two headers starting with the same
  // word would be a coin toss for the reader. That group keeps the outbound
  // paperwork (submittals, transmittals, signing), the formal binder (CDE,
  // source data) and the site photos - none of which are drawings.
  {
    id: 'grp_drawings',
    labelKey: 'sidebar.group.drawings',
    defaultLabel: 'Drawings & Files',
    defaultOpen: true,
    items: [
      // Reuses the page's own title key, which is already translated in all
      // 29 locales, so the sidebar entry and the page heading cannot drift.
      { labelKey: 'sheets.page_title', to: '/sheets', icon: FileText },
      // These two arrive from Documents, which hides itself in Simple mode, so
      // they carry the row-level form of that flag to keep the audience they
      // already had. Moving a row between groups must not change who can see
      // it, or a reorganisation becomes indistinguishable from a launch, and
      // Plan room is still BETA: landing it in front of the users who chose the
      // simplest view is a decision somebody should make on purpose.
      { labelKey: 'nav.plan_room', to: '/plan-room', icon: Layers, badge: 'BETA', advancedOnly: true },
      { labelKey: 'nav.markups', to: '/markups', icon: PenTool, advancedOnly: true },
    ],
  },
  // ── 5. REALITY CAPTURE & 3D ─────────────────────────────────────────
  // The 3D / spatial cluster: the geo overlay (site/spatial context),
  // point-cloud reality capture (laser scan / photogrammetry / LiDAR) and
  // the CAD-BIM data explorer. The BIM 3D model viewer moved up to Takeoff
  // (it is a quantity-extraction surface). This is the founder-requested
  // dedicated home for spatial surfaces (point-cloud plan
  // `internal design note POINTCLOUD_AND_SPATIAL_PLAN`, section 4); it
  // supersedes the earlier "no separate sidebar section" note for this
  // spatial context only. The group's `dynamicGroupKey: 'reality'` keeps a
  // short registry key across the `grp_` rename, so a manifest can publish
  // rows here with `group: 'reality'`. This comment used to say
  // `oe_pointcloud`'s frontend manifest does exactly that; it does not, and
  // cannot — `oe_pointcloud` is a backend module with no frontend manifest,
  // and nothing in `MODULE_REGISTRY` sets `group: 'reality'`. The key is a
  // live extension point, not wiring anything currently depends on. The
  // three rows below are static and keep the group on screen either way,
  // which is why this one is kept where the empty `regional` group was
  // deleted.
  {
    id: 'grp_reality',
    labelKey: 'sidebar.group.reality',
    defaultLabel: 'Reality Capture & 3D',
    dynamicGroupKey: 'reality',
    defaultOpen: true,
    items: [
      { labelKey: 'sidebar.geo_hub', to: '/geo', icon: Globe, badge: 'BETA' },
      { labelKey: 'nav.point_cloud', to: '/pointcloud', icon: ScanLine, badge: 'BETA' },
      { labelKey: 'nav.cad_bim_explorer', to: '/data-explorer', icon: TableProperties, advancedOnly: true },
    ],
  },
  // ── 6. MODEL COORDINATION ──────────────────────────────────────────
  // Multi-model BIM/CAD coordination: clash, federations, rule packs,
  // EIR matrix. Distinct from Takeoff so quantity-only users skip it.
  {
    id: 'grp_coordination',
    labelKey: 'sidebar.group.coordination',
    defaultLabel: 'Model Coordination',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.coordination_hub', to: '/coordination', icon: LayoutDashboard, badge: 'BETA' },
      { labelKey: 'nav.model_review', to: '/model-review', icon: ScanEye, badge: 'BETA' },
      { labelKey: 'nav.bim_federations', to: '/bim/federations', icon: Layers },
      { labelKey: 'nav.clash_detection', to: '/clash', icon: Radar, badge: 'BETA' },
      { labelKey: 'nav.model_issues', to: '/bcf', icon: MessageSquare, badge: 'BETA' },
      { labelKey: 'nav.bim_rules', to: '/bim/rules?mode=requirements', icon: SlidersHorizontal },
      { labelKey: 'nav.eir_matrix', to: '/requirements/matrix', icon: FileCheck, advancedOnly: true, badge: 'BETA' },
    ],
  },
  // ── 7. SCHEDULING ──────────────────────────────────────────────────
  // The time plan: master schedule, advanced CPM, takt, tasks.
  {
    id: 'grp_scheduling',
    labelKey: 'sidebar.group.scheduling',
    defaultLabel: 'Scheduling',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'schedule.title', to: '/schedule', icon: CalendarDays, moduleKey: 'schedule' },
      { labelKey: 'nav.schedule_advanced', to: '/schedule-advanced', icon: LineChart, advancedOnly: true },
      { labelKey: 'portfolio.title', to: '/portfolio', icon: Network, advancedOnly: true },
      { labelKey: 'nav.takt', to: '/takt', icon: GitBranch, advancedOnly: true },
      { labelKey: 'tasks.title', to: '/tasks', icon: ClipboardList },
    ],
  },
  // ── 8. COST CONTROL & RISK ─────────────────────────────────────────
  // 5D cost model, portfolio capacity/leveling and the risk register. The
  // register hosts the Monte Carlo simulation in its own tab, so the old
  // standalone "Risk Analysis" row was retired (IA merge #71) to keep a
  // single Monte-Carlo entry point; `/risk-analysis` now redirects there.
  {
    id: 'grp_cost_control',
    labelKey: 'sidebar.group.cost_control',
    defaultLabel: 'Cost Control & Risk',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.5d_cost_model', to: '/5d', icon: TrendingUp, moduleKey: '5d', advancedOnly: true },
      { labelKey: 'nav.progress', to: '/progress', icon: Activity, advancedOnly: true },
      { labelKey: 'nav.full_evm', to: '/full-evm', icon: LineChart, advancedOnly: true },
      { labelKey: 'nav.capacity_planning', to: '/portfolio/capacity', icon: CalendarRange, advancedOnly: true },
      { labelKey: 'nav.resource_leveling', to: '/portfolio/leveling', icon: Scale, advancedOnly: true },
      { labelKey: 'nav.risk_register', to: '/risks', icon: ShieldAlert, advancedOnly: true },
      { labelKey: 'nav.cvr', to: '/cvr', icon: Scale, advancedOnly: true },
      // Post-calculation closes the loop the rest of this group opens: what the
      // estimate allowed against what the site actually spent, per position.
      { labelKey: 'postcalc.title', to: '/postcalc', icon: Gauge, advancedOnly: true },
    ],
  },
  // ── 9. COMMERCIAL ──────────────────────────────────────────────────
  // CRM lead → contract award → subcontractors. Sourcing (bid, tender,
  // RFQ) lives in its own Procurement group below (see #280).
  {
    id: 'grp_commercial',
    labelKey: 'sidebar.group.commercial',
    defaultLabel: 'Commercial',
    defaultOpen: true,
    // Visible in Simple mode too. A user reported "there is no contracts
    // module" because this whole group was hidden outside Advanced mode
    // (hideInSimple). The group now shows with Contracts always visible;
    // CRM and Subcontractors stay advanced-only so Simple mode surfaces
    // just the core commercial entry point without extra clutter.
    items: [
      { labelKey: 'nav.crm', to: '/crm', icon: Briefcase, advancedOnly: true },
      { labelKey: 'nav.contracts', to: '/contracts', icon: FileSignature },
      { labelKey: 'nav.payment_clock', to: '/payment-clock', icon: Scale },
      { labelKey: 'nav.tax_withholding', to: '/tax-withholding', icon: Percent },
      { labelKey: 'nav.tax_rates', to: '/tax-rates', icon: Landmark },
      { labelKey: 'nav.einvoice_clearance', to: '/einvoice-clearance', icon: Stamp },
      { labelKey: 'nav.subcontractors', to: '/subcontractors', icon: HardHat, advancedOnly: true },
    ],
  },
  // ── 10. PROCUREMENT ────────────────────────────────────────────────
  // The three sourcing flows kept deliberately separate but gathered in
  // one place, each labelled for when to use it, plus the supplier price
  // book they all draw from (#280). Order runs lightest to most formal.
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
        labelKey: 'nav.bid_management',
        to: '/bid-management',
        icon: Scale,
        helpKey: 'sidebar.help.bid_management',
        defaultHelp:
          'Formal bidding with bidder invitations, a questions board and bid leveling.',
      },
      {
        labelKey: 'tendering.title',
        to: '/tendering',
        icon: FileText,
        moduleKey: 'tendering',
        advancedOnly: true,
        helpKey: 'sidebar.help.tendering',
        defaultHelp:
          'Priced from a bill of quantities; writes the winning rates back into the BOQ.',
      },
      {
        labelKey: 'nav.supplier_catalogs',
        to: '/supplier-catalogs',
        icon: ShoppingCart,
        helpKey: 'sidebar.help.supplier_catalogs',
        defaultHelp: 'Vendor price lists that the quotes and bids draw from.',
      },
    ],
  },
  // ── 10b. ESTIMATE DETAIL ───────────────────────────────────────────
  // The advanced refinements layered on top of the BOQ: the basis of
  // estimate, preliminaries and allowances. Split out of Estimating so that
  // group stays at five rows (all advanced-mode only).
  //
  // Founder-requested position, below Procurement rather than directly under
  // Estimating. Everything in here is priced against something bought, so it
  // reads better next to the sourcing groups than as a second estimating
  // block a reader has to scroll past to reach the rest of the project.
  {
    id: 'grp_estimate_detail',
    labelKey: 'sidebar.group.estimate_detail',
    defaultLabel: 'Estimate Detail',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.estimate_basis', to: '/estimate-basis', icon: FileText, advancedOnly: true },
      { labelKey: 'nav.preliminaries', to: '/preliminaries', icon: ClipboardList, advancedOnly: true },
      { labelKey: 'nav.allowances', to: '/allowances', icon: Wallet, advancedOnly: true },
      { labelKey: 'nav.design_options', to: '/design-options', icon: Scale, advancedOnly: true },
      // Shares the page's own heading key rather than minting a second key
      // holding the same word, the way the Teams row below does.
      { labelKey: 'formwork.title', to: '/formwork', icon: Boxes, advancedOnly: true, defaultLabel: 'Formwork' },
    ],
  },
  // ── 10c. CHANGE ────────────────────────────────────────────────────
  // The change-management workflow (variations, MoC, change orders) and
  // the analytics it feeds (change-intelligence, value). Split out of the
  // old "Procurement & Change" group so procurement reads clean (#280),
  // then split again from the capture/records surfaces (now "Records &
  // Capture" below) so neither group carries too many items.
  {
    id: 'grp_change',
    labelKey: 'sidebar.group.change',
    defaultLabel: 'Change',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.variations', to: '/variations', icon: GitBranch },
      { labelKey: 'moc.title', to: '/moc', icon: Replace, advancedOnly: true },
      { labelKey: 'nav.change_orders', to: '/changeorders', icon: FileEdit, advancedOnly: true },
      { labelKey: 'nav.change_intelligence', to: '/change-intelligence', icon: BrainCircuit, advancedOnly: true },
      { labelKey: 'nav.claims_evidence', to: '/claims-evidence', icon: ShieldCheck, advancedOnly: true },
      { labelKey: 'nav.value', to: '/value', icon: TrendingUp, advancedOnly: true },
    ],
  },
  // ── 10c. RECORDS & CAPTURE ──────────────────────────────────────────
  // The surfaces that capture project record (phone log, connectors,
  // reconciliation, inbound) plus cross-record search. Kept distinct from
  // "Change" above so each group stays short and scannable.
  {
    id: 'grp_records',
    labelKey: 'sidebar.group.records',
    defaultLabel: 'Records & Capture',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.phone_log', to: '/phone-log', icon: Phone, advancedOnly: true },
      { labelKey: 'nav.connectors', to: '/connectors', icon: HardDrive, advancedOnly: true },
      { labelKey: 'nav.reconciliation', to: '/reconciliation', icon: Link2, advancedOnly: true },
      {
        labelKey: 'nav.inbound_capture',
        to: '/inbound',
        icon: Mailbox,
        advancedOnly: true,
        adminOnly: true,
      },
      { labelKey: 'nav.inbound_email', to: '/inbound-email', icon: Inbox, advancedOnly: true },
      { labelKey: 'nav.find_records', to: '/find', icon: FileSearch, advancedOnly: true },
      { labelKey: 'project_route.title', to: '/project-route', icon: SlidersHorizontal, advancedOnly: true },
    ],
  },
  // ── 11. FIELD OPERATIONS ───────────────────────────────────────────
  // Day-to-day site: diary, field reports, service tickets, the
  // subcontractor portal. The /portal/payments route is intentionally
  // NOT listed here: it is the external, magic-link-authed surface for
  // subcontractors (no app shell) and is reached only through the link
  // in their invitation email. Internal staff manage payment
  // applications via Progress Claims under /contracts.
  {
    id: 'grp_field',
    labelKey: 'sidebar.group.field',
    defaultLabel: 'Field Operations',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.daily_diary', to: '/daily-diary', icon: BookOpen },
      { labelKey: 'nav.field_reports', to: '/field-reports', icon: ClipboardList, advancedOnly: true },
      { labelKey: 'nav.field_time', to: '/field-time', icon: Timer, advancedOnly: true },
    ],
  },
  // ── 11b. ON SITE ───────────────────────────────────────────────────
  // Site-facing operations: service tickets, site logistics and the
  // external subcontractor / client portal. The /portal/payments route is
  // intentionally NOT listed: it is the magic-link-authed surface for
  // subcontractors (no app shell), reached only via their invitation email.
  {
    id: 'grp_site',
    labelKey: 'sidebar.group.on_site',
    defaultLabel: 'On Site',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'site_prep.title', to: '/site-prep', icon: Flag },
      { labelKey: 'nav.service', to: '/service', icon: Wrench },
      { labelKey: 'nav.site_logistics', to: '/site-logistics', icon: Truck },
      { labelKey: 'site_inventory.title', to: '/site-inventory', icon: Warehouse },
      { labelKey: 'site_supervision.title', to: '/site-supervision', icon: HardHat, advancedOnly: true },
      { labelKey: 'nav.portal', to: '/portal', icon: Globe },
    ],
  },
  // ── 12. RESOURCES & ASSETS ─────────────────────────────────────────
  // Crews, equipment, payroll, the physical asset register.
  {
    id: 'grp_resources',
    labelKey: 'sidebar.group.resources',
    defaultLabel: 'Resources & Assets',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.equipment', to: '/equipment', icon: Truck },
      { labelKey: 'nav.resources', to: '/resources', icon: Users },
      // What the crew is licensed to do, and what the project demands of them.
      // The module has shipped installed since it was written and had no menu
      // entry and no route, so the only way to reach it was to know the URL.
      {
        labelKey: 'nav.credentials',
        defaultLabel: 'Credentials',
        to: '/credentials',
        icon: BadgeCheck,
        advancedOnly: true,
      },
      { labelKey: 'nav.payroll', to: '/payroll', icon: Wallet, advancedOnly: true },
      // The weekly payroll a public works contract has to be certified with.
      // It sits beside payroll because it is built from the same hours.
      {
        labelKey: 'nav.certified_payroll',
        to: '/certified-payroll',
        icon: FileCheck,
        advancedOnly: true,
      },
      { labelKey: 'nav.assets', to: '/assets', icon: Package },
      // Off-site / prefab production sits with resources (it is a production
      // resource surface). Moved out of Model Coordination while it is being
      // wired to BOQ/assembly/BIM; see grp_rate_buildup note on the beta cohort.
      { labelKey: 'nav.prefab', to: '/prefab', icon: Factory, advancedOnly: true },
    ],
  },
  // ── 13. QUALITY ────────────────────────────────────────────────────
  // Validation, inspections, NCR, punchlist — "the work passes".
  {
    id: 'grp_quality',
    labelKey: 'sidebar.group.quality',
    defaultLabel: 'Quality',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.issues', to: '/issues', icon: CircleDot },
      { labelKey: 'validation.title', to: '/validation', icon: ShieldCheck, moduleKey: 'validation' },
      // The rule builder authors what Validation runs, so it belongs beside it.
      // It was routed (`App.tsx` `/compliance/builder`) and named in the title
      // map from the day it shipped, and no surface ever linked to it: the only
      // ways in were typing the URL and the "Open module" button on its
      // how-it-works card, whose spotlight had to point at the Validation row
      // because the builder had none of its own. No `moduleKey` - App.tsx
      // mounts the screen statically, so the row cannot outlive it.
      { labelKey: 'nav.compliance_rule_builder', to: '/compliance/builder', icon: Wand2 },
      { labelKey: 'inspections.title', to: '/inspections', icon: ClipboardCheck },
      { labelKey: 'construction_control.title', to: '/construction-control', icon: ClipboardList },
      { labelKey: 'ncr.title', to: '/ncr', icon: AlertOctagon },
      { labelKey: 'nav.punchlist', to: '/punchlist', icon: ListChecks },
      { labelKey: 'deadlines.title', to: '/deadlines', icon: AlarmClock, defaultLabel: 'Deadlines' },
      { labelKey: 'review_authority.title', to: '/review-authority', icon: FileCheck, advancedOnly: true },
    ],
  },
  // ── 13b. HANDOVER & COMMISSIONING ──────────────────────────────────
  // Finishing the job cleanly: commissioning, close-out and the forms /
  // checklists that back them. Split out of Quality so each group stays
  // short and scannable.
  {
    id: 'grp_handover',
    labelKey: 'sidebar.group.handover',
    defaultLabel: 'Handover & Commissioning',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.commissioning', to: '/commissioning', icon: ClipboardCheck },
      { labelKey: 'closeout.title', to: '/closeout', icon: PackageCheck },
      { labelKey: 'defects_liability.title', to: '/defects-liability', icon: FileWarning },
      { labelKey: 'nav.forms', to: '/forms', icon: ClipboardList },
    ],
  },
  // ── 14. SAFETY & ESG ───────────────────────────────────────────────
  // Safety, HSE, QMS plus the ESG surfaces (carbon, sustainability —
  // the latter re-surfaced from the module registry).
  {
    id: 'grp_safety',
    labelKey: 'sidebar.group.safety',
    defaultLabel: 'Safety & ESG',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'safety.title', to: '/safety', icon: HardHat },
      { labelKey: 'nav.hse_advanced', to: '/hse-advanced', icon: Shield, advancedOnly: true },
      { labelKey: 'temporary_works.title', to: '/temporary-works', icon: Construction },
      { labelKey: 'nav.qms', to: '/qms', icon: BadgeCheck, advancedOnly: true },
    ],
  },
  // ── 14b. ESG & CARBON ──────────────────────────────────────────────
  // Environmental, social and governance reporting: embodied and
  // operational carbon, the sustainability hub and the ESG dashboard.
  {
    id: 'grp_esg',
    labelKey: 'sidebar.group.esg',
    defaultLabel: 'ESG & Carbon',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.carbon', to: '/carbon', icon: Leaf, advancedOnly: true },
      { labelKey: 'nav.sustainability', to: '/sustainability', icon: Leaf, moduleKey: 'sustainability', advancedOnly: true },
      { labelKey: 'nav.esg', to: '/esg', icon: Leaf, advancedOnly: true },
    ],
  },
  // ── 15. COMMUNICATION ──────────────────────────────────────────────
  // Contacts, meetings, RFIs, correspondence, and the real-time
  // collaboration surface (re-added — it was dropped before).
  {
    id: 'grp_communication',
    labelKey: 'sidebar.group.communication',
    defaultLabel: 'Communication',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'contacts.title', to: '/contacts', icon: Users },
      // Teams is the access side of "who is on this project": grouping people
      // and narrowing records to those groups. ShieldCheck rather than Users
      // so it does not read as a second contacts directory.
      {
        labelKey: 'teams.title',
        // Matches the value seeded for `teams.title`, so the row does not
        // change case the moment the locale key lands.
        defaultLabel: 'Teams and visibility',
        to: '/teams',
        icon: ShieldCheck,
        advancedOnly: true,
      },
      { labelKey: 'meetings.title', to: '/meetings', icon: CalendarDays },
      { labelKey: 'rfi.title', to: '/rfi', icon: HelpCircle, advancedOnly: true },
      { labelKey: 'interface_management.title', to: '/interface-management', icon: Handshake },
      { labelKey: 'correspondence.title', to: '/correspondence', icon: Mail, advancedOnly: true },
      { labelKey: 'authority_submission.title', to: '/authority-submissions', icon: Send, advancedOnly: true },
      { labelKey: 'nav.collaboration', to: '/collaboration', icon: Users, moduleKey: 'collaboration', advancedOnly: true },
    ],
  },
  // ── 16. DOCUMENTS ──────────────────────────────────────────────────
  // Outbound paperwork (submittals, transmittals, signing), the CDE binder
  // and imported source data, plus site photos. The drawing surfaces that
  // used to sit here - plan room and markups - moved up to Drawings & Files
  // (group 1b) alongside the sheet register they belong with.
  {
    id: 'grp_documents',
    labelKey: 'sidebar.group.documents',
    defaultLabel: 'Documents',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'submittals.title', to: '/submittals', icon: FileCheck, advancedOnly: true },
      { labelKey: 'transmittals.title', to: '/transmittals', icon: Send, advancedOnly: true },
      { labelKey: 'cde.title', to: '/cde', icon: Database },
      { labelKey: 'source_data.title', to: '/source-data', icon: Database, advancedOnly: true },
      { labelKey: 'signing.title', to: '/signing', icon: PenTool, advancedOnly: true },
      { labelKey: 'nav.photos', to: '/photos', icon: Camera },
    ],
  },
  // ── 17. REAL ESTATE ────────────────────────────────────────────────
  // Developer workflows: property dev, accommodation, dashboards, the
  // two long-lived settings catalogues (house types, doc templates).
  {
    id: 'grp_real_estate',
    labelKey: 'sidebar.group.real_estate',
    defaultLabel: 'Real Estate',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.property_dev', to: '/property-dev', icon: Building2 },
      { labelKey: 'nav.accommodation', to: '/accommodation', icon: Building2, badge: 'BETA' },
      { labelKey: 'nav.property_dev_dashboards', to: '/property-dev/dashboards', icon: BarChart3, advancedOnly: true },
      { labelKey: 'nav.property_dev_house_types', to: '/property-dev/settings/house-types', icon: Building2, advancedOnly: true },
      { labelKey: 'nav.property_dev_doc_templates', to: '/property-dev/settings/document-templates', icon: FileText, advancedOnly: true },
    ],
  },
  // ── 18. FINANCE ────────────────────────────────────────────────────
  // Money roll-up: finance, reports, reporting dashboards.
  {
    id: 'grp_finance',
    labelKey: 'sidebar.group.finance',
    defaultLabel: 'Finance',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'finance.title', to: '/finance', icon: Wallet, advancedOnly: true },
      { labelKey: 'nav.analytics', to: '/analytics', icon: LineChart, advancedOnly: true },
      { labelKey: 'nav.reports', to: '/reports', icon: FileBarChart, advancedOnly: true },
      { labelKey: 'nav.reporting_dashboards', to: '/reporting', icon: BarChart3, advancedOnly: true },
    ],
  },
  // ── 19. CONTROLS & BI ──────────────────────────────────────────────
  // Project controls, BI dashboards, the model snapshots (parquet/CAD-BIM
  // baseline) tool, and the admin-only architecture map.
  {
    id: 'grp_controls_bi',
    labelKey: 'sidebar.group.controls_bi',
    defaultLabel: 'Controls & BI',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.project_controls', to: '/project-controls', icon: Gauge, advancedOnly: true },
      { labelKey: 'nav.bi_dashboards', to: '/bi-dashboards', icon: BarChart3, advancedOnly: true },
      { labelKey: 'nav.snapshots', to: '/dashboards', icon: TrendingUp, advancedOnly: true },
      // Architecture Map — internal/dev tool, admin-only so a regular
      // customer's sidebar isn't cluttered with the dependency graph.
      // The route itself is also wrapped in <AdminOnly> in App.tsx.
      { labelKey: 'nav.architecture_map', to: '/architecture', icon: GitBranch, advancedOnly: true, adminOnly: true },
    ],
  },
  // ── 19b. RATE BUILD-UP ─────────────────────────────────────────────
  // The unit-rate build-up cohort: production norms (resource demand per
  // quantity), all-in labour rates, material waste factors, price escalation,
  // and the resource statement they feed. Sits right above the AI surfaces
  // because rate build-up is core estimating work. Still badged beta per item
  // until each is wired into the position resource split
  // (`metadata_["resources"]`) / assembly components. Ordered as the build-up
  // actually flows: norm -> rate -> waste -> escalation -> summary.
  {
    id: 'grp_rate_buildup',
    labelKey: 'sidebar.group.rate_buildup',
    defaultLabel: 'Rate Build-up',
    defaultOpen: true,
    hideInSimple: true,
    separator: true,
    items: [
      { labelKey: 'nav.norm_expansion', to: '/norm-expansion', icon: ListChecks, advancedOnly: true },
      { labelKey: 'nav.labor_rates', to: '/labor-rates', icon: HardHat, advancedOnly: true },
      { labelKey: 'nav.waste_factors', to: '/waste-factors', icon: Ruler, advancedOnly: true },
      { labelKey: 'nav.price_index', to: '/price-index', icon: TrendingUp, advancedOnly: true },
      { labelKey: 'nav.resource_summary', to: '/resource-summary', icon: Package, advancedOnly: true },
    ],
  },
  // ── 20. AI ESTIMATING (beta, in development) ───────────────────────
  // AI-assisted drafting: the AI estimate, the AI estimator and the
  // estimate copilot. They work but are still beta and lean on the core
  // BOQ, so they sit down here with the other AI surfaces rather than at
  // the top of Estimating. Collapsed by default to keep them low-key.
  {
    id: 'grp_estimating_ai',
    labelKey: 'sidebar.group.estimating_ai',
    defaultLabel: 'AI Estimating',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.ai_estimate', to: '/ai-estimate', icon: Sparkles, badge: 'BETA' },
      { labelKey: 'nav.ai_estimator', to: '/ai-estimator', icon: Wand2, badge: 'BETA' },
      { labelKey: 'nav.estimate_copilot', to: '/estimate-copilot', icon: Bot, badge: 'BETA' },
    ],
  },
  // ── 21. AUTOMATION & AI ────────────────────────────────────────────
  // AI agents, advisor, ERP chat, and the pipeline builder (listed
  // statically — its manifest group `ai` no longer matches any group id,
  // so there is no dynamic duplication).
  //
  // Founder-requested last position, and now last in the array too. This
  // used to read "last among the working groups rather than last in the
  // array", pointing at a `regional` group below that carried
  // `separator: true` and was said to draw the line between project work
  // and the setup surfaces. That group is gone (see the note under the
  // closing bracket); its separator drew nothing in this tree, because it
  // sat inside a group the empty-group guard skipped, so the rendered
  // order is unchanged by its removal.
  {
    id: 'grp_automation_ai',
    labelKey: 'sidebar.group.automation_ai',
    defaultLabel: 'Automation & AI',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.ai_agents', to: '/ai-agents', icon: Bot, badge: 'BETA' },
      { labelKey: 'nav.ai_advisor', to: '/advisor', icon: MessageSquare },
      { labelKey: 'nav.erp_chat', to: '/chat', icon: MessageSquare },
      { labelKey: 'nav.pipelines', to: '/pipelines', icon: GitBranch, moduleKey: 'pipelines', advancedOnly: true, badge: 'BETA' },
      // The register of modules built on this instance. Readable by anyone, so
      // no role gate here: the build and remove controls on the page are what
      // an administrator sees and what the server enforces.
      { labelKey: 'nav.module_builder', to: '/module-builder', icon: Wand2, advancedOnly: true },
    ],
  },
];

// A `regional` group used to close this array, and in this tree it was dead
// wiring. Its rows were to arrive only from `getModuleNavItems('regional')`,
// which filters manifest `navItems` by `group`. Nothing in the tree sets
// `group: 'regional'`: the one frontend module in that category,
// `regional-exchange`, ships `navItems: []` deliberately, and
// `modules/_registry.test.ts` asserts the list stays empty (#217 — the
// twenty country pages were meant to be reached from a BOQ rather than from
// the menu; whether that way in exists is a separate question, and today
// nothing in the app links to those routes). The group header therefore
// renders in no build of this tree, hidden by the generic
// `visibleItems.length === 0` guard in `Sidebar.tsx` and not by any
// regional-specific condition, and the `separator: true` it carried sat
// inside that same skipped branch, so no divider is lost by deleting it.
//
// Where regional packs are surfaced instead: the thirteen backend data
// packs (`oe_us_pack`, `oe_dach_pack`, `oe_uk_pack`, …) appear on
// `/modules` under the "Regional Standards" category, in
// Settings -> Modules, and in the onboarding module picker. They expose a
// single `GET /config/` endpoint and carry no page of their own, so a
// sidebar row for one would have nowhere to point.
//
// Note that `regional` names two unrelated axes. `ModuleManifest.category`
// is the shelf a module sits on for the registry page; `ModuleNavItem.group`
// is the sidebar group a row publishes into. A module can be in the
// `regional` category and publish no nav rows at all, which is exactly the
// case here — reading the category as the sidebar wiring is what made this
// group look alive.
