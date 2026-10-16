// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for project parties and record shares.
 *
 * Backed by /api/v1/teams/project/{id}/parties and /records - see
 * backend/app/modules/teams/party_router.py.
 *
 * A party is a company on one project. Binding a member to a party other than
 * the project owner's makes them external: in the shared registers (RFI,
 * interfaces, correspondence, transmittals, submittals, file transmittals)
 * they see only what their company originated or what was shared with it.
 * Unbound members, the owner's company, the owner and system admins see
 * everything, so a project without parties behaves as before.
 */

import { apiGet, apiPost, apiPatch, apiPut, apiDelete } from '@/shared/lib/api';

const BASE = '/v1/teams';

export const PARTY_ROLES = ['owner', 'contractor', 'subcontractor', 'consultant', 'supplier'] as const;
export type PartyRole = (typeof PARTY_ROLES)[number];

export const SHARE_PERMISSIONS = ['view', 'contribute'] as const;
export type SharePermission = (typeof SHARE_PERMISSIONS)[number];

/** Register keys the backend scopes by party. Mirrors PARTY_SCOPED_REGISTERS. */
export type PartyEntityType =
  | 'rfi'
  | 'interface'
  | 'correspondence'
  | 'transmittal'
  | 'submittal'
  | 'file_transmittal';

export interface ProjectParty {
  id: string;
  project_id: string;
  name: string;
  role: PartyRole;
  legal_entity_id: string | null;
  contact_id: string | null;
  notes: string;
  is_active: boolean;
  is_host: boolean;
  member_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface PartyMember {
  user_id: string;
  party_id: string;
  party_name: string;
  full_name: string;
  email: string;
}

export interface PartyScope {
  project_id: string;
  restricted: boolean;
  party_id: string | null;
  party_name: string | null;
  is_host: boolean;
  has_parties: boolean;
  can_manage: boolean;
}

export interface RecordPartyRow {
  party_id: string;
  party_name: string;
  party_role: PartyRole;
  access: 'originator' | 'shared';
  permission: SharePermission;
  shared_by: string | null;
  shared_at: string | null;
}

export interface RecordParties {
  entity_type: PartyEntityType;
  entity_id: string;
  originator: RecordPartyRow | null;
  shares: RecordPartyRow[];
  can_share: boolean;
  can_set_originator: boolean;
}

export interface PartyPayload {
  name: string;
  role: PartyRole;
  notes?: string;
}

export async function listParties(projectId: string): Promise<ProjectParty[]> {
  return apiGet<ProjectParty[]>(`${BASE}/project/${projectId}/parties`);
}

export async function createParty(projectId: string, payload: PartyPayload): Promise<ProjectParty> {
  return apiPost<ProjectParty, PartyPayload>(`${BASE}/project/${projectId}/parties`, payload);
}

export async function updateParty(
  projectId: string,
  partyId: string,
  payload: Partial<PartyPayload> & { is_active?: boolean },
): Promise<ProjectParty> {
  return apiPatch<ProjectParty>(`${BASE}/project/${projectId}/parties/${partyId}`, payload);
}

export async function deleteParty(projectId: string, partyId: string): Promise<void> {
  await apiDelete(`${BASE}/project/${projectId}/parties/${partyId}`);
}

export async function getMyPartyScope(projectId: string): Promise<PartyScope> {
  return apiGet<PartyScope>(`${BASE}/project/${projectId}/parties/me`);
}

export async function listPartyMembers(projectId: string): Promise<PartyMember[]> {
  return apiGet<PartyMember[]>(`${BASE}/project/${projectId}/parties/members`);
}

export async function bindPartyMember(projectId: string, userId: string, partyId: string): Promise<PartyMember> {
  return apiPut<PartyMember>(`${BASE}/project/${projectId}/parties/members/${userId}`, { party_id: partyId });
}

export async function unbindPartyMember(projectId: string, userId: string): Promise<void> {
  await apiDelete(`${BASE}/project/${projectId}/parties/members/${userId}`);
}

function recordBase(projectId: string, entityType: PartyEntityType, entityId: string): string {
  return `${BASE}/project/${projectId}/records/${entityType}/${entityId}`;
}

export async function getRecordParties(
  projectId: string,
  entityType: PartyEntityType,
  entityId: string,
): Promise<RecordParties> {
  return apiGet<RecordParties>(`${recordBase(projectId, entityType, entityId)}/parties`);
}

export async function shareRecord(
  projectId: string,
  entityType: PartyEntityType,
  entityId: string,
  partyId: string,
  permission: SharePermission,
): Promise<RecordParties> {
  return apiPost<RecordParties>(`${recordBase(projectId, entityType, entityId)}/shares`, {
    party_id: partyId,
    permission,
  });
}

export async function revokeRecordShare(
  projectId: string,
  entityType: PartyEntityType,
  entityId: string,
  partyId: string,
): Promise<void> {
  await apiDelete(`${recordBase(projectId, entityType, entityId)}/shares/${partyId}`);
}

export async function setRecordOriginator(
  projectId: string,
  entityType: PartyEntityType,
  entityId: string,
  partyId: string | null,
): Promise<RecordParties> {
  return apiPut<RecordParties>(`${recordBase(projectId, entityType, entityId)}/originator`, {
    party_id: partyId,
  });
}
