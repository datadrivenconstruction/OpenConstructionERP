// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the staffing screens show for a code: the closed vocabularies
// (plan, position, assignment, file, travel and leave states), the names of
// catalogue items (roles, organisations, document kinds, leave types) and the
// sentences for refusals and findings. The vocabularies are written as key
// maps rather than built from the code at runtime, so the key test can
// enumerate them and a translator can find every key by grep.

import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate } from '@/shared/lib/formatters';

import {
  staffingErrorCode,
  staffingErrorInfo,
  staffingErrorMessage,
  type CellState,
  type EmploymentBasis,
  type FileStatus,
  type FillStatus,
  type Finding,
  type FitForRole,
  type HandoverStatus,
  type Labelled,
  type LawfulBasis,
  type LeaveStatus,
  type Can,
  type Phase,
  type PlanStatus,
  type Position,
  type PositionStatus,
  type RecruitingChannel,
  type StaffingCatalogue,
  type StaffingLabel,
  type TravelKind,
  type TravelStatus,
} from './api';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const PLAN_STATUS: Record<PlanStatus, KeyText> = {
  draft: ['staffing.plan.status.draft', 'Draft'],
  in_review: ['staffing.plan.status.in_review', 'In review'],
  approved: ['staffing.plan.status.approved', 'Approved'],
  binding: ['staffing.plan.status.binding', 'Binding'],
  revising: ['staffing.plan.status.revising', 'Reopened'],
};

export const POSITION_STATUS: Record<PositionStatus, KeyText> = {
  open: ['staffing.position_status.open', 'Open'],
  recruiting: ['staffing.position_status.recruiting', 'Recruiting'],
  filled: ['staffing.position_status.filled', 'Filled'],
  on_hold: ['staffing.position_status.on_hold', 'On hold'],
  cancelled: ['staffing.position_status.cancelled', 'Cancelled'],
};

export const FILL_STATUS: Record<FillStatus, KeyText> = {
  proposed: ['staffing.fill.status.proposed', 'Proposed'],
  confirmed: ['staffing.fill.status.confirmed', 'Confirmed'],
  ended: ['staffing.fill.status.ended', 'Ended'],
};

export const HANDOVER_STATUS: Record<HandoverStatus, KeyText> = {
  planned: ['staffing.handover.status.planned', 'Planned'],
  done: ['staffing.handover.status.done', 'Done'],
};

export const FILE_STATUS: Record<FileStatus, KeyText> = {
  active: ['staffing.file.status.active', 'Active'],
  ended: ['staffing.file.status.ended', 'Ended'],
  retention_hold: ['staffing.file.status.retention_hold', 'On hold'],
  anonymised: ['staffing.file.status.anonymised', 'Anonymised'],
};

/** Names for the phases the shipped catalogues use. Any other phase code shows humanised. */
export const PHASE: Record<Phase, KeyText> = {
  development: ['staffing.phase.development', 'Development'],
  execution: ['staffing.phase.execution', 'Execution'],
  operation: ['staffing.phase.operation', 'Operation'],
};

export const RECRUITING_CHANNEL: Record<RecruitingChannel, KeyText> = {
  internal: ['staffing.recruiting_channel.internal', 'Internal'],
  agency: ['staffing.recruiting_channel.agency', 'Agency'],
  direct: ['staffing.recruiting_channel.direct', 'Direct hire'],
  framework: ['staffing.recruiting_channel.framework', 'Framework agreement'],
  consultant_contract: ['staffing.recruiting_channel.consultant_contract', 'Consultant contract'],
};

export const EMPLOYMENT_BASIS: Record<EmploymentBasis, KeyText> = {
  employee: ['staffing.employment_basis.employee', 'Employee'],
  posted_worker: ['staffing.employment_basis.posted_worker', 'Posted worker'],
  contractor_staff: ['staffing.employment_basis.contractor_staff', 'Contractor staff'],
  consultant: ['staffing.employment_basis.consultant', 'Consultant'],
  agency: ['staffing.employment_basis.agency', 'Agency worker'],
};

export const LAWFUL_BASIS: Record<LawfulBasis, KeyText> = {
  contract: ['staffing.lawful_basis.contract', 'Contract'],
  legal_obligation: ['staffing.lawful_basis.legal_obligation', 'Legal obligation'],
  legitimate_interest: ['staffing.lawful_basis.legitimate_interest', 'Legitimate interest'],
};

export const FIT: Record<FitForRole, KeyText> = {
  yes: ['staffing.fit.yes', 'Fit'],
  with_restrictions: ['staffing.fit.with_restrictions', 'Fit with restrictions'],
  no: ['staffing.fit.no', 'Not fit'],
};

export const TRAVEL_KIND: Record<TravelKind, KeyText> = {
  mobilisation: ['staffing.travel.kind.mobilisation', 'Mobilisation'],
  rotation: ['staffing.travel.kind.rotation', 'Rotation'],
  business: ['staffing.travel.kind.business', 'Business trip'],
  demobilisation: ['staffing.travel.kind.demobilisation', 'Demobilisation'],
};

export const TRAVEL_STATUS: Record<TravelStatus, KeyText> = {
  planned: ['staffing.travel.status.planned', 'Planned'],
  booked: ['staffing.travel.status.booked', 'Booked'],
  done: ['staffing.travel.status.done', 'Done'],
  cancelled: ['staffing.travel.status.cancelled', 'Cancelled'],
};

export const LEAVE_STATUS: Record<LeaveStatus, KeyText> = {
  requested: ['staffing.leave.status.requested', 'Requested'],
  approved: ['staffing.leave.status.approved', 'Approved'],
  taken: ['staffing.leave.status.taken', 'Taken'],
  cancelled: ['staffing.leave.status.cancelled', 'Cancelled'],
};

export const CELL_STATE: Record<CellState, KeyText> = {
  valid: ['staffing.cell.valid', 'Valid'],
  expiring: ['staffing.cell.expiring', 'Expiring'],
  expired: ['staffing.cell.expired', 'Expired'],
  missing: ['staffing.cell.missing', 'Missing'],
  waived: ['staffing.cell.waived', 'Waived'],
  not_required: ['staffing.cell.not_required', 'Not required'],
};

/** The validity state of a recorded document, as the server reports it. */
export const DOCUMENT_STATUS: Record<string, KeyText> = {
  active: ['staffing.document.status.active', 'Valid'],
  expiring_soon: ['staffing.document.status.expiring_soon', 'Expiring soon'],
  expired: ['staffing.document.status.expired', 'Expired'],
  suspended: ['staffing.document.status.suspended', 'Suspended'],
  revoked: ['staffing.document.status.revoked', 'Revoked'],
};

/** What the access log records, in the reader's words. */
export const ACCESS_ACTION: Record<string, KeyText> = {
  'personnel_file.read': ['staffing.file.log.read', 'Opened the file'],
  file_created: ['staffing.file.log.created', 'Created the file'],
  file_updated: ['staffing.file.log.updated', 'Changed the file'],
  file_ended: ['staffing.file.log.ended', 'Ended the assignment'],
  file_held: ['staffing.file.log.held', 'Placed a hold'],
  file_released: ['staffing.file.log.released', 'Released the hold'],
  file_anonymised: ['staffing.file.log.anonymised', 'Erased the personal data'],
};

/** Every finding code the backend sends, as `staffing.findings.<code>`. `{{ref}}` is the role the finding is about. */
export const FINDING_TEXT: Record<string, KeyText> = {
  commissioning_date_missing: [
    'staffing.findings.commissioning_date_missing',
    'Set the commissioning date before planning operation roles.',
  ],
  demobilisation_missing: ['staffing.findings.demobilisation_missing', 'No return travel is planned.'],
  handover_missing: ['staffing.findings.handover_missing', 'Role {{ref}} needs a handover.'],
  key_role_missing: ['staffing.findings.key_role_missing', 'Key role {{ref}} has no position.'],
  key_role_not_filled_before_gate: [
    'staffing.findings.key_role_not_filled_before_gate',
    'Key role {{ref}} is not filled before its gate.',
  ],
  leave_conflicts_gate: [
    'staffing.findings.leave_conflicts_gate',
    'The leave overlaps a mobilisation or a key gate.',
  ],
  no_accommodation: ['staffing.findings.no_accommodation', 'No accommodation is booked for the start date.'],
  not_cleared_to_work: ['staffing.findings.not_cleared_to_work', 'This person is not cleared to work yet.'],
  operation_role_late: ['staffing.findings.operation_role_late', 'Operation role {{ref}} starts after commissioning.'],
  person_overallocated_across_projects: [
    'staffing.findings.person_overallocated_across_projects',
    'This person is planned above 1.0 FTE across projects.',
  ],
  travel_after_assignment: ['staffing.findings.travel_after_assignment', 'Travel starts after the assignment.'],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  PLAN_STATUS,
  POSITION_STATUS,
  FILL_STATUS,
  HANDOVER_STATUS,
  FILE_STATUS,
  PHASE,
  RECRUITING_CHANNEL,
  EMPLOYMENT_BASIS,
  LAWFUL_BASIS,
  FIT,
  TRAVEL_KIND,
  TRAVEL_STATUS,
  LEAVE_STATUS,
  CELL_STATE,
  DOCUMENT_STATUS,
  ACCESS_ACTION,
  FINDING_TEXT,
};

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab<T extends string>(t: TFn, map: Record<T, KeyText>, code: T | '' | null | undefined): string {
  if (!code) return '';
  const entry = map[code as T];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1] });
}

/**
 * A catalogue code written for a reader: `site_manager` becomes "Site manager".
 *
 * The last resort when neither the catalogue nor the locale names the item.
 * It is never a raw key, which is what a demo must not show.
 */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function fromTexts(texts: Record<string, string> | null | undefined, language: string): string {
  if (!texts) return '';
  const lang = language.split('-')[0] ?? 'en';
  return texts[language] ?? texts[lang] ?? texts.en ?? Object.values(texts)[0] ?? '';
}

export type CatalogueGroup = 'role' | 'organisation' | 'document_kind' | 'leave_type';

const GROUP_ITEMS: Record<CatalogueGroup, (c: StaffingCatalogue) => Labelled[]> = {
  role: (c) => c.roles,
  organisation: (c) => c.organisations,
  document_kind: (c) => c.document_kinds,
  leave_type: (c) => c.leave_types,
};

/**
 * The name of a catalogue item: the pinned catalogue's own label first (a
 * locale key for shipped catalogues, texts per language for tenant ones),
 * then the platform key for the code, then the code made readable.
 */
export function catalogueName(
  ctx: LabelContext,
  catalogue: StaffingCatalogue | null | undefined,
  group: CatalogueGroup,
  code: string | null | undefined,
): string {
  if (!code) return '';
  const item = catalogue ? GROUP_ITEMS[group](catalogue).find((i) => i.code === code) : undefined;
  if (item?.name_key && ctx.exists(item.name_key)) return ctx.t(item.name_key);
  const own = fromTexts(item?.labels, ctx.language);
  if (own) return own;
  const key = ['staffing', group, code].join('.');
  if (ctx.exists(key)) return ctx.t(key);
  return humanizeCode(code);
}

/** The name of a staffing catalogue in the catalogue picker. */
export function labelText(ctx: LabelContext, label: StaffingLabel | null | undefined, fallback: string): string {
  if (label?.key && ctx.exists(label.key)) return ctx.t(label.key);
  return fromTexts(label?.text, ctx.language) || humanizeCode(fallback);
}

/** What a position is called on screen: its own title, a custom role name, or the catalogue role. */
export function positionName(
  ctx: LabelContext,
  catalogue: StaffingCatalogue | null | undefined,
  position: Pick<Position, 'role_code' | 'custom_label' | 'title'>,
): string {
  if (position.title && position.title.trim()) return position.title.trim();
  if (position.custom_label && position.custom_label.trim()) return position.custom_label.trim();
  return catalogueName(ctx, catalogue, 'role', position.role_code);
}

/**
 * The sentence for a finding. The backend names the element by a role code or
 * by a position id with the role code beside it; the reader gets the role name.
 */
export function findingText(ctx: LabelContext, catalogue: StaffingCatalogue | null | undefined, finding: Finding): string {
  const roleCode = [finding.ref, finding.detail].find((c) => !!c && !!catalogue?.roles.some((r) => r.code === c));
  const ref = roleCode ? catalogueName(ctx, catalogue, 'role', roleCode) : humanizeCode(finding.detail || finding.ref);
  const entry = FINDING_TEXT[finding.code];
  if (entry) return ctx.t(entry[0], { defaultValue: entry[1], ref });
  return errorText(ctx.t, finding.code);
}

/**
 * Whether a control belongs on screen: the action is allowed, or the server says
 * it applies here and refuses this caller. Without that word from the server a
 * refused action stays off the screen.
 */
export function offered(can: Can | null | undefined): boolean {
  return !!can && (can.allowed || can.applies === true);
}

/** Why the server does not allow a capability, in the reader's language; empty when it is allowed. */
export function whyNot(t: TFn, can: Can | null | undefined): string {
  return can && !can.allowed && can.reason ? errorText(t, can.reason) : '';
}

/** The sentence for a refusal code, translated when the locale has it. */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  return t(['staffing', 'errors', code].join('.'), { defaultValue: serverMessage ?? humanizeCode(code) });
}

/**
 * Why the server refused, in the reader's language.
 *
 * A staffing refusal carries a code and the server's own sentence; anything
 * else (network, 500) falls back to the shared error reader. A refusal that
 * names a date, such as a retention duty still running, shows the date.
 */
export function refusalText(t: TFn, err: unknown): string {
  const code = staffingErrorCode(err);
  if (!code) return getErrorMessage(err);
  const sentence = errorText(t, code, staffingErrorMessage(err));
  const info = staffingErrorInfo(err);
  if (info && /^\d{4}-\d{2}-\d{2}/.test(info)) {
    return t('staffing.refusal_until', { defaultValue: '{{reason}} Until {{date}}.', reason: sentence, date: fmtDate(info) });
  }
  return sentence;
}
