// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the allowances & contingency register.
 *
 * Every path is built from /v1/allowances; apiGet / apiPost already
 * prepend '/api', so we never write '/api/v1' here. Every monetary value crosses
 * the wire as a Decimal-as-string (e.g. "1234.56"), never a number: format it for
 * display with formatCurrency / toNum from '@/shared/lib/money' and never call
 * .toFixed on it or use '+' to add two of them.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';


/* ── Types ─────────────────────────────────────────────────────────────── */

/** The three kinds of allowance an estimate carries. */
export const ALLOWANCE_TYPES = ['provisional_sum', 'pc_sum', 'contingency'] as const;
export type AllowanceType = (typeof ALLOWANCE_TYPES)[number];

/** Default (English) labels for each type; the UI localises via i18n keys. */
export const ALLOWANCE_TYPE_DEFAULT_LABELS: Record<AllowanceType, string> = {
  provisional_sum: 'Provisional sum',
  pc_sum: 'Prime-cost sum',
  contingency: 'Contingency',
};

/** i18n key for an allowance type label (paired with a defaultValue in the UI). */
export function allowanceTypeLabelKey(type: string): string {
  return `allowances.type_${type}`;
}

/** Narrow an arbitrary string to a known {@link AllowanceType}. */
export function isAllowanceType(value: string): value is AllowanceType {
  return (ALLOWANCE_TYPES as readonly string[]).includes(value);
}

/** An allowance with its server-derived drawn / remaining (money as strings). */
export interface Allowance {
  id: string;
  project_id: string;
  label: string;
  allowance_type: AllowanceType;
  held_amount: string;
  currency: string;
  notes: string | null;
  drawn: string;
  remaining: string;
  overdrawn: boolean;
  drawdown_count: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** One amount drawn against an allowance (money as string). */
export interface Drawdown {
  id: string;
  allowance_id: string;
  amount: string;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

/** Held / drawn / remaining for one allowance type within one currency. */
export interface TypeRollup {
  allowance_type: AllowanceType;
  held: string;
  drawn: string;
  remaining: string;
  count: number;
  overdrawn: boolean;
}

/** The register's position in a single currency (money never blended). */
export interface CurrencyRollup {
  currency: string;
  held: string;
  drawn: string;
  remaining: string;
  count: number;
  overdrawn: boolean;
  by_type: TypeRollup[];
}

/** The composed register summary for a project. */
export interface AllowanceRegisterSummary {
  project_id: string;
  by_currency: CurrencyRollup[];
  primary_currency: string;
  allowance_count: number;
}

/* ── Payloads ──────────────────────────────────────────────────────────── */

export interface CreateAllowancePayload {
  label?: string;
  allowance_type?: AllowanceType;
  held_amount?: string;
  currency?: string;
  notes?: string;
}

export type UpdateAllowancePayload = CreateAllowancePayload;

export interface CreateDrawdownPayload {
  amount?: string;
  note?: string;
}

/* ── Pure helpers ──────────────────────────────────────────────────────── */

/** One section of the register: a type and the allowances of that type. */
export interface AllowanceTypeGroup {
  type: AllowanceType;
  items: Allowance[];
}

/**
 * Group allowances into register sections by type, in canonical
 * {@link ALLOWANCE_TYPES} order. Only types that are actually present yield a
 * section (an empty register produces no sections), and within a section the
 * input order of the allowances is preserved. Pure and side-effect free.
 */
export function groupAllowancesByType(items: Allowance[]): AllowanceTypeGroup[] {
  return ALLOWANCE_TYPES.map((type) => ({
    type,
    items: items.filter((a) => a.allowance_type === type),
  })).filter((group) => group.items.length > 0);
}

/* ── Requests ──────────────────────────────────────────────────────────── */

export async function fetchAllowances(projectId: string): Promise<Allowance[]> {
  return apiGet<Allowance[]>(`/v1/allowances/projects/${encodeURIComponent(projectId)}`);
}

export async function fetchRegisterSummary(projectId: string): Promise<AllowanceRegisterSummary> {
  return apiGet<AllowanceRegisterSummary>(
    `/v1/allowances/projects/${encodeURIComponent(projectId)}/summary`,
  );
}

export async function createAllowance(
  projectId: string,
  data: CreateAllowancePayload,
): Promise<Allowance> {
  return apiPost<Allowance>(`/v1/allowances/projects/${encodeURIComponent(projectId)}`, data);
}

export async function updateAllowance(
  allowanceId: string,
  data: UpdateAllowancePayload,
): Promise<Allowance> {
  return apiPatch<Allowance>(`/v1/allowances/items/${allowanceId}`, data);
}

export async function deleteAllowance(allowanceId: string): Promise<void> {
  return apiDelete<void>(`/v1/allowances/items/${allowanceId}`);
}

export async function fetchDrawdowns(allowanceId: string): Promise<Drawdown[]> {
  return apiGet<Drawdown[]>(`/v1/allowances/items/${allowanceId}/drawdowns`);
}

export async function createDrawdown(
  allowanceId: string,
  data: CreateDrawdownPayload,
): Promise<Drawdown> {
  return apiPost<Drawdown>(`/v1/allowances/items/${allowanceId}/drawdowns`, data);
}

export async function deleteDrawdown(drawdownId: string): Promise<void> {
  return apiDelete<void>(`/v1/allowances/drawdowns/${drawdownId}`);
}
