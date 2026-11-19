// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
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
  address?: EntityAddress | null;
  is_active: boolean;
  warnings: LegalEntityIssue[];
}

export interface EntityAddress {
  line1?: string;
  line2?: string;
  postcode?: string;
  city?: string;
}

export interface EntityBank {
  holder?: string;
  iban?: string;
  bic?: string;
  bank_name?: string;
}

export interface TaxIdValue {
  scheme: string;
  value: string;
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
  legal_name: string | null;
  address: EntityAddress | null;
  tax_ids: TaxIdValue[];
  invoice_prefix: string | null;
  default_signatory?: string | null;
  bank?: EntityBank | null;
  /** PNG, JPEG or WebP data URL printed on this company's documents. */
  logo_data_url?: string | null;
  is_default: boolean;
  is_active: boolean;
  metadata: Record<string, unknown>;
  branches: Branch[];
  created_at: string;
  updated_at: string;
  primary_tax_id: string;
  project_count: number;
  member_count: number;
  has_own_einvoice_settings: boolean;
  warnings: LegalEntityIssue[];
}

export interface LegalEntityInput {
  code: string;
  name: string;
  country_code: string;
  subdivision_code?: string | null;
  functional_currency: string;
  registration_number?: string | null;
  tax_id?: string | null;
  legal_name?: string | null;
  address?: EntityAddress | null;
  tax_ids?: TaxIdValue[];
  invoice_prefix?: string | null;
  default_signatory?: string | null;
  bank?: EntityBank | null;
  /** PNG, JPEG or WebP data URL printed on this company's documents. */
  logo_data_url?: string | null;
  is_default?: boolean;
  is_active?: boolean;
}

export interface BranchInput {
  code: string;
  name: string;
  country_code?: string | null;
  subdivision_code?: string | null;
  address?: EntityAddress | null;
}

export interface ProjectEntity {
  project_id: string;
  legal_entity: LegalEntity | null;
  /** `assigned` when the project names it, `default` when the default answers, `none` otherwise. */
  source: 'assigned' | 'default' | 'none';
  legal_entity_branch_id: string | null;
  /** Outgoing invoices past draft; moving the project to another company leaves them behind. */
  issued_invoice_count: number;
  warnings: LegalEntityIssue[];
}

export interface TaxScheme {
  scheme: string;
  pattern: string | null;
  example: string;
  mandatory_on_invoice: boolean;
  legal_reference: string;
}

export type MemberRole = 'viewer' | 'member' | 'admin';

export interface EntityMember {
  id: string;
  legal_entity_id: string;
  user_id: string;
  role: MemberRole;
  email: string;
  full_name: string;
}

export interface EntitiesUiState {
  active_entity_count: number;
  /** Company pickers and filters appear only from two active companies. */
  multi_company: boolean;
  my_entity_ids: string[];
  default_entity_id: string | null;
}

export interface ProjectSeller {
  project_id: string;
  source: 'entity_settings' | 'entity' | 'default' | 'company_profile' | 'none';
  legal_entity_id: string | null;
  legal_entity_code: string | null;
  seller: Record<string, string>;
  complete: boolean;
  missing: string[];
  issues: LegalEntityIssue[];
}

export const LEGAL_ENTITIES_KEY = ['legal-entities'] as const;
export const LEGAL_ENTITIES_UI_KEY = ['legal-entities', 'ui-state'] as const;

/** The company a project belongs to when it names none: the default one. */
export function effectiveEntityId(
  project: { legal_entity_id?: string | null },
  defaultEntityId: string | null | undefined,
): string | null {
  return project.legal_entity_id ?? defaultEntityId ?? null;
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
  assignProject: (projectId: string, legalEntityId: string | null, branchId: string | null = null) =>
    apiPut<ProjectEntity, { legal_entity_id: string | null; legal_entity_branch_id: string | null }>(
      `${BASE}/projects/${projectId}/entity`,
      { legal_entity_id: legalEntityId, legal_entity_branch_id: branchId },
    ),
  updateBranch: (entityId: string, branchId: string, body: Partial<BranchInput> & { is_active?: boolean }) =>
    apiPatch<Branch, Partial<BranchInput> & { is_active?: boolean }>(
      `${BASE}/entities/${entityId}/branches/${branchId}`,
      body,
    ),
  uiState: () => apiGet<EntitiesUiState>(`${BASE}/ui-state`),
  taxSchemes: (countryCode: string) =>
    apiGet<{ country_code: string; schemes: TaxScheme[] }>(
      `${BASE}/tax-schemes/${encodeURIComponent(countryCode || 'ZZ')}`,
    ),
  members: (entityId: string) =>
    apiGet<{ items: EntityMember[]; any_members: boolean }>(`${BASE}/entities/${entityId}/members/`),
  addMember: (entityId: string, userId: string, role: MemberRole = 'member') =>
    apiPost<EntityMember, { user_id: string; role: MemberRole }>(`${BASE}/entities/${entityId}/members/`, {
      user_id: userId,
      role,
    }),
  updateMember: (entityId: string, memberId: string, role: MemberRole) =>
    apiPatch<EntityMember, { role: MemberRole }>(`${BASE}/entities/${entityId}/members/${memberId}`, { role }),
  removeMember: (entityId: string, memberId: string) =>
    apiDelete(`${BASE}/entities/${entityId}/members/${memberId}`),
  projectSeller: (projectId: string) => apiGet<ProjectSeller>(`${BASE}/projects/${projectId}/seller`),
};
