// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Visual tokens for the Pipeline Builder — the **single source of truth** for:
 *   - the 7 node-category palettes (color identity + icon), and
 *   - the typed-port {color, shape, dash} map (triple-encoding so wires are
 *     color-blind safe, matching the EAC `SlotConnection` AC-3.6 precedent).
 *
 * This mirrors the EAC `features/eac/tokens.ts` approach: every Tailwind class
 * is emitted as a **static string** (no template interpolation) so the JIT
 * compiler can detect them at build time. If you change the palette, verify
 * the new classes are still covered by `tailwind.config.js` content paths.
 *
 * Light-mode + dark-mode variants are colocated via Tailwind's `dark:`
 * (the project uses `darkMode: 'class'`), so consumers never write `dark:`
 * themselves when they use these token classes.
 */
import type { ComponentType } from 'react';
import {
  Database,
  Download,
  Filter,
  PlayCircle,
  ShieldCheck,
  Sparkles,
  Workflow,
  type LucideProps,
} from 'lucide-react';

// ── Node categories ────────────────────────────────────────────────────────

/**
 * The 7 palette categories, ordered by the *workflow a specialist thinks in*
 * (03_ux_visual §2.1), not by technical type. Phase-1 only surfaces a subset
 * of node types, but all 7 palettes are defined here so Phase-2 nodes drop in
 * without touching component code.
 */
export type NodeCategory =
  | 'trigger' // Sources / Triggers (green)
  | 'source' // Get data (blue)
  | 'transform' // Transform (purple)
  | 'gate' // Validate (amber)
  | 'ai' // AI (violet, always carries a confidence badge)
  | 'action' // Actions / Outputs (slate)
  | 'flow'; // Flow control (gray)

/** Tailwind class set for one category in both light and dark themes. */
export interface CategoryClassSet {
  bg: string;
  bgSelected: string;
  border: string;
  borderSelected: string;
  text: string;
  textSubtle: string;
  icon: string;
  /** Solid, category-colored header bar (rounded top of the node card). */
  header: string;
  /** Title/icon text color that clears WCAG-AA on the header bar. */
  headerText: string;
  /** Quiet secondary text (the category name) on the header bar. */
  headerSubtle: string;
  /** Hover wash for the icon buttons sitting on the header bar. */
  headerHover: string;
  /** Focus/selected ring color for the whole card. */
  ring: string;
}

export interface CategoryTokenEntry {
  classes: CategoryClassSet;
  Icon: ComponentType<LucideProps>;
  /** i18n key for the category section heading. */
  labelKey: string;
  /** English fallback for the category heading. */
  labelDefault: string;
}

/**
 * The canonical mapping of node category → visual tokens. Keep entries here
 * (not inline in components) so tests / minimap / legend / inspector all read
 * from one place.
 */
export const NODE_CATEGORIES: Record<NodeCategory, CategoryTokenEntry> = {
  trigger: {
    classes: {
      bg: 'bg-green-100 dark:bg-green-900/40',
      bgSelected: 'bg-green-200 dark:bg-green-800/60',
      border: 'border-green-300 dark:border-green-700',
      borderSelected: 'border-green-500 dark:border-green-500',
      text: 'text-green-900 dark:text-green-100',
      textSubtle: 'text-green-700 dark:text-green-300',
      icon: 'text-green-700 dark:text-green-300',
      header: 'bg-green-700 dark:bg-green-800',
      headerText: 'text-white',
      headerSubtle: 'text-white/75',
      headerHover: 'hover:bg-white/20',
      ring: 'ring-green-500',
    },
    Icon: PlayCircle,
    labelKey: 'pipeline.palette.cat_trigger',
    labelDefault: 'Sources / Triggers',
  },
  source: {
    classes: {
      bg: 'bg-blue-100 dark:bg-blue-900/40',
      bgSelected: 'bg-blue-200 dark:bg-blue-800/60',
      border: 'border-blue-300 dark:border-blue-700',
      borderSelected: 'border-blue-500 dark:border-blue-500',
      text: 'text-blue-900 dark:text-blue-100',
      textSubtle: 'text-blue-700 dark:text-blue-300',
      icon: 'text-blue-700 dark:text-blue-300',
      header: 'bg-blue-600 dark:bg-blue-700',
      headerText: 'text-white',
      headerSubtle: 'text-white/75',
      headerHover: 'hover:bg-white/20',
      ring: 'ring-blue-500',
    },
    Icon: Database,
    labelKey: 'pipeline.palette.cat_source',
    labelDefault: 'Get data',
  },
  transform: {
    classes: {
      bg: 'bg-purple-100 dark:bg-purple-900/40',
      bgSelected: 'bg-purple-200 dark:bg-purple-800/60',
      border: 'border-purple-300 dark:border-purple-700',
      borderSelected: 'border-purple-500 dark:border-purple-500',
      text: 'text-purple-900 dark:text-purple-100',
      textSubtle: 'text-purple-700 dark:text-purple-300',
      icon: 'text-purple-700 dark:text-purple-300',
      header: 'bg-purple-600 dark:bg-purple-700',
      headerText: 'text-white',
      headerSubtle: 'text-white/75',
      headerHover: 'hover:bg-white/20',
      ring: 'ring-purple-500',
    },
    Icon: Filter,
    labelKey: 'pipeline.palette.cat_transform',
    labelDefault: 'Transform',
  },
  gate: {
    classes: {
      bg: 'bg-amber-100 dark:bg-amber-900/40',
      bgSelected: 'bg-amber-200 dark:bg-amber-800/60',
      border: 'border-amber-300 dark:border-amber-700',
      borderSelected: 'border-amber-500 dark:border-amber-500',
      text: 'text-amber-900 dark:text-amber-100',
      textSubtle: 'text-amber-700 dark:text-amber-300',
      icon: 'text-amber-700 dark:text-amber-300',
      header: 'bg-amber-300 dark:bg-amber-400',
      headerText: 'text-amber-900',
      headerSubtle: 'text-amber-900/75',
      headerHover: 'hover:bg-black/10',
      ring: 'ring-amber-500',
    },
    Icon: ShieldCheck,
    labelKey: 'pipeline.palette.cat_gate',
    labelDefault: 'Validate',
  },
  ai: {
    classes: {
      bg: 'bg-violet-100 dark:bg-violet-900/40',
      bgSelected: 'bg-violet-200 dark:bg-violet-800/60',
      border: 'border-violet-300 dark:border-violet-700',
      borderSelected: 'border-violet-500 dark:border-violet-500',
      text: 'text-violet-900 dark:text-violet-100',
      textSubtle: 'text-violet-700 dark:text-violet-300',
      icon: 'text-violet-700 dark:text-violet-300',
      header: 'bg-violet-600 dark:bg-violet-700',
      headerText: 'text-white',
      headerSubtle: 'text-white/75',
      headerHover: 'hover:bg-white/20',
      ring: 'ring-violet-500',
    },
    Icon: Sparkles,
    labelKey: 'pipeline.palette.cat_ai',
    labelDefault: 'AI',
  },
  action: {
    classes: {
      bg: 'bg-slate-100 dark:bg-slate-800',
      bgSelected: 'bg-slate-200 dark:bg-slate-700',
      border: 'border-slate-300 dark:border-slate-600',
      borderSelected: 'border-slate-500 dark:border-slate-400',
      text: 'text-slate-900 dark:text-slate-100',
      textSubtle: 'text-slate-600 dark:text-slate-400',
      icon: 'text-slate-700 dark:text-slate-300',
      header: 'bg-slate-600 dark:bg-slate-700',
      headerText: 'text-white',
      headerSubtle: 'text-white/75',
      headerHover: 'hover:bg-white/20',
      ring: 'ring-slate-400',
    },
    Icon: Download,
    labelKey: 'pipeline.palette.cat_action',
    labelDefault: 'Actions / Outputs',
  },
  flow: {
    classes: {
      bg: 'bg-gray-100 dark:bg-gray-800',
      bgSelected: 'bg-gray-200 dark:bg-gray-700',
      border: 'border-gray-300 dark:border-gray-600',
      borderSelected: 'border-gray-500 dark:border-gray-400',
      text: 'text-gray-900 dark:text-gray-100',
      textSubtle: 'text-gray-600 dark:text-gray-400',
      icon: 'text-gray-700 dark:text-gray-300',
      header: 'bg-gray-600 dark:bg-gray-700',
      headerText: 'text-white',
      headerSubtle: 'text-white/75',
      headerHover: 'hover:bg-white/20',
      ring: 'ring-gray-400',
    },
    Icon: Workflow,
    labelKey: 'pipeline.palette.cat_flow',
    labelDefault: 'Flow control',
  },
};

/** Order categories are rendered in the palette accordion. */
export const CATEGORY_ORDER: NodeCategory[] = [
  'trigger',
  'source',
  'transform',
  'gate',
  'ai',
  'action',
  'flow',
];

/** Lookup helper — falls back to `flow` for an unknown category. */
export function getCategoryTokens(category: string): CategoryTokenEntry {
  return NODE_CATEGORIES[category as NodeCategory] ?? NODE_CATEGORIES.flow;
}

/** Hex color used for the minimap dot of a category (xyflow MiniMap nodeColor). */
export const CATEGORY_MINIMAP_COLOR: Record<NodeCategory, string> = {
  trigger: '#16a34a',
  source: '#2563eb',
  transform: '#9333ea',
  gate: '#d97706',
  ai: '#7c3aed',
  action: '#475569',
  flow: '#6b7280',
};

// ── Typed-port map (triple-encoded: color + shape + dash) ───────────────────

/**
 * The logical data type travelling along a wire. These mirror the bare port
 * names the backend advertises (see {@link inferPortType}). Kept narrow on
 * purpose; adding a type requires an entry in `PORT_TYPES` *and*
 * `PORT_COMPATIBILITY` so the matrix stays exhaustive.
 */
export type PortDataType =
  | 'rows' // tabular data (BOQ rows, cost items, query results)
  | 'project' // a project / context object
  | 'trigger' // a control signal that starts a step
  | 'file' // document / export artefact
  | 'any'; // passthrough / wildcard

export type PortShape = 'circle' | 'square' | 'diamond' | 'triangle' | 'hexagon' | 'ring' | 'cross';

export interface PortTypeEntry {
  /** Stroke color (also the handle border) — static hex, used inline by SVG. */
  color: string;
  shape: PortShape;
  /** SVG edge dash array, or `undefined` for a solid stroke. */
  dash: string | undefined;
  /** i18n key for the human-readable type label (used in tooltips / a11y). */
  labelKey: string;
  labelDefault: string;
  /** i18n key for a compact one-word type label (shown inline on port rows). */
  shortKey: string;
  shortDefault: string;
}

/**
 * Single source of truth for port + edge styling (03_ux_visual §2.2 table).
 * Color + shape + dash = triple encoding → color-blind safe.
 */
export const PORT_TYPES: Record<PortDataType, PortTypeEntry> = {
  rows: {
    color: '#2563eb',
    shape: 'circle',
    dash: undefined,
    labelKey: 'pipeline.port.rows',
    labelDefault: 'Table rows',
    shortKey: 'pipeline.port.rows.short',
    shortDefault: 'Rows',
  },
  project: {
    color: '#ea580c',
    shape: 'hexagon',
    dash: undefined,
    labelKey: 'pipeline.port.project',
    labelDefault: 'Project',
    shortKey: 'pipeline.port.project.short',
    shortDefault: 'Project',
  },
  trigger: {
    color: '#16a34a',
    shape: 'triangle',
    dash: undefined,
    labelKey: 'pipeline.port.trigger',
    labelDefault: 'Trigger signal',
    shortKey: 'pipeline.port.trigger.short',
    shortDefault: 'Trigger',
  },
  file: {
    color: '#475569',
    shape: 'square',
    dash: undefined,
    labelKey: 'pipeline.port.file',
    labelDefault: 'File / document',
    shortKey: 'pipeline.port.file.short',
    shortDefault: 'File',
  },
  any: {
    color: '#94a3b8',
    shape: 'ring',
    dash: '4 4',
    labelKey: 'pipeline.port.any',
    labelDefault: 'Any / passthrough',
    shortKey: 'pipeline.port.any.short',
    shortDefault: 'Any',
  },
};

/** Order the port types are listed in the legend / help surfaces. */
export const PORT_TYPE_ORDER: PortDataType[] = [
  'rows',
  'project',
  'trigger',
  'file',
  'any',
];

/** Lookup helper — falls back to `any` for an unknown port type. */
export function getPortTokens(type: string): PortTypeEntry {
  return PORT_TYPES[type as PortDataType] ?? PORT_TYPES.any;
}

/** Narrow an arbitrary string to a known {@link PortDataType}. */
export function isPortDataType(value: string): value is PortDataType {
  return Object.prototype.hasOwnProperty.call(PORT_TYPES, value);
}

/**
 * Infer a port's data type from its bare name. The backend advertises ports as
 * plain strings ("rows", "project", "trigger", "file", "rows_a", "rows_b"), so
 * we map the name onto the typed-port palette: anything mentioning a row is
 * tabular data, the well-known context names map 1:1, and everything else falls
 * back to the permissive `any` passthrough. This is what lights up the port
 * glyphs, edge colors and the legend.
 */
export function inferPortType(name: string): PortDataType {
  const n = name.trim().toLowerCase();
  if (n.includes('row')) return 'rows';
  if (n === 'project') return 'project';
  if (n === 'trigger') return 'trigger';
  if (n === 'file') return 'file';
  return 'any';
}

/**
 * Which output type may feed which input type. `any` is a wildcard on either
 * side; every other type only connects to its own type or to `any`.
 */
export const PORT_COMPATIBILITY: Record<PortDataType, ReadonlySet<PortDataType>> = {
  rows: new Set<PortDataType>(['rows', 'any']),
  project: new Set<PortDataType>(['project', 'any']),
  trigger: new Set<PortDataType>(['trigger', 'any']),
  file: new Set<PortDataType>(['file', 'any']),
  any: new Set<PortDataType>(['rows', 'project', 'trigger', 'file', 'any']),
};

/** True when an output of `source` type may be wired into a `target` input. */
export function isPortCompatible(source: string, target: string): boolean {
  const allowed = PORT_COMPATIBILITY[source as PortDataType];
  if (!allowed) return false;
  return allowed.has(target as PortDataType);
}

/**
 * SVG `points`/`d`-free shape renderer helper data. The actual glyph is drawn
 * as a small inline SVG in `PipelineNode`; we centralise the viewBox geometry
 * here so node, legend, and inspector all render the identical mark.
 */
export const PORT_SHAPE_SVG: Record<PortShape, string> = {
  circle: '<circle cx="6" cy="6" r="5" />',
  square: '<rect x="1.5" y="1.5" width="9" height="9" rx="1" />',
  diamond: '<path d="M6 1 L11 6 L6 11 L1 6 Z" />',
  triangle: '<path d="M6 1.5 L11 10.5 L1 10.5 Z" />',
  hexagon: '<path d="M6 1 L10.3 3.5 L10.3 8.5 L6 11 L1.7 8.5 L1.7 3.5 Z" />',
  ring: '<circle cx="6" cy="6" r="4" fill="none" stroke-width="2" />',
  cross: '<path d="M2 2 L10 10 M10 2 L2 10" fill="none" stroke-width="2" />',
};
