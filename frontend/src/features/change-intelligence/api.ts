// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for the change-intelligence layer. These endpoints turn the many
// change-adjacent modules (change orders, variations, MoC, correspondence,
// approvals) into one read surface that answers three questions a project team
// keeps asking: what to act on first, who owes the next action and by when, and
// what the approved changes have committed in cost and schedule. Money is
// carried on the wire as a string (the Decimal rendered losslessly), so it is
// passed straight to MoneyDisplay and never coerced with toFixed here.

import { apiGet, apiPost, apiPatch, apiPut } from '@/shared/lib/api';

const CI_BASE = '/v1/change-intelligence';
const CR_BASE = '/v1/cost-recovery';

// --- Action coordination ("what to act on first") --------------------------

export type Urgency = 'overdue' | 'due_soon' | 'upcoming' | 'no_date';

export interface CoordinationStep {
  ref_id: string;
  kind: string;
  title: string;
  ball_in_court: string;
  urgency: Urgency;
  days_to_due: number | null;
  recommended_action: string;
  reason: string;
  rank_score: number;
}

export interface CoordinationPlan {
  project_id: string;
  generated_at: string;
  total: number;
  overdue_count: number;
  due_soon_count: number;
  steps: CoordinationStep[];
}

export function getCoordinationPlan(projectId: string): Promise<CoordinationPlan> {
  return apiGet<CoordinationPlan>(`${CI_BASE}/projects/${projectId}/coordination`);
}

// --- Cycle time ("waiting on whom") ----------------------------------------

export interface PartyLoad {
  party: string;
  open_count: number;
  overdue_count: number;
  oldest_age_days: number;
  total_age_days: number;
  avg_age_days: number;
}

export interface ItemAging {
  id: string;
  kind: string;
  code: string;
  title: string;
  status: string;
  party: string;
  age_days: number;
  stale_days: number | null;
  response_due_date: string | null;
  overdue: boolean;
  days_to_due: number | null;
}

export interface CycleTimeBoard {
  project_id: string;
  as_of: string;
  total_open: number;
  total_overdue: number;
  unassigned_open: number;
  parties: PartyLoad[];
  items: ItemAging[];
}

export function getCycleTimeBoard(projectId: string): Promise<CycleTimeBoard> {
  return apiGet<CycleTimeBoard>(`${CI_BASE}/projects/${projectId}/cycle-time`);
}

// --- Approved-change impact (committed cost and schedule) ------------------

export interface KindImpact {
  kind: string;
  count: number;
  total_cost: string;
  total_days: number;
}

export interface CurrencyImpact {
  currency: string;
  total_cost: string;
  count: number;
}

export interface ImpactProjection {
  project_id: string;
  approved_count: number;
  total_schedule_delta_days: number;
  primary_currency: string;
  primary_currency_cost: string;
  by_kind: KindImpact[];
  by_currency: CurrencyImpact[];
}

export function getImpactProjection(projectId: string): Promise<ImpactProjection> {
  return apiGet<ImpactProjection>(`${CI_BASE}/projects/${projectId}/impact`);
}

// --- Correspondence digest ("who owes the next reply") ---------------------

export type Awaiting = 'us' | 'them' | 'none';

export interface ThreadDigest {
  thread_key: string;
  subject: string;
  message_count: number;
  participants: string[];
  first_at: string | null;
  last_at: string | null;
  last_direction: string;
  last_sender: string;
  awaiting: Awaiting;
  is_open: boolean;
}

export interface CommsDigest {
  project_id: string;
  generated_at: string;
  thread_count: number;
  open_count: number;
  awaiting_us_count: number;
  threads: ThreadDigest[];
}

export function getCommsDigest(projectId: string): Promise<CommsDigest> {
  return apiGet<CommsDigest>(`${CI_BASE}/projects/${projectId}/comms-digest`);
}

// --- Change-request clarifier co-pilot -------------------------------------

export interface ClarificationGap {
  field: string;
  question: string;
  severity: string;
}

export interface ClauseSuggestion {
  standard: string;
  clause_ref: string;
  rationale: string;
}

export interface ClarifiedRequest {
  title: string;
  normalized_summary: string;
  detected_classification: string;
  missing: ClarificationGap[];
  clause_suggestions: ClauseSuggestion[];
  suggested_route: string;
  completeness: number;
}

export function clarifyChangeNote(
  note: string,
  contractStandard = '',
): Promise<ClarifiedRequest> {
  return apiPost<ClarifiedRequest>(`${CI_BASE}/clarify`, {
    note,
    contract_standard: contractStandard,
  });
}

// --- Cost recovery / liability ---------------------------------------------

export interface BackCharge {
  id: string;
  project_id: string;
  source_ref: string;
  responsible_party: string;
  description: string;
  basis: string;
  gross_amount: string;
  chargeable_pct: string;
  chargeable_amount: string;
  currency: string;
  status: string;
  recovered_amount: string;
  outstanding: string;
  is_open: boolean;
  agreed_at: string | null;
  recovered_at: string | null;
}

export interface PartyRecovery {
  party: string;
  currency: string;
  item_count: number;
  open_count: number;
  gross_total: string;
  chargeable_total: string;
  recovered_total: string;
  outstanding_total: string;
}

export interface CurrencyRecovery {
  currency: string;
  item_count: number;
  chargeable_total: string;
  recovered_total: string;
  outstanding_total: string;
}

export interface RecoveryLedger {
  project_id: string;
  item_count: number;
  open_count: number;
  primary_currency: string;
  primary_outstanding: string;
  by_party: PartyRecovery[];
  by_currency: CurrencyRecovery[];
}

export function getRecoveryLedger(projectId: string): Promise<RecoveryLedger> {
  return apiGet<RecoveryLedger>(`${CR_BASE}/projects/${projectId}/recovery-ledger`);
}

export function listBackCharges(projectId: string): Promise<BackCharge[]> {
  return apiGet<BackCharge[]>(`${CR_BASE}/projects/${projectId}/back-charges`);
}

// Request body to record a new back-charge. Money fields (gross_amount,
// chargeable_pct) are carried as strings so the Decimal round-trips losslessly;
// they are never coerced to a number here. chargeable_pct is a FRACTION in
// [0, 1] (0.6 means 60%), and status is one of the back-charge commercial
// states (proposed / agreed / disputed / recovered / waived).
export interface BackChargeCreateBody {
  source_ref?: string;
  responsible_party?: string;
  description?: string;
  basis?: string;
  gross_amount?: string;
  chargeable_pct?: string;
  currency?: string;
  status?: string;
}

// Partial update of a back-charge; only the supplied fields change. Money is a
// string for the same lossless-Decimal reason as the create body.
export interface BackChargeUpdateBody {
  responsible_party?: string;
  description?: string;
  basis?: string;
  gross_amount?: string;
  chargeable_pct?: string;
  status?: string;
  recovered_amount?: string;
}

export function createBackCharge(
  projectId: string,
  body: BackChargeCreateBody,
): Promise<BackCharge> {
  return apiPost<BackCharge, BackChargeCreateBody>(
    `${CR_BASE}/projects/${projectId}/back-charges`,
    body,
  );
}

export function updateBackCharge(
  projectId: string,
  backChargeId: string,
  body: BackChargeUpdateBody,
): Promise<BackCharge> {
  return apiPatch<BackCharge, BackChargeUpdateBody>(
    `${CR_BASE}/projects/${projectId}/back-charges/${backChargeId}`,
    body,
  );
}

// --- Recovery performance (recovered vs entitled, by traceability) ----------
// How much of what the project was entitled to recover it actually recovered,
// split by how traceable the responsible owner was (high vs low). Money is a
// string handed to MoneyDisplay untouched; the rate is a string fraction in
// [0, 1] (or null when nothing was chargeable - an undefined ratio, not 0).

export interface CohortRecovery {
  cohort: string;
  currency: string;
  item_count: number;
  chargeable_total: string;
  recovered_total: string;
  outstanding_total: string;
  absorbed_total: string;
  rate: string | null;
}

export interface CurrencyRecoveryPerf {
  currency: string;
  item_count: number;
  chargeable_total: string;
  recovered_total: string;
  outstanding_total: string;
  absorbed_total: string;
  rate: string | null;
  by_cohort: CohortRecovery[];
  by_band: CohortRecovery[];
}

export interface RecoveryPerformance {
  project_id: string | null;
  item_count: number;
  primary_currency: string;
  primary_rate: string | null;
  by_currency: CurrencyRecoveryPerf[];
}

export function getRecoveryPerformance(projectId: string): Promise<RecoveryPerformance> {
  return apiGet<RecoveryPerformance>(`${CR_BASE}/projects/${projectId}/recovery-performance`);
}

// Recovery performance across every project the caller may access (project_id is
// null on the result). Same currency-scoped shape as the per-project variant.
export function getPortfolioRecoveryPerformance(): Promise<RecoveryPerformance> {
  return apiGet<RecoveryPerformance>(`${CR_BASE}/recovery-performance`);
}

// --- Apportionment (one back-charge split across responsible parties) --------
// The chargeable amount of a single back-charge divided across the parties that
// share responsibility. Each share amount is a string for MoneyDisplay; the
// amounts reconcile to the chargeable amount exactly.

export interface ApportionedShare {
  id: string;
  back_charge_id: string;
  project_id: string;
  party: string;
  basis: string;
  share_pct: string;
  share_amount: string;
  currency: string;
}

export interface BackChargeApportionment {
  back_charge_id: string;
  project_id: string;
  currency: string;
  chargeable_amount: string;
  share_total: string;
  is_apportioned: boolean;
  shares: ApportionedShare[];
}

export function getBackChargeApportionment(
  projectId: string,
  backChargeId: string,
): Promise<BackChargeApportionment> {
  return apiGet<BackChargeApportionment>(
    `${CR_BASE}/projects/${projectId}/back-charges/${backChargeId}/apportionment`,
  );
}

// One party's requested share when apportioning a back-charge. share_pct is a
// FRACTION in [0, 1] (0.6 means 60%) carried as a string; the shares for one
// back-charge must sum to 1.0 or the backend 422s. Re-running replaces any
// previous apportionment.
export interface ApportionmentShareInput {
  party: string;
  share_pct: string;
  basis?: string;
}

export function apportionBackCharge(
  projectId: string,
  backChargeId: string,
  shares: ApportionmentShareInput[],
): Promise<BackChargeApportionment> {
  return apiPut<BackChargeApportionment, { shares: ApportionmentShareInput[] }>(
    `${CR_BASE}/projects/${projectId}/back-charges/${backChargeId}/apportionment`,
    { shares },
  );
}

// --- Dispute-exposure radar ("which open change goes to a dispute first") ---
// A composition over provability, overdue age, SLA, ownership and money at
// risk. Money is carried on the wire as a string and handed to MoneyDisplay
// untouched; the exposure score is a pure 0-100 with no currency.

export type ExposureBand = 'low' | 'elevated' | 'high';

export interface RiskFactor {
  name: string;
  weight: number;
  fraction: number;
  weighted: number;
  is_driver: boolean;
}

export interface DisputeRiskItem {
  change_id: string;
  change_ref: string;
  kind: string;
  title: string;
  exposure_score: number;
  band: ExposureBand;
  dominant_driver: string;
  recommended_cure: string;
  intrinsic_exposure: number;
  money_multiplier: number;
  money_basis: string;
  currency: string;
  factors: RiskFactor[];
}

export interface CurrencyExposure {
  currency: string;
  item_count: number;
  money_basis_total: string;
  exposure_weighted_amount: string;
}

export interface DisputeExposureSummary {
  item_count: number;
  band_counts: Record<string, number>;
  by_currency: CurrencyExposure[];
  top_driver_counts: Record<string, number>;
}

export interface DisputeRiskBoard {
  project_id: string;
  generated_at: string;
  items: DisputeRiskItem[];
  summary: DisputeExposureSummary;
}

export function getDisputeRiskBoard(projectId: string): Promise<DisputeRiskBoard> {
  return apiGet<DisputeRiskBoard>(`${CI_BASE}/projects/${projectId}/dispute-risk`);
}

// --- Decision-time impact preview ------------------------------------------
// What approving one candidate change adds on top of the committed baseline.
// Every money / day figure is a string so the signed Decimal round-trips and
// currencies are never blended.

export interface DecisionImpactRow {
  kind: string;
  currency: string;
  current_committed_cost: string;
  candidate_cost_delta: string;
  resulting_cost: string;
  current_committed_days: string;
  candidate_days_delta: string;
  resulting_days: string;
}

export interface CurrencyTotal {
  currency: string;
  current_committed_cost: string;
  candidate_cost_delta: string;
  resulting_cost: string;
  current_committed_days: string;
  candidate_days_delta: string;
  resulting_days: string;
}

export interface DecisionImpact {
  project_id: string;
  candidate_change_id: string;
  candidate_kind: string;
  candidate_currency: string;
  rows: DecisionImpactRow[];
  totals_by_currency: CurrencyTotal[];
}

export function getDecisionImpact(
  projectId: string,
  candidateChangeId: string,
): Promise<DecisionImpact> {
  return apiGet<DecisionImpact>(
    `${CI_BASE}/decision-impact?project_id=${encodeURIComponent(projectId)}&candidate_change_id=${encodeURIComponent(candidateChangeId)}`,
  );
}

// --- Proactive change watch ------------------------------------------------
// Which open changes are quietly drifting toward trouble (stalled / incomplete
// / lost), worst-first, with a per-class count.

export type WatchClass = 'lost' | 'stalled' | 'incomplete' | 'ok';

export interface WatchResult {
  change_id: string;
  kind: string;
  classification: WatchClass;
  reasons: string[];
  idle_days: number;
  overdue_days: number;
}

export interface ChangeWatch {
  project_id: string;
  generated_at: string;
  item_count: number;
  counts: Record<string, number>;
  items: WatchResult[];
}

export function getChangeWatch(projectId: string): Promise<ChangeWatch> {
  return apiGet<ChangeWatch>(`${CI_BASE}/projects/${projectId}/change-watch`);
}

// --- Multi-source intake normalizer ----------------------------------------
// Read a foreign change-request record (a tracker-spreadsheet row, an email
// intake form) with a mapping profile and preview the canonical draft it maps
// to. Cost is money carried as a string for MoneyDisplay; the schedule day count
// is an exact Decimal string. Nothing is persisted - this is a preview.

export interface IntakeProfile {
  profile_name: string;
  required_fields: string[];
  canonical_fields: string[];
  field_alias_count: number;
  unit_synonym_count: number;
  value_synonym_count: number;
}

export interface IntakeProfiles {
  project_id: string;
  profiles: IntakeProfile[];
}

export interface IntakeDraft {
  title: string | null;
  description: string | null;
  cost_impact: string | null;
  currency: string | null;
  schedule_impact_days: string | null;
  requested_by: string | null;
  source_ref: string | null;
}

export interface IntakePreview {
  project_id: string;
  profile_name: string;
  draft: IntakeDraft;
  unmapped_fields: string[];
  missing_required: string[];
  warnings: string[];
  completeness: number;
}

export function getIntakeProfiles(projectId: string): Promise<IntakeProfiles> {
  return apiGet<IntakeProfiles>(`${CI_BASE}/projects/${projectId}/intake/profiles`);
}

export function previewIntake(
  projectId: string,
  profileName: string,
  record: Record<string, unknown>,
): Promise<IntakePreview> {
  return apiPost<IntakePreview>(`${CI_BASE}/projects/${projectId}/intake/preview`, {
    profile_name: profileName,
    record,
  });
}

// --- Predictive delay / overrun risk ---------------------------------------
// Rank a project's open changes by how likely they are to overrun their
// response window, with the ranked factor contributions behind each score. The
// risk and factor values are pure 0-1 ratios (no money), safe to render direct.

export type DelayBand = 'low' | 'elevated' | 'high';

export interface DelayRiskFactor {
  name: string;
  value: number;
  contribution: number;
}

export interface DelayRiskItem {
  change_id: string;
  change_ref: string;
  kind: string;
  title: string;
  party: string;
  risk: number;
  band: DelayBand;
  age_days: number;
  overdue: boolean;
  days_to_due: number | null;
  top_factors: DelayRiskFactor[];
}

export interface DelayRiskBoard {
  project_id: string;
  generated_at: string;
  item_count: number;
  band_counts: Record<string, number>;
  items: DelayRiskItem[];
}

export function getDelayRiskBoard(projectId: string): Promise<DelayRiskBoard> {
  return apiGet<DelayRiskBoard>(`${CI_BASE}/projects/${projectId}/delay-risk`);
}

// --- Pre-construction scope ambiguity --------------------------------------
// Grade a project's BOQ lines for how vague their scope is, worst-first, so the
// soft spots that breed a change order later surface while they are still cheap
// to firm up. The score is a pure 0-100 with no money; bands are high / elevated
// / low and each line names the reasons that drove its grade.

export type ScopeBand = 'high' | 'elevated' | 'low';

export interface ScopeAmbiguityLine {
  line_id: string;
  score: number;
  band: ScopeBand;
  reasons: string[];
  labels: string[];
}

export interface ScopeAmbiguityReport {
  project_id: string;
  boq_id: string | null;
  line_count: number;
  ambiguity_index: number;
  counts_by_band: Record<string, number>;
  top_reasons: string[];
  lines: ScopeAmbiguityLine[];
}

export function getScopeAmbiguity(
  projectId: string,
  boqId?: string | null,
): Promise<ScopeAmbiguityReport> {
  const qs = boqId ? `?boq_id=${encodeURIComponent(boqId)}` : '';
  return apiGet<ScopeAmbiguityReport>(
    `${CI_BASE}/projects/${projectId}/scope-ambiguity${qs}`,
  );
}

// --- Contractual notice and time-bar register ------------------------------
// Every open notice / response clock on the project's changes, variations and
// extension-of-time claims, counted down against the notice period for the
// resolved contract standard (FIDIC / NEC / JCT / AIA / ConsensusDocs, or a
// standard-neutral fallback). Worst-first. days_remaining is a signed pure day
// count (negative once overdue), never money, so it is rendered directly. A
// required notice with no proof on file, or a lapsed bar, is flagged
// entitlement_at_risk so the entitlement is not quietly lost.

export type NoticeStatus = 'met' | 'overdue' | 'due_soon' | 'upcoming' | 'unknown';

export interface NoticeClock {
  source_kind: string;
  source_id: string;
  source_ref: string;
  title: string;
  standard: string;
  notice_type: string;
  clause_ref: string;
  trigger_date: string | null;
  period_days: number | null;
  deadline: string | null;
  days_remaining: number | null;
  status: NoticeStatus;
  requires_notice: boolean;
  proof_on_file: boolean;
  satisfied_at: string | null;
  served_late: boolean;
  entitlement_at_risk: boolean;
  is_open: boolean;
}

export interface NoticeRegisterSummary {
  total: number;
  open_total: number;
  counts_by_status: Record<string, number>;
  at_risk: number;
  proof_missing: number;
  overdue: number;
  due_soon: number;
}

export interface NoticeRegister {
  project_id: string;
  contract_standard: string;
  generated_at: string;
  due_soon_days: number;
  clocks: NoticeClock[];
  summary: NoticeRegisterSummary;
}

// standard is an optional override that wins over the project's own contract
// standard; dueSoonDays sets the amber window (the backend clamps it to 1..90).
// Both are omitted from the query string when not supplied, so the register
// resolves the standard and window on its own.
export function getNoticeRegister(
  projectId: string,
  opts?: { standard?: string; dueSoonDays?: number },
): Promise<NoticeRegister> {
  const params = new URLSearchParams();
  if (opts?.standard) params.set('standard', opts.standard);
  if (opts?.dueSoonDays != null) params.set('due_soon_days', String(opts.dueSoonDays));
  const qs = params.toString();
  return apiGet<NoticeRegister>(
    `${CI_BASE}/projects/${projectId}/notice-register${qs ? `?${qs}` : ''}`,
  );
}

// --- Commitment register ("who owes the next action") ----------------------
// The consolidated, owner-ranked, overdue-first list of open commitments a
// project carries: meeting action items, risk mitigation actions, open change
// orders, and RFIs / submittals awaiting a response. days_overdue and age_days
// are pure day counts (not money), safe to render directly; by_source counts the
// register by its origin (meeting_action / risk_action / change_order / rfi /
// submittal).

export interface Commitment {
  source: string;
  ref_id: string;
  code: string;
  title: string;
  owner: string;
  due_date: string | null;
  overdue: boolean;
  days_overdue: number;
  age_days: number | null;
}

export interface OwnerLoad {
  owner: string;
  open_count: number;
  overdue_count: number;
}

export interface CommitmentRegister {
  project_id: string;
  generated_at: string;
  total_open: number;
  overdue_count: number;
  by_owner: OwnerLoad[];
  by_source: Record<string, number>;
  items: Commitment[];
}

export function getCommitmentRegister(projectId: string): Promise<CommitmentRegister> {
  return apiGet<CommitmentRegister>(`${CI_BASE}/projects/${projectId}/commitments`);
}

// --- Change-driver Pareto analytics ----------------------------------------
// A cost-ranked Pareto of the project's change pressure by originating cause and
// by responsible party, each with a running cumulative percentage, plus a
// per-currency split and a month-over-month trend. cost is money carried as a
// string for MoneyDisplay; cost_pct and cumulative_pct are pure 0-100
// percentages (a ratio, not money), safe to render directly.

export interface ParetoRow {
  key: string;
  count: number;
  cost: string;
  cost_pct: number;
  cumulative_pct: number;
}

export interface DriverCurrency {
  currency: string;
  count: number;
  cost: string;
}

export interface DriverTrendPoint {
  month: string;
  count: number;
  cost: string;
}

export interface ChangeDriverAnalytics {
  project_id: string;
  total_count: number;
  total_cost: string;
  primary_currency: string;
  by_cause: ParetoRow[];
  by_party: ParetoRow[];
  by_currency: DriverCurrency[];
  trend: DriverTrendPoint[];
}

export function getChangeDrivers(projectId: string): Promise<ChangeDriverAnalytics> {
  return apiGet<ChangeDriverAnalytics>(`${CI_BASE}/projects/${projectId}/change-drivers`);
}

// --- Change run-rate / cumulative change curve -----------------------------
// The cumulative approved-plus-pending change value month by month against the
// original contract, the intake rate (changes per month) and a simple linear
// burn-rate forecast of the change percentage at completion. Every money and
// percentage figure is a string (the signed Decimal round-tripped losslessly);
// the percentages are already 0-100 (value / contract * 100), never fractions,
// and change_pct / current_change_pct / final_change_pct are null when there is
// no usable contract value to divide by. intake_rate_per_month is a plain rate.

export interface RunRatePoint {
  month: string;
  approved_value: string;
  pending_value: string;
  cumulative_value: string;
  change_pct: string | null;
}

export interface RunRateForecast {
  method: string;
  elapsed_days: number;
  total_days: number;
  rate_per_day: string;
  final_change_value: string;
  final_change_pct: string | null;
  at_date: string;
}

export interface ChangeRunRate {
  project_id: string;
  original_contract_value: string | null;
  currency: string;
  change_count: number;
  approved_value: string;
  pending_value: string;
  total_change_value: string;
  current_change_pct: string | null;
  intake_rate_per_month: number;
  points: RunRatePoint[];
  forecast: RunRateForecast | null;
}

export function getChangeRunRate(projectId: string): Promise<ChangeRunRate> {
  return apiGet<ChangeRunRate>(`${CI_BASE}/projects/${projectId}/run-rate`);
}
