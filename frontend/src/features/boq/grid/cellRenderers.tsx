import { useState, useCallback, useRef } from 'react';
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
} from 'lucide-react';
import { RESOURCE_TYPE_BADGE, fmtWithCurrency } from '../boqHelpers';
import { countComments } from '../CommentDrawer';

/* ── Validation Status Dot ────────────────────────────────────────── */

const VALIDATION_DOT_STYLES: Record<string, string> = {
  passed: 'bg-emerald-500',
  warnings: 'bg-amber-500',
  errors: 'bg-red-500',
  pending: 'bg-gray-300 dark:bg-gray-600',
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

/* ── Ordinal + Validation Dot + Resource Chevron Renderer ─────────── */

export function OrdinalCellRenderer(params: ICellRendererParams) {
  const { data, value, context } = params;
  if (!data || data._isSection || data._isFooter) return <span>{value}</span>;

  const status = data.validation_status ?? 'pending';
  const dotColor = VALIDATION_DOT_STYLES[status] ?? VALIDATION_DOT_STYLES.pending;

  const ctx = context as ResourceGridContext | undefined;
  const hasResources = Array.isArray(data.metadata?.resources) && data.metadata.resources.length > 0;
  const isExpanded = ctx?.expandedPositions?.has(data.id) ?? false;

  return (
    <div className="flex items-center gap-1 overflow-hidden">
      {hasResources ? (
        <button
          onMouseDown={(e) => e.preventDefault()}
          onClick={(e) => {
            e.stopPropagation();
            ctx?.onToggleResources?.(data.id);
          }}
          className="shrink-0 h-4 w-4 flex items-center justify-center rounded text-content-tertiary hover:text-content-primary transition-colors"
          aria-label={isExpanded ? 'Collapse resources' : 'Expand resources'}
          aria-expanded={isExpanded}
        >
          {isExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </button>
      ) : (
        <span className="shrink-0 w-4" />
      )}
      <span className="text-xs font-mono truncate min-w-0">{value}</span>
      <span
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${dotColor}`}
        title={status}
      />
    </div>
  );
}

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

function EditableResourceRow({ data, ctx }: { data: Record<string, unknown>; ctx: FullGridContext }) {
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
      className="flex items-center w-full h-full pr-3 gap-2 select-none group/res text-[11px]
                  bg-surface-secondary/40 border-b border-border-light/50"
      style={{ paddingLeft: '160px' }}
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

      {/* Unit — editable, aligned to grid Unit column (80px) */}
      <span className="shrink-0 text-center text-content-tertiary" style={{ width: '80px' }}>
        <InlineTextInput value={data._resourceUnit as string} onCommit={(v: string) => ctx.onUpdateResource?.(posId, resIdx, 'unit', v)} className="w-full text-[11px] text-center" />
      </span>

      {/* Quantity — editable, aligned to grid Qty column (100px) */}
      <span className="shrink-0 text-right tabular-nums text-content-secondary" style={{ width: '100px' }}>
        <InlineNumberInput value={qty} onCommit={handleQtyChange} fmt={ctx.fmt} className="w-full text-[11px]" />
      </span>

      {/* Rate — editable, aligned to grid Unit Rate column (110px) */}
      <span className="shrink-0 text-right tabular-nums text-content-secondary" style={{ width: '110px' }}>
        <InlineNumberInput value={rate} onCommit={handleRateChange} fmt={ctx.fmt} className="w-full text-[11px]" />
      </span>

      {/* Total — auto-calculated, aligned to grid Total column (130px) */}
      <span className="shrink-0 text-right tabular-nums font-medium text-content-primary" style={{ width: '130px' }}>
        {formattedTotal}
      </span>

      {/* Actions — aligned to grid Actions column (44px) */}
      <span className="shrink-0 flex items-center justify-center gap-0.5" style={{ width: '44px' }}>
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
  const { data, context } = params;
  const ctx = context as FullGridContext | undefined;

  if (!ctx) return null;

  // Resource sub-row
  if (data?._isResource) {
    return <EditableResourceRow data={data} ctx={ctx} />;
  }

  // "Add resource" row
  if (data?._isAddResource) {
    return (
      <div
        className="flex items-center w-full h-full pr-3 gap-2 select-none
                    bg-surface-secondary/20 border-b border-border-light/30"
        style={{ paddingLeft: '160px' }}
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
