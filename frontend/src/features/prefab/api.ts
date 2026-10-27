// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Off-site / Prefab / DfMA.
 *
 * All endpoints are prefixed with /v1/prefab/. Trailing slashes match the
 * FastAPI routes exactly — without them we hit a 307 redirect that some
 * proxies rewrite without forwarding the auth header.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type PrefabStage =
  | 'design'
  | 'approved_for_production'
  | 'in_production'
  | 'qa'
  | 'dispatched'
  | 'delivered'
  | 'installed';

export type PrefabUnitType =
  | 'pod'
  | 'panel'
  | 'module'
  | 'skid'
  | 'volumetric'
  | 'rebar_cage'
  | 'other';

export interface PrefabUnit {
  id: string;
  project_id: string;
  ref: string;
  unit_type: PrefabUnitType | string;
  status: PrefabStage | string;
  target_install_date: string | null;
  drawing_ref: string | null;
  bim_element_ids: string[] | null;
  notes: string | null;
  created_by: string | null;
  /** Token printed as the unit's QR label and scanned on arrival. */
  qr_token?: string | null;
  delivery_note_ref?: string | null;
  /** Element the unit goes into, e.g. a pile mark. */
  element_ref?: string | null;
  created_at: string;
  updated_at: string;
  /* ── Spine 4: cost link + derived cost view ─────────────────────────── */
  boq_position_id: string | null;
  assembly_id: string | null;
  /** Linked cost basis (BOQ unit_rate or assembly total_rate). Decimal string. */
  cost_basis: string | null;
  /** Which link drove the basis: 'boq_position' | 'assembly' | null. */
  cost_source: 'boq_position' | 'assembly' | null;
  /** Production progress 0..1 from the stage machine. */
  completed_fraction: number | null;
  /** Simple earned value: cost_basis * completed_fraction. Decimal string. */
  earned_value: string | null;
}

export interface ProductionEvent {
  id: string;
  unit_id: string;
  stage: PrefabStage | string;
  from_stage: PrefabStage | string | null;
  at: string;
  note: string | null;
  created_by: string | null;
}

export interface PrefabBoardColumn {
  stage: PrefabStage | string;
  count: number;
  units: PrefabUnit[];
}

export interface PrefabBoardResponse {
  project_id: string;
  total: number;
  columns: PrefabBoardColumn[];
}

export interface PrefabStats {
  total: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
}

export interface PrefabStageInfo {
  stage: PrefabStage | string;
  index: number;
  is_post_qa: boolean;
}

export interface PrefabStagesResponse {
  stages: PrefabStageInfo[];
  unit_types: string[];
}

export interface CreatePrefabUnitPayload {
  project_id: string;
  ref: string;
  unit_type?: PrefabUnitType;
  status?: PrefabStage;
  target_install_date?: string | null;
  drawing_ref?: string | null;
  notes?: string | null;
  bim_element_ids?: string[] | null;
}

export interface UpdatePrefabUnitPayload {
  ref?: string;
  unit_type?: PrefabUnitType;
  target_install_date?: string | null;
  drawing_ref?: string | null;
  notes?: string | null;
  bim_element_ids?: string[] | null;
}

export interface AdvanceStagePayload {
  /** Explicit target stage; omit to advance to the immediate next stage. */
  target_status?: PrefabStage;
  note?: string;
}

export interface LinkPrefabUnitPayload {
  /** UUID to set the BOQ position link, null to clear it, omit to leave as-is. */
  boq_position_id?: string | null;
  /** UUID to set the assembly link, null to clear it, omit to leave as-is. */
  assembly_id?: string | null;
}

/** A BOQ position option for the link picker (subset of the BOQ read model). */
export interface BoqPositionOption {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
  unit_rate: string;
}

/** An assembly option for the link picker (subset of the assembly read model). */
export interface AssemblyOption {
  id: string;
  code: string;
  name: string;
  unit: string;
  total_rate: number;
}

export interface PrefabUnitFilters {
  project_id: string;
  status?: PrefabStage | '';
  type?: PrefabUnitType | '';
}

/* ── API functions ─────────────────────────────────────────────────────── */

export async function fetchPrefabBoard(projectId: string): Promise<PrefabBoardResponse> {
  return apiGet<PrefabBoardResponse>(
    `/v1/prefab/board/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function fetchPrefabUnits(filters: PrefabUnitFilters): Promise<PrefabUnit[]> {
  const params = new URLSearchParams();
  params.set('project_id', filters.project_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.type) params.set('type', filters.type);
  return apiGet<PrefabUnit[]>(`/v1/prefab/units/?${params.toString()}`);
}

export async function createPrefabUnit(data: CreatePrefabUnitPayload): Promise<PrefabUnit> {
  return apiPost<PrefabUnit>('/v1/prefab/units/', data);
}

export async function updatePrefabUnit(
  id: string,
  data: UpdatePrefabUnitPayload,
): Promise<PrefabUnit> {
  return apiPatch<PrefabUnit>(`/v1/prefab/units/${id}`, data);
}

export async function deletePrefabUnit(id: string): Promise<void> {
  return apiDelete<void>(`/v1/prefab/units/${id}`);
}

export async function advancePrefabUnit(
  id: string,
  data: AdvanceStagePayload,
): Promise<PrefabUnit> {
  return apiPost<PrefabUnit>(`/v1/prefab/units/${id}/advance/`, data);
}

export async function receivePrefabUnitByQr(data: {
  qr_token: string;
  delivery_note_ref: string;
  note?: string;
}): Promise<PrefabUnit> {
  return apiPost<PrefabUnit>('/v1/prefab/units/receive/', data);
}

export async function linkPrefabUnit(
  id: string,
  data: LinkPrefabUnitPayload,
): Promise<PrefabUnit> {
  return apiPatch<PrefabUnit>(`/v1/prefab/units/${id}/link`, data);
}

/* ── Link pickers: BOQ positions + assemblies for the current project ───── */

interface BoqListItem {
  id: string;
  name: string;
}

/** List the project's BOQs so a user can choose which one to pull a position from. */
export async function fetchProjectBoqs(projectId: string): Promise<BoqListItem[]> {
  return apiGet<BoqListItem[]>(`/v1/boq/boqs/?project_id=${encodeURIComponent(projectId)}`);
}

/** Fetch a BOQ's positions (the flat line items) for the link picker. */
export async function fetchBoqPositions(boqId: string): Promise<BoqPositionOption[]> {
  const boq = await apiGet<{ positions?: BoqPositionOption[] }>(`/v1/boq/boqs/${boqId}`);
  const positions = boq.positions ?? [];
  // Drop section headers (they carry no unit) - only priceable lines are useful.
  return positions
    .filter((p) => Boolean(p.unit))
    .map((p) => ({
      id: p.id,
      ordinal: p.ordinal,
      description: p.description,
      unit: p.unit,
      unit_rate: String(p.unit_rate ?? '0'),
    }));
}

/** List assemblies usable by the project (project-scoped + platform templates). */
export async function fetchProjectAssemblies(projectId: string): Promise<AssemblyOption[]> {
  const res = await apiGet<{ items?: AssemblyOption[] }>(
    `/v1/assemblies/?project_id=${encodeURIComponent(projectId)}&limit=200`,
  );
  return (res.items ?? []).map((a) => ({
    id: a.id,
    code: a.code,
    name: a.name,
    unit: a.unit,
    total_rate: Number(a.total_rate ?? 0),
  }));
}

export async function fetchUnitEvents(id: string): Promise<ProductionEvent[]> {
  return apiGet<ProductionEvent[]>(`/v1/prefab/units/${id}/events/`);
}

export async function fetchPrefabStages(): Promise<PrefabStagesResponse> {
  return apiGet<PrefabStagesResponse>('/v1/prefab/stages/');
}

export async function fetchPrefabStats(projectId: string): Promise<PrefabStats> {
  return apiGet<PrefabStats>(
    `/v1/prefab/stats/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/* ── Shared stage metadata (mirrors backend guard.py) ──────────────────── */

/** Canonical lifecycle order, matching backend STAGE_ORDER. */
export const STAGE_ORDER: PrefabStage[] = [
  'design',
  'approved_for_production',
  'in_production',
  'qa',
  'dispatched',
  'delivered',
  'installed',
];

/** Stages that can only be entered once a unit has passed QA. */
export const POST_QA_STAGES: PrefabStage[] = ['dispatched', 'delivered', 'installed'];

export const UNIT_TYPES: PrefabUnitType[] = [
  'pod',
  'panel',
  'module',
  'skid',
  'volumetric',
  'other',
];

/** Immediate next stage in the lifecycle, or null at the terminal stage. */
export function nextStage(current: PrefabStage | string): PrefabStage | null {
  const idx = STAGE_ORDER.indexOf(current as PrefabStage);
  if (idx < 0 || idx >= STAGE_ORDER.length - 1) return null;
  return STAGE_ORDER[idx + 1] ?? null;
}
