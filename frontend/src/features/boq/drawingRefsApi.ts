// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Drawing traceability of BOQ lines: which sheet and revision each position was
 * measured from, and whether the sheet has been revised since.
 */

import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiGet, apiPut } from '@/shared/lib/api';

export interface DrawingRef {
  /** Project Files document id. */
  document_id: string | null;
  takeoff_document_id: string | null;
  sheet_id: string | null;
  drawing_number: string | null;
  drawing_title: string | null;
  revision: string | null;
  current_revision: string | null;
  page: number;
  measurement_count: number;
  outdated: boolean;
  /** Takeoff document ids for the PDF compare drawer. */
  compare: { from_document_id: string; to_document_id: string } | null;
}

export interface ManualDrawingRef {
  drawing_ref: string;
  drawing_revision: string | null;
}

export interface PositionDrawingRefs {
  position_id: string;
  ordinal: string;
  outdated: boolean;
  manual: ManualDrawingRef | null;
  refs: DrawingRef[];
}

export interface BoqDrawingRefs {
  boq_id: string;
  outdated_count: number;
  items: PositionDrawingRefs[];
}

export interface ManualDrawingRefPayload {
  drawing_ref: string | null;
  drawing_revision: string | null;
}

export const drawingRefsKey = (boqId: string | undefined) => ['boq-drawing-refs', boqId] as const;

export const drawingRefsApi = {
  list: (boqId: string): Promise<BoqDrawingRefs> =>
    apiGet<BoqDrawingRefs>(`/v1/takeoff/boq/${boqId}/drawing-refs/?outdated_only=false`),
  setManual: (boqId: string, positionId: string, body: ManualDrawingRefPayload) =>
    apiPut<PositionDrawingRefs, ManualDrawingRefPayload>(
      `/v1/takeoff/boq/${boqId}/positions/${positionId}/drawing-ref/`,
      body,
    ),
};

/** Drawing references of every position of the bill, keyed by position id. */
export function useBoqDrawingRefs(boqId: string | undefined) {
  const query = useQuery({
    queryKey: drawingRefsKey(boqId),
    queryFn: () => drawingRefsApi.list(boqId!),
    enabled: !!boqId,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const byPosition = useMemo(() => {
    const map = new Map<string, PositionDrawingRefs>();
    const items = query.data?.items;
    for (const it of Array.isArray(items) ? items : []) map.set(it.position_id, it);
    return map;
  }, [query.data]);
  return { query, byPosition, outdatedCount: query.data?.outdated_count ?? 0 };
}

/** Manual drawing reference of one position; empty `drawing_ref` clears it. */
export function useSetManualDrawingRef(boqId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ positionId, body }: { positionId: string; body: ManualDrawingRefPayload }) =>
      drawingRefsApi.setManual(boqId!, positionId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: drawingRefsKey(boqId) }),
  });
}

/** Viewer link that opens the sheet at the page the quantity was measured on. */
export function drawingRefViewerUrl(ref: DrawingRef): string | null {
  const params = new URLSearchParams();
  params.set('tab', 'measurements');
  if (ref.takeoff_document_id) {
    params.set('doc', ref.takeoff_document_id);
  } else if (ref.document_id) {
    params.set('doc', ref.document_id);
    params.set('source', 'document');
  } else {
    return null;
  }
  if (ref.page > 0) params.set('page', String(ref.page));
  return `/takeoff?${params.toString()}`;
}

/** "A-101 · rev C" - number and revision, whichever of them is known. */
export function drawingRefLabel(
  ref: { drawing_number?: string | null; drawing_ref?: string; revision?: string | null; drawing_revision?: string | null },
  t?: (key: string, opts?: Record<string, string | number>) => string,
): string {
  const number = ref.drawing_number ?? ref.drawing_ref ?? '';
  const rev = ref.revision ?? ref.drawing_revision ?? '';
  const revText = rev
    ? t
      ? t('boq.drawing_ref.rev', { defaultValue: 'rev {{rev}}', rev })
      : `rev ${rev}`
    : '';
  return [number, revText].filter(Boolean).join(' · ');
}

/** Filter predicate: position sits on a revised drawing. */
export function isOnOutdatedDrawing(
  refs: Map<string, PositionDrawingRefs> | undefined,
  positionId: string,
): boolean {
  return refs?.get(positionId)?.outdated === true;
}
