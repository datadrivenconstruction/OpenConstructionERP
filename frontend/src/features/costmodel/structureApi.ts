// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cost structure, code lists and split allocations.
//
// Every money and share figure travels as a decimal string and stays one:
// sums go through `exactDecimal`, display through `fmtCurrency`. Problems come
// back as stable keys (`shares_do_not_add_up`, `duplicate_code`) that
// `problemMessages.ts` turns into a sentence.

import {
  API_BASE,
  ApiError,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  fetchWithAuth,
} from '@/shared/lib/api';
import type { ControlAccount } from './api';

/* ── Code lists ────────────────────────────────────────────────────────── */

export type CodeListSource = 'builtin' | 'pack' | 'custom';

export interface CodeListSummary {
  key: string;
  name: string;
  standard: string;
  source: CodeListSource;
  pack_slug: string | null;
  entry_count: number;
  depth: number;
}

export interface CodeListEntry {
  code: string;
  title: string;
  parent: string | null;
  level: number;
}

export interface CodeListDetail extends CodeListSummary {
  entries: CodeListEntry[];
}

export interface CodeListIssue {
  row: number | null;
  code: string;
  problem: string;
  params: Record<string, unknown>;
}

export interface CodeListImportResult {
  ok: boolean;
  dry_run: boolean;
  key: string;
  name: string;
  entry_count: number;
  depth: number;
  issues: CodeListIssue[];
  preview: CodeListEntry[];
  code_list: CodeListSummary | null;
}

export interface CodeListImportInput {
  file: File;
  key: string;
  name: string;
  dryRun: boolean;
}

/* ── The structure ─────────────────────────────────────────────────────── */

export interface StructureNode {
  id: string;
  parent_id: string | null;
  code: string;
  title: string;
  name: string;
  level: number;
  classification_standard: string;
  status: string;
  is_leaf_postable: boolean;
  own_amount: string;
  posted: string;
  children_total: string;
  total: string;
  line_count: number;
  child_count: number;
}

export type SuspenseKind = 'no_account' | 'invalid_account';

export interface SuspenseBucket {
  kind: SuspenseKind;
  line_count: number;
  amount: string;
  line_ids: string[];
}

export type FindingSeverity = 'error' | 'warning' | 'info';

export interface StructureFinding {
  rule_id: string;
  severity: FindingSeverity;
  /** Already translated by the backend for the caller's locale. */
  message: string;
  suggestion: string;
  element_ref: string | null;
  details: Record<string, unknown>;
}

export interface StructureTree {
  project_id: string;
  currency: string;
  standards: string[];
  nodes: StructureNode[];
  suspense: SuspenseBucket[];
  total: string;
  findings: StructureFinding[];
}

export interface ApplyCodeListResult {
  key: string;
  accounts_created: number;
}

/** Fields of an account the structure panel edits in place. */
export interface AccountPatch {
  title?: string;
  /** Decimal string with at most two decimals. */
  own_amount?: string;
  is_leaf_postable?: boolean;
}

/* ── Allocations (the vector of a bill position) ──────────────────────── */

export type AllocationMode = 'single' | 'percent' | 'quantity' | 'none';
export type SplitMode = 'percent' | 'quantity';

export interface AllocationRow {
  cost_line_id: string;
  cost_line_code: string;
  cost_line_description: string;
  account_id: string | null;
  account_code: string;
  account_title: string;
  /** False when the line has no account, or a heading or closed one: the money is in suspense. */
  account_postable: boolean;
  share: string;
  fraction: string;
  amount: string;
}

export interface PositionAllocation {
  position_id: string;
  boq_id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: string;
  total: string;
  mode: AllocationMode;
  rows: AllocationRow[];
  valid: boolean;
  problem: string | null;
  share_total: string;
  share_expected: string;
  /** At least one share lands on a cost line without a postable account. */
  in_suspense: boolean;
}

export interface AllocationCoverage {
  boq_id: string;
  positions_total: number;
  positions_allocated: number;
  positions_split: number;
  positions_invalid: number;
  value_total: string;
  value_allocated: string;
  value_unallocated: string;
  /** Positions with money on a cost line without a postable account, and that money. */
  positions_in_suspense: number;
  value_in_suspense: string;
  share_pct: string;
}

export interface BoqAllocations {
  boq_id: string;
  project_id: string;
  currency: string;
  coverage: AllocationCoverage;
  positions: PositionAllocation[];
}

/** One share as sent: onto a cost line or onto an account, never both. */
export type AllocationRowInput =
  | { cost_line_id: string; control_account_id?: undefined; share: string }
  | { control_account_id: string; cost_line_id?: undefined; share: string };

export interface PositionAllocationRequest {
  mode: SplitMode;
  rows: AllocationRowInput[];
  note?: string;
}

/* ── Problems ──────────────────────────────────────────────────────────── */

/** A stable problem key from the backend with its parameters. */
export interface Problem {
  problem: string;
  params: Record<string, unknown>;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * The `{problem, params}` an error carries, or null for any other failure.
 *
 * A detail with no `params` object (the 409 structure mismatch puts
 * `standard` and `requested` next to `problem`) hands its own fields over as
 * the parameters.
 */
export function problemOf(err: unknown): Problem | null {
  const body = err instanceof ApiError ? err.body : asRecord(err)?.body;
  const detail = asRecord(asRecord(body)?.detail);
  if (!detail || typeof detail.problem !== 'string' || !detail.problem) return null;
  const params = asRecord(detail.params);
  if (params) return { problem: detail.problem, params };
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(detail)) if (k !== 'problem') rest[k] = v;
  return { problem: detail.problem, params: rest };
}

/** HTTP status of an API failure, or null. */
export function statusOf(err: unknown): number | null {
  return err instanceof ApiError ? err.status : null;
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

function projectQuery(projectId?: string): string {
  return projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
}

export const costStructureApi = {
  /** The lists come in one envelope page; callers get the plain list. */
  listCodeLists: async (projectId?: string) =>
    (
      await apiGet<{ items: CodeListSummary[]; total: number }>(
        `/v1/costmodel/code-lists/${projectQuery(projectId)}`,
      )
    ).items,

  getCodeList: (key: string, projectId?: string) =>
    apiGet<CodeListDetail>(
      `/v1/costmodel/code-lists/${encodeURIComponent(key)}/${projectQuery(projectId)}`,
    ),

  /**
   * Upload a CSV or XLSX code list. With `dryRun` nothing is stored and the
   * result carries the per-row issues and a preview.
   */
  importCodeList: async (projectId: string, input: CodeListImportInput) => {
    const form = new FormData();
    form.append('file', input.file);
    form.append('key', input.key);
    form.append('name', input.name);
    form.append('dry_run', String(input.dryRun));
    const res = await fetchWithAuth(
      `${API_BASE}/v1/costmodel/projects/${projectId}/code-lists/import/`,
      { method: 'POST', body: form },
    );
    const payload: unknown = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, res.statusText, payload);
    return payload as CodeListImportResult;
  },

  deleteCodeList: (projectId: string, key: string) =>
    apiDelete(`/v1/costmodel/projects/${projectId}/code-lists/${encodeURIComponent(key)}/`),

  getStructure: (projectId: string) =>
    apiGet<StructureTree>(`/v1/costmodel/projects/${projectId}/spine/structure/`),

  applyCodeList: (projectId: string, key: string, maxLevel?: number | null) =>
    apiPost<ApplyCodeListResult>(
      `/v1/costmodel/projects/${projectId}/spine/structure/apply-code-list/`,
      maxLevel ? { key, max_level: maxLevel } : { key },
    ),

  updateAccount: (accountId: string, patch: AccountPatch) =>
    apiPatch<ControlAccount>(`/v1/costmodel/spine/accounts/${accountId}`, patch),

  getBoqAllocations: (boqId: string) =>
    apiGet<BoqAllocations>(`/v1/costmodel/boqs/${boqId}/allocations/`),

  putAllocation: (positionId: string, body: PositionAllocationRequest) =>
    apiPut<PositionAllocation>(`/v1/costmodel/positions/${positionId}/allocation/`, body),

  clearAllocation: (positionId: string) =>
    apiDelete<PositionAllocation>(`/v1/costmodel/positions/${positionId}/allocation/`),
};
