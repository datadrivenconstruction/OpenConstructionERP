// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Route → lucide icon map for the top-bar page-title chip.
 *
 * The menu half of this map is DERIVED from `./navCatalog`, so a screen's
 * icon in the top bar is the same object as the icon on its sidebar row and
 * the two cannot drift. This comment used to say the copy had to be kept in
 * sync by hand and ask for exactly this consolidation; when the check was
 * finally written (`navCatalog.test.ts`) the hand-kept copy turned out to be
 * missing 27 of the menu's routes outright, so those screens had been showing
 * no icon at all.
 *
 * What stays by hand is `EXTRA_ROUTE_ICONS`: child and detail routes, the
 * admin grid at the foot of the sidebar and the footer "Add module" tile.
 * Nothing declares those anywhere else. They merge UNDER the derived map, so
 * a path the menu also names always takes the menu's icon.
 *
 * `getRouteIcon` does longest-prefix matching so detail routes resolve to
 * their parent module's icon (e.g. `/rfi/123` → the `/rfi` icon, and
 * `/bim/federations` beats `/bim`). Nested project routes
 * (`/projects/<id>/<feature>`) match on the trailing feature segment.
 *
 * A user's icon override for a menu route (Settings > Menu look) wins over
 * both maps, so the chip, the sidebar row and the command palette agree.
 * Components calling `getRouteIcon` in render subscribe with
 * `useIconOverridesVersion()` from `./menuIcons`.
 */
import {
  LayoutDashboard,
  FolderOpen,
  HardDrive,
  Table2,
  Link2,
  Wand2,
  Sparkles,
  BrainCircuit,
  Database,
  Boxes,
  Compass,
  Layers,
  BarChart3,
  FileBarChart,
  Ruler,
  PencilRuler,
  Box,
  TableProperties,
  Globe,
  Radar,
  SlidersHorizontal,
  FileCheck,
  CalendarDays,
  LineChart,
  GitBranch,
  ClipboardList,
  TrendingUp,
  Activity,
  CalendarRange,
  Scale,
  Percent,
  Stamp,
  ShieldAlert,
  Briefcase,
  FileSignature,
  HardHat,
  FileText,
  Replace,
  ShoppingCart,
  Package,
  FileEdit,
  BookOpen,
  Wrench,
  Timer,
  Truck,
  Factory,
  Users,
  Wallet,
  ShieldCheck,
  ClipboardCheck,
  AlertOctagon,
  CircleDot,
  ListChecks,
  Shield,
  BadgeCheck,
  Leaf,
  HelpCircle,
  Mail,
  Inbox,
  Send,
  Camera,
  PenTool,
  Building2,
  Gauge,
  Bot,
  MessageSquare,
  Settings,
  Info,
  ScrollText,
  Plus,
  PackageCheck,
  ScanEye,
  AlarmClock,
  type LucideIcon,
} from 'lucide-react';
import { getIconOverride } from './menuIcons';
import { navGroups } from './navCatalog';

/**
 * Route prefix → lucide icon, mirroring `Sidebar.tsx`.
 *
 * Stored query strings are intentionally dropped here — the chip cares only
 * about the destination module, not its sub-tab — so `/takeoff?tab=...`
 * and `/bim/rules?mode=...` are keyed by their pathname only.
 */
/** Every screen the menu offers, taking each row's own icon.
 *
 *  This is the half of the map that used to be copied by hand, and the copy was
 *  wrong: a test over `navGroups` found 27 menu rows the map had no entry for at
 *  all, so the top bar showed those screens with no icon. Derived now, so the
 *  two cannot disagree and a new screen needs no second edit.
 *
 *  A row's `to` may carry a query (`/takeoff?tab=measurements`); the map is
 *  keyed by path, and `getRouteIcon` strips queries before looking anything up. */
const FROM_MENU: Record<string, LucideIcon> = (() => {
  const map: Record<string, LucideIcon> = {};
  for (const group of navGroups) {
    for (const item of group.items) {
      const path = item.to.split('?')[0]!;
      // First row wins. Two rows sharing a path differ only by query, and the
      // first is the one the menu lists first.
      if (!(path in map)) map[path] = item.icon;
    }
  }
  return map;
})();

/** Routes the menu has no row for: child and detail routes, the admin grid at
 *  the foot of the sidebar, and the "Add module" tile. Kept by hand because
 *  nothing declares them anywhere else. Merged under `FROM_MENU`, so a path the
 *  menu also names always takes the menu's icon. */
const EXTRA_ROUTE_ICONS: Record<string, LucideIcon> = {
  // ── 1. Overview ───────────────────────────────────────────────────
  '/': LayoutDashboard,
  '/projects': FolderOpen,
  '/files': HardDrive,
  '/sheets': FileText,
  // ── 2. Estimating ─────────────────────────────────────────────────
  '/boq': Table2,
  '/match-elements': Link2,
  '/ai-estimator': Wand2,
  '/ai-estimate': Sparkles,
  '/project-intelligence': BrainCircuit,
  // ── 3. Cost Data ──────────────────────────────────────────────────
  '/costs': Database,
  '/catalog': Boxes,
  '/cost-explorer': Compass,
  '/assemblies': Layers,
  '/benchmarks': BarChart3,
  // ── 4. Takeoff ────────────────────────────────────────────────────
  '/quantities': Ruler,
  '/takeoff': Ruler,
  '/dwg-takeoff': PencilRuler,
  '/bim': Box,
  '/data-explorer': TableProperties,
  '/geo': Globe,
  // ── 5. Model Coordination ─────────────────────────────────────────
  '/coordination': LayoutDashboard,
  '/model-review': ScanEye,
  '/bcf': MessageSquare,
  '/bim/federations': Layers,
  '/clash': Radar,
  '/bim/rules': SlidersHorizontal,
  '/requirements/matrix': FileCheck,
  // ── 6. Scheduling ─────────────────────────────────────────────────
  '/schedule': CalendarDays,
  '/schedule-advanced': LineChart,
  '/takt': GitBranch,
  '/tasks': ClipboardList,
  // ── 7. Cost Control & Risk ────────────────────────────────────────
  '/5d': TrendingUp,
  '/cost-control': Scale,
  '/progress': Activity,
  '/portfolio/capacity': CalendarRange,
  '/portfolio/leveling': Scale,
  '/risks': ShieldAlert,
  // ── 8. Commercial ─────────────────────────────────────────────────
  '/crm': Briefcase,
  '/contracts': FileSignature,
  '/payment-clock': Scale,
  '/tax-withholding': Percent,
  '/einvoice-clearance': Stamp,
  '/cost-match': Link2,
  '/full-evm': LineChart,
  '/fx': Wallet,
  '/subcontractors': HardHat,
  '/bid-management': Scale,
  '/tendering': FileText,
  // ── 9. Procurement & Change ───────────────────────────────────────
  '/variations': GitBranch,
  '/moc': Replace,
  '/supplier-catalogs': ShoppingCart,
  '/procurement': Package,
  '/changeorders': FileEdit,
  // ── 10. Field Operations ──────────────────────────────────────────
  '/daily-diary': BookOpen,
  '/field-reports': ClipboardList,
  '/field-time': Timer,
  '/service': Wrench,
  '/portal': Globe,
  '/portal/payments': FileText,
  // ── 11. Resources & Assets ────────────────────────────────────────
  '/equipment': Truck,
  '/resources': Users,
  '/payroll': Wallet,
  '/certified-payroll': FileCheck,
  '/assets': Package,
  // ── 12. Quality ───────────────────────────────────────────────────
  '/validation': ShieldCheck,
  '/inspections': ClipboardCheck,
  '/ncr': AlertOctagon,
  '/punchlist': ListChecks,
  '/deadlines': AlarmClock,
  '/issues': CircleDot,
  '/closeout': PackageCheck,
  // ── 13. Safety & ESG ──────────────────────────────────────────────
  '/safety': HardHat,
  '/hse-advanced': Shield,
  '/qms': BadgeCheck,
  '/carbon': Leaf,
  '/sustainability': Leaf,
  // ── 14. Communication ─────────────────────────────────────────────
  '/contacts': Users,
  '/meetings': CalendarDays,
  '/rfi': HelpCircle,
  '/correspondence': Mail,
  '/inbound-email': Inbox,
  '/collaboration': Users,
  // ── 15. Documents ─────────────────────────────────────────────────
  '/submittals': FileCheck,
  '/transmittals': Send,
  '/cde': Database,
  '/photos': Camera,
  '/markups': PenTool,
  '/plan-room': Layers,
  // ── 16. Real Estate ───────────────────────────────────────────────
  '/property-dev': Building2,
  '/accommodation': Building2,
  '/property-dev/dashboards': BarChart3,
  '/property-dev/settings/house-types': Building2,
  '/property-dev/settings/document-templates': FileText,
  // ── 17. Finance ───────────────────────────────────────────────────
  '/finance': Wallet,
  '/analytics': LineChart,
  '/reports': FileBarChart,
  '/reporting': BarChart3,
  '/dashboards': TrendingUp,
  // ── 18. Controls & BI ─────────────────────────────────────────────
  '/project-controls': Gauge,
  '/bi-dashboards': BarChart3,
  '/architecture': GitBranch,
  // ── 19. Automation & AI ───────────────────────────────────────────
  '/ai-agents': Bot,
  '/advisor': MessageSquare,
  '/chat': MessageSquare,
  '/teams': ShieldCheck,
  '/pipelines': GitBranch,
  // ── Admin grid (bottom of sidebar) ────────────────────────────────
  '/settings': Settings,
  '/users': Users,
  '/modules': Package,
  '/governance': Scale,
  '/admin/audit-log': ScrollText,
  '/about': Info,
  // ── v10.6.0 modules ───────────────────────────────────────────────
  '/prefab': Factory,
  '/cvr': Scale,
  '/design-options': Scale,
  '/formwork': Boxes,
  '/site-logistics': Truck,
  '/commissioning': ClipboardCheck,
  '/esg': Leaf,
  // ── Gap features ──────────────────────────────────────────────────
  '/forms': ClipboardList,
  // ── Footer CTA ────────────────────────────────────────────────────
  '/modules/developer-guide': Plus,
};

const ROUTE_ICON_MAP: Record<string, LucideIcon> = { ...EXTRA_ROUTE_ICONS, ...FROM_MENU };

/** Pre-sorted route prefixes, longest first, so the first prefix that
 *  matches in `getRouteIcon` is also the most specific (longest) one. */
const SORTED_ROUTE_PREFIXES: readonly string[] = Object.keys(ROUTE_ICON_MAP).sort(
  (a, b) => b.length - a.length,
);

/**
 * Resolve the lucide icon for a pathname, or `null` when no route matches.
 *
 * Mirrors the sidebar's active-route logic: query strings are ignored, the
 * trailing feature segment of a nested project route is used, and the
 * longest matching prefix wins so detail/child routes resolve to their
 * parent module's icon (`/rfi/123` → `/rfi`, `/bim/federations/x` →
 * `/bim/federations`). Root `/` only matches an exact `/`.
 */
export function getRouteIcon(pathname: string): LucideIcon | null {
  if (!pathname) return null;
  // Strip any query string / hash defensively (callers usually pass a bare
  // pathname, but a full `location` href would otherwise miss).
  const cleanPath = pathname.split('?')[0]!.split('#')[0]!;

  // Nested project routes carry the feature after /projects/<id>/. Match the
  // feature segment first (so /projects/<id>/finance resolves to the Finance
  // icon), then fall through to the /projects icon below.
  const projectNested = cleanPath.match(/^\/projects\/[^/]+\/(.+)$/);
  const candidate = projectNested ? `/${projectNested[1]}` : cleanPath;

  for (const prefix of SORTED_ROUTE_PREFIXES) {
    if (prefix === '/') {
      if (candidate === '/') return getIconOverride('/') ?? ROUTE_ICON_MAP['/']!;
      continue;
    }
    if (candidate === prefix || candidate.startsWith(prefix + '/')) {
      return getIconOverride(prefix) ?? ROUTE_ICON_MAP[prefix]!;
    }
  }
  return null;
}
