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
  ExternalLink,
} from 'lucide-react';
import { createPortal } from 'react-dom';
import { useQuery, useQueries } from '@tanstack/react-query';
import {
  COMMON_CURRENCIES,
  CURRENCY_SYMBOL,
  RESOURCE_TYPE_BADGE,
  fmtWithCurrency,
  getUnitsForLocale,
  saveCustomUnit,
} from '../boqHelpers';
import { RESOURCE_TYPES, getResourceTypeLabel } from '../boqResourceTypes';
import { countComments } from '../CommentDrawer';
import { BIMQuantityPicker } from './BIMQuantityPicker';
import { MiniGeometryPreview } from '@/shared/ui/MiniGeometryPreview';
import { fetchBIMElementsByIds, fetchBIMElementProperties } from '@/features/bim/api';
import type { BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useFxRatesStore, getFxRate } from '@/stores/useFxRatesStore';
import { isFormula, evaluateFormula } from './cellEditors';
import { VariantPicker } from '@/features/costs/VariantPicker';
import type { CostVariant, VariantStats } from '@/features/costs/api';

/* ── Variant suffix stripper ──────────────────────────────────────────
 *  Legacy CWICR position-mode applies appended "(Variant: <label>)" /
 *  "(Вариант: <label>)" / "(Variante: <label>)" to the position
 *  description. The variant pick already surfaces via the blue Variant
 *  pill in DescriptionCellRenderer, so the trailing parenthetical is
 *  redundant noise — strip it on display.
 *
 *  Two passes are needed:
 *   1. ``WITH_PARENS_RE`` — the canonical "(Variant: …)" form with
 *      balanced parens at the very end. Uses ``[\s\S]`` (no anchored
 *      class) to allow nested parens / colons / multilingual chars
 *      inside the label.
 *   2. ``BARE_RE`` — fallback for descriptions where the parens were
 *      dropped (legacy migrations, hand-edits). Strips a trailing
 *      "Variant: …" / "Вариант: …" segment with no closing paren.
 *
 *  Both are case-insensitive, Unicode-aware, and cover Latin + Cyrillic
 *  spellings (incl. common typos: "Вриант", "Варинт"). ────────────── */
const VARIANT_KEYWORDS =
  '(?:Variant|Variante|Variantă|Variantti|Variation|Varianta|Variantas|Varianti|Wariant|Wariacja|Variabel|Sürüm|Вариант|Варіант|Варијанта|Вріант|Вриант|Варинт|Варіант|Vairantă)';
const VARIANT_SUFFIX_WITH_PARENS_RE = new RegExp(
  `\\s*[(（\\[]\\s*${VARIANT_KEYWORDS}\\s*[:：][\\s\\S]*?[)）\\]]\\s*$`,
  'iu',
);
const VARIANT_SUFFIX_BARE_RE = new RegExp(
  `\\s*[\\.,;·\\-—]?\\s*${VARIANT_KEYWORDS}\\s*[:：][^\\n\\r]*$`,
  'iu',
);

function stripVariantSuffix(s: string | null | undefined): string {
  if (!s) return '';
  let out = String(s);
  // Loop the with-parens pass to strip multiple stacked suffixes.
  for (let i = 0; i < 3; i++) {
    const next = out.replace(VARIANT_SUFFIX_WITH_PARENS_RE, '');
    if (next === out) break;
    out = next;
  }
  out = out.replace(VARIANT_SUFFIX_BARE_RE, '');
  return out.trim();
}

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
  /** Update multiple fields of a resource in ONE mutation. Use when two fields must
   *  change atomically (e.g. renaming a catalogued resource also clears its code).
   *  Without this, two sequential `onUpdateResource` calls race on the React Query
   *  cache and the second silently overwrites the first. */
  onUpdateResourceFields?: (positionId: string, resourceIndex: number, fields: Record<string, number | string>) => void;
  onSaveResourceToCatalog: (positionId: string, resourceIndex: number) => void;
  /** Save a variant-header synthetic row to the user's catalog under the
   *  user-edited custom name. Reads the chosen variant off the position
   *  directly (no resource index — the variant row is synthetic). */
  onSaveVariantHeaderToCatalog?: (positionId: string, customName: string) => void;
  /** Edit qty / rate on the variant-header synthetic row. The row mirrors
   *  the parent position, so qty edits flow into ``position.quantity``
   *  and rate edits into ``position.unit_rate`` (clearing the
   *  ``metadata.variant`` snapshot so the row "becomes a regular article"
   *  with a manually-overridden rate, per the user's spec). */
  onUpdateVariantHeader?: (positionId: string, fields: { quantity?: number; unit_rate?: number }) => void;
  onOpenCostDbForPosition: (positionId: string) => void;
  onOpenCatalogForPosition: (positionId: string) => void;
  /**
   * Re-pick the variant on an already-added resource row (v2.6.26+).
   * Surfaces the existing CWICR ``VariantPicker`` against the resource's
   * cached ``available_variants`` array, then PATCHes the backend.
   * Optional — when omitted, the row's re-pick pill is not rendered
   * (graceful degrade for grids that haven't wired the callback).
   */
  onRepickResourceVariant?: (
    positionId: string,
    resourceIndex: number,
    variantCode: string,
  ) => void;
  /**
   * One-shot signal that drives the auto-open of an ``EditableResourceRow``'s
   * VariantPicker after the user clicks the position-description "V" icon.
   * The DescriptionCellRenderer fires ``onOpenVariantPickerFor`` which sets
   * this signal AND ensures the position is expanded; the row whose
   * (positionId, resourceIdx) matches consumes the signal in a mount
   * effect, opens its picker, and calls ``onClearOpenVariantPicker`` so the
   * signal is not re-fired on the next render.
   */
  openVariantPickerFor?: { positionId: string; resourceIdx: number } | null;
  onClearOpenVariantPicker?: () => void;
  /** Click handler for the position-description "V" icon — see above.
   *  Used when the position has at least one resource with cached
   *  ``available_variants``. Expands the resource panel and signals the
   *  matching ``EditableResourceRow`` to auto-open its picker. */
  onOpenVariantPickerFor?: (positionId: string, resourceIdx: number) => void;
  /** Position-level fallback for the "V" icon: legacy CWICR position-mode
   *  applies stash the variant catalog on ``position.metadata.cost_item_variants``
   *  with no per-resource cache. Click here renders a portal-anchored
   *  VariantPicker against those catalog entries; ``onApply`` calls
   *  ``onRepickPositionVariant`` so the position's ``unit_rate`` /
   *  ``metadata.variant`` flip directly. ``anchorEl`` is the V button
   *  itself so the popover positions correctly. */
  onOpenPositionVariantPicker?: (positionId: string, anchorEl: HTMLElement | null) => void;
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
  /** Issue #90: persist a Quantity-cell formula on the row's metadata. */
  onFormulaApplied?: (positionId: string, formula: string, result: number) => void;
  /**
   * RFC 37 / Issue #93 — project-level FX template used by the per-resource
   * currency picker. Empty / undefined ⇒ single-currency project.
   */
  fxRates?: { currency: string; rate: number; label?: string }[];
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

/* ── Description + CWICR Variant Badge ────────────────────────────── */

/**
 * Position-description renderer that surfaces a CWICR abstract-resource
 * marker when the position was applied from a cost item that carries
 * variants (concrete C25 / C30 / C35, …).  Two visual states:
 *
 *   • `metadata.variant = { label, price, index }` → user picked a
 *     specific variant.  Renders a bold blue pill "Variant: <label>"
 *     so the choice is unmistakable at a glance.
 *
 *   • `metadata.variant_default ∈ {"mean","median"}` → user accepted
 *     the auto-suggested rate without picking.  Renders a softer
 *     amber pill "Default · refine ▾" prompting the user to click and
 *     pick a real variant.
 *
 * The pill itself is decorative (pointer-events: none on the inner
 * text) — actual variant editing happens via the inline picker on the
 * unit_rate cell.  The description cell remains plain-text editable;
 * the renderer only owns the read-only view.
 */
export function DescriptionCellRenderer(params: ICellRendererParams) {
  const { data, value, context } = params;
  const ctx = context as FullGridContext | undefined;
  const t =
    ctx?.t ??
    ((key: string, opts?: Record<string, string | number>) =>
      (opts?.defaultValue as string) ?? key);

  // Sections + footer + resource rows have their own renderers; bail
  // out cleanly so AG Grid falls back to the default text rendering
  // for those (driven by `colDef.cellClass`).
  if (!data || data._isSection || data._isFooter || data._isResource || data._isAddResource) {
    return <span>{value ?? ''}</span>;
  }

  // Strip legacy "(Variant: …)" trailing parenthetical — variant choice
  // is already displayed via the blue Variant pill on this row, so the
  // duplicated text is just noise on legacy applies.
  const displayValue = stripVariantSuffix(value as string | null | undefined);

  const meta = (data.metadata ?? {}) as Record<string, unknown>;
  const variant = (meta as { variant?: { label?: string; price?: number; index?: number } }).variant;
  const variantDefault = (meta as { variant_default?: 'mean' | 'median' }).variant_default;
  const hasVariant = !!variant && typeof variant.label === 'string' && typeof variant.price === 'number';
  const hasDefault = !hasVariant && (variantDefault === 'mean' || variantDefault === 'median');

  /* ── "V" icon — surfaces when EITHER:
   *     (a) at least one resource on this position carries cached
   *         ``available_variants`` (>= 2) [resource-mode applies], OR
   *     (b) the position itself has ``metadata.cost_item_variants``
   *         (>= 2) [legacy position-mode CWICR applies — the catalog
   *         was stashed at position level, not per-resource].
   *
   *     Click in case (a): expand resource panel + auto-open picker on
   *     that resource (in-place re-pick, fans through onRepickResourceVariant).
   *     Click in case (b): open a position-level picker anchored to the
   *     V button itself; on apply, the position's unit_rate + metadata.variant
   *     flip directly via onRepickPositionVariant.
   *
   *     The icon stays even when a variant is already picked so the user
   *     can re-pick from the same affordance. */
  const resourcesArr = (meta as { resources?: unknown[] }).resources;
  const variantResourceIdx = Array.isArray(resourcesArr)
    ? resourcesArr.findIndex((r) => {
        if (!r || typeof r !== 'object') return false;
        const av = (r as { available_variants?: unknown }).available_variants;
        return Array.isArray(av) && av.length >= 2;
      })
    : -1;
  const hasResourceVariants = variantResourceIdx >= 0;

  const posLevelVariants = (meta as { cost_item_variants?: unknown }).cost_item_variants;
  const hasPositionVariants =
    Array.isArray(posLevelVariants) && posLevelVariants.length >= 2;

  const hasVariantResource = hasResourceVariants || hasPositionVariants;

  const positionId = data.id as string;
  const variantIconButton = hasVariantResource ? (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        if (hasResourceVariants) {
          ctx?.onOpenVariantPickerFor?.(positionId, variantResourceIdx);
        } else if (hasPositionVariants) {
          ctx?.onOpenPositionVariantPicker?.(positionId, e.currentTarget);
        }
      }}
      onMouseDown={(e) => e.stopPropagation()}
      className="shrink-0 inline-flex h-[18px] w-[18px] items-center justify-center
                 rounded-md cursor-pointer
                 bg-violet-50 dark:bg-violet-900/30
                 text-violet-700 dark:text-violet-300
                 text-[11px] font-bold leading-none
                 ring-1 ring-violet-200 dark:ring-violet-700/50
                 hover:bg-violet-100 dark:hover:bg-violet-800/40
                 hover:ring-violet-300 dark:hover:ring-violet-600
                 transition-colors duration-150"
      title={t('boq.position_variant_v_tooltip', {
        defaultValue:
          'This position uses a variant resource — click to choose / switch a price option.',
      })}
      aria-label={t('boq.position_variant_v_label', {
        defaultValue: 'Open variant picker',
      })}
      data-testid={`position-variant-v-${positionId}`}
    >
      V
    </button>
  ) : null;

  if (!hasVariant && !hasDefault) {
    if (!variantIconButton) {
      return <span className="truncate">{displayValue}</span>;
    }
    return (
      <span className="inline-flex items-center gap-1.5 min-w-0 max-w-full">
        {variantIconButton}
        <span className="truncate min-w-0">{displayValue}</span>
      </span>
    );
  }

  const fmt = (n: number) => {
    try {
      return new Intl.NumberFormat(getIntlLocale(), {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(n);
    } catch {
      return String(n);
    }
  };

  if (hasVariant) {
    // Variant choice is surfaced through the V button + the synthetic
    // VARIANT row inside the expanded resource panel \u2014 the blue
    // "Variant: <label>" pill that used to render here was redundant.
    return (
      <span className="inline-flex items-center gap-1.5 min-w-0 max-w-full">
        {variantIconButton}
        <span className="truncate min-w-0">{displayValue}</span>
      </span>
    );
  }

  // Auto-default branch: surface the "options" count + the average rate
  // so the user knows there are alternatives behind the locked-in price.
  // Stats / option count come from `cost_item_variant_count` /
  // `cost_item_variant_mean` snapshots if the apply path stamped them;
  // otherwise we fall back to a generic "default · refine" hint.
  const optsRaw = (meta as { cost_item_variant_count?: number }).cost_item_variant_count;
  const meanRaw = (meta as { cost_item_variant_mean?: number }).cost_item_variant_mean;
  const opts = typeof optsRaw === 'number' && optsRaw >= 2 ? optsRaw : null;
  const mean = typeof meanRaw === 'number' && meanRaw > 0 ? meanRaw : null;

  const tooltip = t('boq.variant_default_pill_tooltip', {
    defaultValue:
      'Auto-applied with the {{strategy}} rate. Click the unit_rate cell to pick a specific variant.',
    strategy:
      variantDefault === 'mean'
        ? t('costs.variant_mean_word', { defaultValue: 'average' })
        : t('costs.variant_median_word', { defaultValue: 'median' }),
  });

  return (
    <span className="inline-flex items-center gap-1.5 min-w-0 max-w-full">
      {variantIconButton}
      <span className="truncate min-w-0">{displayValue}</span>
      <span
        className="shrink-0 inline-flex items-center gap-1 rounded
                   bg-amber-100 dark:bg-amber-900/40
                   text-amber-700 dark:text-amber-300
                   px-1.5 py-0.5 text-2xs font-medium cursor-help"
        title={tooltip}
        data-testid="boq-variant-default-pill"
      >
        {opts != null
          ? t('boq.variant_default_pill_with_count', {
              defaultValue: 'Abstract \u00B7 {{count}} options',
              count: opts,
            })
          : t('boq.variant_default_pill', { defaultValue: 'Default \u00B7 refine \u25BE' })}
        {mean != null && (
          <span className="text-content-tertiary tabular-nums">
            {'\u00A0\u00B7\u00A0'}
            {t('costs.variant_avg_short', { defaultValue: 'avg' })} {fmt(mean)}
          </span>
        )}
      </span>
    </span>
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
    <div className="flex items-center justify-end gap-1 overflow-hidden w-full">
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
  // Convention: ordinals prefixed "TK." come from the PDF takeoff flow,
  // even when the source metadata is missing (legacy rows, seed data).
  // Treat the prefix as a soft link so the red icon surfaces and the
  // user can at least jump back to the PDF takeoff page for context.
  const isTakeoffOrdinal = typeof data.ordinal === 'string'
    && /^TK\.\d+$/.test(data.ordinal.trim());
  const hasPdfLink = !!pdfMeasurementId || !!pdfSource || isTakeoffOrdinal;

  const dwgAnnotationId = meta.dwg_annotation_id as string | undefined;
  const dwgDrawingId = meta.dwg_drawing_id as string | undefined;
  const dwgSource = meta.dwg_annotation_source as string | undefined;
  const hasDwgLink = !!dwgAnnotationId || !!dwgDrawingId || !!dwgSource;

  const [showPreview, setShowPreview] = useState(false);
  const [showPdfPopover, setShowPdfPopover] = useState(false);
  const [showDwgPopover, setShowDwgPopover] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const pdfBtnRef = useRef<HTMLButtonElement>(null);
  const dwgBtnRef = useRef<HTMLButtonElement>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [pdfAnchor, setPdfAnchor] = useState<DOMRect | null>(null);
  const [dwgAnchor, setDwgAnchor] = useState<DOMRect | null>(null);
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
    if (pdfBtnRef.current) setPdfAnchor(pdfBtnRef.current.getBoundingClientRect());
    setShowPdfPopover(true);
  }, []);

  const handleOpenDwg = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (dwgBtnRef.current) setDwgAnchor(dwgBtnRef.current.getBoundingClientRect());
    setShowDwgPopover(true);
  }, []);

  /** Build the deep-link URL for the PDF takeoff viewer, focused on the
   *  linked measurement so the user lands on the exact annotation. */
  const pdfDeepLink = useMemo(() => {
    const params = new URLSearchParams();
    params.set('tab', 'measurements');
    if (pdfMeasurementId) params.set('focus', pdfMeasurementId);
    if (pdfDocumentId) params.set('name', pdfDocumentId);
    if (pdfPage) params.set('page', String(pdfPage));
    return `/takeoff?${params.toString()}`;
  }, [pdfMeasurementId, pdfDocumentId, pdfPage]);

  /** Same for DWG. */
  const dwgDeepLink = useMemo(() => {
    const params = new URLSearchParams();
    if (dwgDrawingId) params.set('drawingId', dwgDrawingId);
    if (dwgAnnotationId) params.set('focus', dwgAnnotationId);
    return `/dwg-takeoff?${params.toString()}`;
  }, [dwgDrawingId, dwgAnnotationId]);

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
          ref={pdfBtnRef}
          onClick={handleOpenPdf}
          onMouseDown={(e) => e.stopPropagation()}
          className="h-6 w-6 inline-flex items-center justify-center rounded
                     bg-rose-500/10 text-rose-600 dark:text-rose-400
                     hover:bg-rose-500/25 transition-colors cursor-pointer"
          title={pdfSource
            ? `${t('boq.pdf_link_tooltip_v2', { defaultValue: 'PDF takeoff — click for details & navigation' })} — ${pdfSource}`
            : t('boq.pdf_link_tooltip_v2', { defaultValue: 'PDF takeoff — click for details & navigation' })}
          aria-label={t('boq.pdf_link_tooltip_v2', { defaultValue: 'PDF takeoff — click for details & navigation' })}
        >
          <FileText size={12} />
        </button>
      )}
      {hasDwgLink && (
        <button
          ref={dwgBtnRef}
          onClick={handleOpenDwg}
          onMouseDown={(e) => e.stopPropagation()}
          className="h-6 w-6 inline-flex items-center justify-center rounded
                     bg-amber-500/10 text-amber-600 dark:text-amber-400
                     hover:bg-amber-500/25 transition-colors cursor-pointer"
          title={dwgSource
            ? `${t('boq.dwg_link_tooltip_v2', { defaultValue: 'DWG drawing — click for details & navigation' })} — ${dwgSource}`
            : t('boq.dwg_link_tooltip_v2', { defaultValue: 'DWG drawing — click for details & navigation' })}
          aria-label={t('boq.dwg_link_tooltip_v2', { defaultValue: 'DWG drawing — click for details & navigation' })}
        >
          <FileBox size={12} />
        </button>
      )}

      {/* PDF source info popover */}
      {showPdfPopover && pdfAnchor &&
        createPortal(
          <>
            <div
              className="fixed inset-0 bg-black/20 backdrop-blur-[2px] z-[9998] animate-fade-in"
              onClick={() => setShowPdfPopover(false)}
            />
            <PdfDwgSourcePopover
              kind="pdf"
              anchor={pdfAnchor}
              sourceName={pdfSource || pdfDocumentId || null}
              page={pdfPage ?? null}
              measurementId={pdfMeasurementId ?? null}
              positionData={data as Record<string, unknown>}
              deepLink={pdfDeepLink}
              onClose={() => setShowPdfPopover(false)}
              onNavigate={() => {
                setShowPdfPopover(false);
                navigate(pdfDeepLink);
              }}
              onApplyQuantity={ctx?.onUpdatePosition}
            />
          </>,
          document.body,
        )}

      {/* DWG source info popover */}
      {showDwgPopover && dwgAnchor &&
        createPortal(
          <>
            <div
              className="fixed inset-0 bg-black/20 backdrop-blur-[2px] z-[9998] animate-fade-in"
              onClick={() => setShowDwgPopover(false)}
            />
            <PdfDwgSourcePopover
              kind="dwg"
              anchor={dwgAnchor}
              sourceName={dwgSource || null}
              drawingId={dwgDrawingId ?? null}
              annotationId={dwgAnnotationId ?? null}
              positionData={data as Record<string, unknown>}
              deepLink={dwgDeepLink}
              onClose={() => setShowDwgPopover(false)}
              onNavigate={() => {
                setShowDwgPopover(false);
                navigate(dwgDeepLink);
              }}
              onApplyQuantity={ctx?.onUpdatePosition}
            />
          </>,
          document.body,
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
  const popoverNavigate = useNavigate();
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
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              const params = new URLSearchParams();
              if (elementIds[0]) params.set('focus', elementIds[0]);
              if (elementIds.length > 1) params.set('select', elementIds.join(','));
              popoverNavigate(`/bim/${modelId}?${params.toString()}`);
              onClose();
            }}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold
                       text-oe-blue hover:bg-oe-blue/10 transition-colors"
            title={t('boq.open_in_bim_title', { defaultValue: 'Open in 3D viewer with the linked element pre-selected' })}
          >
            <ExternalLink size={11} />
            {t('boq.open_in_bim', { defaultValue: 'Open in BIM' })}
          </button>
          <button
            onClick={onClose}
            className="h-6 w-6 flex items-center justify-center rounded text-content-tertiary
                       hover:text-content-primary hover:bg-surface-tertiary transition-colors"
          >
            <X size={14} />
          </button>
        </div>
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

/* ── PDF / DWG source info popover ───────────────────────────────── */
/* Compact popover for non-BIM source links. Shows what the linked
 * measurement / annotation is worth (area / length / volume) and gives
 * the user a single click to jump into the source viewer with the
 * exact item pre-focused. Picks the quantity apply action when the
 * cell grid context exposes an update callback, so the same popover
 * doubles as a "set quantity from source" affordance. */
interface PdfDwgSourcePopoverProps {
  kind: 'pdf' | 'dwg';
  anchor: DOMRect;
  sourceName: string | null;
  page?: number | null;
  measurementId?: string | null;
  drawingId?: string | null;
  annotationId?: string | null;
  positionData: Record<string, unknown> | null;
  deepLink: string;
  onClose: () => void;
  onNavigate: () => void;
  onApplyQuantity?: (id: string, data: Record<string, unknown>, oldData: Record<string, unknown>) => void;
}

function PdfDwgSourcePopover(props: PdfDwgSourcePopoverProps) {
  const {
    kind,
    anchor,
    sourceName,
    page,
    measurementId,
    drawingId,
    annotationId,
    positionData,
    onClose,
    onNavigate,
    onApplyQuantity,
  } = props;
  const { t } = useTranslation();
  const popRef = useRef<HTMLDivElement>(null);

  // Pull numeric quantities out of the position metadata. Both the PDF
  // takeoff editor and the DWG annotation editor write the computed
  // measurement back to position.metadata at link time, so we don't need
  // an API round-trip here — the data is already local.
  const meta = (positionData?.metadata ?? {}) as Record<string, unknown>;
  const numericFromMeta = (keys: string[]): number | null => {
    for (const k of keys) {
      const raw = meta[k];
      const num = typeof raw === 'number' ? raw : parseFloat(String(raw));
      if (Number.isFinite(num) && num !== 0) return num;
    }
    return null;
  };
  const measurementValue =
    kind === 'pdf'
      ? numericFromMeta(['pdf_measurement_value', 'pdf_area', 'pdf_length'])
      : numericFromMeta(['dwg_measurement_value', 'dwg_area', 'dwg_length']);
  const measurementUnit = (meta[kind === 'pdf' ? 'pdf_measurement_unit' : 'dwg_measurement_unit'] as string | undefined)
    ?? (meta[kind === 'pdf' ? 'pdf_unit' : 'dwg_unit'] as string | undefined)
    ?? '';
  const measurementType = (meta[kind === 'pdf' ? 'pdf_measurement_type' : 'dwg_annotation_type'] as string | undefined) ?? null;

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (popRef.current && !popRef.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const width = 320;
  const left = Math.min(anchor.right + 8, window.innerWidth - width - 8);
  const top = Math.max(8, Math.min(anchor.top, window.innerHeight - 240));

  const canApply =
    !!positionData?.id && !!onApplyQuantity && measurementValue !== null;

  const applyQuantity = () => {
    if (!canApply || measurementValue === null) return;
    const id = positionData!.id as string;
    const oldMeta = meta;
    // Build a provenance label using the same shape the picker / takeoff
    // module use, so the quantity-cell icon and unit-cell short label both
    // appear (cellRenderers QuantityCellRenderer/UnitCellRenderer key off
    // ``pdf_measurement_source`` / ``dwg_annotation_source``).
    const label =
      kind === 'pdf'
        ? `Takeoff: ${sourceName ?? measurementType ?? 'measurement'}${page != null ? ` (page ${page})` : ''}`
        : `DWG: ${sourceName ?? measurementType ?? 'annotation'}`;
    const linkKey = kind === 'pdf' ? 'pdf_measurement_source' : 'dwg_annotation_source';
    onApplyQuantity!(
      id,
      {
        quantity: measurementValue,
        metadata: {
          ...oldMeta,
          [linkKey]: label,
        },
      },
      { ...positionData, quantity: positionData?.quantity },
    );
    onClose();
  };

  const accent = kind === 'pdf'
    ? 'from-rose-500 to-rose-600 ring-rose-500/20'
    : 'from-amber-500 to-amber-600 ring-amber-500/20';
  const accentBg = kind === 'pdf'
    ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400'
    : 'bg-amber-500/10 text-amber-600 dark:text-amber-400';

  return (
    <div
      ref={popRef}
      style={{ position: 'fixed', left, top, width, zIndex: 9999 }}
      className="rounded-xl shadow-2xl border border-border-light dark:border-border-dark
                 bg-white dark:bg-surface-elevated overflow-hidden animate-card-in"
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      role="dialog"
      aria-label={kind === 'pdf' ? 'PDF takeoff source' : 'DWG drawing source'}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3.5 py-2 border-b border-border-light dark:border-border-dark bg-surface-secondary/30">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`h-5 w-5 inline-flex items-center justify-center rounded ${accentBg}`}>
            {kind === 'pdf' ? <FileText size={12} /> : <FileBox size={12} />}
          </span>
          <span className="text-[11px] font-semibold text-content-primary uppercase tracking-wide">
            {kind === 'pdf'
              ? t('boq.source_pdf', { defaultValue: 'PDF takeoff' })
              : t('boq.source_dwg', { defaultValue: 'DWG drawing' })}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="h-5 w-5 flex items-center justify-center rounded text-content-tertiary
                     hover:text-content-primary hover:bg-surface-tertiary transition-colors"
          aria-label={t('common.close', { defaultValue: 'Close' })}
        >
          <X size={12} />
        </button>
      </div>

      {/* Body */}
      <div className="px-3.5 py-3 space-y-2.5">
        {/* Source document name */}
        <div>
          <div className="text-[9px] font-semibold uppercase tracking-wider text-content-tertiary mb-0.5">
            {t('boq.source_doc_label', { defaultValue: 'Source document' })}
          </div>
          <div className="text-[12px] font-medium text-content-primary truncate" title={sourceName || ''}>
            {sourceName || t('boq.source_doc_unknown', { defaultValue: 'Unknown document' })}
          </div>
          {kind === 'pdf' && page && (
            <div className="text-[10px] text-content-tertiary mt-0.5">
              {t('boq.source_pdf_page', { defaultValue: 'Page {{page}}', page })}
            </div>
          )}
          {kind === 'dwg' && drawingId && (
            <div className="text-[10px] text-content-tertiary font-mono mt-0.5 truncate">
              {drawingId.slice(0, 8)}…
            </div>
          )}
        </div>

        {/* Measurement value(s) */}
        <div>
          <div className="text-[9px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
            {t('boq.source_measurement_label', { defaultValue: 'Measurement' })}
          </div>
          {measurementValue !== null ? (
            <div className="flex items-baseline gap-1.5">
              <span className="text-[20px] font-semibold tabular-nums text-content-primary leading-none">
                {measurementValue.toLocaleString(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
              </span>
              {measurementUnit && (
                <span className="text-[11px] text-content-secondary font-medium">{measurementUnit}</span>
              )}
              {measurementType && (
                <span className="ml-auto text-[9px] uppercase tracking-wide text-content-tertiary bg-surface-secondary/60 px-1.5 py-0.5 rounded">
                  {measurementType}
                </span>
              )}
            </div>
          ) : (
            <div className="text-[11px] text-content-tertiary italic">
              {t('boq.source_no_measurement', { defaultValue: 'Measurement data not stored locally — open the source to view details.' })}
            </div>
          )}
        </div>

        {/* Identifier (debug-friendly but readable) */}
        {(measurementId || annotationId) && (
          <div>
            <div className="text-[9px] font-semibold uppercase tracking-wider text-content-tertiary mb-0.5">
              {t('boq.source_id_label', { defaultValue: 'Item id' })}
            </div>
            <div className="text-[10px] font-mono text-content-tertiary truncate">
              {(measurementId || annotationId || '').slice(0, 12)}…
            </div>
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="px-3.5 py-2.5 border-t border-border-light dark:border-border-dark bg-surface-secondary/20 flex items-center gap-2">
        {canApply && (
          <button
            type="button"
            onClick={applyQuantity}
            className={`flex-1 h-8 flex items-center justify-center gap-1.5 rounded-md text-[11px] font-semibold text-white bg-gradient-to-r ${accent} ring-1 shadow-sm hover:shadow-md active:scale-[0.98] transition-all`}
            title={t('boq.source_apply_qty_title', { defaultValue: 'Set this value as the BOQ position quantity' })}
          >
            <ArrowRight size={12} />
            {t('boq.source_apply_qty', { defaultValue: 'Set as quantity' })}
          </button>
        )}
        <button
          type="button"
          onClick={onNavigate}
          className={`${canApply ? 'h-8 px-3' : 'flex-1 h-8'} flex items-center justify-center gap-1.5 rounded-md text-[11px] font-semibold text-oe-blue bg-oe-blue/10 hover:bg-oe-blue/20 transition-colors`}
          title={t('boq.source_open_title', { defaultValue: 'Open the source document in its viewer, focused on this item' })}
        >
          <ExternalLink size={12} />
          {t('boq.source_open', { defaultValue: 'Open source' })}
        </button>
      </div>
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
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = useCallback(() => {
    setText(String(value));
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }, [value]);

  // Resource-row qty/rate use this input. Like the position quantity cell,
  // we want Excel-style formulas: typing "=2*PI()*3" or "12.5 x 4" commits
  // the evaluated number. isFormula gates the formula path so plain "12.5"
  // still goes through the simple parseFloat path with no behaviour change.
  const commit = useCallback(() => {
    setEditing(false);
    const trimmed = text.trim();
    let parsed: number;
    if (isFormula(trimmed)) {
      const evaluated = evaluateFormula(trimmed);
      parsed = evaluated !== null ? evaluated : NaN;
    } else {
      parsed = parseFloat(trimmed.replace(',', '.'));
    }
    if (!isNaN(parsed) && parsed !== value) {
      onCommit(parsed);
    }
  }, [text, value, onCommit]);

  // Live formula preview in edit mode — same fx feedback as the position
  // quantity editor, scaled down for the resource row's tighter footprint.
  const livePreview = useMemo(() => {
    if (!editing) return null;
    const trimmed = text.trim();
    if (!isFormula(trimmed)) return null;
    const v = evaluateFormula(trimmed);
    return v !== null ? v : NaN;
  }, [editing, text]);

  if (editing) {
    return (
      <span className="relative inline-block w-full">
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
          className={`bg-white dark:bg-surface-primary border border-oe-blue rounded px-1 py-0 text-right tabular-nums outline-none w-full ${className ?? ''}`}
          aria-label={t('boq.inline_edit_number', { defaultValue: 'Edit value' })}
          placeholder="123  or  =2*PI()*3"
          autoFocus
        />
        {livePreview !== null && (
          <span
            className={`absolute right-0 top-full mt-0.5 text-[10px] tabular-nums pointer-events-none whitespace-nowrap z-10 px-1 rounded shadow-sm bg-surface-elevated border ${
              isNaN(livePreview)
                ? 'border-rose-300 text-rose-600 dark:text-rose-400'
                : 'border-emerald-300 text-emerald-600 dark:text-emerald-400 font-semibold'
            }`}
          >
            {isNaN(livePreview) ? '⚠' : '= ' + fmt.format(livePreview)}
          </span>
        )}
      </span>
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

interface ColWidths { leftPad: number; ordinal: number; bimLink: number; classification: number; unit: number; bimQty: number; quantity: number; unitRate: number; total: number; actions: number }

/**
 * Inline unit input with datalist autocomplete. Accepts free-form values
 * and persists novel ones via `saveCustomUnit` so they appear next time.
 *
 * Behaves like `InlineTextInput` (double-click to edit) but renders a
 * `<input list="…">` so the browser shows the locale unit suggestions.
 */
function InlineUnitInput({
  value,
  onCommit,
  className,
}: {
  value: string;
  onCommit: (v: string) => void;
  className?: string;
}) {
  const { t, i18n } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Stable per-component datalist id so multiple rows don't collide.
  const listId = useMemo(() => `oe-unit-list-${Math.random().toString(36).slice(2, 10)}`, []);
  const units = useMemo(() => getUnitsForLocale(i18n.language), [i18n.language]);

  const startEdit = useCallback(() => {
    setText(value);
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }, [value]);

  const commit = useCallback(() => {
    setEditing(false);
    const trimmed = text.trim();
    if (trimmed && trimmed !== value) {
      // Persist user-typed unit so it shows up in future suggestions.
      saveCustomUnit(trimmed);
      onCommit(trimmed);
    }
  }, [text, value, onCommit]);

  if (editing) {
    return (
      <>
        <input
          ref={inputRef}
          type="text"
          list={listId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') setEditing(false);
          }}
          className={`bg-white dark:bg-surface-primary border border-oe-blue rounded px-1 py-0 outline-none ${className ?? ''}`}
          aria-label={t('boq.inline_edit_unit', { defaultValue: 'Edit unit' })}
          autoFocus
        />
        <datalist id={listId}>
          {units.map((u) => <option key={u} value={u} />)}
        </datalist>
      </>
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

/**
 * Resource type picker — fit-content badge button with portal popover.
 *
 * The native &lt;select&gt; element sizes itself to its longest option, which
 * left every resource-type badge stretched to the width of "EQUIPMENT".
 * Replacing it with a button lets the badge fit its own current label
 * (MATERIAL / LABOR / EQUIPMENT) and gives us a popover we can style.
 */
function ResourceTypePicker({
  value,
  onChange,
  t,
}: {
  value: string;
  onChange: (next: string) => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const badge = RESOURCE_TYPE_BADGE[value] ?? RESOURCE_TYPE_BADGE.other ?? { bg: 'bg-gray-100 text-gray-600', label: '?' };
  const label = getResourceTypeLabel(value, t);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (btnRef.current && btnRef.current.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const togglePicker = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (open) {
      setOpen(false);
      return;
    }
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left });
    }
    setOpen(true);
  };

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={togglePicker}
        className={`shrink-0 inline-flex items-center justify-center h-4 px-1.5 rounded
                    text-[9px] font-bold uppercase tracking-wider whitespace-nowrap
                    cursor-pointer outline-none border-0 focus:ring-1 focus:ring-oe-blue ${badge.bg}`}
        title={t('boq.resource_type', { defaultValue: 'Resource type' })}
        aria-label={t('boq.resource_type', { defaultValue: 'Resource type' })}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {label}
      </button>
      {open && pos && createPortal(
        <div
          role="listbox"
          className="fixed z-[2000] bg-surface-primary border border-border-light rounded-md
                     shadow-lg py-1 min-w-[160px] max-h-[260px] overflow-auto"
          style={{ top: pos.top, left: pos.left }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          {RESOURCE_TYPES.map((rt) => {
            const b = RESOURCE_TYPE_BADGE[rt.value] ?? RESOURCE_TYPE_BADGE.other ?? { bg: 'bg-gray-100 text-gray-600', label: '?' };
            const selected = rt.value === value;
            return (
              <button
                key={rt.value}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={(e) => {
                  e.stopPropagation();
                  onChange(rt.value);
                  setOpen(false);
                }}
                className={`flex items-center gap-2 w-full px-2 py-1.5 text-[11px] text-left
                            hover:bg-surface-secondary transition-colors
                            ${selected ? 'bg-oe-blue-subtle/30' : ''}`}
              >
                <span className={`inline-flex items-center justify-center h-4 w-4 rounded
                                  text-[9px] font-bold ${b.bg}`}>
                  {b.label}
                </span>
                <span className="text-content-primary uppercase tracking-wider font-medium">
                  {getResourceTypeLabel(rt.value, t)}
                </span>
                {selected && <span className="ml-auto text-oe-blue text-[10px]">✓</span>}
              </button>
            );
          })}
        </div>,
        document.body,
      )}
    </>
  );
}

/**
 * Resource currency combobox — picks from suggestions OR accepts a
 * custom 3-letter code. Native <input list="…"> was hiding its
 * dropdown for narrow inputs (60px) and gave no visible chevron, so
 * users couldn't tell a list existed and the saved free-text value
 * wasn't surfacing in the UI. This explicit combobox solves both:
 * a button shows the current code + chevron, clicking opens a portal
 * popover with a search-and-add input on top, the project FX group,
 * and the global ISO 4217 list.  Hitting Enter on a non-empty
 * search saves whatever the user typed as a custom currency, which
 * is then highlighted amber wherever it appears.
 */
function ResourceCurrencyCombobox({
  value,
  onCommit,
  projectGroup,
  otherGroup,
  fxRate,
  fxSource,
  baseCode,
  onCommitFxRate,
  isForeign,
  t,
}: {
  value: string;
  onCommit: (next: string) => void;
  projectGroup: string[];
  otherGroup: string[];
  /** Foreign→base rate (1 unit of `value` in `baseCode`). */
  fxRate?: number | undefined;
  fxSource?: 'project' | 'global' | 'none';
  baseCode?: string;
  onCommitFxRate?: (rate: number) => void;
  /** True iff `value !== baseCode`. */
  isForeign?: boolean;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [search, setSearch] = useState('');
  const btnRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const projectSet = useMemo(() => new Set(projectGroup), [projectGroup]);
  const otherSet = useMemo(() => new Set(otherGroup), [otherGroup]);
  const isUserDefined = value.length > 0 && !projectSet.has(value) && !otherSet.has(value);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (btnRef.current?.contains(e.target as Node)) return;
      // Allow clicks inside the popover (handled via stopPropagation in popover root)
      const popover = document.getElementById('oe-currency-popover');
      if (popover?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const togglePopover = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (open) { setOpen(false); return; }
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left });
    }
    setSearch('');
    setOpen(true);
    // Focus the search input on next tick once the popover is mounted.
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const commit = (raw: string) => {
    const next = raw.trim().toUpperCase().slice(0, 6);
    if (next === '' || next === value) { setOpen(false); return; }
    onCommit(next);
    setOpen(false);
  };

  // Filter both groups by the search prefix (case-insensitive); when the
  // search yields no exact match, show an "Add custom" affordance so the
  // user knows a free-text submission is supported.
  const q = search.trim().toUpperCase();
  const matchProject = projectGroup.filter((c) => !q || c.includes(q));
  const matchOther = otherGroup.filter((c) => !q || c.includes(q));
  const exactMatch = q.length > 0 && (matchProject.includes(q) || matchOther.includes(q));
  const canAddCustom = q.length >= 2 && !exactMatch;

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={togglePopover}
        className={`shrink-0 h-4 px-1 rounded text-[9px] font-mono uppercase tracking-wide
                    text-center cursor-pointer outline-none focus:ring-1 focus:ring-oe-blue
                    inline-flex items-center justify-center gap-0.5
                    ${isUserDefined
                      ? 'bg-amber-50 dark:bg-amber-900/20 border border-amber-400 text-amber-800 dark:text-amber-200 font-bold'
                      : 'bg-surface-primary border border-border-light text-content-secondary'}`}
        style={{ minWidth: '36px' }}
        title={isUserDefined
          ? t('boq.resource_currency_custom', {
              defaultValue: 'Custom currency: {{code}} (not in project FX or ISO 4217 list)',
              code: value,
            })
          : t('boq.resource_currency_pick', {
              defaultValue: 'Currency — {{symbol}} {{code}}',
              symbol: CURRENCY_SYMBOL[value] ?? '',
              code: value,
            })}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('boq.resource_currency', { defaultValue: 'Currency' })}
      >
        <span className="truncate">{value}</span>
        <ChevronDown size={8} className="opacity-60" />
      </button>
      {open && pos && createPortal(
        <div
          id="oe-currency-popover"
          role="listbox"
          className="fixed z-[2000] bg-surface-primary border border-border-light rounded-md
                     shadow-lg w-[220px] max-h-[320px] flex flex-col"
          style={{ top: pos.top, left: pos.left }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="p-2 border-b border-border-light">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value.toUpperCase().slice(0, 6))}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  if (canAddCustom) commit(q);
                  else if (matchProject[0] || matchOther[0]) commit(matchProject[0] ?? matchOther[0]!);
                }
              }}
              placeholder={t('boq.resource_currency_search', { defaultValue: 'Type or search (e.g. EUR, MYC)' })}
              className="w-full h-7 px-2 text-[11px] font-mono uppercase tracking-wide
                         text-center bg-surface-secondary border border-border-light rounded
                         outline-none focus:ring-1 focus:ring-oe-blue"
              autoComplete="off"
              spellCheck={false}
            />
            {canAddCustom && (
              <button
                type="button"
                onClick={() => commit(q)}
                className="mt-1.5 w-full h-6 rounded text-[10px] font-bold uppercase tracking-wide
                           bg-amber-100 hover:bg-amber-200 dark:bg-amber-900/30 dark:hover:bg-amber-900/50
                           text-amber-800 dark:text-amber-200 border border-amber-400
                           flex items-center justify-center gap-1"
              >
                <Plus size={10} />
                <span>{t('boq.resource_currency_add_custom', { defaultValue: 'Add custom: {{code}}', code: q })}</span>
              </button>
            )}
            {/* FX rate editor — visible when the row's currency differs
                from the project base. Lets the estimator confirm or
                tweak the rate without leaving the picker. Project-
                scoped FX rates (set by the BOQ owner) are read-only
                here; the global localStorage rate is editable. */}
            {isForeign && baseCode && onCommitFxRate && (
              <div className="mt-2 pt-2 border-t border-border-light/60">
                <div className="text-[9px] uppercase tracking-wider text-content-tertiary mb-1">
                  {t('boq.fx_rate_label', { defaultValue: 'FX rate' })}
                  {fxSource === 'project' && (
                    <span className="ml-1 px-1 rounded bg-oe-blue-subtle text-oe-blue text-[8px] font-bold">
                      {t('boq.fx_rate_project_badge', { defaultValue: 'PROJECT' })}
                    </span>
                  )}
                  {fxSource === 'global' && (
                    <span className="ml-1 px-1 rounded bg-surface-secondary text-content-tertiary text-[8px] font-bold">
                      {t('boq.fx_rate_global_badge', { defaultValue: 'GLOBAL' })}
                    </span>
                  )}
                </div>
                <PopoverFxRateRow
                  foreignCode={value}
                  baseCode={baseCode}
                  rate={fxRate}
                  readOnly={fxSource === 'project'}
                  onCommit={onCommitFxRate}
                  t={t}
                />
              </div>
            )}
          </div>
          <div className="overflow-auto flex-1 py-1">
            {matchProject.length > 0 && (
              <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-content-tertiary">
                {t('boq.currency_group_project', { defaultValue: 'Project' })}
              </div>
            )}
            {matchProject.map((code) => (
              <CurrencyOption
                key={`p-${code}`}
                code={code}
                selected={code === value}
                custom={false}
                onPick={() => commit(code)}
              />
            ))}
            {matchOther.length > 0 && (
              <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-content-tertiary border-t border-border-light/60">
                {t('boq.currency_group_world', { defaultValue: 'World currencies' })}
              </div>
            )}
            {matchOther.map((code) => (
              <CurrencyOption
                key={`w-${code}`}
                code={code}
                selected={code === value}
                custom={false}
                onPick={() => commit(code)}
              />
            ))}
            {/* Surface the currently saved custom value at the bottom so
                the user can confirm it's persisted. */}
            {isUserDefined && (!q || value.includes(q)) && (
              <>
                <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-300 border-t border-border-light/60">
                  {t('boq.currency_group_custom', { defaultValue: 'Custom (saved)' })}
                </div>
                <CurrencyOption
                  code={value}
                  selected
                  custom
                  onPick={() => setOpen(false)}
                />
              </>
            )}
            {matchProject.length === 0 && matchOther.length === 0 && !canAddCustom && (
              <div className="px-2 py-3 text-[10px] text-center text-content-quaternary">
                {t('boq.resource_currency_no_match', { defaultValue: 'No matches — type at least 2 letters to add a custom code.' })}
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}

/**
 * FX rate row inside the currency popover. Shows "1 ¤foreign = X ¤base"
 * with X editable in place. Replaces the previous inline FX widget
 * which used to live on the row itself; moving it into the popover
 * frees horizontal space and keeps unit/qty/rate column boundaries
 * aligned with the parent position row.
 */
function PopoverFxRateRow({
  foreignCode,
  baseCode,
  rate,
  readOnly,
  onCommit,
  t,
}: {
  foreignCode: string;
  baseCode: string;
  rate: number | undefined;
  readOnly: boolean;
  onCommit: (next: number) => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [draft, setDraft] = useState(rate != null ? String(Number(rate.toFixed(6))) : '');
  useEffect(() => {
    setDraft(rate != null ? String(Number(rate.toFixed(6))) : '');
  }, [rate]);

  const commit = () => {
    const n = parseFloat(draft.replace(',', '.'));
    if (Number.isFinite(n) && n > 0 && rate !== n) onCommit(n);
    else setDraft(rate != null ? String(Number(rate.toFixed(6))) : '');
  };

  return (
    <div className="flex items-center gap-1 text-[10px] font-mono">
      <span className="text-content-secondary">1 {foreignCode} =</span>
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key === 'Escape') {
            setDraft(rate != null ? String(Number(rate.toFixed(6))) : '');
            (e.target as HTMLInputElement).blur();
          }
        }}
        readOnly={readOnly}
        placeholder="—"
        spellCheck={false}
        autoComplete="off"
        className={`flex-1 min-w-0 h-5 px-1 rounded text-center tabular-nums
                    outline-none focus:ring-1 focus:ring-oe-blue
                    ${readOnly
                      ? 'bg-surface-secondary/40 border border-border-light/60 text-content-tertiary cursor-not-allowed'
                      : rate == null
                      ? 'bg-amber-50 dark:bg-amber-900/20 border border-amber-400 text-amber-800 dark:text-amber-200 cursor-text'
                      : 'bg-surface-primary border border-border-light text-content-primary cursor-text'}`}
        aria-label={t('boq.fx_rate_input', { defaultValue: 'FX rate {{from}}→{{to}}', from: foreignCode, to: baseCode })}
      />
      <span className="text-content-secondary">{baseCode}</span>
    </div>
  );
}

function CurrencyOption({
  code,
  selected,
  custom,
  onPick,
}: {
  code: string;
  selected: boolean;
  custom: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={(e) => { e.stopPropagation(); onPick(); }}
      className={`flex items-center gap-2 w-full px-2 py-1.5 text-[11px] text-left
                  hover:bg-surface-secondary transition-colors
                  ${selected ? (custom ? 'bg-amber-100/40 dark:bg-amber-900/20' : 'bg-oe-blue-subtle/30') : ''}`}
    >
      <span className={`inline-flex items-center justify-center w-7 text-[10px] font-mono ${custom ? 'text-amber-700 dark:text-amber-300 font-bold' : 'text-content-secondary'}`}>
        {CURRENCY_SYMBOL[code] ?? '·'}
      </span>
      <span className={`font-mono uppercase tracking-wide ${custom ? 'text-amber-800 dark:text-amber-200 font-bold' : 'text-content-primary'}`}>
        {code}
      </span>
      {selected && <span className="ml-auto text-[10px] text-oe-blue">✓</span>}
    </button>
  );
}

export function EditableResourceRow({ data, ctx, colWidths }: { data: Record<string, unknown>; ctx: FullGridContext; colWidths: ColWidths }) {
  const resourceType = (data._resourceType as string) || 'other';
  const qty = (data._resourceQty as number) ?? 0;
  const rate = (data._resourceRate as number) ?? 0;
  const total = qty * rate;
  const baseCurrency = ctx.currencyCode ?? 'EUR';
  const resourceCurrency = (data._resourceCurrency as string | undefined) || baseCurrency;
  const isForeign = resourceCurrency !== baseCurrency;

  /* ── Variant re-pick state (v2.6.26+) ────────────────────────────────
   *  available_variants is cached on the resource at apply-time. When
   *  present (>= 2 variants) we surface a "▾ N options" pill in the
   *  unit_rate cell that opens the existing CWICR VariantPicker. The
   *  4px left-edge bar marks provenance: blue for an explicit pick,
   *  amber for an auto-default-from-mean, none when the resource has
   *  no variant link. */
  const availableVariants = (data._resourceAvailableVariants as CostVariant[] | undefined);
  const availableVariantStats = (data._resourceAvailableVariantStats as VariantStats | undefined);
  const resourceVariant = data._resourceVariant as
    | { label: string; price: number; index: number }
    | undefined;
  const resourceVariantDefault = data._resourceVariantDefault as 'mean' | 'median' | undefined;
  const resourceVariantSnapshot = data._resourceVariantSnapshot as
    | { label?: string; rate?: number; currency?: string; captured_at?: string; source?: string }
    | undefined;
  const hasVariants =
    Array.isArray(availableVariants) &&
    availableVariants.length >= 2 &&
    availableVariantStats != null;
  const canRepick = hasVariants && typeof ctx.onRepickResourceVariant === 'function';

  // Provenance bar colour:
  //   blue   → explicit user pick (resource.variant set)
  //   amber  → auto-default (variant_default set)
  //   violet → variant resource w/ no pick yet (visual flag for the row)
  //   none   → plain row, no variant link
  let variantBarTone: 'blue' | 'amber' | 'violet' | null = null;
  if (resourceVariant) variantBarTone = 'blue';
  else if (resourceVariantDefault) variantBarTone = 'amber';
  else if (hasVariants) variantBarTone = 'violet';

  const [variantPickerOpen, setVariantPickerOpen] = useState(false);
  const variantPillRef = useRef<HTMLButtonElement>(null);
  const closeVariantPicker = useCallback(() => setVariantPickerOpen(false), []);

  /* ── Auto-open hook ────────────────────────────────────────────────
   *  When the user clicks the position-description "V" icon, the parent
   *  grid stashes a one-shot signal naming this exact (positionId, resIdx)
   *  pair. We pop our picker open in response, then ask the parent to
   *  clear the signal so a re-render with stale state doesn't re-open
   *  the picker after the user has dismissed it.
   *
   *  Skipped when the row carries no variants — defensive, the parent
   *  shouldn't fire the signal for non-variant rows in the first place.
   */
  const openVariantSignal = ctx.openVariantPickerFor;
  const clearOpenVariant = ctx.onClearOpenVariantPicker;
  useEffect(() => {
    if (!openVariantSignal || !hasVariants) return;
    const myPosId = data._parentPositionId as string;
    const myResIdx = data._resourceIndex as number;
    if (
      openVariantSignal.positionId === myPosId &&
      openVariantSignal.resourceIdx === myResIdx
    ) {
      setVariantPickerOpen(true);
      clearOpenVariant?.();
    }
  }, [openVariantSignal, clearOpenVariant, hasVariants, data]);

  const handleRepick = useCallback(
    (chosen: CostVariant) => {
      setVariantPickerOpen(false);
      const posIdLocal = data._parentPositionId as string;
      const resIdxLocal = data._resourceIndex as number;
      ctx.onRepickResourceVariant?.(posIdLocal, resIdxLocal, chosen.label);
    },
    [ctx, data],
  );

  const handleRepickUseDefault = useCallback(
    (strategy: 'mean' | 'median') => {
      // The re-pick endpoint expects an explicit variant label; map the
      // mean/median strategy to the closest variant in the cache. Mirrors
      // the position-level pill's "Use average" CTA without forcing a
      // separate backend code path.
      if (!availableVariants || availableVariants.length === 0 || !availableVariantStats) {
        setVariantPickerOpen(false);
        return;
      }
      const target = strategy === 'mean' ? availableVariantStats.mean : availableVariantStats.median;
      let bestIdx = 0;
      let bestDelta = Number.POSITIVE_INFINITY;
      for (let i = 0; i < availableVariants.length; i++) {
        const v = availableVariants[i];
        if (!v) continue;
        const d = Math.abs(v.price - target);
        if (d < bestDelta) {
          bestDelta = d;
          bestIdx = i;
        }
      }
      const chosen = availableVariants[bestIdx];
      if (chosen) {
        const posIdLocal = data._parentPositionId as string;
        const resIdxLocal = data._resourceIndex as number;
        ctx.onRepickResourceVariant?.(posIdLocal, resIdxLocal, chosen.label);
      }
      setVariantPickerOpen(false);
    },
    [availableVariants, availableVariantStats, ctx, data],
  );

  // Pill tooltip — surface variant code + price + delta-vs-mean chip.
  const variantPillTooltip = (() => {
    if (!hasVariants) return '';
    const meanRate = availableVariantStats!.mean;
    const minRate = availableVariantStats!.min;
    const maxRate = availableVariantStats!.max;
    const range = `${minRate.toFixed(2)} – ${maxRate.toFixed(2)} ${resourceCurrency}`;
    if (resourceVariant) {
      const delta =
        meanRate > 0
          ? Math.round(((resourceVariant.price - meanRate) / meanRate) * 100)
          : null;
      const deltaStr =
        delta == null ? '' : ` (${delta > 0 ? '+' : ''}${delta}% vs avg)`;
      return ctx.t('boq.resource_variant_pill_tooltip_picked', {
        defaultValue:
          'Variant: {{label}} @ {{price}} {{currency}}{{delta}}. Click to switch.',
        label: resourceVariant.label,
        price: resourceVariant.price.toFixed(2),
        currency: resourceCurrency,
        delta: deltaStr,
      });
    }
    if (resourceVariantDefault) {
      return ctx.t('boq.resource_variant_pill_tooltip_default', {
        defaultValue:
          'Auto-applied with {{strategy}} rate. {{count}} options ({{range}}). Click to refine.',
        strategy: resourceVariantDefault === 'mean' ? 'average' : 'median',
        count: availableVariantStats!.count,
        range,
      });
    }
    return ctx.t('boq.resource_variant_pill_tooltip_unset', {
      defaultValue:
        '{{count}} priced variants available ({{range}}). Click to pick one.',
      count: availableVariantStats!.count,
      range,
    });
  })();

  const variantBarTooltip = (() => {
    if (variantBarTone === null) return '';
    const captured = resourceVariantSnapshot?.captured_at;
    if (variantBarTone === 'blue' && resourceVariant) {
      return ctx.t('boq.resource_variant_bar_tooltip_picked', {
        defaultValue: 'Explicit variant: {{label}}{{captured}}',
        label: resourceVariant.label,
        captured: captured ? ` · captured ${captured.split('T')[0]}` : '',
      });
    }
    if (variantBarTone === 'amber' && resourceVariantDefault) {
      return ctx.t('boq.resource_variant_bar_tooltip_default', {
        defaultValue:
          'Auto-default ({{strategy}}){{captured}} — click pill to refine.',
        strategy: resourceVariantDefault,
        captured: captured ? ` · captured ${captured.split('T')[0]}` : '',
      });
    }
    return '';
  })();
  const fxRates = ctx.fxRates ?? [];
  const fxEntry = isForeign ? fxRates.find((r) => r.currency === resourceCurrency) : undefined;
  // Project-scoped FX rates (set by the BOQ owner) take priority. When
  // missing, fall back to the global localStorage-persisted store so an
  // estimator can pick e.g. JPY without the BOQ owner having pre-loaded
  // a rate. Inline editing of the rate writes to the global store.
  const ratesVsUsd = useFxRatesStore((s) => s.ratesVsUsd);
  const setGlobalRate = useFxRatesStore((s) => s.setRate);
  const globalRate = isForeign ? getFxRate(resourceCurrency, baseCurrency, ratesVsUsd) : undefined;
  const fxRate: number | undefined = fxEntry?.rate ?? globalRate;
  const fxSource: 'project' | 'global' | 'none' = fxEntry?.rate
    ? 'project'
    : (globalRate != null ? 'global' : 'none');
  const hasFxRate = !isForeign || (typeof fxRate === 'number' && fxRate > 0);
  const totalInBase = isForeign && hasFxRate ? total * (fxRate ?? 1) : total;

  // When the user edits the global rate inline, we store "1 unit of <foreign> = X <USD>".
  // Math: rate(foreign→base) = rateVsUsd(foreign) / rateVsUsd(base)
  //   ⇒ rateVsUsd(foreign) = rate(foreign→base) * rateVsUsd(base)
  const handleGlobalFxRateChange = useCallback(
    (newRateForeignToBase: number) => {
      if (!Number.isFinite(newRateForeignToBase) || newRateForeignToBase <= 0) return;
      const baseVsUsd = ratesVsUsd[baseCurrency] ?? 1;
      setGlobalRate(resourceCurrency, newRateForeignToBase * baseVsUsd);
    },
    [resourceCurrency, baseCurrency, ratesVsUsd, setGlobalRate],
  );

  const formattedTotal = fmtWithCurrency(total, ctx.locale ?? 'de-DE', resourceCurrency);
  const formattedTotalInBase = isForeign && hasFxRate
    ? fmtWithCurrency(totalInBase, ctx.locale ?? 'de-DE', baseCurrency)
    : null;

  const posId = data._parentPositionId as string;
  const resIdx = data._resourceIndex as number;
  const storedName = (data._resourceName as string) || '';
  // For variant resources, the display name MUST surface the abstract
  // base (``price_abstract_resource_common_start``). Legacy applies
  // stored only the variable_part / "description (label)" form, so we
  // recompose at display time when the cached stats carry common_start
  // and the stored name doesn't already start with it. Plain rows pass
  // straight through.
  const variantCommonStart =
    (availableVariantStats as { common_start?: string } | undefined)?.common_start?.trim() ?? '';
  const variantLabelForName = resourceVariant?.label?.trim() ?? '';
  // Variant resource name = ``price_abstract_resource_common_start``
  // (the abstract base) + the picked ``price_abstract_resource_variable_parts``
  // token. When no variant picked yet, show just the base. Plain
  // (non-variant) rows fall through to the stored name.
  const labelStartsWithCommon =
    variantLabelForName.length > 0 &&
    variantCommonStart.length > 0 &&
    variantLabelForName.toLowerCase().startsWith(variantCommonStart.toLowerCase());
  let composedVariantName = '';
  if (variantCommonStart && variantLabelForName && !labelStartsWithCommon) {
    composedVariantName = `${variantCommonStart} ${variantLabelForName}`.trim();
  } else if (variantLabelForName) {
    composedVariantName = variantLabelForName;
  } else if (variantCommonStart) {
    composedVariantName = variantCommonStart;
  }
  const originalName = composedVariantName || storedName;
  const resourceCode = (data._resourceCode as string | undefined) || '';

  const handleQtyChange = useCallback(
    (v: number) => ctx.onUpdateResource?.(posId, resIdx, 'quantity', v),
    [ctx, posId, resIdx],
  );
  const handleRateChange = useCallback(
    (v: number) => ctx.onUpdateResource?.(posId, resIdx, 'unit_rate', v),
    [ctx, posId, resIdx],
  );

  // When the user edits the resource name, treat it as a customisation:
  // the linked catalogue code no longer represents this row, so clear it.
  // The "Save to my catalog" button (BookmarkPlus) then lets the user
  // persist the customised resource as a brand-new entry in their own
  // catalogue without overwriting the public CWICR row.
  const handleNameChange = useCallback(
    (v: string) => {
      const next = v.trim();
      // Compare against BOTH the stored name and the composed display
      // name — committing the prefilled "common_start · label" without
      // changes shouldn't trigger a rename.
      if (next === storedName.trim() || next === originalName.trim()) return;
      // Renaming a catalogued resource clears its code (the row is now a
      // user customisation). Both fields must land in ONE mutation —
      // sending two `onUpdateResource` calls would race on the React Query
      // cache: the second read sees the pre-name-change resources array
      // and overwrites the name we just sent. Symptom reported by user:
      // "the name resets to the old value, only the second click sticks."
      if (ctx.onUpdateResourceFields) {
        ctx.onUpdateResourceFields(
          posId,
          resIdx,
          resourceCode ? { name: v, code: '' } : { name: v },
        );
      } else {
        // Backward-compat path for grid contexts that haven't wired the
        // batched update yet — preserves the old (racy) behaviour rather
        // than crashing.
        ctx.onUpdateResource?.(posId, resIdx, 'name', v);
        if (resourceCode) ctx.onUpdateResource?.(posId, resIdx, 'code', '');
      }
    },
    [ctx, posId, resIdx, storedName, originalName, resourceCode],
  );

  const handleTypeChange = useCallback(
    (v: string) => ctx.onUpdateResource?.(posId, resIdx, 'type', v),
    [ctx, posId, resIdx],
  );

  const handleCurrencyChange = useCallback(
    (v: string) => {
      // Empty string is the explicit "use project base" sentinel — record
      // an empty string so the backend can clear the override.
      const value = v === baseCurrency ? '' : v;
      ctx.onUpdateResource?.(posId, resIdx, 'currency', value);
    },
    [ctx, posId, resIdx, baseCurrency],
  );

  // Currency dropdown — three groups, deduped:
  //   1. Project base + every fx_rates entry the BOQ owner already configured.
  //   2. The resource's current currency if it's outside both above
  //      (so the picker can faithfully render whatever was already saved).
  //   3. COMMON_CURRENCIES — global fallback so an international estimator
  //      can pick e.g. JPY for an imported component even when the project
  //      hasn't pre-loaded an FX rate. The "no FX" warning badge on the
  //      total cell flags missing-rate cases.
  const { projectGroup, otherGroup } = useMemo(() => {
    const seen = new Set<string>();
    const project: string[] = [];
    const other: string[] = [];
    if (baseCurrency) {
      project.push(baseCurrency);
      seen.add(baseCurrency);
    }
    for (const fx of fxRates) {
      if (fx.currency && !seen.has(fx.currency)) {
        project.push(fx.currency);
        seen.add(fx.currency);
      }
    }
    if (resourceCurrency && !seen.has(resourceCurrency)) {
      project.push(resourceCurrency);
      seen.add(resourceCurrency);
    }
    for (const code of COMMON_CURRENCIES) {
      if (!seen.has(code)) {
        other.push(code);
        seen.add(code);
      }
    }
    return { projectGroup: project, otherGroup: other };
  }, [baseCurrency, fxRates, resourceCurrency]);

  const totalTitle = (() => {
    if (!isForeign) return formattedTotal;
    if (hasFxRate && formattedTotalInBase) {
      return ctx.t('boq.resource_total_in_base', {
        defaultValue: '{{foreign}} ≈ {{base}} (1 {{code}} = {{rate}} {{baseCode}})',
        foreign: formattedTotal,
        base: formattedTotalInBase,
        code: resourceCurrency,
        rate: String(fxRate ?? ''),
        baseCode: baseCurrency,
      });
    }
    return ctx.t('boq.resource_no_fx_rate', {
      defaultValue: 'No FX rate configured for {{code}} — total shown in {{code}}',
      code: resourceCurrency,
    });
  })();

  return (
    <div
      className={`relative flex items-stretch w-full h-full select-none group/res text-xs border-b border-border-light/50 ${
        hasVariants
          ? 'bg-violet-50/60 dark:bg-violet-950/25'
          : 'bg-surface-secondary/40'
      }`}
      style={{ paddingLeft: `${colWidths.leftPad}px`, paddingRight: '4px' }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        ctx.onShowContextMenu?.(e, 'resource', data);
      }}
      data-resource-variant={hasVariants ? '1' : undefined}
    >
      {/* Provenance left-edge bar — 4px wide, full row height. Marks variant
          source so a quick scan reveals which resources were explicitly
          picked vs auto-defaulted vs unset-but-variant. Hidden when the
          resource has no variant link at all (legacy plain rows). */}
      {variantBarTone && (
        <span
          aria-hidden="true"
          title={variantBarTooltip}
          data-testid={`resource-variant-bar-${data._resourceIndex}-${variantBarTone}`}
          className={`absolute left-0 top-0 bottom-0 w-1 ${
            variantBarTone === 'blue'
              ? 'bg-oe-blue/70'
              : variantBarTone === 'amber'
              ? 'bg-amber-400 dark:bg-amber-500'
              : 'bg-gradient-to-b from-violet-500 to-purple-600'
          }`}
        />
      )}

      {/* LEFT section — three slots that MIRROR the AG Grid columns
          (ordinal, _bim_link, description) 1:1, so resource code lines
          up under position ordinal, resource tag lines up under the
          BIM-link column, and resource name starts where the position
          description starts. Widths are read from the live grid via
          colWidths, padding mirrors AG Grid's --ag-cell-horizontal-padding
          equivalent (pr-2 / pl-1 = same as the column cellClass
          overrides) so right edges and left edges line up exactly. */}

      {/* Code — width = ordinal column. Right-aligned with pr-2 to match
          the position ordinal cell's `text-right !pr-2`, so the code's
          right edge sits on the same X as the ordinal's right edge. */}
      <span
        className="shrink-0 inline-flex items-center justify-end self-center pr-2 text-[8px] font-mono whitespace-nowrap overflow-hidden"
        style={{ width: `${colWidths.ordinal}px` }}
        title={resourceCode
          ? ctx.t('boq.resource_catalog_code', { defaultValue: 'Catalogue code: {{code}}', code: resourceCode })
          : ctx.t('boq.resource_customised', { defaultValue: 'Customised resource — no catalogue code' })}
      >
        {resourceCode ? (
          <span className="px-1 py-0.5 rounded bg-surface-secondary/60 text-content-quaternary">
            {resourceCode}
          </span>
        ) : (
          <span className="text-content-quaternary/50">—</span>
        )}
      </span>

      {/* Tag — width = _bim_link column. Right-aligned so tag right
          edges line up across all rows. ``pr-3`` keeps a 12px gap from
          the start of the name slot; ``pl-2`` provides minimal padding
          from the code chip when the bim_link column is at its
          narrowest. The chip is right-anchored within this slot so the
          left edge of the name slot can start at the SAME X as the
          position description's left edge (visual spine). */}
      <span
        className="shrink-0 inline-flex items-center justify-end self-center pl-2 pr-3"
        style={{ width: `${colWidths.bimLink}px` }}
      >
        <ResourceTypePicker
          value={resourceType}
          onChange={handleTypeChange}
          t={ctx.t}
        />
      </span>

      {/* Name — flex-1, mirrors the position description column.
          ``pl-1`` (4px) matches the position description column's
          ``!pl-1`` cellClass so the resource name's left edge lands on
          the EXACT same X as the position description text — the
          vertical spine the user requested. Visual gap from the type
          chip is preserved by the chip slot's ``pr-3`` (12px). */}
      <span className="truncate min-w-0 flex-1 self-center text-left text-content-secondary font-medium inline-flex items-center gap-1 pl-1">
        {hasVariants && (
          <span
            aria-hidden="true"
            title={ctx.t('boq.resource_is_variant_badge', {
              defaultValue: 'Variant resource — multiple price options available',
            })}
            className="shrink-0 relative inline-flex h-[18px] w-[18px] items-center justify-center
                       rounded-full overflow-hidden
                       bg-gradient-to-br from-violet-500 via-purple-500 to-fuchsia-600
                       text-white text-[9px] font-extrabold leading-none tracking-wider
                       ring-1 ring-white/30
                       shadow-[0_1px_3px_rgba(139,92,246,0.5),0_0_0_1px_rgba(139,92,246,0.2)]"
            data-testid={`resource-variant-badge-${data._resourceIndex}`}
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-1/2 rounded-t-full
                         bg-gradient-to-b from-white/35 to-transparent"
            />
            <span className="relative z-10 drop-shadow-[0_1px_1px_rgba(0,0,0,0.25)]">V</span>
          </span>
        )}
        <InlineTextInput value={originalName} onCommit={handleNameChange} className="flex-1 min-w-0 text-xs text-left" />
      </span>

      {/* Classification spacer — hidden by default (width 0) but reserved so
          that toggling it on doesn't break alignment. */}
      {colWidths.classification > 0 && (
        <span className="shrink-0 self-center" style={{ width: `${colWidths.classification}px` }} aria-hidden="true" />
      )}

      {/* RIGHT section — unit / [bim_qty spacer] / qty / rate / total / actions
          are direct siblings of the outer flex container with NO inter-slot
          gap, so their X coordinates exactly match the position row's AG
          Grid columns. Per UX request: unit on every resource row must
          sit on the same vertical X as unit on every position row. */}
      <span className="shrink-0 text-center text-content-tertiary self-center px-2" style={{ width: `${colWidths.unit}px` }}>
        <InlineUnitInput
          value={data._resourceUnit as string}
          onCommit={(v: string) => ctx.onUpdateResource?.(posId, resIdx, 'unit', v)}
          className="w-full text-xs text-center"
        />
      </span>

      {/* _bim_qty spacer — the position grid has a 28px BIM-quantity-picker
          column between unit and quantity. The resource row has no
          equivalent feature (a resource has no BIM link), so we render an
          empty placeholder of the exact same width. Without this spacer
          every resource numeric value (qty / rate / total / actions) sits
          28px LEFT of the position row. */}
      {colWidths.bimQty > 0 && (
        <span className="shrink-0 self-center" style={{ width: `${colWidths.bimQty}px` }} aria-hidden="true" />
      )}

      {/* Qty — slot pr-1/pl-1 (4px) + InlineNumberInput's display-span
          px-1 (4px) sums to 8px, matching the position quantity cell's
          `!pr-2 !pl-2`. Without this compensation the resource qty
          number sits 4px LEFT of the position qty number. */}
      <span className="shrink-0 text-right tabular-nums text-content-secondary self-center pr-1 pl-1" style={{ width: `${colWidths.quantity}px` }}>
        <InlineNumberInput value={qty} onCommit={handleQtyChange} fmt={ctx.fmt} className="w-full text-xs" />
      </span>

      {/* Unit rate slot — wraps the rate number AND the currency button
          together so the currency is visually attached to the price
          (it labels the price, not the unit). Currency button hosts
          the FX-rate editor in its popover when the row uses a foreign
          currency, so we don't need an extra inline FX widget. pr-2/pl-2
          mirror the position cell padding so the rate text right edge
          (before the currency chip) aligns with the position rate. */}
      <span
        className="shrink-0 inline-flex items-center justify-end self-center gap-1 pr-2 pl-2"
        style={{ width: `${colWidths.unitRate}px` }}
      >
        {canRepick && (
          <button
            ref={variantPillRef}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setVariantPickerOpen((open) => !open);
            }}
            onMouseDown={(e) => e.stopPropagation()}
            className={`shrink-0 inline-flex items-center gap-0.5 h-4 px-1 rounded text-[9px] font-semibold
                        transition-colors cursor-pointer ${
                          resourceVariant
                            ? 'bg-oe-blue/15 text-oe-blue hover:bg-oe-blue/25'
                            : resourceVariantDefault
                            ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/60'
                            : 'bg-surface-tertiary/60 text-content-secondary hover:bg-surface-tertiary'
                        }`}
            title={variantPillTooltip}
            aria-label={variantPillTooltip}
            aria-haspopup="dialog"
            aria-expanded={variantPickerOpen}
            data-testid={`resource-variant-pill-${data._resourceIndex}`}
          >
            {ctx.t('boq.resource_variant_pill', {
              defaultValue: '\u25BE {{count}}',
              count: availableVariantStats!.count,
            })}
          </button>
        )}
        <InlineNumberInput
          value={rate}
          onCommit={handleRateChange}
          fmt={ctx.fmt}
          className="flex-1 min-w-0 text-right tabular-nums text-content-secondary text-xs"
        />
        <ResourceCurrencyCombobox
          value={resourceCurrency}
          onCommit={handleCurrencyChange}
          projectGroup={projectGroup}
          otherGroup={otherGroup}
          fxRate={fxRate}
          fxSource={fxSource}
          baseCode={baseCurrency}
          onCommitFxRate={handleGlobalFxRateChange}
          isForeign={isForeign}
          t={ctx.t}
        />
        {variantPickerOpen && hasVariants && (
          <VariantPicker
            variants={availableVariants!}
            stats={availableVariantStats!}
            defaultStrategy="mean"
            defaultIndex={resourceVariant?.index}
            anchorEl={variantPillRef.current}
            unitLabel={(data._resourceUnit as string) || ''}
            currency={resourceCurrency}
            onApply={handleRepick}
            onUseDefault={handleRepickUseDefault}
            onClose={closeVariantPicker}
          />
        )}
      </span>

      <span
        className="shrink-0 text-right tabular-nums font-medium text-content-primary flex items-center justify-end gap-1 self-center pr-2 pl-2"
        style={{ width: `${colWidths.total}px` }}
        title={totalTitle}
      >
        {isForeign && !hasFxRate && (
          <span
            className="inline-flex items-center justify-center h-3 px-1 rounded
                       text-[8px] font-bold uppercase
                       bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
            title={ctx.t('boq.resource_no_fx_rate', {
              defaultValue: 'No FX rate configured for {{code}} — total shown in {{code}}',
              code: resourceCurrency,
            })}
          >
            ⚠ no FX
          </span>
        )}
        <span>{formattedTotal}</span>
      </span>

      {/* Actions — aligned to grid Actions column */}
      <span className="shrink-0 flex items-center justify-center gap-0.5 self-center" style={{ width: `${colWidths.actions}px` }}>
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

/* ── Variant Header Row ─────────────────────────────────────────────
 *  Synthetic row prepended above a position's component-resources when
 *  the position carries position-level CWICR variants
 *  (``metadata.cost_item_variants``). Renders with the EXACT same column
 *  geometry as ``EditableResourceRow`` so the abstract variant lines up
 *  cleanly with the regular components beneath it: same code / type /
 *  name / unit / qty / rate / total slots. The row is read-only and the
 *  only mutation surface is the "▾ N options" pill in the unit-rate
 *  cell — clicking it reopens the position-level VariantPicker, which on
 *  apply patches ``position.unit_rate`` and ``metadata.variant``.
 *
 *  Quantity = position quantity (the abstract resource inherits the
 *  position's volume — e.g. 1 t of steel — so qty × rate gives the
 *  same total as the position's unit_rate). Only the rate flips with
 *  variant choice. */
function VariantHeaderResourceRow({
  data,
  ctx,
  colWidths,
}: {
  data: Record<string, unknown>;
  ctx: FullGridContext;
  colWidths: ColWidths;
}) {
  const positionId = data._parentPositionId as string;
  const headerName = (data._variantHeaderName as string) || '';
  const chosenLabel = data._variantHeaderChosenLabel as string | null;
  const chosenPrice = data._variantHeaderChosenPrice as number | null;
  const optCount = (data._variantHeaderCount as number) || 0;
  const currency = (data._variantHeaderCurrency as string) || 'EUR';
  const qty = (data._variantHeaderQty as number) || 0;
  const unitLabel = (data._variantHeaderUnit as string) || '';
  const triggerRef = useRef<HTMLButtonElement>(null);

  const openPicker = useCallback(() => {
    ctx.onOpenPositionVariantPicker?.(positionId, triggerRef.current);
  }, [ctx, positionId]);

  const rate = chosenPrice ?? 0;
  const total = qty * rate;
  const fmtNum = (n: number) => ctx.fmt.format(n);
  // Display name = ``price_abstract_resource_common_start`` as the base
  // + the chosen ``price_abstract_resource_variable_parts`` token (the
  // picked variant). When nothing's picked yet we show just the base.
  // Defensive: if the chosen label was stamped as the full label
  // (e.g. legacy mis-stamped imports), don't double up the prefix.
  // The position description never bleeds into this name.
  const trimmedBase = headerName.trim();
  const trimmedChosen = (chosenLabel ?? '').trim();
  const labelStartsWithBase =
    trimmedChosen.length > 0 &&
    trimmedBase.length > 0 &&
    trimmedChosen.toLowerCase().startsWith(trimmedBase.toLowerCase());
  let computedName: string;
  if (trimmedBase && trimmedChosen && !labelStartsWithBase) {
    computedName = `${trimmedBase} ${trimmedChosen}`;
  } else if (trimmedChosen) {
    computedName = trimmedChosen;
  } else {
    computedName = trimmedBase;
  }

  // Local edit state — the user can rename the variant resource inline.
  // On commit we POST the new name to the user's catalog (the same code
  // path the BookmarkPlus button on regular resources uses) so the row
  // "becomes" a regular saved article. The row keeps its variant
  // decorations so subsequent variant swaps still flip the rate.
  const [editedName, setEditedName] = useState(computedName);
  // Reset when the chosen variant changes upstream.
  useEffect(() => setEditedName(computedName), [computedName]);
  const isCustomName = editedName.trim() !== computedName.trim() && editedName.trim().length > 0;

  // qty / rate edit handlers. The variant row is a SYNTHETIC view of the
  // parent position, so commits flow into ``onUpdateVariantHeader`` which
  // patches ``position.quantity`` / ``position.unit_rate`` upstream.
  const handleQtyCommit = useCallback(
    (v: number) => {
      ctx.onUpdateVariantHeader?.(positionId, { quantity: v });
    },
    [ctx, positionId],
  );
  const handleRateCommit = useCallback(
    (v: number) => {
      ctx.onUpdateVariantHeader?.(positionId, { unit_rate: v });
    },
    [ctx, positionId],
  );

  // When qty is unset / 0 we hide qty / rate / total entirely — the user's
  // spec: "если количества нет - то ничего и не показывай". The picker
  // and the editable name still render so the user can pick a variant or
  // promote the row before entering a quantity.
  const showNumbers = qty > 0;

  return (
    <div
      className="relative flex items-stretch w-full h-full select-none group/vh text-xs
                 bg-violet-50/60 dark:bg-violet-950/25
                 border-b border-border-light/50
                 transition-colors"
      style={{ paddingLeft: `${colWidths.leftPad}px`, paddingRight: '4px' }}
      data-testid={`variant-header-row-${positionId}`}
    >
      {/* Provenance bar — same width as the resource provenance bar so the
          variant row visually slots into the resource list, just with a
          violet→fuchsia gradient announcing "this is the variant pick". */}
      <span
        aria-hidden="true"
        className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-violet-500 to-fuchsia-600"
      />

      {/* Code slot — width = ordinal column (right-aligned, mirrors
          EditableResourceRow). Shows a small "VAR" chip instead of a
          catalogue code; tooltip explains the slot. */}
      <span
        className="shrink-0 inline-flex items-center justify-end self-center pr-2 text-[8px] font-mono whitespace-nowrap overflow-hidden"
        style={{ width: `${colWidths.ordinal}px` }}
        title={ctx.t('boq.variant_header_code_tooltip', {
          defaultValue: 'Abstract variant resource — inherits the position quantity',
        })}
      >
        <span className="px-1 py-0.5 rounded bg-violet-200/60 dark:bg-violet-800/40 text-violet-800 dark:text-violet-200 font-bold tracking-wider">
          VAR
        </span>
      </span>

      {/* Type slot — width = _bim_link column. Mirrors the resource type
          chip ("МАТЕРИАЛЫ" / "ОБОРУДОВАНИЕ" / ...) by rendering a
          dedicated "VARIANT" chip in the same place, so the variant
          resource visually slots into the same column the user already
          scans for resource categorisation. Mirrors EditableResourceRow
          padding (``pl-2 pr-3``) so the name slot can start at the
          SAME X as the position description (visual spine). */}
      <span
        className="shrink-0 inline-flex items-center justify-end self-center pl-2 pr-3"
        style={{ width: `${colWidths.bimLink}px` }}
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            openPicker();
          }}
          onMouseDown={(e) => e.stopPropagation()}
          className="inline-flex items-center px-1.5 py-0.5 rounded
                     bg-gradient-to-br from-violet-500 to-fuchsia-600 text-white
                     text-[9px] font-bold uppercase tracking-wider
                     ring-1 ring-white/30 shadow-[0_1px_3px_rgba(139,92,246,0.4)]
                     hover:from-violet-400 hover:to-fuchsia-500
                     hover:shadow-[0_2px_6px_rgba(217,70,239,0.5)]
                     hover:scale-105 active:scale-95
                     transition-all duration-150 cursor-pointer"
          title={ctx.t('boq.variant_header_type_tooltip', {
            defaultValue: 'Click to pick a price variant from the catalog',
          })}
          data-testid={`variant-header-chip-${positionId}`}
        >
          {ctx.t('boq.variant_header_type_label', { defaultValue: 'Variant' })}
        </button>
      </span>

      {/* Name slot — flex-1, mirrors the position description column.
          The V badge lives on the parent position's description (not
          repeated here); the VARIANT type chip + the violet provenance
          bar already mark this row as the variant resource. The name is
          editable: editing + committing turns this into a custom article
          name that can be saved to the catalog via the BookmarkPlus
          button in the Actions column (mirrors regular resources). */}
      <span
        className="truncate min-w-0 flex-1 self-center text-left text-content-primary font-medium pl-1 pr-1 inline-flex items-center gap-1"
        data-variant-header-interactive="1"
      >
        <InlineTextInput
          value={editedName}
          onCommit={(v) => setEditedName(v)}
          className="flex-1 min-w-0 text-xs text-left"
        />
      </span>

      {/* Classification spacer — same hidden-by-default col as the
          resource row so toggling on classification doesn't break align. */}
      {colWidths.classification > 0 && (
        <span className="shrink-0 self-center" style={{ width: `${colWidths.classification}px` }} aria-hidden="true" />
      )}

      {/* Unit slot. */}
      <span
        className="shrink-0 text-center text-content-secondary font-mono uppercase self-center px-2 text-[11px]"
        style={{ width: `${colWidths.unit}px` }}
      >
        {unitLabel || '—'}
      </span>

      {/* _bim_qty spacer — same 28px column as the resource row. */}
      {colWidths.bimQty > 0 && (
        <span className="shrink-0 self-center" style={{ width: `${colWidths.bimQty}px` }} aria-hidden="true" />
      )}

      {/* Quantity slot — editable. Inherits from the parent position;
          commits go through ``onUpdateVariantHeader`` which patches
          ``position.quantity`` upstream. Empty when qty <= 0 (per user
          spec: hide numbers when the position has no quantity yet). */}
      <span
        className="shrink-0 text-right tabular-nums text-content-secondary self-center pr-1 pl-1"
        style={{ width: `${colWidths.quantity}px` }}
        data-variant-header-interactive="1"
        title={ctx.t('boq.variant_header_qty_edit_tooltip', {
          defaultValue: 'Double-click to edit quantity (synced with the position).',
        })}
      >
        {showNumbers ? (
          <InlineNumberInput
            value={qty}
            onCommit={handleQtyCommit}
            fmt={ctx.fmt}
            className="w-full text-xs"
          />
        ) : (
          ''
        )}
      </span>

      {/* Unit rate slot — picker pill (▾ N) opens the variant picker;
          rate is editable inline. Editing the rate manually keeps the
          variant marker but overrides the price — the user's spec for
          "стоановится обычным артикулом" is honoured by the editable
          name + Save-to-catalog action above. */}
      <span
        className="shrink-0 inline-flex items-center justify-end self-center gap-1 pr-2 pl-2"
        style={{ width: `${colWidths.unitRate}px` }}
        data-variant-header-interactive="1"
      >
        <button
          ref={triggerRef}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            openPicker();
          }}
          onMouseDown={(e) => e.stopPropagation()}
          className="shrink-0 inline-flex items-center gap-0.5 h-4 px-1 rounded text-[9px] font-semibold
                     bg-gradient-to-br from-violet-500 to-fuchsia-600 text-white
                     ring-1 ring-white/30 shadow-[0_1px_3px_rgba(139,92,246,0.4)]
                     hover:from-violet-400 hover:to-fuchsia-500 hover:shadow-[0_2px_6px_rgba(217,70,239,0.5)]
                     hover:scale-105 active:scale-95
                     transition-all duration-150 cursor-pointer"
          title={ctx.t('boq.variant_header_pill_tooltip', {
            defaultValue: 'Choose / switch a price variant for this abstract resource',
          })}
          data-testid={`variant-header-pill-${positionId}`}
        >
          ▾ {optCount}
        </button>
        {showNumbers && (
          <>
            <span className="flex-1 min-w-0 text-right tabular-nums text-content-primary text-xs font-semibold">
              <InlineNumberInput
                value={rate}
                onCommit={handleRateCommit}
                fmt={ctx.fmt}
                className="w-full text-xs"
              />
            </span>
            <span className="shrink-0 inline-flex items-center justify-center w-7 text-[10px] font-mono text-content-secondary">
              {currency}
            </span>
          </>
        )}
      </span>

      {/* Total slot — also empty when qty is 0 / missing. */}
      <span
        className="shrink-0 text-right tabular-nums font-semibold text-content-primary self-center pr-2 pl-2"
        style={{ width: `${colWidths.total}px` }}
      >
        {showNumbers ? fmtNum(total) : ''}
      </span>

      {/* Actions slot — Save-to-catalog button mirrors the regular
          resource row's BookmarkPlus, surfaces only after the user has
          renamed the variant resource (so the user is opting in to
          catalog-promote a customised name). Width matches the position
          row's actions column for vertical alignment. */}
      <span
        className="shrink-0 flex items-center justify-center gap-0.5 self-center"
        style={{ width: `${colWidths.actions}px` }}
      >
        {isCustomName && ctx.onSaveVariantHeaderToCatalog && (
          <button
            type="button"
            data-variant-header-interactive="1"
            onClick={(e) => {
              e.stopPropagation();
              ctx.onSaveVariantHeaderToCatalog?.(positionId, editedName);
            }}
            onMouseDown={(e) => e.stopPropagation()}
            className="shrink-0 h-4 w-4 flex items-center justify-center rounded
                       text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle
                       transition-all"
            title={ctx.t('boq.rs_save_variant_to_catalog', {
              defaultValue: 'Save as a regular article in your catalog',
            })}
          >
            <BookmarkPlus size={10} />
          </button>
        )}
      </span>
    </div>
  );
}

/* ── Resource Full-Width Renderer ──────────────────────────────────── */

export function ResourceFullWidthRenderer(params: ICellRendererParams) {
  const { data, context, api } = params;
  const ctx = context as FullGridContext | undefined;

  // Read actual column widths from the grid for perfect alignment.
  //
  // leftPad lands the resource's catalogue-code chip at the SAME X as
  // the position's ordinal cell (e.g. "01.02.003") — the visual spine
  // the user asked for: position ordinals and resource codes line up
  // vertically. Includes _drag + _checkbox + _expand (the three
  // before the ordinal column).
  const colWidths = useMemo(() => {
    const getW = (id: string) => api?.getColumn(id)?.getActualWidth() ?? 0;
    // Extra 56px nudge — pushes code chip / type tag / resource name
    // visibly to the right of the position ordinal column so the resource
    // panel reads as visually subordinate to its parent position. The
    // numeric columns (unit / qty / rate / total / actions) keep the same
    // X coordinates as the position row because the flex-1 name slot
    // absorbs the shift.
    const leftPad = getW('_drag') + getW('_checkbox') + getW('_expand') + 56;
    return {
      leftPad,
      ordinal: getW('ordinal'),
      bimLink: getW('_bim_link'),
      // classification is hide:true by default; if a user toggles it on,
      // we still match the position layout so values stay aligned.
      classification: getW('classification'),
      unit: getW('unit'),
      // _bim_qty is a 28px visible column between unit and quantity; the
      // resource row needs a matching spacer or every numeric value
      // (qty/rate/total/actions) sits 28px LEFT of its position counterpart.
      bimQty: getW('_bim_qty'),
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

  // Synthetic "abstract variant" header — surfaces the position-level
  // CWICR variant catalog as a visible row inside the resource panel.
  // V badge prominent + click anywhere reopens the position-level picker.
  if (data?._isVariantHeader) {
    return <VariantHeaderResourceRow data={data} ctx={ctx} colWidths={colWidths} />;
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
    // Footer rows (Direct Cost / Net Total / VAT / Gross Total) must not
    // display a numeric Qty — totals don't have a meaningful quantity (Bug 15).
    if (data?._isFooter) return <span />;
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
  const hasDwgSource = !!meta.dwg_annotation_source;
  const formulaSource = typeof meta.formula === 'string' ? meta.formula : null;

  let colorClass = '';
  let titleText: string | undefined;
  if (hasPdfSource) {
    colorClass = 'font-semibold text-rose-700 dark:text-rose-400';
    titleText = String(meta.pdf_measurement_source);
  } else if (hasDwgSource) {
    colorClass = 'font-semibold text-amber-700 dark:text-amber-400';
    titleText = String(meta.dwg_annotation_source);
  } else if (hasBimSource) {
    colorClass = 'font-semibold text-emerald-700 dark:text-emerald-400';
    titleText = String(meta.bim_qty_source);
  } else if (formulaSource) {
    // Issue #90: cells with a stored formula get a violet accent + the
    // formula string in the title so a user knows the qty is computed.
    colorClass = 'font-semibold text-violet-700 dark:text-violet-300';
    titleText = `Formula: ${formulaSource}`;
  }

  // When a formula is the source of the value, give the cell a clear,
  // unmissable visual treatment: a violet ƒx pill on the left, the resolved
  // number on the right, and the original formula string surfaced in the
  // browser tooltip. Click → re-enter edit mode and the FormulaCellEditor
  // pre-fills with the source formula (not the resolved number).
  if (formulaSource && !hasBimSource && !hasPdfSource && !hasDwgSource) {
    return (
      <span
        className="relative flex items-center justify-end gap-1 w-full h-full text-xs tabular-nums leading-[32px]"
        title={`ƒx ${formulaSource}  =  ${formatted}\n\nClick to edit the formula.`}
      >
        <span
          aria-hidden="true"
          className="inline-flex items-center px-1 h-[16px] rounded text-[9px] font-bold leading-none tracking-tight bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300 border border-violet-300/60 dark:border-violet-700/50"
        >
          ƒx
        </span>
        <span className="font-semibold text-violet-700 dark:text-violet-300">{formatted}</span>
      </span>
    );
  }

  // Source badge: BIM → Cuboid, PDF → Ruler, DWG → FileBox. Same icons used
  // by the link-buttons next to the description column so provenance is
  // visually consistent across the grid.
  if (hasBimSource || hasPdfSource || hasDwgSource) {
    const Icon = hasBimSource ? Cuboid : hasPdfSource ? Ruler : FileBox;
    return (
      <span
        className={`flex items-center justify-end gap-1 w-full h-full text-xs tabular-nums leading-[32px] ${colorClass}`}
        title={titleText}
      >
        <Icon className="w-3 h-3 opacity-80" aria-hidden="true" />
        <span>{formatted}</span>
      </span>
    );
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

/* ── Unit Rate Cell + inline CWICR Variant Picker ──────────────────── */

/**
 * `UnitRateCellRenderer` — shows the position's `unit_rate` and, when the
 * position carries CWICR abstract-resource variants, surfaces a small
 * "▾ N options" pill that opens the inline `VariantPicker` for live
 * variant switching.
 *
 * Persistence: the picker resolves to a `CostVariant`, the renderer wraps
 * the parent's `onUpdatePosition` callback to PATCH `metadata.variant`
 * + `unit_rate`.  The backend re-stamps `variant_snapshot` (frozen rate
 * + currency + UTC timestamp) so the choice survives a cost-DB re-import.
 *
 * Visibility rules:
 *   • Positions without `metadata.cost_item_variants` (or with <2) fall
 *     through to the default tabular-nums numeric cell — no extra UI.
 *   • Resource-driven positions (where `metadata.resources` derives the
 *     rate) suppress the pill — picking a variant on a position whose
 *     rate is computed from resources would silently get overwritten on
 *     the next resource edit.
 *
 * Why a renderer (not a popup off the column header):
 *   • AG Grid mounts/unmounts row renderers on virtualisation, so the
 *     picker state must live OUTSIDE the renderer.  We portal the picker
 *     to `document.body` from inside the renderer hook — same pattern as
 *     `BIMQuantityPicker` / `PdfDwgSourcePopover`.
 */
export function UnitRateCellRenderer(params: ICellRendererParams) {
  const { data, value, context } = params;
  const ctx = context as FullGridContext | undefined;
  const t = ctx?.t ?? ((key: string, opts?: Record<string, string | number>) =>
    (opts?.defaultValue as string) ?? key);

  // Footer / section / resource sub-row / add-resource row → default cell.
  if (!data || data._isSection || data._isFooter || data._isResource || data._isAddResource) {
    return <span className="text-right text-xs tabular-nums">{value ?? ''}</span>;
  }

  const meta = (data.metadata ?? {}) as Record<string, unknown>;
  const variants = meta.cost_item_variants as CostVariant[] | undefined;
  const stats = meta.cost_item_variant_stats as VariantStats | undefined;
  const variant = (meta as { variant?: { label: string; price: number; index: number } }).variant;
  const variantDefault = meta.variant_default as 'mean' | 'median' | undefined;
  const currency = (meta.currency as string | undefined) || ctx?.currencyCode || 'USD';
  const unit = data.unit as string | undefined;
  const resources = meta.resources;
  const isResourceDriven = Array.isArray(resources) && resources.length > 0;

  const numericVal = typeof value === 'number' ? value : parseFloat(String(value ?? 0));
  const formatted = (() => {
    try {
      return new Intl.NumberFormat(getIntlLocale(), {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(isNaN(numericVal) ? 0 : numericVal);
    } catch {
      return String(value ?? '');
    }
  })();

  const hasVariants = Array.isArray(variants) && variants.length >= 2 && stats != null;

  // Picker state — owned per renderer instance.  AG Grid re-mounts the
  // renderer when the row scrolls out / back, so an open picker on a
  // virtualised row will close cleanly when the row leaves the viewport.
  const [pickerOpen, setPickerOpen] = useState(false);
  const anchorRef = useRef<HTMLButtonElement>(null);

  const closePicker = useCallback(() => setPickerOpen(false), []);

  const handlePick = useCallback(
    (chosen: CostVariant) => {
      setPickerOpen(false);
      if (!ctx?.onUpdatePosition || !data?.id) return;
      const newMeta = { ...meta };
      // Drop the auto-default marker — user made an explicit pick.
      if ('variant_default' in newMeta) delete newMeta.variant_default;
      newMeta.variant = {
        label: chosen.label,
        price: chosen.price,
        index: chosen.index,
      };
      ctx.onUpdatePosition(
        data.id as string,
        {
          unit_rate: chosen.price,
          metadata: newMeta,
        },
        {
          unit_rate: numericVal,
          metadata: meta,
        },
      );
    },
    [ctx, data, meta, numericVal],
  );

  const handleUseDefault = useCallback(
    (strategy: 'mean' | 'median') => {
      setPickerOpen(false);
      if (!ctx?.onUpdatePosition || !data?.id || !stats) return;
      const newRate =
        strategy === 'mean' && stats.mean > 0
          ? stats.mean
          : stats.median > 0
            ? stats.median
            : numericVal;
      const newMeta = { ...meta };
      if ('variant' in newMeta) delete newMeta.variant;
      newMeta.variant_default = strategy;
      ctx.onUpdatePosition(
        data.id as string,
        {
          unit_rate: newRate,
          metadata: newMeta,
        },
        {
          unit_rate: numericVal,
          metadata: meta,
        },
      );
    },
    [ctx, data, meta, numericVal, stats],
  );

  // No variant cache → just render the formatted number.  Cell is still
  // editable (click → AG Grid mounts agNumberCellEditor).
  if (!hasVariants) {
    const colorClass = isResourceDriven ? 'text-content-tertiary' : '';
    return (
      <span className={`block text-right text-xs tabular-nums w-full h-full leading-[32px] ${colorClass}`}>
        {formatted}
      </span>
    );
  }

  // Variant cache present — render number + pill.  When resource-driven,
  // suppress the pill (rate is computed from resources, not a variant).
  const optsCount = stats!.count;
  const minMax = `${stats!.min.toFixed(2)} – ${stats!.max.toFixed(2)} ${currency}`;
  const tooltip = variant
    ? t('boq.unit_rate_variant_pill_tooltip_picked', {
        defaultValue:
          'Currently: {{label}}. Click to switch to a different variant.',
        label: variant.label,
      })
    : variantDefault
      ? t('boq.unit_rate_variant_pill_tooltip_default', {
          defaultValue:
            'Auto-applied with {{strategy}} rate ({{count}} options, {{range}}). Click to refine.',
          strategy:
            variantDefault === 'mean'
              ? t('costs.variant_mean_word', { defaultValue: 'average' })
              : t('costs.variant_median_word', { defaultValue: 'median' }),
          count: optsCount,
          range: minMax,
        })
      : t('boq.unit_rate_variant_pill_tooltip_unset', {
          defaultValue:
            '{{count}} priced variants available ({{range}}). Click to pick one.',
          count: optsCount,
          range: minMax,
        });

  return (
    <span className="flex items-center justify-end gap-1.5 w-full h-full text-xs tabular-nums leading-[32px]">
      <span className={isResourceDriven ? 'text-content-tertiary' : ''}>{formatted}</span>
      {!isResourceDriven && (
        <button
          ref={anchorRef}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setPickerOpen((open) => !open);
          }}
          onMouseDown={(e) => e.stopPropagation()}
          className={`shrink-0 inline-flex items-center gap-0.5 h-5 px-1.5 rounded text-[10px] font-semibold
                      transition-colors cursor-pointer ${
                        variant
                          ? 'bg-oe-blue/15 text-oe-blue hover:bg-oe-blue/25'
                          : 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/60'
                      }`}
          title={tooltip}
          aria-label={tooltip}
          aria-haspopup="dialog"
          aria-expanded={pickerOpen}
          data-testid={`boq-variant-pill-${data.id}`}
        >
          {t('boq.unit_rate_variant_pill', {
            defaultValue: '\u25BE {{count}} options',
            count: optsCount,
          })}
        </button>
      )}
      {pickerOpen && hasVariants && (
        <VariantPicker
          variants={variants!}
          stats={stats!}
          defaultStrategy="mean"
          defaultIndex={variant?.index}
          anchorEl={anchorRef.current}
          unitLabel={unit || ''}
          currency={currency}
          onApply={handlePick}
          onUseDefault={handleUseDefault}
          onClose={closePicker}
        />
      )}
    </span>
  );
}

/* ── Unit Cell — shows unit + BIM param name if sourced from model ── */

export function UnitCellRenderer(params: ICellRendererParams) {
  const { data, value } = params;
  // Bug 9: render the raw unit code (e.g. "m2") with NO casing transform — must match
  // the agSelectCellEditor dropdown which lists lowercase values.
  if (!data || data._isSection || data._isFooter) {
    return <span className="text-center text-2xs font-mono">{value ?? ''}</span>;
  }

  const meta = (data.metadata ?? {}) as Record<string, unknown>;
  const bimSource = meta.bim_qty_source as string | undefined;
  const pdfSource = meta.pdf_measurement_source as string | undefined;
  const dwgSource = meta.dwg_annotation_source as string | undefined;

  // No source indicator needed
  if (!bimSource && !pdfSource && !dwgSource) {
    return <span className="text-center text-2xs font-mono w-full block">{value ?? ''}</span>;
  }

  if (pdfSource) {
    // Extract short label: "Takeoff: Area on Page 3" -> "Page 3"
    const parts = pdfSource.split(' on ');
    const shortLabel = (parts[parts.length - 1] ?? pdfSource).trim();
    return (
      <div className="flex flex-col items-center justify-center h-full w-full gap-0">
        <span className="text-2xs font-mono leading-tight">{value ?? ''}</span>
        <span
          className="text-[7px] leading-none font-medium text-rose-600 dark:text-rose-400 truncate max-w-full"
          title={pdfSource}
        >
          {shortLabel}
        </span>
      </div>
    );
  }

  if (dwgSource) {
    // Extract short label: "DWG: Area annotation" -> "annotation" (last token).
    const parts = dwgSource.split(/[:/]/);
    const shortLabel = (parts[parts.length - 1] ?? dwgSource).trim();
    return (
      <div className="flex flex-col items-center justify-center h-full w-full gap-0">
        <span className="text-2xs font-mono leading-tight">{value ?? ''}</span>
        <span
          className="text-[7px] leading-none font-medium text-amber-600 dark:text-amber-400 truncate max-w-full"
          title={dwgSource}
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
      <span className="text-2xs font-mono leading-tight">{value ?? ''}</span>
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
