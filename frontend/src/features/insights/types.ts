// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Module Insights - the shared contract for the toggleable visualization
 * panel that every module can embed. A module hands the panel one or more
 * {@link InsightDataset}s (its already-loaded rows) plus a set of built-in
 * {@link InsightDef}s; the panel renders those and lets the user build their
 * own from the same datasets. Definitions are intentionally serialisable so a
 * chart can later be pinned to the cross-module dashboard unchanged.
 */

/** How a single chart draws its data. */
export type ChartKind = 'kpi' | 'bar' | 'line' | 'area' | 'donut';

/** How rows collapse to a value per group (or per KPI). */
export type Aggregation = 'sum' | 'avg' | 'count' | 'min' | 'max';

/** How a measure reads once aggregated. */
export type ValueFormat = 'number' | 'currency' | 'percent';

/** One column a dataset exposes to the panel and the builder. */
export interface InsightField {
  /** Row key. */
  key: string;
  /** Human label shown in the builder and axes. */
  label: string;
  /** Dimensions group (x axis / slices); measures are aggregated (y axis / value). */
  kind: 'dimension' | 'measure';
  /** Measure display format; ignored for dimensions. Defaults to 'number'. */
  format?: ValueFormat;
}

/** A named table of rows a module exposes for charting. */
export interface InsightDataset {
  id: string;
  label: string;
  rows: Array<Record<string, string | number | null | undefined>>;
  fields: InsightField[];
  /** Currency code for currency-formatted measures (e.g. 'EUR'); '' if unknown. */
  currency?: string;
  /** True when these rows are illustrative samples, not the user's real data. */
  sample?: boolean;
}

/** A single chart: which dataset, how to draw it, what to group and measure. */
export interface InsightDef {
  id: string;
  title: string;
  datasetId: string;
  chart: ChartKind;
  /** Dimension field key (x axis / slices). Omitted for KPI. */
  dimension?: string;
  /** Measure field key (y axis / value). Omitted when agg is 'count'. */
  measure?: string;
  agg: Aggregation;
  /** Built-ins ship with the module and cannot be edited or removed. */
  builtin?: boolean;
  /** Palette index for the accent colour. */
  color?: number;
}
