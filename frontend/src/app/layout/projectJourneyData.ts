// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Project Journey - the single source of truth for the whole-platform
 * lifecycle map shown from the top bar.
 *
 * The model mirrors how a real construction project runs, from chasing the
 * lead to handing over the building, and places every major module on that
 * line. It exists so a user can always answer three questions at a glance:
 * where am I now, what came before, and what comes next.
 *
 * Structure:
 *   - 3 arcs (plan and price -> procure and schedule -> build and hand over)
 *   - 11 phases, numbered 1..11 in the order they usually happen
 *   - a set of "always on" modules that work across every phase (AI,
 *     collaboration) and therefore sit outside the line.
 *
 * Module chips reuse the sidebar's own i18n keys (``nav.*`` / ``*.title``)
 * so they translate for free in every locale; only the arc and phase names
 * and the panel chrome need dedicated ``journey.*`` keys.
 *
 * ``resolveJourneyPhaseKey`` maps the active route to its phase via a
 * longest-prefix match over every module route (shown or not), so the "you
 * are here" indicator is correct on any screen, including deep project
 * routes like ``/projects/<id>/finance``.
 */

import {
  Target,
  Building2,
  ScanLine,
  Ruler,
  Calculator,
  ShieldCheck,
  Handshake,
  CalendarRange,
  HardHat,
  Gauge,
  KeyRound,
  type LucideIcon,
} from 'lucide-react';

export type JourneyArcKey = 'plan' | 'procure' | 'deliver';

export interface JourneyModule {
  /** Route to navigate to when the chip is clicked. */
  to: string;
  /** i18n key reused from the sidebar so the chip translates for free. */
  labelKey: string;
  /** English fallback used as the ``defaultValue``. */
  label: string;
}

export interface JourneyPhase {
  key: string;
  arc: JourneyArcKey;
  icon: LucideIcon;
  nameKey: string;
  name: string;
  descKey: string;
  desc: string;
  /** Headline modules shown as chips on the phase card. */
  modules: JourneyModule[];
  /** Extra routes that belong to this phase for "you are here" matching but
   *  are not shown as chips (niche / advanced surfaces). */
  extraRoutes?: string[];
}

export interface JourneyArc {
  key: JourneyArcKey;
  nameKey: string;
  name: string;
  descKey: string;
  desc: string;
}

export const JOURNEY_ARCS: readonly JourneyArc[] = [
  {
    key: 'plan',
    nameKey: 'journey.arc.plan',
    name: 'Plan and price',
    descKey: 'journey.arc.plan_sub',
    desc: 'Decide what to build and what it should cost.',
  },
  {
    key: 'procure',
    nameKey: 'journey.arc.procure',
    name: 'Procure and schedule',
    descKey: 'journey.arc.procure_sub',
    desc: 'Choose who builds it, and plan when.',
  },
  {
    key: 'deliver',
    nameKey: 'journey.arc.deliver',
    name: 'Build and hand over',
    descKey: 'journey.arc.deliver_sub',
    desc: 'Deliver on site, control the money, close out.',
  },
] as const;

export const JOURNEY_PHASES: readonly JourneyPhase[] = [
  {
    key: 'win',
    arc: 'plan',
    icon: Target,
    nameKey: 'journey.phase.win.name',
    name: 'Win the work',
    descKey: 'journey.phase.win.desc',
    desc: 'Track leads and turn opportunities into signed projects.',
    modules: [
      { to: '/crm', labelKey: 'nav.crm', label: 'CRM' },
      { to: '/contacts', labelKey: 'contacts.title', label: 'Contacts' },
      { to: '/contracts', labelKey: 'nav.contracts', label: 'Contracts' },
    ],
  },
  {
    key: 'setup',
    arc: 'plan',
    icon: Building2,
    nameKey: 'journey.phase.setup.name',
    name: 'Set up the project',
    descKey: 'journey.phase.setup.desc',
    desc: 'Create the project, set standards and base currency, invite the team.',
    modules: [
      { to: '/projects', labelKey: 'projects.title', label: 'Projects' },
      { to: '/users', labelKey: 'sidebar.admin_grid.users', label: 'Users & teams' },
      { to: '/files', labelKey: 'nav.documents', label: 'Documents' },
      { to: '/governance', labelKey: 'sidebar.admin_grid.governance', label: 'Governance' },
    ],
    extraRoutes: ['/settings'],
  },
  {
    key: 'capture',
    arc: 'plan',
    icon: ScanLine,
    nameKey: 'journey.phase.capture.name',
    name: 'Capture the design',
    descKey: 'journey.phase.capture.desc',
    desc: 'Bring drawings, BIM models and reality scans into one place, and coordinate them.',
    modules: [
      { to: '/bim', labelKey: 'nav.bim_viewer', label: 'BIM Viewer' },
      { to: '/data-explorer', labelKey: 'nav.cad_bim_explorer', label: 'CAD-BIM BI Explorer' },
      { to: '/pointcloud', labelKey: 'nav.point_cloud', label: 'Point Cloud' },
      { to: '/cde', labelKey: 'cde.title', label: 'CDE' },
      { to: '/coordination', labelKey: 'nav.coordination_hub', label: 'Coordination Hub' },
      { to: '/clash', labelKey: 'nav.clash_detection', label: 'Clash Detection' },
      { to: '/geo', labelKey: 'sidebar.geo_hub', label: 'Geo Hub' },
    ],
    extraRoutes: [
      '/bim/federations',
      '/bim/rules',
      '/requirements/matrix',
      '/documents',
    ],
  },
  {
    key: 'quantify',
    arc: 'plan',
    icon: Ruler,
    nameKey: 'journey.phase.quantify.name',
    name: 'Quantify',
    descKey: 'journey.phase.quantify.desc',
    desc: 'Collect quantities, then filter and group them into the structure your estimate needs.',
    modules: [
      { to: '/quantities', labelKey: 'nav.quantities', label: 'Quantities' },
      { to: '/takeoff', labelKey: 'nav.pdf_measurements', label: 'PDF Takeoff' },
      { to: '/dwg-takeoff', labelKey: 'nav.dwg_takeoff', label: 'DWG Takeoff' },
      { to: '/match-elements', labelKey: 'nav.match_elements', label: 'Match to cost' },
    ],
  },
  {
    key: 'estimate',
    arc: 'plan',
    icon: Calculator,
    nameKey: 'journey.phase.estimate.name',
    name: 'Estimate',
    descKey: 'journey.phase.estimate.desc',
    desc: 'Turn quantities into a priced bill with rates, assemblies and AI suggestions.',
    modules: [
      { to: '/boq', labelKey: 'boq.title', label: 'Bill of Quantities' },
      { to: '/costs', labelKey: 'costs.title', label: 'Cost Database' },
      { to: '/assemblies', labelKey: 'nav.assemblies', label: 'Assemblies' },
      { to: '/ai-estimate', labelKey: 'nav.ai_estimate', label: 'AI Quick Estimate' },
    ],
    extraRoutes: [
      '/catalog',
      '/ai-estimator',
      '/project-intelligence',
      '/benchmarks',
      '/design-options',
    ],
  },
  {
    key: 'validate',
    arc: 'plan',
    icon: ShieldCheck,
    nameKey: 'journey.phase.validate.name',
    name: 'Validate',
    descKey: 'journey.phase.validate.desc',
    desc: 'Run rule checks for completeness, standards and data quality before you commit.',
    modules: [{ to: '/validation', labelKey: 'validation.title', label: 'Validation' }],
    extraRoutes: ['/compliance'],
  },
  {
    key: 'tender',
    arc: 'procure',
    icon: Handshake,
    nameKey: 'journey.phase.tender.name',
    name: 'Source and tender',
    descKey: 'journey.phase.tender.desc',
    desc: 'Package the work, invite builders and suppliers, compare bids and award.',
    modules: [
      { to: '/tendering', labelKey: 'tendering.title', label: 'Tendering' },
      { to: '/subcontractors', labelKey: 'nav.subcontractors', label: 'Subcontractors' },
      { to: '/bid-management', labelKey: 'nav.bid_management', label: 'Bid Management' },
      { to: '/procurement', labelKey: 'procurement.title', label: 'Procurement' },
    ],
    extraRoutes: ['/supplier-catalogs'],
  },
  {
    key: 'schedule',
    arc: 'procure',
    icon: CalendarRange,
    nameKey: 'journey.phase.schedule.name',
    name: 'Plan and schedule',
    descKey: 'journey.phase.schedule.desc',
    desc: 'Sequence the work in time, link cost to schedule (5D), and plan crews, plant and risk.',
    modules: [
      { to: '/schedule', labelKey: 'schedule.title', label: 'Schedule' },
      { to: '/5d', labelKey: 'nav.5d_cost_model', label: '5D Cost Model' },
      { to: '/tasks', labelKey: 'tasks.title', label: 'Tasks' },
      { to: '/resources', labelKey: 'nav.resources', label: 'Resources' },
      { to: '/risks', labelKey: 'nav.risk_register', label: 'Risk Register' },
      { to: '/portfolio', labelKey: 'portfolio.title', label: 'Portfolio' },
    ],
    extraRoutes: [
      '/schedule-advanced',
      '/takt',
      '/equipment',
      '/payroll',
      '/prefab',
      '/portfolio/capacity',
      '/portfolio/leveling',
    ],
  },
  {
    key: 'build',
    arc: 'deliver',
    icon: HardHat,
    nameKey: 'journey.phase.build.name',
    name: 'Build on site',
    descKey: 'journey.phase.build.desc',
    desc: 'Run site work day to day: diaries, RFIs, submittals, quality, safety and changes.',
    modules: [
      { to: '/daily-diary', labelKey: 'nav.daily_diary', label: 'Daily Diary' },
      { to: '/rfi', labelKey: 'rfi.title', label: 'RFI' },
      { to: '/submittals', labelKey: 'submittals.title', label: 'Submittals' },
      { to: '/inspections', labelKey: 'inspections.title', label: 'Inspections' },
      { to: '/photos', labelKey: 'nav.photos', label: 'Photos' },
      { to: '/changeorders', labelKey: 'nav.change_orders', label: 'Change Orders' },
    ],
    extraRoutes: [
      '/field-reports',
      '/field-time',
      '/site-sensors',
      '/meetings',
      '/correspondence',
      '/transmittals',
      '/markups',
      '/ncr',
      '/punchlist',
      '/forms',
      '/construction-control',
      '/safety',
      '/qms',
      '/hse-advanced',
      '/variations',
      '/moc',
      '/portal',
      '/carbon',
      '/sustainability',
      '/esg',
    ],
  },
  {
    key: 'control',
    arc: 'deliver',
    icon: Gauge,
    nameKey: 'journey.phase.control.name',
    name: 'Control and report',
    descKey: 'journey.phase.control.desc',
    desc: 'Track cost against budget, invoice, and report progress with live dashboards.',
    modules: [
      { to: '/finance', labelKey: 'finance.title', label: 'Finance' },
      { to: '/cvr', labelKey: 'nav.cvr', label: 'Cost-Value Reconciliation' },
      { to: '/project-controls', labelKey: 'nav.project_controls', label: 'Project Controls' },
      { to: '/bi-dashboards', labelKey: 'nav.bi_dashboards', label: 'BI Dashboards' },
      { to: '/reports', labelKey: 'nav.reports', label: 'Reports' },
    ],
    extraRoutes: ['/analytics', '/reporting', '/dashboards', '/admin/audit-log'],
  },
  {
    key: 'close',
    arc: 'deliver',
    icon: KeyRound,
    nameKey: 'journey.phase.close.name',
    name: 'Close and operate',
    descKey: 'journey.phase.close.desc',
    desc: 'Hand over, manage the assets and the built estate, and feed lessons back.',
    modules: [
      { to: '/commissioning', labelKey: 'nav.commissioning', label: 'Commissioning' },
      { to: '/closeout', labelKey: 'closeout.title', label: 'Closeout' },
      { to: '/assets', labelKey: 'nav.assets', label: 'Asset Register' },
      { to: '/property-dev', labelKey: 'nav.property_dev', label: 'Property Development' },
      { to: '/service', labelKey: 'nav.service', label: 'Service' },
    ],
    extraRoutes: ['/accommodation'],
  },
] as const;

/** Cross-cutting modules that help across every phase rather than sitting on
 *  the line. Shown as an "always on" band under the journey. */
export const JOURNEY_ALWAYS_ON: readonly JourneyModule[] = [
  { to: '/ai-agents', labelKey: 'nav.ai_agents', label: 'AI Agents' },
  { to: '/advisor', labelKey: 'nav.ai_advisor', label: 'AI Cost Advisor' },
  { to: '/chat', labelKey: 'nav.erp_chat', label: 'AI Chat' },
  { to: '/collaboration', labelKey: 'nav.collaboration', label: 'Collaboration' },
  { to: '/pipelines', labelKey: 'nav.pipelines', label: 'Pipelines' },
] as const;

// Flat, longest-prefix-first index of every phase route for "you are here".
const ROUTE_INDEX: ReadonlyArray<{ prefix: string; phaseKey: string }> = (() => {
  const out: { prefix: string; phaseKey: string }[] = [];
  for (const phase of JOURNEY_PHASES) {
    for (const m of phase.modules) {
      out.push({ prefix: m.to.split('?')[0]!, phaseKey: phase.key });
    }
    for (const r of phase.extraRoutes ?? []) {
      out.push({ prefix: r, phaseKey: phase.key });
    }
  }
  out.sort((a, b) => b.prefix.length - a.prefix.length);
  return out;
})();

/**
 * Normalise a pathname to its journey-comparable candidate by stripping the
 * ``/projects/<id>/`` prefix, so a project-scoped route matches its plain
 * module route (``/projects/abc/finance`` -> ``/finance``). Shared by phase
 * detection and chip active-state so the two cannot drift apart.
 */
export function journeyRouteCandidate(pathname: string): string {
  const projectNested = pathname.match(/^\/projects\/[^/]+\/(.+)$/);
  return projectNested ? `/${projectNested[1]}` : pathname;
}

/**
 * Resolve the lifecycle phase key for a pathname, or ``null`` when the route
 * is not part of the journey (dashboard, admin, modules, about, ...).
 *
 * Project-nested routes (``/projects/<id>/finance``) are matched on the
 * feature segment first, mirroring the header's bug-report route resolver.
 */
export function resolveJourneyPhaseKey(pathname: string): string | null {
  if (!pathname || pathname === '/') return null;
  const candidate = journeyRouteCandidate(pathname);
  for (const { prefix, phaseKey } of ROUTE_INDEX) {
    if (candidate === prefix || candidate.startsWith(prefix + '/')) return phaseKey;
  }
  return null;
}

/** Look up a phase by key (``undefined`` when not found). */
export function getJourneyPhase(key: string | null): JourneyPhase | undefined {
  if (!key) return undefined;
  return JOURNEY_PHASES.find((p) => p.key === key);
}

/** 1-based number of a phase in the journey (0 when not found). */
export function getJourneyPhaseNumber(key: string | null): number {
  if (!key) return 0;
  return JOURNEY_PHASES.findIndex((p) => p.key === key) + 1;
}
