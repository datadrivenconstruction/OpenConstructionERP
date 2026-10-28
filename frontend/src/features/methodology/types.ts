// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// TypeScript types for the estimating-methodology engine, mirroring the
// backend Pydantic schemas in backend/app/modules/methodology/schemas.py.
//
// MONEY / RATE CONTRACT (important):
// The backend stores money and rates as Decimal and serialises them as plain
// decimal STRINGS in JSON (the platform's "Decimal-in, Decimal-as-string out"
// contract, identical to the BOQ module). So every `rate`, `amount`,
// `vat_rate`, base/composite total and cascade total arrives as a `string`.
// These are typed as `string` here on purpose. NEVER do `a + b` or `.toFixed`
// directly on them (string `+` silently concatenates - the bug class that
// produced "0900.0500.0" -> NaN elsewhere in this codebase). Always coerce
// with `toNum(x)` (see api.ts) before any arithmetic or formatting.

/** Where a methodology originates. Mirrors Methodology.scope. */
export type MethodologyScope = 'builtin' | 'project' | 'pack';

/** A cascade step kind. */
export type StepKind = 'percentage' | 'fixed';

/** An analytical-dimension kind. */
export type DimensionKind = 'flat' | 'tree';

/**
 * One ordered markup step in a methodology cascade.
 *
 * `base` lists the tokens this step applies to - each a leaf base key, a
 * composite name, or the key of an EARLIER step. `rate` is a percentage (used
 * when kind === 'percentage'); `amount` is a fixed value (used when
 * kind === 'fixed'). Both arrive as decimal strings.
 */
export interface MarkupStep {
  key: string;
  label: string;
  category: string;
  kind: StepKind;
  /** Percentage rate as a decimal string, e.g. "12" or "0.32". */
  rate: string;
  /** Fixed amount as a decimal string (used when kind === 'fixed'). */
  amount: string;
  base: string[];
}

/** A value within an analytical dimension (response shape). */
export interface DimensionValue {
  id: string;
  dimension_id: string;
  parent_id: string | null;
  code: string;
  label: string;
  sort_order: number;
  metadata: Record<string, unknown>;
}

/** A value to create within an analytical dimension. */
export interface DimensionValueCreate {
  code: string;
  label: string;
  parent_code?: string | null;
  sort_order?: number;
  metadata?: Record<string, unknown>;
}

/** An analytical dimension returned from the API, with its values. */
export interface Dimension {
  id: string;
  project_id: string | null;
  methodology_slug: string | null;
  key: string;
  label: string;
  kind: DimensionKind;
  is_required: boolean;
  sort_order: number;
  values: DimensionValue[];
  metadata: Record<string, unknown>;
}

/** Create an analytical dimension under a project (and/or methodology). */
export interface DimensionCreate {
  project_id: string;
  methodology_slug?: string | null;
  key: string;
  label: string;
  kind?: DimensionKind;
  is_required?: boolean;
  sort_order?: number;
  values?: DimensionValueCreate[];
  metadata?: Record<string, unknown>;
}

/** A funding source returned from the API. */
export interface FundingSource {
  id: string;
  project_id: string | null;
  code: string;
  name: string;
  sort_order: number;
  metadata: Record<string, unknown>;
}

/** Create a funding-source master entry for a project. */
export interface FundingSourceCreate {
  project_id: string;
  code: string;
  name: string;
  sort_order?: number;
  metadata?: Record<string, unknown>;
}

/** Partial update for a funding source. */
export interface FundingSourceUpdate {
  code?: string;
  name?: string;
  sort_order?: number;
  metadata?: Record<string, unknown>;
}

/** A methodology returned from the API (full shape). */
export interface Methodology {
  id: string;
  slug: string;
  scope: MethodologyScope;
  project_id: string | null;
  is_builtin: boolean;
  is_editable: boolean;
  name: string;
  description: string | null;
  country_code: string | null;
  industry: string | null;
  currency: string;
  decimals: number;
  hierarchy_levels: Array<Record<string, unknown>>;
  dimension_scheme: Array<Record<string, unknown>>;
  column_preset: string | null;
  base_mapping: Record<string, string[]>;
  composites: Record<string, string[]>;
  cascade_steps: MarkupStep[];
  /**
   * Catalogue fact about a country, recorded when the methodology was minted.
   * Nothing prices from it: the cascade's `tax` step computes, and a project
   * stating its own rate replaces that step. Read `effective_vat` to learn
   * what a project is actually charged.
   */
  vat_rate: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  /**
   * Which VAT rate this methodology is priced at for the asking project.
   * Absent on endpoints that were not asked on behalf of a project; absence
   * never means "no VAT applies".
   */
  effective_vat?: EffectiveVat | null;
}

/** The VAT rate a methodology is actually priced at for a project, and why. */
export interface EffectiveVat {
  /** Rate applied, as a decimal string, or null when no single tax line exists. */
  rate: string | null;
  /**
   * `project` when the project's own rate is substituted for the stack's tax
   * line, `methodology` when the stack speaks for itself, `none` when there is
   * no single tax line to name a rate for.
   */
  source: 'project' | 'methodology' | 'none';
  /** What the stored cascade says, for showing both figures side by side. */
  stored_rate: string | null;
  /** True only when the priced rate and the stored rate genuinely differ. */
  differs_from_stored: boolean;
}

/** Compact methodology row for list endpoints. */
export interface MethodologyListItem {
  id: string;
  slug: string;
  scope: MethodologyScope;
  project_id: string | null;
  country_code: string | null;
  industry: string | null;
  name: string;
  currency: string;
  is_builtin: boolean;
  is_editable: boolean;
}

/** A built-in template descriptor (catalogue listing, not yet installed). */
export interface TemplateListItem {
  slug: string;
  name: string;
  description: string;
  country_code: string | null;
  industry: string | null;
  currency: string;
  step_count: number;
}

/** Create a project-scoped methodology. */
export interface MethodologyCreate {
  project_id: string;
  slug?: string;
  name: string;
  description?: string | null;
  country_code?: string | null;
  industry?: string | null;
  currency?: string;
  decimals?: number;
  hierarchy_levels?: Array<Record<string, unknown>>;
  dimension_scheme?: Array<Record<string, unknown>>;
  column_preset?: string | null;
  base_mapping?: Record<string, string[]>;
  composites?: Record<string, string[]>;
  cascade_steps?: MarkupStep[];
  vat_rate?: string | null;
  metadata?: Record<string, unknown>;
}

/**
 * Partial update for a methodology. Every field is optional; only the ones
 * present are sent. `cascade_steps`, `base_mapping`, `composites` are replaced
 * wholesale when present (the backend does NOT deep-merge them); `metadata` is
 * merged server-side.
 */
export interface MethodologyUpdate {
  name?: string;
  description?: string | null;
  country_code?: string | null;
  industry?: string | null;
  currency?: string;
  decimals?: number;
  hierarchy_levels?: Array<Record<string, unknown>>;
  dimension_scheme?: Array<Record<string, unknown>>;
  column_preset?: string | null;
  base_mapping?: Record<string, string[]>;
  composites?: Record<string, string[]>;
  cascade_steps?: MarkupStep[];
  vat_rate?: string | null;
  metadata?: Record<string, unknown>;
}

/** Install a built-in template into a project as a project-scoped clone. */
export interface InstallTemplateRequest {
  project_id: string;
  template_slug: string;
  /** Reuse an existing clone of the same source template (default true). */
  idempotent?: boolean;
  /** Activate the installed methodology on the project (default false). */
  set_active?: boolean;
}

/** Request to compute a cascade for a project under a chosen methodology. */
export interface ComputeEstimateRequest {
  project_id: string;
  /** Override the project's active methodology for a what-if computation. */
  methodology_slug?: string | null;
  boq_id?: string | null;
  /** Caller-supplied, already-aggregated per-resource-type totals. */
  resource_totals?: Record<string, number | string> | null;
}

/** The computed outcome of one cascade step (all money fields are strings). */
export interface StepResult {
  key: string;
  label: string;
  category: string;
  kind: StepKind;
  rate: string;
  base_amount: string;
  amount: string;
  running_total: string;
}

/** The full result of computing a methodology cascade for a project. */
export interface ComputeEstimateResponse {
  project_id: string;
  methodology_slug: string;
  currency: string;
  decimals: number;
  /** Leaf base token -> amount (decimal string). */
  bases: Record<string, string>;
  /** Composite name -> amount (decimal string). */
  composites: Record<string, string>;
  steps: StepResult[];
  direct_total: string;
  markup_total: string;
  grand_total: string;
}

/** The active-methodology pointer for a project. */
export interface ActiveMethodology {
  project_id: string;
  methodology_slug: string;
}

/** The neutral default methodology slug a project falls back to. */
export const INTERNATIONAL_SLUG = 'international';
