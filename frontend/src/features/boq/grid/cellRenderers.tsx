import { useState, useCallback, useRef, useMemo, useEffect, forwardRef } from 'react';
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
} from 'lucide-react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { RESOURCE_TYPE_BADGE, fmtWithCurrency } from '../boqHelpers';
import { countComments } from '../CommentDrawer';
import { BIMQuantityPicker } from './BIMQuantityPicker';
import { MiniGeometryPreview } from '@/shared/ui/MiniGeometryPreview';
import { fetchBIMElementsByIds } from '@/features/bim/api';

/* ── Validation Status Dot ────────────────────────────────────────── */

const VALIDATION_DOT_STYLES: Record<string, string> = {
  passed: 'bg-emerald-500',
  warnings: 'bg-amber-500',
  errors: 'bg-red-500',
  pending: 'bg-gray-300 dark:bg-gray-600',
};

const VALIDATION_DOT_TOOLTIP: Record<string, string> = {
  passed: 'Validation passed — position is complete',
  warnings: 'Validation warnings — review recommended',
  errors: 'Validation errors — action required',
  pending: 'Validation pending — not yet checked',
};

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
  const ctx = context as SectionGroupContext | undefined;

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

  return (
    <div className="flex items-center w-full h-full px-2 gap-2 select-none group/section">
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: (...args: any[]) => string;
}

export type FullGridContext = ActionsContext & ResourceGridContext & SectionGroupContext & {
  onApplyAnomalySuggestion?: (positionId: string, suggestedRate: number) => void;
  /** First ready BIM model ID for the current project (used for mini 3D previews). */
  bimModelId?: string | null;
  /** Update a BOQ position — used by QuantityCellRenderer to apply BIM quantities. */
  onUpdatePosition?: (id: string, data: Record<string, unknown>, oldData: Record<string, unknown>) => void;
  /** Highlight linked BIM elements in the 3D viewer (triggered from ordinal badge). */
  onHighlightBIMElements?: (elementIds: string[]) => void;
};

/* ── Actions Cell Renderer ────────────────────────────────────────── */

export function ActionsCellRenderer(params: ICellRendererParams) {
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;

  if (!data || data._isSection || data._isFooter) return null;

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
          title={`${commentCount} comment${commentCount > 1 ? 's' : ''}`}
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
        title="Actions"
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

  const hasResources = Array.isArray(data.metadata?.resources) && data.metadata.resources.length > 0;
  if (!hasResources) return null;

  const isExpanded = ctx?.expandedPositions?.has(data.id) ?? false;

  return (
    <div className="flex items-center justify-center h-full w-full">
      <button
        onClick={() => ctx?.onToggleResources?.(data.id)}
        className="h-6 w-6 flex items-center justify-center rounded
                   text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10
                   transition-colors cursor-pointer"
        title={isExpanded ? 'Collapse resources' : 'Expand resources'}
      >
        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
    </div>
  );
}

/* ── Ordinal + Validation Dot ─────────────────────────────────────── */

export function OrdinalCellRenderer(params: ICellRendererParams) {
  const { data, value } = params;
  if (!data || data._isSection || data._isFooter) return <span>{value}</span>;

  const status = data.validation_status ?? 'pending';
  const dotColor = VALIDATION_DOT_STYLES[status] ?? VALIDATION_DOT_STYLES.pending;

  return (
    <div className="flex items-center gap-1 overflow-hidden">
      <span className="text-xs font-mono truncate min-w-0">{value}</span>
      <span
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${dotColor} cursor-help`}
        title={VALIDATION_DOT_TOOLTIP[status] ?? status}
      />
    </div>
  );
}

/* ── BIM Link Badge + Mini 3D Preview (own column) ───────────────── */

export function BimLinkCellRenderer(params: ICellRendererParams) {
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;

  if (!data || data._isFooter || data._isResource || data._isAddResource || data._isSection) {
    return null;
  }

  const bimLinks: unknown = data.cad_element_ids;
  const bimLinkIds: string[] = Array.isArray(bimLinks)
    ? bimLinks.filter((x): x is string => typeof x === 'string' && x.length > 0)
    : [];
  const bimLinkCount = bimLinkIds.length;
  const hasBimLink = bimLinkCount > 0 && !!ctx?.bimModelId;

  const [showPreview, setShowPreview] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const handleOpen = useCallback(() => {
    console.log('[BimLink] Opening preview', { bimLinkIds, modelId: ctx?.bimModelId });
    if (btnRef.current) {
      setAnchorRect(btnRef.current.getBoundingClientRect());
    }
    setShowPreview(true);
    ctx?.onHighlightBIMElements?.(bimLinkIds);
  }, [bimLinkIds, ctx]);

  if (!hasBimLink) return null;

  const popoverStyle = anchorRect
    ? {
        position: 'fixed' as const,
        left: Math.min(anchorRect.right + 8, window.innerWidth - 660),
        top: Math.max(8, Math.min(anchorRect.top - 40, window.innerHeight - 520)),
        zIndex: 9999,
      }
    : undefined;

  return (
    <div className="flex items-center justify-center h-full w-full">
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
        title={`${bimLinkCount} BIM element${bimLinkCount > 1 ? 's' : ''} linked — click to preview`}
      >
        <Cuboid size={11} />
        {bimLinkCount}
      </button>
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
  const { data, isLoading } = useQuery({
    queryKey: ['bim-link-preview', modelId, ...elementIds],
    queryFn: () => fetchBIMElementsByIds(modelId, elementIds),
    enabled: elementIds.length > 0,
    staleTime: 5 * 60_000,
  });
  const elements = data?.items ?? [];

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

  // Compute sums across all elements for each quantity key
  const quantitySums = useMemo(() => {
    if (elements.length === 0) return [] as { key: string; label: string; sum: number; unit: string; count: number }[];
    const map = new Map<string, { key: string; label: string; sum: number; unit: string; count: number }>();
    for (const el of elements) {
      if (!el.quantities) continue;
      for (const [k, v] of Object.entries(el.quantities)) {
        const num = typeof v === 'number' ? v : parseFloat(String(v));
        if (isNaN(num) || num === 0) continue;
        const existing = map.get(k);
        const label = k.replace(/_m2$|_m3$|_m$|_kg$/, '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
        if (existing) {
          existing.sum += num;
          existing.count += 1;
        } else {
          let unit = '';
          if (k.includes('area') || k.endsWith('_m2')) unit = 'm\u00B2';
          else if (k.includes('volume') || k.endsWith('_m3')) unit = 'm\u00B3';
          else if (k.includes('length') || k.endsWith('_m') || k.includes('height') || k.includes('width') || k.includes('perimeter')) unit = 'm';
          else if (k.includes('weight') || k.endsWith('_kg')) unit = 'kg';
          else if (k.includes('count')) unit = 'pcs';
          map.set(k, { key: k, label, sum: num, unit, count: 1 });
        }
      }
    }
    return Array.from(map.values()).sort((a, b) => b.sum - a.sum);
  }, [elements]);

  return (
    <div
      ref={combinedRef}
      className="rounded-xl shadow-2xl border border-border-light dark:border-border-dark
                 bg-white dark:bg-surface-elevated overflow-hidden"
      style={{ ...style, width: canApply ? 640 : 380 }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border-light dark:border-border-dark bg-surface-secondary/30">
        <div className="flex items-center gap-2">
          <Cuboid size={14} className="text-oe-blue" />
          <span className="text-xs font-semibold text-content-primary">
            Linked Geometry
          </span>
          <span className="text-[10px] text-content-tertiary tabular-nums">
            ({elementIds.length} element{elementIds.length !== 1 ? 's' : ''})
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

      <div className={canApply ? 'flex' : ''}>
        {/* Left column: 3D preview + element cards */}
        <div className={canApply ? 'w-[380px] shrink-0 border-r border-border-light dark:border-border-dark' : 'w-full'}>
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
                Loading element data...
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

        {/* Right column: properties + quantity picker */}
        {canApply && (
          <div className="w-[260px] flex flex-col">
            {/* Properties header + toggle */}
            <button
              onClick={() => setShowAllProps((v) => !v)}
              className="flex items-center gap-1.5 px-3 py-1.5 w-full bg-blue-50/50 dark:bg-blue-950/20 border-b border-border-light/50 dark:border-border-dark/50 hover:bg-blue-50 dark:hover:bg-blue-950/30 transition-colors"
            >
              <Info size={11} className="text-blue-600 shrink-0" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-700 dark:text-blue-400 flex-1 text-left">
                Properties
              </span>
              <ChevronDown size={12} className={`text-blue-500 transition-transform ${showAllProps ? 'rotate-180' : ''}`} />
            </button>
            <div className={`overflow-y-auto border-b border-border-light dark:border-border-dark ${showAllProps ? 'max-h-[280px]' : 'max-h-[140px]'}`}>
              {isLoading && (
                <div className="flex items-center justify-center gap-2 py-4">
                  <Loader2 size={12} className="animate-spin text-content-tertiary" />
                </div>
              )}
              {!isLoading && elements.map((el) => {
                // Collect numeric entries from quantities + properties
                const numericEntries: { key: string; value: number; source: 'qty' | 'prop' }[] = [];
                if (el.quantities) {
                  for (const [k, v] of Object.entries(el.quantities)) {
                    const num = typeof v === 'number' ? v : parseFloat(String(v));
                    if (!isNaN(num)) numericEntries.push({ key: k, value: num, source: 'qty' });
                  }
                }
                if (showAllProps && el.properties) {
                  for (const [k, v] of Object.entries(el.properties)) {
                    const num = typeof v === 'number' ? v : parseFloat(String(v));
                    if (!isNaN(num) && !numericEntries.some((e) => e.key === k)) {
                      numericEntries.push({ key: k, value: num, source: 'prop' });
                    }
                  }
                }
                if (numericEntries.length === 0) return null;
                return (
                  <div key={el.id} className="px-3 py-1.5 border-b border-border-light/30 dark:border-border-dark/30 last:border-b-0">
                    {elements.length > 1 && (
                      <div className="text-[9px] font-medium text-content-tertiary mb-0.5 truncate">{el.name || el.element_type}</div>
                    )}
                    {numericEntries.map(({ key, value, source }) => (
                      <div key={key} className="flex items-baseline justify-between gap-2 py-0.5">
                        <span className={`text-[10px] truncate ${source === 'prop' ? 'text-content-tertiary italic' : 'text-content-secondary'}`}>
                          {key.replace(/_/g, ' ')}
                        </span>
                        <span className="text-[10px] font-mono text-content-primary tabular-nums shrink-0 font-medium">
                          {value.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })}
              {!isLoading && elements.every((el) => !el.quantities || Object.keys(el.quantities).length === 0) && !showAllProps && (
                <div className="py-3 text-center text-[10px] text-content-tertiary">No quantities — click to show all properties</div>
              )}
            </div>

            {/* Apply Quantity section — aggregated sums */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50/50 dark:bg-emerald-950/20 border-b border-border-light/50 dark:border-border-dark/50">
              <Ruler size={11} className="text-emerald-600 shrink-0" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                Apply to BOQ
              </span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {isLoading && (
                <div className="flex items-center justify-center gap-2 py-4">
                  <Loader2 size={12} className="animate-spin text-content-tertiary" />
                </div>
              )}
              {!isLoading && quantitySums.length === 0 && (
                <div className="py-3 text-center text-[10px] text-content-tertiary">
                  No numeric quantities
                </div>
              )}
              {!isLoading && quantitySums.map((s) => {
                const isCurrent = Math.abs(s.sum - currentQuantity) < 0.001;
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
                      <span className="text-[11px] text-content-secondary truncate block">
                        {s.label}
                      </span>
                      <div className="flex items-baseline gap-1">
                        <span className="text-[12px] tabular-nums text-content-primary font-semibold">
                          {Number.isInteger(s.sum) ? s.sum.toLocaleString('en') : s.sum.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                        </span>
                        {s.unit && (
                          <span className="text-[9px] text-content-quaternary font-mono">{s.unit}</span>
                        )}
                        {elements.length > 1 && s.count > 1 && (
                          <span className="text-[8px] text-content-quaternary">({s.count} el.)</span>
                        )}
                      </div>
                    </div>
                    {isCurrent ? (
                      <span className="text-[9px] text-emerald-600 font-semibold shrink-0 bg-emerald-100 dark:bg-emerald-900/40 px-1.5 py-0.5 rounded">
                        current
                      </span>
                    ) : (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleUseQuantity(s.sum, `BIM: ${s.label}`);
                        }}
                        className="shrink-0 h-6 flex items-center gap-0.5 px-2.5 rounded text-[10px] font-semibold
                                   text-white bg-emerald-500 hover:bg-emerald-600
                                   shadow-sm transition-all"
                      >
                        Use <ArrowRight size={9} />
                      </button>
                    )}
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
          Open in BIM Viewer
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
        autoFocus
      />
    );
  }

  return (
    <span
      onDoubleClick={startEdit}
      className={`cursor-text hover:bg-oe-blue-subtle/50 rounded px-1 transition-colors ${className ?? ''}`}
      title="Double-click to edit"
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
        autoFocus
      />
    );
  }

  return (
    <span
      onDoubleClick={startEdit}
      className={`cursor-text hover:bg-oe-blue-subtle/50 rounded px-1 transition-colors truncate ${className ?? ''}`}
      title="Double-click to edit"
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

  return (
    <span
      className={`block text-right text-xs tabular-nums w-full h-full leading-[32px] ${
        hasBimSource
          ? 'font-semibold text-emerald-700 dark:text-emerald-400'
          : ''
      }`}
      title={hasBimSource ? String(meta.bim_qty_source) : undefined}
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

  if (!bimSource) {
    return <span className="text-center text-2xs font-mono uppercase w-full block">{value ?? ''}</span>;
  }

  // Extract short param name: "BIM: Wall / Area" -> "Area"
  const parts = bimSource.split('/');
  const paramName = (parts[parts.length - 1] ?? bimSource).trim();

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
        title="Pick quantity from BIM"
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
