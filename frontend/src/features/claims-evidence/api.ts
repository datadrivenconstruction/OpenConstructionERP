// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for the claims-evidence provability surface (#6). Grades how
// provable one change / claim is from the evidence already on the project and
// returns the 0-100 score, its band and the per-signal breakdown plus the cure
// list. Read-only; nothing is persisted server-side.

import { apiGet, apiPost, downloadWithAuth } from '@/shared/lib/api';
import { documentExportUrl, type DocumentFormat } from '@/shared/lib/documentExport';
import type { EvidencePack, ProvabilityScore } from './types';

const BASE = '/v1/claims-evidence';

// The change families a subject can be (mirrors the backend subject kinds).
export type SubjectKind =
  | 'change_order'
  | 'variation_notice'
  | 'variation_request'
  | 'variation_order'
  | 'moc_entry';

export function getChangeProvability(
  projectId: string,
  subjectKind: SubjectKind,
  subjectId: string,
): Promise<ProvabilityScore> {
  return apiGet<ProvabilityScore>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/changes/${encodeURIComponent(
      subjectKind,
    )}/${encodeURIComponent(subjectId)}/provability`,
  );
}

/**
 * Assemble the project-wide evidence pack: every change-family record plus the
 * recent cross-module activity, ordered, sectioned and SHA-256 digested by the
 * engine so the same project state always yields the same pack. `subjectRef` is
 * only the label the pack is filed under (it does not filter the contents) and
 * `basis` names why it is being assembled. Read-only; nothing is persisted.
 */
export function getEvidencePack(
  projectId: string,
  subjectRef: string,
  basis = 'dispute',
): Promise<EvidencePack> {
  const query = new URLSearchParams({ subject_ref: subjectRef || 'project', basis });
  return apiGet<EvidencePack>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/pack?${query.toString()}`,
  );
}

// The reconcilable record types a change thread can be grown from (mirrors the
// backend _RECONSTRUCT_KINDS). Deliberately distinct from SubjectKind: the
// reconciliation engine names these "notice" / "moc" where the provability
// surface uses "variation_notice" / "moc_entry", so a caller must map across.
export type ReconstructSubjectType =
  | 'change_order'
  | 'variation_request'
  | 'variation_order'
  | 'notice'
  | 'moc'
  | 'correspondence';

// Map a provability / dispute SubjectKind onto the reconciliation record type
// the reconstruct endpoint seeds from. Kept here so the difference between the
// two vocabularies lives in one place.
const RECONSTRUCT_TYPE_BY_KIND: Record<string, ReconstructSubjectType> = {
  change_order: 'change_order',
  variation_request: 'variation_request',
  variation_order: 'variation_order',
  variation_notice: 'notice',
  moc_entry: 'moc',
};

/**
 * The reconstruct subject type for a provability / dispute kind, or null when
 * the kind has no reconcilable mapping (so a caller can omit the panel rather
 * than call the endpoint with a type it would reject).
 */
export function reconstructTypeForKind(kind: string): ReconstructSubjectType | null {
  return RECONSTRUCT_TYPE_BY_KIND[kind] ?? null;
}

/**
 * Reconstruct one change as a scoped, deterministic evidence pack: the
 * reconciliation engine's connected component of records linked to the subject,
 * assembled and SHA-256 digested. Read-only; nothing is persisted server-side.
 */
export function reconstructChange(
  projectId: string,
  subjectType: ReconstructSubjectType,
  subjectId: string,
): Promise<EvidencePack> {
  return apiGet<EvidencePack>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/reconstruct/${encodeURIComponent(
      subjectType,
    )}/${encodeURIComponent(subjectId)}`,
  );
}

/**
 * Export a reconstructed evidence pack: the deliberate "assemble an evidence
 * pack" action. Returns the same deterministic pack the reconstruct GET produces,
 * and (when the pack is non-empty) records one activity-log row so the export
 * lands in the audit trail and counts toward guided adoption. Unlike the GET it
 * is only called on an explicit export, never on a browse.
 */
export function exportReconstructedPack(
  projectId: string,
  subjectType: ReconstructSubjectType,
  subjectId: string,
): Promise<EvidencePack> {
  return apiPost<EvidencePack, Record<string, never>>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/reconstruct/${encodeURIComponent(
      subjectType,
    )}/${encodeURIComponent(subjectId)}/export`,
    {},
  );
}

/* -- Printed documents ---------------------------------------------------- */

/**
 * Download the project-wide evidence pack as a printable PDF or a workbook
 * (GET /projects/{id}/pack/export/, trailing slash as the route declares it).
 * `subjectRef` and `basis` mean what they mean for `getEvidencePack`, so the
 * document is the pack the screen is showing.
 */
export function downloadEvidencePack(
  projectId: string,
  subjectRef: string,
  basis: string,
  format: DocumentFormat,
  locale: string,
): Promise<void> {
  return downloadWithAuth(
    documentExportUrl(`${BASE}/projects/${encodeURIComponent(projectId)}/pack/export/`, {
      subject_ref: subjectRef || 'project',
      basis,
      format,
      locale,
    }),
    `evidence-pack.${format}`,
  );
}

/**
 * Download one change's reconstructed evidence pack as a printable PDF or a
 * workbook (GET /projects/{id}/reconstruct/{type}/{id}/export/). A read: unlike
 * `exportReconstructedPack` it records nothing in the activity log.
 */
export function downloadReconstructedPack(
  projectId: string,
  subjectType: ReconstructSubjectType,
  subjectId: string,
  format: DocumentFormat,
  locale: string,
): Promise<void> {
  return downloadWithAuth(
    documentExportUrl(
      `${BASE}/projects/${encodeURIComponent(projectId)}/reconstruct/${encodeURIComponent(
        subjectType,
      )}/${encodeURIComponent(subjectId)}/export/`,
      { format, locale },
    ),
    `evidence-pack.${format}`,
  );
}
