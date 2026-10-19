// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Defects Liability module.
 *
 * Post-handover warranty / defects-liability-period (DLP) governance: the
 * per-project register of warranty / DLP entries, the defect notices raised
 * against them, and the derived register rollup plus retention-release
 * readiness view (the money signal: which entries have finished their DLP
 * clean and are clear for the final retention).
 *
 * Every endpoint is project-scoped IN THE PATH, mounted under
 * `/api/v1/defects-liability/projects/{projectId}/...` (the DB table prefix is
 * `oe_dlp_` but the route name is `defects-liability`). The filter helpers below
 * mirror the server-side query params, though the page filters client-side over
 * a full project fetch so the defect -> warranty reference map is always complete.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* -- Vocabularies (in lock-step with backend register.py) ------------------ */

export type WarrantyType =
  | 'workmanship'
  | 'manufacturer'
  | 'latent_defect'
  | 'extended'
  | 'other';

export type WarrantyStatus = 'in_dlp' | 'expiring' | 'expired' | 'closed' | 'on_hold';

export type DefectStatus = 'open' | 'rectifying' | 'rectified' | 'rejected' | 'closed';

export type DefectSeverity = 'minor' | 'major' | 'critical';

export const WARRANTY_TYPES: WarrantyType[] = [
  'workmanship',
  'manufacturer',
  'latent_defect',
  'extended',
  'other',
];

export const WARRANTY_STATUSES: WarrantyStatus[] = [
  'in_dlp',
  'expiring',
  'expired',
  'closed',
  'on_hold',
];

export const DEFECT_STATUSES: DefectStatus[] = [
  'open',
  'rectifying',
  'rectified',
  'rejected',
  'closed',
];

export const DEFECT_SEVERITIES: DefectSeverity[] = ['minor', 'major', 'critical'];

/* -- Limitation regime (opt-in) -------------------------------------------- */

/**
 * The legal regime a warranty period was derived from. Never set unless somebody
 * chooses one: `null` is the state every entry starts in and the state it stays
 * in for a team whose legal system has no such regime.
 */
export type LimitationRegime =
  | 'de_vob_b'
  | 'de_bgb'
  | 'eg_civil_651'
  | 'fr_civil_1792_6'
  | 'fr_civil_1792_3'
  | 'fr_civil_1792'
  | 'sa_sbc_decennial';

/**
 * The shipped regimes, in lock-step with `ALL_LIMITATION_REGIMES` in the backend
 * module `app/modules/defects_liability/limitation.py`.
 *
 * `statute` is a legal citation, not prose: it reads the same in every language
 * and is deliberately not translated. The sentence around it is composed from
 * locale keys, so a German reader gets German around a citation that is German
 * already. `months` is duplicated here only so the form can show the date a
 * choice produces before the save; the server derives it again and the server's
 * answer is the one that is stored.
 */
export const LIMITATION_REGIMES: {
  code: LimitationRegime;
  months: number;
  statute: string;
  /** Badge-length form of the same citation. A proper name, so never translated. */
  short: string;
}[] = [
  { code: 'de_vob_b', months: 48, statute: 'VOB/B § 13 Abs. 4', short: 'VOB/B' },
  { code: 'de_bgb', months: 60, statute: 'BGB § 634a Abs. 1 Nr. 2', short: 'BGB' },
  { code: 'eg_civil_651', months: 120, statute: 'Egyptian Civil Code Art. 651', short: 'EG CC 651' },
  { code: 'fr_civil_1792_6', months: 12, statute: 'Code civil art. 1792-6', short: 'C. civ. 1792-6' },
  { code: 'fr_civil_1792_3', months: 24, statute: 'Code civil art. 1792-3', short: 'C. civ. 1792-3' },
  { code: 'fr_civil_1792', months: 120, statute: 'Code civil art. 1792', short: 'C. civ. 1792' },
  { code: 'sa_sbc_decennial', months: 120, statute: 'Saudi Building Code Application Law Art. 29', short: 'SA SBC 29' },
];

/** The shipped regime with this code, or undefined for none / an unknown one. */
export function limitationRegime(code: string | null | undefined) {
  if (!code) return undefined;
  return LIMITATION_REGIMES.find((r) => r.code === code);
}

/**
 * The day a period of `months` months starting on `startIso` runs out.
 *
 * Counted the way § 188 Abs. 2 BGB counts: the day of the final month whose
 * number matches the start day, clamped to the last day of that month where it
 * has no such day (§ 188 Abs. 3). Returns `''` when there is no start date,
 * because a period counted from nothing is the one thing this must never show.
 */
export function limitationEndDate(startIso: string, months: number): string {
  if (!startIso) return '';
  const [y, m, d] = startIso.split('-').map(Number);
  if (!y || !m || !d) return '';
  const total = m - 1 + months;
  const year = y + Math.floor(total / 12);
  const month = (total % 12) + 1;
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const day = Math.min(d, lastDay);
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

/* -- Entity types ---------------------------------------------------------- */

/** A warranty / DLP entry (WarrantyResponse). Dates are ISO `YYYY-MM-DD`. */
export interface Warranty {
  id: string;
  project_id: string;
  reference: string;
  title: string;
  element_description: string | null;
  subcontractor_id: string | null;
  subcontractor_name: string | null;
  work_package: string | null;
  warranty_type: WarrantyType | null;
  handover_date: string | null;
  warranty_start_date: string | null;
  warranty_months: number | null;
  warranty_end_date: string | null;
  /** The legal regime the period came from, or null when nobody chose one. */
  limitation_regime: LimitationRegime | null;
  /** Server-derived, all null while `limitation_regime` is null. */
  limitation_statute: string | null;
  limitation_months: number | null;
  limitation_end_date: string | null;
  dlp_end_date: string | null;
  status: WarrantyStatus;
  retention_release_date: string | null;
  contract_id: string | null;
  document_id: string | null;
  sort_order: number;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** WarrantyCreate payload. `reference` and `title` are required by the server. */
export interface WarrantyCreate {
  reference: string;
  title: string;
  element_description?: string | null;
  subcontractor_name?: string | null;
  work_package?: string | null;
  warranty_type?: WarrantyType | null;
  handover_date?: string | null;
  warranty_start_date?: string | null;
  warranty_months?: number | null;
  warranty_end_date?: string | null;
  limitation_regime?: LimitationRegime | null;
  dlp_end_date?: string | null;
  status?: WarrantyStatus;
  retention_release_date?: string | null;
  sort_order?: number;
  notes?: string | null;
}

/** WarrantyUpdate payload: only provided fields change (null clears). */
export type WarrantyUpdate = Partial<WarrantyCreate>;

/** A defect notice (DefectResponse). */
export interface Defect {
  id: string;
  project_id: string;
  warranty_id: string;
  reference: string;
  description: string;
  severity: DefectSeverity | null;
  raised_date: string | null;
  due_date: string | null;
  status: DefectStatus;
  rectified_date: string | null;
  responsible_party: string | null;
  punchlist_id: string | null;
  ncr_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** DefectCreate payload. `reference` and `description` are required. */
export interface DefectCreate {
  reference: string;
  description: string;
  severity?: DefectSeverity | null;
  raised_date?: string | null;
  due_date?: string | null;
  status?: DefectStatus;
  rectified_date?: string | null;
  responsible_party?: string | null;
}

/** DefectUpdate payload: only provided fields change (null clears). */
export type DefectUpdate = Partial<DefectCreate>;

/* -- Derived register views ------------------------------------------------ */

/** Lightweight reference to an entry, used in expiring / ready lists. */
export interface WarrantyRef {
  warranty_id: string | null;
  reference: string;
  title: string;
  status: string;
  subcontractor_name: string | null;
  work_package: string | null;
  warranty_type: string | null;
  dlp_end_date: string | null;
  warranty_end_date: string | null;
  open_defect_count: number;
  retention_release_ready: boolean;
}

/** One overdue defect carrying its owning warranty's identity. */
export interface OverdueDefectRef {
  warranty_id: string | null;
  warranty_reference: string;
  title: string;
  severity: string | null;
  status: string;
  due_date: string | null;
}

/** Post-handover DLP health rollup for one subcontractor. */
export interface SubcontractorDlpHealth {
  subcontractor: string;
  total: number;
  open_defects: number;
  overdue_defects: number;
  /** Percentage as a plain decimal string (e.g. "100.00"), or null when undefined. */
  health_score: string | null;
}

/** The full defects-liability register rollup (DlpRegisterResponse). */
export interface DlpRegister {
  project_id: string;
  as_of: string;
  horizon_days: number;
  total: number;
  per_status: Record<string, number>;
  per_warranty_type: Record<string, number>;
  total_open_defects: number;
  /** Percentage as a plain decimal string, or null when the register is empty. */
  overall_health_score: string | null;
  is_clean: boolean;
  expiring: WarrantyRef[];
  expired: WarrantyRef[];
  overdue_defects: OverdueDefectRef[];
  retention_release_ready: WarrantyRef[];
  subcontractors: SubcontractorDlpHealth[];
}

/** The entries clear for final retention release (RetentionReleaseReadinessResponse). */
export interface RetentionReleaseReadiness {
  project_id: string;
  as_of: string;
  total: number;
  ready_count: number;
  ready: WarrantyRef[];
}

/**
 * One finding about an entry that named a limitation regime.
 *
 * `message` and `suggestion` are English, which is the platform's convention for
 * validation-rule prose. `details` carries the same finding as named values, so
 * the page composes the sentence from locale keys and shows the English only
 * when it meets a rule it does not know.
 */
export interface LimitationFinding {
  rule_id: string;
  rule_name: string;
  severity: string;
  warranty_id: string;
  reference: string;
  title: string;
  message: string;
  suggestion: string | null;
  details: {
    statute?: string;
    limitation_regime?: string;
    statutory_months?: number;
    recorded_months?: number;
    statutory_end_date?: string;
    recorded_end_date?: string;
    difference_days?: number;
  };
}

/**
 * What the limitation rules found (LimitationReviewResponse).
 *
 * `reviewed_count` counts the entries that named a regime, which is the number
 * the rules looked at. A register where nobody chose one reviews nothing, so the
 * page never asks for this at all.
 */
export interface LimitationReview {
  project_id: string;
  total: number;
  reviewed_count: number;
  regimes_in_use: LimitationRegime[];
  findings: LimitationFinding[];
}

/* -- API functions --------------------------------------------------------- */

const BASE = '/v1/defects-liability';

/** List a project's warranty / DLP entries (optionally filtered server-side). */
export async function fetchWarranties(
  projectId: string,
  filters?: { status?: WarrantyStatus; warranty_type?: WarrantyType; work_package?: string },
): Promise<Warranty[]> {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.warranty_type) params.set('warranty_type', filters.warranty_type);
  if (filters?.work_package) params.set('work_package', filters.work_package);
  const qs = params.toString();
  return apiGet<Warranty[]>(`${BASE}/projects/${projectId}/warranties${qs ? `?${qs}` : ''}`);
}

/** Create a warranty / DLP entry on a project. */
export async function createWarranty(
  projectId: string,
  payload: WarrantyCreate,
): Promise<Warranty> {
  return apiPost<Warranty, WarrantyCreate>(
    `${BASE}/projects/${projectId}/warranties`,
    payload,
  );
}

/** Patch a warranty / DLP entry (only provided fields change). */
export async function updateWarranty(
  projectId: string,
  warrantyId: string,
  payload: WarrantyUpdate,
): Promise<Warranty> {
  return apiPatch<Warranty, WarrantyUpdate>(
    `${BASE}/projects/${projectId}/warranties/${warrantyId}`,
    payload,
  );
}

/** Delete a warranty / DLP entry and its defects. */
export async function deleteWarranty(projectId: string, warrantyId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/projects/${projectId}/warranties/${warrantyId}`);
}

/** List a project's defect notices (optionally filtered server-side). */
export async function fetchDefects(
  projectId: string,
  filters?: { warranty_id?: string; status?: DefectStatus; severity?: DefectSeverity },
): Promise<Defect[]> {
  const params = new URLSearchParams();
  if (filters?.warranty_id) params.set('warranty_id', filters.warranty_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.severity) params.set('severity', filters.severity);
  const qs = params.toString();
  return apiGet<Defect[]>(`${BASE}/projects/${projectId}/defects${qs ? `?${qs}` : ''}`);
}

/** Raise a defect notice against a warranty (warranty is taken from the path). */
export async function createDefect(
  projectId: string,
  warrantyId: string,
  payload: DefectCreate,
): Promise<Defect> {
  return apiPost<Defect, DefectCreate>(
    `${BASE}/projects/${projectId}/warranties/${warrantyId}/defects`,
    payload,
  );
}

/** Patch (or close) a defect notice (only provided fields change). */
export async function updateDefect(
  projectId: string,
  defectId: string,
  payload: DefectUpdate,
): Promise<Defect> {
  return apiPatch<Defect, DefectUpdate>(
    `${BASE}/projects/${projectId}/defects/${defectId}`,
    payload,
  );
}

/** Full defects-liability register rollup: counts, expiry, defect load, health. */
export async function fetchRegister(
  projectId: string,
  params?: { as_of?: string; horizon_days?: number },
): Promise<DlpRegister> {
  const q = new URLSearchParams();
  if (params?.as_of) q.set('as_of', params.as_of);
  if (params?.horizon_days != null) q.set('horizon_days', String(params.horizon_days));
  const qs = q.toString();
  return apiGet<DlpRegister>(`${BASE}/projects/${projectId}/register${qs ? `?${qs}` : ''}`);
}

/** Entries whose DLP has ended clean, clear for final retention release. */
export async function fetchRetentionReadiness(
  projectId: string,
  asOf?: string,
): Promise<RetentionReleaseReadiness> {
  const q = new URLSearchParams();
  if (asOf) q.set('as_of', asOf);
  const qs = q.toString();
  return apiGet<RetentionReleaseReadiness>(
    `${BASE}/projects/${projectId}/retention-release-readiness${qs ? `?${qs}` : ''}`,
  );
}

/**
 * Where a recorded period disagrees with the legal regime it names.
 *
 * Only meaningful once at least one entry names a regime; the page keeps the
 * query disabled until then, so a register that never opted in never sends this
 * request.
 */
export async function fetchLimitationReview(projectId: string): Promise<LimitationReview> {
  return apiGet<LimitationReview>(`${BASE}/projects/${projectId}/limitation-review`);
}
