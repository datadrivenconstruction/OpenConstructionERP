// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for User Management.
 */

import { apiGet, apiPatch, apiPost, apiDelete } from '@/shared/lib/api';

export type UserRole = 'admin' | 'manager' | 'editor' | 'viewer';
export type ModuleAccessLevel = 'none' | 'view' | 'edit' | 'full';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  locale: string;
  is_active: boolean;
  last_login_at: string | null;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface UserAdminUpdate {
  full_name?: string;
  role?: UserRole;
  is_active?: boolean;
  locale?: string;
}

export interface InviteUserPayload {
  email: string;
  password: string;
  full_name: string;
  role: UserRole;
}

export interface ModuleAccess {
  visible: boolean;
  access: ModuleAccessLevel;
}

export interface UserModuleAccessPayload {
  modules: Record<string, ModuleAccess>;
  custom_role_name?: string | null;
}

export async function fetchUsers(params?: {
  is_active?: boolean;
  limit?: number;
  offset?: number;
}): Promise<User[]> {
  const qs = new URLSearchParams();
  if (params?.is_active !== undefined) qs.set('is_active', String(params.is_active));
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return apiGet<User[]>(`/v1/users/${q ? `?${q}` : ''}`);
}

export async function updateUser(id: string, data: UserAdminUpdate): Promise<User> {
  return apiPatch<User>(`/v1/users/${id}`, data);
}

/**
 * Admin-only: permanently delete (erase) a user account. The server anonymises
 * the row in place so the user's projects and history keep resolving, but every
 * personal field is stripped and the account can no longer log in. The last
 * active admin cannot be deleted (409), and an admin cannot delete their own
 * account through this route (400) - that goes through account settings.
 */
export async function deleteUser(id: string): Promise<void> {
  await apiDelete(`/v1/users/${id}`);
}

export async function inviteUser(data: InviteUserPayload): Promise<User> {
  // Admin-create endpoint (POST /v1/users/, gated by users.create) honors the
  // chosen role. The previous target /auth/register is the OPEN self-signup
  // flow, which ignores `role` and always lands the user as viewer, so the
  // role picker in the invite modal was a silent no-op.
  return apiPost<User>('/v1/users/', data);
}

export async function getUserModuleAccess(userId: string): Promise<UserModuleAccessPayload> {
  return apiGet<UserModuleAccessPayload>(`/v1/users/${userId}/module-access/`);
}

export async function setUserModuleAccess(
  userId: string,
  data: UserModuleAccessPayload,
): Promise<UserModuleAccessPayload> {
  return apiPatch<UserModuleAccessPayload>(`/v1/users/${userId}/module-access/`, data);
}
