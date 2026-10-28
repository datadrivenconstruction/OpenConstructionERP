// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — content model.
//
// The "How it works" hub (HowItWorksPage) renders a clear, searchable
// explanation of EVERY user-facing module in one place: what it is, how it
// works step by step, pro tips, and when to use it. Each entry can also dim
// the rest of the app and spotlight its own sidebar entry, so a new user sees
// exactly where the module lives.
//
// Every string is an i18n key WITH an inline English default, read via
// t(key, { defaultValue }). The inline English string IS the source copy;
// translators fill the other locales later. Keys never need to be added to
// en.ts or any locale file by hand.
//
// Authoring: add ModuleExplanation objects to the per-domain files under
// ./catalog/*. One file per domain keeps parallel authoring conflict-free.
// Key convention per module id `m`:
//   howto.<m>.title / .summary / .what / .when
//   howto.<m>.how.1 .. howto.<m>.how.n     (ordered steps)
//   howto.<m>.tip.1 .. howto.<m>.tip.n     (optional tips)

/** One translatable line: an i18n key plus its inline English default. */
export interface HowToStep {
  /** i18n key, e.g. `howto.boq.how.1`. */
  key: string;
  /** Inline English default, passed straight to t(key, { defaultValue }). */
  default: string;
}

/**
 * Fine-grained display category. The hub groups modules under these headings
 * (independent of which catalog file an entry is authored in).
 */
export type CategoryId =
  | 'overview'
  | 'estimating'
  | 'takeoff'
  | 'reality'
  | 'cost_data'
  | 'scheduling'
  | 'cost_control'
  | 'coordination'
  | 'commercial'
  | 'procurement'
  | 'field'
  | 'resources'
  | 'quality'
  | 'safety'
  | 'communication'
  | 'documents'
  | 'real_estate'
  | 'finance'
  | 'controls'
  | 'automation'
  | 'integrations'
  | 'admin';

/**
 * A complete plain-language explanation of one module.
 *
 * `icon` is a lucide-react icon name resolved by the hub's ICON map; unknown
 * names fall back to a default so a typo never breaks the build. Supported
 * names (curated): Boxes, LayoutDashboard, FolderKanban, FolderOpen, Ruler,
 * FileText, PencilRuler, Box, Scan, Map, Mountain, Calculator, Layers3,
 * Sparkles, Wand2, Link2, Brain, Database, Library, BarChart3, CalendarDays,
 * GanttChartSquare, Clock, TrendingUp, Gauge, Dices, ShieldCheck, Boxes,
 * Network, GitCompare, Workflow, Users, Building2, Home, Handshake,
 * FileSignature, ShoppingCart, Truck, ClipboardList, ClipboardCheck,
 * HardHat, Leaf, Recycle, MessageSquare, Mail, Send, FileBarChart,
 * PieChart, Bot, MessageCircle, Plug, Settings, ShieldAlert, BookOpen.
 */
export interface ModuleExplanation {
  /** Stable slug, e.g. `boq`. Used for i18n key prefixes + React keys. */
  id: string;
  /** Sidebar route this module lives at, e.g. `/boq`. Drives the "Open module"
   *  action, and the sidebar spotlight target unless `spotlightRoute` overrides
   *  it. */
  route: string;
  /** Optional spotlight target for modules that open at a sub-route with no
   *  sidebar link of its own (e.g. `/files/search`). "Show me where" highlights
   *  this parent entry (e.g. `/files`) instead, while "Open module" still uses
   *  `route`. Defaults to `route`. */
  spotlightRoute?: string;
  /** Lucide icon name (see ICON map). Unknown names fall back gracefully. */
  icon: string;
  /** Display grouping. */
  category: CategoryId;
  /** Marks pre-1.0 / preview modules with a small badge. */
  beta?: boolean;
  /** Optional explicit order within this module's category section (ascending).
   *  Modules that set it sort first, in ascending order; modules without it keep
   *  their original catalog order after them. Lets an author make the reading
   *  order inside a section intentional without numbering every entry. */
  order?: number;
  /** Extra search terms (English, space-separated). Not shown to users. */
  keywords?: string;

  titleKey: string;
  titleDefault: string;
  /** One-line summary shown on the collapsed card + used by the spotlight. */
  summaryKey: string;
  summaryDefault: string;
  /** A short paragraph: what this module is and why it exists. */
  whatKey: string;
  whatDefault: string;
  /** 3-6 ordered steps describing how it works / how to use it. */
  how: HowToStep[];
  /** 0-3 optional pro tips. */
  tips?: HowToStep[];
  /** Optional: when to reach for this module. */
  whenKey?: string;
  whenDefault?: string;
}

/** One section heading on the hub. */
export interface HowItWorksCategory {
  id: CategoryId;
  labelKey: string;
  labelDefault: string;
  descKey: string;
  descDefault: string;
}

/**
 * Ordered category headings for the hub. The order here is the order sections
 * appear on the page, following the natural project lifecycle.
 */
export const HOW_IT_WORKS_CATEGORIES: HowItWorksCategory[] = [
  {
    id: 'overview',
    labelKey: 'howto.cat.overview',
    labelDefault: 'Overview',
    descKey: 'howto.cat.overview.desc',
    descDefault: 'Where every working day starts: your projects, files and live status.',
  },
  {
    id: 'takeoff',
    labelKey: 'howto.cat.takeoff',
    labelDefault: 'Takeoff & quantities',
    descKey: 'howto.cat.takeoff.desc',
    descDefault: 'Pull measurable quantities out of PDFs, CAD, BIM models and point clouds.',
  },
  {
    id: 'estimating',
    labelKey: 'howto.cat.estimating',
    labelDefault: 'Estimating',
    descKey: 'howto.cat.estimating.desc',
    descDefault: 'Turn quantities into a priced, defensible bill of quantities.',
  },
  {
    id: 'cost_data',
    labelKey: 'howto.cat.cost_data',
    labelDefault: 'Cost data',
    descKey: 'howto.cat.cost_data.desc',
    descDefault: 'The catalogs, assemblies and benchmarks your prices come from.',
  },
  {
    id: 'scheduling',
    labelKey: 'howto.cat.scheduling',
    labelDefault: 'Scheduling',
    descKey: 'howto.cat.scheduling.desc',
    descDefault: 'Plan the work in time: tasks, critical path, 4D and takt.',
  },
  {
    id: 'cost_control',
    labelKey: 'howto.cat.cost_control',
    labelDefault: 'Cost control & risk',
    descKey: 'howto.cat.cost_control.desc',
    descDefault: 'Track budget against actuals, level resources and quantify risk.',
  },
  {
    id: 'reality',
    labelKey: 'howto.cat.reality',
    labelDefault: 'Reality capture & 3D',
    descKey: 'howto.cat.reality.desc',
    descDefault: 'Site maps, geospatial data and point-cloud reality models.',
  },
  {
    id: 'coordination',
    labelKey: 'howto.cat.coordination',
    labelDefault: 'Model coordination',
    descKey: 'howto.cat.coordination.desc',
    descDefault: 'Federate models, find clashes and check them against requirements.',
  },
  {
    id: 'commercial',
    labelKey: 'howto.cat.commercial',
    labelDefault: 'Commercial',
    descKey: 'howto.cat.commercial.desc',
    descDefault: 'Win and run the contract: CRM, tenders, contracts and claims.',
  },
  {
    id: 'procurement',
    labelKey: 'howto.cat.procurement',
    labelDefault: 'Procurement & change',
    descKey: 'howto.cat.procurement.desc',
    descDefault: 'Buy the work and keep change under control.',
  },
  {
    id: 'field',
    labelKey: 'howto.cat.field',
    labelDefault: 'Field operations',
    descKey: 'howto.cat.field.desc',
    descDefault: 'What happens on site: diaries, reports, service and portals.',
  },
  {
    id: 'resources',
    labelKey: 'howto.cat.resources',
    labelDefault: 'Resources & assets',
    descKey: 'howto.cat.resources.desc',
    descDefault: 'People, crews, plant and payroll behind the work.',
  },
  {
    id: 'quality',
    labelKey: 'howto.cat.quality',
    labelDefault: 'Quality',
    descKey: 'howto.cat.quality.desc',
    descDefault: 'Inspections, non-conformance, punch lists and handover.',
  },
  {
    id: 'safety',
    labelKey: 'howto.cat.safety',
    labelDefault: 'Safety & ESG',
    descKey: 'howto.cat.safety.desc',
    descDefault: 'Health and safety plus carbon and sustainability.',
  },
  {
    id: 'communication',
    labelKey: 'howto.cat.communication',
    labelDefault: 'Communication',
    descKey: 'howto.cat.communication.desc',
    descDefault: 'Contacts, meetings, RFIs, correspondence and live collaboration.',
  },
  {
    id: 'documents',
    labelKey: 'howto.cat.documents',
    labelDefault: 'Documents',
    descKey: 'howto.cat.documents.desc',
    descDefault: 'The document spine: submittals, transmittals, CDE and markups.',
  },
  {
    id: 'real_estate',
    labelKey: 'howto.cat.real_estate',
    labelDefault: 'Real estate',
    descKey: 'howto.cat.real_estate.desc',
    descDefault: 'Developer workflows: property development and accommodation.',
  },
  {
    id: 'finance',
    labelKey: 'howto.cat.finance',
    labelDefault: 'Finance & reports',
    descKey: 'howto.cat.finance.desc',
    descDefault: 'Ledgers, analytics and the reports that go to stakeholders.',
  },
  {
    id: 'controls',
    labelKey: 'howto.cat.controls',
    labelDefault: 'Controls & BI',
    descKey: 'howto.cat.controls.desc',
    descDefault: 'Project controls, dashboards and baseline snapshots.',
  },
  {
    id: 'automation',
    labelKey: 'howto.cat.automation',
    labelDefault: 'Automation & AI',
    descKey: 'howto.cat.automation.desc',
    descDefault: 'Assistants, advisors and no-code automation pipelines.',
  },
  {
    id: 'integrations',
    labelKey: 'howto.cat.integrations',
    labelDefault: 'Integrations & exchange',
    descKey: 'howto.cat.integrations.desc',
    descDefault: 'Open exchange formats, converters and outside connections.',
  },
  {
    id: 'admin',
    labelKey: 'howto.cat.admin',
    labelDefault: 'Setup & administration',
    descKey: 'howto.cat.admin.desc',
    descDefault: 'Settings, users, modules and governance.',
  },
];
