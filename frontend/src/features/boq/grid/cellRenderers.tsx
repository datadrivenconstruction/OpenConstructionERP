import { useState, useCallback, useRef, useMemo, useEffect, forwardRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import type { ICellRendererParams } from 'ag-grid-community';
import {
  ChevronDown,
  ChevronRight,
  GripVertical,
  Plus,
  FolderOpen,
  Folder,
  X,
  BookmarkPlus,
  MoreHorizontal,
  Boxes,
  Cuboid,
  Ruler,
  ArrowRight,
  Loader2,
  Info,
  Trash2,
  FileText,
  FileBox,
  CheckCircle2,
} from 'lucide-react';
import { createPortal } from 'react-dom';
import { useQuery, useQueries } from '@tanstack/react-query';
import { RESOURCE_TYPE_BADGE, fmtWithCurrency } from '../boqHelpers';
import { countComments } from '../CommentDrawer';
import { BIMQuantityPicker } from './BIMQuantityPicker';
import { MiniGeometryPreview } from '@/shared/ui/MiniGeometryPreview';
import { fetchBIMElementsByIds, fetchBIMElementProperties } from '@/features/bim/api';
import type { BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Validation Status Dot ────────────────────────────────────────── */

const VALIDATION_DOT_STYLES: Record<string, string> = {
  passed: 'bg-emerald-500',
  warnings: 'bg-amber-500',
  errors: 'bg-red-500',
  pending: 'bg-gray-300 dark:bg-gray-600',
};

/**
 * Validation tooltip lookup — requires `t()` from context, so we return
 * a factory that the renderer calls.
 */
function getValidationTooltip(
  status: string,
  t: (key: string, opts?: Record<string, string>) => string,
): string {
  switch (status) {
    case 'passed':
      return t('boq.validation_passed', { defaultValue: 'Validation passed — position is complete' });
    case 'warnings':
      return t('boq.validation_warnings', { defaultValue: 'Validation warnings — review recommended' });
    case 'errors':
      return t('boq.validation_errors', { defaultValue: 'Validation errors — action required' });
    case 'pending':
      return t('boq.validation_pending', { defaultValue: 'Validation pending — not yet checked' });
    default:
      return status;
  }
}

/* ── Section Full-Width Group Row Renderer ────────────────────────── */

export interface SectionGroupContext {
  collapsedSections: Set<string>;
  onToggleSection: (sectionId: string) => void;
  onAddPosition: (sectionId?: string) => void;
  currencySymbol: string;
  currencyCode?: string;
  locale?: string;
  fmt: Intl.NumberFormat;
  t: (key: string, opts?: Record<string, string | number>) => string;
}

export function SectionFullWidthRenderer(params: ICellRendererParams) {
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;

  if (!data?._isSection || !ctx) return null;

  const isCollapsed = ctx.collapsedSections?.has(data.id) ?? false;
  const childCount: number = data._childCount ?? 0;
  const subtotal: number = data._subtotal ?? data.total ?? 0;
  const description: string = data.description ?? '';

  const formattedSubtotal = ctx.fmt
    ? fmtWithCurrency(subtotal, ctx.locale ?? 'de-DE', ctx.currencyCode ?? 'EUR')
    : `${subtotal.toFixed(2)}`;

  const t = ctx.t ?? ((key: string, opts?: Record<string, string | number>) =>
    (opts?.defaultValue as string) ?? key);

  const [dragOver, setDragOver] = useState(false);

  return (
    <div
      className={`flex items-center w-full h-full px-2 gap-2 select-none group/section transition-colors ${
        dragOver ? 'bg-oe-blue-subtle/40 border-t-2 border-oe-blue' : ''
      }`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/x-section-id', data.id);
        e.dataTransfer.effectAllowed = 'move';
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('text/x-section-id')) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          setDragOver(true);
        }
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const fromId = e.dataTransfer.getData('text/x-section-id');
        if (fromId && fromId !== data.id) {
          ctx.onReorderSections?.(fromId, data.id);
        }
      }}
    >
      <span className="cursor-grab opacity-40 group-hover/section:opacity-80 shrink-0 transition-opacity">
        <GripVertical size={14} className="text-content-tertiary" />
      </span>

      <button
        onClick={(e) => {
          e.stopPropagation();
          ctx.onToggleSection?.(data.id);
        }}
        className="shrink-0 h-6 w-6 flex items-center justify-center rounded
                   text-content-secondary hover:text-content-primary
                   hover:bg-surface-tertiary/80 transition-colors"
        title={isCollapsed
          ? t('boq.expand_section', { defaultValue: 'Expand section' })
          : t('boq.collapse_section', { defaultValue: 'Collapse section' })
        }
      >
        {isCollapsed ? (
          <Folder size={15} className="text-content-tertiary" />
        ) : (
          <FolderOpen size={15} className="text-oe-blue" />
        )}
      </button>

      <span className="shrink-0 text-content-tertiary">
        {isCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
      </span>

      <span className="text-xs font-bold text-content-primary uppercase tracking-wide truncate min-w-0">
        {description}
      </span>

      <span className="shrink-0 inline-flex items-center h-4 px-1.5 rounded-full
                       bg-surface-tertiary text-[10px] font-medium text-content-tertiary
                       tabular-nums">
        {childCount} {childCount === 1
          ? t('boq.item', { defaultValue: 'item' })
          : t('boq.items', { defaultValue: 'items' })
        }
      </span>

      <div className="flex-1" />

      <button
        onClick={(e) => {
          e.stopPropagation();
          ctx.onAddPosition?.(data.id);
        }}
        className="shrink-0 h-5 flex items-center gap-0.5 px-1.5 rounded
                   text-[10px] font-medium
                   text-content-tertiary hover:text-oe-blue
                   bg-transparent hover:bg-oe-blue-subtle
                   opacity-0 group-hover/section:opacity-100
                   transition-all"
        title={t('boq.add_position_to_section', { defaultValue: 'Add position to this section' })}
      >
        <Plus size={10} />
        {t('boq.add_item', { defaultValue: 'Add' })}
      </button>

      {(ctx as FullGridContext | undefined)?.onDeleteSection && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (window.confirm(
              t('boq.confirm_delete_section', {
                defaultValue: 'Delete this section and all {{count}} positions inside it?',
                count: childCount,
              })
            )) {
              (ctx as FullGridContext).onDeleteSection!(data.id);
            }
          }}
          className="shrink-0 h-5 flex items-center gap-0.5 px-1.5 rounded
                     text-[10px] font-medium
                     text-content-tertiary hover:text-red-600
                     bg-transparent hover:bg-red-50 dark:hover:bg-red-950/30
                     opacity-0 group-hover/section:opacity-100
                     transition-all"
          title={t('boq.delete_section', { defaultValue: 'Delete section with all positions' })}
          aria-label={t('boq.delete_section', { defaultValue: 'Delete section with all positions' })}
        >
          <Trash2 size={10} />
        </button>
      )}

      <span className="shrink-0 text-xs font-bold text-content-primary tabular-nums pl-2">
        {formattedSubtotal}
      </span>
    </div>
  );
}

/* ── Grid Context ────────────────────────────────────────────────────
 * Unified context passed via AG Grid's `context` prop.
 * Contains all callbacks + formatting helpers.
 * ──────────────────────────────────────────────────────────────────── */

export interface ActionsContext {
  onDeletePosition: (id: string) => void;
  onSaveToDatabase: (id: string) => void;
  onAddComment: (id: string) => void;
  onOpenCostDbForPosition: (id: string) => void;
  onAddManualResource: (positionId: string) => void;
  onDuplicatePosition: (positionId: string) => void;
  onShowContextMenu: (e: React.MouseEvent, rowType: ContextMenuTarget, data: Record<string, unknown>) => void;
  anomalyMap?: Map<string, { severity: string; message: string; suggestion: number }>;
}

export type ContextMenuTarget = 'position' | 'resource' | 'section' | 'addResource' | 'footer';

export interface ResourceGridContext {
  expandedPositions: Set<string>;
  onToggleResources: (positionId: string) => void;
  onRemoveResource: (positionId: string, resourceIndex: number) => void;
  onUpdateResource: (positionId: string, resourceIndex: number, field: string, value: number | string) => void;
  onSaveResourceToCatalog: (positionId: string, resourceIndex: number) => void;
  onOpenCostDbForPosition: (positionId: string) => void;
  onOpenCatalogForPosition: (positionId: string) => void;
  currencySymbol: string;
  currencyCode: string;
  locale: string;
  fmt: Intl.NumberFormat;
  t: (key: string, options?: Record<string, string | number>) => string;
}

export type FullGridContext = ActionsContext & ResourceGridContext & SectionGroupContext & {
  onApplyAnomalySuggestion?: (positionId: string, suggestedRate: number) => void;
  /** First ready BIM model ID for the current project (used for mini 3D previews). */
  bimModelId?: string | null;
  /** Update a BOQ position — used by QuantityCellRenderer to apply BIM quantities. */
  onUpdatePosition?: (id: string, data: Record<string, unknown>, oldData: Record<string, unknown>) => void;
  /** Highlight linked BIM elements in the 3D viewer (triggered from ordinal badge). */
  onHighlightBIMElements?: (elementIds: string[]) => void;
  /** Delete a section with all its child positions. */
  onDeleteSection?: (sectionId: string) => void;
  /** Reorder sections via drag-and-drop. */
  onReorderSections?: (fromId: string, toId: string) => void;
};

/* ── Actions Cell Renderer ────────────────────────────────────────── */

export function ActionsCellRenderer(params: ICellRendererParams) {
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;

  if (!data || data._isSection || data._isFooter) return null;

  const t = ctx?.t ?? ((key: string, opts?: Record<string, string | number>) => (opts?.defaultValue as string) ?? key);
  const commentCount = countComments(data.metadata as Record<string, unknown> | undefined);
  const anomaly = ctx?.anomalyMap?.get(data.id as string);

  return (
    <div className="flex items-center justify-end gap-0.5 h-full w-full pr-1">
      {/* Anomaly warning badge */}
      {anomaly && (
        <span
          className={`flex h-4 items-center px-1 rounded shrink-0 ${
            anomaly.severity === 'error'
              ? 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400'
              : 'bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400'
          }`}
          title={anomaly.message}
        >
          <svg width="10" height="10" viewBox="0 0 16 16" fill="none" className="shrink-0">
            <path d="M8 1L1 14h14L8 1z" fill="currentColor" opacity="0.8" />
            <path d="M7.5 6v4h1V6h-1zm0 5v1h1v-1h-1z" fill="white" />
          </svg>
        </span>
      )}
      {/* Comment count badge */}
      {commentCount > 0 && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            ctx?.onAddComment?.(data.id as string);
          }}
          className="flex h-4 items-center gap-0.5 px-1 rounded bg-amber-100 text-amber-600
                     dark:bg-amber-900/30 dark:text-amber-400
                     hover:bg-amber-200 dark:hover:bg-amber-900/50 transition-colors shrink-0"
          title={t('boq.comment_count', { defaultValue: '{{count}} comment(s)', count: commentCount })}
          aria-label={t('boq.comment_count', { defaultValue: '{{count}} comment(s)', count: commentCount })}
        >
          <span className="text-[9px] font-bold tabular-nums">{commentCount}</span>
        </button>
      )}
      {/* More actions button — triggers context menu */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          ctx?.onShowContextMenu?.(e, 'position', data);
        }}
        className="flex h-6 w-6 items-center justify-center rounded
                   text-content-tertiary/50 hover:text-content-primary
                   hover:bg-surface-tertiary transition-all"
        title={t('common.actions', { defaultValue: 'Actions' })}
        aria-label={t('common.actions', { defaultValue: 'Actions' })}
      >
        <MoreHorizontal size={14} />
      </button>
    </div>
  );
}

/* ── Expand / Collapse Resources Cell Renderer (own non-editable column) */

export function ExpandCellRenderer(params: ICellRendererParams) {
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;

  if (!data || data._isSection || data._isFooter || data._isResource || data._isAddResource) return null;

  const t = ctx?.t ?? ((key: string, opts?: Record<string, string>) => (opts?.defaultValue as string) ?? key);
  const hasResources = Array.isArray(data.metadata?.resources) && data.metadata.resources.length > 0;
  if (!hasResources) return null;

  const isExpanded = ctx?.expandedPositions?.has(data.id) ?? false;
  const expandTitle = isExpanded
    ? t('boq.collapse_resources', { defaultValue: 'Collapse resources' })
    : t('boq.expand_resources', { defaultValue: 'Expand resources' });

  return (
    <div className="flex items-center justify-center h-full w-full">
      <button
        onClick={() => ctx?.onToggleResources?.(data.id)}
        className="h-6 w-6 flex items-center justify-center rounded
                   text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10
                   transition-colors cursor-pointer"
        title={expandTitle}
        aria-label={expandTitle}
      >
        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
    </div>
  );
}

/* ── Ordinal + Validation Dot ─────────────────────────────────────── */

export function OrdinalCellRenderer(params: ICellRendererParams) {
  const { data, value, context } = params;
  if (!data || data._isSection || data._isFooter) return <span>{value}</span>;

  const ctx = context as FullGridContext | undefined;
  const t = ctx?.t ?? ((key: string, opts?: Record<string, string>) => (opts?.defaultValue as string) ?? key);
  const status = data.validation_status ?? 'pending';
  const dotColor = VALIDATION_DOT_STYLES[status] ?? VALIDATION_DOT_STYLES.pending;

  return (
    <div className="flex items-center gap-1 overflow-hidden">
      <span className="text-xs font-mono truncate min-w-0">{value}</span>
      <span
        className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${dotColor} cursor-help`}
        title={getValidationTooltip(status, t)}
        aria-label={getValidationTooltip(status, t)}
      />
    </div>
  );
}

/* ── BIM Link Badge + Mini 3D Preview (own column) ───────────────── */

export function BimLinkCellRenderer(params: ICellRendererParams) {
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;
  const t = ctx?.t ?? ((key: string, opts?: Record<string, string | number>) => (opts?.defaultValue as string) ?? key);

  if (!data || data._isFooter || data._isResource || data._isAddResource || data._isSection) {
    return null;
  }

  const bimLinks: unknown = data.cad_element_ids;
  const bimLinkIds: string[] = Array.isArray(bimLinks)
    ? bimLinks.filter((x): x is string => typeof x === 'string' && x.length > 0)
    : [];
  const bimLinkCount = bimLinkIds.length;
  const hasBimLink = bimLinkCount > 0 && !!ctx?.bimModelId;

  // PDF + DWG link metadata is stored under position.metadata so the
  // relationship is persistent and survives reloads.
  const meta = (data.metadata ?? {}) as Record<string, unknown>;
  const pdfMeasurementId = meta.pdf_measurement_id as string | undefined;
  const pdfDocumentId = meta.pdf_document_id as string | undefined;
  const pdfPage = meta.pdf_page as number | undefined;
  const pdfSource = meta.pdf_measurement_source as string | undefined;
  const hasPdfLink = !!pdfMeasurementId || !!pdfSource;

  const dwgAnnotationId = meta.dwg_annotation_id as string | undefined;
  const dwgDrawingId = meta.dwg_drawing_id as string | undefined;
  const dwgSource = meta.dwg_annotation_source as string | undefined;
  const hasDwgLink = !!dwgAnnotationId || !!dwgDrawingId || !!dwgSource;

  const [showPreview, setShowPreview] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const handleOpen = useCallback(() => {
    if (btnRef.current) {
      setAnchorRect(btnRef.current.getBoundingClientRect());
    }
    setShowPreview(true);
    ctx?.onHighlightBIMElements?.(bimLinkIds);
  }, [bimLinkIds, ctx]);

  const navigate = useNavigate();

  const handleOpenPdf = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    const params = new URLSearchParams();
    params.set('tab', 'measurements');
    if (pdfMeasurementId) params.set('focus', pdfMeasurementId);
    // pdf_document_id in metadata is the *filename* (not a UUID), so we
    // pass it as `name` and let TakeoffPage resolve it against the
    // server documents list.
    if (pdfDocumentId) params.set('name', pdfDocumentId);
    if (pdfPage) params.set('page', String(pdfPage));
    navigate(`/takeoff?${params.toString()}`);
  }, [pdfMeasurementId, pdfDocumentId, pdfPage, navigate]);

  const handleOpenDwg = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    const params = new URLSearchParams();
    // DwgTakeoffPage reads `drawingId` (not `drawing`) — see DwgTakeoffPage.tsx:275.
    if (dwgDrawingId) params.set('drawingId', dwgDrawingId);
    if (dwgAnnotationId) params.set('focus', dwgAnnotationId);
    navigate(`/dwg-takeoff?${params.toString()}`);
  }, [dwgDrawingId, dwgAnnotationId, navigate]);

  if (!hasBimLink && !hasPdfLink && !hasDwgLink) return null;

  const popoverStyle = anchorRect
    ? {
        position: 'fixed' as const,
        left: Math.min(anchorRect.right + 8, window.innerWidth - 660),
        top: Math.max(8, Math.min(anchorRect.top - 40, window.innerHeight - 520)),
        zIndex: 9999,
      }
    : undefined;

  return (
    <div className="flex items-center justify-center gap-0.5 h-full w-full">
      {hasBimLink && (
        <button
          ref={btnRef}
          onClick={(e) => {
            e.stopPropagation();
            handleOpen();
          }}
          onMouseDown={(e) => e.stopPropagation()}
          className="h-6 px-1.5 inline-flex items-center gap-0.5 rounded
                     bg-oe-blue/10 text-oe-blue text-[10px] font-semibold
                     hover:bg-oe-blue/25 transition-colors cursor-pointer"
          title={t('boq.bim_link_tooltip', { defaultValue: '{{count}} BIM element(s) linked — click to preview', count: bimLinkCount })}
          aria-label={t('boq.bim_link_tooltip', { defaultValue: '{{count}} BIM element(s) linked — click to preview', count: bimLinkCount })}
        >
          <Cuboid size={11} />
          {bimLinkCount}
        </button>
      )}
      {hasPdfLink && (
        <button
          onClick={handleOpenPdf}
          onMouseDown={(e) => e.stopPropagation()}
          className="h-6 w-6 inline-flex items-center justify-center rounded
                     bg-rose-500/10 text-rose-600 dark:text-rose-400
                     hover:bg-rose-500/25 transition-colors cursor-pointer"
          title={pdfSource
            ? `${t('boq.pdf_link_tooltip', { defaultValue: 'Open linked PDF takeoff' })} — ${pdfSource}`
            : t('boq.pdf_link_tooltip', { defaultValue: 'Open linked PDF takeoff' })}
          aria-label={t('boq.pdf_link_tooltip', { defaultValue: 'Open linked PDF takeoff' })}
        >
          <FileText size={12} />
        </button>
      )}
      {hasDwgLink && (
        <button
          onClick={handleOpenDwg}
          onMouseDown={(e) => e.stopPropagation()}
          className="h-6 w-6 inline-flex items-center justify-center rounded
                     bg-amber-500/10 text-amber-600 dark:text-amber-400
                     hover:bg-amber-500/25 transition-colors cursor-pointer"
          title={dwgSource
            ? `${t('boq.dwg_link_tooltip', { defaultValue: 'Open linked DWG drawing' })} — ${dwgSource}`
            : t('boq.dwg_link_tooltip', { defaultValue: 'Open linked DWG drawing' })}
          aria-label={t('boq.dwg_link_tooltip', { defaultValue: 'Open linked DWG drawing' })}
        >
          <FileBox size={12} />
        </button>
      )}
      {showPreview && anchorRect && ctx?.bimModelId &&
        createPortal(
          <>
            {/* Backdrop blur overlay */}
            <div
              className="fixed inset-0 bg-black/30 backdrop-blur-sm z-[9998] animate-fade-in"
              onClick={() => setShowPreview(false)}
            />
            <BimLinkPopover
              ref={popoverRef}
              modelId={ctx.bimModelId}
              elementIds={bimLinkIds}
              style={popoverStyle!}
              onClose={() => setShowPreview(false)}
              positionData={data}
              onUpdatePosition={ctx?.onUpdatePosition}
            />
          </>,
          document.body,
        )}
    </div>
  );
}

/* ── BIM Link Popover — 3D preview + element info + navigate ─────── */

const BimLinkPopover = forwardRef<
  HTMLDivElement,
  {
    modelId: string;
    elementIds: string[];
    style: React.CSSProperties;
    onClose: () => void;
    positionData?: Record<string, unknown>;
    onUpdatePosition?: (id: string, data: Record<string, unknown>, oldData: Record<string, unknown>) => void;
  }
>(function BimLinkPopover({ modelId, elementIds, style, onClose, positionData, onUpdatePosition }, ref) {
  const { t } = useTranslation();
  const innerRef = useRef<HTMLDivElement>(null);
  const combinedRef = useCallback(
    (node: HTMLDivElement | null) => {
      (innerRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
      if (typeof ref === 'function') ref(node);
      else if (ref) (ref as React.MutableRefObject<HTMLDivElement | null>).current = node;
    },
    [ref],
  );

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (innerRef.current && !innerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const [glbOk, setGlbOk] = useState(true);
  const [showAllProps, setShowAllProps] = useState(false);
  const [showAllSums, setShowAllSums] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ['bim-link-preview', modelId, ...elementIds],
    queryFn: () => fetchBIMElementsByIds(modelId, elementIds),
    enabled: elementIds.length > 0,
    staleTime: 5 * 60_000,
  });
  const elements = data?.items ?? [];

  // Parquet fallback: some BIM elements have empty `quantities` in the DB
  // because DDC's "standard" Excel extract skips Area/Volume for certain
  // Revit categories (e.g. tapered roofs, planting). The full DDC
  // dataframe stored in Parquet often still has useful numerics
  // (thickness, level offset, rafter cut, …). We fetch the Parquet row
  // for each linked element keyed by its Revit ElementId (`mesh_ref`)
  // and merge those numeric values into the view so the user always
  // has something actionable to apply.
  const parquetFetches = useQueries({
    queries: elements.map((el) => ({
      queryKey: ['bim-parquet-row', modelId, el.mesh_ref || el.id],
      queryFn: () => fetchBIMElementProperties(modelId, el.mesh_ref || el.stable_id || el.id),
      enabled: !!modelId && !!el.mesh_ref,
      staleTime: 5 * 60_000,
    })),
  });
  const parquetByElementId = useMemo(() => {
    const out: Record<string, Record<string, unknown>> = {};
    elements.forEach((el, i) => {
      const row = parquetFetches[i]?.data;
      if (row) out[el.id] = row;
    });
    return out;
  }, [elements, parquetFetches]);

  /** Extract numeric entries from an element, with Parquet fallback
   *  when DB quantities are empty. Keys already present in `quantities`
   *  are preferred (they're the canonical Area/Volume/Length fields);
   *  Parquet fills the rest. */
  const extractNumerics = useCallback(
    (el: BIMElementData, includeAllProperties: boolean) => {
      const entries: { key: string; value: number; source: 'qty' | 'prop' | 'parquet' }[] = [];
      const seen = new Set<string>();
      if (el.quantities) {
        for (const [k, v] of Object.entries(el.quantities)) {
          const num = typeof v === 'number' ? v : parseFloat(String(v));
          if (!isNaN(num) && num !== 0) {
            entries.push({ key: k, value: num, source: 'qty' });
            seen.add(k);
          }
        }
      }
      if (includeAllProperties && el.properties) {
        for (const [k, v] of Object.entries(el.properties)) {
          if (seen.has(k)) continue;
          const num = typeof v === 'number' ? v : parseFloat(String(v));
          if (!isNaN(num) && num !== 0) {
            entries.push({ key: k, value: num, source: 'prop' });
            seen.add(k);
          }
        }
      }
      // Parquet-sourced numerics — surface them when the DB has no
      // direct quantities (so the panel always has SOMETHING), and
      // when the user explicitly asks for all properties.
      const parquet = parquetByElementId[el.id];
      if (parquet && (entries.length === 0 || includeAllProperties)) {
        for (const [k, v] of Object.entries(parquet)) {
          if (seen.has(k)) continue;
          // Skip the `id` column (that's the Revit ElementId, not a quantity)
          if (k === 'id') continue;
          const num = typeof v === 'number' ? v : parseFloat(String(v));
          if (!isNaN(num) && num !== 0) {
            entries.push({ key: k, value: num, source: 'parquet' });
            seen.add(k);
          }
        }
      }
      return entries;
    },
    [parquetByElementId],
  );

  const isEnriching = parquetFetches.some((q) => q.isLoading);

  const currentQuantity = typeof positionData?.quantity === 'number' ? positionData.quantity : 0;
  const canApply = !!positionData?.id && !!onUpdatePosition;

  const handleUseQuantity = useCallback(
    (value: number, source: string) => {
      if (!positionData?.id || !onUpdatePosition) return;
      const id = positionData.id as string;
      const oldMeta = (positionData.metadata ?? {}) as Record<string, unknown>;
      onUpdatePosition(
        id,
        { quantity: value, metadata: { ...oldMeta, bim_qty_source: source } },
        { ...positionData, quantity: currentQuantity },
      );
    },
    [positionData, onUpdatePosition, currentQuantity],
  );

  // Aggregation across linked elements — two semantics:
  //
  //   SUM — additive totals: area, volume, length, perimeter, weight, count.
  //         Σ across all elements is what the BOQ position quantity should be.
  //
  //   DISTINCT — per-element constants: thickness, width, height, material
  //         type, fire rating. Summing them is meaningless (five 240 mm walls
  //         aren't "1200 mm thick"). We keep the list of unique values so the
  //         user can pick one to apply, or just see the distribution.
  //
  // We classify each key with a keyword heuristic. Unknown → DISTINCT (safer
  // default: showing "N unique values" never lies; an unwarranted sum might).
  const quantitySums = useMemo(() => {
    if (elements.length === 0) {
      return [] as {
        key: string;
        label: string;
        agg: 'sum' | 'distinct';
        sum: number;
        unit: string;
        count: number;
        uniqueValues: number[];
      }[];
    }
    type Entry = {
      key: string;
      label: string;
      agg: 'sum' | 'distinct';
      sum: number;
      unit: string;
      count: number;
      uniqueValues: number[];
    };
    const classify = (k: string): 'sum' | 'distinct' => {
      const low = k.toLowerCase();
      // Additive — quantities that roll up
      if (
        low.includes('area') ||
        low.endsWith('_m2') ||
        low.includes('volume') ||
        low.endsWith('_m3') ||
        low === 'length' ||
        low.endsWith('_length') ||
        low.endsWith('_m') ||
        low.includes('perimeter') ||
        low.includes('weight') ||
        low.endsWith('_kg') ||
        low.includes('count') ||
        low === 'qty' ||
        low === 'quantity'
      ) {
        return 'sum';
      }
      // Per-element constants — thickness, width, height, span, rating…
      return 'distinct';
    };
    const unitOf = (k: string): string => {
      const low = k.toLowerCase();
      if (low.includes('area') || low.endsWith('_m2')) return 'm\u00B2';
      if (low.includes('volume') || low.endsWith('_m3')) return 'm\u00B3';
      if (
        low.includes('length') ||
        low.endsWith('_m') ||
        low.includes('height') ||
        low.includes('width') ||
        low.includes('perimeter')
      )
        return 'm';
      if (low.includes('thickness')) return 'mm';
      if (low.includes('weight') || low.endsWith('_kg')) return 'kg';
      if (low.includes('count')) return 'pcs';
      return '';
    };
    const map = new Map<string, Entry>();
    const bump = (k: string, num: number) => {
      const existing = map.get(k);
      const label = k
        .replace(/_m2$|_m3$|_m$|_kg$/, '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
      if (existing) {
        existing.sum += num;
        existing.count += 1;
        if (!existing.uniqueValues.includes(num)) existing.uniqueValues.push(num);
      } else {
        map.set(k, {
          key: k,
          label,
          agg: classify(k),
          sum: num,
          unit: unitOf(k),
          count: 1,
          uniqueValues: [num],
        });
      }
    };
    for (const el of elements) {
      const dbKeys = new Set<string>();
      if (el.quantities) {
        for (const [k, v] of Object.entries(el.quantities)) {
          const num = typeof v === 'number' ? v : parseFloat(String(v));
          if (isNaN(num) || num === 0) continue;
          bump(k, num);
          dbKeys.add(k);
        }
      }
      // Parquet enrichment.
      //   - Default (collapsed): only fire if the DB had no numeric
      //     quantities at all, to avoid polluting sums with cosmetic
      //     numerics (material id, color code, …) when real area/volume
      //     already came through.
      //   - Expanded (showAllSums=true): merge every numeric Parquet
      //     column so the Apply panel surfaces the same set the BIM
      //     Quantities picker shows. Keys already counted from the DB
      //     are skipped to avoid double-counting.
      if (dbKeys.size === 0 || showAllSums) {
        const parquet = parquetByElementId[el.id];
        if (parquet) {
          for (const [k, v] of Object.entries(parquet)) {
            if (k === 'id') continue;
            if (dbKeys.has(k)) continue;
            const num = typeof v === 'number' ? v : parseFloat(String(v));
            if (isNaN(num) || num === 0) continue;
            bump(k, num);
          }
        }
      }
    }
    // Sort: SUM entries first (they're the headline numbers), then DISTINCT
    // in descending order of "informativeness" (variety of values).
    return Array.from(map.values()).sort((a, b) => {
      if (a.agg !== b.agg) return a.agg === 'sum' ? -1 : 1;
      if (a.agg === 'sum') return b.sum - a.sum;
      return b.uniqueValues.length - a.uniqueValues.length;
    });
  }, [elements, parquetByElementId, showAllSums]);

  return (
    <div
      ref={combinedRef}
      className="rounded-xl shadow-2xl border border-border-light dark:border-border-dark
                 bg-white dark:bg-surface-elevated overflow-hidden flex flex-col"
      style={{ ...style, width: canApply ? 900 : 380, maxHeight: 'calc(100vh - 48px)' }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border-light dark:border-border-dark bg-surface-secondary/30">
        <div className="flex items-center gap-2">
          <Cuboid size={14} className="text-oe-blue" />
          <span className="text-xs font-semibold text-content-primary">
            {t('boq.linked_geometry', { defaultValue: 'Linked Geometry' })}
          </span>
          <span className="text-[10px] text-content-tertiary tabular-nums">
            ({t('boq.element_count', { defaultValue: '{{count}} element(s)', count: elementIds.length })})
          </span>
        </div>
        <button
          onClick={onClose}
          className="h-6 w-6 flex items-center justify-center rounded text-content-tertiary
                     hover:text-content-primary hover:bg-surface-tertiary transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      <div className={canApply ? 'flex flex-1 min-h-0 overflow-hidden' : ''}>
        {/* LEFT column: properties (moved out of the middle so the BIM
            properties read first, like a spec sheet next to the
            geometry).  Header is a static label — the toggle that
            expands the list is an explicit "Show all" pill button on
            the right so the affordance is obvious. */}
        {canApply && (
          <div className="w-[260px] shrink-0 flex flex-col border-r border-border-light dark:border-border-dark">
            <div className="flex items-center gap-1.5 px-3 py-1.5 w-full bg-blue-50/50 dark:bg-blue-950/20 border-b border-border-light/50 dark:border-border-dark/50 shrink-0">
              <Info size={11} className="text-blue-600 shrink-0" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-700 dark:text-blue-400 flex-1 text-left">
                {t('boq.bim_properties', { defaultValue: 'Properties' })}
              </span>
              <button
                type="button"
                onClick={() => setShowAllProps((v) => !v)}
                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold transition-colors ${
                  showAllProps
                    ? 'bg-blue-600 text-white hover:bg-blue-700'
                    : 'bg-white dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-700 hover:bg-blue-100 dark:hover:bg-blue-900/60'
                }`}
                title={
                  showAllProps
                    ? t('boq.bim_props_show_basic_title', { defaultValue: 'Hide non-quantity properties' })
                    : t('boq.bim_props_show_all_title', { defaultValue: 'Include every numeric property from BIM' })
                }
              >
                {showAllProps
                  ? t('boq.bim_show_less', { defaultValue: 'Show less' })
                  : t('boq.bim_show_all', { defaultValue: 'Show all' })}
                <ChevronDown size={10} className={`transition-transform ${showAllProps ? 'rotate-180' : ''}`} />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto">
              {isLoading && (
                <div className="flex items-center justify-center gap-2 py-4">
                  <Loader2 size={12} className="animate-spin text-content-tertiary" />
                </div>
              )}
              {!isLoading && elements.map((el) => {
                const numericEntries = extractNumerics(el, showAllProps);
                if (numericEntries.length === 0) return null;
                return (
                  <div key={el.id} className="px-3 py-1.5 border-b border-border-light/30 dark:border-border-dark/30 last:border-b-0">
                    {elements.length > 1 && (
                      <div className="text-[9px] font-medium text-content-tertiary mb-0.5 truncate">{el.name || el.element_type}</div>
                    )}
                    {numericEntries.map(({ key, value, source }) => {
                      const isCurrent = canApply && Math.abs(value - currentQuantity) < 0.001;
                      const paramLabel = key.replace(/_/g, ' ');
                      return (
                        <div
                          key={key}
                          className="group/prow flex items-center justify-between gap-1.5 py-0.5 rounded-sm hover:bg-blue-50/40 dark:hover:bg-blue-950/20 transition-colors"
                        >
                          <span
                            className={`text-[10px] truncate ${
                              source === 'qty'
                                ? 'text-content-secondary'
                                : source === 'parquet'
                                  ? 'text-emerald-700 dark:text-emerald-400'
                                  : 'text-content-tertiary italic'
                            }`}
                            title={source === 'parquet' ? 'From Parquet row (DDC export)' : source === 'prop' ? 'From element properties' : 'From element quantities'}
                          >
                            {paramLabel}
                          </span>
                          <div className="flex items-center gap-1 shrink-0">
                            <span className="text-[10px] font-mono text-content-primary tabular-nums font-medium">
                              {value.toLocaleString(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                            </span>
                            {canApply && (
                              isCurrent ? (
                                <span
                                  className="text-[8px] font-semibold uppercase text-emerald-600 bg-emerald-100 dark:bg-emerald-900/40 px-1 py-0.5 rounded"
                                  title={t('boq.bim_qty_current_title', { defaultValue: 'Already the position quantity' })}
                                >
                                  {t('boq.bim_qty_current', { defaultValue: 'current' })}
                                </span>
                              ) : (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleUseQuantity(value, `BIM: ${paramLabel}`);
                                  }}
                                  className="inline-flex items-center gap-0.5 px-1.5 h-4 rounded-sm text-[9px] font-semibold
                                             text-emerald-700 dark:text-emerald-300
                                             bg-emerald-100/70 dark:bg-emerald-900/30
                                             hover:bg-emerald-500 hover:text-white dark:hover:bg-emerald-500
                                             opacity-0 group-hover/prow:opacity-100 transition-all"
                                  title={t('boq.set_as_quantity_title', { defaultValue: 'Push this value into the BOQ quantity field' })}
                                >
                                  {t('boq.set_as_quantity', { defaultValue: 'Set as qty' })}
                                  <ArrowRight size={8} />
                                </button>
                              )
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
              {!isLoading && !isEnriching && elements.every((el) => extractNumerics(el, showAllProps).length === 0) && (
                <div className="py-3 text-center text-[10px] text-content-tertiary">
                  {!showAllProps
                    ? t('boq.no_quantities_hint_button', { defaultValue: 'No quantities — press "Show all" above to surface every BIM property' })
                    : t('boq.no_numeric_found', { defaultValue: 'No numeric values in this element' })}
                </div>
              )}
              {isEnriching && !isLoading && (
                <div className="flex items-center justify-center gap-2 py-2 text-[10px] text-content-tertiary">
                  <Loader2 size={10} className="animate-spin" />
                  {t('boq.loading_full_properties', { defaultValue: 'Loading full properties…' })}
                </div>
              )}
            </div>
          </div>
        )}

        {/* MIDDLE column: 3D preview + element cards */}
        <div className={canApply ? 'w-[380px] shrink-0 border-r border-border-light dark:border-border-dark flex flex-col' : 'w-full'}>
          {/* 3D Preview */}
          {glbOk && (
            <MiniGeometryPreview
              modelId={modelId}
              elementIds={elementIds}
              width={380}
              height={220}
              className="bg-gray-50 dark:bg-gray-900 border-b border-border-light dark:border-border-dark"
              onError={() => setGlbOk(false)}
            />
          )}

          {/* Element info cards */}
          <div className="max-h-[180px] overflow-y-auto">
            {isLoading && (
              <div className="flex items-center justify-center py-6 text-content-tertiary text-xs">
                {t('boq.loading_element_data', { defaultValue: 'Loading element data...' })}
              </div>
            )}
            {!isLoading && elements.map((el) => (
              <div key={el.id} className="px-3 py-2 border-b border-border-light/50 dark:border-border-dark/50 last:border-b-0">
                <div className="flex items-center gap-2">
                  <Cuboid size={11} className="text-oe-blue/60 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-medium text-content-primary truncate">
                      {el.name || el.element_type}
                    </div>
                    <div className="text-[9px] text-content-tertiary font-mono">{el.element_type}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* RIGHT column: Apply to BOQ — quantity sums that drop values
            into the position quantity on click. Own scroll container so
            the "Use" buttons are always reachable even when the
            properties column has many rows. Header is a static label;
            an explicit "Show all" pill toggles whether every Parquet
            numeric is summed (vs only the headline area/volume/length). */}
        {canApply && (
          <div className="w-[260px] shrink-0 flex flex-col">
            <div className="flex items-center gap-1.5 px-3 py-1.5 w-full bg-emerald-50/50 dark:bg-emerald-950/20 border-b border-border-light/50 dark:border-border-dark/50 shrink-0">
              <Ruler size={11} className="text-emerald-600 shrink-0" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400 flex-1 text-left">
                {t('boq.apply_to_boq', { defaultValue: 'Apply to BOQ' })}
              </span>
              {isEnriching && (
                <Loader2 size={10} className="animate-spin text-emerald-600/60 shrink-0" />
              )}
              <button
                type="button"
                onClick={() => setShowAllSums((v) => !v)}
                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold transition-colors ${
                  showAllSums
                    ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                    : 'bg-white dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700 hover:bg-emerald-100 dark:hover:bg-emerald-900/60'
                }`}
                title={
                  showAllSums
                    ? t('boq.bim_collapse_sums', { defaultValue: 'Show only headline quantities' })
                    : t('boq.bim_expand_sums', { defaultValue: 'Show all numeric values from BIM' })
                }
              >
                {showAllSums
                  ? t('boq.bim_show_less', { defaultValue: 'Show less' })
                  : t('boq.bim_show_all', { defaultValue: 'Show all' })}
                <ChevronDown size={10} className={`transition-transform ${showAllSums ? 'rotate-180' : ''}`} />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto">
              {isLoading && (
                <div className="flex items-center justify-center gap-2 py-4">
                  <Loader2 size={12} className="animate-spin text-content-tertiary" />
                </div>
              )}
              {!isLoading && quantitySums.length === 0 && (
                <div className="py-3 text-center text-[10px] text-content-tertiary">
                  {t('boq.no_numeric_quantities', { defaultValue: 'No numeric quantities' })}
                </div>
              )}
              {!isLoading && quantitySums.map((s) => {
                // SUM entries get the traditional "Use this number" row.
                if (s.agg === 'sum') {
                  const isCurrent = Math.abs(s.sum - currentQuantity) < 0.001;
                  const fmt = Number.isInteger(s.sum)
                    ? s.sum.toLocaleString(getIntlLocale())
                    : s.sum.toLocaleString(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 });
                  return (
                    <div
                      key={s.key}
                      className={`flex items-center gap-1 px-3 py-1.5 group/qrow transition-colors ${
                        isCurrent
                          ? 'bg-emerald-50/60 dark:bg-emerald-950/20'
                          : 'hover:bg-emerald-50/80 dark:hover:bg-emerald-950/30'
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1">
                          <span className="text-[11px] text-content-secondary truncate">{s.label}</span>
                          <span
                            className="text-[8px] font-bold uppercase text-emerald-600/80 tracking-wider shrink-0"
                            title={t('boq.bim_agg_sum_title', { defaultValue: 'Summed across all linked elements' })}
                          >
                            Σ
                          </span>
                        </div>
                        <div className="flex items-baseline gap-1">
                          <span className="text-[12px] tabular-nums text-content-primary font-semibold">{fmt}</span>
                          {s.unit && <span className="text-[9px] text-content-quaternary font-mono">{s.unit}</span>}
                          {elements.length > 1 && s.count > 1 && (
                            <span className="text-[8px] text-content-quaternary">({s.count} el.)</span>
                          )}
                        </div>
                      </div>
                      {isCurrent ? (
                        <span className="text-[9px] text-emerald-600 font-semibold shrink-0 bg-emerald-100 dark:bg-emerald-900/40 px-1.5 py-0.5 rounded inline-flex items-center gap-0.5">
                          <CheckCircle2 size={9} />
                          {t('boq.bim_qty_current', { defaultValue: 'current' })}
                        </span>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleUseQuantity(s.sum, `BIM: ${s.label} (Σ)`);
                          }}
                          className="shrink-0 h-6 flex items-center gap-1 px-2.5 rounded-md text-[10px] font-semibold
                                     text-white bg-gradient-to-r from-emerald-500 to-emerald-600
                                     hover:from-emerald-600 hover:to-emerald-700
                                     shadow-sm hover:shadow-md ring-1 ring-emerald-500/20 hover:ring-emerald-500/40
                                     active:scale-[0.97] transition-all"
                          title={t('boq.bim_qty_use_as_quantity', { defaultValue: 'Set as quantity' })}
                        >
                          {t('boq.bim_qty_use_as_quantity', { defaultValue: 'Set as quantity' })}
                          <ArrowRight size={10} />
                        </button>
                      )}
                    </div>
                  );
                }
                // DISTINCT entries: list unique values (e.g. wall thicknesses
                // across a multi-wall selection). Single value → one chip.
                // Many values → scrollable chip strip, each individually
                // clickable to apply that specific number.
                const unique = s.uniqueValues;
                const sortedUnique = [...unique].sort((a, b) => a - b);
                const fmtVal = (n: number) =>
                  Number.isInteger(n)
                    ? n.toLocaleString(getIntlLocale())
                    : n.toLocaleString(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 });
                return (
                  <div key={s.key} className="px-3 py-1.5 border-b border-border-light/30 dark:border-border-dark/30 last:border-b-0 hover:bg-sky-50/40 dark:hover:bg-sky-950/20 transition-colors">
                    <div className="flex items-center gap-1 mb-0.5">
                      <span className="text-[11px] text-content-secondary truncate">{s.label}</span>
                      <span
                        className="text-[8px] font-bold uppercase text-sky-600/80 tracking-wider shrink-0"
                        title={t('boq.bim_agg_distinct_title', {
                          defaultValue:
                            'Per-element value — summing is meaningless, so each unique value is listed. Click one to apply it.',
                        })}
                      >
                        {sortedUnique.length === 1
                          ? '='
                          : t('boq.bim_agg_distinct_label', {
                              defaultValue: '{{n}} values',
                              n: sortedUnique.length,
                            })}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 flex-wrap">
                      {sortedUnique.map((v) => {
                        const isCurrent = Math.abs(v - currentQuantity) < 0.001;
                        return (
                          <button
                            key={v}
                            onClick={(e) => {
                              e.stopPropagation();
                              if (!isCurrent) handleUseQuantity(v, `BIM: ${s.label} = ${fmtVal(v)}`);
                            }}
                            disabled={isCurrent}
                            className={`group/chip inline-flex items-center gap-0.5 px-2 py-1 rounded-md border text-[10px] tabular-nums font-mono transition-all ${
                              isCurrent
                                ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400 border-emerald-300 cursor-default'
                                : 'bg-surface-primary text-content-primary border-border-light hover:bg-emerald-500 hover:text-white hover:border-emerald-500 hover:shadow-sm active:scale-[0.97]'
                            }`}
                            title={
                              isCurrent
                                ? t('boq.bim_qty_current', { defaultValue: 'current' })
                                : t('boq.bim_qty_use_as_quantity', { defaultValue: 'Set as quantity' })
                            }
                          >
                            <span className="font-semibold">{fmtVal(v)}</span>
                            {s.unit && <span className="text-[8px] opacity-70 group-hover/chip:opacity-100">{s.unit}</span>}
                            {!isCurrent && (
                              <ArrowRight size={8} className="opacity-0 group-hover/chip:opacity-100 transition-opacity -mr-0.5" />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Footer — navigate to BIM viewer */}
      <div className="px-4 py-2 border-t border-border-light dark:border-border-dark bg-surface-secondary/20">
        <a
          href={`/bim?model=${encodeURIComponent(modelId)}&highlight=${encodeURIComponent(elementIds.join(','))}`}
          className="flex items-center justify-center gap-2 w-full h-8 rounded-lg
                     bg-oe-blue/10 hover:bg-oe-blue/20 text-oe-blue text-xs font-medium
                     transition-colors"
          onClick={(e) => {
            e.preventDefault();
            onClose();
            window.location.href = `/bim?model=${encodeURIComponent(modelId)}&highlight=${encodeURIComponent(elementIds.join(','))}`;
          }}
        >
          <Boxes size={14} />
          {t('boq.open_in_bim_viewer', { defaultValue: 'Open in BIM Viewer' })}
        </a>
      </div>
    </div>
  );
});

/* ── Inline Number Input ──────────────────────────────────────────── */

function InlineNumberInput({
  value,
  onCommit,
  className,
  fmt,
}: {
  value: number;
  onCommit: (v: number) => void;
  className?: string;
  fmt: Intl.NumberFormat;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = useCallback(() => {
    setText(String(value));
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }, [value]);

  const commit = useCallback(() => {
    setEditing(false);
    const parsed = parseFloat(text.replace(',', '.'));
    if (!isNaN(parsed) && parsed !== value) {
      onCommit(parsed);
    }
  }, [text, value, onCommit]);

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setEditing(false);
        }}
        className={`bg-white dark:bg-surface-primary border border-oe-blue rounded px-1 py-0 text-right tabular-nums outline-none ${className ?? ''}`}
        aria-label={t('boq.inline_edit_number', { defaultValue: 'Edit value' })}
        autoFocus
      />
    );
  }

  return (
    <span
      onDoubleClick={startEdit}
      className={`cursor-text hover:bg-oe-blue-subtle/50 rounded px-1 transition-colors ${className ?? ''}`}
      title={t('boq.double_click_to_edit', { defaultValue: 'Double-click to edit' })}
    >
      {fmt.format(value)}
    </span>
  );
}

function InlineTextInput({
  value,
  onCommit,
  className,
}: {
  value: string;
  onCommit: (v: string) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = useCallback(() => {
    setText(value);
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }, [value]);

  const commit = useCallback(() => {
    setEditing(false);
    const trimmed = text.trim();
    if (trimmed && trimmed !== value) {
      onCommit(trimmed);
    }
  }, [text, value, onCommit]);

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setEditing(false);
        }}
        className={`bg-white dark:bg-surface-primary border border-oe-blue rounded px-1 py-0 outline-none ${className ?? ''}`}
        aria-label={t('boq.inline_edit_text', { defaultValue: 'Edit text' })}
        autoFocus
      />
    );
  }

  return (
    <span
      onDoubleClick={startEdit}
      className={`cursor-text hover:bg-oe-blue-subtle/50 rounded px-1 transition-colors truncate ${className ?? ''}`}
      title={t('boq.double_click_to_edit', { defaultValue: 'Double-click to edit' })}
    >
      {value}
    </span>
  );
}

/* ── Editable Resource Row ───────────────────────────────────────── */

interface ColWidths { leftPad: number; unit: number; quantity: number; unitRate: number; total: number; actions: number }

function EditableResourceRow({ data, ctx, colWidths }: { data: Record<string, unknown>; ctx: FullGridContext; colWidths: ColWidths }) {
  const badge = RESOURCE_TYPE_BADGE[(data._resourceType as string)] ?? RESOURCE_TYPE_BADGE.other ?? { bg: 'bg-gray-100 text-gray-600', label: '?' };
  const qty = (data._resourceQty as number) ?? 0;
  const rate = (data._resourceRate as number) ?? 0;
  const total = qty * rate;
  const formattedTotal = fmtWithCurrency(total, ctx.locale ?? 'de-DE', ctx.currencyCode ?? 'EUR');
  const posId = data._parentPositionId as string;
  const resIdx = data._resourceIndex as number;

  const handleQtyChange = useCallback(
    (v: number) => ctx.onUpdateResource?.(posId, resIdx, 'quantity', v),
    [ctx, posId, resIdx],
  );
  const handleRateChange = useCallback(
    (v: number) => ctx.onUpdateResource?.(posId, resIdx, 'unit_rate', v),
    [ctx, posId, resIdx],
  );

  const handleNameChange = useCallback(
    (v: string) => ctx.onUpdateResource?.(posId, resIdx, 'name', v),
    [ctx, posId, resIdx],
  );

  return (
    <div
      className="flex items-center w-full h-full gap-2 select-none group/res text-[11px]
                  bg-surface-secondary/40 border-b border-border-light/50"
      style={{ paddingLeft: `${colWidths.leftPad}px`, paddingRight: '4px' }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        ctx.onShowContextMenu?.(e, 'resource', data);
      }}
    >
      {/* Type badge */}
      <span className={`shrink-0 inline-flex items-center h-4 px-1.5 rounded text-[9px] font-bold uppercase tracking-wider ${badge.bg}`}>
        {badge.label}
      </span>

      {/* Name — editable */}
      <span className="truncate min-w-0 flex-1 text-content-secondary font-medium">
        <InlineTextInput value={data._resourceName as string} onCommit={handleNameChange} className="w-full text-[11px]" />
      </span>

      {/* Code (small, muted) */}
      {typeof data._resourceCode === 'string' && data._resourceCode && (
        <span className="shrink-0 text-[9px] font-mono text-content-quaternary truncate max-w-[60px]" title={data._resourceCode}>
          {data._resourceCode}
        </span>
      )}

      {/* Unit — aligned to grid Unit column */}
      <span className="shrink-0 text-center text-content-tertiary" style={{ width: `${colWidths.unit}px` }}>
        <InlineTextInput value={data._resourceUnit as string} onCommit={(v: string) => ctx.onUpdateResource?.(posId, resIdx, 'unit', v)} className="w-full text-[11px] text-center" />
      </span>

      {/* Quantity — aligned to grid Qty column */}
      <span className="shrink-0 text-right tabular-nums text-content-secondary" style={{ width: `${colWidths.quantity}px` }}>
        <InlineNumberInput value={qty} onCommit={handleQtyChange} fmt={ctx.fmt} className="w-full text-[11px]" />
      </span>

      {/* Rate — aligned to grid Unit Rate column */}
      <span className="shrink-0 text-right tabular-nums text-content-secondary" style={{ width: `${colWidths.unitRate}px` }}>
        <InlineNumberInput value={rate} onCommit={handleRateChange} fmt={ctx.fmt} className="w-full text-[11px]" />
      </span>

      {/* Total — aligned to grid Total column */}
      <span className="shrink-0 text-right tabular-nums font-medium text-content-primary" style={{ width: `${colWidths.total}px` }}>
        {formattedTotal}
      </span>

      {/* Actions — aligned to grid Actions column */}
      <span className="shrink-0 flex items-center justify-center gap-0.5" style={{ width: `${colWidths.actions}px` }}>
        <button
          onClick={(e) => {
            e.stopPropagation();
            ctx.onSaveResourceToCatalog?.(posId, resIdx);
          }}
          className="shrink-0 h-4 w-4 flex items-center justify-center rounded
                     text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle
                     opacity-0 group-hover/res:opacity-100 transition-all"
          title={ctx.t('boq.save_to_catalog', { defaultValue: 'Save to My Catalog' })}
        >
          <BookmarkPlus size={10} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            ctx.onRemoveResource?.(posId, resIdx);
          }}
          className="shrink-0 h-4 w-4 flex items-center justify-center rounded
                     text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg
                     opacity-0 group-hover/res:opacity-100 transition-all"
        >
          <X size={10} />
        </button>
      </span>
    </div>
  );
}

/* ── Resource Full-Width Renderer ──────────────────────────────────── */

export function ResourceFullWidthRenderer(params: ICellRendererParams) {
  const { data, context, api } = params;
  const ctx = context as FullGridContext | undefined;

  // Read actual column widths from the grid for perfect alignment
  const colWidths = useMemo(() => {
    const getW = (id: string) => api?.getColumn(id)?.getActualWidth() ?? 0;
    const leftPad = getW('_drag') + getW('_checkbox') + getW('ordinal');
    return {
      leftPad,
      unit: getW('unit'),
      quantity: getW('quantity'),
      unitRate: getW('unit_rate'),
      total: getW('total'),
      actions: getW('_actions'),
    };
  }, [api]);

  if (!ctx) return null;

  // Section row — delegate to SectionFullWidthRenderer
  if (data?._isSection) {
    return <SectionFullWidthRenderer {...params} />;
  }

  // Resource sub-row
  if (data?._isResource) {
    return <EditableResourceRow data={data} ctx={ctx} colWidths={colWidths} />;
  }

  // "Add resource" row
  if (data?._isAddResource) {
    return (
      <div
        className="flex items-center w-full h-full pr-3 gap-2 select-none
                    bg-surface-secondary/20 border-b border-border-light/30"
        style={{ paddingLeft: `${colWidths.leftPad}px` }}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
          ctx.onShowContextMenu?.(e, 'addResource', data);
        }}
      >
        <button
          onClick={(e) => {
            e.stopPropagation();
            ctx.onAddManualResource?.(data._parentPositionId);
          }}
          className="flex items-center gap-1.5 h-5 px-2 rounded text-[10px] font-medium
                     text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle transition-all"
        >
          <Plus size={10} />
          {ctx.t('boq.add_resource_manual', { defaultValue: 'Add Resource' })}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            ctx.onOpenCostDbForPosition?.(data._parentPositionId);
          }}
          className="flex items-center gap-1.5 h-5 px-2 rounded text-[10px] font-medium
                     text-content-tertiary hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all"
        >
          <Plus size={10} />
          {ctx.t('boq.add_from_database', { defaultValue: 'From Database' })}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            ctx.onOpenCatalogForPosition?.(data._parentPositionId);
          }}
          className="flex items-center gap-1.5 h-5 px-2 rounded text-[10px] font-medium
                     text-content-tertiary hover:text-teal-600 hover:bg-teal-50 dark:hover:bg-teal-900/20 transition-all"
        >
          <Boxes size={10} />
          {ctx.t('boq.add_from_catalog_short', { defaultValue: 'From Catalog' })}
        </button>
        <div className="flex-1" />
        {typeof data._positionResourceTotal === 'number' && data._positionResourceTotal > 0 && (
          <span className="text-[10px] font-medium text-content-tertiary tabular-nums pr-5">
            {ctx.t('boq.resources_total', { defaultValue: 'Resources total' })}: {fmtWithCurrency(data._positionResourceTotal as number, ctx.locale ?? 'de-DE', ctx.currencyCode ?? 'EUR')}
          </span>
        )}
      </div>
    );
  }

  // Fallback: delegate to section renderer
  return <SectionFullWidthRenderer {...params} />;
}

/* ── Quantity Cell — clean number, BIM-sourced shown with subtle bg ─ */

export function QuantityCellRenderer(params: ICellRendererParams) {
  const { data, value, context } = params;
  if (!data || data._isSection || data._isFooter) {
    return <span className="text-right text-xs tabular-nums">{value != null ? value : ''}</span>;
  }

  const ctx = context as FullGridContext | undefined;
  // Smart formatting: >=1 → 2 decimals; <1 → up to 4; <0.01 → show all significant digits
  let formatted = '';
  if (value != null) {
    const num = typeof value === 'number' ? value : parseFloat(String(value));
    if (!isNaN(num)) {
      const absVal = Math.abs(num);
      let maxFrac = 2;
      if (absVal > 0 && absVal < 0.01) {
        maxFrac = Math.max(6, Math.ceil(-Math.log10(absVal)) + 2);
      } else if (absVal > 0 && absVal < 1) {
        maxFrac = 4;
      }
      // Always use a dedicated formatter with the computed maxFrac
      // (ctx.fmt is fixed at 2 decimals and would hide small values)
      const f = new Intl.NumberFormat(ctx?.locale ?? 'en', {
        minimumFractionDigits: 2,
        maximumFractionDigits: maxFrac,
      });
      formatted = f.format(num);
    }
  }

  const meta = (data.metadata ?? {}) as Record<string, unknown>;
  const hasBimSource = !!meta.bim_qty_source;
  const hasPdfSource = !!meta.pdf_measurement_source;

  let colorClass = '';
  let titleText: string | undefined;
  if (hasPdfSource) {
    colorClass = 'font-semibold text-rose-700 dark:text-rose-400';
    titleText = String(meta.pdf_measurement_source);
  } else if (hasBimSource) {
    colorClass = 'font-semibold text-emerald-700 dark:text-emerald-400';
    titleText = String(meta.bim_qty_source);
  }

  return (
    <span
      className={`block text-right text-xs tabular-nums w-full h-full leading-[32px] ${colorClass}`}
      title={titleText}
    >
      {formatted}
    </span>
  );
}

/* ── Unit Cell — shows unit + BIM param name if sourced from model ── */

export function UnitCellRenderer(params: ICellRendererParams) {
  const { data, value } = params;
  if (!data || data._isSection || data._isFooter) {
    return <span className="text-center text-2xs font-mono uppercase">{value ?? ''}</span>;
  }

  const meta = (data.metadata ?? {}) as Record<string, unknown>;
  const bimSource = meta.bim_qty_source as string | undefined;
  const pdfSource = meta.pdf_measurement_source as string | undefined;

  // No source indicator needed
  if (!bimSource && !pdfSource) {
    return <span className="text-center text-2xs font-mono uppercase w-full block">{value ?? ''}</span>;
  }

  if (pdfSource) {
    // Extract short label: "Takeoff: Area on Page 3" -> "Page 3"
    const parts = pdfSource.split(' on ');
    const shortLabel = (parts[parts.length - 1] ?? pdfSource).trim();
    return (
      <div className="flex flex-col items-center justify-center h-full w-full gap-0">
        <span className="text-2xs font-mono uppercase leading-tight">{value ?? ''}</span>
        <span
          className="text-[7px] leading-none font-medium text-rose-600 dark:text-rose-400 truncate max-w-full"
          title={pdfSource}
        >
          {shortLabel}
        </span>
      </div>
    );
  }

  // BIM source (existing behavior)
  // Extract short param name: "BIM: Wall / Area" -> "Area"
  const parts = (bimSource ?? '').split('/');
  const paramName = (parts[parts.length - 1] ?? bimSource ?? '').trim();

  return (
    <div className="flex flex-col items-center justify-center h-full w-full gap-0">
      <span className="text-2xs font-mono uppercase leading-tight">{value ?? ''}</span>
      <span
        className="text-[7px] leading-none font-medium text-emerald-600 dark:text-emerald-400 truncate max-w-full"
        title={bimSource}
      >
        {paramName}
      </span>
    </div>
  );
}

/**
 * BIM Quantity Picker cell renderer — placed in a narrow column before Qty.
 * Shows a ruler icon when the position is linked to BIM elements.
 * Clicking opens a portal popover with available BIM quantities.
 */
export function BimQtyPickerCellRenderer(params: ICellRendererParams) {
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;
  const t = ctx?.t ?? ((key: string, opts?: Record<string, string>) => (opts?.defaultValue as string) ?? key);

  if (!data || data._isFooter || data._isResource || data._isAddResource || data._isSection) {
    return null;
  }

  const cadElementIds: string[] = Array.isArray(data.cad_element_ids)
    ? data.cad_element_ids.filter((x: unknown): x is string => typeof x === 'string' && (x as string).length > 0)
    : [];
  const hasBimLink = cadElementIds.length > 0 && !!ctx?.bimModelId;

  const [showPicker, setShowPicker] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

  const handleOpen = useCallback(() => {
    if (btnRef.current) {
      setAnchorRect(btnRef.current.getBoundingClientRect());
    }
    setShowPicker(true);
  }, []);

  if (!hasBimLink) return null;

  return (
    <div className="flex items-center justify-center h-full w-full">
      <button
        ref={btnRef}
        onClick={handleOpen}
        className="h-6 w-6 flex items-center justify-center rounded
                   text-emerald-600/60 hover:text-emerald-600 hover:bg-emerald-50
                   dark:hover:bg-emerald-950/30 transition-colors cursor-pointer"
        title={t('boq.pick_qty_from_bim', { defaultValue: 'Pick quantity from BIM' })}
        aria-label={t('boq.pick_qty_from_bim', { defaultValue: 'Pick quantity from BIM' })}
      >
        <Ruler size={13} />
      </button>
      {showPicker && ctx?.bimModelId && anchorRect && (
        <BIMQuantityPicker
          positionId={data.id}
          cadElementIds={cadElementIds}
          bimModelId={ctx.bimModelId}
          currentQuantity={data.quantity ?? 0}
          currentUnit={data.unit ?? ''}
          anchorRect={anchorRect}
          onSelectQuantity={(val, source) => {
            ctx?.onUpdatePosition?.(
              data.id,
              { quantity: val, metadata: { ...((data.metadata ?? {}) as Record<string, unknown>), bim_qty_source: source } },
              { quantity: data.quantity },
            );
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}
