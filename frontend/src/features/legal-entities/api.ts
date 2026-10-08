// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Legal entities API types and calls.
 *
 * The types mirror `backend/app/modules/legal_entities/schemas.py`.
 */

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';

const BASE = '/v1/legal-entities';

export interface LegalEntityIssue {
  rule_id: string;
  severity: 'error' | 'warning';
  field: string;
  message: string;
}

export interface Branch {
  id: string;
  legal_entity_id: string;
  code: string;
  name: string;
  country_code: string;
  subdivision_code: string | null;
  is_active: boolean;
  warnings: LegalEntityIssue[];
}

export interface LegalEntity {
  id: string;
  code: string;
  name: string;
  country_code: string;
  subdivision_code: string | null;
  functional_currency: string;
  registration_number: string | null;
  tax_id: string | null;
  is_default: boolean;
  is_active: boolean;
  metadata: Record<string, unknown>;
  branches: Branch[];
  created_at: string;
  updated_at: string;
}

export interface LegalEntityInput {
  code: string;
  name: string;
  country_code: string;
  subdivision_code?: string | null;
  functional_currency: string;
  registration_number?: string | null;
  tax_id?: string | null;
  is_default?: boolean;
  is_active?: boolean;
}

export interface BranchInput {
  code: string;
  name: string;
  country_code?: string | null;
  subdivision_code?: string | null;
}

export interface ProjectEntity {
  project_id: string;
  legal_entity: LegalEntity | null;
  /** `assigned` when the project names it, `default` when the default answers, `none` otherwise. */
  source: 'assigned' | 'default' | 'none';
}

export const legalEntitiesApi = {
  list: (includeInactive = true) =>
    apiGet<{ items: LegalEntity[]; total: number }>(
      `${BASE}/entities/?include_inactive=${includeInactive ? 'true' : 'false'}`,
    ),
  create: (body: LegalEntityInput) => apiPost<LegalEntity, LegalEntityInput>(`${BASE}/entities/`, body),
  update: (id: string, body: Partial<LegalEntityInput>) =>
    apiPatch<LegalEntity, Partial<LegalEntityInput>>(`${BASE}/entities/${id}`, body),
  remove: (id: string) => apiDelete(`${BASE}/entities/${id}`),
  addBranch: (entityId: string, body: BranchInput) =>
    apiPost<Branch, BranchInput>(`${BASE}/entities/${entityId}/branches/`, body),
  removeBranch: (entityId: string, branchId: string) =>
    apiDelete(`${BASE}/entities/${entityId}/branches/${branchId}`),
  projectEntity: (projectId: string) => apiGet<ProjectEntity>(`${BASE}/projects/${projectId}/entity`),
  assignProject: (projectId: string, legalEntityId: string | null) =>
    apiPut<ProjectEntity, { legal_entity_id: string | null }>(`${BASE}/projects/${projectId}/entity`, {
      legal_entity_id: legalEntityId,
    }),
};
