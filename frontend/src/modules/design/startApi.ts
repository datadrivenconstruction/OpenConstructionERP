// Design module (ERP side of the design editor link).
/** Project start: templates, drawings and photos read by the R5 extraction. Nothing here writes the brief. */
import { apiGet, apiPost } from '@/shared/lib/api';
import { uploadDocument } from '@/features/documents/api';
import { LINK_VERSION, type Extraction } from './api';
import type { BriefDoc } from './data/briefModel';

const HEADERS = { 'X-DDC-Link': LINK_VERSION };

export interface TemplateValue { pointer: string; value: string | number | boolean; doubtful: boolean }
export interface StartTemplate { id: string; typology: string; max_floors: number; values: TemplateValue[]; source: string }

export const fetchTemplates = () =>
  apiGet<{ templates: StartTemplate[]; source: string }>('/v1/design/templates', { headers: HEADERS });

/** File types the extraction reads (brief_sources.py): PDF text or pages, DWG/DXF annotations, images. */
export const ACCEPT = ['.pdf', '.dwg', '.dxf', '.png', '.jpg', '.jpeg', '.webp'];
export const MAX_FILES = 20;

export function acceptable(name: string): boolean {
  const i = name.lastIndexOf('.');
  return i > 0 && ACCEPT.includes(name.slice(i).toLowerCase());
}

/** Drawings go to Documents as drawings, photos as other files: they stay in the project and can be cited later. */
export function uploadSource(projectId: string, file: File) {
  const image = /\.(png|jpe?g|webp)$/i.test(file.name);
  return uploadDocument(projectId, file, image ? 'other' : 'drawing');
}

export function extractFromFiles(projectId: string, documentIds: string[], current: BriefDoc | null, text = ''): Promise<Extraction> {
  return apiPost<Extraction, { document_ids: string[]; text: string | null; use_ai: boolean; base: BriefDoc | null }>(
    `/v1/design/projects/${projectId}/brief/extract`,
    { document_ids: documentIds, text: text.trim() || null, use_ai: true, base: current },
    { headers: HEADERS },
  );
}

/** Quick massing from a short brief (design/quick.py): computed on the server, nothing is stored. */
export type Quality = 'economy' | 'standard' | 'high';
export interface QuickBrief {
  building_type: string; gfa_m2: number; storeys: number; country?: string; quality: Quality;
  floor_height_m?: number; depth_m?: number; grid_m?: number; wwr?: number; slab_zone_m?: number;
  plot_area_m2?: number; max_height_m?: number; currency?: string; fx_rate?: string;
}
/** Where a number came from: brief, generator source, country data, benchmark or formula; `ref` names the file. */
export interface Provenance { source: string; ref: string; formula: string | null; status?: string; note?: string }
export interface QuickIssue { code: string; field: string; severity: 'error' | 'warning'; params: Record<string, unknown> }
export interface QuickQuantity { code: string; value: number | null; unit: string; provenance: Provenance; flag: string | null }
export interface QuickLine { code: string; quantity: number | null; unit: string; unit_rate: string | null; amount: string; provenance: Provenance }
export interface QuickCost {
  currency: string | null; total: string | null; per_m2?: string; reason: 'no_band' | 'currency' | null; flag?: string;
  band_currency?: string; lines?: QuickLine[]; needs_expert_review: boolean; base_date: string; ref: string;
  benchmark?: { low: string; mid: string; high: string; within: boolean };
}
export interface QuickPhase { code: string; start_day: number | null; days: number | null; flag: string | null }
export interface QuickSuggestion { pointer: string; value: number | string | boolean; provenance: Provenance }
export interface QuickResult {
  issues: QuickIssue[]; generator: boolean | null; suggestions: QuickSuggestion[];
  model: null | {
    height_m: number; roof_form: string | null; levels: { index: number; elevation_m: number }[];
    footprint: { width_m: number; depth_m: number; area_m2: number };
    grid: { spacing_m: number; bays_x: number; bays_y: number; columns_per_storey: number } | null;
    quantities: QuickQuantity[];
  };
  cost: QuickCost | null;
  schedule: null | { phases: QuickPhase[]; total_days: number | null; reason: string | null };
}

export const fetchQuickTypes = () =>
  apiGet<{ types: { id: string; generator: boolean; priced: boolean }[] }>('/v1/design/quick/types', { headers: HEADERS });

/** In the project: the server takes the project's currency, country and fx_rates. */
export const runQuick = (projectId: string, brief: QuickBrief) =>
  apiPost<QuickResult, QuickBrief>(`/v1/design/projects/${projectId}/quick`, brief, { headers: HEADERS });
