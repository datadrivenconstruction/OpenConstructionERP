// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan Room sheet viewer.
 *
 * Renders one document page with pdf.js (self-contained loader kept separate
 * from the markups annotator, exactly like the punch pin board) and paints the
 * marks from every source on top as independent layers:
 *
 *   - Pins (punch + plan) - HTML markers positioned by the normalised (0..1)
 *     x/y the payload carries, so they stay correct at any zoom without any
 *     coordinate maths. Click a pin to see its title / note / status / priority.
 *   - Markups + measurements - an SVG overlay sized to the canvas. Each source
 *     has its own coordinate space, so each is projected differently:
 *       · measurement points are in takeoff scale-1 viewport units -> multiply
 *         by the render scale (matches how the takeoff viewer draws them);
 *       · markup points are in PDF user space -> project with the live
 *         `viewport.convertToViewportPoint` (matches the markups annotator).
 *
 * Write users get a "Drop a pin" mode: click the sheet to capture a normalised
 * point, type a note, save. It is the one thing created on this page, so it is
 * the toolbar's primary action with a one-line hint; read-only users see why
 * it is missing in the same spot. The parent owns the mutation and optimistic
 * state; this component only captures the point and the note.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { closePdf, openPdf, type PageViewport, type PDFDocumentProxy, type RenderTask } from '@/shared/lib/pdfjs';
import {
  ChevronLeft,
  ChevronRight,
  Crosshair,
  Loader2,
  Lock,
  MapPin,
  Trash2,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button } from '@/shared/ui';
import { API_BASE, getAuthToken } from '@/shared/lib/api';
import {
  parseOverlayPoints,
  type OverlayMarkup,
  type OverlayMeasurement,
  type OverlayPin,
  type OverlaysResponse,
} from './api';
import { pinColor, statusBadgeVariant, type LayerKey } from './layers';

const ZOOM_LEVELS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];
const BASE_SCALE = 1.3;

/** The rendered page, kept so the SVG overlay can project geometry onto it. */
interface PageView {
  scale: number;
  width: number;
  height: number;
  viewport: PageViewport;
}

interface Props {
  documentId: string;
  /** 1-based page currently shown (owned by the parent - it keys the query). */
  page: number;
  onPageChange: (page: number) => void;
  /** Reports the page count once the PDF loads (for the parent's context line). */
  onNumPages?: (n: number) => void;
  /** Overlay composite for this page. Pin adds / deletes are applied
   *  optimistically to this object's cache by the parent, so it already
   *  reflects a just-dropped or just-removed plan pin before the refetch. */
  overlays: OverlaysResponse | undefined;
  visibility: Record<LayerKey, boolean>;
  canWrite: boolean;
  /** Drop-pin mode (parent-owned so the header button and the sheet agree). */
  placing: boolean;
  onStartPlacing: () => void;
  onCancelPlacing: () => void;
  onCreatePin: (x: number, y: number, note: string) => void;
  onDeletePin: (pin: OverlayPin) => void;
  isSaving: boolean;
}

export function PlanRoomViewer({
  documentId,
  page,
  onPageChange,
  onNumPages,
  overlays,
  visibility,
  canWrite,
  placing,
  onStartPlacing,
  onCancelPlacing,
  onCreatePin,
  onDeletePin,
  isSaving,
}: Props) {
  const { t } = useTranslation();

  const [numPages, setNumPages] = useState(0);
  const [zoomIdx, setZoomIdx] = useState(2);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [pageView, setPageView] = useState<PageView | null>(null);
  const [selectedPin, setSelectedPin] = useState<OverlayPin | null>(null);
  // A point clicked in placing mode, awaiting a note before it is saved.
  const [draft, setDraft] = useState<{ x: number; y: number } | null>(null);
  const [draftNote, setDraftNote] = useState('');

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);

  const zoom = ZOOM_LEVELS[zoomIdx] ?? 1.0;

  /* ── Load the PDF document ─────────────────────────────────────────── */
  useEffect(() => {
    if (!documentId) {
      pdfRef.current = null;
      setNumPages(0);
      return;
    }
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    setIsLoading(true);
    setLoadError(false);
    (async () => {
      try {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/v1/documents/${documentId}/download/`, {
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
        setNumPages(doc.numPages);
        onNumPages?.(doc.numPages);
        // Clamp a parent page that overshoots the real page count.
        if (page > doc.numPages) onPageChange(doc.numPages);
      } catch {
        if (!cancelled) {
          setLoadError(true);
          pdfRef.current = null;
          setNumPages(0);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      closePdf(loaded);
    };
    // page is intentionally excluded: a page change must not reload the PDF.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  /* ── Render the current page ───────────────────────────────────────── */
  useEffect(() => {
    const doc = pdfRef.current;
    if (!doc || !canvasRef.current || numPages === 0) return;
    let cancelled = false;
    let task: RenderTask | null = null;
    (async () => {
      try {
        const safePage = Math.min(Math.max(1, page), numPages);
        const pdfPage = await doc.getPage(safePage);
        if (cancelled) return;
        const scale = zoom * BASE_SCALE;
        const viewport = pdfPage.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        task = pdfPage.render({ canvas, viewport });
        await task.promise;
        if (!cancelled) {
          setPageView({ scale, width: viewport.width, height: viewport.height, viewport });
        }
      } catch (err) {
        if (err && (err as { name?: string }).name !== 'RenderingCancelledException') {
          if (import.meta.env.DEV) console.warn('Plan Room render failed', err);
        }
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel?.();
    };
  }, [page, zoom, numPages]);

  // Leaving placing mode (or changing page) drops any half-entered draft.
  useEffect(() => {
    if (!placing) {
      setDraft(null);
      setDraftNote('');
    }
  }, [placing]);
  useEffect(() => {
    setDraft(null);
    setDraftNote('');
    setSelectedPin(null);
  }, [page, documentId]);

  /* ── Pins on this page (payload; optimistic adds/removes already applied
   *     to the overlays cache by the parent) ────────────────────────────── */
  const pins = useMemo(() => {
    const base = overlays?.pins ?? [];
    return base.filter((p) => (p.kind === 'punch' ? visibility.punch : visibility.plan));
  }, [overlays?.pins, visibility.punch, visibility.plan]);

  /* ── Placement ─────────────────────────────────────────────────────── */
  const handlePlaceClick = useCallback(
    (e: React.MouseEvent) => {
      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
      setSelectedPin(null);
      setDraft({ x, y });
      setDraftNote('');
    },
    [],
  );

  const saveDraft = useCallback(() => {
    if (!draft) return;
    onCreatePin(draft.x, draft.y, draftNote.trim());
    setDraft(null);
    setDraftNote('');
    onCancelPlacing();
  }, [draft, draftNote, onCreatePin, onCancelPlacing]);

  const cancelDraft = useCallback(() => {
    setDraft(null);
    setDraftNote('');
    onCancelPlacing();
  }, [onCancelPlacing]);

  /* ── Overlay geometry projection ───────────────────────────────────── */

  /** Project a takeoff measurement point (scale-1 viewport units) to canvas px. */
  const measurementToScreen = useCallback(
    (pt: { x: number; y: number }, view: PageView) => ({ x: pt.x * view.scale, y: pt.y * view.scale }),
    [],
  );

  /** Project a markup point to canvas px, honouring its stored coord space. */
  const markupToScreen = useCallback(
    (pt: { x: number; y: number }, geometry: Record<string, unknown>, view: PageView) => {
      // Legacy markups store raw canvas pixels; modern ones store PDF user
      // space (the annotator's `convertToPdfPoint`). Project each accordingly.
      if (geometry.coord_space === 'canvas') {
        return { x: pt.x * view.scale, y: pt.y * view.scale };
      }
      const projected = view.viewport.convertToViewportPoint(pt.x, pt.y);
      return { x: projected[0] ?? 0, y: projected[1] ?? 0 };
    },
    [],
  );

  const hasDrawing = !!documentId;

  return (
    <div className="rounded-xl border border-border-light bg-surface-primary">
      {/* ── Toolbar ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border-light px-3 py-2">
        {/* Page nav */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page <= 1}
            aria-label={t('plan_room.prev_page', { defaultValue: 'Previous page' })}
            className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="min-w-[52px] text-center text-xs tabular-nums text-content-secondary">
            {numPages > 0 ? `${page} / ${numPages}` : '-'}
          </span>
          <button
            type="button"
            onClick={() => onPageChange(Math.min(numPages || 1, page + 1))}
            disabled={numPages === 0 || page >= numPages}
            aria-label={t('plan_room.next_page', { defaultValue: 'Next page' })}
            className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          >
            <ChevronRight size={16} />
          </button>
        </div>

        {/* Zoom */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setZoomIdx((i) => Math.max(0, i - 1))}
            disabled={zoomIdx <= 0}
            aria-label={t('plan_room.zoom_out', { defaultValue: 'Zoom out' })}
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
            aria-label={t('plan_room.zoom_in', { defaultValue: 'Zoom in' })}
            className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          >
            <ZoomIn size={16} />
          </button>
        </div>

        {/* Drop-pin control: the primary action for write users, a visible
            view-only notice in the same place for everyone else. */}
        {canWrite ? (
          <div className="ml-auto flex min-w-0 items-center gap-2">
            {placing ? (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue/10 px-2 py-1 text-xs font-medium text-oe-blue">
                <Crosshair size={13} />
                {t('plan_room.click_to_place', { defaultValue: 'Click the drawing to drop a pin' })}
                <button
                  type="button"
                  onClick={cancelDraft}
                  aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
                  className="ml-1 rounded hover:bg-oe-blue/20"
                >
                  <X size={13} />
                </button>
              </span>
            ) : (
              <>
                <span className="hidden min-w-0 truncate text-xs text-content-tertiary sm:inline">
                  {t('plan_room.pin_hint', {
                    defaultValue: 'A pin marks a spot on the drawing with your note.',
                  })}
                </span>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<MapPin size={14} />}
                  onClick={onStartPlacing}
                  disabled={!hasDrawing || isLoading}
                >
                  {t('plan_room.drop_pin', { defaultValue: 'Drop a pin' })}
                </Button>
              </>
            )}
          </div>
        ) : (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-surface-secondary px-2 py-1 text-xs text-content-secondary">
            <Lock size={13} className="shrink-0" />
            {t('plan_room.view_only', {
              defaultValue: 'View only. You can look at the drawing but not add pins.',
            })}
          </span>
        )}
      </div>

      {/* ── Canvas + overlays ───────────────────────────────────────────── */}
      <div className="relative max-h-[70vh] overflow-auto bg-neutral-100 p-3 dark:bg-neutral-900">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={28} className="animate-spin text-oe-blue" />
          </div>
        ) : loadError ? (
          <div className="flex items-center justify-center py-20 text-sm text-content-tertiary">
            {t('plan_room.sheet_load_error', {
              defaultValue: 'This document could not be shown as a drawing.',
            })}
          </div>
        ) : (
          <div
            ref={wrapperRef}
            className={clsx('relative inline-block', placing && !draft && 'cursor-crosshair')}
          >
            <canvas ref={canvasRef} className="block rounded shadow-sm" />

            {/* Markups + measurements (SVG, projected onto the canvas). */}
            {pageView && (overlays?.markups?.length || overlays?.measurements?.length) ? (
              <svg
                width={pageView.width}
                height={pageView.height}
                className="pointer-events-none absolute left-0 top-0"
                aria-hidden
              >
                {visibility.measurements &&
                  overlays?.measurements?.map((m) => (
                    <MeasurementMark
                      key={`ms-${m.id}`}
                      measurement={m}
                      project={(pt) => measurementToScreen(pt, pageView)}
                    />
                  ))}
                {visibility.markups &&
                  overlays?.markups?.map((mk) => (
                    <MarkupMark
                      key={`mk-${mk.id}`}
                      markup={mk}
                      project={(pt) => markupToScreen(pt, mk.geometry, pageView)}
                    />
                  ))}
              </svg>
            ) : null}

            {/* Pins (HTML markers, percentage positioned). */}
            {pins.map((pin) => (
              <button
                key={`${pin.kind}-${pin.id}`}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (placing) return;
                  setSelectedPin(pin);
                }}
                title={pin.title ?? pin.note ?? undefined}
                style={{
                  left: `${pin.x * 100}%`,
                  top: `${pin.y * 100}%`,
                  backgroundColor: pinColor(pin),
                }}
                className={clsx(
                  'absolute z-20 flex h-6 w-6 -translate-x-1/2 -translate-y-full items-center justify-center',
                  'rounded-full rounded-bl-none border-2 border-white text-white shadow-md',
                  placing ? 'pointer-events-none opacity-70' : 'hover:scale-110',
                )}
              >
                <MapPin size={12} />
              </button>
            ))}

            {/* Ghost pin at the point being placed. */}
            {draft && (
              <span
                style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%` }}
                className="absolute z-30 flex h-6 w-6 -translate-x-1/2 -translate-y-full items-center justify-center rounded-full rounded-bl-none border-2 border-white bg-oe-blue text-white shadow-md"
                aria-hidden
              >
                <MapPin size={12} />
              </span>
            )}

            {/* Placement capture overlay - on top so clicks land here. */}
            {placing && !draft && (
              <div
                className="absolute inset-0 z-30"
                onClick={handlePlaceClick}
                role="presentation"
              />
            )}

            {/* Note popover for the pin being placed. */}
            {draft && (
              <div
                style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%` }}
                className="absolute z-40 w-64 -translate-x-1/2 translate-y-2 rounded-lg border border-border bg-surface-primary p-3 shadow-lg"
              >
                <h5 className="mb-1.5 text-xs font-semibold text-content-primary">
                  {t('plan_room.new_pin', { defaultValue: 'New plan pin' })}
                </h5>
                <textarea
                  value={draftNote}
                  onChange={(e) => setDraftNote(e.target.value)}
                  rows={3}
                  autoFocus
                  placeholder={t('plan_room.note_placeholder', {
                    defaultValue: 'Add a note (optional)...',
                  })}
                  className="w-full resize-none rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                />
                <div className="mt-2 flex justify-end gap-2">
                  <Button variant="ghost" size="sm" onClick={cancelDraft} disabled={isSaving}>
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={saveDraft}
                    disabled={isSaving}
                    icon={isSaving ? <Loader2 size={13} className="animate-spin" /> : undefined}
                  >
                    {t('plan_room.save_pin', { defaultValue: 'Save pin' })}
                  </Button>
                </div>
              </div>
            )}

            {/* Selected pin detail popover. */}
            {selectedPin && (
              <PinPopover
                pin={selectedPin}
                canWrite={canWrite}
                onClose={() => setSelectedPin(null)}
                onDelete={() => {
                  onDeletePin(selectedPin);
                  setSelectedPin(null);
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Measurement mark ────────────────────────────────────────────────────── */

function isClosedType(type: string): boolean {
  const s = type.toLowerCase();
  return s.includes('area') || s.includes('volume') || s.includes('region');
}

function MeasurementMark({
  measurement,
  project,
}: {
  measurement: OverlayMeasurement;
  project: (pt: { x: number; y: number }) => { x: number; y: number };
}) {
  const pts = parseOverlayPoints(measurement.points).map(project);
  if (pts.length === 0) return null;
  const color = measurement.group_color || '#10b981';
  const label = [measurement.measurement_value, measurement.measurement_unit]
    .filter(Boolean)
    .join(' ');
  const coords = pts.map((p) => `${p.x},${p.y}`).join(' ');

  // A single point (e.g. a count) draws a dot; a run draws a poly.
  const body =
    pts.length === 1 ? (
      <circle cx={pts[0]!.x} cy={pts[0]!.y} r={4} fill={color} />
    ) : isClosedType(measurement.type) ? (
      <polygon points={coords} fill={color} fillOpacity={0.12} stroke={color} strokeWidth={2} />
    ) : (
      <polyline points={coords} fill="none" stroke={color} strokeWidth={2} />
    );

  return (
    <g>
      {body}
      {label && (
        <text
          x={pts[0]!.x + 6}
          y={pts[0]!.y - 6}
          fontSize={11}
          fill={color}
          className="select-none"
          style={{ paintOrder: 'stroke', stroke: '#fff', strokeWidth: 3 }}
        >
          {label}
        </text>
      )}
    </g>
  );
}

/* ── Markup mark ─────────────────────────────────────────────────────────── */

function isClosedMarkup(markup: OverlayMarkup): boolean {
  const tool = String(markup.geometry.tool ?? markup.type).toLowerCase();
  return ['rectangle', 'ellipse', 'polygon', 'cloud', 'area', 'highlight'].some((k) =>
    tool.includes(k),
  );
}

function MarkupMark({
  markup,
  project,
}: {
  markup: OverlayMarkup;
  project: (pt: { x: number; y: number }) => { x: number; y: number };
}) {
  const rawPoints = Array.isArray(markup.geometry.points)
    ? (markup.geometry.points as unknown[])
    : [];
  const pts = parseOverlayPoints(rawPoints).map(project);
  const color = markup.color || '#a855f7';
  const opacity = markup.opacity ?? 1;
  const strokeWidth = markup.line_width ?? 2;
  const caption = markup.label || markup.text || '';

  if (pts.length === 0) {
    // Nothing positionable (bare text / stamp without points) - skip on-canvas.
    return null;
  }

  let body: JSX.Element;
  if (pts.length === 1) {
    body = <circle cx={pts[0]!.x} cy={pts[0]!.y} r={5} fill={color} fillOpacity={opacity} />;
  } else if (pts.length === 2 && isClosedMarkup(markup)) {
    // Two-corner rectangle.
    const [a, b] = pts;
    body = (
      <rect
        x={Math.min(a!.x, b!.x)}
        y={Math.min(a!.y, b!.y)}
        width={Math.abs(b!.x - a!.x)}
        height={Math.abs(b!.y - a!.y)}
        fill={color}
        fillOpacity={0.1 * opacity}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeOpacity={opacity}
      />
    );
  } else {
    const coords = pts.map((p) => `${p.x},${p.y}`).join(' ');
    body = isClosedMarkup(markup) ? (
      <polygon
        points={coords}
        fill={color}
        fillOpacity={0.1 * opacity}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeOpacity={opacity}
      />
    ) : (
      <polyline
        points={coords}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeOpacity={opacity}
      />
    );
  }

  return (
    <g>
      {body}
      {caption && (
        <text
          x={pts[0]!.x + 6}
          y={pts[0]!.y - 6}
          fontSize={11}
          fill={color}
          className="select-none"
          style={{ paintOrder: 'stroke', stroke: '#fff', strokeWidth: 3 }}
        >
          {caption.length > 32 ? `${caption.slice(0, 32)}…` : caption}
        </text>
      )}
    </g>
  );
}

/* ── Pin detail popover ──────────────────────────────────────────────────── */

function PinPopover({
  pin,
  canWrite,
  onClose,
  onDelete,
}: {
  pin: OverlayPin;
  canWrite: boolean;
  onClose: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const heading =
    pin.title ||
    (pin.kind === 'punch'
      ? t('plan_room.punch_item', { defaultValue: 'Punch item' })
      : t('plan_room.plan_pin', { defaultValue: 'Plan pin' }));

  return (
    <div
      style={{ left: `${pin.x * 100}%`, top: `${pin.y * 100}%` }}
      className="absolute z-40 w-60 -translate-x-1/2 -translate-y-[calc(100%+0.75rem)] rounded-lg border border-border bg-surface-primary p-3 shadow-lg"
    >
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <h5 className="min-w-0 text-sm font-semibold text-content-primary">{heading}</h5>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close', { defaultValue: 'Close' })}
          className="-mr-1 -mt-1 shrink-0 rounded p-0.5 text-content-tertiary hover:bg-surface-secondary"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={pin.kind === 'punch' ? 'error' : 'blue'} size="sm">
          {pin.kind === 'punch'
            ? t('plan_room.layer_punch', { defaultValue: 'Punch pins' })
            : t('plan_room.layer_plan', { defaultValue: 'Plan pins' })}
        </Badge>
        {pin.status && (
          <Badge variant={statusBadgeVariant(pin.status)} size="sm">
            {pin.status}
          </Badge>
        )}
        {pin.priority && (
          <Badge variant="warning" size="sm">
            {pin.priority}
          </Badge>
        )}
      </div>

      {pin.note && <p className="mt-2 text-sm text-content-secondary">{pin.note}</p>}
      {pin.assigned_to && (
        <p className="mt-1.5 text-xs text-content-tertiary">
          {t('plan_room.assigned_to', { defaultValue: 'Assigned to' })}: {pin.assigned_to}
        </p>
      )}

      {/* Delete is only offered for plan pins (this module owns them) to write
          users; the backend authorises the delete by the plan_room.write
          permission, so any editor can remove a plan pin. */}
      {pin.kind === 'plan' && canWrite && (
        <div className="mt-2.5 flex justify-end border-t border-border-light pt-2">
          <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} onClick={onDelete}>
            {t('common.delete', { defaultValue: 'Delete' })}
          </Button>
        </div>
      )}
    </div>
  );
}
