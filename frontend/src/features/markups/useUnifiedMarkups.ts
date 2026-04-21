/**
 * React hook that wires the three source-specific APIs into the unified
 * aggregator.
 *
 * - Uses React Query under the hood so the hub survives navigation + refresh
 *   (cache is shared with the native DWG/PDF/Hub queries already in the app).
 * - Network failures on one source degrade gracefully — the other two still
 *   populate the feed.
 * - Invalidation is centralised on the ``['unified-markups', projectId]``
 *   key so the source modules can refresh the hub without knowing its
 *   internals (see ``invalidateUnifiedMarkups`` below).
 */

import { useMemo } from 'react';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { apiGet } from '@/shared/lib/api';
import { fetchMarkups } from './api';
import { fetchDrawings, fetchAnnotations } from '@/features/dwg-takeoff/api';
import { takeoffApi, type MeasurementResponse } from '@/features/takeoff/api';
import type { DwgAnnotation, DwgDrawing } from '@/features/dwg-takeoff/api';

import {
  fromDwgAnnotation,
  fromMarkupsHub,
  fromPdfMeasurement,
  mergeUnified,
  summarise,
  type UnifiedMarkup,
  type UnifiedSummary,
} from './aggregator';

/** Minimal shape used for file-name lookup by the Markups hub. */
interface DocItem {
  id: string;
  name: string;
}

interface UseUnifiedMarkupsResult {
  items: UnifiedMarkup[];
  summary: UnifiedSummary;
  isLoading: boolean;
  error: Error | null;
}

/** Key used by all Query entries this hook produces. Exported so source
 *  modules can invalidate it after creating a new annotation. */
export const UNIFIED_MARKUPS_QUERY_KEY = ['unified-markups'] as const;

/** Invalidate the unified feed (use from source modules after create/delete). */
export function invalidateUnifiedMarkups(qc: QueryClient, projectId?: string): void {
  if (projectId) {
    qc.invalidateQueries({ queryKey: [...UNIFIED_MARKUPS_QUERY_KEY, projectId] });
  } else {
    qc.invalidateQueries({ queryKey: UNIFIED_MARKUPS_QUERY_KEY });
  }
}

/* ── Hook ────────────────────────────────────────────────────────────── */

export function useUnifiedMarkups(projectId: string | null | undefined): UseUnifiedMarkupsResult {
  // Hub markups — already project-scoped.
  const hubQuery = useQuery({
    queryKey: [...UNIFIED_MARKUPS_QUERY_KEY, projectId, 'hub'],
    queryFn: () => fetchMarkups(projectId as string),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  // Documents lookup — lets us show friendly names instead of UUID prefixes.
  const documentsQuery = useQuery({
    queryKey: [...UNIFIED_MARKUPS_QUERY_KEY, projectId, 'documents'],
    queryFn: () => apiGet<DocItem[]>(`/v1/documents/?project_id=${projectId}`),
    enabled: !!projectId,
    staleTime: 60_000,
  });

  // DWG — per-project drawings, then per-drawing annotations.
  const drawingsQuery = useQuery<DwgDrawing[]>({
    queryKey: [...UNIFIED_MARKUPS_QUERY_KEY, projectId, 'dwg-drawings'],
    queryFn: () => fetchDrawings(projectId as string),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const dwgAnnotationsQuery = useQuery<DwgAnnotation[]>({
    queryKey: [
      ...UNIFIED_MARKUPS_QUERY_KEY,
      projectId,
      'dwg-annotations',
      (drawingsQuery.data ?? []).map((d) => d.id).join(','),
    ],
    queryFn: async () => {
      const drawings = drawingsQuery.data ?? [];
      if (drawings.length === 0) return [];
      // Fire in parallel; tolerate per-drawing failures so one broken
      // drawing doesn't blank the whole feed.
      const settled = await Promise.allSettled(
        drawings.map((d) => fetchAnnotations(d.id)),
      );
      const out: DwgAnnotation[] = [];
      for (const r of settled) {
        if (r.status === 'fulfilled') out.push(...r.value);
      }
      return out;
    },
    enabled: !!projectId && !!drawingsQuery.data,
    staleTime: 30_000,
  });

  // PDF takeoff measurements — already project-scoped. We only display the
  // annotation-style types in the hub; the full list is filtered at render.
  const pdfQuery = useQuery<MeasurementResponse[]>({
    queryKey: [...UNIFIED_MARKUPS_QUERY_KEY, projectId, 'pdf-measurements'],
    queryFn: () => takeoffApi.list(projectId as string),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const { items, summary } = useMemo(() => {
    const docNameById = new Map<string, string>();
    for (const d of documentsQuery.data ?? []) docNameById.set(d.id, d.name);

    const drawingById = new Map<string, DwgDrawing>();
    for (const d of drawingsQuery.data ?? []) drawingById.set(d.id, d);

    const hub = (hubQuery.data ?? []).map((m) =>
      fromMarkupsHub(m, {
        documentName: m.document_id ? docNameById.get(m.document_id) ?? null : null,
      }),
    );

    const dwg = (dwgAnnotationsQuery.data ?? [])
      .map((a) => {
        const drawing = drawingById.get(a.drawing_id);
        if (!drawing) return null;
        return fromDwgAnnotation(a, drawing);
      })
      .filter((x): x is UnifiedMarkup => x !== null);

    const pdf = (pdfQuery.data ?? []).map((m) =>
      fromPdfMeasurement(m, {
        documentName: m.document_id ? docNameById.get(m.document_id) ?? m.document_id : null,
      }),
    );

    const merged = mergeUnified(hub, dwg, pdf);
    return { items: merged, summary: summarise(merged) };
  }, [
    hubQuery.data,
    dwgAnnotationsQuery.data,
    pdfQuery.data,
    drawingsQuery.data,
    documentsQuery.data,
  ]);

  const isLoading =
    hubQuery.isLoading ||
    drawingsQuery.isLoading ||
    dwgAnnotationsQuery.isLoading ||
    pdfQuery.isLoading;

  // Surface the first real error, but never block render — partial data is
  // better than an empty page when one source is offline.
  const error =
    (hubQuery.error as Error | undefined) ??
    (drawingsQuery.error as Error | undefined) ??
    (dwgAnnotationsQuery.error as Error | undefined) ??
    (pdfQuery.error as Error | undefined) ??
    null;

  return { items, summary, isLoading, error };
}

/** Hook consumers export this so the DWG/PDF modules can trigger a refresh
 *  without circular imports. */
export function useInvalidateUnifiedMarkups(): (projectId?: string) => void {
  const qc = useQueryClient();
  return (projectId?: string) => invalidateUnifiedMarkups(qc, projectId);
}
