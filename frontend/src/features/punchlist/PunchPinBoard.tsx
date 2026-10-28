// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Visual pin board: punch items rendered as numbered pins over the drawing
 * sheet they are pinned to.
 *
 * Self-contained pdf.js viewer (kept separate from the markups annotator, which
 * owns a full annotation toolbar we do not want here). Pins use the punch item's
 * normalised location_x/location_y (0..1), so they are positioned as a
 * percentage over the rendered page and stay correct at any zoom without any
 * coordinate maths.
 *
 * Click-to-place: pick an item, enter placement mode, then click the sheet to
 * drop the pin. The click is normalised to 0..1 and written through the shipped
 * pin-to-sheet endpoint. Clicking an existing pin opens that item.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { closePdf, openPdf, type PDFDocumentProxy, type RenderTask } from '@/shared/lib/pdfjs';
import {
  ChevronLeft,
  ChevronRight,
  Crosshair,
  Loader2,
  MapPin,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import clsx from 'clsx';
import { Button } from '@/shared/ui';
import { API_BASE, getAuthToken } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { pinPunchToSheet, type PunchDrawing, type PunchItem, type PunchPriority } from './api';

const ZOOM_LEVELS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];
const BASE_SCALE = 1.3;

/** Pin dot colour by priority so urgent snags read at a glance. */
const PIN_COLOR: Record<PunchPriority, string> = {
  low: '#6b7280',
  medium: '#eab308',
  high: '#f97316',
  critical: '#ef4444',
};

interface Props {
  /** All punch items for the project (source of both pins and placement list). */
  items: PunchItem[];
  /** Documents that can be shown as drawings. */
  drawings: PunchDrawing[];
  /** Open the detail drawer for an item (pin click). */
  onOpenItem: (item: PunchItem) => void;
  /** Called after a successful pin so the parent can refetch. */
  onPinned: () => void;
  /** Optional document/page to open on first render (from "open on pin board"). */
  initialDocId?: string | null;
  initialPage?: number | null;
}

export function PunchPinBoard({
  items,
  drawings,
  onOpenItem,
  onPinned,
  initialDocId,
  initialPage,
}: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // Documents that already carry at least one pinned punch, so we can default
  // to a useful sheet rather than a blank first document.
  const pinnedDocIds = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) {
      if (it.document_id && it.location_x != null && it.location_y != null) {
        set.add(it.document_id);
      }
    }
    return set;
  }, [items]);

  const defaultDocId = useMemo(() => {
    if (initialDocId && drawings.some((d) => d.id === initialDocId)) return initialDocId;
    const firstPinned = drawings.find((d) => pinnedDocIds.has(d.id));
    return firstPinned?.id ?? drawings[0]?.id ?? '';
  }, [initialDocId, drawings, pinnedDocIds]);

  const [selectedDocId, setSelectedDocId] = useState(defaultDocId);
  const [currentPage, setCurrentPage] = useState(initialPage && initialPage > 0 ? initialPage : 1);
  const [totalPages, setTotalPages] = useState(0);
  const [zoomIdx, setZoomIdx] = useState(2);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [placingItemId, setPlacingItemId] = useState<string>('');
  const [placing, setPlacing] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);

  // Keep the selected document in sync when the default resolves later (e.g.
  // drawings load after mount) but never fight a user selection.
  useEffect(() => {
    if (!selectedDocId && defaultDocId) setSelectedDocId(defaultDocId);
  }, [defaultDocId, selectedDocId]);

  const zoom = ZOOM_LEVELS[zoomIdx] ?? 1.0;

  /* ── Load the PDF document ─────────────────────────────────────────── */
  useEffect(() => {
    if (!selectedDocId) {
      pdfRef.current = null;
      setTotalPages(0);
      return;
    }
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    setIsLoading(true);
    setLoadError(false);
    (async () => {
      try {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/v1/documents/${selectedDocId}/download/`, {
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            'X-DDC-Client': 'OE/1.0',
          },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = await res.arrayBuffer();
        if (cancelled) return;
        const doc = await openPdf(buf).promise;
        if (cancelled) {
          closePdf(doc);
          return;
        }
        loaded = doc;
        pdfRef.current = doc;
        setTotalPages(doc.numPages);
        setCurrentPage((p) => Math.min(Math.max(1, p), doc.numPages));
      } catch {
        if (!cancelled) {
          setLoadError(true);
          pdfRef.current = null;
          setTotalPages(0);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      closePdf(loaded);
    };
  }, [selectedDocId]);

  /* ── Render the current page ───────────────────────────────────────── */
  useEffect(() => {
    const doc = pdfRef.current;
    if (!doc || !canvasRef.current || totalPages === 0) return;
    let cancelled = false;
    let task: RenderTask | null = null;
    (async () => {
      try {
        const page = await doc.getPage(currentPage);
        if (cancelled) return;
        const viewport = page.getViewport({ scale: zoom * BASE_SCALE });
        const canvas = canvasRef.current;
        if (!canvas) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        task = page.render({ canvas, viewport });
        await task.promise;
      } catch (err) {
        if (err && (err as { name?: string }).name !== 'RenderingCancelledException') {
          if (import.meta.env.DEV) console.warn('Punch pin-board render failed', err);
        }
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel?.();
    };
  }, [currentPage, zoom, totalPages]);

  /* ── Pins on the current sheet + page ──────────────────────────────── */
  const pins = useMemo(() => {
    return items
      .filter(
        (it) =>
          it.document_id === selectedDocId &&
          (it.page ?? 1) === currentPage &&
          it.location_x != null &&
          it.location_y != null,
      )
      .sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
  }, [items, selectedDocId, currentPage]);

  /* ── Placement ─────────────────────────────────────────────────────── */
  const pinMut = useMutation({
    mutationFn: ({ id, x, y }: { id: string; x: number; y: number }) =>
      pinPunchToSheet(id, {
        document_id: selectedDocId,
        page: currentPage,
        location_x: x,
        location_y: y,
      }),
    onSuccess: () => {
      onPinned();
      setPlacing(false);
      addToast({
        type: 'success',
        title: t('punch.pin_placed', { defaultValue: 'Pin placed on the drawing' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('punch.pin_failed', { defaultValue: 'Could not place the pin' }),
        message: e.message,
      }),
  });

  const handlePlaceClick = useCallback(
    (e: React.MouseEvent) => {
      if (!placing || !placingItemId) return;
      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
      pinMut.mutate({ id: placingItemId, x, y });
    },
    [placing, placingItemId, pinMut],
  );

  // Items that can be placed: everything not already pinned to THIS sheet+page
  // (re-pinning an item that lives elsewhere is still allowed by selecting it).
  const placeableItems = useMemo(() => {
    const onSheet = new Set(pins.map((p) => p.id));
    return items.filter((it) => !onSheet.has(it.id));
  }, [items, pins]);

  const startPlacing = useCallback(() => {
    if (!placingItemId) {
      addToast({
        type: 'info',
        title: t('punch.pick_item_first', { defaultValue: 'Pick an item to place first' }),
      });
      return;
    }
    setPlacing(true);
  }, [placingItemId, addToast, t]);

  const hasDrawings = drawings.length > 0;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
      {/* ── Sheet ─────────────────────────────────────────────────────── */}
      <div className="rounded-xl border border-border-light bg-surface-primary">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-border-light px-3 py-2">
          <select
            value={selectedDocId}
            onChange={(e) => {
              setSelectedDocId(e.target.value);
              setCurrentPage(1);
              setPlacing(false);
            }}
            aria-label={t('punch.select_drawing', { defaultValue: 'Select drawing' })}
            className="h-9 max-w-[240px] flex-1 rounded-lg border border-border bg-surface-primary px-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {!hasDrawings && (
              <option value="">{t('punch.no_drawings', { defaultValue: 'No drawings' })}</option>
            )}
            {drawings.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename || d.id.slice(0, 8)}
              </option>
            ))}
          </select>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              aria-label={t('punch.prev_page', { defaultValue: 'Previous page' })}
              className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="min-w-[52px] text-center text-xs tabular-nums text-content-secondary">
              {totalPages > 0 ? `${currentPage} / ${totalPages}` : '-'}
            </span>
            <button
              type="button"
              onClick={() => setCurrentPage((p) => Math.min(totalPages || 1, p + 1))}
              disabled={totalPages === 0 || currentPage >= totalPages}
              aria-label={t('punch.next_page', { defaultValue: 'Next page' })}
              className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setZoomIdx((i) => Math.max(0, i - 1))}
              disabled={zoomIdx <= 0}
              aria-label={t('punch.zoom_out', { defaultValue: 'Zoom out' })}
              className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
            >
              <ZoomOut size={16} />
            </button>
            <span className="w-10 text-center text-2xs tabular-nums text-content-tertiary">
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              onClick={() => setZoomIdx((i) => Math.min(ZOOM_LEVELS.length - 1, i + 1))}
              disabled={zoomIdx >= ZOOM_LEVELS.length - 1}
              aria-label={t('punch.zoom_in', { defaultValue: 'Zoom in' })}
              className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
            >
              <ZoomIn size={16} />
            </button>
          </div>

          {placing && (
            <span className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-oe-blue/10 px-2 py-1 text-xs font-medium text-oe-blue">
              <Crosshair size={13} />
              {t('punch.click_to_place', { defaultValue: 'Click the drawing to drop the pin' })}
              <button
                type="button"
                onClick={() => setPlacing(false)}
                aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
                className="ml-1 rounded hover:bg-oe-blue/20"
              >
                <X size={13} />
              </button>
            </span>
          )}
        </div>

        {/* Canvas area */}
        <div className="relative max-h-[65vh] overflow-auto bg-neutral-100 p-3 dark:bg-neutral-900">
          {isLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 size={28} className="animate-spin text-oe-blue" />
            </div>
          ) : loadError ? (
            <div className="flex items-center justify-center py-20 text-sm text-content-tertiary">
              {t('punch.sheet_load_error', {
                defaultValue: 'This document could not be shown as a drawing.',
              })}
            </div>
          ) : !selectedDocId ? (
            <div className="flex items-center justify-center py-20 text-sm text-content-tertiary">
              {t('punch.pick_drawing_hint', {
                defaultValue: 'Select a drawing to see and place pins.',
              })}
            </div>
          ) : (
            <div
              ref={wrapperRef}
              className={clsx('relative inline-block', placing && 'cursor-crosshair')}
            >
              <canvas ref={canvasRef} className="block rounded shadow-sm" />

              {/* Existing pins (percentage positioned; zoom-independent). */}
              {pins.map((pin, idx) => {
                const color = PIN_COLOR[pin.priority];
                return (
                  <button
                    key={pin.id}
                    type="button"
                    onClick={() => !placing && onOpenItem(pin)}
                    title={`#${idx + 1} - ${pin.title}`}
                    style={{
                      left: `${(pin.location_x ?? 0) * 100}%`,
                      top: `${(pin.location_y ?? 0) * 100}%`,
                      backgroundColor: color,
                    }}
                    className={clsx(
                      'absolute z-10 flex h-6 w-6 -translate-x-1/2 -translate-y-full items-center justify-center rounded-full rounded-bl-none border-2 border-white text-2xs font-bold text-white shadow-md',
                      placing ? 'pointer-events-none opacity-70' : 'hover:scale-110',
                    )}
                  >
                    {idx + 1}
                  </button>
                );
              })}

              {/* Placement capture overlay - on top so clicks land here. */}
              {placing && (
                <div
                  className="absolute inset-0 z-20"
                  onClick={handlePlaceClick}
                  role="presentation"
                />
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Side panel ────────────────────────────────────────────────── */}
      <div className="space-y-4">
        {/* Place a pin */}
        <div className="rounded-xl border border-border-light bg-surface-primary p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            {t('punch.place_a_pin', { defaultValue: 'Place a pin' })}
          </h4>
          <select
            value={placingItemId}
            onChange={(e) => setPlacingItemId(e.target.value)}
            aria-label={t('punch.select_item_to_place', { defaultValue: 'Select an item to place' })}
            className="mb-2 h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            <option value="">
              {t('punch.choose_item', { defaultValue: 'Choose an item...' })}
            </option>
            {placeableItems.map((it) => (
              <option key={it.id} value={it.id}>
                {it.title.length > 48 ? `${it.title.slice(0, 48)}...` : it.title}
              </option>
            ))}
          </select>
          <Button
            variant="primary"
            size="sm"
            onClick={startPlacing}
            disabled={!selectedDocId || !placingItemId || placing || pinMut.isPending}
            icon={pinMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Crosshair size={14} />}
            className="w-full"
          >
            {placing
              ? t('punch.placing', { defaultValue: 'Click the drawing...' })
              : t('punch.place_on_sheet', { defaultValue: 'Place on sheet' })}
          </Button>
        </div>

        {/* Pins on this sheet */}
        <div className="rounded-xl border border-border-light bg-surface-primary p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            {t('punch.pins_on_sheet', { defaultValue: 'Pins on this sheet' })}
            <span className="ml-1.5 text-content-quaternary">({pins.length})</span>
          </h4>
          {pins.length === 0 ? (
            <p className="text-xs text-content-tertiary">
              {t('punch.no_pins_here', { defaultValue: 'No pins on this page yet.' })}
            </p>
          ) : (
            <ul className="space-y-1">
              {pins.map((pin, idx) => (
                <li key={pin.id}>
                  <button
                    type="button"
                    onClick={() => onOpenItem(pin)}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                  >
                    <span
                      style={{ backgroundColor: PIN_COLOR[pin.priority] }}
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-2xs font-bold text-white"
                    >
                      {idx + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-content-secondary">
                      {pin.title}
                    </span>
                    <MapPin size={13} className="shrink-0 text-content-quaternary" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
