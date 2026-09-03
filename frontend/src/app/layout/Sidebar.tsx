// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useEffect, useMemo, useRef, Fragment } from 'react';
import { useQuery } from '@tanstack/react-query';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { CustomBranding } from './CustomBranding';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  FolderOpen,
  Table2,
  CalendarDays,
  Boxes,
  Settings,
  Info,
  ChevronDown,
  ChevronRight,
  X,
  ClipboardList,
  Users,
  HelpCircle,
  History,
  Plus,
  Search,
  Pin,
  PinOff,
  Eye,
  EyeOff,
  Pencil,
  Check,
  Loader2,
  type LucideIcon,
} from 'lucide-react';
import { navGroups, type NavItem } from './navCatalog';
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
import { useHiddenModules } from '@/shared/hooks/useHiddenModules';
import { useIsRTL } from '@/shared/hooks/useIsRTL';
import { useI18nReady } from '@/shared/lib/useI18nReady';
import {
  useSidebarCollapseStore,
  SIDEBAR_WIDTH_FULL,
  SIDEBAR_WIDTH_ICON,
} from '@/stores/useSidebarCollapseStore';
import {
  useActiveProjectProfile,
  buildModuleGate,
} from '@/features/projects/useProjectProfile';
import { getIntlLocale } from '@/shared/lib/formatters';



/** An admin-grid tile. Extends NavItem with an optional `onClick`: when set,
 *  the tile runs that action in place instead of navigating to `to`. Used for
 *  the "Edit menu" tile, whose `to` is a non-routable sentinel. */
type AdminGridItem = NavItem & { onClick?: () => void };



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
// Modules (/modules) and Governance (/governance) intentionally no longer
// appear as their own sidebar tiles - they are reached from inside Settings
// (Settings -> Modules / Governance links), which declutters the left menu.
// Their routes stay live, so any deep link or the Settings entries still work.
// Audit Log used to sit here as a role-gated tile. It moved into Settings
// (Settings -> Audit log, Manager+ only) so the admin grid stays short and
// the security surfaces live together under Settings. Its route
// (`/admin/audit-log`) stays live for deep links. The slot it vacated now
// holds the "Edit menu" action tile (see `editMenuGridItem` below), which
// opens the sidebar customiser in place.
const adminGridItems: NavItem[] = [
  { labelKey: 'sidebar.admin_grid.settings', to: '/settings', icon: Settings },
  { labelKey: 'sidebar.admin_grid.users', to: '/users', icon: Users },
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
  '/payment-clock': 'oe_payment_clock',
  '/tax-withholding': 'oe_tax_withholding',
  '/einvoice-clearance': 'oe_einvoice_clearance',
  '/cost-match': 'oe_cost_match',
  '/full-evm': 'oe_full_evm',
  '/fx': 'oe_fx',
  '/subcontractors': 'oe_subcontractors',
  '/bid-management': 'oe_bid_management',
  '/tendering': 'oe_tendering',
  '/variations': 'oe_variations',
  '/moc': 'oe_moc',
  '/supplier-catalogs': 'oe_supplier_catalogs',
  '/design-options': 'oe_design_options',
  '/formwork': 'oe_formwork',
  // Real estate development
  '/property-dev': 'oe_property_dev',
  '/accommodation': 'oe_accommodation',
  // Planning
  '/schedule': 'oe_schedule',
  '/schedule-advanced': 'oe_schedule_advanced',
  '/portfolio': 'oe_portfolio',
  '/takt': 'oe_schedule_advanced',
  '/tasks': 'oe_tasks',
  '/5d': 'oe_costmodel',
  '/risks': 'oe_risk',
  // Field operations
  '/daily-diary': 'oe_daily_diary',
  '/field-reports': 'oe_fieldreports',
  '/field-time': 'oe_field_time',
  '/equipment': 'oe_equipment',
  '/resources': 'oe_resources',
  '/payroll': 'oe_payroll',
  '/certified-payroll': 'oe_certified_payroll',
  '/service': 'oe_service',
  '/portal': 'oe_portal',
  // Quality
  '/validation': 'oe_validation',
  '/inspections': 'oe_inspections',
  '/construction-control': 'oe_construction_control',
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
  '/inbound-email': 'oe_inbound_email',
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
  // v10.6.0 modules
  '/prefab': 'oe_prefab',
  '/cvr': 'oe_cvr',
  '/site-logistics': 'oe_site_logistics',
  '/commissioning': 'oe_commissioning',
  '/esg': 'oe_esg',
  '/forms': 'oe_forms',
  // Delivery-lifecycle registers (v11.11 backend, surfaced in this wave).
  '/site-prep': 'oe_site_prep',
  '/site-inventory': 'oe_site_inventory',
  '/postcalc': 'oe_postcalc',
  '/temporary-works': 'oe_temporary_works',
  '/interface-management': 'oe_interface_management',
  '/defects-liability': 'oe_defects_liability',
  // International delivery / authority modules (frontends added this wave).
  '/authority-submissions': 'oe_authority_submission',
  '/review-authority': 'oe_review_authority',
  '/signing': 'oe_signing',
  '/source-data': 'oe_source_data',
  '/project-route': 'oe_project_route',
  '/site-supervision': 'oe_site_supervision',
};

// localStorage key for collapsed state
const COLLAPSED_KEY = 'oe_sidebar_collapsed_v2';
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

/** localStorage key for per-route click counts. Purely a client-side
 *  convenience: the counts colour the most-travelled rows so a busy menu
 *  reads at a glance. Never synced to the server. */
const USAGE_KEY = 'oe_nav_usage';

function readUsage(): Record<string, number> {
  try {
    const raw = localStorage.getItem(USAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') return parsed as Record<string, number>;
    }
  } catch {
    /* ignore */
  }
  return {};
}

function writeUsage(map: Record<string, number>) {
  try {
    localStorage.setItem(USAGE_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

/** How strongly a row is accented from its click history. */
export type NavHeat = 'hot' | 'warm' | null;

/** Rank routes by click count: the top 3 well-used routes go 'hot'
 *  (orange accent), the next 5 'warm' (amber). A route needs at least
 *  3 recorded visits before it earns any colour, so a fresh install -
 *  or an accidental click - never lights anything up. */
function computeHeat(usage: Record<string, number>): Record<string, NavHeat> {
  const ranked = Object.entries(usage)
    .filter(([, n]) => n >= 3)
    .sort((a, b) => b[1] - a[1]);
  const out: Record<string, NavHeat> = {};
  ranked.slice(0, 3).forEach(([route]) => (out[route] = 'hot'));
  ranked.slice(3, 8).forEach(([route]) => (out[route] = 'warm'));
  return out;
}

/** localStorage key for MANUAL row colours assigned in Edit menu
 *  (right-click a row). A manual colour outranks the automatic usage
 *  heat; the special value 'none' suppresses colour on that row
 *  entirely. */
const NAV_COLORS_KEY = 'oe_nav_colors';

/** The named accents a row can carry - the automatic tiers reuse the
 *  same visual language. Literal class strings on purpose: Tailwind's
 *  scanner must see them in source. */
const ACCENT_CLASSES: Record<string, string> = {
  hot: 'border-orange-500/80 bg-orange-500/[0.06] text-content-primary',
  warm: 'border-amber-400/70 bg-amber-400/[0.05]',
  orange: 'border-orange-500/80 bg-orange-500/[0.07] text-content-primary',
  amber: 'border-amber-400/80 bg-amber-400/[0.07]',
  blue: 'border-sky-500/70 bg-sky-500/[0.07]',
  green: 'border-emerald-500/70 bg-emerald-500/[0.07]',
  purple: 'border-violet-500/70 bg-violet-500/[0.07]',
  red: 'border-rose-500/70 bg-rose-500/[0.07]',
};

/** Swatch colours for the edit-menu colour picker (right-click a row). */
const ACCENT_SWATCHES: Record<string, string> = {
  orange: '#f97316',
  amber: '#fbbf24',
  blue: '#0ea5e9',
  green: '#10b981',
  purple: '#8b5cf6',
  red: '#f43f5e',
};

function readNavColors(): Record<string, string> {
  try {
    const raw = localStorage.getItem(NAV_COLORS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') return parsed as Record<string, string>;
    }
  } catch {
    /* ignore */
  }
  return {};
}

function writeNavColors(map: Record<string, string>) {
  try {
    localStorage.setItem(NAV_COLORS_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

/** localStorage key for the user's own ordering of the nav sections
 *  (Edit menu up/down arrows). Ids missing from the saved list keep
 *  their catalog order, after the ordered ones. */
const GROUP_ORDER_KEY = 'oe_group_order';

function readGroupOrder(): string[] {
  try {
    const raw = localStorage.getItem(GROUP_ORDER_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.filter((g): g is string => typeof g === 'string');
    }
  } catch {
    /* ignore */
  }
  return [];
}

function writeGroupOrder(arr: string[]) {
  try {
    localStorage.setItem(GROUP_ORDER_KEY, JSON.stringify(arr));
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
  // The sidebar mounts at app boot, outside any Suspense boundary, exactly
  // like the Header. Under StrictMode's double-mount, `useTranslation`'s own
  // store subscription can be churned away and miss the bundle-added event
  // when a lazy locale chunk lands, freezing the nav on the English fallback.
  // This external-store subscription survives the remount and forces a
  // re-render whenever a bundle is merged; the returned value is unused.
  useI18nReady();
  const navigate = useNavigate();
  const location = useLocation();
  const { isModuleEnabled } = useModuleStore();
  // Subscribed separately so the module-count summary at the foot of the nav
  // recomputes whenever a module is switched on or off.
  const enabledModules = useModuleStore((s) => s.enabledModules);
  // Hidden whole-sections (nav groups) the user has switched off via the
  // "Edit menu". Persisted in useModuleStore alongside module state; here we
  // read the list and the bulk setter the Save action commits to.
  const hiddenGroups = useModuleStore((s) => s.hiddenGroups);
  const setHiddenGroups = useModuleStore((s) => s.setHiddenGroups);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const setViewMode = useViewModeStore((s) => s.setMode);
  const badgeCounts = useSidebarBadges();
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
  // this is just to keep the sidebar tidy for non-admin users. The
  // hidden-state filter is applied further down (once `editMode` and
  // `hiddenModules` are in scope) so these bottom tiles can be hidden and
  // restored through the same Edit menu gesture as the nav rows.
  const roleVisibleAdminGridItems = adminGridItems.filter(
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

  // Per-route click counts -> colour accents on the busiest rows.
  const [usage, setUsage] = useState<Record<string, number>>(() => readUsage());
  const heatByRoute = useMemo(() => computeHeat(usage), [usage]);
  const recordNav = useCallback((route: string) => {
    setUsage((prev) => {
      const next = { ...prev, [route]: (prev[route] ?? 0) + 1 };
      writeUsage(next);
      return next;
    });
  }, []);

  // Manual colour overrides (Edit menu, right-click a row). A manual
  // colour outranks the usage heat; 'none' silences a row completely.
  const [navColors, setNavColors] = useState<Record<string, string>>(() => readNavColors());
  const setRowColor = useCallback((route: string, color: string | null) => {
    setNavColors((prev) => {
      const next = { ...prev };
      if (color === null) delete next[route];
      else next[route] = color;
      writeNavColors(next);
      return next;
    });
  }, []);
  const accentFor = useCallback(
    (route: string): string | null => {
      const manual = navColors[route];
      if (manual === 'none') return null;
      if (manual && ACCENT_CLASSES[manual]) return manual;
      const heat = heatByRoute[route];
      return heat ?? null;
    },
    [navColors, heatByRoute],
  );

  // Right-click colour picker, only while the menu editor is open.
  const [colorMenu, setColorMenu] = useState<{ x: number; y: number; route: string; label: string } | null>(null);
  const openColorMenu = useCallback((route: string, label: string, x: number, y: number) => {
    setColorMenu({ x, y, route, label });
  }, []);

  // User-chosen section order (Edit menu up/down). Sections the user has
  // never moved keep their catalog order, after the ordered ones.
  const [groupOrder, setGroupOrder] = useState<string[]>(() => readGroupOrder());
  const orderedNavGroups = useMemo(() => {
    if (groupOrder.length === 0) return navGroups;
    const rank = new Map(groupOrder.map((id, i) => [id, i]));
    return [...navGroups]
      .map((g, catalogIdx) => ({ g, key: rank.has(g.id) ? rank.get(g.id)! : groupOrder.length + catalogIdx }))
      .sort((a, b) => a.key - b.key)
      .map((x) => x.g);
  }, [groupOrder]);
  const moveGroup = useCallback(
    (groupId: string, dir: -1 | 1) => {
      const ids = orderedNavGroups.map((g) => g.id);
      const i = ids.indexOf(groupId);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j]!, ids[i]!];
      writeGroupOrder(ids);
      setGroupOrder(ids);
    },
    [orderedNavGroups],
  );

  // ── Menu editor state ───────────────────────────────────────────────
  // `hiddenModules` is the *persisted* set — drives which rows are
  // filtered out of the rendered nav in normal mode. Persistence is
  // owned by `useHiddenModules()`: server-side per-user with localStorage
  // as instant cache + offline fallback (multi-device safe).
  // `editMode` is the transient "Edit menu" toggle.
  // `editingHidden` is the in-memory working copy users edit while in
  // edit mode; only committed to `hiddenModules` on Save.
  // Two independent working copies: one for individual rows (`editingHidden`,
  // routes) and one for whole sections (`editingHiddenGroups`, group ids).
  // Both are seeded on entry and committed together on Save, so hiding a
  // module and hiding a section share one Save/Cancel gesture.
  const { hiddenModules, setHiddenModules } = useHiddenModules();
  const [editMode, setEditMode] = useState(false);
  // Leaving the menu editor closes any open colour picker with it.
  useEffect(() => {
    if (!editMode) setColorMenu(null);
  }, [editMode]);
  const [editingHidden, setEditingHidden] = useState<string[]>([]);
  const [editingHiddenGroups, setEditingHiddenGroups] = useState<string[]>([]);

  const enterEditMode = useCallback(() => {
    setEditingHidden(hiddenModules);
    setEditingHiddenGroups(hiddenGroups);
    setEditMode(true);
  }, [hiddenModules, hiddenGroups]);

  const cancelEditMode = useCallback(() => {
    setEditMode(false);
    setEditingHidden([]);
    setEditingHiddenGroups([]);
  }, []);

  const saveEditMode = useCallback(() => {
    setHiddenModules(editingHidden);
    setHiddenGroups(editingHiddenGroups);
    setEditMode(false);
    setEditingHidden([]);
    setEditingHiddenGroups([]);
  }, [editingHidden, editingHiddenGroups, setHiddenModules, setHiddenGroups]);

  const toggleItemHidden = useCallback((route: string) => {
    setEditingHidden((prev) =>
      prev.includes(route) ? prev.filter((r) => r !== route) : [...prev, route],
    );
  }, []);

  // Flip a whole section's hidden state inside the working copy. Committed to
  // the store (and localStorage) only when the user hits Save.
  const toggleGroupHidden = useCallback((groupId: string) => {
    setEditingHiddenGroups((prev) =>
      prev.includes(groupId) ? prev.filter((g) => g !== groupId) : [...prev, groupId],
    );
  }, []);

  // Set used by the render loop to decide whether to hide a row. In edit
  // mode the user sees EVERYTHING (so they can re-enable items) — only
  // normal mode actually filters. The visual "muted" state is driven by
  // `editingHidden` so re-enabled rows visually un-mute immediately.
  const effectiveHidden = editMode ? [] : hiddenModules;
  // Same idea for whole sections: in normal mode a hidden group (its header
  // and every row) drops out entirely; in edit mode this is empty so the
  // group still renders — dimmed — and the user can switch it back on.
  const effectiveHiddenGroups = editMode ? [] : hiddenGroups;

  // Bottom admin/setup tiles (Settings, Users, Modules, Governance, Audit,
  // About). In edit mode we render every role-visible tile so hidden ones
  // can be toggled back on; in normal mode the ones the user hid drop out.
  // They share the same `hiddenModules` route list as the nav rows, so a
  // hidden tile counts toward the "{N} hidden" badge and the single
  // Save/Cancel gesture covers rows, sections and these tiles together.
  const visibleAdminGridItems = editMode
    ? roleVisibleAdminGridItems
    : roleVisibleAdminGridItems.filter((item) => !hiddenModules.includes(item.to));

  // "Edit menu" action tile — fills the slot the Audit Log tile vacated when
  // it moved into Settings. Clicking it opens the sidebar customiser in place
  // (the same edit gesture whose Save / Cancel controls appear below the nav
  // list). It is an action, not a route, so it carries `onClick` and a
  // non-routable `to` sentinel, and it is dropped in edit mode (you are
  // already editing). Slotted just before the About tile so the grid reads
  // Settings · Users · Edit menu · About.
  const editMenuGridItem: AdminGridItem = {
    labelKey: 'sidebar.edit_menu',
    to: '__edit_menu__',
    icon: Pencil,
    onClick: enterEditMode,
  };
  const adminGridWithEdit: AdminGridItem[] = useMemo(() => {
    if (editMode) return visibleAdminGridItems;
    const aboutIdx = visibleAdminGridItems.findIndex((item) => item.to === '/about');
    if (aboutIdx === -1) return [...visibleAdminGridItems, editMenuGridItem];
    return [
      ...visibleAdminGridItems.slice(0, aboutIdx),
      editMenuGridItem,
      ...visibleAdminGridItems.slice(aboutIdx),
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editMode, visibleAdminGridItems, enterEditMode]);

  // Module counter shown at the foot of the nav (before the "Add module"
  // tile): how many module rows are visible in the menu right now versus how
  // many the platform offers this user. "Total" counts every leaf menu row
  // (static + dynamically registered module rows) the user is allowed to see
  // (admin-only dev surfaces excluded for non-admins), regardless of whether
  // it is currently switched on or hidden. "Shown" applies the same normal-mode
  // visibility filter the nav render uses, so the pair updates live as modules
  // are enabled/disabled or hidden/shown via Edit menu. It intentionally
  // mirrors the predicate in the `navGroups.map` below; keep the two in step.
  const moduleCounts = useMemo(() => {
    let total = 0;
    let shown = 0;
    for (const group of navGroups) {
      const groupHidden = hiddenGroups.includes(group.id);
      const groupHiddenInSimple = Boolean(group.hideInSimple) && !isAdvanced;
      const dynamicItems = getModuleNavItems(group.dynamicGroupKey ?? group.id).map((mi) => ({
        to: mi.to,
        moduleKey: mi.to.slice(1),
        advancedOnly: mi.advancedOnly,
        adminOnly: false,
      }));
      const staticItems = group.items.map((it) => ({
        to: it.to,
        moduleKey: it.moduleKey,
        advancedOnly: it.advancedOnly,
        adminOnly: it.adminOnly,
      }));
      for (const item of [...staticItems, ...dynamicItems]) {
        // Admin-only rows are internal/dev surfaces, not product modules, so
        // they do not count toward the platform total for a regular user.
        if (item.adminOnly && userRole !== 'admin') continue;
        total += 1;
        const visible =
          !groupHidden &&
          !groupHiddenInSimple &&
          (!item.moduleKey || isModuleEnabled(item.moduleKey)) &&
          (!item.advancedOnly || isAdvanced) &&
          !isRouteBackendDisabled(item.to) &&
          !hiddenModules.includes(item.to);
        if (visible) shown += 1;
      }
    }
    return { total, shown };
    // `enabledModules` is a dep so the count reacts to enable/disable; it feeds
    // `isModuleEnabled` even though that function reference is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdvanced, userRole, hiddenModules, hiddenGroups, enabledModules, isRouteBackendDisabled]);


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
  const rawGate = buildModuleGate(activeProfile);
  // The sequence chips read as clutter to users who never asked for a
  // guided journey - a menu full of numbered badges is what "lost its
  // refinement" looks like. Numbering is now opt-in per browser
  // (localStorage 'oe_journey_numbers' = '1'); the profile gate itself
  // still works everywhere else it is used.
  let journeyNumbersOn = false;
  try {
    journeyNumbersOn = localStorage.getItem('oe_journey_numbers') === '1';
  } catch {
    /* ignore */
  }
  const gate = journeyNumbersOn ? rawGate : { ...rawGate, active: false };
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
                    label={t(item.labelKey, { defaultValue: item.defaultLabel })}
                    onClick={onClose}
                    badge={badgeMap[item.to]}
                    isPinned={true}
                    onTogglePin={togglePin}
                    activeRoute={activeRoute}
                    iconified={iconified}
                    editMode={editMode}
                    isItemHidden={editingHidden.includes(item.to)}
                    onToggleHidden={toggleItemHidden}
                    accent={accentFor(item.to)}
                    onNavRecord={recordNav}
                    onColorMenu={editMode ? openColorMenu : undefined}
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
        {orderedNavGroups.map((group, orderIdx) => {
          // Hide entire group in simple mode if flagged
          if (group.hideInSimple && !isAdvanced) return null;

          // Menu-editor: a section the user has hidden drops out completely
          // (header + every row) in normal mode. In edit mode
          // `effectiveHiddenGroups` is empty, so the section still renders and
          // shows dimmed via `editingHiddenGroups` (see NavGroupSection) with
          // an eye control to switch it back on.
          if (effectiveHiddenGroups.includes(group.id)) return null;

          // Merge static items + dynamic module items for this group.
          // Most groups inject by their own `id`; `grp_reality` overrides
          // with `dynamicGroupKey: 'reality'`.
          //
          // Nothing reaches this path today, which is worth knowing before
          // debugging a module whose row will not appear. Every id in the
          // catalogue is `grp_*` and the only `dynamicGroupKey` is
          // `reality`, while the two manifests that declare navItems name
          // `tools` (sustainability) and `ai` (pipelines) — neither is a
          // group id in this catalogue, so both lists are dropped and both
          // rows are carried statically there instead. This comment used
          // to credit `oe_pointcloud` with injecting into `reality`; it is
          // backend-only and has no manifest here. The mechanism itself
          // works — a module publishing to a real `grp_*` id lands — it is
          // simply unused in-tree.
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
            // A company profile (picked in onboarding, or switched on the
            // Modules > Company Profiles tab) now shapes the menu: a row whose
            // `moduleKey` maps to a module the profile disabled drops out, so
            // the sidebar matches the profile the company chose. Core modules
            // are never disabled and `isModuleEnabled` is fail-open, so nothing
            // essential disappears, and any module can be switched back on from
            // the Modules page. In menu-edit mode we skip this gate so every row
            // stays reachable to toggle. The per-project focus gate below only
            // annotates rows with a sequence number; it never drops them.
            return (
              (editMode || !item.moduleKey || isModuleEnabled(item.moduleKey)) &&
              (!item.advancedOnly || isAdvanced) &&
              (!item.adminOnly || userRole === 'admin') &&
              // Backend-disabled gate - a System Module a company admin has
              // explicitly switched off on the System Modules admin tab hides
              // its sidebar route here so we never link to a broken/blank
              // surface. This is an admin control, not the onboarding profile.
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
                  className="my-3 mx-auto h-px w-10/12 bg-border-light"
                  aria-hidden
                />
              )}
            <NavGroupSection
              label={t(group.labelKey, { defaultValue: group.defaultLabel ?? group.id })}
              description={
                group.descriptionKey
                  ? t(group.descriptionKey, {
                      defaultValue: group.defaultDescription ?? '',
                    })
                  : undefined
              }
              isCollapsed={isCollapsed}
              onToggle={() => toggleGroup(group.id)}
              iconified={iconified}
              editMode={editMode}
              isGroupHidden={editingHiddenGroups.includes(group.id)}
              onToggleGroupHidden={() => toggleGroupHidden(group.id)}
              onMoveUp={orderIdx > 0 ? () => moveGroup(group.id, -1) : undefined}
              onMoveDown={
                orderIdx < orderedNavGroups.length - 1 ? () => moveGroup(group.id, 1) : undefined
              }
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
                  // No opacity dimming: every visible nav row renders at full
                  // strength. Modules that are empty for the current project or
                  // outside the project focus are no longer greyed out, since
                  // the faded rows read as broken or disabled rather than as a
                  // hint. Project focus still annotates needed rows with a
                  // sequence number and keeps them compact.
                  return (
                    <li
                      key={item.to}
                      className="oe-stagger"
                      style={{ animationDelay: `${i * 18}ms` }}
                    >
                      <SidebarItem
                        item={item}
                        label={t(item.labelKey, { defaultValue: item.defaultLabel })}
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
                        accent={accentFor(item.to)}
                        onNavRecord={recordNav}
                        onColorMenu={editMode ? openColorMenu : undefined}
                      />
                    </li>
                  );
                })}
              </ul>
            </NavGroupSection>
            </Fragment>
          );
        })}
        {/* Menu editor controls — sit just above the add-module tiles.
             Iconified mode hides this row entirely (no room for text and the
             editor is mouse-driven on the visible labels anyway). The "Edit
             menu" entry point now lives in the admin grid tile below, so in
             normal mode this row only surfaces a "{N} hidden — show" restore
             chip when the user has hidden something; otherwise it renders
             nothing. In edit mode the row holds the Save / Cancel controls. */}
        {/* Normal-mode restore chip: a single "{N} hidden — show" control that
             reopens the editor so hidden items can be switched back on. The
             Save / Cancel controls for edit mode are NOT here - they live in a
             pinned bar directly beneath the "Edit menu" tile below (see the
             admin grid), so the user always finds them without scrolling to
             the end of the module list. */}
        {!iconified && !editMode && hiddenModules.length + hiddenGroups.length > 0 && (
          <div className="pt-3 pb-1 px-3">
            <button
              type="button"
              onClick={enterEditMode}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-border-light bg-surface-secondary/30 px-2.5 py-1.5 text-[11px] font-medium text-content-secondary hover:border-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              title={t('sidebar.show_hidden', { defaultValue: 'Show hidden' })}
            >
              <Eye size={12} strokeWidth={2} />
              <span>
                {t('sidebar.hidden_count', {
                  defaultValue: '{{count}} hidden',
                  count: hiddenModules.length + hiddenGroups.length,
                })}
              </span>
            </button>
          </div>
        )}
        {/* Module counter — a small live "{shown} of {total} modules" chip
             right before the Add-module tile, so a user can see at a glance
             how many modules are open in this menu and how many the platform
             offers in total. Updates automatically as modules are enabled /
             disabled or hidden / shown. Iconified mode shows a compact
             "shown/total" so the number is never lost. */}
        <div className={clsx('pt-2 pb-0.5', iconified ? 'px-1' : 'px-3')}>
          <div
            className={clsx(
              'flex items-center justify-center rounded-lg bg-surface-secondary/40 text-content-secondary',
              iconified ? 'px-1 py-1 gap-0.5' : 'gap-1.5 px-2.5 py-1.5',
            )}
            title={t('sidebar.module_count_title', {
              defaultValue: '{{shown}} of {{total}} modules are shown in this menu',
              shown: moduleCounts.shown,
              total: moduleCounts.total,
            })}
          >
            <Boxes
              size={iconified ? 13 : 12}
              strokeWidth={2}
              className="shrink-0 text-content-tertiary"
              aria-hidden
            />
            {iconified ? (
              <span className="text-[9px] font-semibold tabular-nums leading-none text-content-secondary">
                {moduleCounts.shown}/{moduleCounts.total}
              </span>
            ) : (
              <span className="text-[11px] font-medium tabular-nums">
                <span className="font-semibold text-content-primary">{moduleCounts.shown}</span>
                <span className="text-content-tertiary"> / {moduleCounts.total} </span>
                {t('sidebar.module_count_label', { defaultValue: 'modules' })}
              </span>
            )}
            {/* Manage-modules shortcut — a small gear button immediately to the
                 right of the "{shown} / {total} modules" count that jumps to the
                 Modules settings page, where modules can be switched on / off.
                 Hidden in iconified mode where horizontal room is tight. */}
            {!iconified && (
              <NavLink
                to="/modules"
                onClick={onClose}
                title={t('sidebar.manage_modules', { defaultValue: 'Manage modules' })}
                aria-label={t('sidebar.manage_modules', { defaultValue: 'Manage modules' })}
                className="ml-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              >
                <Settings size={12} strokeWidth={2} aria-hidden />
              </NavLink>
            )}
          </div>
        </div>
        {/* Edit-menu shortcut — deliberately the same action as the "Edit menu"
             tile in the admin grid further down, repeated here directly under
             the module count. That grid sits below the entire nav list, so on a
             long menu it is off screen at exactly the moment a user has just
             scrolled past thirty rows and concluded there are too many. Both
             entry points call `enterEditMode`, so whichever one is found first
             behaves identically. Dropped in edit mode, where the Save / Cancel
             bar has already taken over. */}
        {!editMode && (
          <div className={clsx('pt-1.5 pb-0.5', iconified ? 'px-1 flex justify-center' : 'px-3')}>
            <button
              type="button"
              onClick={enterEditMode}
              title={t('sidebar.edit_menu', { defaultValue: 'Edit menu' })}
              aria-label={iconified ? t('sidebar.edit_menu', { defaultValue: 'Edit menu' }) : undefined}
              className={clsx(
                'flex items-center rounded-lg border border-border-light bg-surface-secondary/30 text-content-secondary hover:border-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors',
                iconified ? 'h-7 w-7 justify-center' : 'w-full justify-center gap-1.5 px-2.5 py-1.5',
              )}
            >
              <Pencil size={12} strokeWidth={2} aria-hidden />
              {!iconified && (
                <span className="text-[11px] font-medium">
                  {t('sidebar.edit_menu', { defaultValue: 'Edit menu' })}
                </span>
              )}
            </button>
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
          items={adminGridWithEdit}
          activeRoute={activeRoute}
          iconified={iconified}
          onNavigate={onClose}
          editMode={editMode}
          hiddenSet={editingHidden}
          onToggleHidden={toggleItemHidden}
        />

        {/* Menu-editor action bar - pinned directly beneath the "Edit menu"
            tile so Save / Cancel stay in view the whole time the user is
            editing, instead of being buried at the end of the scrolling
            module list where they were easy to miss. Expanded sidebar only;
            iconified mode has no room and the editor needs the labels. */}
        {!iconified && editMode && (
          <div className="mt-2.5 flex items-center gap-1.5">
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
            {editingHidden.length + editingHiddenGroups.length > 0 && (
              <span className="shrink-0 text-2xs text-content-tertiary tabular-nums">
                {t('sidebar.hidden_count', {
                  defaultValue: '{{count}} hidden',
                  count: editingHidden.length + editingHiddenGroups.length,
                })}
              </span>
            )}
          </div>
        )}

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

        {/* Version + AGPL link. Vendor links (GitHub repo, Telegram
            community, article promo card) were removed from the shell; the
            licence link is an AGPL-3.0 obligation and stays, as does the
            running version so a support conversation can name the build. */}
        {iconified ? (
          <div className="pt-2 pb-1 flex flex-col items-center">
            <a
              href="/api/source"
              target="_blank"
              rel="noopener noreferrer"
              title={`AGPL-3.0 (v${APP_VERSION})`}
              className="text-[9px] font-medium text-content-tertiary hover:text-content-secondary transition-colors"
            >
              AGPL
            </a>
          </div>
        ) : (
          <div className="pb-2 pt-1 flex flex-col gap-1.5">
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
      {/* Edit-menu colour picker — opened by right-clicking a row while
          the menu editor is on. Manual colour outranks the automatic
          usage heat; the reset entries clear the click history that
          drives the automatic tier. */}
      {colorMenu && (
        <>
          <button
            type="button"
            aria-label={t('sidebar.close_color_menu', { defaultValue: 'Close colour menu' })}
            className="fixed inset-0 z-[75] cursor-default"
            onClick={() => setColorMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setColorMenu(null);
            }}
          />
          <div
            className="fixed z-[76] w-56 rounded-lg border border-border-light bg-surface-primary py-1 shadow-xl"
            style={{
              left: Math.min(colorMenu.x, window.innerWidth - 240),
              top: Math.min(colorMenu.y, window.innerHeight - 300),
            }}
          >
            <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-content-tertiary truncate">
              {colorMenu.label}
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5">
              {Object.entries(ACCENT_SWATCHES).map(([name, hex]) => (
                <button
                  key={name}
                  type="button"
                  title={name}
                  aria-label={name}
                  onClick={() => {
                    setRowColor(colorMenu.route, name);
                    setColorMenu(null);
                  }}
                  className={clsx(
                    'h-5 w-5 rounded-full border-2 transition-transform hover:scale-110',
                    navColors[colorMenu.route] === name ? 'border-content-primary' : 'border-transparent',
                  )}
                  style={{ backgroundColor: hex }}
                />
              ))}
            </div>
            <button
              type="button"
              className="flex w-full items-center px-3 py-1.5 text-left text-sm hover:bg-surface-secondary"
              onClick={() => {
                setRowColor(colorMenu.route, null);
                setColorMenu(null);
              }}
            >
              {t('sidebar.color_auto', { defaultValue: 'Automatic (by usage)' })}
            </button>
            <button
              type="button"
              className="flex w-full items-center px-3 py-1.5 text-left text-sm hover:bg-surface-secondary"
              onClick={() => {
                setRowColor(colorMenu.route, 'none');
                setColorMenu(null);
              }}
            >
              {t('sidebar.color_none', { defaultValue: 'No colour' })}
            </button>
            <div className="my-1 border-t border-border-light" />
            <button
              type="button"
              className="flex w-full items-center px-3 py-1.5 text-left text-sm hover:bg-surface-secondary"
              onClick={() => {
                setUsage((prev) => {
                  const next = { ...prev };
                  delete next[colorMenu.route];
                  writeUsage(next);
                  return next;
                });
                setColorMenu(null);
              }}
            >
              {t('sidebar.reset_clicks_one', { defaultValue: 'Reset click history (this link)' })}
            </button>
            <button
              type="button"
              className="flex w-full items-center px-3 py-1.5 text-left text-sm text-rose-600 hover:bg-surface-secondary"
              onClick={() => {
                setUsage(() => {
                  writeUsage({});
                  return {};
                });
                setColorMenu(null);
              }}
            >
              {t('sidebar.reset_clicks_all', { defaultValue: 'Reset click history (all links)' })}
            </button>
            <button
              type="button"
              className="flex w-full items-center px-3 py-1.5 text-left text-sm text-rose-600 hover:bg-surface-secondary"
              onClick={() => {
                setNavColors(() => {
                  writeNavColors({});
                  return {};
                });
                setColorMenu(null);
              }}
            >
              {t('sidebar.reset_colors_all', { defaultValue: 'Clear all manual colours' })}
            </button>
          </div>
        </>
      )}
    </aside>
  );
}

function NavGroupSection({
  label,
  description,
  isCollapsed,
  onToggle,
  children,
  iconified,
  editMode,
  isGroupHidden,
  onToggleGroupHidden,
  onMoveUp,
  onMoveDown,
}: {
  label: string;
  description?: string;
  isCollapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  iconified?: boolean;
  /** When true, the header shows an Eye / EyeOff control that hides or
   *  restores this whole section in one click, and the section renders
   *  dimmed while hidden — the section-level twin of the per-row toggle. */
  editMode?: boolean;
  isGroupHidden?: boolean;
  onToggleGroupHidden?: () => void;
  /** Edit-menu section reordering: move this whole section one slot up or
   *  down. Undefined at the ends of the list, so the arrow greys out. */
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}) {
  const { t } = useTranslation();
  // In icon-only mode there is no room for the group header chevron;
  // we surface group boundaries as a thin centred hairline and keep
  // the items always-expanded (per-group collapse is irrelevant when
  // labels aren't visible).
  if (iconified) {
    return (
      <div className="mb-1">
        <div className="my-1.5 mx-auto h-px w-6 bg-border-light" aria-hidden />
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
    <div className={clsx('mt-3 mb-0.5', editMode && isGroupHidden && 'opacity-50')}>
      {/* Header row — the collapse toggle plus, in Edit-menu mode, a
          section-level Eye / EyeOff control. Kept as sibling buttons (not
          nested) so both stay valid, focusable controls. */}
      <div className="mb-0.5 flex items-center gap-0.5">
      <button
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        aria-label={
          isCollapsed
            ? t('common.expand_section', { defaultValue: 'Expand {{label}}', label })
            : t('common.collapse_section', { defaultValue: 'Collapse {{label}}', label })
        }
        className={clsx(
          'flex flex-1 min-w-0 items-center justify-between gap-2 rounded-md',
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
                ? 'bg-content-quaternary group-hover:bg-content-tertiary'
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
      {editMode && (
        <>
          <button
            type="button"
            onClick={onMoveUp}
            disabled={!onMoveUp}
            aria-label={t('sidebar.move_group_up', { defaultValue: 'Move {{label}} up', label })}
            title={t('sidebar.move_group_up', { defaultValue: 'Move {{label}} up', label })}
            className={clsx(
              'flex h-6 w-5 shrink-0 items-center justify-center rounded-md transition-colors duration-150',
              onMoveUp
                ? 'text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10'
                : 'text-content-quaternary/40 cursor-default',
            )}
          >
            <ChevronDown size={12} strokeWidth={2} className="rotate-180" />
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={!onMoveDown}
            aria-label={t('sidebar.move_group_down', { defaultValue: 'Move {{label}} down', label })}
            title={t('sidebar.move_group_down', { defaultValue: 'Move {{label}} down', label })}
            className={clsx(
              'flex h-6 w-5 shrink-0 items-center justify-center rounded-md transition-colors duration-150',
              onMoveDown
                ? 'text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10'
                : 'text-content-quaternary/40 cursor-default',
            )}
          >
            <ChevronDown size={12} strokeWidth={2} />
          </button>
        </>
      )}
      {editMode && onToggleGroupHidden && (
        <button
          type="button"
          onClick={onToggleGroupHidden}
          aria-label={
            isGroupHidden
              ? t('sidebar.show_group', { defaultValue: 'Show {{label}} section', label })
              : t('sidebar.hide_group', { defaultValue: 'Hide {{label}} section', label })
          }
          title={
            isGroupHidden
              ? t('sidebar.show_group', { defaultValue: 'Show {{label}} section', label })
              : t('sidebar.hide_group', { defaultValue: 'Hide {{label}} section', label })
          }
          className={clsx(
            'flex h-6 w-6 shrink-0 items-center justify-center rounded-md',
            'text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10',
            'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-oe-blue/40',
            'transition-colors duration-150',
          )}
        >
          {isGroupHidden ? (
            <EyeOff size={12} strokeWidth={2} />
          ) : (
            <Eye size={12} strokeWidth={2} />
          )}
        </button>
      )}
      </div>
      {!isCollapsed && description && (
        <p className="mb-1 px-2 text-[10px] leading-snug text-content-quaternary">
          {description}
        </p>
      )}
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
  accent,
  onNavRecord,
  onColorMenu,
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
  /** Colour accent on the row: an automatic usage tier ('hot'/'warm') or
   *  a manually assigned colour name. Active state wins visually. */
  accent?: string | null;
  onNavRecord?: (route: string) => void;
  /** Edit-menu colour picker: right-clicking the row opens it. Only
   *  passed while the menu editor is open. */
  onColorMenu?: (route: string, label: string, x: number, y: number) => void;
}) {
  const { t } = useTranslation();
  const Icon = item.icon;
  const kbdHint = KBD_HINTS[item.to];
  const tourTestId = PRODUCT_TOUR_NAV_TESTIDS[item.to];
  // Hover tooltip: label, plus the "when to use this" one-liner when the
  // item defines one (procurement look-alikes, #280). Kept on one line.
  const helpText = item.helpKey
    ? t(item.helpKey, { defaultValue: item.defaultHelp ?? '' })
    : '';
  const titleText = helpText ? `${label} - ${helpText}` : label;

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
        onClick={() => {
          onNavRecord?.(item.to);
          onClick?.();
        }}
        title={titleText}
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
          onNavRecord?.(item.to);
          onClick?.();
        }}
        onContextMenu={
          onColorMenu
            ? (e) => {
                // Edit-menu colour picker — the browser menu would cover it.
                e.preventDefault();
                e.stopPropagation();
                onColorMenu(item.to, label, e.clientX, e.clientY);
              }
            : undefined
        }
        title={titleText}
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
            // Colour accent — automatic usage tier or a manually assigned
            // colour (Edit menu right-click). Rendered in edit mode too,
            // so assigning a colour shows its effect immediately; only the
            // blue active treatment outranks it.
            !active && accent && ACCENT_CLASSES[accent],
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
        {/* One line, truncated. v16 let labels wrap to two lines (German
            compound words), which turned an English menu ragged - rows of
            uneven height read as unfinished. The title tooltip carries the
            full label for anything that truncates. */}
        <span className="min-w-0 truncate leading-snug" title={label}>
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
              title={
                isPinned
                  ? t('nav.unpin', { defaultValue: 'Unpin {{label}}', label })
                  : t('nav.pin', { defaultValue: 'Pin {{label}}', label })
              }
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
  editMode,
  hiddenSet,
  onToggleHidden,
}: {
  /** Admin-grid tiles. Most are plain routes (`to`); a tile may instead
   *  carry an `onClick` to run an in-place action (e.g. the "Edit menu"
   *  tile that opens the sidebar customiser) rather than navigate. */
  items: AdminGridItem[];
  activeRoute?: string | null;
  iconified?: boolean;
  onNavigate?: () => void;
  /** When true, each tile becomes a hide/show target: clicking it toggles
   *  the tile's hidden state instead of navigating, it dims while hidden,
   *  and an Eye / EyeOff indicator shows its state. Mirrors the per-row
   *  editor on the nav list so the whole menu curates in one gesture. */
  editMode?: boolean;
  hiddenSet?: string[];
  onToggleHidden?: (route: string) => void;
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
          const label = t(item.labelKey, { defaultValue: item.defaultLabel });
          const tileClass = clsx(
            'relative flex h-9 w-9 items-center justify-center rounded-md transition-colors duration-fast ease-oe',
            isActive
              ? 'bg-oe-blue/[0.14] text-oe-blue shadow-[inset_0_0_0_1px_rgba(0,122,255,0.18)] dark:bg-oe-blue/25'
              : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
          );
          // Action tiles (e.g. "Edit menu") run in place — render a button so
          // they never navigate and don't close the drawer.
          if (item.onClick) {
            return (
              <li key={item.to}>
                <button
                  type="button"
                  onClick={item.onClick}
                  title={label}
                  aria-label={label}
                  className={tileClass}
                >
                  <Icon size={16} strokeWidth={1.75} aria-hidden />
                </button>
              </li>
            );
          }
          return (
            <li key={item.to}>
              <NavLink
                to={item.to}
                onClick={onNavigate}
                title={label}
                aria-label={label}
                className={() => tileClass}
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
  // confuse screen readers that expect a button grid). In edit mode the
  // tile stops navigating and instead toggles its own hidden state, dims
  // while hidden and shows an Eye / EyeOff indicator — the bottom-cluster
  // twin of the per-row editor above.
  return (
    <ul className="grid grid-cols-2 gap-1">
      {items.map((item) => {
        const Icon = item.icon;
        const isActive = activeRoute === item.to;
        const label = t(item.labelKey, { defaultValue: item.defaultLabel });
        const editable = editMode && !!onToggleHidden;
        const isHidden = editable ? (hiddenSet?.includes(item.to) ?? false) : false;
        const editLabel = isHidden
          ? t('sidebar.show_item', { defaultValue: 'Show {{label}}', label })
          : t('sidebar.hide_item', { defaultValue: 'Hide {{label}}', label });
        return (
          <li key={item.to}>
            <button
              type="button"
              onClick={() => {
                if (editable) {
                  onToggleHidden!(item.to);
                  return;
                }
                // Action tile (e.g. "Edit menu") runs in place; keep the
                // drawer open so the customiser it toggles stays visible.
                if (item.onClick) {
                  item.onClick();
                  return;
                }
                navigate(item.to);
                onNavigate?.();
              }}
              aria-label={editable ? editLabel : label}
              aria-current={!editMode && isActive ? 'page' : undefined}
              aria-pressed={editable ? isHidden : undefined}
              title={editable ? editLabel : label}
              className={clsx(
                'group flex h-8 w-full items-center justify-start gap-1.5 rounded-md border px-2 text-left transition-colors duration-fast ease-oe',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                isActive && !editMode
                  ? 'border-transparent bg-oe-blue/[0.14] text-oe-blue shadow-[inset_0_0_0_1px_rgba(0,122,255,0.18)] dark:bg-oe-blue/25'
                  : 'border-border-light/60 bg-surface-primary text-content-secondary hover:bg-surface-secondary hover:text-content-primary hover:border-border-medium dark:border-border-light/40 dark:bg-transparent dark:hover:bg-surface-secondary/60',
                isHidden && 'opacity-50',
              )}
            >
              <Icon
                size={14}
                strokeWidth={isActive && !editMode ? 2 : 1.75}
                aria-hidden
                className="shrink-0"
              />
              <span className="min-w-0 flex-1 text-[11px] font-medium leading-none whitespace-nowrap overflow-hidden text-ellipsis">
                {label}
              </span>
              {editable && (
                <span aria-hidden className="shrink-0 text-content-quaternary">
                  {isHidden ? <EyeOff size={11} strokeWidth={2} /> : <Eye size={11} strokeWidth={2} />}
                </span>
              )}
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
        <div className="absolute bottom-12 end-0 w-72 rounded-xl border border-border-light bg-surface-primary shadow-xl overflow-hidden">
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
                      {new Date(item.visitedAt).toLocaleTimeString(getIntlLocale(), { hour: '2-digit', minute: '2-digit' })}
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

