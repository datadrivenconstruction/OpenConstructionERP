// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/**
 * Six standard resource types — promoted to a first-class column in
 * v2940 so the M/L/E breakdown can be filtered and rolled up without
 * description-text inference.
 */
export type ResourceType =
  | 'material'
  | 'labor'
  | 'equipment'
  | 'operator'
  | 'subcontractor'
  | 'overhead';

/**
 * Optional, type-specific metadata fields the editor can attach to a
 * component. The server reads them when computing the typed total
 * (waste/burden uplift, fuel add-on); the FE persists them as-is in
 * the JSON `metadata` blob so adding new vocabulary doesn't require
 * a migration.
 */
export interface ComponentMetadata {
  // Material
  waste_pct?: number;
  vendor?: string;
  // Labor
  crew_size?: number;
  hours?: number;
  productivity?: number;
  base_wage?: number;
  burden_pct?: number;
  skill_level?: string;
  // Equipment
  rental_days?: number;
  hourly_rate?: number;
  fuel_cost?: number;
  // Generic
  notes?: string;
  resource_type?: ResourceType;
  [k: string]: unknown;
}

/**
 * Parametric assemblies (Issue #365). An assembly can carry named
 * parameters and let each component drive its quantity from a formula over
 * them, so one recipe expands to many priced positions.
 *
 * Three kinds:
 * - `input`      — a value the estimator enters (with a stored default).
 * - `constant`   — a fixed value baked into the recipe.
 * - `calculated` — a formula over the other parameters.
 *
 * `value` is Decimal-in / Decimal-as-string out: it ARRIVES as a numeric
 * string (e.g. "0.5") for input/constant, and is `null` for calculated.
 * When sending back (create/update) it stays a numeric string for
 * input/constant (kept exact), and calculated carries a non-empty `formula`
 * string with a null value.
 */
export type ParameterKind = 'input' | 'calculated' | 'constant';

export interface AssemblyParameter {
  name: string;
  kind: ParameterKind;
  value: string | null;
  formula: string | null;
  unit: string;
  description: string;
}

/**
 * One structured problem with a parameter graph or a component formula.
 * `code` is one of: empty_name | duplicate | invalid_value | missing_formula
 * | syntax | invalid_ref | cycle | div_by_zero. `scope` is "parameter" or
 * "component".
 */
export interface ParameterError {
  scope: string;
  name: string;
  code: string;
  message: string;
}

/** Response of POST /v1/assemblies/{id}/validate-parameters/. */
export interface ParameterValidationResponse {
  ok: boolean;
  errors: ParameterError[];
  resolved: Record<string, string>;
}

/**
 * One expanded component line in an expansion preview. All numeric fields are
 * Decimal-exact strings — display them verbatim; only coerce with Number()
 * when arithmetic is unavoidable.
 */
export interface ExpandLine {
  component_id: string | null;
  description: string;
  unit: string;
  resource_type: string | null;
  static_quantity: string;
  computed_quantity: string;
  unit_cost: string;
  total: string;
}

/** Response of POST /v1/assemblies/{id}/expand-preview/. */
export interface ExpandPreviewResponse {
  resolved_parameters: Record<string, string>;
  lines: ExpandLine[];
  total_rate: string;
  errors: ParameterError[];
}

export interface AssemblyComponent {
  id: string;
  assembly_id: string;
  cost_item_id: string | null;
  catalog_resource_id: string | null;
  description: string;
  resource_type: ResourceType | null;
  factor: number;
  quantity: number;
  // Parametric quantity (Issue #365): an arithmetic formula over the parent
  // assembly's parameters. When set it drives the computed quantity at
  // preview / apply time; null keeps the static `quantity` above.
  quantity_formula: string | null;
  unit: string;
  unit_cost: number;
  total: number;
  sort_order: number;
  metadata: ComponentMetadata;
}

export interface Assembly {
  id: string;
  code: string;
  name: string;
  description: string;
  unit: string;
  category: string;
  classification: Record<string, string>;
  total_rate: number;
  currency: string;
  bid_factor: number;
  regional_factors: Record<string, string>;
  is_template: boolean;
  project_id: string | null;
  owner_id: string | null;
  is_active: boolean;
  component_count: number;
  usage_count: number;
  tags: string[];
  // Parametric assembly parameters (Issue #365). Empty for classic recipes.
  // Flows into AssemblyWithComponents (extends Assembly) so the editor can
  // read the parameter graph alongside the components.
  parameters: AssemblyParameter[];
  created_at: string;
  updated_at: string;
}

export interface AssemblyExport {
  code: string;
  name: string;
  description: string;
  unit: string;
  category: string;
  classification: Record<string, string>;
  currency: string;
  bid_factor: number;
  regional_factors: Record<string, string>;
  tags: string[];
  components: Array<{
    description: string;
    resource_type?: ResourceType | null;
    factor: number;
    quantity: number;
    unit: string;
    unit_cost: number;
    sort_order: number;
    metadata?: ComponentMetadata;
  }>;
}

export interface AssemblySearchResponse {
  items: Assembly[];
  total: number;
  limit: number;
  offset: number;
}

export interface AssemblyStats {
  total: number;
  most_used: Array<{ name: string; usage_count: number }>;
  by_category: Record<string, number>;
}

export interface AssemblyWithComponents extends Assembly {
  components: AssemblyComponent[];
}

export interface CreateAssemblyData {
  code: string;
  name: string;
  unit: string;
  category?: string;
  classification?: Record<string, string>;
  currency?: string;
  bid_factor?: number;
  project_id?: string;
  // Issue #365 — create/update carry the parameter graph. For input/constant
  // send a numeric `value`; for calculated send a non-empty `formula`.
  parameters?: AssemblyParameter[];
}

export interface CreateComponentData {
  cost_item_id?: string;
  catalog_resource_id?: string;
  description: string;
  resource_type?: ResourceType;
  factor: number;
  quantity: number;
  // Issue #365 — a formula over the assembly's parameters. Send "" or null to
  // clear it back to the static `quantity`.
  quantity_formula?: string | null;
  unit: string;
  unit_cost: number;
  metadata?: ComponentMetadata;
}

export interface AIGenerateRequest {
  description: string;
  region?: string;
  unit?: string;
}

export interface AIGeneratedComponent {
  name: string;
  code: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  type: string;
  sort_order: number;
  cost_item_id?: string;
}

export interface AIGeneratedAssembly {
  name: string;
  code: string;
  unit: string;
  category: string;
  components: AIGeneratedComponent[];
  total_rate: number;
  source_items_count: number;
  confidence: number;
  description: string;
  region: string;
}

// ── Assembly Library templates (v3.13.0 — Slice 1) ──────────────────────

/** One catalogue-agnostic component inside a library template. */
export interface AssemblyTemplateComponent {
  cost_match_query: string;
  factor: number;
  unit: string;
  role: string;
  description: string;
}

/** A row from the platform-wide Assembly Library. */
export interface AssemblyTemplate {
  id: string;
  name: string;
  name_translations: Record<string, string>;
  category: string;
  unit: string;
  components: AssemblyTemplateComponent[];
  classification: Record<string, string>;
  tags: string[];
  is_builtin: boolean;
  component_count: number;
  created_at: string;
  updated_at: string;
}

export interface AssemblyTemplateSearchResponse {
  items: AssemblyTemplate[];
  total: number;
  limit: number;
  offset: number;
}

export interface AppliedTemplateComponent {
  description: string;
  cost_match_query: string;
  matched_cost_item_id: string | null;
  matched_description: string;
  matched_code: string;
  factor: number;
  scaled_quantity: number;
  unit: string;
  unit_rate: number;
  total: number;
  /** ISO code `unit_rate` and `total` are in — the matched item's own, which is
   *  not necessarily the response's target currency. */
  currency: string;
  /** Whether this component's contribution reached the target-currency total. */
  converted_to_target: boolean;
  role: string;
  match_confidence: number;
  match_channel: string;
}

/** One currency's share of a preview. Never mixed with another's. */
export interface AppliedTemplateCurrencySubtotal {
  currency: string;
  amount: number;
  component_count: number;
  is_target: boolean;
}

export interface AppliedTemplateResponse {
  template_id: string;
  template_name: string;
  project_id: string;
  boq_position_id: string | null;
  quantity: number;
  unit: string;
  currency: string;
  components: AppliedTemplateComponent[];
  /** The authoritative figure: one bucket per currency, always complete. */
  totals_by_currency: AppliedTemplateCurrencySubtotal[];
  /** `null` when the preview spans more than one currency — the backend refuses
   *  to name a single total it could only produce by adding two currencies
   *  together. Render the per-currency breakdown instead, never `Number(null)`,
   *  which would print a confident 0.00. */
  total_rate: number | null;
  grand_total: number | null;
  unresolved_components: string[];
  warnings: string[];
}

export interface ApplyTemplatePayload {
  project_id: string;
  boq_position_id?: string;
  quantity: number;
  region?: string;
  language?: string;
}

/**
 * Money and numeric fields come off the wire as JSON strings: the backend
 * serialises Decimal money as an exact string like "900.0" (the platform's
 * "Decimal-in, Decimal-as-string out" money contract). The interfaces above
 * declare these as `number`, and the Cost Drivers roll-up plus other consumers
 * do real arithmetic on them. A raw string silently turns `a + b` into string
 * concatenation: with two priced components a category total became
 * "0900.0" + "500.0" -> "0900.0500.0" -> Number(...) -> NaN, so `NaN > 0` was
 * false and the whole category vanished from the breakdown (single-component
 * categories survived by luck). Coerce at the API boundary so runtime matches
 * the declared `number` types and every consumer gets real numbers.
 */
const toNum = (v: unknown): number => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : 0;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
};

const normalizeComponent = (c: AssemblyComponent): AssemblyComponent => ({
  ...c,
  factor: toNum(c.factor),
  quantity: toNum(c.quantity),
  unit_cost: toNum(c.unit_cost),
  total: toNum(c.total),
  // Keep the Decimal-as-string formula as-is; null when the line is static.
  quantity_formula: c.quantity_formula ?? null,
});

const normalizeAssembly = <T extends Assembly>(a: T): T => ({
  ...a,
  total_rate: toNum(a.total_rate),
  bid_factor: toNum(a.bid_factor),
  // Parameter `value`s stay Decimal-as-string; only default to [] when the
  // server omits the field (classic non-parametric assemblies).
  parameters: a.parameters ?? [],
});

const normalizeWithComponents = (a: AssemblyWithComponents): AssemblyWithComponents => ({
  ...normalizeAssembly(a),
  components: (a.components ?? []).map(normalizeComponent),
});

export const assembliesApi = {
  list: (params?: Record<string, string>) =>
    apiGet<AssemblySearchResponse>(`/v1/assemblies/?${new URLSearchParams(params)}`).then((r) => ({
      ...r,
      items: (r.items ?? []).map(normalizeAssembly),
    })),
  get: (id: string) =>
    apiGet<AssemblyWithComponents>(`/v1/assemblies/${id}`).then(normalizeWithComponents),
  create: (data: CreateAssemblyData) =>
    apiPost<Assembly>('/v1/assemblies/', data).then(normalizeAssembly),
  update: (id: string, data: Partial<CreateAssemblyData>) =>
    apiPatch<Assembly>(`/v1/assemblies/${id}`, data).then(normalizeAssembly),
  delete: (id: string) => apiDelete(`/v1/assemblies/${id}`),
  addComponent: (assemblyId: string, data: CreateComponentData) =>
    apiPost<AssemblyComponent>(`/v1/assemblies/${assemblyId}/components/`, data).then(
      normalizeComponent,
    ),
  updateComponent: (assemblyId: string, componentId: string, data: Partial<CreateComponentData>) =>
    apiPatch<AssemblyComponent>(
      `/v1/assemblies/${assemblyId}/components/${componentId}`,
      data,
    ).then(normalizeComponent),
  deleteComponent: (assemblyId: string, componentId: string) =>
    apiDelete(`/v1/assemblies/${assemblyId}/components/${componentId}`),
  applyToBoq: (
    assemblyId: string,
    boqId: string,
    quantity: number,
    parameterValues?: Record<string, number>,
  ) =>
    apiPost(`/v1/assemblies/${assemblyId}/apply-to-boq/`, {
      boq_id: boqId,
      quantity,
      // Only send parameter_values when the caller supplies them (Issue #365)
      // so the existing 3-arg call sites keep sending the classic body.
      ...(parameterValues ? { parameter_values: parameterValues } : {}),
    }),
  // Issue #365 — structural check of the parameter graph (no body). Reports
  // cycles / bad references / duplicates / syntax errors plus the resolved
  // default values.
  validateParameters: (id: string) =>
    apiPost<ParameterValidationResponse>(`/v1/assemblies/${id}/validate-parameters/`, {}),
  // Issue #365 — server-authoritative (Decimal-exact) expansion at the given
  // `input` parameter values.
  expandPreview: (id: string, parameterValues: Record<string, number>) =>
    apiPost<ExpandPreviewResponse>(`/v1/assemblies/${id}/expand-preview/`, {
      parameter_values: parameterValues,
    }),
  aiGenerate: (data: AIGenerateRequest) =>
    apiPost<AIGeneratedAssembly>('/v1/assemblies/ai-generate/', data),
  reorderComponents: (assemblyId: string, componentIds: string[]) =>
    apiPost(`/v1/assemblies/${assemblyId}/reorder-components/`, { component_ids: componentIds }),
  exportAssembly: (assemblyId: string) =>
    apiGet<AssemblyExport>(`/v1/assemblies/${assemblyId}/export/`),
  importAssembly: (data: AssemblyExport) =>
    apiPost<Assembly>('/v1/assemblies/import/', { assembly: data }),
  updateTags: (assemblyId: string, tags: string[]) =>
    apiPatch<Assembly>(`/v1/assemblies/${assemblyId}/tags/`, { tags }).then(normalizeAssembly),
  getStats: () => apiGet<AssemblyStats>(`/v1/assemblies/stats/`),

  // Assembly Library templates
  listTemplates: (params?: Record<string, string>) =>
    apiGet<AssemblyTemplateSearchResponse>(
      `/v1/assemblies/templates/?${new URLSearchParams(params)}`
    ),
  getTemplate: (id: string) =>
    apiGet<AssemblyTemplate>(`/v1/assemblies/templates/${id}`),
  applyTemplate: (id: string, body: ApplyTemplatePayload) =>
    apiPost<AppliedTemplateResponse>(`/v1/assemblies/templates/${id}/apply`, body),
};
