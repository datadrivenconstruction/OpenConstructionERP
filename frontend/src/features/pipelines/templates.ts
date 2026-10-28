// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Starter templates for the Pipeline Builder - ready-made automation graphs a
 * user can drop onto an empty canvas and run (or tweak) in one click.
 *
 * These are the platform's built-in automation rules: each is a small,
 * jurisdiction-neutral construction workflow (guard a budget, flag zero-priced
 * items, validate before export, ...) wired only from node types that ship in
 * the base engine, so every template is valid the moment it lands on the
 * canvas. The graphs are plain {@link PipelineGraph} data - the same shape a
 * saved pipeline round-trips through - so loading one reuses the exact
 * hydration path the canvas already uses for opening a saved workflow.
 *
 * Adding a template: append to {@link PIPELINE_TEMPLATES}. Keep it built from
 * shipped node types (see `GET /node-types/`) and give it a one-line,
 * plain-language description a site engineer understands without a manual.
 */
import type { PipelineGraph, PipelineGraphEdge, PipelineGraphNode } from './api';

/** A named starter graph shown in the template gallery. */
export interface PipelineTemplate {
  /** Stable id (used as the React key and the "recently used" marker). */
  id: string;
  /** Short title. Shown on the gallery card and used as the pipeline name. */
  name: string;
  /** One-line, plain-language summary of what the automation does. */
  description: string;
  /** Grouping tag for the gallery ("Quality", "Cost", "Reporting", ...). */
  tag: TemplateTag;
  /** The ready-to-run graph. */
  graph: PipelineGraph;
}

export type TemplateTag = 'quality' | 'cost' | 'reporting' | 'catalog';

// ── Builders ────────────────────────────────────────────────────────────────
// A template graph is almost always a left-to-right chain, so we describe each
// step as [type, params] and let `chain()` lay them out and wire them. The port
// handles match the backend node-type ports (bare names: "trigger", "rows",
// "file"); a step that starts from a trigger uses the "trigger" handle for its
// first hop, everything downstream flows on "rows".

type Step = {
  type: string;
  params?: Record<string, unknown>;
  /** Output port this step emits on (defaults to "rows"). */
  out?: string;
  /** Input port the NEXT step consumes on (defaults to "rows"). */
  nextIn?: string;
};

const X0 = 60;
const Y0 = 150;
const DX = 235;

/** Build a linear graph from an ordered list of steps. */
function chain(steps: Step[]): PipelineGraph {
  const nodes: PipelineGraphNode[] = steps.map((s, i) => ({
    id: `n${i + 1}`,
    type: s.type,
    params: s.params ?? {},
    position: { x: X0 + i * DX, y: Y0 },
  }));
  const edges: PipelineGraphEdge[] = [];
  for (let i = 0; i < steps.length - 1; i += 1) {
    const from = steps[i]!;
    const handle = from.out ?? 'rows';
    const targetHandle = from.nextIn ?? 'rows';
    edges.push({
      id: `e${i + 1}`,
      source: `n${i + 1}`,
      target: `n${i + 2}`,
      sourceHandle: handle,
      targetHandle,
    });
  }
  return { nodes, edges };
}

// A manual trigger feeding a source: the trigger emits on "trigger" and the
// source reads its "trigger" port, then the source emits rows downstream.
const trigger = (): Step => ({ type: 'trigger.manual', out: 'trigger', nextIn: 'trigger' });

// ── Templates ─────────────────────────────────────────────────────────────

export const PIPELINE_TEMPLATES: readonly PipelineTemplate[] = [
  {
    id: 'zero-priced-items',
    name: 'Zero-priced items report',
    description:
      'Find every BOQ position that still has a unit rate of 0 and export the list to review.',
    tag: 'quality',
    graph: chain([
      trigger(),
      { type: 'source.boq' },
      { type: 'transform.filter', params: { field: 'unit_rate', op: 'eq', value: 0 } },
      { type: 'action.export.excel', params: { filename: 'zero-priced-items' } },
    ]),
  },
  {
    id: 'top-cost-positions',
    name: 'Top 10 costliest positions',
    description:
      'Rank BOQ positions by unit rate, keep the ten highest and export them for a quick cost review.',
    tag: 'cost',
    graph: chain([
      { type: 'source.boq' },
      { type: 'transform.sort', params: { field: 'unit_rate', descending: true } },
      { type: 'transform.limit', params: { count: 10 } },
      { type: 'action.export.excel', params: { filename: 'top-cost-positions' } },
    ]),
  },
  {
    id: 'budget-ceiling-guard',
    name: 'Budget ceiling guard',
    description:
      'Roll up the estimate total and stop the run if it goes over the ceiling you set, otherwise export it.',
    tag: 'cost',
    graph: chain([
      { type: 'source.boq' },
      { type: 'transform.rollup' },
      { type: 'gate.budget', params: { max_total: 1000000 } },
      { type: 'action.export.csv', params: { filename: 'budget-check' } },
    ]),
  },
  {
    id: 'validate-before-export',
    name: 'Validate before export',
    description:
      'Run the BOQ quality rules first and only produce the export when the estimate passes the gate.',
    tag: 'quality',
    graph: chain([
      { type: 'source.boq' },
      { type: 'gate.validation', params: { rule_sets: ['boq_quality'] } },
      { type: 'action.export.excel', params: { filename: 'validated-boq' } },
    ]),
  },
  {
    id: 'duplicate-ordinals',
    name: 'Duplicate ordinal cleanup preview',
    description:
      'Drop rows that repeat an ordinal so you can see the de-duplicated position list before fixing the source.',
    tag: 'quality',
    graph: chain([
      { type: 'source.boq' },
      { type: 'transform.dedupe', params: { field: 'ordinal' } },
      { type: 'action.export.csv', params: { filename: 'deduped-positions' } },
    ]),
  },
  {
    id: 'regional-markup-pricelist',
    name: 'Regional markup price list',
    description:
      'Load priced catalog items, raise every rate by a regional markup, sort them and export a price list.',
    tag: 'catalog',
    graph: chain([
      { type: 'source.cost_catalog', params: { query: '', limit: 200 } },
      { type: 'transform.markup', params: { percent: 12 } },
      { type: 'transform.sort', params: { field: 'unit_rate', descending: true } },
      { type: 'action.export.excel', params: { filename: 'regional-pricelist' } },
    ]),
  },
  {
    id: 'trade-filtered-export',
    name: 'Trade-filtered export',
    description:
      'Keep only positions whose description mentions a trade keyword, sort by rate and export that trade package.',
    tag: 'reporting',
    graph: chain([
      { type: 'source.boq' },
      { type: 'transform.filter', params: { field: 'description', op: 'contains', value: 'concrete' } },
      { type: 'transform.sort', params: { field: 'unit_rate', descending: true } },
      { type: 'action.export.excel', params: { filename: 'trade-package' } },
    ]),
  },
  {
    id: 'catalog-search-export',
    name: 'Catalog search export',
    description:
      'Search the cost catalog for a keyword and export the matching priced items to a CSV.',
    tag: 'catalog',
    graph: chain([
      { type: 'source.cost_catalog', params: { query: 'concrete', limit: 100 } },
      { type: 'action.export.csv', params: { filename: 'catalog-search' } },
    ]),
  },
  {
    id: 'empty-boq-guard',
    name: 'Non-empty BOQ guard',
    description:
      'Stop early when a project has no priced positions yet, so an empty estimate never reaches an export.',
    tag: 'quality',
    graph: chain([
      trigger(),
      { type: 'source.boq' },
      { type: 'gate.count', params: { min_rows: 1 } },
      { type: 'action.export.excel', params: { filename: 'boq-snapshot' } },
    ]),
  },
  {
    id: 'cost-rollup-report',
    name: 'Cost roll-up report',
    description:
      'Check the estimate has positions, roll up the totals and export a compact cost summary.',
    tag: 'reporting',
    graph: chain([
      { type: 'source.boq' },
      { type: 'gate.count', params: { min_rows: 1 } },
      { type: 'transform.rollup' },
      { type: 'action.export.csv', params: { filename: 'cost-rollup' } },
    ]),
  },
] as const;

export const TEMPLATE_TAG_LABELS: Record<TemplateTag, string> = {
  quality: 'Quality',
  cost: 'Cost',
  reporting: 'Reporting',
  catalog: 'Catalog',
};
