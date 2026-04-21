/**
 * Unified markup aggregator (read-only) — Option B.
 *
 * Joins the three heterogeneous annotation stores into a single feed:
 *
 *   1. Markups hub      — POST /v1/markups/        (per-project, optional document_id)
 *   2. DWG takeoff      — POST /v1/dwg_takeoff/annotations/   (per-drawing)
 *   3. PDF takeoff      — POST /v1/takeoff/measurements/      (per-project + document_id)
 *
 * Rationale for Option B (frontend aggregator) over Option A (extend Markups table):
 *
 *   - DWG annotations live on `drawing_id`; PDF measurements live on
 *     `document_id`; hub markups live on `project_id`. Columns, indexes
 *     and RBAC rules differ.
 *   - Retrofitting a discriminator onto the `oe_markups_markup` table would
 *     require migrations across three test suites and risk breaking the
 *     existing DWG/PDF write paths.
 *   - Each source already exposes a project-scoped read endpoint, so the
 *     frontend can safely merge the three lists in-memory. Filter chips
 *     + click-through then work without any schema change.
 *
 * All functions in this file are pure (no React, no fetch). The hook that
 * wires them up lives in ``useUnifiedMarkups.ts`` and is consumed by the
 * Markups hub page.
 */

import type { Markup, MarkupType } from './api';
import type { DwgAnnotation, DwgDrawing } from '@/features/dwg-takeoff/api';
import type { MeasurementResponse } from '@/features/takeoff/api';

/* ── Source discriminators ───────────────────────────────────────────── */

export type UnifiedMarkupSource = 'markups_hub' | 'pdf_takeoff' | 'dwg_takeoff';

/** Canonical set of annotation types displayed in the hub.
 *  All three surfaces are normalised to this vocabulary. */
export type UnifiedMarkupType =
  | 'cloud'
  | 'arrow'
  | 'text'
  | 'rectangle'
  | 'highlight'
  | 'distance'
  | 'area'
  | 'count'
  | 'stamp'
  | 'polygon'
  | 'polyline'
  | 'circle'
  | 'text_pin'
  | 'line'
  | 'volume'
  | 'other';

/** Minimal shape produced by the aggregator. A single card/row per entry. */
export interface UnifiedMarkup {
  /** Globally unique across sources — prefixed with source kind. */
  id: string;
  /** The underlying source record id (no prefix). */
  nativeId: string;
  source: UnifiedMarkupSource;
  projectId: string;
  /** Drawing id (DWG) or document id (PDF / hub). Null for orphan hub rows. */
  sourceFileId: string | null;
  /** Human-readable file name for filter chips + display. */
  sourceFileName: string;
  type: UnifiedMarkupType;
  /** Page number for PDFs. `null` for DWG. */
  page: number | null;
  /** Short label or derived description ("Distance", first chars of text). */
  label: string;
  text: string | null;
  color: string;
  status: 'active' | 'resolved' | 'archived';
  author: string;
  createdAt: string;
  /** Target route to navigate to on click. */
  deepLink: string;
}

/* ── Normaliser helpers ──────────────────────────────────────────────── */

const TYPE_WHITELIST: ReadonlySet<UnifiedMarkupType> = new Set<UnifiedMarkupType>([
  'cloud',
  'arrow',
  'text',
  'rectangle',
  'highlight',
  'distance',
  'area',
  'count',
  'stamp',
  'polygon',
  'polyline',
  'circle',
  'text_pin',
  'line',
  'volume',
  'other',
]);

function coerceType(t: string | null | undefined): UnifiedMarkupType {
  if (!t) return 'other';
  return TYPE_WHITELIST.has(t as UnifiedMarkupType) ? (t as UnifiedMarkupType) : 'other';
}

function truncate(s: string | null | undefined, max = 80): string {
  if (!s) return '';
  const clean = String(s).trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}\u2026` : clean;
}

/* ── Normalisers (one per source) ────────────────────────────────────── */

export function fromMarkupsHub(
  m: Markup,
  opts: { documentName?: string | null } = {},
): UnifiedMarkup {
  const docName = opts.documentName ?? (m.document_id ? m.document_id.slice(0, 8) : 'Unassigned');
  return {
    id: `hub:${m.id}`,
    nativeId: m.id,
    source: 'markups_hub',
    projectId: m.project_id,
    sourceFileId: m.document_id,
    sourceFileName: docName,
    type: coerceType(m.type as MarkupType),
    page: m.page ?? null,
    label: m.label || truncate(m.text) || m.type,
    text: m.text,
    color: m.color || '#3b82f6',
    status: (m.status as UnifiedMarkup['status']) || 'active',
    author: m.created_by || m.author_id || 'unknown',
    createdAt: m.created_at,
    deepLink: m.document_id
      ? `/markups?documentId=${encodeURIComponent(m.document_id)}&markupId=${m.id}`
      : `/markups?markupId=${m.id}`,
  };
}

export function fromDwgAnnotation(
  a: DwgAnnotation,
  drawing: Pick<DwgDrawing, 'id' | 'project_id' | 'name' | 'filename'>,
): UnifiedMarkup {
  // The backend serialises this column as ``annotation_type`` (Pydantic
  // field name), but the TS interface calls it ``type``. Read both so the
  // aggregator works regardless of whether the caller has already remapped.
  const rawType =
    (a as unknown as { annotation_type?: string }).annotation_type ?? a.type;
  return {
    id: `dwg:${a.id}`,
    nativeId: a.id,
    source: 'dwg_takeoff',
    projectId: drawing.project_id,
    sourceFileId: drawing.id,
    sourceFileName: drawing.name || drawing.filename || drawing.id.slice(0, 8),
    type: coerceType(rawType),
    page: null,
    label: truncate(a.text) || (rawType ?? 'annotation').replace(/_/g, ' '),
    text: a.text,
    color: a.color || '#3b82f6',
    // DWG annotations don't carry status yet — treat as active.
    status: 'active',
    author: a.created_by || 'unknown',
    createdAt: a.created_at,
    deepLink: `/dwg-takeoff?drawingId=${drawing.id}&annotationId=${a.id}`,
  };
}

export function fromPdfMeasurement(
  m: MeasurementResponse,
  opts: { documentName?: string | null } = {},
): UnifiedMarkup {
  const docName =
    opts.documentName ?? (m.document_id ? m.document_id : 'PDF takeoff');
  const label =
    (m.annotation && m.annotation.trim()) ||
    (m.type === 'count'
      ? `${m.count_value ?? 0} ${m.measurement_unit}`
      : m.measurement_value != null
        ? `${m.measurement_value} ${m.measurement_unit}`
        : m.type);
  return {
    id: `pdf:${m.id}`,
    nativeId: m.id,
    source: 'pdf_takeoff',
    projectId: m.project_id,
    sourceFileId: m.document_id,
    sourceFileName: docName,
    type: coerceType(m.type),
    page: m.page ?? null,
    label: truncate(label),
    text: (m.metadata?.text as string) ?? null,
    color: m.group_color || '#3b82f6',
    status: 'active',
    author: m.created_by || 'unknown',
    createdAt: m.created_at,
    deepLink: m.document_id
      ? `/takeoff?tab=measurements&docId=${encodeURIComponent(m.document_id)}&measurementId=${m.id}`
      : `/takeoff?tab=measurements&measurementId=${m.id}`,
  };
}

/* ── Merge + filter + sort ──────────────────────────────────────────── */

export interface UnifiedFilters {
  sources?: ReadonlySet<UnifiedMarkupSource>;
  types?: ReadonlySet<UnifiedMarkupType>;
  fileIds?: ReadonlySet<string>;
  /** Full-text substring match against label / text / file name. */
  search?: string;
}

/** Merge any number of already-normalised lists, newest-first. */
export function mergeUnified(
  ...lists: ReadonlyArray<ReadonlyArray<UnifiedMarkup>>
): UnifiedMarkup[] {
  const all = lists.flatMap((l) => l.slice());
  all.sort((a, b) => {
    // Newest first. Fall back to stable id ordering when timestamps are equal
    // (important for deterministic test output on the same millisecond).
    if (a.createdAt === b.createdAt) return a.id.localeCompare(b.id);
    return a.createdAt < b.createdAt ? 1 : -1;
  });
  return all;
}

/** Apply filter chips — all criteria are AND-combined. */
export function applyFilters(
  items: ReadonlyArray<UnifiedMarkup>,
  filters: UnifiedFilters,
): UnifiedMarkup[] {
  const { sources, types, fileIds, search } = filters;
  const q = (search ?? '').trim().toLowerCase();
  return items.filter((m) => {
    if (sources && sources.size > 0 && !sources.has(m.source)) return false;
    if (types && types.size > 0 && !types.has(m.type)) return false;
    if (fileIds && fileIds.size > 0) {
      if (!m.sourceFileId || !fileIds.has(m.sourceFileId)) return false;
    }
    if (q) {
      const hay = `${m.label} ${m.text ?? ''} ${m.sourceFileName} ${m.type}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

/** Summary counts for the filter toolbar. Purely derived. */
export interface UnifiedSummary {
  total: number;
  bySource: Record<UnifiedMarkupSource, number>;
  byType: Partial<Record<UnifiedMarkupType, number>>;
  /** file id → file name (for the file filter dropdown). */
  files: Array<{ id: string; name: string }>;
}

export function summarise(items: ReadonlyArray<UnifiedMarkup>): UnifiedSummary {
  const bySource: Record<UnifiedMarkupSource, number> = {
    markups_hub: 0,
    pdf_takeoff: 0,
    dwg_takeoff: 0,
  };
  const byType: Partial<Record<UnifiedMarkupType, number>> = {};
  const fileMap = new Map<string, string>();
  for (const m of items) {
    bySource[m.source] += 1;
    byType[m.type] = (byType[m.type] ?? 0) + 1;
    if (m.sourceFileId && !fileMap.has(m.sourceFileId)) {
      fileMap.set(m.sourceFileId, m.sourceFileName);
    }
  }
  const files = Array.from(fileMap.entries())
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return { total: items.length, bySource, byType, files };
}
