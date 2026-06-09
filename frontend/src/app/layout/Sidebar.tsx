import { useState, useCallback, useEffect, useMemo, useRef, Fragment } from 'react';
import { useQuery } from '@tanstack/react-query';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { CustomBranding } from './CustomBranding';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  LayoutDashboard,
  FolderOpen,
  Table2,
  CalendarDays,
  Database,
  Bot,
  Layers,
  Boxes,
  Box,
  ShieldCheck,
  FileText,
  FileBarChart,
  Package,
  Settings,
  Info,
  TrendingUp,
  ChevronDown,
  ChevronRight,
  Ruler,
  Sparkles,
  MessageSquare,
  X,
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
  AlertOctagon,
  FileCheck,
  Mail,
  Send,
  History,
  BrainCircuit,
  SlidersHorizontal,
  Plus,
  Search,
  Pin,
  PinOff,
  Eye,
  EyeOff,
  Pencil,
  Check,
  Github,
  HardDrive,
  Link2,
  // 18-Modules Wave icons
  Wrench,
  Truck,
  BookOpen,
  Globe,
  FileSignature,
  Briefcase,
  Scale,
  GitBranch,
  Building2,
  ShoppingCart,
  BadgeCheck,
  Shield,
  Leaf,
  BarChart3,
  LineChart,
  Radar,
  ScrollText,
  CalendarRange,
  Gauge,
  Wand2,
  PackageCheck,
  Loader2,
  type LucideIcon,
} from 'lucide-react';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { apiGet } from '@/shared/lib/api';
import { UpdateNotification } from '@/shared/ui/UpdateChecker';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useNavPendingStore } from '@/shared/lib/navigationProgress';
import { useRecentStore } from '@/stores/useRecentStore';
import { useGlobalSearchStore } from '@/stores/useGlobalSearchStore';
import { getModuleNavItems } from '@/modules/_registry';
import { APP_VERSION } from '@/shared/lib/version';
import { useSidebarBadges } from '@/shared/hooks/useSidebarBadges';
import { useModulePresence } from '@/shared/hooks/useModulePresence';
import { useHiddenModules } from '@/shared/hooks/useHiddenModules';
import { useIsRTL } from '@/shared/hooks/useIsRTL';
import {
  useSidebarCollapseStore,
  SIDEBAR_WIDTH_FULL,
  SIDEBAR_WIDTH_ICON,
} from '@/stores/useSidebarCollapseStore';
import { RequestCustomModuleDialog } from '@/features/modules/RequestCustomModuleDialog';
import {
  useActiveProjectProfile,
  buildModuleGate,
} from '@/features/projects/useProjectProfile';


interface NavItem {
  labelKey: string;
  to: string;
  icon: LucideIcon;
  badge?: string;
  highlight?: boolean;
  moduleKey?: string;
  advancedOnly?: boolean; // Hidden in simple mode
  tourId?: string; // data-tour attribute for onboarding
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

interface NavGroup {
  id: string;
  labelKey: string;
  /** Human English fallback shown until the `labelKey` locale string is
   *  added (the locale keys for the v6.10.0 group labels are wired in a
   *  later i18n pass). Passed to i18next as `defaultValue` so the header
   *  never renders a raw key. */
  defaultLabel?: string;
  descriptionKey?: string;
  items: NavItem[];
  defaultOpen: boolean;
  hideInSimple?: boolean; // Entire group hidden in simple mode
  /** Render a thin horizontal divider above this group. Used to peel
   *  reference/setup groups (Regional, Modules, Settings) away from
   *  the project-work surface above. */
  separator?: boolean;
  /** Registry key used to pull dynamic module nav items into this group,
   *  when it differs from `id`. The render loop calls
   *  `getModuleNavItems(group.dynamicGroupKey ?? group.id)`. Used by
   *  `grp_reality`, whose stable internal id is `grp_reality` but whose
   *  module-injection contract (so `oe_pointcloud`'s manifest can add its
   *  own row) is the shorter `reality` key documented in the point-cloud
   *  plan (`docs/strategy/POINTCLOUD_AND_SPATIAL_PLAN.md`, section 4). */
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
// Source-of-truth audit: every `to` here is cross-checked against
// `App.tsx` <Route path="…"/> entries — no broken links. Two routes the
// old flat menu had dropped (`/benchmarks` Cost Benchmarks, and
// `/collaboration`) are re-surfaced here, along with the two
// module-registry surfaces that never had a sidebar home because their
// manifest declared a `tools` group that did not exist (`/sustainability`,
// `/risk-analysis`). All four are now static rows with module-key gating.
//
// Group ids are deliberately unique and do NOT reuse the old `ai` / `tools`
// ids that module manifests inject into via `getModuleNavItems(group.id)`.
// Those manifest items (pipelines, sustainability, risk-analysis) are now
// listed statically instead, so there is no dynamic duplication. The one
// dynamic group kept verbatim is `regional` (Regional Exchange) — it still
// pulls its rows from the module registry and keeps its conditional render.
//
// Group labels use `t('sidebar.group.<slug>', { defaultValue: '<EN>' })`.
// The locale keys are added by a later pass; until then the English
// default renders. Item labelKeys reuse the existing locale strings.
const navGroups: NavGroup[] = [
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
      { labelKey: 'nav.project_files', to: '/files', icon: HardDrive },
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
    defaultOpen: false,
    items: [
      { labelKey: 'nav.quantities', to: '/quantities', icon: Ruler },
      { labelKey: 'nav.pdf_measurements', to: '/takeoff?tab=measurements', icon: Ruler },
      { labelKey: 'nav.dwg_takeoff', to: '/dwg-takeoff', icon: PencilRuler },
      { labelKey: 'nav.bim_viewer', to: '/bim', icon: Box },
    ],
  },
  // ── 3. ESTIMATING ──────────────────────────────────────────────────
  // The project's cost work-product: BOQ, the BIM↔catalogue match, the
  // AI estimate and the estimation intelligence dashboard.
  {
    id: 'grp_estimating',
    labelKey: 'sidebar.group.estimating',
    defaultLabel: 'Estimating',
    defaultOpen: false,
    items: [
      { labelKey: 'boq.title', to: '/boq', icon: Table2, tourId: 'boq' },
      { labelKey: 'nav.ai_estimator', to: '/ai-estimator', icon: Wand2 },
      { labelKey: 'nav.ai_estimate', to: '/ai-estimate', icon: Sparkles, badge: 'BETA' },
      { labelKey: 'nav.match_elements', to: '/match-elements', icon: Link2, badge: 'BETA' },
      { labelKey: 'nav.estimation_dashboard', to: '/project-intelligence', icon: BrainCircuit },
    ],
  },
  // ── 4. COST DATA ───────────────────────────────────────────────────
  // Cross-project reference data: cost databases, catalogues, assemblies,
  // and the cost-benchmark surface (re-added - it was dropped before).
  {
    id: 'grp_cost_data',
    labelKey: 'sidebar.group.cost_data',
    defaultLabel: 'Cost Data',
    defaultOpen: false,
    items: [
      { labelKey: 'costs.title', to: '/costs', icon: Database, tourId: 'costs' },
      { labelKey: 'catalog.title', to: '/catalog', icon: Boxes },
      { labelKey: 'nav.assemblies', to: '/assemblies', icon: Layers },
      { labelKey: 'nav.benchmarks', to: '/benchmarks', icon: BarChart3, moduleKey: 'cost-benchmark', advancedOnly: true },
    ],
  },
  // ── 5. REALITY CAPTURE & 3D ─────────────────────────────────────────
  // The 3D / spatial cluster: the geo overlay (site/spatial context),
  // point-cloud reality capture (laser scan / photogrammetry / LiDAR) and
  // the CAD-BIM data explorer. The BIM 3D model viewer moved up to Takeoff
  // (it is a quantity-extraction surface). This is the founder-requested
  // dedicated home for spatial surfaces (point-cloud plan
  // `docs/strategy/POINTCLOUD_AND_SPATIAL_PLAN.md`, section 4); it
  // supersedes the earlier "no separate sidebar section" note for this
  // spatial context only. `oe_pointcloud`'s frontend manifest injects its
  // own rows here via `getModuleNavItems('reality')` (the group's
  // `dynamicGroupKey`).
  {
    id: 'grp_reality',
    labelKey: 'sidebar.group.reality',
    defaultLabel: 'Reality Capture & 3D',
    dynamicGroupKey: 'reality',
    defaultOpen: false,
    items: [
      { labelKey: 'sidebar.geo_hub', to: '/geo', icon: Globe },
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
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.coordination_hub', to: '/coordination', icon: LayoutDashboard },
      { labelKey: 'nav.bim_federations', to: '/bim/federations', icon: Layers },
      { labelKey: 'nav.clash_detection', to: '/clash', icon: Radar },
      { labelKey: 'nav.bim_rules', to: '/bim/rules?mode=requirements', icon: SlidersHorizontal },
      { labelKey: 'nav.eir_matrix', to: '/requirements/matrix', icon: FileCheck, advancedOnly: true },
    ],
  },
  // ── 7. SCHEDULING ──────────────────────────────────────────────────
  // The time plan: master schedule, advanced CPM, takt, tasks.
  {
    id: 'grp_scheduling',
    labelKey: 'sidebar.group.scheduling',
    defaultLabel: 'Scheduling',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'schedule.title', to: '/schedule', icon: CalendarDays, moduleKey: 'schedule' },
      { labelKey: 'nav.schedule_advanced', to: '/schedule-advanced', icon: LineChart, advancedOnly: true },
      { labelKey: 'nav.takt', to: '/takt', icon: GitBranch, advancedOnly: true },
      { labelKey: 'tasks.title', to: '/tasks', icon: ClipboardList },
    ],
  },
  // ── 8. COST CONTROL & RISK ─────────────────────────────────────────
  // 5D cost model, portfolio capacity/leveling, risk register and the
  // Monte-Carlo risk-analysis tool (re-surfaced from the module registry).
  {
    id: 'grp_cost_control',
    labelKey: 'sidebar.group.cost_control',
    defaultLabel: 'Cost Control & Risk',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.5d_cost_model', to: '/5d', icon: TrendingUp, moduleKey: '5d', advancedOnly: true },
      { labelKey: 'nav.capacity_planning', to: '/portfolio/capacity', icon: CalendarRange, advancedOnly: true },
      { labelKey: 'nav.resource_leveling', to: '/portfolio/leveling', icon: Scale, advancedOnly: true },
      { labelKey: 'nav.risk_register', to: '/risks', icon: ShieldAlert, advancedOnly: true },
      { labelKey: 'nav.risk_analysis', to: '/risk-analysis', icon: Radar, moduleKey: 'risk-analysis', advancedOnly: true },
    ],
  },
  // ── 9. COMMERCIAL ──────────────────────────────────────────────────
  // CRM lead → contract award → subcontractors, bid management, tender.
  {
    id: 'grp_commercial',
    labelKey: 'sidebar.group.commercial',
    defaultLabel: 'Commercial',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.crm', to: '/crm', icon: Briefcase },
      { labelKey: 'nav.contracts', to: '/contracts', icon: FileSignature },
      { labelKey: 'nav.subcontractors', to: '/subcontractors', icon: HardHat },
      { labelKey: 'nav.bid_management', to: '/bid-management', icon: Scale },
      { labelKey: 'tendering.title', to: '/tendering', icon: FileText, moduleKey: 'tendering', advancedOnly: true },
    ],
  },
  // ── 10. PROCUREMENT & CHANGE ───────────────────────────────────────
  // Variations / MoC, supplier catalogues, procurement, change orders.
  {
    id: 'grp_procurement',
    labelKey: 'sidebar.group.procurement',
    defaultLabel: 'Procurement & Change',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.variations', to: '/variations', icon: GitBranch },
      { labelKey: 'moc.title', to: '/moc', icon: Replace, advancedOnly: true },
      { labelKey: 'nav.supplier_catalogs', to: '/supplier-catalogs', icon: ShoppingCart },
      { labelKey: 'procurement.title', to: '/procurement', icon: Package, advancedOnly: true },
      { labelKey: 'nav.change_orders', to: '/changeorders', icon: FileEdit, advancedOnly: true },
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
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.daily_diary', to: '/daily-diary', icon: BookOpen },
      { labelKey: 'nav.field_reports', to: '/field-reports', icon: ClipboardList, advancedOnly: true },
      { labelKey: 'nav.service', to: '/service', icon: Wrench },
      { labelKey: 'nav.portal', to: '/portal', icon: Globe },
    ],
  },
  // ── 12. RESOURCES & ASSETS ─────────────────────────────────────────
  // Crews, equipment, payroll, the physical asset register.
  {
    id: 'grp_resources',
    labelKey: 'sidebar.group.resources',
    defaultLabel: 'Resources & Assets',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.equipment', to: '/equipment', icon: Truck },
      { labelKey: 'nav.resources', to: '/resources', icon: Users },
      { labelKey: 'nav.payroll', to: '/payroll', icon: Wallet, advancedOnly: true },
      { labelKey: 'nav.assets', to: '/assets', icon: Package },
    ],
  },
  // ── 13. QUALITY ────────────────────────────────────────────────────
  // Validation, inspections, NCR, punchlist — "the work passes".
  {
    id: 'grp_quality',
    labelKey: 'sidebar.group.quality',
    defaultLabel: 'Quality',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'validation.title', to: '/validation', icon: ShieldCheck, moduleKey: 'validation' },
      { labelKey: 'inspections.title', to: '/inspections', icon: ClipboardCheck },
      { labelKey: 'ncr.title', to: '/ncr', icon: AlertOctagon },
      { labelKey: 'nav.punchlist', to: '/punchlist', icon: ListChecks },
      { labelKey: 'closeout.title', to: '/closeout', icon: PackageCheck },
    ],
  },
  // ── 14. SAFETY & ESG ───────────────────────────────────────────────
  // Safety, HSE, QMS plus the ESG surfaces (carbon, sustainability —
  // the latter re-surfaced from the module registry).
  {
    id: 'grp_safety',
    labelKey: 'sidebar.group.safety',
    defaultLabel: 'Safety & ESG',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'safety.title', to: '/safety', icon: HardHat },
      { labelKey: 'nav.hse_advanced', to: '/hse-advanced', icon: Shield, advancedOnly: true },
      { labelKey: 'nav.qms', to: '/qms', icon: BadgeCheck, advancedOnly: true },
      { labelKey: 'nav.carbon', to: '/carbon', icon: Leaf, advancedOnly: true },
      { labelKey: 'nav.sustainability', to: '/sustainability', icon: Leaf, moduleKey: 'sustainability', advancedOnly: true },
    ],
  },
  // ── 15. COMMUNICATION ──────────────────────────────────────────────
  // Contacts, meetings, RFIs, correspondence, and the real-time
  // collaboration surface (re-added — it was dropped before).
  {
    id: 'grp_communication',
    labelKey: 'sidebar.group.communication',
    defaultLabel: 'Communication',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'contacts.title', to: '/contacts', icon: Users },
      { labelKey: 'meetings.title', to: '/meetings', icon: CalendarDays },
      { labelKey: 'rfi.title', to: '/rfi', icon: HelpCircle, advancedOnly: true },
      { labelKey: 'correspondence.title', to: '/correspondence', icon: Mail, advancedOnly: true },
      { labelKey: 'nav.collaboration', to: '/collaboration', icon: Users, moduleKey: 'collaboration', advancedOnly: true },
    ],
  },
  // ── 16. DOCUMENTS ──────────────────────────────────────────────────
  // Outbound paperwork + the CDE binder, project photos, drawing markups.
  {
    id: 'grp_documents',
    labelKey: 'sidebar.group.documents',
    defaultLabel: 'Documents',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'submittals.title', to: '/submittals', icon: FileCheck, advancedOnly: true },
      { labelKey: 'transmittals.title', to: '/transmittals', icon: Send, advancedOnly: true },
      { labelKey: 'cde.title', to: '/cde', icon: Database },
      { labelKey: 'nav.photos', to: '/photos', icon: Camera },
      { labelKey: 'nav.markups', to: '/markups', icon: PenTool },
    ],
  },
  // ── 17. REAL ESTATE ────────────────────────────────────────────────
  // Developer workflows: property dev, accommodation, dashboards, the
  // two long-lived settings catalogues (house types, doc templates).
  {
    id: 'grp_real_estate',
    labelKey: 'sidebar.group.real_estate',
    defaultLabel: 'Real Estate',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.property_dev', to: '/property-dev', icon: Building2 },
      { labelKey: 'nav.accommodation', to: '/accommodation', icon: Building2 },
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
    defaultOpen: false,
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
    defaultOpen: false,
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
  // ── 20. AUTOMATION & AI ────────────────────────────────────────────
  // AI agents, advisor, ERP chat, and the pipeline builder (listed
  // statically — its manifest group `ai` no longer matches any group id,
  // so there is no dynamic duplication).
  {
    id: 'grp_automation_ai',
    labelKey: 'sidebar.group.automation_ai',
    defaultLabel: 'Automation & AI',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.ai_agents', to: '/ai-agents', icon: Bot, badge: 'BETA' },
      { labelKey: 'nav.ai_advisor', to: '/advisor', icon: MessageSquare },
      { labelKey: 'nav.erp_chat', to: '/chat', icon: MessageSquare },
      { labelKey: 'nav.pipelines', to: '/pipelines', icon: GitBranch, moduleKey: 'pipelines', advancedOnly: true },
    ],
  },
  // ── REGIONAL EXCHANGE (setup-only, dynamic) ────────────────────────
  // Separator marks the boundary between the project-work groups above
  // and the reference/setup surfaces below. Rows are injected purely
  // from the module registry via `getModuleNavItems('regional')`; the
  // group renders only when at least one regional module is enabled
  // (conditional render preserved from the previous design).
  {
    id: 'regional',
    labelKey: 'modules.cat_regional',
    descriptionKey: 'modules.cat_regional_desc',
    defaultOpen: false,
    hideInSimple: true,
    separator: true,
    items: [
      // All regional exchange modules injected dynamically from module registry
    ],
  },
];

// Admin / setup surfaces — rendered as a 2-column button grid pinned
// at the bottom of the sidebar (below the scroll area, above the
// GitHub/version footer). The grid is denser than the main nav list
// and keeps these always-available shortcuts out of the project-work
// flow. Role-gated items (audit log, permissions matrix) only render
// for admin/manager JWTs — backend `RequirePermission` remains
// authoritative; the client gate just keeps the grid tidy.
// Admin / setup surfaces — one 2-column button grid, ordered
// most-important → least-important. Permissions, Approval Routes and
// Validation Rules used to be three separate tiles here; they now share
// one "Governance" surface (/governance, three /modules-style tabs), so
// a single Governance tile sits right after Modules in the flow.
// Integrations is intentionally absent: it lives under Settings →
// Integrations, so a tile would duplicate it.
const adminGridItems: NavItem[] = [
  { labelKey: 'sidebar.admin_grid.settings', to: '/settings', icon: Settings },
  { labelKey: 'sidebar.admin_grid.users', to: '/users', icon: Users },
  { labelKey: 'sidebar.admin_grid.modules', to: '/modules', icon: Package },
  {
    labelKey: 'sidebar.admin_grid.governance',
    to: '/governance',
    icon: Scale,
    roleGate: ['admin', 'manager'],
  },
  {
    labelKey: 'sidebar.admin_grid.audit',
    to: '/admin/audit-log',
    icon: ScrollText,
    roleGate: ['admin', 'manager'],
  },
  { labelKey: 'sidebar.admin_grid.about', to: '/about', icon: Info },
];

/** Flat lookup of every NavItem in the sidebar, keyed by `to`. The
 *  Pinned section uses this to resolve a stored route string into a
 *  full NavItem (with icon, labelKey, badge etc.) without duplicating
 *  the source-of-truth list. */
const ALL_NAV_ITEMS: Record<string, NavItem> = (() => {
  const map: Record<string, NavItem> = {};
  for (const group of navGroups) for (const item of group.items) map[item.to] = item;
  for (const item of adminGridItems) map[item.to] = item;
  return map;
})();

/** Maps a static nav route (`NavItem.to`) to the id of the group that
 *  contains it. Used to auto-expand the group holding the active route so
 *  the user always sees where they are, even though every group starts
 *  collapsed. Dynamic (module-registry) rows are not here; their group
 *  auto-expands only if the active route is one of the static rows. */
const GROUP_ID_BY_ROUTE: Record<string, string> = (() => {
  const map: Record<string, string> = {};
  for (const group of navGroups) for (const item of group.items) map[item.to] = group.id;
  return map;
})();

/** Legacy → current group-id aliases. The ProductTour steps reference the
 *  pre-redesign group ids (`property`, `cad_bim_analytics`) when they fire
 *  `oe:tour-reveal`. The v6.10.0 redesign renamed every group, so the
 *  tour-reveal handler maps any incoming legacy id to its current id before
 *  expanding, keeping the onboarding spotlight working without editing the
 *  tour definition. New code should dispatch the current `grp_*` ids. */
const LEGACY_GROUP_ID_ALIASES: Record<string, string> = {
  property: 'grp_real_estate',
  cad_bim_analytics: 'grp_coordination',
};

/** Minimal shape of a backend module entry returned by `GET /v1/modules/`.
 *  We only read the fields needed to reconcile sidebar visibility with the
 *  server-side enabled/disabled state set on the System Modules tab. */
interface BackendModuleState {
  name: string;
  enabled: boolean;
  is_core: boolean;
}

/** Maps a sidebar route (`NavItem.to`, query string stripped) to the backend
 *  module manifest name (`oe_*`) that powers it. When that backend module is
 *  *explicitly* disabled on the System Modules tab, the route below is hidden
 *  so the sidebar never links to a 404/blank surface (the two enable systems
 *  — frontend `useModuleStore` and the backend module loader — were
 *  previously unreconciled, leaving disabled-backend routes live and broken).
 *
 *  Only optional (non-core) modules that own a sidebar route need an entry;
 *  core modules (Dashboard, Projects, BOQ, Costs, Settings, Modules, Users)
 *  can never be disabled and are intentionally absent. Routes not listed here
 *  are never gated by backend state (fail-open). */
const ROUTE_BACKEND_MODULE: Record<string, string> = {
  // Takeoff
  '/quantities': 'oe_takeoff',
  '/takeoff': 'oe_takeoff',
  '/dwg-takeoff': 'oe_dwg_takeoff',
  '/bim': 'oe_bim_hub',
  '/data-explorer': 'oe_cad',
  // Model coordination
  '/coordination': 'oe_coordination_hub',
  '/bim/federations': 'oe_bim_hub',
  '/clash': 'oe_clash',
  '/bim/rules': 'oe_bim_requirements',
  '/requirements/matrix': 'oe_requirements',
  '/geo': 'oe_geo_hub',
  // AI & tools
  '/ai-agents': 'oe_ai_agents',
  '/advisor': 'oe_ai',
  '/chat': 'oe_erp_chat',
  '/pipelines': 'oe_pipelines',
  // Commercial
  '/crm': 'oe_crm',
  '/contracts': 'oe_contracts',
  '/subcontractors': 'oe_subcontractors',
  '/bid-management': 'oe_bid_management',
  '/tendering': 'oe_tendering',
  '/variations': 'oe_variations',
  '/moc': 'oe_moc',
  '/supplier-catalogs': 'oe_supplier_catalogs',
  // Real estate development
  '/property-dev': 'oe_property_dev',
  '/accommodation': 'oe_accommodation',
  // Planning
  '/schedule': 'oe_schedule',
  '/schedule-advanced': 'oe_schedule_advanced',
  '/takt': 'oe_schedule_advanced',
  '/tasks': 'oe_tasks',
  '/5d': 'oe_costmodel',
  '/risks': 'oe_risk',
  // Field operations
  '/daily-diary': 'oe_daily_diary',
  '/field-reports': 'oe_fieldreports',
  '/equipment': 'oe_equipment',
  '/resources': 'oe_resources',
  '/payroll': 'oe_payroll',
  '/service': 'oe_service',
  '/portal': 'oe_portal',
  // Quality
  '/validation': 'oe_validation',
  '/inspections': 'oe_inspections',
  '/ncr': 'oe_ncr',
  '/punchlist': 'oe_punchlist',
  '/closeout': 'oe_closeout',
  '/qms': 'oe_qms',
  // Safety & HSE
  '/safety': 'oe_safety',
  '/hse-advanced': 'oe_hse_advanced',
  '/carbon': 'oe_carbon',
  // Communication
  '/contacts': 'oe_contacts',
  '/meetings': 'oe_meetings',
  '/rfi': 'oe_rfi',
  '/submittals': 'oe_submittals',
  '/transmittals': 'oe_transmittals',
  '/correspondence': 'oe_correspondence',
  '/collaboration': 'oe_collaboration',
  // Documentation
  '/cde': 'oe_cde',
  '/markups': 'oe_markups',
  // Finance & procurement
  '/finance': 'oe_finance',
  '/procurement': 'oe_procurement',
  '/changeorders': 'oe_changeorders',
  // Analytics & reports
  '/reports': 'oe_reporting',
  '/project-controls': 'oe_project_controls',
  '/bi-dashboards': 'oe_bi_dashboards',
  '/reporting': 'oe_reporting',
  '/architecture': 'oe_architecture_map',
};

/** Maps a sidebar route (`NavItem.to`, query string stripped) to the canonical
 *  module key used by Company Profiles and the onboarding catalogue
 *  (`frontend/src/features/onboarding/modules.ts` + the backend
 *  `onboarding_presets.py`). When a profile leaves that module out, the row is
 *  hidden — this is what makes a Company Profile actually shape the sidebar
 *  rather than just toggle a counter.
 *
 *  Several routes can share one key (e.g. all model-coordination surfaces map
 *  to `bim_hub`, every property-dev tab to `property_dev`) so a profile reveals
 *  or hides a whole capability at once. Core surfaces every company needs
 *  (Dashboard, Projects, Files, Contacts, Estimation Intelligence, Architecture
 *  Map) are intentionally absent here, so a profile can never hide them. */
const ROUTE_MODULE_KEY: Record<string, string> = {
  // Estimating
  '/boq': 'boq',
  '/match-elements': 'match_elements',
  '/ai-estimator': 'ai_estimator',
  '/ai-estimate': 'ai',
  // Catalogues & reference (/costs, /catalog, /assemblies) are intentionally
  // absent: the cost database, resource catalogue and assembly library are
  // core to a cost-estimation platform, so a company profile must never hide
  // them. They are forced on in onboarding_presets._CORE_MODULES too.
  // Takeoff
  '/quantities': 'takeoff',
  '/takeoff': 'takeoff',
  '/dwg-takeoff': 'dwg_takeoff',
  '/bim': 'bim_hub',
  '/data-explorer': 'cad',
  // Model coordination (all powered by the BIM hub capability)
  '/coordination': 'bim_hub',
  '/bim/federations': 'bim_hub',
  '/clash': 'bim_hub',
  '/bim/rules': 'bim_requirements',
  '/requirements/matrix': 'bim_requirements',
  '/geo': 'bim_hub',
  // AI & tools
  '/ai-agents': 'ai',
  '/advisor': 'ai',
  '/chat': 'erp_chat',
  // (/pipelines, /benchmarks, /sustainability, /risk-analysis are gated by
  //  their inline `moduleKey` instead — no Company-Profile mapping.)
  // Commercial
  '/crm': 'crm',
  '/contracts': 'contracts',
  '/subcontractors': 'subcontractors',
  '/bid-management': 'bid_management',
  '/tendering': 'tendering',
  '/variations': 'variations',
  '/moc': 'moc',
  '/supplier-catalogs': 'supplier_catalogs',
  // Real estate development (every tab tied to the one capability)
  '/property-dev': 'property_dev',
  '/accommodation': 'property_dev',
  '/property-dev/dashboards': 'property_dev',
  '/property-dev/settings/house-types': 'property_dev',
  '/property-dev/settings/document-templates': 'property_dev',
  // Planning
  '/schedule': 'schedule',
  '/schedule-advanced': 'schedule_advanced',
  '/takt': 'schedule_advanced',
  '/tasks': 'tasks',
  '/5d': 'costmodel',
  '/risks': 'risk',
  // Field operations
  '/daily-diary': 'daily_diary',
  '/field-reports': 'fieldreports',
  '/equipment': 'equipment',
  '/resources': 'resources',
  '/payroll': 'payroll',
  '/service': 'service',
  '/portal': 'portal',
  '/assets': 'equipment',
  // Quality
  '/validation': 'validation',
  '/inspections': 'inspections',
  '/ncr': 'ncr',
  '/punchlist': 'punchlist',
  '/closeout': 'closeout',
  '/qms': 'qms',
  // Safety & HSE
  '/safety': 'safety',
  '/hse-advanced': 'hse_advanced',
  '/carbon': 'carbon',
  // Communication
  '/meetings': 'meetings',
  '/rfi': 'rfi',
  '/submittals': 'submittals',
  '/transmittals': 'transmittals',
  '/correspondence': 'correspondence',
  '/collaboration': 'collaboration',
  // Documentation
  '/cde': 'cde',
  '/photos': 'documents',
  '/markups': 'markups',
  // Finance & procurement
  '/finance': 'finance',
  '/procurement': 'procurement',
  '/changeorders': 'changeorders',
  // Analytics & reports
  '/reports': 'reporting',
  '/project-controls': 'project_controls',
  '/bi-dashboards': 'bi_dashboards',
  '/dashboards': 'reporting',
  '/reporting': 'reporting',
};

// localStorage key for collapsed state
const COLLAPSED_KEY = 'oe_sidebar_collapsed';
const PINNED_KEY = 'oe_sidebar_pinned';
// Hidden-modules persistence is owned by `useHiddenModules()` — it stores
// the per-user list server-side under `metadata_.sidebar_hidden_modules`
// with localStorage as instant cache + offline fallback. The legacy global
// key `oe.sidebar_hidden_modules` was per-browser, leaked across user
// switches in the same browser, and is no longer read or written here.

function readCollapsedState(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* ignore */
  }
  return {};
}

function writeCollapsedState(state: Record<string, boolean>) {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

function readPinned(): string[] {
  try {
    const raw = localStorage.getItem(PINNED_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.filter((p) => typeof p === 'string');
    }
  } catch {
    /* ignore */
  }
  return [];
}

function writePinned(arr: string[]) {
  try {
    localStorage.setItem(PINNED_KEY, JSON.stringify(arr));
  } catch {
    /* ignore */
  }
}

// Stable data-testid map for the ProductTour spotlight. Tests + the
// onboarding walk-through query the sidebar by these attributes
// rather than by label, so they survive i18n changes. Only routes the
// tour actually targets need an entry here; everything else falls
// through to the default `data-tour` attribute (if any).
const PRODUCT_TOUR_NAV_TESTIDS: Record<string, string> = {
  '/boq': 'sidebar-nav-boq',
  '/bim': 'sidebar-nav-bim',
  '/property-dev': 'sidebar-nav-property-dev',
  '/accommodation': 'sidebar-nav-accommodation',
  '/geo': 'sidebar-nav-geo-hub',
};

// Two-key keyboard shortcuts for the most-trafficked routes. The
// sequence is `G` then a single letter — the same convention modern
// SaaS apps use, so muscle memory transfers. We surface the hint inline
// next to the item so users can discover the shortcut without docs.
const KBD_HINTS: Record<string, string> = {
  '/': 'G D',
  '/projects': 'G P',
  '/boq': 'G B',
  '/costs': 'G C',
  '/bim': 'G M',
  '/ai-estimate': 'G A',
  '/settings': 'G ,',
};
const KBD_BY_LETTER: Record<string, string> = {
  d: '/',
  p: '/projects',
  b: '/boq',
  c: '/costs',
  m: '/bim',
  a: '/ai-estimate',
  ',': '/settings',
};

/** Compute the single best-matching nav route for the current location.
 *  React Router's NavLink uses prefix matching, which lights up BOTH
 *  `/bim` and `/bim/rules` when the user is on `/bim/rules`. We pick
 *  the most specific match instead — query-aware exact match wins,
 *  then plain pathname match, then the longest prefix among nav items.
 *  Returns the chosen item's `to` string, or null when nothing matches.
 */
function pickActiveRoute(
  location: { pathname: string; search: string },
  routes: string[],
): string | null {
  const currentParams = new URLSearchParams(location.search);

  // 1) Query-aware exact match — `/takeoff?tab=measurements` wins over
  //    `/takeoff` and over the broader `/takeoff?tab=...` siblings when
  //    every required param value is present in the current URL.
  const queryMatches = routes
    .filter((r) => r.includes('?'))
    .filter((r) => {
      const [pathname, qs] = r.split('?');
      if (location.pathname !== pathname) return false;
      const want = new URLSearchParams(qs);
      for (const [k, v] of want) {
        if (currentParams.get(k) !== v) return false;
      }
      return true;
    });
  if (queryMatches.length > 0) {
    return queryMatches.sort((a, b) => b.length - a.length)[0]!;
  }

  // 2) Plain pathname matches: exact wins; otherwise longest prefix.
  let best: string | null = null;
  let bestLen = -1;
  for (const route of routes) {
    if (route.includes('?')) continue;
    if (route === location.pathname) {
      if (route.length > bestLen) {
        best = route;
        bestLen = route.length;
      }
      continue;
    }
    if (route !== '/' && location.pathname.startsWith(route + '/')) {
      if (route.length > bestLen) {
        best = route;
        bestLen = route.length;
      }
    } else if (route === '/' && location.pathname === '/') {
      if (route.length > bestLen) {
        best = route;
        bestLen = route.length;
      }
    }
  }
  return best;
}

export function Sidebar({ onClose }: { onClose?: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isModuleEnabled } = useModuleStore();
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const setViewMode = useViewModeStore((s) => s.setMode);
  const badgeCounts = useSidebarBadges();
  const modulePresence = useModulePresence();
  const openSearch = useGlobalSearchStore((s) => s.openModal);
  const iconified = useSidebarCollapseStore((s) => s.iconified);
  const toggleIconified = useSidebarCollapseStore((s) => s.toggle);
  const isRTL = useIsRTL();
  const userRole = useAuthStore((s) => s.userRole);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  // Backend module enabled-state. The System Modules tab disables/enables
  // server-side plugins; without this, a backend-disabled module's sidebar
  // route stayed live and broke on click. We share the `['system-modules']`
  // query key with the Modules page so a successful toggle there invalidates
  // this query and the sidebar updates immediately. Fail-open: if the fetch
  // errors or is still loading, no route is hidden.
  const { data: backendModules } = useQuery({
    queryKey: ['system-modules'],
    queryFn: () => apiGet<BackendModuleState[]>('/v1/modules/'),
    enabled: isAuthenticated,
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });

  // Set of backend module names that are EXPLICITLY disabled (non-core).
  const disabledBackendModules = useMemo(() => {
    const set = new Set<string>();
    for (const m of backendModules ?? []) {
      if (!m.is_core && !m.enabled) set.add(m.name);
    }
    return set;
  }, [backendModules]);

  // True when the sidebar route's backing backend module is disabled.
  const isRouteBackendDisabled = useCallback(
    (to: string) => {
      const path = to.split('?')[0]!;
      const moduleName = ROUTE_BACKEND_MODULE[path];
      return moduleName ? disabledBackendModules.has(moduleName) : false;
    },
    [disabledBackendModules],
  );

  // Role-gate the admin grid. Items without a `roleGate` always show;
  // gated items only render when the current JWT role matches. The
  // backend `RequirePermission` decorator still enforces real access —
  // this is just to keep the sidebar tidy for non-admin users.
  const visibleAdminGridItems = adminGridItems.filter(
    (item) => !item.roleGate || (userRole && (item.roleGate as string[]).includes(userRole)),
  );

  // Drive the global CSS variable so both the aside (`w-sidebar`) and
  // the main-content offset (`lg:pl-sidebar`) shrink/grow in lockstep.
  // The variable lives on :root so it survives across remounts; we
  // reset it to the full width when the component unmounts only if it
  // was the one that shrunk it, to avoid stranding a 64px gutter when
  // the user logs out.
  useEffect(() => {
    document.documentElement.style.setProperty(
      '--oe-sidebar-width',
      iconified ? SIDEBAR_WIDTH_ICON : SIDEBAR_WIDTH_FULL,
    );
  }, [iconified]);

  // Map route paths → open-item counts for sidebar badges
  const badgeMap: Record<string, number> = {
    '/tasks': badgeCounts.tasks,
    '/rfi': badgeCounts.rfi,
    '/safety': badgeCounts.safety,
  };

  // Initialize collapsed state from localStorage, falling back to group defaults
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const stored = readCollapsedState();
    const initial: Record<string, boolean> = {};
    for (const group of navGroups) {
      initial[group.id] = stored[group.id] ?? !group.defaultOpen;
    }
    return initial;
  });

  // Pinned routes — small starter section above the first group. Users
  // pin/unpin via the small icon-button that appears on item hover.
  const [pinned, setPinned] = useState<string[]>(() => readPinned());

  // ── Menu editor state ───────────────────────────────────────────────
  // `hiddenModules` is the *persisted* set — drives which rows are
  // filtered out of the rendered nav in normal mode. Persistence is
  // owned by `useHiddenModules()`: server-side per-user with localStorage
  // as instant cache + offline fallback (multi-device safe).
  // `editMode` is the transient "Edit menu" toggle.
  // `editingHidden` is the in-memory working copy users edit while in
  // edit mode; only committed to `hiddenModules` on Save.
  const { hiddenModules, setHiddenModules } = useHiddenModules();
  const [editMode, setEditMode] = useState(false);
  const [editingHidden, setEditingHidden] = useState<string[]>([]);

  const enterEditMode = useCallback(() => {
    setEditingHidden(hiddenModules);
    setEditMode(true);
  }, [hiddenModules]);

  const cancelEditMode = useCallback(() => {
    setEditMode(false);
    setEditingHidden([]);
  }, []);

  const saveEditMode = useCallback(() => {
    setHiddenModules(editingHidden);
    setEditMode(false);
    setEditingHidden([]);
  }, [editingHidden, setHiddenModules]);

  const toggleItemHidden = useCallback((route: string) => {
    setEditingHidden((prev) =>
      prev.includes(route) ? prev.filter((r) => r !== route) : [...prev, route],
    );
  }, []);

  // Set used by the render loop to decide whether to hide a row. In edit
  // mode the user sees EVERYTHING (so they can re-enable items) — only
  // normal mode actually filters. The visual "muted" state is driven by
  // `editingHidden` so re-enabled rows visually un-mute immediately.
  const effectiveHidden = editMode ? [] : hiddenModules;

  // Custom-module request dialog — opens from the "Request a custom
  // module" CTA at the bottom of the nav (below the "+ Add module"
  // developer-guide tile). The dialog itself handles community vs
  // bespoke routing.
  const [customModuleOpen, setCustomModuleOpen] = useState(false);

  // Persist collapsed state to localStorage
  useEffect(() => {
    writeCollapsedState(collapsed);
  }, [collapsed]);

  // Persist pinned state to localStorage
  useEffect(() => {
    writePinned(pinned);
  }, [pinned]);

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsed((prev) => ({ ...prev, [groupId]: !prev[groupId] }));
  }, []);

  // ── Product-tour reveal bridge ──────────────────────────────────────
  // The global tour spotlights rows that live inside collapsible groups
  // (e.g. "property" / "cad_bim_analytics"). Those groups are collapsed by
  // default — and some are hidden entirely in simple view — so the target
  // row is unmounted and the tour can't measure it. When the tour hits such
  // a step it dispatches `oe:tour-reveal` with the group id; we force that
  // group expanded and switch to advanced view if the group is gated behind
  // it, so the row mounts and the spotlight can latch on.
  useEffect(() => {
    const onReveal = (evt: Event) => {
      const raw = (evt as CustomEvent<{ groupId?: string }>).detail?.groupId;
      if (!raw) return;
      // Translate legacy tour group ids to the current redesigned ids.
      const groupId = LEGACY_GROUP_ID_ALIASES[raw] ?? raw;
      setCollapsed((prev) => ({ ...prev, [groupId]: false }));
      const group = navGroups.find((g) => g.id === groupId);
      if (group?.hideInSimple && useViewModeStore.getState().mode !== 'advanced') {
        setViewMode('advanced');
      }
    };
    window.addEventListener('oe:tour-reveal', onReveal);
    return () => window.removeEventListener('oe:tour-reveal', onReveal);
  }, [setViewMode]);

  const togglePin = useCallback((route: string) => {
    setPinned((prev) =>
      prev.includes(route) ? prev.filter((p) => p !== route) : [...prev, route],
    );
  }, []);

  // ── Two-key navigation shortcuts (G then X) ──────────────────────────
  // Modern-SaaS-style. We listen at document level for the leading
  // `G`, then within 1.5 s any single letter from KBD_BY_LETTER fires
  // the matching navigation. Ignores all keystrokes that originate
  // from text fields so it doesn't conflict with form input.
  const firstKeyRef = useRef<string | null>(null);
  const firstKeyTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const clearFirst = () => {
      firstKeyRef.current = null;
      if (firstKeyTimerRef.current != null) {
        window.clearTimeout(firstKeyTimerRef.current);
        firstKeyTimerRef.current = null;
      }
    };

    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const editable = (e.target as HTMLElement | null)?.isContentEditable;
      if (editable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // #153 guard — non-printable keys (Dead/Meta combos on certain layouts)
      // can land with `e.key === undefined`.
      const key = (e.key ?? '').toLowerCase();
      if (!key) return;

      if (firstKeyRef.current === 'g') {
        const route = KBD_BY_LETTER[key];
        if (route) {
          e.preventDefault();
          // The dashboard chord must reach the dashboard even on fresh
          // installs — DashboardPage normally redirects to /onboarding
          // until the wizard is finished, but a deliberate chord nav
          // means "show me the dashboard now". Sentinel is read+cleared
          // by DashboardPage's first-launch effect.
          if (key === 'd') {
            try {
              sessionStorage.setItem('oe_skip_onboarding_redirect', '1');
            } catch {
              /* storage unavailable */
            }
          }
          navigate(route);
        }
        clearFirst();
        return;
      }

      if (key === 'g') {
        firstKeyRef.current = 'g';
        firstKeyTimerRef.current = window.setTimeout(clearFirst, 1500);
      }
    };

    document.addEventListener('keydown', handler);
    return () => {
      document.removeEventListener('keydown', handler);
      clearFirst();
    };
  }, [navigate]);

  // Resolve pinned route strings into full NavItems (skipping any
  // routes that are no longer in the registry — e.g. a module the user
  // pinned earlier has been disabled, or hidden via the menu editor).
  // In edit mode we show the full pinned list so users can also see
  // them; in normal mode we drop hidden routes.
  const pinnedItems: NavItem[] = pinned
    .map((route) => ALL_NAV_ITEMS[route])
    .filter((item): item is NavItem => Boolean(item))
    .filter((item) => !isRouteBackendDisabled(item.to))
    .filter((item) => editMode || !hiddenModules.includes(item.to));

  // Pick a single winning route for highlighting. Without this, both
  // `/bim` (parent) and `/bim/rules` (child) would render as "active"
  // because `/bim/rules` starts with `/bim/`. We hand the chosen
  // string down to every `SidebarItem` so only one row lights up.
  const activeRoute = pickActiveRoute(location, Object.keys(ALL_NAV_ITEMS));

  // ── Auto-expand the group holding the active route ──────────────────
  // Every group is collapsed by default, so on navigation the user could
  // land on a page whose sidebar group is closed and lose their bearings.
  // When the active route belongs to a static group, force that group
  // open. We only ever expand (never collapse) here, so the user's manual
  // collapse of OTHER groups — and the persisted localStorage state — is
  // left untouched.
  useEffect(() => {
    if (!activeRoute) return;
    const groupId = GROUP_ID_BY_ROUTE[activeRoute];
    if (!groupId) return;
    setCollapsed((prev) => (prev[groupId] ? { ...prev, [groupId]: false } : prev));
  }, [activeRoute]);

  // ── Project focus (in-place) ────────────────────────────────────────
  // When the active project has a setup profile with focus mode ON, the
  // sidebar keeps its ORIGINAL menu and ORIGINAL order — no separate
  // "project route" section is hoisted to the top. Instead, in place:
  //   • modules the project needs  → fully visible + a sequence number
  //   • modules it does not need   → smaller and de-emphasized (grey)
  //   • routes outside the profile → rendered normally (global nav
  //     never breaks).
  // No active project / no profile / focus mode OFF → `gate.active` is
  // false and every row renders exactly as the flat default.
  const { profile: activeProfile } = useActiveProjectProfile();
  const gate = buildModuleGate(activeProfile);
  // Running 1..N sequence assigned to project-needed rows as they
  // render top-to-bottom. Resets every render (component body re-runs),
  // so the numbers always read in visual order regardless of grouping.
  let routeSeq = 0;

  return (
    <aside
      data-tour="sidebar"
      data-testid="app-sidebar"
      className="oe-sidebar relative flex h-full w-sidebar flex-col bg-surface-primary"
      style={{
        // Right-edge depth — 1px hairline + a soft 12px fade. Replaces
        // the hard `border-r border-border-light` for a modern-SaaS
        // feel: definition without rigidity.
        boxShadow:
          '1px 0 0 rgba(15, 23, 42, 0.05), 4px 0 12px -8px rgba(15, 23, 42, 0.06)',
      }}
    >
      {/* Page-scoped CSS — sidebar-only animations. Defined inline to
          keep this component fully self-contained. */}
      <style>{`
        @keyframes oeStaggerIn {
          0%   { opacity: 0; transform: translateY(-4px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        .oe-sidebar .oe-stagger {
          animation: oeStaggerIn 220ms cubic-bezier(0.2, 0.8, 0.2, 1) backwards;
        }
        /* Hover-arrow: a subtle right-pointing chevron that fades in
           on hover - hints "click to navigate" without taking space
           when idle. The opacity transition keeps the layout stable. */
        .oe-sidebar a .oe-hover-arrow {
          opacity: 0;
          transform: translateX(-4px);
          transition: opacity 0.18s ease, transform 0.18s ease;
        }
        .oe-sidebar a:hover .oe-hover-arrow,
        .oe-sidebar a:focus-visible .oe-hover-arrow {
          opacity: 0.55;
          transform: translateX(0);
        }
        /* Pin button on items - invisible until item is hovered, then
           fades in from the right. Click does not navigate (handled by
           preventDefault + stopPropagation in the handler). */
        .oe-sidebar a .oe-pin-btn {
          opacity: 0;
          transition: opacity 0.18s ease, color 0.18s ease;
        }
        .oe-sidebar a:hover .oe-pin-btn,
        .oe-sidebar a:focus-within .oe-pin-btn,
        .oe-sidebar a .oe-pin-btn[data-pinned="true"] {
          opacity: 1;
        }
      `}</style>

      {/* Logo + mobile close button. The desktop collapse/expand
          toggle lives as a floating pill on the right edge — see the
          <CollapseTab/> right below — not in the header. */}
      <div
        className={clsx(
          'relative flex h-header items-center px-5',
          iconified ? 'justify-center px-0' : 'justify-between',
        )}
      >
        {/* Brand block — white-labellable. When the user has set a
            custom logo or company name (via the pencil-on-hover edit
            affordance), this renders their brand large with a small
            "powered by OpenConstructionERP" attribution beneath. */}
        <CustomBranding iconified={iconified} />
        {!iconified && onClose && (
          <button
            onClick={onClose}
            className="lg:hidden flex h-7 w-7 min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            aria-label={t('common.close')}
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* Floating collapse/expand tab — pill-shaped, half-protruding
          from the right edge of the sidebar at vertical centre.
          Desktop-only (mobile uses overlay drawer with its own X).
          Same button toggles both directions; the chevron flips to
          show which way the click will move the panel. */}
      <button
        onClick={toggleIconified}
        aria-label={
          iconified
            ? t('sidebar.expand', { defaultValue: 'Expand sidebar' })
            : t('sidebar.collapse', { defaultValue: 'Collapse sidebar' })
        }
        title={
          iconified
            ? t('sidebar.expand', { defaultValue: 'Expand sidebar' })
            : t('sidebar.collapse', { defaultValue: 'Collapse sidebar' })
        }
        className={clsx(
          // Position: vertical centre, sitting on the outer border with
          // half its width protruding into the main content area.
          // LTR → outer = right; RTL → outer = left.
          'hidden lg:flex absolute top-1/2 z-10',
          isRTL ? 'left-0' : 'right-0',
          // Size + shape: tall pill, narrow.
          'h-12 w-5 items-center justify-center rounded-full',
          // Surface: clean white with a subtle ring; hover lifts to the
          // brand colour. Smooth transition on both background and the
          // chevron rotation, so the toggle feels intentional.
          'border border-border-light bg-surface-primary text-content-tertiary shadow-sm',
          'hover:border-oe-blue hover:bg-oe-blue hover:text-white hover:shadow-md hover:shadow-oe-blue/20',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
          'transition-all duration-200 ease-oe',
        )}
        style={{
          // Manual translate: Tailwind has no logical translate-x, so
          // we compose Y-centre and X-protrude in one transform.
          // RTL flips the X sign so the pill still protrudes outward.
          transform: isRTL
            ? 'translateY(-50%) translateX(-50%)'
            : 'translateY(-50%) translateX(50%)',
        }}
      >
        <ChevronRight
          size={12}
          strokeWidth={2.5}
          className={clsx(
            'transition-transform duration-200 ease-oe',
            // The chevron always points in the direction the click will
            // move the panel. In RTL the outward direction flips, so
            // the rotation logic flips too.
            isRTL
              ? iconified
                ? 'rotate-180'
                : 'rotate-0'
              : iconified
                ? 'rotate-0'
                : 'rotate-180',
          )}
        />
      </button>

      {/* Search-as-jumper — modern-SaaS-style. Triggers the existing global
          semantic-search palette. Keeps the visible affordance for
          users who don't know the ⌘K shortcut, while still surfacing
          it for those who do. When iconified, collapses to a single
          icon button — the ⌘K shortcut still works regardless. */}
      <div className={clsx('pt-1 pb-1', iconified ? 'px-2 flex justify-center' : 'px-3')}>
        <button
          type="button"
          onClick={() => openSearch()}
          className={clsx(
            'group flex items-center gap-2 rounded-md border border-border-light bg-surface-secondary/60 text-[12px] text-content-tertiary hover:border-content-quaternary/30 hover:bg-surface-secondary hover:text-content-secondary transition-colors',
            iconified ? 'h-8 w-8 justify-center' : 'w-full px-2.5 py-1.5',
          )}
          aria-label={t('common.search', { defaultValue: 'Search' })}
          title={iconified ? t('common.search', { defaultValue: 'Search' }) : undefined}
        >
          <Search size={13} strokeWidth={1.75} className="shrink-0" />
          {!iconified && (
            <>
              <span className="truncate">
                {t('common.search', { defaultValue: 'Search' })}
              </span>
              <kbd className="ms-auto hidden sm:inline-flex items-center gap-0.5 rounded border border-border-light bg-surface-primary px-1 py-px text-[9px] font-medium text-content-quaternary group-hover:text-content-tertiary">
                ⌘K
              </kbd>
            </>
          )}
        </button>
      </div>

      {/* Main navigation — grouped with collapsible headers.
          role="navigation" + aria-label make this an addressable
          landmark for screen readers; previously the sidebar was just
          a div soup with no landmark, so AT users could not jump to
          the nav region (WCAG 2.4.1 + 1.3.1, Round 2 Wave D audit). */}
      <nav
        role="navigation"
        aria-label={t('sidebar.main_navigation', { defaultValue: 'Main navigation' })}
        className={clsx(
          'flex-1 overflow-y-auto pt-2 pb-3',
          iconified ? 'px-2' : 'px-3',
        )}
        data-engine="cwicr"
      >
        {/* Pinned section — appears at the top when the user has
            pinned at least one item. No collapsible chevron; just a
            small label + the pinned items in their stored order. */}
        {pinnedItems.length > 0 && (
          <div className="mb-2">
            {!iconified && (
              <div className="mt-2 mb-0.5 flex items-center gap-1.5 px-2.5">
                <Pin size={9} strokeWidth={2.25} className="text-content-quaternary" />
                <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                  {t('nav.pinned', { defaultValue: 'Pinned' })}
                </span>
              </div>
            )}
            <ul className="space-y-0.5">
              {pinnedItems.map((item, i) => (
                <li
                  key={item.to}
                  className="oe-stagger"
                  style={{ animationDelay: `${i * 18}ms` }}
                >
                  <SidebarItem
                    item={item}
                    label={t(item.labelKey)}
                    onClick={onClose}
                    badge={badgeMap[item.to]}
                    isPinned={true}
                    onTogglePin={togglePin}
                    activeRoute={activeRoute}
                    iconified={iconified}
                    editMode={editMode}
                    isItemHidden={editingHidden.includes(item.to)}
                    onToggleHidden={toggleItemHidden}
                  />
                </li>
              ))}
            </ul>
            {iconified && (
              <div className="my-2 mx-auto h-px w-6 bg-border-light" aria-hidden />
            )}
          </div>
        )}
        {/* Project focus is applied IN PLACE inside the original groups
            below — there is NO separate "project route" section and no
            reordering. Each row is only annotated: needed → sequence
            number; not needed → smaller + greyed; unconstrained → as
            default. Focus OFF / no profile → every row is default. */}
        {navGroups.map((group) => {
          // Hide entire group in simple mode if flagged
          if (group.hideInSimple && !isAdvanced) return null;

          // Merge static items + dynamic module items for this group.
          // Most groups inject by their own `id`; `grp_reality` overrides
          // with `dynamicGroupKey: 'reality'` so `oe_pointcloud`'s manifest
          // can add its row via the documented `reality` registry key.
          const dynamicItems: NavItem[] = getModuleNavItems(group.dynamicGroupKey ?? group.id)
            .filter((mi) => {
              const moduleId = mi.labelKey.split('.')[1] ?? mi.to.slice(1);
              return isModuleEnabled(moduleId);
            })
            .map((mi) => ({
              labelKey: mi.labelKey,
              to: mi.to,
              icon: mi.icon,
              moduleKey: mi.to.slice(1), // e.g. '/sustainability' → 'sustainability'
              advancedOnly: mi.advancedOnly,
            }));

          // Filter by module-enabled + advanced mode + admin gate. The
          // menu keeps its original shape and order; project focus
          // never removes or reorders rows — it only annotates them
          // below. `adminOnly` items disappear for non-admin JWTs so
          // dev / internal surfaces (Architecture Map) don't clutter
          // a regular customer's sidebar — the route itself is also
          // wrapped in <AdminOnly> in App.tsx, so this is just keeping
          // the menu tidy.
          const allItems = [...group.items, ...dynamicItems];
          const visibleItems = allItems.filter((item) => {
            // The active Company Profile maps each route to a canonical module
            // key; when the profile leaves that module out, the row is hidden.
            // Inline `moduleKey` (e.g. dynamic plugin rows) is the fallback.
            // Routes absent from ROUTE_MODULE_KEY are never profile-gated.
            const moduleKey = ROUTE_MODULE_KEY[item.to.split('?')[0]!] ?? item.moduleKey;
            return (
              (!moduleKey || isModuleEnabled(moduleKey)) &&
              (!item.advancedOnly || isAdvanced) &&
              (!item.adminOnly || userRole === 'admin') &&
              // Backend-disabled gate — a System Module switched off on the
              // Modules page hides its sidebar route here so we never link
              // to a broken/blank surface.
              !isRouteBackendDisabled(item.to) &&
              // Menu-editor filter — in normal mode, drop user-hidden
              // rows; in edit mode `effectiveHidden` is empty so every
              // row renders (muted via the editingHidden state below).
              !effectiveHidden.includes(item.to)
            );
          });

          // Skip group if no visible items. In normal mode this means
          // "every item in this group is user-hidden or unavailable" —
          // so the group header itself disappears (per spec). In edit
          // mode `effectiveHidden` is empty, so users can always reach
          // any group to re-enable rows inside it.
          if (visibleItems.length === 0) return null;

          const isCollapsed = collapsed[group.id] ?? false;

          return (
            <Fragment key={group.id}>
              {group.separator && (
                <div
                  className="my-3 mx-auto h-px w-10/12 bg-border-light/70"
                  aria-hidden
                />
              )}
            <NavGroupSection
              label={t(group.labelKey, { defaultValue: group.defaultLabel ?? group.id })}
              isCollapsed={isCollapsed}
              onToggle={() => toggleGroup(group.id)}
              iconified={iconified}
            >
              <ul className="space-y-0.5">
                {visibleItems.map((item, i) => {
                  // In-place project-focus annotation (no reorder):
                  //   g === null      → route not profile-constrained →
                  //                      render exactly as the default.
                  //   g.enabled       → project needs it → sequence #.
                  //   g.enabled false → not needed → smaller + greyed.
                  const g =
                    gate.active && !iconified ? gate.byRoute(item.to) : null;
                  const notNeeded = g != null && !g.enabled;
                  const needed = g != null && g.enabled;
                  const seq = needed ? (routeSeq += 1) : null;
                  // Module-presence dimming: modules with no data for
                  // this project render at 55 % opacity so users see at
                  // a glance which surfaces are populated. Only applies
                  // when project-focus is OFF (project-focus already
                  // greys-out unrelated rows more strongly via opacity-45).
                  const isEmptyForProject =
                    !notNeeded && !modulePresence.isPopulated(item.to);
                  return (
                    <li
                      key={item.to}
                      className={clsx(
                        'oe-stagger',
                        notNeeded && 'opacity-45',
                        isEmptyForProject && 'opacity-55',
                      )}
                      style={{ animationDelay: `${i * 18}ms` }}
                    >
                      <SidebarItem
                        item={item}
                        label={t(item.labelKey)}
                        onClick={onClose}
                        badge={badgeMap[item.to]}
                        seq={seq}
                        compact={notNeeded}
                        isPinned={pinned.includes(item.to)}
                        onTogglePin={togglePin}
                        activeRoute={activeRoute}
                        iconified={iconified}
                        editMode={editMode}
                        isItemHidden={editingHidden.includes(item.to)}
                        onToggleHidden={toggleItemHidden}
                      />
                    </li>
                  );
                })}
              </ul>
            </NavGroupSection>
            </Fragment>
          );
        })}
        {/* Menu editor controls — sit just above the add-module tiles so
             users see them after scanning their actual menu. Iconified
             mode hides this row entirely (no room for text and the
             editor is mouse-driven on the visible labels anyway). In
             normal mode: a small "Edit menu" ghost button + a "{N}
             hidden" badge when applicable. In edit mode the buttons
             flip to Save / Cancel. */}
        {!iconified && (
          <div className="pt-3 pb-1 px-3">
            {editMode ? (
              <div className="flex items-center gap-1.5 w-full">
                <button
                  type="button"
                  onClick={saveEditMode}
                  className="flex-1 flex items-center justify-center gap-1 rounded-lg border border-oe-blue/30 bg-oe-blue/10 px-2.5 py-2 text-xs font-medium text-oe-blue hover:bg-oe-blue/15 transition-colors"
                >
                  <Check size={12} strokeWidth={2.25} />
                  <span>{t('sidebar.save', { defaultValue: 'Save' })}</span>
                </button>
                <button
                  type="button"
                  onClick={cancelEditMode}
                  className="flex-1 flex items-center justify-center gap-1 rounded-lg border border-border-light bg-surface-secondary/60 px-2.5 py-2 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
                >
                  <X size={12} strokeWidth={2.25} />
                  <span>{t('sidebar.cancel', { defaultValue: 'Cancel' })}</span>
                </button>
                {editingHidden.length > 0 && (
                  <span className="shrink-0 text-2xs text-content-tertiary tabular-nums">
                    {t('sidebar.hidden_count', {
                      defaultValue: '{{count}} hidden',
                      count: editingHidden.length,
                    })}
                  </span>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-1.5 w-full">
                <button
                  type="button"
                  onClick={enterEditMode}
                  className="flex-1 flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-border-light bg-surface-secondary/30 px-2.5 py-2 text-xs font-medium text-content-secondary hover:border-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
                  title={t('sidebar.edit_menu_hint', {
                    defaultValue: "Hide items you don't use",
                  })}
                >
                  <Pencil size={12} strokeWidth={2} />
                  <span>{t('sidebar.edit_menu', { defaultValue: 'Edit menu' })}</span>
                </button>
                {hiddenModules.length > 0 && (
                  <span
                    className="shrink-0 rounded-full bg-surface-tertiary/70 px-1.5 py-px text-[10px] font-medium text-content-tertiary tabular-nums"
                    title={t('sidebar.show_hidden', { defaultValue: 'Show hidden' })}
                  >
                    {t('sidebar.hidden_count', {
                      defaultValue: '{{count}} hidden',
                      count: hiddenModules.length,
                    })}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
        {/* Add-a-module CTA — dashed-border tile with a plus icon. Sits at
             the very end of the main nav groups so it reads as "keep going,
             there's more — build your own". Navigates into the in-app
             developer guide rather than to the marketplace, which gives
             contributors a clearer first step. When iconified, shrinks
             to a centred icon-only square — the dashed border still
             signals "add something". */}
        <div className={clsx('pt-2 pb-1', iconified ? 'px-0 flex justify-center' : 'px-3')}>
          <NavLink
            to="/modules/developer-guide"
            onClick={onClose}
            title={iconified ? t('nav.add_module', { defaultValue: 'Add module' }) : undefined}
            className={clsx(
              'group flex items-center rounded-lg border border-dashed border-oe-blue/40 bg-gradient-to-br from-oe-blue/5 via-transparent to-blue-50/40 dark:from-oe-blue/10 dark:via-transparent dark:to-slate-900/30 hover:border-oe-blue hover:from-oe-blue/10 hover:shadow-sm transition-all',
              iconified ? 'h-9 w-9 justify-center' : 'gap-2.5 px-2.5 py-2',
            )}
          >
            <span className="shrink-0 flex h-7 w-7 items-center justify-center rounded-md bg-oe-blue/10 text-oe-blue group-hover:bg-oe-blue group-hover:text-white transition-colors">
              <Plus size={14} strokeWidth={2.5} />
            </span>
            {!iconified && (
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-semibold text-content-primary leading-tight">
                  {t('nav.add_module', { defaultValue: 'Add module' })}
                </span>
                <span className="block text-[10px] text-content-tertiary leading-tight mt-0.5 truncate">
                  {t('nav.add_module_hint', { defaultValue: 'Build your own · developer guide' })}
                </span>
              </span>
            )}
          </NavLink>
        </div>
        {/* Request-a-custom-module CTA — second dashed tile, purple
             accent, opens a popup instead of navigating. The popup
             routes the request to two destinations depending on the
             user's choice:
               • "Could help others too"  → community / GitHub backlog
                 → ends up in a future open-source release.
               • "Only for my company"    → private / bespoke quote
                 → DDC team replies with scope + price.
             We keep this distinct from the developer-guide tile above
             on purpose: contributors who want to build a module
             themselves use the guide; users who want us to build it
             for them use this dialog. */}
        <div className={clsx('pt-1 pb-3', iconified ? 'px-0 flex justify-center' : 'px-3')}>
          <button
            type="button"
            onClick={() => {
              setCustomModuleOpen(true);
              onClose?.();
            }}
            title={
              iconified
                ? t('nav.request_custom_module', { defaultValue: 'Request a custom module' })
                : undefined
            }
            className={clsx(
              'group flex items-center rounded-lg border border-dashed border-purple-400/40 bg-gradient-to-br from-purple-500/5 via-transparent to-purple-50/40 dark:from-purple-500/10 dark:via-transparent dark:to-slate-900/30 hover:border-purple-500 hover:from-purple-500/10 hover:shadow-sm transition-all text-left',
              iconified ? 'h-9 w-9 justify-center' : 'w-full gap-2.5 px-2.5 py-2',
            )}
            aria-haspopup="dialog"
            aria-expanded={customModuleOpen}
          >
            <span className="shrink-0 flex h-7 w-7 items-center justify-center rounded-md bg-purple-100 dark:bg-purple-900/40 text-purple-600 dark:text-purple-300 group-hover:bg-purple-600 group-hover:text-white transition-colors">
              <Sparkles size={14} strokeWidth={2.25} />
            </span>
            {!iconified && (
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-semibold text-content-primary leading-tight">
                  {t('nav.request_custom_module', {
                    defaultValue: 'Request a custom module',
                  })}
                </span>
                <span className="block text-[10px] text-content-tertiary leading-tight mt-0.5 truncate">
                  {t('nav.request_custom_module_hint', {
                    defaultValue: 'Missing something? Tell us what you need',
                  })}
                </span>
              </span>
            )}
          </button>
        </div>
      </nav>

      {/* Admin / setup surfaces — rendered as a 2-column button grid
          (1-column in icon-only mode). Soft hairline separator + subtle
          paper-tint background as before. The grid keeps Users / Audit
          Log / Permissions / Modules / Settings / About visually grouped
          and out of the project-work nav flow above. */}
      <div
        className={clsx(
          'relative py-2 bg-black/[0.02] dark:bg-white/[0.02]',
          iconified ? 'px-2' : 'px-2',
        )}
      >
        <div
          className={clsx(
            'absolute top-0 h-px bg-gradient-to-r from-transparent via-border to-transparent',
            iconified ? 'left-2 right-2' : 'left-3 right-3',
          )}
        />
        <AdminGrid
          items={visibleAdminGridItems}
          activeRoute={activeRoute}
          iconified={iconified}
          onNavigate={onClose}
        />

        {/* Update notification — compact clickable card in the sidebar; the
            whole card opens a full-screen modal with highlights + install
            commands when the user clicks it. Hidden in icon-only mode
            because the card is text-heavy; users will still see it after
            expanding the sidebar. `mt-3` breathes the card away from the
            admin grid buttons above. */}
        {!iconified && (
          <div className="mt-3">
            <UpdateNotification />
          </div>
        )}

        {/* Version + AGPL + GitHub link
            Layout: GitHub icon (left) · version · AGPL link.
            The GitHub link uses Lucide's Github mark — keeps the row aligned
            with the rest of the sidebar's lucide icons and gives a clear
            visual entry point to the source repo. */}
        {iconified ? (
          // Icon-only footer: GitHub + Telegram stacked. The expand
          // toggle lives on the floating edge-pill, not down here, so
          // users see only one toggle entry-point — no duplicate UI.
          <div className="pt-2 pb-1 flex flex-col items-center gap-1">
            <a
              href="https://github.com/datadrivenconstruction/OpenConstructionERP"
              target="_blank"
              rel="noopener noreferrer"
              title={`${t('sidebar.github_repo', { defaultValue: 'GitHub repository' })} (v${APP_VERSION})`}
              aria-label={t('sidebar.github_repo', { defaultValue: 'GitHub repository' })}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border-light bg-surface-primary hover:bg-surface-elevated transition-all"
            >
              <Github size={13} strokeWidth={1.75} className="text-content-secondary" />
            </a>
            <a
              href="https://t.me/datadrivenconstruction"
              target="_blank"
              rel="noopener noreferrer"
              title={t('sidebar.community_title', { defaultValue: 'Community' })}
              aria-label={t('sidebar.telegram_community', { defaultValue: 'Telegram community' })}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border-light bg-surface-primary hover:bg-surface-elevated transition-all"
            >
              <svg viewBox="0 0 24 24" fill="currentColor" className="h-[13px] w-[13px] text-content-secondary" aria-hidden>
                <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71l-4.14-3.06-1.99 1.93c-.23.23-.42.42-.83.42z" />
              </svg>
            </a>
          </div>
        ) : (
          // GitHub / Community / version row.
          //
          // The horizontal padding here MUST mirror AdminGrid's column geometry
          // (the parent `<div>` already gives us `px-2`; AdminGrid's `<ul>` uses
          // `grid-cols-2 gap-1` with no extra inner padding). Earlier this row
          // wrapped its buttons in another `px-2`, which made each button
          // ~8 px narrower than every admin tile above. The buttons are now
          // siblings of the admin grid in the layout coordinate space:
          // same outer `px-2`, same `gap-1` between the two cards.
          <div className="pb-2 pt-1 flex flex-col gap-1.5">
            <div className="grid grid-cols-2 gap-1">
              <a
                href="https://github.com/datadrivenconstruction/OpenConstructionERP"
                target="_blank"
                rel="noopener noreferrer"
                title={t('sidebar.github_repo', { defaultValue: 'GitHub repository' })}
                aria-label={t('sidebar.github_repo', { defaultValue: 'GitHub repository' })}
                className={clsx(
                  'group flex h-8 w-full items-center justify-start gap-1.5 rounded-md border px-2 text-left transition-colors duration-fast ease-oe',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                  'border-border-light/60 bg-surface-primary text-content-secondary hover:bg-surface-secondary hover:text-content-primary hover:border-border-medium',
                )}
              >
                <Github size={14} strokeWidth={1.75} aria-hidden className="shrink-0 text-content-secondary" />
                <span className="min-w-0 flex-1 text-[11px] font-medium leading-none whitespace-nowrap overflow-hidden text-ellipsis text-content-secondary">
                  GitHub
                </span>
              </a>
              <a
                href="https://t.me/datadrivenconstruction"
                target="_blank"
                rel="noopener noreferrer"
                title={t('sidebar.join_telegram', { defaultValue: 'Join the Telegram community' })}
                aria-label={t('sidebar.telegram_community', { defaultValue: 'Telegram community' })}
                className={clsx(
                  'group flex h-8 w-full items-center justify-start gap-1.5 rounded-md border px-2 text-left transition-colors duration-fast ease-oe',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                  'border-border-light/60 bg-surface-primary text-content-secondary hover:bg-surface-secondary hover:text-content-primary hover:border-border-medium',
                )}
              >
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-[14px] w-[14px] shrink-0 text-content-secondary" aria-hidden>
                  <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71l-4.14-3.06-1.99 1.93c-.23.23-.42.42-.83.42z" />
                </svg>
                <span className="min-w-0 flex-1 text-[11px] font-medium leading-none whitespace-nowrap overflow-hidden text-ellipsis text-content-secondary">
                  {t('sidebar.community_title', { defaultValue: 'Community' })}
                </span>
              </a>
            </div>
            <div className="flex items-center justify-center gap-1.5 min-w-0">
              <span className="text-2xs text-content-tertiary">v{APP_VERSION}</span>
              <span className="text-2xs text-content-quaternary/40">·</span>
              <a
                href="/api/source"
                target="_blank"
                rel="noopener noreferrer"
                className="text-2xs text-content-tertiary hover:text-content-secondary transition-colors"
              >
                AGPL-3.0
              </a>
            </div>
          </div>
        )}
      </div>
      {/* Mounted at the aside root so the dialog escapes any
          z-index / overflow trap imposed by the inner nav scroller.
          The dialog itself is full-screen modal (fixed inset-0) and
          self-renders only when open=true. */}
      <RequestCustomModuleDialog
        open={customModuleOpen}
        onClose={() => setCustomModuleOpen(false)}
      />
    </aside>
  );
}

function NavGroupSection({
  label,
  isCollapsed,
  onToggle,
  children,
  iconified,
}: {
  label: string;
  isCollapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  iconified?: boolean;
}) {
  const { t } = useTranslation();
  // In icon-only mode there is no room for the group header chevron;
  // we surface group boundaries as a thin centred hairline and keep
  // the items always-expanded (per-group collapse is irrelevant when
  // labels aren't visible).
  if (iconified) {
    return (
      <div className="mb-1">
        <div className="my-1.5 mx-auto h-px w-6 bg-border-light/60" aria-hidden />
        {children}
      </div>
    );
  }
  // Expanded sidebar — render a clear section header with a subtle dot
  // glyph on the leading edge (modern-SaaS-style "rest" indicator) so the
  // grouping reads as a list, not a wall of indistinguishable rows.
  // Header is a real button so the entire row toggles the section, and
  // keyboard focus shows a clean ring without bleeding outside the
  // padded box.
  return (
    <div className="mt-3 mb-0.5">
      <button
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        aria-label={
          isCollapsed
            ? t('common.expand_section', { defaultValue: 'Expand {{label}}', label })
            : t('common.collapse_section', { defaultValue: 'Collapse {{label}}', label })
        }
        className={clsx(
          'mb-0.5 flex w-full items-center justify-between gap-2 rounded-md',
          'px-2 py-1 group cursor-pointer text-left',
          'hover:bg-surface-secondary/60 focus-visible:outline-none',
          'focus-visible:ring-1 focus-visible:ring-oe-blue/40',
          'transition-colors duration-150',
        )}
      >
        <span className="flex items-center gap-1.5 min-w-0">
          {/* Small leading dot — provides a calm visual rhythm down the
              sidebar so users can pick out group starts at a glance. */}
          <span
            className={clsx(
              'h-1 w-1 rounded-full shrink-0 transition-colors duration-150',
              isCollapsed
                ? 'bg-content-quaternary/45 group-hover:bg-content-tertiary'
                : 'bg-oe-blue/55 group-hover:bg-oe-blue',
            )}
            aria-hidden
          />
          <span className="text-[10px] font-semibold uppercase tracking-[0.085em] text-content-tertiary group-hover:text-content-secondary transition-colors truncate">
            {label}
          </span>
        </span>
        <ChevronDown
          size={11}
          strokeWidth={2}
          className={clsx(
            'shrink-0 text-content-quaternary group-hover:text-content-secondary',
            'transition-transform duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)]',
            isCollapsed && '-rotate-90',
          )}
          aria-hidden
        />
      </button>
      {!isCollapsed && children}
    </div>
  );
}

function SidebarItem({
  item,
  label,
  onClick,
  badge: numericBadge,
  seq,
  isPinned,
  onTogglePin,
  activeRoute,
  iconified,
  compact,
  editMode,
  isItemHidden,
  onToggleHidden,
}: {
  item: NavItem;
  label: string;
  onClick?: () => void;
  badge?: number;
  seq?: number | null;
  isPinned?: boolean;
  onTogglePin?: (route: string) => void;
  activeRoute?: string | null;
  iconified?: boolean;
  compact?: boolean;
  /** When true, the row is in menu-editor mode and shows an Eye / EyeOff
   *  toggle instead of the pin button. Hidden rows render dimmed so the
   *  user can see at a glance what will be filtered out on Save. */
  editMode?: boolean;
  isItemHidden?: boolean;
  onToggleHidden?: (route: string) => void;
}) {
  const { t } = useTranslation();
  const Icon = item.icon;
  const kbdHint = KBD_HINTS[item.to];
  const tourTestId = PRODUCT_TOUR_NAV_TESTIDS[item.to];

  // Route-transition feedback: while THIS row's destination is loading
  // (history pushed, React location not yet committed — see
  // navigationProgress.ts) swap the icon for a spinner. Boolean selector
  // so only the affected row re-renders. Items that pin a query string
  // ("/boq?tab=…") must match it exactly; plain items match pathname.
  const itemPath = item.to.split('?')[0];
  const isPendingTarget = useNavPendingStore((s) => {
    if (!s.pendingPath) return false;
    return item.to.includes('?')
      ? s.pendingPath === item.to
      : s.pendingPath.split('?')[0] === itemPath;
  });

  const handlePinClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onTogglePin?.(item.to);
  };

  const handleHiddenClick = (e: React.MouseEvent) => {
    // Eye-toggle inside the row must NEVER navigate — the row is still
    // a NavLink so a bubbled click would otherwise route the user away
    // from wherever they're currently editing the menu.
    e.preventDefault();
    e.stopPropagation();
    onToggleHidden?.(item.to);
  };

  // Single source of truth for active state — Sidebar picks one winning
  // route across all visible items, so only the most-specific match
  // lights up (no more "/bim" + "/bim/rules" both glowing blue).
  const isActive = activeRoute === item.to;
  const hasQuery = item.to.includes('?');

  // Icon-only branch — short-circuits the full row layout. Native
  // `title` surfaces the label on hover; the active-state dot replaces
  // the 2px accent bar (which would clip the centred icon at 48px wide).
  if (iconified) {
    const hasBadge =
      (numericBadge != null && numericBadge > 0) || Boolean(item.badge);
    return (
      <NavLink
        to={item.to}
        end={item.to === '/' || hasQuery}
        onClick={onClick}
        title={label}
        aria-label={label}
        {...(item.tourId ? { 'data-tour': item.tourId } : {})}
        {...(tourTestId ? { 'data-testid': tourTestId } : {})}
        className={() =>
          clsx(
            'relative mx-auto flex h-9 w-9 items-center justify-center rounded-md transition-colors duration-fast ease-oe',
            isActive
              ? 'bg-oe-blue/[0.14] text-oe-blue shadow-[inset_0_0_0_1px_rgba(0,122,255,0.18)] dark:bg-oe-blue/25'
              : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
            editMode && isItemHidden && 'opacity-50',
          )
        }
      >
        {isPendingTarget ? (
          <Loader2 size={16} className="oe-nav-spinner text-oe-blue" />
        ) : (
          <Icon size={16} strokeWidth={isActive ? 2 : 1.75} />
        )}
        {hasBadge && (
          <span
            className={clsx(
              'absolute top-1 right-1 h-1.5 w-1.5 rounded-full',
              isActive ? 'bg-oe-blue' : 'bg-semantic-error/80',
            )}
            aria-hidden
          />
        )}
      </NavLink>
    );
  }

  return (
      <NavLink
        to={item.to}
        end={item.to === '/' || hasQuery}
        onClick={(e) => {
          // In edit mode the row is a "hide/show this item" target —
          // navigating away while the user is curating the menu would
          // be jarring and lose the unsaved working set. We swallow
          // navigation here and let the trailing eye-toggle handle
          // the actual state change instead.
          if (editMode) {
            e.preventDefault();
            onToggleHidden?.(item.to);
            return;
          }
          onClick?.();
        }}
        title={label}
        {...(item.tourId ? { 'data-tour': item.tourId } : {})}
        {...(tourTestId ? { 'data-testid': tourTestId } : {})}
        className={() => {
          const active = isActive;
          return clsx(
            // 2px transparent left border on every item — when active
            // it flips to oe-blue. No layout shift between states. The
            // accent bar is the entire visual change for "active",
            // alongside the subtle background tint and bolded label.
            // This is the modern-SaaS pattern — solid, calm, fast.
            'relative flex items-center rounded-md border-l-2 border-transparent',
            'transition-colors duration-fast ease-oe',
            compact
              ? 'gap-1.5 pl-2 pr-1.5 py-[3px] text-[12px]'
              : 'gap-2 pl-[10px] pr-2.5 py-1 text-[13px]',
            item.highlight && !active
              ? 'font-medium bg-gradient-to-r from-[#7c3aed]/10 to-[#0ea5e9]/10 text-[#6d28d9] hover:from-[#7c3aed]/15 hover:to-[#0ea5e9]/15'
              : active
                ? 'font-semibold border-oe-blue bg-oe-blue/[0.14] text-oe-blue shadow-[inset_0_0_0_1px_rgba(0,122,255,0.06)] dark:bg-oe-blue/25'
                : 'font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
            editMode && isItemHidden && 'opacity-50',
          );
        }}
      >
        {/* Project-focus sequence number — only set for rows the active
            project needs (focus mode on). A small leading chip so the
            menu reads as a numbered route while keeping its order. */}
        {seq != null && (
          <span
            className={clsx(
              'shrink-0 flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-[10px] font-bold tabular-nums transition-colors',
              isActive
                ? 'bg-oe-blue text-white'
                : 'bg-oe-blue-subtle text-oe-blue-text',
            )}
            aria-hidden
          >
            {seq}
          </span>
        )}
        {isPendingTarget ? (
          <Loader2
            size={compact ? 14 : 16}
            className="oe-nav-spinner shrink-0 text-oe-blue"
          />
        ) : (
          <Icon size={compact ? 14 : 16} strokeWidth={isActive ? 2 : 1.75} className="shrink-0" />
        )}
        {/* Hover-tooltip via title falls back to the full label even when
            CSS truncates with an ellipsis. The visible width is now
            264px (was 232) so most labels render in full at default
            zoom; this is the safety net for narrow sidebars / dense
            translations / large-text accessibility settings. */}
        <span className="truncate" title={label}>
          {label}
        </span>
        {/* Right-edge cluster — kbd hint first, badges last, so the
            BETA / NEW chips always sit at the absolute right margin
            (flush against the row edge) instead of being pushed inward
            by the fixed-width keyboard hint column. Reserve the 26px
            kbd column ONLY when this row actually has a shortcut —
            empty rows previously paid the same 26px tax for nothing,
            squeezing the label width and triggering avoidable
            ellipsis truncation. */}
        <span className={clsx('ms-auto flex items-center shrink-0', compact ? 'gap-1 ps-1' : 'gap-1.5 ps-1.5')}>
          {!compact && (
            <span
              className={clsx(
                'hidden lg:inline-flex justify-end items-center gap-0.5 text-[9px] font-medium tracking-wide tabular-nums',
                kbdHint ? 'min-w-[26px]' : 'min-w-0',
                isActive ? 'text-oe-blue/60' : 'text-content-quaternary',
              )}
            >
              {kbdHint ?? (
                <ChevronRight
                  size={12}
                  className="oe-hover-arrow text-content-tertiary"
                />
              )}
            </span>
          )}
          {numericBadge != null && numericBadge > 0 && (
            <span
              className={clsx(
                'flex h-4 min-w-[1.25rem] items-center justify-center rounded-full text-2xs font-bold px-1 transition-colors',
                isActive
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-tertiary text-content-secondary',
              )}
            >
              {numericBadge > 99 ? '99+' : numericBadge}
            </span>
          )}
          {item.badge && (
            <span
              className={clsx(
                item.badge === 'BETA'
                  ? 'text-[9px] font-medium uppercase tracking-wide px-1.5 py-px rounded text-content-quaternary bg-surface-tertiary/60 dark:bg-surface-tertiary/40'
                  : item.highlight
                    ? 'text-2xs font-semibold px-1.5 py-0.5 rounded-full bg-gradient-to-r from-[#7c3aed] to-[#0ea5e9] text-white'
                    : 'text-2xs font-semibold px-1.5 py-0.5 rounded-full text-content-tertiary',
              )}
            >
              {item.badge === 'BETA' ? 'beta' : item.badge}
            </span>
          )}
        </span>
        {/* Edit-mode wins over pin — when the user is curating the menu,
            the trailing slot becomes a persistent Eye/EyeOff toggle so
            they can hide/show every item in one click. Normal mode
            falls back to the pin button. */}
        {editMode && onToggleHidden ? (
          <button
            type="button"
            onClick={handleHiddenClick}
            data-pinned="true"
            aria-label={
              isItemHidden
                ? t('sidebar.show_item', { defaultValue: 'Show {{label}}', label })
                : t('sidebar.hide_item', { defaultValue: 'Hide {{label}}', label })
            }
            title={
              isItemHidden
                ? t('sidebar.show_item', { defaultValue: 'Show {{label}}', label })
                : t('sidebar.hide_item', { defaultValue: 'Hide {{label}}', label })
            }
            className={clsx(
              'oe-pin-btn ms-1 flex h-4 w-4 shrink-0 items-center justify-center rounded',
              'text-content-quaternary hover:text-oe-blue hover:bg-oe-blue/10',
              isItemHidden && 'text-content-quaternary/70',
            )}
          >
            {isItemHidden ? (
              <EyeOff size={10} strokeWidth={2} />
            ) : (
              <Eye size={10} strokeWidth={2} />
            )}
          </button>
        ) : (
          /* Pin / unpin button — only shown when the item supports it
             (any item with an onTogglePin handler). Visible on hover or
             persistently when pinned. Click does not navigate. */
          onTogglePin && (
            <button
              type="button"
              onClick={handlePinClick}
              data-pinned={isPinned ? 'true' : undefined}
              aria-label={
                isPinned
                  ? t('nav.unpin', { defaultValue: 'Unpin {{label}}', label })
                  : t('nav.pin', { defaultValue: 'Pin {{label}}', label })
              }
              title={isPinned ? t('nav.unpin', { defaultValue: 'Unpin' }) : t('nav.pin', { defaultValue: 'Pin' })}
              className={clsx(
                'oe-pin-btn ms-1 flex h-4 w-4 shrink-0 items-center justify-center rounded',
                'text-content-quaternary hover:text-oe-blue hover:bg-oe-blue/10',
                isPinned && 'text-oe-blue',
              )}
            >
              {isPinned ? <PinOff size={10} strokeWidth={2} /> : <Pin size={10} strokeWidth={2} />}
            </button>
          )
        )}
      </NavLink>
  );
}

/** 2-column button grid for admin/setup surfaces (Users, Audit Log,
 *  Permissions Matrix, Modules, Settings, About). Renders pinned at the
 *  bottom of the sidebar above the GitHub/version footer.
 *
 *  Layout:
 *    - Expanded sidebar  → grid-cols-2, square-ish tiles with icon
 *                          stacked above the label.
 *    - Iconified sidebar → single column, icon-only tiles (same width
 *                          as the rest of the iconified rail).
 *
 *  Active route uses the same translucent oe-blue highlight as the
 *  iconified branch of `SidebarItem`, so the visual language is
 *  consistent across the whole sidebar. */
function AdminGrid({
  items,
  activeRoute,
  iconified,
  onNavigate,
}: {
  items: NavItem[];
  activeRoute?: string | null;
  iconified?: boolean;
  onNavigate?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  if (iconified) {
    // Icon-only rail — stack as a single column, matching the rest of
    // the iconified sidebar (each tile is 36×36 like SidebarItem).
    return (
      <ul className="flex flex-col items-center gap-1">
        {items.map((item) => {
          const Icon = item.icon;
          const isActive = activeRoute === item.to;
          const label = t(item.labelKey);
          return (
            <li key={item.to}>
              <NavLink
                to={item.to}
                onClick={onNavigate}
                title={label}
                aria-label={label}
                className={() =>
                  clsx(
                    'relative flex h-9 w-9 items-center justify-center rounded-md transition-colors duration-fast ease-oe',
                    isActive
                      ? 'bg-oe-blue/[0.14] text-oe-blue shadow-[inset_0_0_0_1px_rgba(0,122,255,0.18)] dark:bg-oe-blue/25'
                      : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                  )
                }
              >
                <Icon size={16} strokeWidth={isActive ? 2 : 1.75} aria-hidden />
              </NavLink>
            </li>
          );
        })}
      </ul>
    );
  }

  // Expanded mode: 2×N grid. Each tile is a real <button> so keyboard
  // focus + Enter activation Just Work; we navigate imperatively so the
  // button retains semantics (NavLink renders as <a>, which would
  // confuse screen readers that expect a button grid).
  return (
    <ul className="grid grid-cols-2 gap-1">
      {items.map((item) => {
        const Icon = item.icon;
        const isActive = activeRoute === item.to;
        const label = t(item.labelKey);
        return (
          <li key={item.to}>
            <button
              type="button"
              onClick={() => {
                navigate(item.to);
                onNavigate?.();
              }}
              aria-label={label}
              aria-current={isActive ? 'page' : undefined}
              title={label}
              className={clsx(
                'group flex h-8 w-full items-center justify-start gap-1.5 rounded-md border px-2 text-left transition-colors duration-fast ease-oe',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                isActive
                  ? 'border-transparent bg-oe-blue/[0.14] text-oe-blue shadow-[inset_0_0_0_1px_rgba(0,122,255,0.18)] dark:bg-oe-blue/25'
                  : 'border-border-light/60 bg-surface-primary text-content-secondary hover:bg-surface-secondary hover:text-content-primary hover:border-border-medium',
              )}
            >
              <Icon size={14} strokeWidth={isActive ? 2 : 1.75} aria-hidden className="shrink-0" />
              <span className="min-w-0 flex-1 text-[11px] font-medium leading-none whitespace-nowrap overflow-hidden text-ellipsis">
                {label}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

const RECENT_TYPE_ICONS: Record<string, LucideIcon> = {
  project: FolderOpen,
  boq: Table2,
  schedule: CalendarDays,
  task: ClipboardList,
  rfi: HelpCircle,
  contact: Users,
};

/** Floating Recent button — rendered by AppLayout in the bottom-right corner. */
export function FloatingRecentButton() {
  const { t } = useTranslation();
  const recentItems = useRecentStore((s) => s.items);
  const [open, setOpen] = useState(false);

  if (recentItems.length === 0) return null;
  const displayed = recentItems.slice(0, 5);

  return (
    // Smaller, slightly higher than the Chat FAB so they stack visually
    <div className="fixed bottom-24 end-4 z-40">
      {/* Popover */}
      {open && (
        <div className="absolute bottom-12 end-0 w-72 rounded-xl border border-border-light bg-surface-primary shadow-xl overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-150">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-light">
            <span className="text-xs font-semibold text-content-primary">{t('nav.recent', { defaultValue: 'Recent' })}</span>
            <button
              onClick={() => setOpen(false)}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              title={t('common.close', { defaultValue: 'Close' })}
              className="p-0.5 rounded text-content-tertiary hover:text-content-primary"
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
          <ul className="py-1.5 max-h-60 overflow-y-auto">
            {displayed.map((item) => {
              const Icon = RECENT_TYPE_ICONS[item.type] || FolderOpen;
              return (
                <li key={item.id}>
                  <NavLink
                    to={item.url}
                    onClick={() => setOpen(false)}
                    title={item.title}
                    className="flex items-center gap-2.5 px-4 py-2 text-[13px] font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-all"
                  >
                    <Icon size={14} strokeWidth={1.75} className="shrink-0 text-content-tertiary" />
                    <span className="truncate flex-1">{item.title}</span>
                    <span className="text-[10px] text-content-quaternary shrink-0 tabular-nums">
                      {new Date(item.visitedAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* FAB button */}
      <button
        onClick={() => setOpen((p) => !p)}
        aria-label={t('nav.recent', { defaultValue: 'Recent' })}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={clsx(
          'w-10 h-10 rounded-full flex items-center justify-center shadow-lg border transition-all duration-200 hover:scale-105 active:scale-95',
          open
            ? 'bg-oe-blue text-white border-oe-blue shadow-oe-blue/20'
            : 'bg-surface-primary text-content-secondary border-border-light hover:border-oe-blue/30 hover:text-oe-blue',
        )}
        title={t('nav.recent', { defaultValue: 'Recent' })}
      >
        <History size={18} strokeWidth={2} aria-hidden="true" />
      </button>
    </div>
  );
}

