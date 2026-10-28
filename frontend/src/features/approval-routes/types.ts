// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for Approval Routes (Wave 2, Epic A).
//
// Mirrors backend/app/modules/approval_routes/schemas.py — keep in sync.
// A *Route* is a reusable workflow template (steps with approver role/user
// + decision mode + optional SLA). An *Instance* is a running workflow on
// a specific target (markup, submittal, RFI, …).
//
// IMPORTANT: every field below maps 1:1 to a Pydantic response model on
// the backend. The instance row is flat — it carries `step_states` (one
// decision row per approver per step), NOT an expanded per-step ladder.
// The UI joins `step_states` against the route's `steps` (fetched via
// getRoute) to render the ladder, and derives the active step from
// `current_step_ordinal` (1-based).

/** Decision mode for a step — how many approvers must approve before it
 *  closes. ``all`` = every distinct approver who acted (role steps degrade
 *  to "any" — see backend note), ``any`` = first one wins, ``majority`` =
 *  > 50 % of approvers who acted. */
export type RouteStepMode = 'all' | 'any' | 'majority';

/** Lifecycle status of a running instance. Mirrors
 *  models.INSTANCE_STATUSES — there is no separate "in_progress" state;
 *  ``pending`` IS the active state. */
export type InstanceStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

/** Per-step decision recorded in a StepState row. Mirrors
 *  models.STEP_DECISIONS. */
export type StepDecisionState = 'pending' | 'approved' | 'rejected';

/** Outcome a user submits via the decide endpoint — exactly what the
 *  backend DecisionSubmit.decision Literal accepts. */
export type StepDecision = 'approved' | 'rejected';

/** A template step — pinned to a role OR a specific user (mutually
 *  exclusive). One of the two must be set. ``ordinal`` is 1-based and
 *  dense (1, 2, 3, …). */
export interface RouteStep {
  id: string;
  route_id: string;
  ordinal: number;
  approver_role: string | null;
  approver_user_id: string | null;
  mode: RouteStepMode;
  /** Eligible-approver population for a role-based all / majority step. null
   *  when the author did not declare a quorum. */
  required_approver_count: number | null;
  sla_hours: number | null;
}

/** A reusable approval-route template scoped to a project (or global). */
export interface ApprovalRoute {
  id: string;
  project_id: string | null;
  target_kind: string;
  name: string;
  is_active: boolean;
  steps: RouteStep[];
  created_by: string | null;
  /** Set only on platform-seeded presets (tenant-wide, read-only ISO 19650
   *  review flows); null for every user-created route. The UI flags a preset
   *  from this and the API rejects edits / deletes of a route that carries it. */
  system_key: string | null;
  created_at: string;
  updated_at: string;
}

/** Payload shape when creating/updating a step inside a route. ``ordinal``
 *  is 1-based and required on create (the backend enforces dense ordinals). */
export interface RouteStepPayload {
  ordinal: number;
  approver_role?: string | null;
  approver_user_id?: string | null;
  mode: RouteStepMode;
  sla_hours?: number | null;
}

export interface ApprovalRouteCreatePayload {
  project_id?: string | null;
  target_kind: string;
  name: string;
  is_active?: boolean;
  steps: RouteStepPayload[];
}

/** Patch payload. ``steps`` is optional — when supplied the whole step
 *  list is replaced server-side (delete + reinsert). target_kind and
 *  project_id are immutable on the backend and are not part of the patch. */
export interface ApprovalRouteUpdatePayload {
  name?: string;
  is_active?: boolean;
  steps?: RouteStepPayload[];
}

/** One per-approver decision row inside a running instance. Mirrors
 *  StepStateResponse. ``decision`` is one of pending/approved/rejected. */
export interface StepState {
  id: string;
  instance_id: string;
  step_id: string;
  approver_user_id: string | null;
  decision: StepDecisionState;
  comment: string | null;
  decided_at: string | null;
  created_at: string;
}

/** A running approval workflow on a specific target. Flat shape — the
 *  ladder is reconstructed by the UI from the route's steps + these
 *  step_states. */
export interface ApprovalInstance {
  id: string;
  route_id: string;
  target_kind: string;
  target_id: string;
  current_step_ordinal: number;
  status: InstanceStatus;
  started_at: string;
  completed_at: string | null;
  started_by: string | null;
  /** Who must act on the current step right now (the "ball in court").
   *  null means the step's own approver / role (or its resolved
   *  out-of-office delegate) is responsible; a value is a one-tap
   *  reassignment override pinned via the reassign endpoint. */
  current_assignee_user_id?: string | null;
  created_at: string;
  updated_at: string;
  step_states: StepState[];
}

export interface InstanceCreatePayload {
  route_id: string;
  target_kind: string;
  target_id: string;
}

export interface InstanceDecidePayload {
  step_id: string;
  decision: StepDecision;
  comment?: string | null;
}

export interface InstanceCancelPayload {
  reason?: string | null;
}

/** One-tap reassignment of an instance's current step to another user.
 *  Mirrors the backend ReassignInstance schema. */
export interface InstanceReassignPayload {
  to_user_id: string;
  reason?: string | null;
}

/** Metadata payload from GET /approval-routes/meta — single source of
 *  truth for the validated whitelists so the UI never drifts from the DB. */
export interface ApprovalRoutesMeta {
  target_kinds: string[];
  step_modes: RouteStepMode[];
  instance_statuses: InstanceStatus[];
}

/* ── Delegations (out-of-office) ──────────────────────────────────── */

/** A read-side out-of-office hand-off row. Mirrors the backend
 *  DelegationResponse. The ``delegator`` is the user who handed their
 *  approvals away; the ``delegate`` is the stand-in who covers them. An
 *  optional ``starts_at``/``ends_at`` window scopes when it is live; a
 *  null ``project_id`` is a blanket hand-off across every project. */
export interface ApprovalDelegation {
  id: string;
  delegator_user_id: string;
  delegate_user_id: string;
  project_id: string | null;
  starts_at: string | null;
  ends_at: string | null;
  is_active: boolean;
  reason: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** Create payload for an out-of-office hand-off. The delegator is always
 *  the authenticated caller server-side — never sent in the body. Mirrors
 *  the backend DelegationCreate. Datetimes are ISO-8601 strings. */
export interface DelegationCreatePayload {
  delegate_user_id: string;
  project_id?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  reason?: string | null;
}

/** Which side of a hand-off to list: ``mine`` = hand-offs the caller
 *  created (approvals they delegated away); ``covering`` = hand-offs
 *  naming the caller as the stand-in. */
export type DelegationRole = 'mine' | 'covering';

/** Escalation standing of one instance's current step (#17). Mirrors the
 *  backend EscalationOut. ``has_sla`` is false when there is no live SLA
 *  clock; ``severity`` is the overrun band, ``next_target`` the approver to
 *  escalate to now (or null), and ``level`` the 1-based escalation level. */
export type EscalationSeverity = 'on_time' | 'late' | 'breached' | 'critical';

export interface Escalation {
  instance_id: string;
  target_kind: string;
  current_step_ordinal: number;
  has_sla: boolean;
  severity: EscalationSeverity;
  hours_overdue: number;
  should_escalate: boolean;
  next_target: string | null;
  level: number;
  reason: string;
  chain_length: number;
  current_holder: string | null;
}

/* ── Dry-run simulation (inc3a/inc3c) ─────────────────────────────── */

/** One step's hypothetical decision tally for a what-if dry run. Mirrors the
 *  backend SimulateDecision. ``distinct_approvers`` defaults to ``approvals``
 *  server-side when omitted. */
export interface SimulateDecision {
  ordinal: number;
  approvals: number;
  rejections: number;
  distinct_approvers?: number | null;
}

/** Optional body for POST /routes/{id}/simulate. An empty body runs only the
 *  happy path; supplying ``decisions`` adds a second what-if walk. */
export interface SimulateRequest {
  decisions: SimulateDecision[];
}

/** Per-step analysis of a route template in a dry run. Mirrors the backend
 *  SimulatedStep. */
export interface SimulatedStep {
  ordinal: number;
  mode: string;
  approver_role: string | null;
  approver_user_id: string | null;
  quorum_required: number | null;
  min_approvals_to_clear: number;
  needs_multiple_approvers: boolean;
  note: string;
}

/** Where one dry-run walk (happy path or scenario) ends up. ``outcome`` is
 *  completed (reaches approved), rejected (a rejection short-circuits) or
 *  stuck (a step never gathers enough approvals). */
export type SimulationOutcomeKind = 'completed' | 'rejected' | 'stuck';

export interface SimulationOutcome {
  outcome: SimulationOutcomeKind;
  stopped_at_ordinal: number | null;
  trace: string[];
}

/** Result of dry-running a route template. Mirrors the backend
 *  RouteSimulationResponse. */
export interface RouteSimulation {
  route_id: string;
  target_kind: string;
  step_count: number;
  steps: SimulatedStep[];
  happy_path: SimulationOutcome;
  scenario: SimulationOutcome | null;
  warnings: string[];
}

/* ── Approval-cycle analytics (item #11) ──────────────────────────── */

/** Project-level KPI headline. Mirrors the backend AnalyticsKpis. */
export interface ApprovalAnalyticsKpis {
  total_instances: number;
  pending: number;
  approved: number;
  rejected: number;
  cancelled: number;
  /** approved / (approved + rejected); null when there is no terminal decision. */
  approval_rate: number | null;
  avg_cycle_days: number | null;
  median_cycle_days: number | null;
  breached_steps_total: number;
  instances_with_breach: number;
  /** Pending instances whose current step is overdue right now. */
  open_overdue_now: number;
}

/** Held-time stats for the decided steps attributed to one role. Mirrors
 *  AnalyticsRoleStat. ``role`` is null for user-pinned steps. */
export interface ApprovalAnalyticsRoleStat {
  role: string | null;
  decided_count: number;
  avg_hours: number;
  median_hours: number;
  max_hours: number;
  breach_count: number;
  breach_rate: number;
}

/** Held-time stats for one route step (route + ordinal). Mirrors
 *  AnalyticsStepStat. */
export interface ApprovalAnalyticsStepStat {
  route_id: string;
  route_name: string;
  ordinal: number;
  approver_role: string | null;
  decided_count: number;
  avg_hours: number;
  median_hours: number;
  breach_count: number;
  breach_rate: number;
  sla_hours: number | null;
}

/** A ranked slow point - a role or a specific route step. Mirrors
 *  AnalyticsBottleneck. ``ref`` is the role name or ``{route_id}:{ordinal}``. */
export interface ApprovalAnalyticsBottleneck {
  kind: 'role' | 'step';
  label: string;
  ref: string;
  avg_hours: number;
  median_hours: number;
  breach_rate: number;
  sample_size: number;
}

/** Full project-scoped approval-cycle analytics. Mirrors the backend
 *  ApprovalAnalyticsResponse. */
export interface ApprovalAnalytics {
  project_id: string;
  generated_at: string;
  range_days: number | null;
  started_after: string | null;
  started_before: string | null;
  /** Instances actually computed (post-cap). */
  sample_size: number;
  /** True when the compute cap was hit; status counts stay exact regardless. */
  truncated: boolean;
  kpis: ApprovalAnalyticsKpis;
  by_role: ApprovalAnalyticsRoleStat[];
  by_step: ApprovalAnalyticsStepStat[];
  bottlenecks: ApprovalAnalyticsBottleneck[];
}
