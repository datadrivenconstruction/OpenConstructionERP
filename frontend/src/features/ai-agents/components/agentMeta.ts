// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Presentation metadata for the AI-agents gallery: icon resolution, friendly
// tool labels, and category grouping. Kept framework-light (no JSX here) so it
// can be imported by both the gallery and the run timeline.
import {
  Bot,
  Brain,
  Wrench,
  MessageSquare,
  Calculator,
  Tags,
  FileSearch,
  BarChart3,
  Scale,
  ShieldCheck,
  Sparkles,
  Search,
  ClipboardCheck,
  FileText,
  TrendingUp,
  Ruler,
  Layers,
  Receipt,
  Package,
  Gauge,
  Lightbulb,
  type LucideIcon,
} from 'lucide-react';

// ── Icon resolution ─────────────────────────────────────────────────────────

// Explicit allow-list keyed by the lucide icon name a backend descriptor may
// send (snake_case / kebab-case / PascalCase all normalise to one of these).
// An explicit map keeps the bundle tree-shakeable (no `import * as lucide`).
const ICON_BY_KEY: Record<string, LucideIcon> = {
  bot: Bot,
  brain: Brain,
  wrench: Wrench,
  messagesquare: MessageSquare,
  calculator: Calculator,
  tags: Tags,
  filesearch: FileSearch,
  barchart3: BarChart3,
  barchart: BarChart3,
  scale: Scale,
  shieldcheck: ShieldCheck,
  sparkles: Sparkles,
  search: Search,
  clipboardcheck: ClipboardCheck,
  filetext: FileText,
  trendingup: TrendingUp,
  ruler: Ruler,
  layers: Layers,
  receipt: Receipt,
  package: Package,
  gauge: Gauge,
  lightbulb: Lightbulb,
};

/** Normalise an arbitrary icon name to the ICON_BY_KEY key form. */
function iconKey(name: string): string {
  return name.toLowerCase().replace(/[-_\s]+/g, '');
}

/**
 * Resolve a descriptor's `icon` string to a lucide component, falling back to
 * a sensible default (Bot) for unknown / missing names. Never throws.
 */
export function resolveAgentIcon(icon?: string | null): LucideIcon {
  if (!icon) return Sparkles;
  return ICON_BY_KEY[iconKey(icon)] ?? Sparkles;
}

// ── Categories ───────────────────────────────────────────────────────────────

export interface CategoryMeta {
  icon: LucideIcon;
  /** i18n default label for the section header. */
  label: string;
  /** Tailwind classes for the section-header icon chip (accent tint). */
  chip: string;
}

const CATEGORY_META: Record<string, CategoryMeta> = {
  my_agents: {
    icon: Sparkles,
    label: 'Your agents',
    chip: 'bg-oe-blue text-content-inverse',
  },
  estimating: {
    icon: Calculator,
    label: 'Estimating',
    chip: 'bg-oe-blue-subtle text-oe-blue-text',
  },
  quality: {
    icon: ShieldCheck,
    label: 'Quality & compliance',
    chip: 'bg-semantic-success-bg text-semantic-success',
  },
  documents: {
    icon: FileSearch,
    label: 'Documents',
    chip: 'bg-semantic-info-bg text-semantic-info',
  },
  analytics: {
    icon: BarChart3,
    label: 'Analytics',
    chip: 'bg-semantic-warning-bg text-[#b45309]',
  },
  classification: {
    icon: Tags,
    label: 'Classification',
    chip: 'bg-oe-blue-subtle text-oe-blue-text',
  },
  planning: {
    icon: TrendingUp,
    label: 'Planning',
    chip: 'bg-semantic-info-bg text-semantic-info',
  },
  general: {
    icon: Sparkles,
    label: 'General',
    chip: 'bg-surface-secondary text-content-secondary',
  },
};

const FALLBACK_CATEGORY = 'general';

/** Resolve category metadata for an agent, with a graceful default. */
export function resolveCategoryMeta(category?: string | null): CategoryMeta {
  const key = (category ?? FALLBACK_CATEGORY).toLowerCase();
  return (
    CATEGORY_META[key] ?? {
      icon: Sparkles,
      label: titleCase(category ?? FALLBACK_CATEGORY),
      chip: 'bg-surface-secondary text-content-secondary',
    }
  );
}

/** Stable display order for category sections; unknowns sort to the end. */
const CATEGORY_ORDER = [
  'my_agents',
  'estimating',
  'classification',
  'quality',
  'documents',
  'analytics',
  'planning',
  'general',
];

export function categorySortIndex(category?: string | null): number {
  const key = (category ?? FALLBACK_CATEGORY).toLowerCase();
  const idx = CATEGORY_ORDER.indexOf(key);
  return idx === -1 ? CATEGORY_ORDER.length : idx;
}

export function normaliseCategory(category?: string | null): string {
  return (category ?? FALLBACK_CATEGORY).toLowerCase();
}

// ── Tool labels ────────────────────────────────────────────────────────────

interface ToolLabel {
  label: string;
  hint: string;
}

// Known tool slugs → friendly label + tooltip. Anything not listed gets a
// humanised fallback (see toolLabel below) so new backend tools still read
// nicely without a frontend change.
const TOOL_LABELS: Record<string, ToolLabel> = {
  search_costs: {
    label: 'Search cost database',
    hint: 'Looks up unit rates and items in the cost database.',
  },
  suggest_assembly: {
    label: 'Suggest assembly',
    hint: 'Proposes a composite assembly (recipe) for a scope of work.',
  },
  create_position: {
    label: 'Draft BOQ position',
    hint: 'Drafts a new bill-of-quantities position for your review.',
  },
  read_boq: {
    label: 'Read the BOQ',
    hint: 'Reads the current bill of quantities for context.',
  },
  check_boq_quality: {
    label: 'Quality checks',
    hint: 'Runs quality rules over the BOQ (missing quantities, zero prices, duplicates).',
  },
  classify_item: {
    label: 'Classify cost code',
    hint: 'Assigns a classification code (DIN 276, NRM, MasterFormat).',
  },
  search_documents: {
    label: 'Search documents',
    hint: 'Searches project documents for relevant passages.',
  },
  project_cost_summary: {
    label: 'Project cost summary',
    hint: 'Summarises the total project cost and its breakdown.',
  },
  benchmark_rate: {
    label: 'Benchmark a rate',
    hint: 'Compares a unit rate against historical benchmarks.',
  },
};

/** Title-case a slug-ish string: `benchmark_rate` → `Benchmark Rate`. */
export function titleCase(slug: string): string {
  return slug
    .replace(/[-_]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
    .split(' ')
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
}

/** Friendly label + tooltip for a tool slug, with a humanised fallback. */
export function toolLabel(slug: string): ToolLabel {
  return (
    TOOL_LABELS[slug] ?? {
      label: titleCase(slug),
      hint: `Tool: ${slug}`,
    }
  );
}

// ── Agent name / tagline fallbacks ───────────────────────────────────────────

/**
 * Humanise a registered agent `name` (e.g. `boq_estimator` →
 * `BOQ Estimator`). Common construction acronyms are upper-cased.
 */
const ACRONYMS = new Set([
  'boq',
  'cad',
  'bim',
  'ai',
  'gaeb',
  'din',
  'nrm',
  'qa',
  'qc',
  'kg',
  'us',
  'uk',
]);

export function humanizeAgentName(name: string): string {
  return name
    .replace(/[-_]+/g, ' ')
    .trim()
    .split(/\s+/)
    .map((w) => {
      const lower = w.toLowerCase();
      if (ACRONYMS.has(lower)) return lower.toUpperCase();
      return w.charAt(0).toUpperCase() + w.slice(1);
    })
    .join(' ');
}

/** Best display name for an agent: explicit display_name → humanised name. */
export function agentDisplayName(name: string, displayName?: string | null): string {
  const dn = displayName?.trim();
  return dn && dn.length > 0 ? dn : humanizeAgentName(name);
}

/** Best tagline for an agent: explicit tagline → description → empty. */
export function agentTagline(tagline?: string | null, description?: string | null): string {
  return (tagline?.trim() || description?.trim() || '').trim();
}
