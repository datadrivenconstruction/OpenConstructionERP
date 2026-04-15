import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Core BOQ types ──────────────────────────────────────────────────── */

export interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
  estimate_type: string | null;
  is_locked: boolean;
  created_at: string;
  updated_at: string;
}

export interface Position {
  id: string;
  boq_id: string;
  parent_id: string | null;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  classification: Record<string, string>;
  source: string;
  confidence: number | null;
  sort_order: number;
  validation_status: string;
  /** BIM element IDs linked to this position (cross-highlight source). */
  cad_element_ids?: string[];
  /** Backend returns `metadata_` (aliased) — normalize to `metadata` in fetch layer */
  metadata: Record<string, unknown>;
  metadata_?: Record<string, unknown>;
}

export interface BOQWithPositions extends BOQ {
  positions: Position[];
  grand_total: number;
}

/* ── Markup types ────────────────────────────────────────────────────── */

export interface Markup {
  id: string;
  boq_id: string;
  name: string;
  markup_type: 'percentage' | 'fixed' | 'per_unit';
  category: 'overhead' | 'profit' | 'tax' | 'contingency' | 'insurance' | 'bond' | 'other';
  percentage: number;
  fixed_amount: number;
  apply_to: 'direct_cost' | 'subtotal' | 'cumulative';
  sort_order: number;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MarkupsResponse {
  markups: Markup[];
}

export interface CreateMarkupData {
  name: string;
  markup_type?: string;
  category?: string;
  percentage?: number;
  fixed_amount?: number;
  apply_to?: string;
  sort_order?: number;
  is_active?: boolean;
}

export interface UpdateMarkupData {
  name?: string;
  markup_type?: string;
  category?: string;
  percentage?: number;
  fixed_amount?: number;
  apply_to?: string;
  sort_order?: number;
  is_active?: boolean;
}

/* ── Create / Update payloads ────────────────────────────────────────── */

export interface CreateBOQData {
  project_id: string;
  name: string;
  description?: string;
}

export interface CreatePositionData {
  boq_id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  classification?: Record<string, string>;
  parent_id?: string;
}

export interface UpdatePositionData {
  ordinal?: string;
  description?: string;
  unit?: string;
  quantity?: number;
  unit_rate?: number;
  classification?: Record<string, string>;
  parent_id?: string | null;
  source?: string;
  metadata?: Record<string, unknown>;
  sort_order?: number;
}

/* ── Normalize backend metadata_ → metadata ─────────────────────── */

/** Backend returns `metadata_` due to SQLAlchemy naming. Normalize to `metadata`. */
export function normalizePosition(p: Position): Position {
  if (!p.metadata && p.metadata_) {
    return { ...p, metadata: p.metadata_ };
  }
  if (!p.metadata) {
    return { ...p, metadata: {} };
  }
  return p;
}

export function normalizePositions(positions: Position[]): Position[] {
  return positions.map(normalizePosition);
}

/* ── Section helpers (used on the frontend to group positions) ────── */

/** A section is a position with no unit (acts as a group header). */
export function isSection(pos: Position): boolean {
  return !pos.unit || pos.unit.trim() === '' || pos.unit.trim().toLowerCase() === 'section';
}

/**
 * Organizes a flat positions list into sections with children.
 * A section is any position where `unit` is empty.
 * Positions with a `parent_id` pointing to a section go under that section.
 * Positions without a parent that are not sections go into an "Ungrouped" virtual bucket.
 */
export interface SectionGroup {
  section: Position;
  children: Position[];
  subtotal: number;
}

export function groupPositionsIntoSections(positions: Position[]): {
  sections: SectionGroup[];
  ungrouped: Position[];
} {
  const sections: SectionGroup[] = [];
  const ungrouped: Position[] = [];
  const sectionMap = new Map<string, SectionGroup>();

  // First pass: identify sections
  const sortedPositions = [...positions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
    return a.ordinal.localeCompare(b.ordinal, undefined, { numeric: true });
  });

  for (const pos of sortedPositions) {
    if (isSection(pos)) {
      const group: SectionGroup = { section: pos, children: [], subtotal: 0 };
      sectionMap.set(pos.id, group);
      sections.push(group);
    }
  }

  // Second pass: assign children to sections
  for (const pos of sortedPositions) {
    if (isSection(pos)) continue;

    if (pos.parent_id && sectionMap.has(pos.parent_id)) {
      const group = sectionMap.get(pos.parent_id)!;
      group.children.push(pos);
      group.subtotal += pos.total;
    } else {
      ungrouped.push(pos);
    }
  }

  return { sections, ungrouped };
}

/* ── Hierarchical tree builder (multi-level BOQ) ─────────────────────── */

export interface HierarchyNode {
  position: Position;
  level: number;
  children: HierarchyNode[];
  subtotal: number;
}

/**
 * Build a recursive tree from flat positions list.
 * Supports unlimited nesting depth via parent_id references.
 * Sections and positions can appear at any level.
 */
export function buildHierarchy(positions: Position[]): HierarchyNode[] {
  const sorted = [...positions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
    return a.ordinal.localeCompare(b.ordinal, undefined, { numeric: true });
  });

  const posMap = new Map<string, Position>();
  for (const p of sorted) posMap.set(p.id, p);

  function buildChildren(parentId: string | null, level: number): HierarchyNode[] {
    const children = sorted.filter((p) => p.parent_id === parentId);
    return children.map((pos) => {
      const childNodes = buildChildren(pos.id, level + 1);
      const subtotal = isSection(pos)
        ? childNodes.reduce((sum, c) => sum + c.subtotal, 0)
        : pos.total;
      return { position: pos, level, children: childNodes, subtotal };
    });
  }

  return buildChildren(null, 0);
}

/**
 * Get the depth (level) of a position in the hierarchy.
 * Follows parent_id chain up to root.
 */
export function getPositionDepth(pos: Position, posMap: Map<string, Position>): number {
  let depth = 0;
  let current = pos;
  while (current.parent_id && posMap.has(current.parent_id)) {
    depth++;
    current = posMap.get(current.parent_id)!;
  }
  return depth;
}

/* ── Activity types ──────────────────────────────────────────────────── */

export type ActivityAction =
  | 'position_added'
  | 'position_updated'
  | 'position_deleted'
  | 'quantity_updated'
  | 'rate_updated'
  | 'section_added'
  | 'section_deleted'
  | 'validation_run'
  | 'excel_imported'
  | 'csv_imported'
  | 'boq_created'
  | 'template_applied'
  | 'markup_added'
  | 'markup_updated'
  | 'status_changed';

export interface ActivityEntry {
  id: string;
  boq_id: string;
  action: ActivityAction;
  description: string;
  details: Record<string, unknown>;
  created_at: string;
  user_name?: string;
}

export interface ActivityResponse {
  activities: ActivityEntry[];
  total: number;
}

export interface ProjectActivityEntry {
  id: string;
  project_id: string | null;
  boq_id: string | null;
  user_id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  description: string;
  changes: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
}

/* ── Cost autocomplete types ─────────────────────────────────────────── */

export interface CostItemComponent {
  name: string;
  code?: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  cost: number;
  type: string;
}

export interface CostAutocompleteItem {
  code: string;
  description: string;
  unit: string;
  rate: number;
  classification: Record<string, string>;
  components: CostItemComponent[];
}

/* ── AI Chat types ──────────────────────────────────────────────────── */

export interface AIChatContext {
  project_name: string;
  currency: string;
  standard: string;
  existing_positions_count: number;
}

export interface AIChatRequest {
  message: string;
  context: AIChatContext;
  locale?: string;
}

export interface AIChatItem {
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
}

export interface AIChatResponse {
  items: AIChatItem[];
  message: string;
}

/* ── Cost Breakdown types ─────────────────────────────────────────── */

export interface CostBreakdownCategory {
  type: string;
  amount: number;
  percentage: number;
  item_count: number;
}

export interface CostBreakdownMarkup {
  name: string;
  percentage: number;
  amount: number;
}

export interface CostBreakdownResource {
  name: string;
  type: string;
  total_cost: number;
  positions_count: number;
}

export interface CostBreakdownResponse {
  boq_id: string;
  grand_total: number;
  direct_cost: number;
  categories: CostBreakdownCategory[];
  markups: CostBreakdownMarkup[];
  top_resources: CostBreakdownResource[];
}

/* ── Resource Summary types ────────────────────────────────────────── */

export interface ResourceSummaryItem {
  name: string;
  type: string;
  unit: string;
  total_quantity: number;
  avg_unit_rate: number;
  total_cost: number;
  positions_used: number;
}

export interface ResourceTypeSummary {
  count: number;
  total_cost: number;
}

export interface ResourceSummaryResponse {
  total_resources: number;
  by_type: Record<string, ResourceTypeSummary>;
  resources: ResourceSummaryItem[];
}

/* ── Sensitivity Analysis types ───────────────────────────────────────── */

export interface SensitivityItem {
  ordinal: string;
  description: string;
  total: number;
  share_pct: number;
  impact_low: number;
  impact_high: number;
}

export interface SensitivityResponse {
  base_total: number;
  variation_pct: number;
  items: SensitivityItem[];
}

/* ── BOQ Snapshot / Version History types ─────────────────────────────── */

export interface BOQSnapshot {
  id: string;
  boq_id: string;
  name: string;
  position_count?: number;
  grand_total?: number;
  created_at: string;
  created_by: string | null;
}

/* ── AACE Estimate Classification types ──────────────────────────────── */

export interface EstimateClassificationMetrics {
  total_positions: number;
  positions_with_rates: number;
  positions_with_resources: number;
  positions_with_classification: number;
  rate_completeness_pct: number;
  resource_completeness_pct: number;
  classification_completeness_pct: number;
}

export interface EstimateClassificationResponse {
  estimate_class: number;
  class_label: string;
  accuracy_low: string;
  accuracy_high: string;
  definition_level_low: number;
  definition_level_high: number;
  methodology: string;
  metrics: EstimateClassificationMetrics;
}

/* ── Monte Carlo Cost Risk types ─────────────────────────────────────── */

export interface CostRiskHistogramBin {
  bin_start: number;
  bin_end: number;
  count: number;
}

export interface CostRiskDriver {
  ordinal: string;
  description: string;
  contribution_pct: number;
}

export interface CostRiskPercentiles {
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p80: number;
  p90: number;
}

export interface CostRiskResponse {
  iterations: number;
  base_total: number;
  percentiles: CostRiskPercentiles;
  contingency_p80: number;
  contingency_pct: number;
  recommended_budget: number;
  histogram: CostRiskHistogramBin[];
  risk_drivers: CostRiskDriver[];
}

/* ── AI Classification types ─────────────────────────────────────────── */

export interface ClassificationSuggestion {
  standard: string;
  code: string;
  label: string;
  confidence: number;
}

export interface ClassifyResponse {
  suggestions: ClassificationSuggestion[];
}

/* ── AI Rate Suggestion types ────────────────────────────────────────── */

export interface RateMatch {
  code: string;
  description: string;
  rate: number;
  region: string;
  score: number;
}

export interface SuggestRateResponse {
  suggested_rate: number;
  confidence: number;
  source: string;
  matches: RateMatch[];
}

/* ── Anomaly Detection types ─────────────────────────────────────────── */

export interface PricingAnomaly {
  position_id: string;
  field: string;
  current_value: number;
  market_range: { p25: number; median: number; p75: number };
  severity: 'warning' | 'error';
  message: string;
  suggestion: number;
}

export interface AnomalyCheckResponse {
  anomalies: PricingAnomaly[];
  positions_checked: number;
}

/* ── AI Cost Finder types ─────────────────────────────────────────── */

export interface CostItemSearchResult {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  region: string;
  score: number;
  classification: Record<string, string>;
  components: { description: string; unit: string; rate: number }[];
  currency: string;
}

export interface CostItemSearchResponse {
  results: CostItemSearchResult[];
  total_found: number;
  query_embedding_ms: number;
  search_ms: number;
}

/* ── API client ──────────────────────────────────────────────────────── */

export const boqApi = {
  /* BOQ CRUD */
  list: (projectId: string) => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${projectId}`),
  get: (boqId: string) => apiGet<BOQWithPositions>(`/v1/boq/boqs/${boqId}`),
  create: (data: CreateBOQData) => apiPost<BOQ>('/v1/boq/boqs/', data),
  deleteBoq: (boqId: string) => apiDelete(`/v1/boq/boqs/${boqId}`),

  /* Duplicate */
  duplicateBoq: (boqId: string) => apiPost<BOQ>(`/v1/boq/boqs/${boqId}/duplicate/`, {}),
  duplicatePosition: (posId: string) =>
    apiPost<Position>(`/v1/boq/positions/${posId}/duplicate/`, {}),

  /* Section */
  addSection: (boqId: string, data: { ordinal: string; description: string }) =>
    apiPost<Position>(`/v1/boq/boqs/${boqId}/sections/`, { boq_id: boqId, ...data }),

  /* Position CRUD */
  addPosition: (data: CreatePositionData) =>
    apiPost<Position>(`/v1/boq/boqs/${data.boq_id}/positions/`, data),
  updatePosition: (posId: string, data: UpdatePositionData) =>
    apiPatch<Position>(`/v1/boq/positions/${posId}`, data),
  deletePosition: (posId: string) => apiDelete(`/v1/boq/positions/${posId}`),

  /* Position reorder (drag-and-drop) */
  reorderPositions: (boqId: string, positionIds: string[]) =>
    apiPost<{ ok: boolean }>(`/v1/boq/boqs/${boqId}/positions/reorder/`, {
      position_ids: positionIds,
    }),

  /* Markups */
  getMarkups: (boqId: string) => apiGet<MarkupsResponse>(`/v1/boq/boqs/${boqId}/markups/`),
  addMarkup: (boqId: string, data: CreateMarkupData) =>
    apiPost<Markup>(`/v1/boq/boqs/${boqId}/markups/`, data),
  updateMarkup: (boqId: string, markupId: string, data: UpdateMarkupData) =>
    apiPatch<Markup>(`/v1/boq/boqs/${boqId}/markups/${markupId}`, data),
  deleteMarkup: (boqId: string, markupId: string) =>
    apiDelete(`/v1/boq/boqs/${boqId}/markups/${markupId}`),
  applyDefaults: (boqId: string, region: string) =>
    apiPost<Markup[]>(`/v1/boq/boqs/${boqId}/markups/apply-defaults/?region=${encodeURIComponent(region)}`, {}),

  /* Activity */
  getActivity: async (boqId: string): Promise<ActivityResponse> => {
    const raw = await apiGet<{
      items: Array<{
        id: string;
        boq_id: string;
        user_id: string;
        action: string;
        description: string;
        changes?: Record<string, unknown>;
        metadata_?: Record<string, unknown>;
        metadata?: Record<string, unknown>;
        created_at: string;
      }>;
      total: number;
    }>(`/v1/boq/boqs/${boqId}/activity`);
    return {
      activities: (raw.items ?? []).map((item) => ({
        id: item.id,
        boq_id: item.boq_id ?? boqId,
        action: item.action as ActivityAction,
        description: item.description,
        details: item.changes ?? item.metadata_ ?? item.metadata ?? {},
        created_at: item.created_at,
        user_name: undefined,
      })),
      total: raw.total ?? 0,
    };
  },
  getProjectActivity: (projectId: string, limit = 10) =>
    apiGet<{ items: ProjectActivityEntry[]; total: number }>(
      `/v1/boq/projects/${projectId}/activity?limit=${limit}`,
    ),

  /* Cost autocomplete — uses vector semantic search when available */
  autocomplete: (q: string, limit = 8, region?: string) => {
    const params = new URLSearchParams({ q, limit: String(limit), semantic: 'true' });
    if (region) params.set('region', region);
    return apiGet<CostAutocompleteItem[]>(`/v1/costs/autocomplete/?${params.toString()}`);
  },

  /* AI Chat */
  aiChat: (boqId: string, data: AIChatRequest) =>
    apiPost<AIChatResponse>(`/v1/boq/boqs/${boqId}/ai-chat/`, data),

  /* Recalculate rates from resource breakdowns */
  recalculateRates: (boqId: string) =>
    apiPost<{ updated: number; skipped: number; total: number }>(
      `/v1/boq/boqs/${boqId}/recalculate-rates/`,
      {},
    ),

  /* Resource Summary */
  getResourceSummary: (boqId: string) =>
    apiGet<ResourceSummaryResponse>(`/v1/boq/boqs/${boqId}/resource-summary/`),

  /* Cost Breakdown */
  getCostBreakdown: (boqId: string) =>
    apiGet<CostBreakdownResponse>(`/v1/boq/boqs/${boqId}/cost-breakdown/`),

  /* AACE Estimate Classification */
  getClassification: (boqId: string) =>
    apiGet<EstimateClassificationResponse>(`/v1/boq/boqs/${boqId}/classification/`),

  /* Sensitivity Analysis */
  getSensitivity: (boqId: string, variationPct = 10) =>
    apiGet<SensitivityResponse>(
      `/v1/boq/boqs/${boqId}/sensitivity/?variation_pct=${variationPct}`,
    ),

  /* Monte Carlo Cost Risk */
  getCostRisk: (boqId: string, iterations = 1000) =>
    apiGet<CostRiskResponse>(
      `/v1/boq/boqs/${boqId}/cost-risk/?iterations=${iterations}`,
    ),

  /* Statistics — aggregated BOQ metrics */
  getStatistics: (boqId: string) =>
    apiGet<{
      boq_id: string;
      boq_name: string;
      status: string;
      position_count: number;
      section_count: number;
      direct_cost: number;
      grand_total: number;
      avg_unit_rate: number;
      completion_pct: number;
      unit_breakdown: Record<string, number>;
      source_breakdown: Record<string, number>;
      classification_coverage_pct: number;
      created_at: string;
      updated_at: string;
    }>(`/v1/boq/boqs/${boqId}/statistics/`),

  /* Snapshot / Version History */
  getSnapshots: (boqId: string) =>
    apiGet<BOQSnapshot[]>(`/v1/boq/boqs/${boqId}/snapshots/`),
  createSnapshot: (boqId: string, label?: string) =>
    apiPost<BOQSnapshot>(`/v1/boq/boqs/${boqId}/snapshots/`, { name: label ?? '' }),
  restoreSnapshot: (boqId: string, snapshotId: string) =>
    apiPost<{ ok: boolean }>(`/v1/boq/boqs/${boqId}/restore/${snapshotId}`, {}),

  /* Enrich positions with resources from cost database */
  enrichResources: (boqId: string) =>
    apiPost<{ enriched_count: number; total_positions: number }>(
      `/v1/boq/boqs/${boqId}/enrich-resources/`,
      {},
    ),

  /* AI: Classify position */
  classify: (data: { description: string; unit?: string; project_standard?: string }) =>
    apiPost<ClassifyResponse>('/v1/boq/boqs/classify/', data),

  /* AI: Suggest rate */
  suggestRate: (data: { description: string; unit?: string; classification?: Record<string, string>; region?: string }) =>
    apiPost<SuggestRateResponse>('/v1/boq/boqs/suggest-rate/', data),

  /* AI: Check anomalies */
  checkAnomalies: (boqId: string) =>
    apiPost<AnomalyCheckResponse>(`/v1/boq/boqs/${boqId}/check-anomalies/`, {}),

  /* AI: Search cost items (vector similarity) */
  searchCostItems: (data: {
    query: string;
    unit?: string;
    region?: string;
    limit?: number;
    min_score?: number;
  }) => apiPost<CostItemSearchResponse>('/v1/boq/boqs/search-cost-items/', data),

  /* AI: Enhance description via LLM */
  enhanceDescription: (data: {
    description: string;
    unit?: string;
    classification?: Record<string, string>;
    locale?: string;
  }) => apiPost<EnhanceDescriptionResponse>('/v1/boq/boqs/enhance-description/', data),

  /* AI: Suggest prerequisites via LLM */
  suggestPrerequisites: (data: {
    description: string;
    unit?: string;
    classification?: Record<string, string>;
    existing_descriptions?: string[];
    locale?: string;
  }) => apiPost<SuggestPrerequisitesResponse>('/v1/boq/boqs/suggest-prerequisites/', data),

  /* AI: Check scope completeness via LLM */
  checkScope: (boqId: string, data: {
    project_type?: string;
    region?: string;
    currency?: string;
    locale?: string;
  }) => apiPost<CheckScopeResponse>(`/v1/boq/boqs/${boqId}/check-scope/`, data),

  /* AI: Escalate rate via LLM */
  escalateRate: (data: {
    description: string;
    unit: string;
    rate: number;
    currency?: string;
    base_year?: number;
    target_year?: number;
    region?: string;
    locale?: string;
  }) => apiPost<EscalateRateResponse>('/v1/boq/boqs/escalate-rate/', data),

  /* Custom Columns — manage user-defined fields per BOQ */
  listCustomColumns: (boqId: string) =>
    apiGet<CustomColumnDef[]>(`/v1/boq/boqs/${boqId}/columns/`),
  addCustomColumn: (boqId: string, data: CustomColumnDef) =>
    apiPost<CustomColumnDef, CustomColumnDef>(`/v1/boq/boqs/${boqId}/columns/`, data),
  deleteCustomColumn: (boqId: string, columnName: string) =>
    apiDelete<void>(`/v1/boq/boqs/${boqId}/columns/${columnName}`),

  /* Renumber positions using one of several professional schemes.
     - gap10:      01, 01.10, 01.20  (German tender default — leaves room to insert later)
     - gap100:     01, 01.100, 01.200 (very large BOQs)
     - sequential: 01, 01.01, 01.02  (compact, traditional)
     - dotted:     1, 1.1, 1.2      (NRM-style short form) */
  renumberPositions: (
    boqId: string,
    options?: { scheme?: 'gap10' | 'gap100' | 'sequential' | 'dotted'; pad?: boolean },
  ) =>
    apiPost<{ renumbered: number; scheme: string }>(
      `/v1/boq/boqs/${boqId}/renumber/`,
      options ?? {},
    ),
};

/**
 * Custom column definition stored in BOQ `metadata.custom_columns`.
 *
 * `sort_order` is assigned by the backend on insert (= current count) so the
 * client can omit it; on read it is always populated. The grid keeps columns
 * sorted by this value.
 */
export interface CustomColumnDef {
  name: string;
  display_name: string;
  column_type: 'text' | 'number' | 'date' | 'select';
  options?: string[];
  sort_order?: number;
}

/* ── LLM AI feature types ───────────────────────────────────────────── */

export interface EnhanceDescriptionResponse {
  enhanced_description: string;
  specifications: string[];
  standards: string[];
  confidence: number;
  model_used: string;
  tokens_used: number;
}

export interface PrerequisiteItem {
  description: string;
  unit: string;
  typical_rate_eur: number;
  relationship: 'prerequisite' | 'companion' | 'successor';
  reason: string;
}

export interface SuggestPrerequisitesResponse {
  suggestions: PrerequisiteItem[];
  model_used: string;
  tokens_used: number;
}

export interface ScopeMissingItem {
  description: string;
  category: string;
  priority: 'high' | 'medium' | 'low';
  reason: string;
  estimated_rate: number;
  unit: string;
}

export interface CheckScopeResponse {
  completeness_score: number;
  missing_items: ScopeMissingItem[];
  warnings: string[];
  summary: string;
  model_used: string;
  tokens_used: number;
}

export interface EscalationFactors {
  material_inflation: number;
  labor_cost_change: number;
  regional_adjustment: number;
}

export interface EscalateRateResponse {
  original_rate: number;
  escalated_rate: number;
  escalation_percent: number;
  factors: EscalationFactors;
  confidence: 'high' | 'medium' | 'low';
  reasoning: string;
  model_used: string;
  tokens_used: number;
}
