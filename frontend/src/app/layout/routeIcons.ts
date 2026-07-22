// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Route → lucide icon map for the top-bar page-title chip.
 *
 * ⚠️ This map MIRRORS the nav definitions in `Sidebar.tsx` (the 19
 * `navGroups`, the `adminGridItems` grid, and the footer "Add module"
 * tile). Each route's icon here is the EXACT same lucide icon the sidebar
 * row uses for that destination, so the top-bar title and the sidebar
 * entry can never disagree. The two MUST be kept in sync: when a route's
 * icon changes in `Sidebar.tsx`, change it here too (and vice versa). A
 * later consolidation can make `Sidebar.tsx` consume this map directly so
 * there is a single source of truth; until then, update both together.
 *
 * `getRouteIcon` does longest-prefix matching so detail routes resolve to
 * their parent module's icon (e.g. `/rfi/123` → the `/rfi` icon, and
 * `/bim/federations` beats `/bim`). Nested project routes
 * (`/projects/<id>/<feature>`) match on the trailing feature segment.
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
  type LucideIcon,
} from 'lucide-react';

/**
 * Route prefix → lucide icon, mirroring `Sidebar.tsx`.
 *
 * Stored query strings are intentionally dropped here — the chip cares only
 * about the destination module, not its sub-tab — so `/takeoff?tab=...`
 * and `/bim/rules?mode=...` are keyed by their pathname only.
 */
const ROUTE_ICON_MAP: Record<string, LucideIcon> = {
  // ── 1. Overview ───────────────────────────────────────────────────
  '/': LayoutDashboard,
  '/projects': FolderOpen,
  '/files': HardDrive,
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
  '/progress': Activity,
  '/portfolio/capacity': CalendarRange,
  '/portfolio/leveling': Scale,
  '/risks': ShieldAlert,
  // ── 8. Commercial ─────────────────────────────────────────────────
  '/crm': Briefcase,
  '/contracts': FileSignature,
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
  '/assets': Package,
  // ── 12. Quality ───────────────────────────────────────────────────
  '/validation': ShieldCheck,
  '/inspections': ClipboardCheck,
  '/ncr': AlertOctagon,
  '/punchlist': ListChecks,
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
  '/site-logistics': Truck,
  '/commissioning': ClipboardCheck,
  '/esg': Leaf,
  // ── Gap features ──────────────────────────────────────────────────
  '/forms': ClipboardList,
  // ── Footer CTA ────────────────────────────────────────────────────
  '/modules/developer-guide': Plus,
};

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
      if (candidate === '/') return ROUTE_ICON_MAP['/']!;
      continue;
    }
    if (candidate === prefix || candidate.startsWith(prefix + '/')) {
      return ROUTE_ICON_MAP[prefix]!;
    }
  }
  return null;
}
