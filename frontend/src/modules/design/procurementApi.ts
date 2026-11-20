// Design module (ERP side of the design editor link).
import { apiGet, apiPost } from '@/shared/lib/api';
import type { ProcurementImpact } from './data/procurement';

/** What accepting the revision would do to the design take-off. Writes nothing. */
export function fetchProcurementImpact(revisionId: string): Promise<ProcurementImpact> {
  return apiGet<ProcurementImpact>(`/v1/design/revisions/${revisionId}/procurement-impact`);
}

/** Create the take-off of a project and its tender packages (a project manager's act). */
export function setupProcurement(projectId: string, groupBy: 'type_key' | 'ifc_class'): Promise<{ procurement: boolean }> {
  return apiPost<{ procurement: boolean }, { group_by: string }>(`/v1/design/projects/${projectId}/procurement/setup`, {
    group_by: groupBy,
  });
}

export interface AddendumDraftState {
  revision_id: string; revision_number: number | null; addendum_id: string; revision_no: number | null;
  lines: number; sheets: number; elements: number;
  /** draft: waiting for a person in Tendering; published: sent by a person; missing: deleted there. */
  state: 'draft' | 'published' | 'missing';
}
export interface ProcurementPackage {
  ifc_class: string; package_id: string | null; name: string | null; status: string | null; missing: boolean;
  lines: number; url: string; addenda?: AddendumDraftState[];
}
export interface ProcurementSummary { procurement: boolean; packages?: ProcurementPackage[] }

/** The take-off as it stands: packages with the addendum drafts prepared for them. */
export function fetchProcurement(projectId: string): Promise<ProcurementSummary> {
  return apiGet<ProcurementSummary>(`/v1/design/projects/${projectId}/procurement`);
}
