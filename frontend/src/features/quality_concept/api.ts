// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the project quality concept: standards basis, certification
// targets, proofs and their evidence, commissioning stages, acceptance units,
// evidence preservation surveys and expert reports.
//
// Backend module: backend/app/modules/quality_concept/router.py, mounted at
// /api/v1/quality-concept/. Every route lives under /projects/{project_id}/.
//
// Responses are the stored row plus a few computed fields (see the `_*_out`
// helpers in the router). Points and quantities travel as decimal strings in
// both directions: the server refuses a JSON float. Calendar days are ISO
// `YYYY-MM-DD` strings.
//
// Errors arrive as `detail = {code, message_key, message, violations?, info?}`.

import { API_BASE, ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type CatalogueSource = 'shipped' | 'tenant' | 'pack';

/** A catalogue label: a message key for shipped items, texts per locale for tenant ones. */
export interface QcLabel {
  key: string | null;
  text: Record<string, string> | null;
}

/**
 * What the server lets this reader do with one record: a flag per action, and
 * where the flag is false the error code the route would answer.
 */
export interface Capable {
  can?: Record<string, boolean> | null;
  can_reason?: Record<string, string> | null;
}

/** A record of a neighbour module, named so the screen can say which one it is. */
export interface RecordRef {
  kind: string;
  id: string;
  label: string | null;
  status: string | null;
}

export interface HoldGateRef extends RecordRef {
  gate_number: string | number | null;
  required_party_role: string;
}

export interface Finding {
  code: string;
  severity: 'error' | 'warning' | string;
  ref: string;
  params: Record<string, unknown>;
  /** The name of the record `ref` is the id of; null when `ref` already reads as a code. */
  label?: string | null;
  link_label?: string | null;
}

export type ConceptState = 'draft' | 'in_review' | 'approved' | 'binding' | 'revising';
export type CertificationState =
  | 'planned'
  | 'registered'
  | 'design_assessed'
  | 'post_construction_assessed'
  | 'certified'
  | 'level_missed'
  | 'abandoned';
export type CreditState = 'targeted' | 'evidence_submitted' | 'achieved' | 'not_achieved' | 'dropped';
export type ProofState = 'open' | 'partly_delivered' | 'delivered' | 'accepted' | 'waived';
export type ProofDecision = 'none' | 'accepted' | 'waived';
export type StageState =
  | 'blocked'
  | 'ready'
  | 'in_test'
  | 'failed'
  | 'passed'
  | 'released'
  | 'stale'
  | 'not_applicable';
export type AcceptanceState =
  | 'planned'
  | 'requested'
  | 'inspection_scheduled'
  | 'refused'
  | 'accepted'
  | 'accepted_with_reservations'
  | 'deemed_accepted';
export type SurveyState = 'planned' | 'invited' | 'surveyed' | 'report_issued' | 'closed' | 'access_refused';
export type ExpertReportState = 'planned' | 'commissioned' | 'reporting' | 'completed' | 'cancelled';

export type CertificationAction =
  | 'register'
  | 'assess_design'
  | 'assess_post_construction'
  | 'certify'
  | 'miss_level'
  | 'abandon';
export type CreditAction = 'submit_evidence' | 'achieve' | 'not_achieve' | 'return' | 'drop' | 'reinstate';
export type UnitAction = 'schedule_inspection' | 'withdraw' | 'confirm_deemed';
export type SurveyAction = 'invite' | 'record_survey' | 'issue_report' | 'close' | 'refuse_access';

export interface PackageScope {
  ref: string;
  code: string;
  title: string;
  no_proofs_rationale: string;
}

/** What the server lets this reader do with the concept. Never re-derived in the client. */
export interface ConceptCan {
  manage: boolean;
  edit_plan: boolean;
  submit: boolean;
  submit_reason: 'manage_required' | 'invalid_transition' | 'concept_incomplete' | string | null;
  /** Approving on this page exists only on a project without gates; with gates the gate decision approves. */
  approve_applies?: boolean;
  approve?: boolean;
  approve_reason?: string | null;
  /** Reopening on this page exists only on a project without gates; with gates a change request reopens. */
  reopen_applies?: boolean;
  reopen?: boolean;
  reopen_reason?: string | null;
}

export interface Concept {
  id: string;
  project_id: string;
  catalogue_source: CatalogueSource;
  catalogue_id: string;
  catalogue_version: number;
  state: ConceptState;
  /** False on a project that never adopted a phase model: no gate will ever approve the concept. */
  gates_in_use?: boolean;
  governance_doc_id: string | null;
  /** The frame document the concept is bound to, as the governance module names it. */
  governance_document?: { id: string; code: string; label: QcLabel; status: string } | null;
  requirement_set_id: string | null;
  documentation_set_code: string | null;
  packages: PackageScope[];
  holidays: string[];
  revision_no: number;
  submitted_by: string | null;
  submitted_at: string | null;
  catalogue_label: QcLabel;
  catalogue_review_status: string;
  applicable_packages: PackageScope[];
  findings: Finding[];
  can: ConceptCan;
}

export interface ConceptRevision {
  id: string;
  revision_no: number;
  reason: string;
  created_by: string | null;
  created_by_name?: string | null;
  created_at?: string;
  snapshot?: { reopen_reason?: string | null } | null;
}

/* ── Catalogue ─────────────────────────────────────────────────────────── */

export interface CatalogueItem {
  code: string;
  name_key?: string;
  labels?: Record<string, string> | null;
  source_url?: string | null;
  review_status?: string;
}

export interface CatalogueLevel extends CatalogueItem {
  min_score: string | null;
  score_unit: string;
}

export interface CatalogueScheme extends CatalogueItem {
  scope: string;
  versions: string[];
  levels: CatalogueLevel[];
  credit_categories: string[];
}

export interface CatalogueEvidenceType extends CatalogueItem {
  kind: string;
  fulfilled_by: string[];
  default_deliverer: string;
}

export interface CatalogueStage extends CatalogueItem {
  order: number;
  description_key?: string;
  default_release_party: string;
  evidence_types: string[];
}

export interface RegimeEffect {
  effect: string;
  detail_key?: string;
  value?: string | null;
  source_url?: string | null;
  review_status?: string;
}

export interface CatalogueRegime extends CatalogueItem {
  country_code: string | null;
  contract_basis: string;
  act_name: string;
  partial_allowed: boolean;
  partial_term: string;
  reservable: string[];
  /** Facts of this regime nobody has checked against the source yet. */
  unconfirmed_facts?: string[];
  refusal_needs_defect: boolean;
  effects: RegimeEffect[];
}

export interface CatalogueSubject extends CatalogueItem {
  influence_triggers: string[];
  survey_methods: string[];
}

export interface Catalogue {
  id: string;
  version: number;
  name_key?: string;
  labels?: Record<string, string> | null;
  review_status?: string;
  standard_families: CatalogueItem[];
  requirement_categories: Array<CatalogueItem & { verification_method: string }>;
  certification_schemes: CatalogueScheme[];
  evidence_types: CatalogueEvidenceType[];
  commissioning_stages: CatalogueStage[];
  acceptance_regimes: CatalogueRegime[];
  documentation_sets: CatalogueItem[];
  preservation_subjects: CatalogueSubject[];
}

/* ── Standards and requirements ────────────────────────────────────────── */

export type Mandate = 'statute' | 'contract' | 'voluntary';

export interface AppliedStandard extends Capable {
  id: string;
  code: string;
  edition: string;
  title: string;
  family_code: string | null;
  discipline: string;
  package_refs: string[];
  source_url: string | null;
  mandate: Mandate;
  note: string;
}

export interface StandardInput {
  code: string;
  edition?: string;
  title?: string;
  family_code?: string | null;
  discipline?: string;
  mandate?: Mandate;
  note?: string;
}

export interface QualityRequirement {
  id: string;
  category: string;
  entity: string;
  attribute: string;
  constraint_value: string;
  unit: string;
  source_ref: string;
  verification_method: string | null;
  status: string | null;
  rationale: string;
}

export interface RequirementInput {
  category: string;
  entity: string;
  attribute: string;
  constraint_value?: string;
  unit?: string;
  source_ref?: string;
  verification_method?: string | null;
  rationale?: string;
}

/* ── Certification ─────────────────────────────────────────────────────── */

export interface Credit extends Capable {
  id: string;
  target_id: string;
  credit_code: string;
  category: string;
  points_targeted: string;
  points_achieved: string | null;
  owner_user_id: string | null;
  state: CreditState;
}

export interface Certification extends Capable {
  id: string;
  scheme_code: string;
  scheme_version: string;
  scope: string;
  target_level: string;
  achieved_level: string | null;
  assessor_contact_id: string | null;
  assessor_contact_label?: string | null;
  registration_no: string;
  certificate_cde_id: string | null;
  state: CertificationState;
  rationale: string;
  registered_on: string | null;
  certified_on: string | null;
  credits: Credit[];
  points_available: string | null;
  points_targeted: string;
  points_achieved: string;
}

export interface CertificationInput {
  scheme_code: string;
  scheme_version?: string;
  scope: string;
  target_level: string;
  registration_no?: string;
  assessor_contact_id?: string | null;
  /** Decimal string, or left out when the scheme has no fixed total. */
  points_available?: string;
}

export interface CertificationPatch {
  scheme_version?: string;
  target_level?: string;
  registration_no?: string;
  assessor_contact_id?: string | null;
  certificate_cde_id?: string | null;
  points_available?: string;
}

export interface CertificationTransitionInput {
  action: CertificationAction;
  achieved_level?: string | null;
  rationale?: string;
  on?: string | null;
}

export interface CreditInput {
  credit_code: string;
  category?: string;
  /** Decimal string; the server refuses a JSON number with a fraction. */
  points_targeted: string;
  owner_user_id?: string | null;
}

export interface CreditPatch {
  category?: string;
  points_targeted?: string;
  points_achieved?: string;
  owner_user_id?: string | null;
  action?: CreditAction;
}

/* ── Proofs and evidence ───────────────────────────────────────────────── */

export interface QuantityRule {
  per_quantity?: string;
  unit?: string;
  min_count?: number;
  placed_quantity?: string | null;
}

export interface Proof extends Capable {
  id: string;
  package_ref: string | null;
  plant_item_id: string | null;
  cx_system_id: string | null;
  evidence_type: string;
  title: string;
  deliverer_role: string;
  deliverer_contact_id: string | null;
  deliverer_contact_label?: string | null;
  required_by_kind: string;
  required_by_ref: string;
  quantity_rule: QuantityRule;
  review_by_role: string;
  source: string;
  decision: ProofDecision;
  decision_rationale: string;
  requested_by: string | null;
  requested_by_name?: string | null;
  decided_by: string | null;
  decided_by_name?: string | null;
  decided_at: string | null;
  derived_state: string;
  state: ProofState;
  counted: number;
  required: number;
  findings: Finding[];
}

export interface ProofInput {
  package_ref?: string | null;
  cx_system_id?: string | null;
  evidence_type: string;
  title?: string;
  deliverer_role: string;
  deliverer_contact_id?: string | null;
  required_by_kind: string;
  required_by_ref: string;
  quantity_rule?: QuantityRule | null;
}

export interface ProofPatch {
  title?: string;
  deliverer_role?: string;
  deliverer_contact_id?: string | null;
  required_by_kind?: string;
  required_by_ref?: string;
  quantity_rule?: QuantityRule | null;
}

export interface ProofPreviewRow {
  evidence_type: string;
  deliverer_role: string;
  required_by_kind: string;
  required_by_ref: string;
  quantity_rule: QuantityRule;
  quantity_rule_review_status: string | null;
  exists: boolean;
}

export interface ProofGenerateResult extends Page<ProofPreviewRow> {
  created: Proof[];
  preview: boolean;
}

export interface CoverageRow {
  package_ref: string | null;
  total: number;
  done: number;
  [state: string]: number | string | null;
}

export interface CoverageResponse extends Page<CoverageRow> {
  findings: Finding[];
}

export type LinkOwnerKind = 'proof' | 'credit' | 'stage_progress' | 'preservation' | 'expert_report';

export interface EvidenceFact {
  outcome: string | null;
  sample: string | null;
  calibration_expired: boolean;
  expired_at_use: boolean;
  quantity: string | null;
}

export interface EvidenceLink {
  id: string;
  owner_kind: LinkOwnerKind;
  owner_id: string;
  link_kind: string;
  link_id: string;
  retest_of: string | null;
  note: string;
  fact?: EvidenceFact | null;
  /** The name of the linked record; null when it cannot be named. */
  label?: string | null;
  /** False when the linked record is gone or left the project. */
  exists?: boolean;
}

export interface LinkCandidate {
  id: string;
  label: string;
  outcome?: string | null;
}

/* ── Stages ────────────────────────────────────────────────────────────── */

export interface StagePrecondition {
  code: string;
  params: Record<string, unknown>;
}

export interface StageDef extends Capable {
  id: string;
  code: string;
  order: number;
  name_override: string;
  owner_user_id: string | null;
  owner_user_id_name?: string | null;
  release_party_role: string;
  release_user_ids: string[];
  preconditions: StagePrecondition[];
  evidence_types: string[];
  applies_to: Record<string, unknown>;
  catalogue_code: string;
}

export interface StageDefInput {
  code: string;
  order: number;
  name_override?: string;
  owner_user_id?: string | null;
  release_party_role: string;
}

export interface StageDefPatch {
  order?: number;
  name_override?: string;
  owner_user_id?: string | null;
  release_party_role?: string;
}

export interface PreconditionResult {
  code: string;
  met: boolean;
  reason: string;
  params: Record<string, unknown>;
}

export interface StageProgress extends Capable {
  id: string;
  system_id: string;
  stage_code: string;
  state: StageState;
  rationale: string;
  depends_on_system_ids: string[];
  hold_gate_id: string | null;
  released_at: string | null;
  released_by: string | null;
  released_by_name?: string | null;
  computed_state: StageState;
  preconditions: PreconditionResult[];
  hold_gate?: HoldGateRef | null;
}

export interface CxSystemRef {
  id: string;
  name: string;
  system_type: string;
  status: string;
}

export interface StageMatrix extends Page<StageProgress> {
  systems: CxSystemRef[];
  stages: StageDef[];
}

export interface ReleaseRequestResult {
  progress_id: string;
  hold_gate: {
    id: string;
    gate_number: string | number | null;
    required_party_role: string;
    status: string;
    label?: string | null;
  };
}

/* ── Acceptance ────────────────────────────────────────────────────────── */

export interface DeemedDate {
  trigger: string;
  from: string;
  deemed_on: string | null;
  days_left: number | null;
  needs_deadline: boolean;
  source_url: string | null;
  review_status: string;
}

export interface AppliedEffect {
  id: string;
  unit_id: string;
  effect: string;
  effective_date: string | null;
  source_url: string | null;
  review_status: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  /** What confirming it set in motion; `revoked_at` marks a confirmation that no longer holds. */
  outcome?: Record<string, unknown> | null;
}

export interface UnmetPrecondition {
  kind: string;
  ref: string;
  label?: string | null;
}

export interface AcceptanceUnit extends Capable {
  id: string;
  code: string;
  title: string;
  kind: string;
  package_refs: string[];
  section_ref: string;
  regime_code: string | null;
  planned_date: string | null;
  schedule_activity_id?: string | null;
  handover_package_id: string | null;
  handover_package?: RecordRef | null;
  state: AcceptanceState;
  completion_notice_at: string | null;
  use_started_at: string | null;
  deadline_at: string | null;
  accepted_on: string | null;
  reservations: Array<Record<string, unknown>>;
  refusal_reason: string;
  refusal_defects: string[];
  regime: CatalogueRegime | null;
  deemed: DeemedDate[];
  effects_applied: AppliedEffect[];
  effects_proposed: RegimeEffect[];
  unmet: UnmetPrecondition[];
}

export interface AcceptanceUnitInput {
  code?: string;
  title?: string;
  kind: string;
  package_refs?: string[];
  section_ref?: string;
  regime_code?: string | null;
  planned_date?: string | null;
  schedule_activity_id?: string | null;
}

export type AcceptanceUnitPatch = Partial<Omit<AcceptanceUnitInput, 'kind'>> & { handover_package_id?: string | null };

export interface AcceptanceDatesInput {
  completion_notice_at?: string | null;
  use_started_at?: string | null;
  deadline_at?: string | null;
}

/* ── Preservation and expert reports ───────────────────────────────────── */

export interface Survey extends Capable {
  id: string;
  subject_kind: string;
  subject_ref: string;
  address: string;
  parcel: string;
  owner_contact_id?: string | null;
  owner_contact_label?: string | null;
  surveyor_contact_id?: string | null;
  surveyor_contact_label?: string | null;
  influence_triggers: string[];
  phase: string;
  methods: string[];
  planned_date: string | null;
  survey_date: string | null;
  invitation_sent_on: string | null;
  owner_acknowledged: boolean | null;
  access_refused_on: string | null;
  access_refusal_note: string;
  state: SurveyState;
  paired_with_id: string | null;
}

export interface SurveyInput {
  subject_kind: string;
  subject_ref: string;
  address?: string;
  parcel?: string;
  influence_triggers?: string[];
  phase: string;
  methods?: string[];
  planned_date?: string | null;
  owner_contact_id?: string | null;
  surveyor_contact_id?: string | null;
}

export type SurveyPatch = Partial<
  Pick<
    SurveyInput,
    'address' | 'parcel' | 'influence_triggers' | 'methods' | 'planned_date' | 'owner_contact_id' | 'surveyor_contact_id'
  >
>;

export interface SurveyActionInput {
  action: SurveyAction;
  on?: string | null;
  owner_acknowledged?: boolean | null;
  note?: string;
}

export interface SurveyList extends Page<Survey> {
  findings: Finding[];
}

export interface ExpertReport extends Capable {
  id: string;
  subject: string;
  expert_contact_id: string | null;
  expert_contact_label?: string | null;
  trigger: string;
  frequency: string;
  due_dates: string[];
  commitment_ref: string | null;
  state: ExpertReportState;
}

export interface ExpertReportInput {
  subject: string;
  expert_contact_id?: string | null;
  trigger?: string;
  frequency?: string;
  due_dates?: string[];
  state?: ExpertReportState;
}

/* ── Listings to choose from ───────────────────────────────────────────── */

/** One catalogue the project may pin: shipped with the product, kept by the tenant, or brought by a pack. */
export interface CatalogueChoice {
  kind: string;
  source: CatalogueSource;
  id: string;
  code: string;
  name: QcLabel;
  state: string;
  versions: number[];
  latest_version: number | null;
  review_status: string | null;
  jurisdiction_countries: string[];
  /** The one a new concept starts on. */
  default: boolean;
  /** The one this concept uses. */
  pinned: boolean;
  pack?: string | null;
}

export interface CatalogueChoices extends Page<CatalogueChoice> {
  can: { pin: boolean };
}

export type OptionKind =
  | 'contact'
  | 'plant_item'
  | 'cx_system'
  | 'schedule_activity'
  | 'handover_package'
  | 'certificate_document'
  | 'retest_of';

export interface OptionItem {
  id: string;
  label: string;
}

/** `available: false` is not an empty list: the server cannot offer one, and `reason` says why. */
export interface OptionList extends Page<OptionItem> {
  available: boolean;
  reason: string | null;
}

/* ── Readiness and validation ──────────────────────────────────────────── */

export interface Readiness {
  state?: ConceptState;
  concept: boolean;
  approved: boolean;
  errors: Finding[];
  /** References of the subjects that have no before survey yet. */
  preservation_unplanned: string[];
  /** Why the governance gate cannot read the concept, when it cannot. */
  gate_detail?: string | null;
}

export interface ValidationItem {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export type ExportWhat =
  | 'proofs'
  | 'stages'
  | 'acceptance'
  | 'preservation'
  | 'certification'
  | 'proof_matrix'
  | 'stage_matrix';

/* ── Errors ────────────────────────────────────────────────────────────── */

export interface RefusalDetail {
  code: string | null;
  messageKey: string | null;
  message: string | null;
  violations: Finding[];
  info: string | null;
  /** What another module said when the refusal came from it, in that module's own words. */
  detail: string | null;
}

/** The structured refusal the backend put in `detail`, or null for any other failure. */
export function refusalDetail(err: unknown): RefusalDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const d = detail as Record<string, unknown>;
  const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
  return {
    code: str(d.code),
    messageKey: str(d.message_key),
    message: str(d.message),
    violations: Array.isArray(d.violations) ? (d.violations as Finding[]) : [],
    info: str(d.info),
    detail: str(d.detail),
  };
}

/** The project has no quality concept yet: the one failure of the first read that is a normal state. */
export function isConceptMissing(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && refusalDetail(err)?.code === 'concept_missing';
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const qcKeys = {
  project: (projectId: string) => ['quality-concept', projectId] as const,
  concept: (projectId: string) => ['quality-concept', projectId, 'concept'] as const,
  catalogue: (projectId: string) => ['quality-concept', projectId, 'catalogue'] as const,
  catalogues: (projectId: string) => ['quality-concept', projectId, 'catalogues'] as const,
  options: (projectId: string, kind: string, q: string) => ['quality-concept', projectId, 'options', kind, q] as const,
  revisions: (projectId: string) => ['quality-concept', projectId, 'revisions'] as const,
  standards: (projectId: string) => ['quality-concept', projectId, 'standards'] as const,
  requirements: (projectId: string) => ['quality-concept', projectId, 'requirements'] as const,
  certifications: (projectId: string) => ['quality-concept', projectId, 'certifications'] as const,
  proofs: (projectId: string) => ['quality-concept', projectId, 'proofs'] as const,
  coverage: (projectId: string) => ['quality-concept', projectId, 'coverage'] as const,
  links: (projectId: string, kind: string, id: string) => ['quality-concept', projectId, 'links', kind, id] as const,
  candidates: (projectId: string, kind: string, q: string) =>
    ['quality-concept', projectId, 'candidates', kind, q] as const,
  stages: (projectId: string) => ['quality-concept', projectId, 'stages'] as const,
  matrix: (projectId: string) => ['quality-concept', projectId, 'stage-progress'] as const,
  units: (projectId: string) => ['quality-concept', projectId, 'acceptance-units'] as const,
  surveys: (projectId: string) => ['quality-concept', projectId, 'preservation'] as const,
  permitConditions: (projectId: string) => ['quality-concept', projectId, 'permit-conditions'] as const,
  expertReports: (projectId: string) => ['quality-concept', projectId, 'expert-reports'] as const,
  readiness: (projectId: string) => ['quality-concept', projectId, 'readiness'] as const,
  validation: (projectId: string) => ['quality-concept', projectId, 'validation'] as const,
};

/* ── Concept ───────────────────────────────────────────────────────────── */

export const getConcept = (projectId: string) => apiGet<Concept>(`/v1/quality-concept/projects/${projectId}/concept`);

export const createConcept = (projectId: string) => apiPost<Concept>(`/v1/quality-concept/projects/${projectId}/concept`, {});

export const patchConcept = (
  projectId: string,
  body: { packages?: PackageScope[]; holidays?: string[]; documentation_set_code?: string | null },
) => apiPatch<Concept>(`/v1/quality-concept/projects/${projectId}/concept`, body);

/** Creates what the chosen documentation set asks for; answers the created references by kind. */
export const applyDocumentationSet = (projectId: string) =>
  apiPost<Record<string, string[]>>(`/v1/quality-concept/projects/${projectId}/concept/documentation-set/apply`, {});

export const pinCatalogue = (
  projectId: string,
  body: { catalogue_source: CatalogueSource; catalogue_id: string; catalogue_version?: number | null },
) => apiPut<Concept>(`/v1/quality-concept/projects/${projectId}/concept/catalogue`, body);

export const listCatalogues = (projectId: string) => apiGet<CatalogueChoices>(`/v1/quality-concept/projects/${projectId}/catalogues`);

export const listOptions = (projectId: string, kind: OptionKind, q: string) =>
  apiGet<OptionList>(
    `/v1/quality-concept/projects/${projectId}/options?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}`,
  );

export const getCatalogue = (projectId: string) => apiGet<Catalogue>(`/v1/quality-concept/projects/${projectId}/concept/catalogue`);

export const submitConcept = (projectId: string) => apiPost<Concept>(`/v1/quality-concept/projects/${projectId}/concept/submit`, {});

/** `return` is the only step a reader takes here; a binding concept reopens through a change request. */
export const conceptAction = (projectId: string, action: 'return') =>
  apiPost<Concept>(`/v1/quality-concept/projects/${projectId}/concept/${action}`, {});

/** Approves a submitted concept on a project without gates; it becomes binding in one step. */
export const approveConcept = (projectId: string) => apiPost<Concept>(`/v1/quality-concept/projects/${projectId}/concept/approve`, {});

/** Reopens a binding concept on a project without gates; the reason is kept with the revision. */
export const reopenConcept = (projectId: string, body: { rationale: string }) =>
  apiPost<Concept>(`/v1/quality-concept/projects/${projectId}/concept/reopen`, body);

export const listRevisions = (projectId: string) => apiGet<Page<ConceptRevision>>(`/v1/quality-concept/projects/${projectId}/concept/revisions`);

/* ── Standards and requirements ────────────────────────────────────────── */

export const listStandards = (projectId: string) => apiGet<Page<AppliedStandard>>(`/v1/quality-concept/projects/${projectId}/standards`);

export const createStandard = (projectId: string, body: StandardInput) =>
  apiPost<AppliedStandard>(`/v1/quality-concept/projects/${projectId}/standards`, body);

export const patchStandard = (projectId: string, id: string, body: Partial<StandardInput>) =>
  apiPatch<AppliedStandard>(`/v1/quality-concept/projects/${projectId}/standards/${id}`, body);

export const deleteStandard = (projectId: string, id: string) => apiDelete(`/v1/quality-concept/projects/${projectId}/standards/${id}`);

export const listRequirements = (projectId: string) =>
  apiGet<Page<QualityRequirement>>(`/v1/quality-concept/projects/${projectId}/requirements`);

export const addRequirement = (projectId: string, body: RequirementInput) =>
  apiPost<QualityRequirement>(`/v1/quality-concept/projects/${projectId}/requirements`, body);

/* ── Certification ─────────────────────────────────────────────────────── */

export const listCertifications = (projectId: string) =>
  apiGet<Page<Certification> & { findings: Finding[] }>(`/v1/quality-concept/projects/${projectId}/certifications`);

export const createCertification = (projectId: string, body: CertificationInput) =>
  apiPost<Certification>(`/v1/quality-concept/projects/${projectId}/certifications`, body);

export const patchCertification = (projectId: string, id: string, body: CertificationPatch) =>
  apiPatch<Certification>(`/v1/quality-concept/projects/${projectId}/certifications/${id}`, body);

export const transitionCertification = (projectId: string, id: string, body: CertificationTransitionInput) =>
  apiPost<Certification>(`/v1/quality-concept/projects/${projectId}/certifications/${id}/transition`, body);

export const deleteCertification = (projectId: string, id: string) =>
  apiDelete(`/v1/quality-concept/projects/${projectId}/certifications/${id}`);

export const addCredits = (projectId: string, certificationId: string, items: CreditInput[]) =>
  apiPost<Page<Credit>>(`/v1/quality-concept/projects/${projectId}/certifications/${certificationId}/credits`, { items });

/** Credit state changes travel in the same PATCH as its fields: there is no separate transition route. */
export const patchCredit = (projectId: string, id: string, body: CreditPatch) =>
  apiPatch<Credit>(`/v1/quality-concept/projects/${projectId}/credits/${id}`, body);

export const deleteCredit = (projectId: string, id: string) => apiDelete(`/v1/quality-concept/projects/${projectId}/credits/${id}`);

/* ── Proofs ────────────────────────────────────────────────────────────── */

export const listProofs = (projectId: string) => apiGet<Page<Proof>>(`/v1/quality-concept/projects/${projectId}/proofs?limit=2000`);

export const createProof = (projectId: string, body: ProofInput) => apiPost<Proof>(`/v1/quality-concept/projects/${projectId}/proofs`, body);

export const patchProof = (projectId: string, id: string, body: ProofPatch) =>
  apiPatch<Proof>(`/v1/quality-concept/projects/${projectId}/proofs/${id}`, body);

export const deleteProof = (projectId: string, id: string) => apiDelete(`/v1/quality-concept/projects/${projectId}/proofs/${id}`);

/** Without `confirm` the server only previews; with it, it creates the named evidence types. */
export const generateProofs = (projectId: string, body: { package_ref: string; confirm?: string[] }) =>
  apiPost<ProofGenerateResult>(`/v1/quality-concept/projects/${projectId}/proofs/generate`, body);

export const getCoverage = (projectId: string) => apiGet<CoverageResponse>(`/v1/quality-concept/projects/${projectId}/proofs/coverage`);

export const requestWaiver = (projectId: string, id: string, rationale: string) =>
  apiPost<Proof>(`/v1/quality-concept/projects/${projectId}/proofs/${id}/waiver-request`, { rationale });

export const decideWaiver = (projectId: string, id: string, approve: boolean) =>
  apiPost<Proof>(`/v1/quality-concept/projects/${projectId}/proofs/${id}/waiver-decision`, { approve });

export const proofAction = (projectId: string, id: string, action: 'accept' | 'reopen') =>
  apiPost<Proof>(`/v1/quality-concept/projects/${projectId}/proofs/${id}/${action}`, {});

/* ── Evidence links ────────────────────────────────────────────────────── */

export const listLinks = (projectId: string, ownerKind: LinkOwnerKind, ownerId: string) =>
  apiGet<Page<EvidenceLink>>(`/v1/quality-concept/projects/${projectId}/evidence-links?owner_kind=${ownerKind}&owner_id=${ownerId}`);

export const addLink = (
  projectId: string,
  body: {
    owner_kind: LinkOwnerKind;
    owner_id: string;
    link_kind: string;
    link_id: string;
    note?: string;
    /** The earlier link of the same record this one repeats. */
    retest_of?: string;
  },
) => apiPost<EvidenceLink>(`/v1/quality-concept/projects/${projectId}/evidence-links`, body);

export const removeLink = (projectId: string, id: string) => apiDelete(`/v1/quality-concept/projects/${projectId}/evidence-links/${id}`);

export const listCandidates = (projectId: string, linkKind: string, q: string) =>
  apiGet<Page<LinkCandidate>>(
    `/v1/quality-concept/projects/${projectId}/evidence-links/candidates?link_kind=${encodeURIComponent(linkKind)}&q=${encodeURIComponent(q)}`,
  );

/* ── Stages ────────────────────────────────────────────────────────────── */

export const listStages = (projectId: string) => apiGet<Page<StageDef>>(`/v1/quality-concept/projects/${projectId}/stages`);

export const applyCatalogueStages = (projectId: string) =>
  apiPost<Page<StageDef>>(`/v1/quality-concept/projects/${projectId}/stages/apply-catalogue`, {});

export const addStage = (projectId: string, body: StageDefInput) => apiPost<StageDef>(`/v1/quality-concept/projects/${projectId}/stages`, body);

export const patchStage = (projectId: string, id: string, body: StageDefPatch) =>
  apiPatch<StageDef>(`/v1/quality-concept/projects/${projectId}/stages/${id}`, body);

export const deleteStage = (projectId: string, id: string) => apiDelete(`/v1/quality-concept/projects/${projectId}/stages/${id}`);

export const getStageMatrix = (projectId: string) => apiGet<StageMatrix>(`/v1/quality-concept/projects/${projectId}/stage-progress`);

export const syncStageProgress = (projectId: string) => apiPost<StageMatrix>(`/v1/quality-concept/projects/${projectId}/stage-progress/sync`, {});

export const openStageTest = (projectId: string, id: string) =>
  apiPost<StageProgress>(`/v1/quality-concept/projects/${projectId}/stage-progress/${id}/open-test`, {});

export const recordStageResult = (
  projectId: string,
  id: string,
  body: { result: 'pass' | 'fail'; note?: string; severity?: 'low' | 'medium' | 'high' | 'critical' },
) => apiPost<StageProgress>(`/v1/quality-concept/projects/${projectId}/stage-progress/${id}/result`, body);

export const requestStageRelease = (projectId: string, id: string) =>
  apiPost<ReleaseRequestResult>(`/v1/quality-concept/projects/${projectId}/stage-progress/${id}/request-release`, {});

export const markStageNotApplicable = (projectId: string, id: string, rationale: string) =>
  apiPost<StageProgress>(`/v1/quality-concept/projects/${projectId}/stage-progress/${id}/not-applicable`, { rationale });

export const reinstateStage = (projectId: string, id: string) =>
  apiPost<StageProgress>(`/v1/quality-concept/projects/${projectId}/stage-progress/${id}/reinstate`, {});

export const setStageDependencies = (projectId: string, id: string, systemIds: string[]) =>
  apiPut<StageProgress>(`/v1/quality-concept/projects/${projectId}/stage-progress/${id}/depends-on`, { system_ids: systemIds });

/* ── Acceptance ────────────────────────────────────────────────────────── */

export const listUnits = (projectId: string) =>
  apiGet<Page<AcceptanceUnit>>(`/v1/quality-concept/projects/${projectId}/acceptance-units?today=${localToday()}`);

export const createUnit = (projectId: string, body: AcceptanceUnitInput) =>
  apiPost<AcceptanceUnit>(`/v1/quality-concept/projects/${projectId}/acceptance-units`, body);

export const patchUnit = (projectId: string, id: string, body: AcceptanceUnitPatch) =>
  apiPatch<AcceptanceUnit>(`/v1/quality-concept/projects/${projectId}/acceptance-units/${id}`, body);

export const deleteUnit = (projectId: string, id: string) => apiDelete(`/v1/quality-concept/projects/${projectId}/acceptance-units/${id}`);

export const requestAcceptance = (projectId: string, id: string, withReservations: boolean) =>
  apiPost<AcceptanceUnit>(`/v1/quality-concept/projects/${projectId}/acceptance-units/${id}/request`, { with_reservations: withReservations });

export const recordUnitDates = (projectId: string, id: string, body: AcceptanceDatesInput) =>
  apiPost<AcceptanceUnit>(`/v1/quality-concept/projects/${projectId}/acceptance-units/${id}/dates`, body);

export const refuseUnit = (projectId: string, id: string, body: { rationale: string; defects: string[] }) =>
  apiPost<AcceptanceUnit>(`/v1/quality-concept/projects/${projectId}/acceptance-units/${id}/refuse`, body);

export const confirmEffect = (projectId: string, id: string, body: { effect: string; effective_date?: string | null }) =>
  apiPost<AppliedEffect>(`/v1/quality-concept/projects/${projectId}/acceptance-units/${id}/effects`, body);

export const unitAction = (projectId: string, id: string, action: UnitAction) =>
  apiPost<AcceptanceUnit>(`/v1/quality-concept/projects/${projectId}/acceptance-units/${id}/${action}`, {});

/* ── Preservation and expert reports ───────────────────────────────────── */

export const listSurveys = (projectId: string) =>
  apiGet<SurveyList>(`/v1/quality-concept/projects/${projectId}/preservation?today=${localToday()}`);

export const createSurvey = (projectId: string, body: SurveyInput) =>
  apiPost<Survey>(`/v1/quality-concept/projects/${projectId}/preservation`, body);

export const patchSurvey = (projectId: string, id: string, body: SurveyPatch) =>
  apiPatch<Survey>(`/v1/quality-concept/projects/${projectId}/preservation/${id}`, body);

export const surveyAction = (projectId: string, id: string, body: SurveyActionInput) =>
  apiPost<Survey>(`/v1/quality-concept/projects/${projectId}/preservation/${id}/action`, body);

export const pairSurvey = (projectId: string, id: string, beforeId: string) =>
  apiPost<Survey>(`/v1/quality-concept/projects/${projectId}/preservation/${id}/pair`, { before_id: beforeId });

export const deleteSurvey = (projectId: string, id: string) => apiDelete(`/v1/quality-concept/projects/${projectId}/preservation/${id}`);

export interface PermitConditionCheck {
  condition_id: string;
  permit_id: string;
  permit_reference: string;
  permit_type_code: string;
  number: string;
  requirement: string;
  evidence_required: string;
  trigger: string;
  due_date: string | null;
  topic: string;
  responsible_party: string;
  owner_user_id: string | null;
  condition_state: string;
  check_state: 'to_prove' | 'in_verification' | 'failed' | 'proven' | 'not_required';
  blocks_start: boolean;
}

export interface PermitConditionChecks {
  available: boolean;
  reason: string;
  items: PermitConditionCheck[];
  summary: { total: number; proven: number; unproven: number; failed: number; blocks_start: number };
}

export const getPermitConditionChecks = (projectId: string) =>
  apiGet<PermitConditionChecks>(`/v1/quality-concept/projects/${projectId}/permit-conditions`);

export const listExpertReports = (projectId: string) =>
  apiGet<Page<ExpertReport>>(`/v1/quality-concept/projects/${projectId}/expert-reports`);

export const createExpertReport = (projectId: string, body: ExpertReportInput) =>
  apiPost<ExpertReport>(`/v1/quality-concept/projects/${projectId}/expert-reports`, body);

export const patchExpertReport = (projectId: string, id: string, body: Partial<ExpertReportInput>) =>
  apiPatch<ExpertReport>(`/v1/quality-concept/projects/${projectId}/expert-reports/${id}`, body);

export const deleteExpertReport = (projectId: string, id: string) =>
  apiDelete(`/v1/quality-concept/projects/${projectId}/expert-reports/${id}`);

/* ── Readiness, validation, export ─────────────────────────────────────── */

export const getReadiness = (projectId: string) =>
  apiGet<Readiness>(`/v1/quality-concept/projects/${projectId}/readiness?today=${localToday()}`);

export const getValidation = (projectId: string) =>
  apiGet<Page<ValidationItem>>(`/v1/quality-concept/projects/${projectId}/validation?today=${localToday()}`);

export function downloadExport(projectId: string, what: ExportWhat, format: 'pdf' | 'xlsx'): Promise<void> {
  return downloadWithAuth(`${API_BASE}/v1/quality-concept/projects/${projectId}/export?what=${what}&format=${format}`, `quality_${what}.${format}`);
}
