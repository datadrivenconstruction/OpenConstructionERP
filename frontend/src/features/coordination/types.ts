// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * TypeScript types for the Coordination Hub dashboard.
 *
 * Mirror of the Pydantic schemas under
 * ``backend/app/modules/coordination_hub/schemas.py``. Kept hand-written
 * (rather than openapi-generated) because the dashboard is a presentation
 * surface — the wire shape is small, stable, and we want the inline JSDoc
 * for the editor tooltip.
 */

/** Per-category federation rollup. */
export interface FederationStats {
  count: number;
  total_members: number;
  total_elements: number;
}

/** Run-to-run movement for the open clash queue. */
export interface ClashDelta {
  new: number;
  resolved: number;
  reopened: number;
}

/** Clash rollup — open / resolved / ignored + last-run delta. */
export interface ClashStats {
  open_count: number;
  resolved_count: number;
  ignored_count: number;
  delta_since_last_run: ClashDelta;
  /** ISO-8601 — `null` until a run completes for this project. */
  last_run_at: string | null;
}

/** BIM requirement / rule-pack rollup. */
export interface RulePackStats {
  installed_count: number;
  last_check_pass_count: number;
  last_check_fail_count: number;
  last_check_at: string | null;
}

/** Smart-view inventory split by scope. */
export interface SmartViewStats {
  user_count: number;
  project_count: number;
}

/** BCF I/O activity over the last 30 days. */
export interface BCFActivityStats {
  topics_exported_30d: number;
  topics_imported_30d: number;
  last_export_at: string | null;
}

/** Full payload returned by `GET /coordination/projects/:id/dashboard`. */
export interface CoordinationDashboard {
  project_id: string;
  currency: string;
  /** ISO-8601 — server-side timestamp the rollup was assembled at. */
  as_of: string;
  federations: FederationStats;
  clashes: ClashStats;
  rule_packs: RulePackStats;
  smart_views: SmartViewStats;
  bcf_activity: BCFActivityStats;
  open_cost_impact_total: number;
}

/** Canonical 6-trade taxonomy. Matches `schemas.CANONICAL_TRADES`. */
export type CanonicalTrade =
  | 'arch'
  | 'struct'
  | 'mep'
  | 'landscape'
  | 'civil'
  | 'other';

/** One discipline-pair cell in the trade matrix. */
export interface TradeMatrixCell {
  row: CanonicalTrade;
  col: CanonicalTrade;
  count: number;
  open: number;
  resolved: number;
  /**
   * Summed open cost-impact (rework + labour) of this discipline pair,
   * computed by the clash_cost_impact kernel. Decimal-as-string on the
   * wire; `'0'` when the cost module is unavailable or no priced rework.
   */
  cost_impact: string | number;
}

/** Full payload returned by `GET /coordination/projects/:id/trade-matrix`. */
export interface TradeMatrixResponse {
  project_id: string;
  trades: CanonicalTrade[];
  cells: TradeMatrixCell[];
  /** Project display currency for the cost-weighted view (may be ''). */
  currency?: string;
  /** Sum of every cell's `cost_impact` (Decimal-as-string). */
  total_cost_impact?: string | number;
}

/**
 * Interpolation params the client uses to build the localised timeline
 * label. The set of keys present depends on `type`:
 *   • clash_run         → name, total, status, kind ('completed'|'pending')
 *   • federation_created→ name
 *   • rule_pack_installed→ name
 *   • bcf_export        → name, status
 */
export interface CoordinationTimelineParams {
  name?: string | null;
  total?: number | null;
  status?: string | null;
  kind?: string | null;
  [key: string]: string | number | null | undefined;
}

/** One activity-stream entry. */
export interface CoordinationTimelineEvent {
  /** ISO-8601. */
  ts: string;
  /** Discriminant — drives the icon + label template. */
  type:
    | 'clash_run'
    | 'federation_created'
    | 'rule_pack_installed'
    | 'bcf_export'
    | string;
  /** Interpolation params for the client-built, localised label. */
  params: CoordinationTimelineParams;
  /** Pre-rendered English fallback (API exports / logs); the UI builds
   *  its own localised label from `type` + `params` instead. */
  summary: string;
  user_id: string | null;
  /** Deep-link route (e.g. `/clash?run=…`). May be null. */
  target: string | null;
}

/** Full payload returned by `GET /coordination/projects/:id/timeline`. */
export interface CoordinationTimelineResponse {
  project_id: string;
  events: CoordinationTimelineEvent[];
}

// ── Thresholds & alerts ────────────────────────────────────────────────────

/** Severity bucket of an evaluated threshold result. */
export type ThresholdLevel = 'ok' | 'warn' | 'error';

/**
 * The four metrics the coordination hub evaluates thresholds against.
 * Mirrors `models.KNOWN_METRICS` on the backend.
 */
export type CoordinationMetric =
  | 'open_clashes_total'
  | 'high_severity_clashes'
  | 'open_cost_impact_pct_of_budget'
  | 'model_age_days_max'
  | string;

/** One configured threshold + its current evaluated state. */
export interface ThresholdRow {
  metric: CoordinationMetric;
  /** Numbers arrive as JSON strings (Decimal-as-string on the wire). */
  warn_value: string | number;
  error_value: string | number;
  enabled: boolean;
  current_value: string | number;
  level: ThresholdLevel;
  message: string;
}

/** A single in-breach metric — surfaces in the dashboard alert banner. */
export interface ThresholdAlert {
  metric: CoordinationMetric;
  current_value: string | number;
  threshold_value: string | number;
  level: ThresholdLevel;
  message: string;
}

/** Full payload returned by `GET /coordination/projects/:id/thresholds`. */
export interface CoordinationThresholdsResponse {
  project_id: string;
  thresholds: ThresholdRow[];
  alerts: ThresholdAlert[];
}

/** PUT body for editing one threshold. All fields optional, but at least one. */
export interface CoordinationThresholdUpdate {
  warn_value?: number;
  error_value?: number;
  enabled?: boolean;
}
