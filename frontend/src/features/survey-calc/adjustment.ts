// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Least-squares traverse adjustment: response types, the demo field book, the
 * PDF report, survey links (site diary, documents) and the sketch geometry.
 */

import { API_BASE, activeLanguageTag, apiGet, apiPost, fetchWithAuth, getErrorMessage, triggerDownload } from '@/shared/lib/api';
import type { FieldTraverseIn, LevelBookIn } from './api';

export type AdjustMethod = 'bowditch' | 'lsq';

export interface InstrumentClass {
  key: string;
  angle_sd_sec: number;
  dist_sd_mm: number;
  dist_ppm: number;
  centering_sd_mm: number;
}

export interface Ellipse {
  ref: string;
  a_m: number;
  b_m: number;
  azimuth_deg: number;
  sd_e_m: number;
  sd_n_m: number;
}

export interface LsqResidual {
  kind: 'angle' | 'distance';
  ref: string;
  observed: number;
  residual: number;
  sd: number;
  redundancy: number;
  standardized: number | null;
  flagged: boolean;
  suspect: boolean;
}

export interface LsqStation {
  station_id: string;
  e: number;
  n: number;
  fixed: boolean;
  d_e_mm: number;
  d_n_mm: number;
}

export interface LsqOut {
  iterations: number;
  observations: number;
  unknowns: number;
  redundancy: number;
  vtpv: number;
  sigma0: number;
  chi2_lower: number;
  chi2_upper: number;
  chi2_pass: boolean;
  alpha: number;
  confidence_95: number;
  angle_sd_sec: number;
  dist_sd_mm: number;
  dist_ppm: number;
  centering_sd_mm: number;
  stations: LsqStation[];
  residuals: LsqResidual[];
  ellipses: Ellipse[];
  relative_ellipses: Ellipse[];
}

export interface CalcDemo {
  traverse: FieldTraverseIn;
  level_book: LevelBookIn;
}

export type SurveyLinkKind = 'traverse' | 'point_set';

export interface DiaryLink {
  entry_id: string;
  diary_id: string;
  diary_date: string;
  title: string;
  crew: string;
  instrument: string;
  weather: string;
}

export interface DocumentLink {
  reference_id: string;
  file_kind: string;
  file_id: string;
  label: string;
}

export interface SurveyLinks {
  kind: SurveyLinkKind;
  target_id: string;
  diary: DiaryLink[];
  documents: DocumentLink[];
}

export interface DiaryLinkIn {
  diary_date: string;
  title: string;
  crew: string;
  instrument: string;
  weather: string;
  note?: string;
}

const loc = () => `locale=${encodeURIComponent(activeLanguageTag() ?? 'en')}`;

export const getCalcDemo = () => apiGet<CalcDemo>(`/v1/survey-core/calc/demo`);

export const getSurveyLinks = (projectId: string, kind: SurveyLinkKind, id: string) =>
  apiGet<SurveyLinks>(`/v1/survey-core/projects/${projectId}/survey-links/${kind}/${id}`);

export const linkDiary = (projectId: string, kind: SurveyLinkKind, id: string, body: DiaryLinkIn) =>
  apiPost<DiaryLink, DiaryLinkIn>(`/v1/survey-core/projects/${projectId}/survey-links/${kind}/${id}/diary`, body);

/** Download the adjustment report; the labels are the reader's language. */
export async function downloadTraverseReport(traverse: FieldTraverseIn, title: string, labels: Record<string, string>): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/v1/survey-core/calc/field-traverse/report?${loc()}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ traverse, title, labels }),
  });
  if (!res.ok) throw new Error(getErrorMessage(await res.json().catch(() => res.statusText)));
  const name = (traverse.name || 'traverse').replace(/[^\w-]+/g, '_').slice(0, 60);
  triggerDownload(await res.blob(), `${name}_adjustment.pdf`);
}
