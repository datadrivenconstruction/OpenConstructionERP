// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Field book, road alignment, surface sections and the monitoring plan: the routes the P3 screens call. */

import { activeLanguageTag, apiGet, apiPost, apiPut } from '@/shared/lib/api';
import type { FieldTraverseOut, Finding } from '@/features/survey-calc/api';
import type { AngleUnit } from './units/conventions';
import type { SampleRow } from './engine/sections';

const loc = () => `locale=${encodeURIComponent(activeLanguageTag() ?? 'en')}`;

// ── Field book ────────────────────────────────────────────────────────────

export type BookShape = 'loop' | 'link';
export type AngleMode = 'right' | 'left' | 'deflection' | 'azimuth';
export type DistMode = 'horizontal' | 'slope';

export interface BookRowIn {
  station: string;
  bs?: string;
  fs?: string;
  face_l?: string | null;
  face_r?: string | null;
  dist_mode: DistMode;
  distance?: number | null;
  zenith?: string | null;
  hi?: number | null;
  ht?: number | null;
  note?: string;
}

export interface KnownPoint {
  station_id: string;
  e: number;
  n: number;
}

export interface FieldBookIn {
  name: string;
  shape: BookShape;
  angle_unit: AngleUnit;
  angle_mode: AngleMode;
  start: KnownPoint;
  backsight_id?: string;
  backsight_azimuth?: string | null;
  closing_angle?: string | null;
  end?: KnownPoint | null;
  closing_azimuth?: string | null;
  rows: BookRowIn[];
  class_key?: string;
  angular_k_sec?: number | null;
  min_ratio?: number | null;
  save_points?: boolean;
  note?: string;
}

export interface ReducedRow {
  station: string;
  angle_deg: number;
  angle_right_deg: number;
  face_diff_sec: number | null;
  hd: number | null;
  dh: number | null;
}

export interface FieldBookOut {
  rows: ReducedRow[];
  traverse: FieldTraverseOut;
  unadjusted: KnownPoint[];
  computed_end: KnownPoint;
  fixed_end: KnownPoint;
}

/** A parsed book file: the header and rows as text, the way the grid holds them. */
export interface ParsedBook {
  name: string;
  shape: BookShape;
  angle_unit: AngleUnit;
  angle_mode: AngleMode;
  start: KnownPoint;
  backsight_id: string;
  backsight_azimuth: string | null;
  closing_angle: string | null;
  end: KnownPoint | null;
  closing_azimuth: string | null;
  rows: (Omit<BookRowIn, 'distance' | 'hi' | 'ht'> & { distance: number | string | null; hi: number | string | null; ht: number | string | null })[];
}

export const fieldBookApi = {
  compute: (body: FieldBookIn, projectId?: string | null) =>
    apiPost<FieldBookOut, FieldBookIn>(`/v1/survey-core/calc/field-book?${loc()}${projectId ? `&project_id=${projectId}` : ''}`, body),
  save: (projectId: string, body: FieldBookIn) => apiPost<FieldBookOut, FieldBookIn>(`/v1/survey-core/projects/${projectId}/field-books?${loc()}`, body),
  parse: (text: string) => apiPost<ParsedBook, { text: string }>(`/v1/survey-core/calc/field-book/parse`, { text }),
  demo: () => apiGet<ParsedBook>(`/v1/survey-core/calc/field-book/demo/riverside`),
};

// ── Road alignment ────────────────────────────────────────────────────────

export interface IpIn {
  e: number;
  n: number;
  radius: number;
  name?: string;
}

export interface AlignmentDesignIn {
  name: string;
  ips: IpIn[];
  start_chainage: number;
  design_speed_kmh?: number | null;
  tick_interval?: number;
  label_interval?: number;
}

export interface CurveOut {
  ref: string;
  ip_index: number;
  radius: number;
  deflection_deg: number;
  left: boolean;
  tangent: number;
  arc_length: number;
  external: number;
  tc: number[];
  ct: number[];
  centre: number[];
  tc_chainage: number;
  ct_chainage: number;
  below_min: boolean;
}

export interface MinRadiusOut {
  radius_m: number;
  speed_kmh: number;
  source: 'pack' | 'demo' | string;
  reference: string;
  country: string;
}

export interface AlignmentDesignOut {
  length: number;
  start_chainage: number;
  fits: boolean;
  curves: CurveOut[];
  overlaps: { a: string; b: string; need: number; have: number }[];
  min_radius: MinRadiusOut | null;
  ticks: { chainage: number; e: number; n: number; labelled: boolean }[];
  alignment: Record<string, unknown> | null;
  findings: Finding[];
  saved: boolean;
}

export const alignmentApi = {
  preview: (body: AlignmentDesignIn) => apiPost<AlignmentDesignOut, AlignmentDesignIn>(`/v1/setting-out/alignment/preview?${loc()}`, body),
  save: (requestId: string, body: AlignmentDesignIn) =>
    apiPut<AlignmentDesignOut, AlignmentDesignIn>(`/v1/setting-out/requests/${requestId}/alignment?${loc()}`, body),
  demoRoad: (projectId: string) => apiPost<AlignmentDesignOut>(`/v1/setting-out/projects/${projectId}/demo/riverside/road?${loc()}`),
};

// ── Surface sections (owned by surfaces_volumes) ──────────────────────────

export interface SurfaceItem {
  id: string;
  name: string;
}

export const sectionApi = {
  surfaces: (projectId: string) =>
    apiGet<{ items: SurfaceItem[] } | SurfaceItem[]>(`/v1/surfaces-volumes/projects/${projectId}/surfaces`).then((r) => (Array.isArray(r) ? r : r.items)),
  sample: (surfaceId: string, body: { polyline: number[][]; interval: number; offsets: number[] }) =>
    apiPost<{ surface_id: string; length_m: number; rows: SampleRow[] }, typeof body>(`/v1/surfaces-volumes/surfaces/${surfaceId}/sample`, body),
};

// ── Monitoring plan ───────────────────────────────────────────────────────

export interface MonitoringPlanPoint {
  id: string;
  code: string;
  name: string;
  point_type: string;
  level: string;
  displacement_mm: number | null;
  rate_mm_day: number | null;
  latest_at: string | null;
  e: number | null;
  n: number | null;
  position_source: 'reading' | 'mark' | '';
  de_mm: number | null;
  dn_mm: number | null;
}

export const monitoringPlanApi = {
  plan: (projectId: string) => apiGet<{ items: MonitoringPlanPoint[]; off_plan: number }>(`/v1/monitoring/projects/${projectId}/plan`),
  setPosition: (pointId: string, e: number, n: number) => apiPut<MonitoringPlanPoint, { e: number; n: number }>(`/v1/monitoring/points/${pointId}/position`, { e, n }),
  demoPositions: (projectId: string) => apiPost<{ items: MonitoringPlanPoint[]; off_plan: number }>(`/v1/monitoring/projects/${projectId}/demo/riverside/positions`),
};
