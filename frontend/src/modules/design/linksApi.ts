// Design module (ERP side of the design editor link).
/**
 * The design and the other ERP modules: which BOQ positions, schedule activities and tender packages an element
 * feeds, the elements behind a position, and the project overview module by module. Also the ERP addresses that
 * open each of them, so every link can be followed both ways.
 */
import { apiGet, apiPost, apiPut } from '@/shared/lib/api';
import { LINK_VERSION } from './api';
import type { SelectedElement } from './bridge/protocol';

const HEADERS = { 'X-DDC-Link': LINK_VERSION };
const P = (id: string) => `/v1/design/projects/${id}`;

export interface LinkedPosition {
  position_id: string; boq_id: string; source: 'estimate' | 'takeoff'; ordinal: string; description: string;
  quantity: string | null; unit: string; elements: string[];
}
export interface LinkedActivity {
  activity_id: string; schedule_id: string; name: string; start_date: string | null; end_date: string | null;
  storey: string; elements: string[];
}
export interface LinkedPackage { package_id: string; name: string; status: string; ifc_class: string; elements: string[] }
export interface ElementLinks { keys: string[]; positions: LinkedPosition[]; activities: LinkedActivity[]; packages: LinkedPackage[] }
export interface PositionElements {
  position_id: string; boq_id: string; model_id: string | null; keys: string[]; element_ids: string[]; isolate: string[] | null;
}

export type StepId = 'brief' | 'model' | 'estimate' | 'schedule' | 'procurement' | 'documents' | 'bim' | 'change_orders' | 'tasks';
export interface OverviewStep {
  id: StepId; done: boolean; count: number | null; url: string;
  waiting?: number; drafts?: number; current?: number | null;
}
export interface Overview { project_id: string; steps: OverviewStep[]; waiting_revision_id: string | null }

/** At most this many keys go in one request (the server's limit). */
export const MAX_KEYS = 500;

export function fetchLinks(projectId: string, keys: string[]): Promise<ElementLinks> {
  const q = new URLSearchParams();
  for (const k of keys.slice(0, MAX_KEYS)) q.append('keys', k);
  return apiGet<ElementLinks>(`${P(projectId)}/links?${q.toString()}`, { headers: HEADERS });
}

export const fetchPositionElements = (projectId: string, positionId: string) =>
  apiGet<PositionElements>(`${P(projectId)}/positions/${positionId}/elements`, { headers: HEADERS });

export const fetchOverview = (projectId: string) => apiGet<Overview>(`${P(projectId)}/overview`, { headers: HEADERS });

export interface FieldReportRow {
  id: string; report_date: string; report_type: string; status: string; excerpt: string;
  keys: string[]; position_ids: string[]; revision_id: string | null;
  matched_keys?: string[]; matched_positions?: string[];
}
export interface ReportElements {
  report_id: string; model_id: string | null; keys: string[]; element_ids: string[]; isolate: string[] | null;
  positions: { position_id: string; boq_id: string; ordinal: string; description: string }[];
}

/** Field reports that name one of these elements (or a position they feed); without keys, every report of the project. */
export function fetchFieldReports(projectId: string, keys: string[]): Promise<{ items: FieldReportRow[] }> {
  const q = new URLSearchParams();
  for (const k of keys.slice(0, MAX_KEYS)) q.append('keys', k);
  return apiGet(`${P(projectId)}/field-reports?${q.toString()}`, { headers: HEADERS });
}
export const putReportLinks = (projectId: string, reportId: string, body: { keys: string[]; position_ids: string[] }) =>
  apiPut<FieldReportRow>(`${P(projectId)}/field-reports/${reportId}/links`, body, { headers: HEADERS });
export const fetchReportElements = (projectId: string, reportId: string) =>
  apiGet<ReportElements>(`${P(projectId)}/field-reports/${reportId}/elements`, { headers: HEADERS });
export const reportViewerUrl = (projectId: string, e: ReportElements) =>
  viewerUrl(projectId, { position_id: '', boq_id: '', model_id: e.model_id, keys: e.keys, element_ids: e.element_ids, isolate: e.isolate });

export const syncLinks = (projectId: string) =>
  apiPost<{ positions: number; element_links: number; activities: number }>(`${P(projectId)}/links/sync`, {}, { headers: HEADERS });

// Where the ERP shows each thing. The BOQ grid highlights ?highlight=, tendering opens ?package=, the viewer
// isolates ?isolate= (element ids) — the ERP's own deep links.
export const boqUrl = (p: Pick<LinkedPosition, 'boq_id' | 'position_id'>) =>
  `/boq/${p.boq_id}?highlight=${encodeURIComponent(p.position_id)}`;
export const scheduleUrl = (a: Pick<LinkedActivity, 'schedule_id'>) => `/schedule/${a.schedule_id}/cpm`;
export const packageUrl = (k: Pick<LinkedPackage, 'package_id'>) => `/tendering?package=${encodeURIComponent(k.package_id)}`;
export function viewerUrl(projectId: string, e: PositionElements): string | null {
  if (!e.model_id) return null;
  const base = `/projects/${projectId}/bim/${e.model_id}`;
  return e.isolate && e.isolate.length > 0 ? `${base}?isolate=${e.isolate.join(',')}` : base;
}
export const editorUrl = (keys: string[]) => `/design/editor?select=${encodeURIComponent(keys.slice(0, 50).join(','))}`;

/** Element keys from a deep link; at most 50, the rest is left to the person. */
export function selectionFromUrl(raw: string | null): SelectedElement[] {
  if (!raw) return [];
  return [...new Set(raw.split(',').map((k) => k.trim()).filter((k) => /^[A-Za-z0-9_$][A-Za-z0-9._#/:$-]*$/.test(k)))]
    .slice(0, 50).map((element_key) => ({ element_key }));
}

export interface ContextDocument {
  document_id: string; name: string; category: string; version: number; link_type: string;
  revision: number | null; elements: string[]; url: string;
}
export interface ContextRemark {
  kind: 'task' | 'punch'; id: string; title: string; status: string; due: string | null; elements: string[]; url: string;
}
export interface ElementContext {
  keys: string[]; found: number;
  quantities: { kind: 'length_m' | 'area_m2' | 'volume_m3' | 'weight_kg' | 'count' | 'area_gross_m2' | 'volume_gross_m3'; value: string }[];
  documents: ContextDocument[]; remarks: ContextRemark[];
}

/** Model quantities, linked documents and open remarks of the selected elements. */
export function fetchElementContext(projectId: string, keys: string[]): Promise<ElementContext> {
  const q = new URLSearchParams();
  for (const k of keys.slice(0, MAX_KEYS)) q.append('keys', k);
  return apiGet<ElementContext>(`${P(projectId)}/element-context?${q.toString()}`, { headers: HEADERS });
}
