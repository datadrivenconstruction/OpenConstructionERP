// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Pure helpers for the Surveys panel: variance status, observed % parsing,
// upload form validation and the two-date compare slider. No React, no I/O.

import type { BadgeVariant } from '@/shared/ui';

import type { SurveyCapture, SurveyPlatform, SurveyStatus } from './types';
import { fmtFixed } from '@/shared/lib/formatters';

/** Mirrors backend ``survey_logic.DEFAULT_TOLERANCE_PCT``. */
export const DEFAULT_TOLERANCE_PCT = 5;

export const SURVEY_PLATFORMS: SurveyPlatform[] = ['drone', 'aircraft', 'ground', 'other'];

/** ``observed - planned`` in points: ahead above tolerance, behind below it. */
export function statusFor(
  variance: number | null | undefined,
  tolerance: number = DEFAULT_TOLERANCE_PCT,
): SurveyStatus {
  if (variance === null || variance === undefined || Number.isNaN(variance)) return 'unobserved';
  if (Math.abs(variance) <= tolerance) return 'on_track';
  return variance > 0 ? 'ahead' : 'behind';
}

export interface VarianceBadge {
  variant: BadgeVariant;
  labelKey: string;
  labelDefault: string;
}

const BADGES: Record<SurveyStatus, VarianceBadge> = {
  ahead: { variant: 'blue', labelKey: 'geo_hub.surveys.status.ahead', labelDefault: 'Ahead' },
  on_track: { variant: 'success', labelKey: 'geo_hub.surveys.status.on_track', labelDefault: 'On track' },
  behind: { variant: 'error', labelKey: 'geo_hub.surveys.status.behind', labelDefault: 'Behind' },
  unobserved: { variant: 'neutral', labelKey: 'geo_hub.surveys.status.unobserved', labelDefault: 'Not observed' },
};

export function varianceBadge(status: SurveyStatus): VarianceBadge {
  return BADGES[status];
}

/** ``+20.0`` / ``-5.5`` / ``0.0`` points, or an em dash when nothing was observed. */
export function formatVariance(variance: number | null | undefined): string {
  if (variance === null || variance === undefined || Number.isNaN(variance)) return '—';
  const rounded = Math.round(variance * 10) / 10;
  return `${rounded > 0 ? '+' : ''}${fmtFixed(rounded, 1)}`;
}

export type ParsedPct = { ok: true; value: number } | { ok: false };

/** Accepts ``65``, ``65.5`` and ``65,5`` (with an optional ``%``); only 0..100 is valid. */
export function parseObservedPct(raw: string): ParsedPct {
  const cleaned = raw.trim().replace('%', '').replace(',', '.').trim();
  if (cleaned === '' || !/^\d+(\.\d{1,2})?$/.test(cleaned)) return { ok: false };
  const value = Number(cleaned);
  return value >= 0 && value <= 100 ? { ok: true, value } : { ok: false };
}

/** English defaults for the keys built from a code; the locale bundles carry the translations. */
export const UPLOAD_ERROR_DEFAULT: Record<string, string> = {
  source_required: 'Choose a GeoTIFF or an existing scan.',
  file_type: 'Only .tif or .tiff files are accepted.',
  date_required: 'Pick the flight date.',
  date_future: 'The flight date cannot be in the future.',
};
export const PLATFORM_DEFAULT: Record<SurveyPlatform, string> = {
  drone: 'Drone',
  aircraft: 'Aircraft',
  ground: 'Ground',
  other: 'Other',
};
export const KIND_DEFAULT: Record<string, string> = {
  orthophoto: 'Orthophoto',
  point_cloud: 'Point cloud',
  dsm: 'Surface model',
};
export const WARNING_DEFAULT: Record<string, string> = {
  not_georeferenced: 'The file has no georeference, so it cannot be placed on the globe.',
  crs_unknown: 'The coordinate system is not an EPSG code, so the file cannot be placed on the globe.',
  crs_transform_unavailable: 'The coordinate system could not be converted to WGS84 on this server.',
};

export type UploadFormError = 'source_required' | 'file_type' | 'date_required' | 'date_future';

export interface UploadFormState {
  file: { name: string } | null;
  scanId: string | null;
  capturedOn: string;
}

/** ``today`` is ``YYYY-MM-DD``. Mirrors the server rules so the user hears about a problem before the upload. */
export function validateUploadForm(state: UploadFormState, today: string): UploadFormError[] {
  const errors: UploadFormError[] = [];
  if (!state.file && !state.scanId) errors.push('source_required');
  else if (state.file && !/\.tiff?$/i.test(state.file.name)) errors.push('file_type');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(state.capturedOn)) errors.push('date_required');
  else if (state.capturedOn > today) errors.push('date_future');
  return errors;
}

/** Local calendar day as ``YYYY-MM-DD`` (the date picker default). */
export function todayIso(now: Date = new Date()): string {
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${m}-${d}`;
}

/** Newest capture first; equal dates keep a stable order by creation time. */
export function sortSurveys<T extends Pick<SurveyCapture, 'captured_on' | 'created_at'>>(list: T[]): T[] {
  return [...list].sort(
    (a, b) => b.captured_on.localeCompare(a.captured_on) || b.created_at.localeCompare(a.created_at),
  );
}

/** Slider 0 shows the earlier survey, 1 the later one; the overlay opacity control does the blend. */
export function compareOpacities(position: number): { earlier: number; later: number } {
  const p = Math.min(1, Math.max(0, Number.isFinite(position) ? position : 0));
  return { earlier: Math.round((1 - p) * 100) / 100, later: Math.round(p * 100) / 100 };
}

/** ``3.2 cm/px``; the backend sends centimetres. */
export function formatGsd(gsdCm: string | number | null | undefined): string | null {
  if (gsdCm === null || gsdCm === undefined || gsdCm === '') return null;
  const n = Number(gsdCm);
  if (!Number.isFinite(n)) return null;
  return n >= 100 ? `${fmtFixed(n / 100, 2)} m/px` : `${fmtFixed(n, 1)} cm/px`;
}

export function formatSize(width: number | null | undefined, height: number | null | undefined): string | null {
  return width && height ? `${width} × ${height} px` : null;
}
