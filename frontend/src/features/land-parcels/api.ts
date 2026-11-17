// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Land & parcels: the schedule, import (preview first,
 * nothing saved until Import), exports, plan GeoJSON, parties and rights,
 * and sending a parcel's compensation to a BOQ.
 */

import { apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/land-parcels';

export type ParcelStatus = 'needed' | 'negotiating' | 'acquired' | 'expropriation';
export const PARCEL_STATUSES: ParcelStatus[] = ['needed', 'negotiating', 'acquired', 'expropriation'];
export type RightKind = 'ownership' | 'lease' | 'easement' | 'servitude' | 'mortgage' | 'restriction' | 'other';
export const RIGHT_KINDS: RightKind[] = ['ownership', 'lease', 'easement', 'servitude', 'mortgage', 'restriction', 'other'];
export type PartyKind = 'person' | 'organisation' | 'public';
export const PARTY_KINDS: PartyKind[] = ['person', 'organisation', 'public'];
export type ImportTarget = 'parcels' | 'work_zone';
export type ImportFormat = 'geojson' | 'shapefile';

export interface Finding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  suggestion?: string | null;
  element_ref?: string | null;
}

export interface Parcel {
  id: string;
  parcel_ref: string;
  name: string;
  status: ParcelStatus;
  legal_area: string | null;
  computed_area: string | null;
  area_diff: string | null;
  ring_closed: boolean;
  epsg: number | null;
  acquisition_cost: string | null;
  currency: string;
  acquired_on: string | null;
  note: string;
  source: string;
  source_filename: string;
  point_count: number;
  rights_count: number;
  rights_kinds: string[];
  boq_position_id: string | null;
  sent_at: string | null;
  findings: Finding[];
}

export interface BoundaryPoint {
  seq: number;
  label: string;
  e: number;
  n: number;
  mark: string;
  accuracy_m: number | null;
}

export interface Right {
  id: string;
  parcel_id: string;
  party_id: string | null;
  party_name: string;
  kind: RightKind;
  share: string;
  description: string;
  registry_ref: string;
  valid_from: string | null;
  valid_to: string | null;
}

export interface ParcelDetail extends Parcel {
  points: BoundaryPoint[];
  rights: Right[];
}

export interface Party {
  id: string;
  name: string;
  kind: PartyKind;
  reference: string;
  note: string;
}

export interface ParcelSummary {
  parcels: number;
  acquired: number;
  total_area: string;
  blocking_works: number;
  cost_to_acquire: string;
  currency: string;
  findings: number;
  by_status: Record<string, number>;
}

export interface ParcelProfile {
  country: string;
  id_label_key: string;
  id_label_default: string;
  id_example: string;
  area_decimals: number;
  area_tolerance_source: string;
  export_formats: string[];
}

export interface ParcelSettings {
  area_tolerance_pct: string;
  gap_tolerance_m: string;
}

export interface ImportBody {
  format: ImportFormat;
  target: ImportTarget;
  filename: string;
  text?: string;
  content_base64?: string;
  source_epsg?: number | null;
  on_existing?: 'skip' | 'replace';
}

export interface ImportPreview {
  features_read: number;
  problem_count: number;
  problems: { index: number; code: string; detail: string }[];
  features: {
    index: number;
    ref: string;
    name: string;
    legal_area: string | null;
    computed_area: string | null;
    status: string;
    vertices: number;
    closed: boolean;
    exists: boolean;
  }[];
  fields: string[];
  file_epsg: number | null;
  project_epsg: number | null;
  transform: string | null;
  total_area: string;
}

export interface ImportResult {
  created: number;
  replaced: number;
  skipped: number;
  work_zones: number;
  total_area: string;
}

export interface PlanCollection {
  type: 'FeatureCollection';
  local: boolean;
  epsg: number | null;
  features: {
    type: 'Feature';
    id: string;
    properties: { kind: 'parcel' | 'work_zone'; id: string; ref?: string; name?: string; status?: ParcelStatus; blocking?: boolean; area?: string | null };
    geometry: { type: 'Polygon'; coordinates: number[][][] };
  }[];
}

export interface WorkZone {
  id: string;
  name: string;
  epsg: number | null;
  source_filename: string;
  vertex_count: number;
}

export interface BoqRow {
  id: string;
  name: string;
}

const p = (projectId: string) => `${BASE}/projects/${projectId}`;
const lang = (locale: string) => `locale=${encodeURIComponent(locale)}`;

export const getProfile = (projectId: string) => apiGet<ParcelProfile>(`${p(projectId)}/profile`);
export const getSettings = (projectId: string) => apiGet<ParcelSettings>(`${p(projectId)}/settings`);
export const putSettings = (projectId: string, body: ParcelSettings) => apiPut<ParcelSettings, ParcelSettings>(`${p(projectId)}/settings`, body);
export const listParcels = (projectId: string, locale: string) => apiGet<Parcel[]>(`${p(projectId)}/parcels?${lang(locale)}`);
export const getSummary = (projectId: string) => apiGet<ParcelSummary>(`${p(projectId)}/summary`);
export const getPlan = (projectId: string) => apiGet<PlanCollection>(`${p(projectId)}/plan`);
export const listZones = (projectId: string) => apiGet<WorkZone[]>(`${p(projectId)}/work-zones`);
export const deleteZone = (zoneId: string) => apiDelete(`${BASE}/work-zones/${zoneId}`);
export const previewImport = (projectId: string, body: ImportBody) => apiPost<ImportPreview, ImportBody>(`${p(projectId)}/import/preview`, body);
export const importFile = (projectId: string, body: ImportBody) => apiPost<ImportResult, ImportBody>(`${p(projectId)}/import`, body);
export const getParcel = (parcelId: string, locale: string) => apiGet<ParcelDetail>(`${BASE}/parcels/${parcelId}?${lang(locale)}`);
export const updateParcel = (parcelId: string, body: Record<string, unknown>, locale: string) =>
  apiPatch<ParcelDetail, Record<string, unknown>>(`${BASE}/parcels/${parcelId}?${lang(locale)}`, body);
export const deleteParcel = (parcelId: string) => apiDelete(`${BASE}/parcels/${parcelId}`);
export const listParties = (projectId: string) => apiGet<Party[]>(`${p(projectId)}/parties`);
export const createParty = (projectId: string, body: Omit<Party, 'id'>) => apiPost<Party, Omit<Party, 'id'>>(`${p(projectId)}/parties`, body);
export const deleteParty = (partyId: string) => apiDelete(`${BASE}/parties/${partyId}`);
export const listRights = (projectId: string) => apiGet<Right[]>(`${p(projectId)}/rights`);
export const addRight = (parcelId: string, body: Partial<Right>) => apiPost<Right, Partial<Right>>(`${BASE}/parcels/${parcelId}/rights`, body);
export const deleteRight = (rightId: string) => apiDelete(`${BASE}/rights/${rightId}`);
export const listBoqs = (projectId: string) => apiGet<BoqRow[]>(`/v1/boq/boqs/?project_id=${projectId}`);
export const sendToBoq = (parcelId: string, body: { boq_id: string; position_id?: string | null; description: string }) =>
  apiPost<{ position_id: string; ordinal: string; total: string; mode: 'added' | 'replaced' }, typeof body>(
    `${BASE}/parcels/${parcelId}/send-to-boq`,
    body,
  );

export const downloadExport = (projectId: string, format: string) =>
  downloadWithAuth(`/api${p(projectId)}/export?format=${encodeURIComponent(format)}`, `parcels.${format === 'shapefile' ? 'zip' : format}`);
export const downloadSchedule = (projectId: string, locale: string) =>
  downloadWithAuth(`/api${p(projectId)}/schedule.pdf?${lang(locale)}`, 'parcel_schedule.pdf');
