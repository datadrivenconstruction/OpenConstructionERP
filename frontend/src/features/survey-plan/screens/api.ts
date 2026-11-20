// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Endpoints of the P2 plan screens: parcels and work zones in grid metres,
 * the boundary point register, design pads, contours, profile sampling,
 * stockpile and mine plans, and the plan DXF.
 */

import { apiGet, apiPost, apiPut } from '@/shared/lib/api';

const LP = '/v1/land-parcels';
const SV = '/v1/surfaces-volumes';

export interface GridCorner { label: string; e: number; n: number; mark: string }
export interface GridParcel {
  id: string;
  ref: string;
  name: string;
  status: string;
  legal_area: string | null;
  computed_area: string | null;
  tolerance_m2: string | null;
  points: GridCorner[];
}
export interface GridZone { id: string; name: string; ring: Array<[number, number]> }
export interface PlanGrid {
  epsg: number | null;
  id_pattern: string;
  gap_tolerance_m: string;
  parcels: GridParcel[];
  zones: GridZone[];
}

export interface BoundaryPointRow {
  point_no: string;
  e: number;
  n: number;
  mark: string;
  monumented: boolean | null;
  accuracy_m: number | null;
  corner_status: string;
  parcels: string[];
  mark_conflict: boolean;
  position_spread_m: number;
}
export interface BoundaryPointRegister { items: BoundaryPointRow[]; total: number; monumented: number; unmarked: number; conflicts: number }

export interface TouchedParcel { parcel_id: string; parcel_ref: string; status: string; overlap_m2: number; blocking: boolean }
export interface ServerFinding { rule_id: string; severity: string; message: string; suggestion?: string | null; element_ref?: string | null }
export interface WorkZoneDetail { id: string; name: string; ring: Array<[number, number]>; touched: TouchedParcel[]; findings: ServerFinding[] }

export interface PadInput {
  name: string;
  outline: Array<[number, number]>;
  level: number;
  batter_n: number;
  cross_fall_pct: number;
  fall_bearing_deg: number;
  ground_surface_id: string | null;
  note?: string;
}
export interface PadCheck { valid: boolean; findings: ServerFinding[]; area_m2: number }

export interface ContourLine { z: number; index: boolean; coords: Array<[number, number]>; closed: boolean }
export interface Contours { surface_id: string; interval: number; auto_interval: number; index_every: number; z_min: number | null; z_max: number | null; lines: ContourLine[] }
export interface MeshOut { vertices: Array<[number, number, number]>; faces: Array<[number, number, number]> }
export interface SampleRow { ch: number; offset: number; e: number; n: number; z: number | null }
export interface SampleOut { rows: SampleRow[]; length_m: number }

export interface StockpilePlan {
  stockpile_id: string;
  code: string;
  name: string;
  material: string;
  survey_id: string | null;
  surveyed_on: string | null;
  volume_m3: string | null;
  tonnes: string | null;
  base_surface_id: string | null;
  pile_surface_id: string | null;
  toe: Array<[number, number]>;
  crest: Array<[number, number]>;
  max_height_m: number;
  footprint_m2: number;
  heat: HeatGrid | null;
  surveys: Array<{ id: string; surveyed_on: string; volume_m3: string }>;
}
export interface HeatGrid { origin_e: number; origin_n: number; cell: number; nx: number; ny: number; dh: Array<number | null> }

export interface MinePlan {
  periods: Array<{ id: string; label: string; period_end: string }>;
  period_id: string | null;
  blast_blocks: Array<{ pattern_id: string; code: string; name: string; unit_id: string | null; ring: Array<[number, number]>; holes: Array<[number, number]>; hole_spacing_m: number }>;
  reconciliation: Array<{
    entry_id: string; unit_id: string; unit_code: string; unit_name: string; unit_type: string; plan_m3: string;
    volume_id: string | null; volume_code: string; base_surface_id: string | null; compare_surface_id: string | null;
    cut_m3: string | null; fill_m3: string | null; net_m3: string | null;
  }>;
  pit_surface_id: string | null;
}

export interface PlanDxfFeature { kind: 'point' | 'line' | 'polygon' | 'text'; coords: number[][]; label?: string; text_mm?: number }
export interface PlanDxfLayer { id: string; aci: number; features: PlanDxfFeature[] }
export interface PlanDxfBody { title: string; drawing_no: string; revision: string; scale: number; layers: PlanDxfLayer[] }

export const p2Api = {
  planGrid: (projectId: string) => apiGet<PlanGrid>(`${LP}/projects/${projectId}/plan-grid`),
  boundaryPoints: (projectId: string) => apiGet<BoundaryPointRegister>(`${LP}/projects/${projectId}/boundary-points`),
  setParcelPoints: (parcelId: string, points: GridCorner[]) => apiPut<unknown>(`${LP}/parcels/${parcelId}/points`, { points }),
  createZone: (projectId: string, body: { name: string; ring: Array<[number, number]> }) => apiPost<WorkZoneDetail>(`${LP}/projects/${projectId}/work-zones`, body),
  getZone: (zoneId: string) => apiGet<WorkZoneDetail>(`${LP}/work-zones/${zoneId}`),
  putZone: (zoneId: string, body: { name: string; ring: Array<[number, number]> }, baseRev?: number | null) =>
    apiPut<WorkZoneDetail>(`${LP}/work-zones/${zoneId}${baseRev != null ? `?base_rev=${baseRev}` : ''}`, body),
  loadDemo: (projectId: string) => apiPost<{ parcels: number; work_zones: number; skipped: number }>(`${LP}/projects/${projectId}/demo/riverside`, {}),
  checkPad: (projectId: string, body: PadInput) => apiPost<PadCheck>(`${SV}/projects/${projectId}/surfaces/pad/check`, body),
  createPad: (projectId: string, body: PadInput) => apiPost<{ id: string; name: string }>(`${SV}/projects/${projectId}/surfaces/pad`, body),
  contours: (surfaceId: string, interval?: number | null) => apiGet<Contours>(`${SV}/surfaces/${surfaceId}/contours${interval ? `?interval=${interval}` : ''}`),
  mesh: (surfaceId: string) => apiGet<MeshOut>(`${SV}/surfaces/${surfaceId}/mesh`),
  sample: (surfaceId: string, body: { polyline: Array<[number, number]>; interval: number; offsets: number[] }) => apiPost<SampleOut>(`${SV}/surfaces/${surfaceId}/sample`, body),
  stockpilePlan: (stockpileId: string, surveyId?: string | null) => apiGet<StockpilePlan>(`/v1/stockpiles/stockpiles/${stockpileId}/plan${surveyId ? `?survey_id=${surveyId}` : ''}`),
  minePlan: (projectId: string, periodId?: string | null) => apiGet<MinePlan>(`/v1/mine-survey/projects/${projectId}/plan${periodId ? `?period_id=${periodId}` : ''}`),
};

export const p2Keys = {
  grid: (projectId: string) => ['survey-plan', 'p2', 'grid', projectId] as const,
  points: (projectId: string) => ['survey-plan', 'p2', 'boundary-points', projectId] as const,
  contours: (surfaceId: string, interval: number | null) => ['survey-plan', 'p2', 'contours', surfaceId, interval] as const,
  mesh: (surfaceId: string) => ['survey-plan', 'p2', 'mesh', surfaceId] as const,
  stockpile: (id: string, surveyId: string | null) => ['survey-plan', 'p2', 'stockpile', id, surveyId] as const,
  mine: (projectId: string, periodId: string | null) => ['survey-plan', 'p2', 'mine', projectId, periodId] as const,
};
