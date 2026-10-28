// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Compliance-docs API client.

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type {
  ComplianceDoc,
  ComplianceDocCreate,
  ComplianceDocUpdate,
} from './types';

const BASE = '/v1/compliance_docs';

export interface ListComplianceDocsParams {
  project_id: string;
  status?: string | null;
  doc_type?: string | null;
}

export async function listComplianceDocs(
  params: ListComplianceDocsParams,
): Promise<ComplianceDoc[]> {
  const q = new URLSearchParams({ project_id: params.project_id });
  if (params.status) q.set('status', params.status);
  if (params.doc_type) q.set('doc_type', params.doc_type);
  return apiGet<ComplianceDoc[]>(`${BASE}/?${q.toString()}`);
}

export async function listExpiringSoon(
  projectId: string,
  limit = 5,
): Promise<ComplianceDoc[]> {
  const q = new URLSearchParams({
    project_id: projectId,
    limit: String(limit),
  });
  return apiGet<ComplianceDoc[]>(`${BASE}/expiring-soon/?${q.toString()}`);
}

export async function getComplianceDoc(id: string): Promise<ComplianceDoc> {
  return apiGet<ComplianceDoc>(`${BASE}/${id}/`);
}

export async function createComplianceDoc(
  body: ComplianceDocCreate,
): Promise<ComplianceDoc> {
  return apiPost<ComplianceDoc, ComplianceDocCreate>(`${BASE}/`, body);
}

export async function updateComplianceDoc(
  id: string,
  body: ComplianceDocUpdate,
): Promise<ComplianceDoc> {
  return apiPatch<ComplianceDoc, ComplianceDocUpdate>(`${BASE}/${id}/`, body);
}

export async function deleteComplianceDoc(id: string): Promise<void> {
  return apiDelete(`${BASE}/${id}/`);
}
