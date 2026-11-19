// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers of the survey calculations: COGO, field traverse, level book,
 * road stake list and the parcel tools (split, merge, corners, setback).
 * Every compute call saves nothing; the save calls are separate.
 */

import { activeLanguageTag, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type { AngleUnit } from './angles';


const loc = () => `locale=${encodeURIComponent(activeLanguageTag() ?? 'en')}`;

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion?: string | null;
  element_ref?: string | null;
}

export interface ClosureClass {
  key: string;
  label: string;
  country: string;
  source: string;
  status: string;
  angular_k_sec: number | null;
  traverse_min_ratio: number | null;
  level_k_mm: number | null;
}

export interface CornerClass {
  key: string;
  label: string;
  source: string;
  status: string;
  base_m: number;
  ppm: number;
}

export interface CalcClasses {
  closure: ClosureClass[];
  corner: CornerClass[];
}

export type CogoMethod = 'inverse' | 'polar' | 'bearing_bearing' | 'line_line' | 'distance_distance' | 'offset' | 'area';
export const COGO_METHODS: CogoMethod[] = ['inverse', 'polar', 'bearing_bearing', 'line_line', 'distance_distance', 'offset', 'area'];

export interface CogoRequest {
  method: CogoMethod;
  angle_unit: AngleUnit;
  a?: number[];
  b?: number[];
  c?: number[];
  d?: number[];
  bearing_a?: string;
  bearing_b?: string;
  distance?: number;
  distance_a?: number;
  distance_b?: number;
  ring?: number[][];
}

export interface CogoResult {
  method: string;
  angle_unit: string;
  distance: number | null;
  bearing_deg: number | null;
  bearing_text: string | null;
  d_e: number | null;
  d_n: number | null;
  d_z: number | null;
  chainage: number | null;
  offset: number | null;
  area: number | null;
  perimeter: number | null;
  solutions: number[][];
  inputs: Record<string, unknown>;
  findings: Finding[];
}

export interface ComputedPoint {
  point_id: string;
  e: number;
  n: number;
  z?: number | null;
  method: string;
  inputs: Record<string, unknown>;
}

export interface StationIn {
  station_id: string;
  angle: string;
  distance_m: number | null;
}

export interface FieldTraverseIn {
  name: string;
  shape: 'loop' | 'link';
  angle_unit: AngleUnit;
  angle_sense: 'right' | 'left';
  start: { station_id: string; e: number; n: number };
  azimuth: string;
  stations: StationIn[];
  end?: { station_id: string; e: number; n: number } | null;
  closing_azimuth?: string | null;
  class_key: string;
  save_points?: boolean;
}

export interface FieldTraverseOut {
  shape: string;
  angle_count: number;
  angle_sum_deg: number;
  expected_sum_deg: number | null;
  angular_misclosure_sec: number;
  angular_correction_sec: number;
  angular_k_sec: number | null;
  angular_allowed_sec: number | null;
  angular_verdict: string;
  length_m: number;
  f_e: number;
  f_n: number;
  misclosure_m: number;
  ratio: number | null;
  min_ratio: number | null;
  linear_verdict: string;
  class_label: string;
  stations: { station_id: string; e: number; n: number; angle_corrected_deg: number; c_e: number; c_n: number }[];
  findings: Finding[];
  points_saved: number;
}

export interface BookRow {
  station: string;
  bs: number | null;
  is: number | null;
  fs: number | null;
  distance_m: number | null;
}

export interface LevelBookIn {
  name: string;
  method: 'rise_fall' | 'hi';
  start_rl: number;
  close_rl: number | null;
  rows: BookRow[];
  class_key: string;
  write_rls?: boolean;
}

export interface LevelBookOut {
  method: string;
  rows: {
    station: string;
    bs: number | null;
    is: number | null;
    fs: number | null;
    rise: number | null;
    fall: number | null;
    hi: number | null;
    rl: number;
    correction_mm: number;
    step_mm: number;
    rl_adjusted: number;
  }[];
  sum_bs: number;
  sum_fs: number;
  sum_rise: number;
  sum_fall: number;
  first_rl: number;
  last_rl: number;
  arithmetic_ok: boolean;
  misclosure_mm: number | null;
  distance_km: number;
  allowed_mm: number | null;
  verdict: string;
  class_label: string;
  findings: Finding[];
  points_updated: number;
}

export const getClasses = () => apiGet<CalcClasses>(`/v1/survey-core/calc/classes`);
export const runCogo = (body: CogoRequest) => apiPost<CogoResult, CogoRequest>(`/v1/survey-core/calc/cogo?${loc()}`, body);
export const saveComputedPoints = (projectId: string, name: string, points: ComputedPoint[]) =>
  apiPost<{ point_set_id: string; saved: number }>(`/v1/survey-core/projects/${projectId}/computed-points`, { name, points });
export const runTraverse = (body: FieldTraverseIn) =>
  apiPost<FieldTraverseOut, FieldTraverseIn>(`/v1/survey-core/calc/field-traverse?${loc()}`, body);
export const saveTraverse = (projectId: string, body: FieldTraverseIn) =>
  apiPost<FieldTraverseOut, FieldTraverseIn>(`/v1/survey-core/projects/${projectId}/field-traverses?${loc()}`, body);
export const runLevelBook = (body: LevelBookIn) => apiPost<LevelBookOut, LevelBookIn>(`/v1/survey-core/calc/level-book?${loc()}`, body);
export const saveLevelBook = (projectId: string, body: LevelBookIn) =>
  apiPost<LevelBookOut, LevelBookIn>(`/v1/survey-core/projects/${projectId}/level-books?${loc()}`, body);

export interface StakeListIn {
  landxml: string;
  interval: number;
  offsets: number[];
  crossfall_pct: number;
  measured: { chainage: number; offset: number; z: number }[];
  mode: 'stake' | 'as_built';
}

export interface StakeListOut {
  alignment_length: number;
  start_chainage: number;
  has_profile: boolean;
  rows: { chainage: number; offset: number; e: number; n: number; design_z: number | null; measured_z: number | null; dz_mm: number | null; cut_fill: string }[];
  problems: string[];
  findings: Finding[];
}

export const runStakeList = (body: StakeListIn) => apiPost<StakeListOut, StakeListIn>(`/v1/setting-out/road/stake-list?${loc()}`, body);

export interface SplitIn {
  mode: 'line' | 'parallel' | 'rotate';
  a?: number[];
  b?: number[];
  side?: number;
  pivot?: number[];
  target_area?: number;
  refs?: string[];
  preview: boolean;
}

export interface SplitOut {
  parent_area: number;
  parts: { ref: string; area: number; ring: number[][]; parcel_id: string | null }[];
  cut: number[][];
  cut_length: number | null;
  position: number | null;
  findings: Finding[];
  saved: boolean;
}

export interface Corner {
  seq: number;
  label: string;
  e: number;
  n: number;
  mark: string;
  corner_status: string;
  accuracy_class: string;
  accuracy_m: number | null;
  limit_m: number | null;
  class_label: string;
  findings: Finding[];
}

export interface CornerRegister {
  parcel_id: string;
  parcel_ref: string;
  corners: Corner[];
  classes: CornerClass[];
}

export interface CornerPatch {
  corner_status?: string;
  accuracy_class?: string;
  accuracy_m?: number;
  clear_accuracy?: boolean;
}

export interface SetbackOut {
  min_distance: number;
  setback_m: number;
  edges: { edge: number; label: string; distance: number; encroaches: boolean; ok: boolean }[];
  findings: Finding[];
}

export const splitParcel = (parcelId: string, body: SplitIn) => apiPost<SplitOut, SplitIn>(`/v1/land-parcels/parcels/${parcelId}/split?${loc()}`, body);
export const mergeParcels = (projectId: string, parcelIds: string[], ref: string, preview: boolean) =>
  apiPost<SplitOut>(`/v1/land-parcels/projects/${projectId}/parcels/merge?${loc()}`, { parcel_ids: parcelIds, ref, preview });
export const getCorners = (parcelId: string) => apiGet<CornerRegister>(`/v1/land-parcels/parcels/${parcelId}/corners?${loc()}`);
export const patchCorner = (parcelId: string, seq: number, body: CornerPatch) =>
  apiPatch<CornerRegister, CornerPatch>(`/v1/land-parcels/parcels/${parcelId}/corners/${seq}?${loc()}`, body);
export const stakeCorners = (parcelId: string) =>
  apiPost<{ request_id: string; code: string; stakes: number }>(`/v1/land-parcels/parcels/${parcelId}/corners/stake`, {});
export const checkSetback = (parcelId: string, footprint: number[][], name: string, setbackM: number) =>
  apiPost<SetbackOut>(`/v1/land-parcels/parcels/${parcelId}/setback?${loc()}`, { footprint, name, setback_m: setbackM });
