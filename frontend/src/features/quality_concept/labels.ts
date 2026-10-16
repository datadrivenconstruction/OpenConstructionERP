// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the quality concept screens show for a code: the states and
// actions of each record, the closed vocabularies, the findings the server
// computes and the catalogue item names. The vocabularies are written as key
// maps rather than built from the code at runtime, so the key test can
// enumerate them and a translator can find every key by grep.

import { ApiError, getErrorMessage } from '@/shared/lib/api';

import { refusalDetail, type Capable, type CatalogueItem } from './api';
import { canKey, may, whyNot } from './rules';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];
export type KeyMap = Record<string, KeyText>;

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const CONCEPT_STATE: KeyMap = {
  draft: ['qualityConcept.conceptState.draft', 'Draft'],
  in_review: ['qualityConcept.conceptState.in_review', 'In review'],
  approved: ['qualityConcept.conceptState.approved', 'Approved'],
  binding: ['qualityConcept.conceptState.binding', 'Binding'],
  revising: ['qualityConcept.conceptState.revising', 'Reopened'],
};

export const CERTIFICATION_STATE: KeyMap = {
  planned: ['qualityConcept.certState.planned', 'Planned'],
  registered: ['qualityConcept.certState.registered', 'Registered'],
  design_assessed: ['qualityConcept.certState.design_assessed', 'Design assessed'],
  post_construction_assessed: ['qualityConcept.certState.post_construction_assessed', 'Assessed after construction'],
  certified: ['qualityConcept.certState.certified', 'Certified'],
  level_missed: ['qualityConcept.certState.level_missed', 'Target level missed'],
  abandoned: ['qualityConcept.certState.abandoned', 'Abandoned'],
};

export const CERTIFICATION_ACTION: KeyMap = {
  register: ['qualityConcept.certAction.register', 'Record registration'],
  assess_design: ['qualityConcept.certAction.assess_design', 'Record design assessment'],
  assess_post_construction: ['qualityConcept.certAction.assess_post_construction', 'Record final assessment'],
  certify: ['qualityConcept.certAction.certify', 'Record certificate'],
  miss_level: ['qualityConcept.certAction.miss_level', 'Record a lower level'],
  abandon: ['qualityConcept.certAction.abandon', 'Abandon target'],
};

export const CERTIFICATION_SCOPE: KeyMap = {
  building: ['qualityConcept.certScope.building', 'Building'],
  plant: ['qualityConcept.certScope.plant', 'Plant'],
  operation: ['qualityConcept.certScope.operation', 'Operation'],
};

export const CREDIT_STATE: KeyMap = {
  targeted: ['qualityConcept.creditState.targeted', 'Targeted'],
  evidence_submitted: ['qualityConcept.creditState.evidence_submitted', 'Evidence submitted'],
  achieved: ['qualityConcept.creditState.achieved', 'Achieved'],
  not_achieved: ['qualityConcept.creditState.not_achieved', 'Not achieved'],
  dropped: ['qualityConcept.creditState.dropped', 'Dropped'],
};

export const CREDIT_ACTION: KeyMap = {
  submit_evidence: ['qualityConcept.creditAction.submit_evidence', 'Submit evidence'],
  achieve: ['qualityConcept.creditAction.achieve', 'Mark achieved'],
  not_achieve: ['qualityConcept.creditAction.not_achieve', 'Mark not achieved'],
  return: ['qualityConcept.creditAction.return', 'Return for rework'],
  drop: ['qualityConcept.creditAction.drop', 'Drop credit'],
  reinstate: ['qualityConcept.creditAction.reinstate', 'Reinstate credit'],
};

export const PROOF_STATE: KeyMap = {
  open: ['qualityConcept.proofState.open', 'Open'],
  partly_delivered: ['qualityConcept.proofState.partly_delivered', 'Partly delivered'],
  delivered: ['qualityConcept.proofState.delivered', 'Delivered'],
  accepted: ['qualityConcept.proofState.accepted', 'Accepted'],
  waived: ['qualityConcept.proofState.waived', 'Waived'],
};

export const PROOF_ACTION: KeyMap = {
  accept: ['qualityConcept.proofAction.accept', 'Accept proof'],
  request_waiver: ['qualityConcept.actions.requestWaiver', 'Request waiver'],
  approve_waiver: ['qualityConcept.proofAction.approve_waiver', 'Approve waiver'],
  reject_waiver: ['qualityConcept.proofAction.reject_waiver', 'Reject waiver'],
  reopen: ['qualityConcept.proofAction.reopen', 'Reopen'],
};

export const DELIVERER_ROLE: KeyMap = {
  designer: ['qualityConcept.deliverer.designer', 'Designer'],
  contractor: ['qualityConcept.deliverer.contractor', 'Contractor'],
  supplier: ['qualityConcept.deliverer.supplier', 'Supplier'],
  independent_expert: ['qualityConcept.deliverer.independent_expert', 'Independent expert'],
  owner: ['qualityConcept.deliverer.owner', 'Owner'],
  authority: ['qualityConcept.deliverer.authority', 'Authority'],
};

export const REQUIRED_BY_KIND: KeyMap = {
  stage: ['qualityConcept.requiredBy.stage', 'Commissioning stage'],
  acceptance_unit: ['qualityConcept.requiredBy.acceptance_unit', 'Acceptance unit'],
  activity: ['qualityConcept.requiredBy.activity', 'Schedule activity'],
  date: ['qualityConcept.requiredBy.date', 'Fixed date'],
};

export const MANDATE: KeyMap = {
  statute: ['qualityConcept.mandate.statute', 'Required by law'],
  contract: ['qualityConcept.mandate.contract', 'Agreed in the contract'],
  voluntary: ['qualityConcept.mandate.voluntary', 'Voluntary'],
};

export const VERIFICATION_METHOD: KeyMap = {
  inspection: ['qualityConcept.verification.inspection', 'Inspection'],
  analysis: ['qualityConcept.verification.analysis', 'Analysis'],
  demonstration: ['qualityConcept.verification.demonstration', 'Demonstration'],
  test: ['qualityConcept.verification.test', 'Test'],
  document_review: ['qualityConcept.verification.document_review', 'Document review'],
  model_check: ['qualityConcept.verification.model_check', 'Model check'],
};

export const STAGE_STATE: KeyMap = {
  blocked: ['qualityConcept.stageState.blocked', 'Blocked'],
  ready: ['qualityConcept.stageState.ready', 'Ready for test'],
  in_test: ['qualityConcept.stageState.in_test', 'In test'],
  failed: ['qualityConcept.stageState.failed', 'Failed'],
  passed: ['qualityConcept.stageState.passed', 'Passed'],
  released: ['qualityConcept.stageState.released', 'Released'],
  stale: ['qualityConcept.stageState.stale', 'Release outdated'],
  not_applicable: ['qualityConcept.stageState.not_applicable', 'Not applicable'],
};

export const STAGE_ACTION: KeyMap = {
  open_test: ['qualityConcept.stageAction.open_test', 'Start test'],
  pass: ['qualityConcept.stageAction.pass', 'Record pass'],
  fail: ['qualityConcept.stageAction.fail', 'Record fail'],
  request_release: ['qualityConcept.actions.requestRelease', 'Request release'],
  not_applicable: ['qualityConcept.stageAction.not_applicable', 'Mark not applicable'],
  reinstate: ['qualityConcept.stageAction.reinstate', 'Bring back into the plan'],
};

export const PARTY_ROLE: KeyMap = {
  qc: ['qualityConcept.party.qc', 'Contractor quality control'],
  qa: ['qualityConcept.party.qa', 'Client quality assurance'],
  tpi: ['qualityConcept.party.tpi', 'Third-party inspector'],
  ahj: ['qualityConcept.party.ahj', 'Authority'],
};

export const PRECONDITION: KeyMap = {
  previous_stage_released: ['qualityConcept.precondition.previous_stage_released', 'Previous stage released'],
  proofs_delivered: ['qualityConcept.precondition.proofs_delivered', 'Required proofs delivered'],
  no_open_cx_issues: ['qualityConcept.precondition.no_open_cx_issues', 'No open commissioning issues'],
  hold_gates_released: ['qualityConcept.precondition.hold_gates_released', 'Hold points released'],
  plant_item_delivered: ['qualityConcept.precondition.plant_item_delivered', 'Equipment delivered'],
  delivery_limit_agreed: ['qualityConcept.precondition.delivery_limit_agreed', 'Delivery limits agreed'],
  authority_acceptance_present: [
    'qualityConcept.precondition.authority_acceptance_present',
    'Authority acceptance on file',
  ],
  systems_released: ['qualityConcept.precondition.systems_released', 'Systems it depends on released'],
  documentation_slots_delivered: [
    'qualityConcept.precondition.documentation_slots_delivered',
    'Handover documents delivered',
  ],
};

export const SEVERITY: KeyMap = {
  low: ['qualityConcept.severity.low', 'Low'],
  medium: ['qualityConcept.severity.medium', 'Medium'],
  high: ['qualityConcept.severity.high', 'High'],
  critical: ['qualityConcept.severity.critical', 'Critical'],
};

export const ACCEPTANCE_STATE: KeyMap = {
  planned: ['qualityConcept.acceptanceState.planned', 'Planned'],
  requested: ['qualityConcept.acceptanceState.requested', 'Requested'],
  inspection_scheduled: ['qualityConcept.acceptanceState.inspection_scheduled', 'Inspection scheduled'],
  refused: ['qualityConcept.acceptanceState.refused', 'Refused'],
  accepted: ['qualityConcept.acceptanceState.accepted', 'Accepted'],
  accepted_with_reservations: [
    'qualityConcept.acceptanceState.accepted_with_reservations',
    'Accepted with reservations',
  ],
  deemed_accepted: ['qualityConcept.acceptanceState.deemed_accepted', 'Deemed accepted'],
};

export const ACCEPTANCE_ACTION: KeyMap = {
  request: ['qualityConcept.acceptanceAction.request', 'Request acceptance'],
  schedule_inspection: ['qualityConcept.acceptanceAction.schedule_inspection', 'Schedule inspection'],
  withdraw: ['qualityConcept.acceptanceAction.withdraw', 'Withdraw request'],
  refuse: ['qualityConcept.acceptanceAction.refuse', 'Refuse acceptance'],
  confirm_deemed: ['qualityConcept.acceptanceAction.confirm_deemed', 'Confirm deemed acceptance'],
  record_dates: ['qualityConcept.acceptanceAction.record_dates', 'Record dates'],
};

export const ACCEPTANCE_KIND: KeyMap = {
  partial_package: ['qualityConcept.acceptanceKind.partial_package', 'Partial, by package'],
  partial_section: ['qualityConcept.acceptanceKind.partial_section', 'Partial, by section'],
  total: ['qualityConcept.acceptanceKind.total', 'Whole works'],
  handover_to_operation: ['qualityConcept.acceptanceKind.handover_to_operation', 'Handover to operation'],
  authority: ['qualityConcept.acceptanceKind.authority', 'Authority acceptance'],
};

export const LEGAL_EFFECT: KeyMap = {
  risk_transfer: ['qualityConcept.effect.risk_transfer', 'Risk passes to the client'],
  limitation_starts: ['qualityConcept.effect.limitation_starts', 'Limitation period starts'],
  payment_due: ['qualityConcept.effect.payment_due', 'Payment falls due'],
  retention_release_part: ['qualityConcept.effect.retention_release_part', 'Part of the retention is released'],
  liquidated_damages_end: ['qualityConcept.effect.liquidated_damages_end', 'Delay damages stop'],
  burden_of_proof_shifts: ['qualityConcept.effect.burden_of_proof_shifts', 'Burden of proof shifts'],
  defects_period_starts: ['qualityConcept.effect.defects_period_starts', 'Defects period starts'],
  occupation_permitted: ['qualityConcept.effect.occupation_permitted', 'The client may use the works'],
  insurance_responsibility_shifts: [
    'qualityConcept.effect.insurance_responsibility_shifts',
    'Insurance responsibility shifts',
  ],
};

export const DEEMED_TRIGGER: KeyMap = {
  completion_notice: ['qualityConcept.deemedTrigger.completion_notice', 'Completion notice'],
  use_start: ['qualityConcept.deemedTrigger.use_start', 'Start of use'],
  deadline_set: ['qualityConcept.deemedTrigger.deadline_set', 'Deadline set by the contractor'],
};

export const UNMET_KIND: KeyMap = {
  stage: ['qualityConcept.unmet.stage', 'Commissioning stage not released'],
  proofs: ['qualityConcept.unmet.proofs', 'Proof not delivered'],
  documentation: ['qualityConcept.unmet.documentation', 'Handover document missing'],
  defects: ['qualityConcept.unmet.defects', 'Open defect'],
  partials: ['qualityConcept.unmet.partials', 'Partial acceptance still open'],
  final_stage: ['qualityConcept.unmet.final_stage', 'Final commissioning stage not released'],
  fm_data: ['qualityConcept.unmet.fm_data', 'Operation data missing'],
  material_defects: ['qualityConcept.unmet.material_defects', 'Open material defect'],
  hold_gates: ['qualityConcept.unmet.hold_gates', 'Hold point not released'],
};

export const SURVEY_STATE: KeyMap = {
  planned: ['qualityConcept.surveyState.planned', 'Planned'],
  invited: ['qualityConcept.surveyState.invited', 'Owner invited'],
  surveyed: ['qualityConcept.surveyState.surveyed', 'Surveyed'],
  report_issued: ['qualityConcept.surveyState.report_issued', 'Report issued'],
  closed: ['qualityConcept.surveyState.closed', 'Closed'],
  access_refused: ['qualityConcept.surveyState.access_refused', 'Access refused'],
};

export const SURVEY_ACTION: KeyMap = {
  invite: ['qualityConcept.surveyAction.invite', 'Record invitation'],
  record_survey: ['qualityConcept.surveyAction.record_survey', 'Record survey'],
  issue_report: ['qualityConcept.surveyAction.issue_report', 'Record report issued'],
  close: ['qualityConcept.surveyAction.close', 'Close'],
  refuse_access: ['qualityConcept.surveyAction.refuse_access', 'Record refused access'],
};

export const SURVEY_PHASE: KeyMap = {
  before: ['qualityConcept.surveyPhase.before', 'Before the works'],
  during: ['qualityConcept.surveyPhase.during', 'During the works'],
  after: ['qualityConcept.surveyPhase.after', 'After the works'],
  on_complaint: ['qualityConcept.surveyPhase.on_complaint', 'After a complaint'],
};

export const SURVEY_METHOD: KeyMap = {
  photo: ['qualityConcept.surveyMethod.photo', 'Photos'],
  crack_mapping: ['qualityConcept.surveyMethod.crack_mapping', 'Crack mapping'],
  level_survey: ['qualityConcept.surveyMethod.level_survey', 'Level survey'],
  vibration_monitoring: ['qualityConcept.surveyMethod.vibration_monitoring', 'Vibration monitoring'],
  reality_capture: ['qualityConcept.surveyMethod.reality_capture', 'Reality capture'],
};

export const INFLUENCE_TRIGGER: KeyMap = {
  excavation: ['qualityConcept.trigger.excavation', 'Excavation'],
  piling: ['qualityConcept.trigger.piling', 'Piling'],
  dewatering: ['qualityConcept.trigger.dewatering', 'Dewatering'],
  vibration: ['qualityConcept.trigger.vibration', 'Vibration'],
  crane_oversail: ['qualityConcept.trigger.crane_oversail', 'Crane oversail'],
  demolition: ['qualityConcept.trigger.demolition', 'Demolition'],
};

export const EXPERT_STATE: KeyMap = {
  planned: ['qualityConcept.expertState.planned', 'Planned'],
  commissioned: ['qualityConcept.expertState.commissioned', 'Commissioned'],
  reporting: ['qualityConcept.expertState.reporting', 'Reporting'],
  completed: ['qualityConcept.expertState.completed', 'Completed'],
  cancelled: ['qualityConcept.expertState.cancelled', 'Cancelled'],
};

export const LINK_KIND: KeyMap = {
  cc_test_result: ['qualityConcept.linkKind.cc_test_result', 'Test result'],
  cc_material_record: ['qualityConcept.linkKind.cc_material_record', 'Material record'],
  cc_inspection: ['qualityConcept.linkKind.cc_inspection', 'Site inspection'],
  cc_asbuilt: ['qualityConcept.linkKind.cc_asbuilt', 'As-built record'],
  cc_handover_package: ['qualityConcept.linkKind.cc_handover_package', 'Handover act'],
  qms_itp_plan: ['qualityConcept.linkKind.qms_itp_plan', 'Inspection and test plan'],
  qms_calibration: ['qualityConcept.linkKind.qms_calibration', 'Calibration record'],
  cx_checklist: ['qualityConcept.linkKind.cx_checklist', 'Commissioning checklist'],
  cx_system: ['qualityConcept.linkKind.cx_system', 'Commissioning system'],
  closeout_slot: ['qualityConcept.linkKind.closeout_slot', 'Closeout document'],
  submittal: ['qualityConcept.linkKind.submittal', 'Submittal'],
  inspection: ['qualityConcept.linkKind.inspection', 'Inspection'],
  cde_document: ['qualityConcept.linkKind.cde_document', 'Document in the CDE'],
  diary_photo: ['qualityConcept.linkKind.diary_photo', 'Site diary photo'],
  diary_reality_capture: ['qualityConcept.linkKind.diary_reality_capture', 'Reality capture from the diary'],
  requirement_deliverable: ['qualityConcept.linkKind.requirement_deliverable', 'Requirement deliverable'],
  goods_receipt: ['qualityConcept.linkKind.goods_receipt', 'Delivery (goods receipt)'],
};

export const FACT_OUTCOME: KeyMap = {
  pass: ['qualityConcept.factOutcome.pass', 'Passed'],
  fail: ['qualityConcept.factOutcome.fail', 'Failed'],
  pending: ['qualityConcept.factOutcome.pending', 'Pending'],
};

/**
 * The sentence for each finding the server computes. `{{ref}}` is the thing
 * the finding is about, already turned into a name by the caller.
 */
export const FINDING: KeyMap = {
  standards_basis_missing: ['qualityConcept.finding.standards_basis_missing', 'No standard is named yet'],
  stage_model_missing: ['qualityConcept.finding.stage_model_missing', 'No commissioning stages are set up yet'],
  package_without_proofs: [
    'qualityConcept.finding.package_without_proofs',
    'Package {{ref}} has no proofs and no reason why none are needed',
  ],
  acceptance_unit_per_package: [
    'qualityConcept.finding.acceptance_unit_per_package',
    'Package {{ref}} is not covered by any acceptance unit',
  ],
  acceptance_regime_missing: [
    'qualityConcept.finding.acceptance_regime_missing',
    'An acceptance unit has no acceptance regime',
  ],
  stage_without_owner: ['qualityConcept.finding.stage_without_owner', 'Stage {{ref}} has no owner'],
  stage_without_release_party: [
    'qualityConcept.finding.stage_without_release_party',
    'Stage {{ref}} has no release party',
  ],
  proof_without_deliverer: ['qualityConcept.finding.proof_without_deliverer', 'A proof names nobody who delivers it'],
  proof_without_due: ['qualityConcept.finding.proof_without_due', 'A proof has no point by which it is due'],
  proof_due_stage_unknown: [
    'qualityConcept.finding.proof_due_stage_unknown',
    'A proof is due at a stage the project does not have',
  ],
  proof_due_unit_unknown: [
    'qualityConcept.finding.proof_due_unit_unknown',
    'A proof is due at an acceptance unit that does not exist',
  ],
  proof_due_date_invalid: ['qualityConcept.finding.proof_due_date_invalid', 'A proof has a due date that is not a date'],
  evidence_kind_not_allowed: [
    'qualityConcept.finding.evidence_kind_not_allowed',
    'A linked record is of a kind that cannot prove this evidence type',
  ],
  evidence_with_expired_calibration: [
    'qualityConcept.finding.evidence_with_expired_calibration',
    'Evidence was measured with an instrument whose calibration had expired',
  ],
  failed_evidence_unresolved: [
    'qualityConcept.finding.failed_evidence_unresolved',
    'A failed test has no passing retest yet',
  ],
  material_expired_at_use: ['qualityConcept.finding.material_expired_at_use', 'Material was past its shelf life when used'],
  acceptance_preconditions_unmet: [
    'qualityConcept.finding.acceptance_preconditions_unmet',
    'A precondition of the acceptance is not met',
  ],
  precondition_not_reservable: [
    'qualityConcept.finding.precondition_not_reservable',
    'This open point cannot be carried as a reservation under the regime',
  ],
  preservation_acknowledged: [
    'qualityConcept.finding.preservation_acknowledged',
    'Survey {{ref}} has no acknowledgment from the owner',
  ],
  preservation_after_unpaired: [
    'qualityConcept.finding.preservation_after_unpaired',
    'After survey {{ref}} is not paired with a before survey',
  ],
  preservation_missing_before_start: [
    'qualityConcept.finding.preservation_missing_before_start',
    'Subject {{ref}} has no before survey ahead of the works',
  ],
  certification_target_at_risk: [
    'qualityConcept.finding.certification_target_at_risk',
    'The targeted credits no longer reach the target level',
  ],
  acceptance_unit_total_missing: [
    'qualityConcept.finding.acceptance_unit_total_missing',
    'No acceptance of the whole works is planned',
  ],
  acceptance_unit_handover_to_operation_missing: [
    'qualityConcept.finding.acceptance_unit_handover_to_operation_missing',
    'No handover to operation is planned',
  ],
  deemed_acceptance_due: [
    'qualityConcept.finding.deemed_acceptance_due',
    'Deemed acceptance may already have occurred. Check the dates',
  ],
  material_test_frequency_short: [
    'qualityConcept.finding.material_test_frequency_short',
    'Fewer passing tests than the placed quantity requires',
  ],
  placed_quantity_missing: [
    'qualityConcept.finding.placed_quantity_missing',
    'A proof is counted per quantity, but the placed quantity is not known',
  ],
};

export const PRECONDITION_REASON: KeyMap = {
  previous_stage_not_released: [
    'qualityConcept.reason.previous_stage_not_released',
    'The stage before it is not released yet',
  ],
  proofs_missing: ['qualityConcept.reason.proofs_missing', 'Proofs are still missing'],
  open_cx_issues: ['qualityConcept.reason.open_cx_issues', 'There are open commissioning issues'],
  hold_gates_open: ['qualityConcept.reason.hold_gates_open', 'Hold points are still open'],
  fact_unavailable: ['qualityConcept.reason.fact_unavailable', 'No record answers this yet'],
  plant_item_delivered_not_met: [
    'qualityConcept.reason.plant_item_delivered_not_met',
    'The equipment is not delivered yet',
  ],
  delivery_limit_agreed_not_met: [
    'qualityConcept.reason.delivery_limit_agreed_not_met',
    'The delivery limits are not agreed yet',
  ],
  authority_acceptance_missing: [
    'qualityConcept.reason.authority_acceptance_missing',
    'No authority acceptance is on file',
  ],
  systems_not_released: ['qualityConcept.reason.systems_not_released', 'A system it depends on is not released'],
  slots_missing: ['qualityConcept.reason.slots_missing', 'Handover documents are still missing'],
  unknown_predicate: ['qualityConcept.reason.unknown_predicate', 'This check is not known'],
  no_plant_item_linked: ['qualityConcept.reason.no_plant_item_linked', 'No equipment is linked to this system'],
  no_plant_register: ['qualityConcept.reason.no_plant_register', 'No equipment register is installed'],
};

export const REVIEW_STATUS: KeyMap = {
  unconfirmed: ['qualityConcept.review.unconfirmed', 'Not yet confirmed by a specialist'],
  verified: ['qualityConcept.review.verified', 'Confirmed'],
};

export const PACKAGE_PROBLEM: KeyMap = {
  ref_required: ['qualityConcept.packages.problem_ref_required', 'Every package needs a reference'],
  ref_duplicate: ['qualityConcept.packages.problem_ref_duplicate', 'A package reference appears twice'],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const EXPERT_TRIGGER: KeyMap = {
  before_start: ['quality_concept.vocab.expert_trigger.before_start', 'Before work starts'],
  before_concreting: ['quality_concept.vocab.expert_trigger.before_concreting', 'Before concreting'],
  before_concealment: ['quality_concept.vocab.expert_trigger.before_concealment', 'Before the work is covered up'],
  after_installation: ['quality_concept.vocab.expert_trigger.after_installation', 'After installation'],
  before_commissioning: ['quality_concept.vocab.expert_trigger.before_commissioning', 'Before commissioning'],
  before_acceptance: ['quality_concept.vocab.expert_trigger.before_acceptance', 'Before acceptance'],
  on_defect: ['quality_concept.vocab.expert_trigger.on_defect', 'When a defect is found'],
  on_change: ['quality_concept.vocab.expert_trigger.on_change', 'When the design changes'],
  periodic: ['quality_concept.vocab.expert_trigger.periodic', 'At regular intervals'],
};

export const EXPERT_FREQUENCY: KeyMap = {
  once: ['quality_concept.vocab.expert_frequency.once', 'Once'],
  per_floor: ['quality_concept.vocab.expert_frequency.per_floor', 'Per floor'],
  per_section: ['quality_concept.vocab.expert_frequency.per_section', 'Per section'],
  per_package: ['quality_concept.vocab.expert_frequency.per_package', 'Per contract package'],
  weekly: ['quality_concept.vocab.expert_frequency.weekly', 'Weekly'],
  monthly: ['quality_concept.vocab.expert_frequency.monthly', 'Monthly'],
  quarterly: ['quality_concept.vocab.expert_frequency.quarterly', 'Quarterly'],
  on_event: ['quality_concept.vocab.expert_frequency.on_event', 'On each occurrence'],
};

/** Why the server keeps the submit button closed. */
export const SUBMIT_REASON: KeyMap = {
  manage_required: [
    'qualityConcept.submitReason.manage_required',
    'Only a manager or the owner of the quality area can submit the concept.',
  ],
  concept_incomplete: [
    'qualityConcept.concept.next_incomplete',
    'Clear the open points below, then submit the concept for approval.',
  ],
  invalid_transition: [
    'qualityConcept.submitReason.invalid_transition',
    'The concept cannot be submitted in its current state.',
  ],
};

export const ALL_KEY_MAPS: Record<string, KeyMap> = {
  SUBMIT_REASON,
  EXPERT_TRIGGER,
  EXPERT_FREQUENCY,
  CONCEPT_STATE,
  CERTIFICATION_STATE,
  CERTIFICATION_ACTION,
  CERTIFICATION_SCOPE,
  CREDIT_STATE,
  CREDIT_ACTION,
  PROOF_STATE,
  PROOF_ACTION,
  DELIVERER_ROLE,
  REQUIRED_BY_KIND,
  MANDATE,
  VERIFICATION_METHOD,
  STAGE_STATE,
  STAGE_ACTION,
  PARTY_ROLE,
  PRECONDITION,
  SEVERITY,
  ACCEPTANCE_STATE,
  ACCEPTANCE_ACTION,
  ACCEPTANCE_KIND,
  LEGAL_EFFECT,
  DEEMED_TRIGGER,
  UNMET_KIND,
  SURVEY_STATE,
  SURVEY_ACTION,
  SURVEY_PHASE,
  SURVEY_METHOD,
  INFLUENCE_TRIGGER,
  EXPERT_STATE,
  LINK_KIND,
  FACT_OUTCOME,
  FINDING,
  PRECONDITION_REASON,
  REVIEW_STATUS,
  PACKAGE_PROBLEM,
};

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab(t: TFn, map: KeyMap, code: string | null | undefined, params?: Record<string, unknown>): string {
  if (!code) return '';
  const entry = map[code];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1], ...params });
}

/** A code written for a reader: `pressure_test` becomes "Pressure test". Never a raw key. */
/** Why the governance gate cannot read the concept, each with what to do about it. */
export const GATE_DETAIL: Record<string, KeyText> = {
  quality_frame_document_missing: [
    'qualityConcept.gate.quality_frame_document_missing',
    'The governance gate cannot read this concept, because the project has no frame document for the quality concept. In project governance, add the quality concept to the frame documents of the project.',
  ],
  governance_catalogue_has_no_quality_area: [
    'qualityConcept.gate.governance_catalogue_has_no_quality_area',
    'The governance gate cannot read this concept, because the governance catalogue of the project has no quality area. Choose a governance catalogue that has one.',
  ],
  no_phase_enables_construction: [
    'qualityConcept.gate.no_phase_enables_construction',
    'The governance gate cannot read this concept, because no phase of the governance catalogue opens construction. Check the phases of the governance catalogue.',
  ],
};

/** Why a revision of the concept was kept. */
export const REVISION_REASON: Record<string, KeyText> = {
  submitted: ['qualityConcept.revisions.reason_submitted', 'Submitted for approval'],
  approved: ['qualityConcept.revisions.reason_approved', 'Approved'],
  reopened: ['qualityConcept.revisions.reason_reopened', 'Reopened'],
  change_request: ['qualityConcept.revisions.reason_change_request', 'Reopened by a change request'],
};

export const CATALOGUE_SOURCE: Record<string, KeyText> = {
  shipped: ['qualityConcept.catalogues.source_shipped', 'Shipped with the product'],
  tenant: ['qualityConcept.catalogues.source_tenant', 'Kept by your organisation'],
  pack: ['qualityConcept.catalogues.source_pack', 'From a country pack'],
};

export function humanizeCode(code: string): string {
  const words = code.replace(/^quality\./, '').replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * The name of a catalogue item: the key the catalogue names when the locale
 * has it, then the text the catalogue carries, then the code made readable.
 */
export function catalogueName(ctx: LabelContext, item: CatalogueItem | null | undefined, code?: string | null): string {
  if (item) {
    if (item.name_key && ctx.exists(item.name_key)) return ctx.t(item.name_key);
    if (item.labels) {
      const lang = ctx.language.split('-')[0] ?? 'en';
      const text = item.labels[ctx.language] ?? item.labels[lang] ?? item.labels.en ?? Object.values(item.labels)[0];
      if (text) return text;
    }
    return humanizeCode(item.code);
  }
  return code ? humanizeCode(code) : '';
}

/** Find a catalogue item by code and name it; the code alone still reads as words. */
export function nameIn(ctx: LabelContext, list: CatalogueItem[] | undefined, code: string | null | undefined): string {
  if (!code) return '';
  return catalogueName(ctx, list?.find((i) => i.code === code), code);
}

/** A stored value that is a code of the vocabulary, or free text an older record still holds. */
export function vocabOrRaw(t: TFn, map: KeyMap, value: string | null | undefined): string {
  if (!value) return '';
  const entry = map[value];
  return entry ? t(entry[0], { defaultValue: entry[1] }) : value;
}

/**
 * Button props from the capability flags of a record: closed when the server
 * says so, with its reason as the tooltip. The reason is the error code the
 * route would answer, so it reads through the same message key.
 */
export function gate(
  t: TFn,
  row: Capable | null | undefined,
  action: string,
  fallback = true,
): { disabled: boolean; title?: string } {
  const key = canKey(action);
  const reason = whyNot(row, key);
  return {
    disabled: !may(row, key, fallback),
    title: reason ? t(`quality_concept.errors.${reason}`, { defaultValue: humanizeCode(reason) }) : undefined,
  };
}

/** The sentence for a finding. */
export function findingText(t: TFn, code: string, ref?: string): string {
  return vocab(t, FINDING, code, { ref: ref ?? '' });
}

/**
 * What to tell the reader when the server refused. The server sends the key
 * and its own sentence in the reader's language; the key wins when the locale
 * has it, the sentence otherwise, and a failure without a structured body
 * falls back to the shared error text.
 */
export function refusalText(t: TFn, err: unknown): string {
  const detail = refusalDetail(err);
  if (detail?.messageKey) {
    const said = t(detail.messageKey, { defaultValue: detail.message ?? humanizeCode(detail.code ?? '') });
    // A refusal passed on from another module carries that module's own sentence; without it the reader learns nothing.
    return detail.detail
      ? t('qualityConcept.refusal.with_detail', { defaultValue: '{{message}} Details: {{detail}}', message: said, detail: detail.detail })
      : said;
  }
  if (detail?.message) return detail.message;
  if (err instanceof ApiError || err instanceof Error) return getErrorMessage(err);
  return t('qualityConcept.refusal.unknown', { defaultValue: 'The action could not be completed.' });
}
