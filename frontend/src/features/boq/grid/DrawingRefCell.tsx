// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Read-only "Drawing" cell of the BOQ grid: the sheet and revision a position
// was measured from. One chip per position ("A-101 · rev C", "+N" for more
// sheets); an amber "Revised" badge when the sheet has a newer revision. A chip
// opens the sheet at the measured page, the badge opens the revision compare,
// "+N" and the empty-cell "+" open the position's source-drawings panel.

import type { ICellRendererParams } from 'ag-grid-community';
import { FileText, Plus } from 'lucide-react';

import {
  drawingRefLabel,
  type DrawingRef,
  type PositionDrawingRefs,
} from '../drawingRefsApi';

type T = (key: string, opts?: Record<string, string | number>) => string;

/** What the grid context carries for this column. */
export interface DrawingRefGridContext {
  t?: T;
  /** Drawing references of the bill's positions, keyed by position id. */
  drawingRefs?: Map<string, PositionDrawingRefs>;
  /** Opens the sheet of a reference at its page. */
  onOpenDrawingRef?: (ref: DrawingRef) => void;
  /** Opens the revision compare of a reference. */
  onCompareDrawingRef?: (ref: DrawingRef) => void;
  /** Opens the source-drawings panel of a position. */
  onOpenDrawingRefs?: (positionId: string) => void;
}

export interface DrawingRefCellView {
  /** The reference the chip shows: the first measured sheet, else the manual one. */
  first: DrawingRef | null;
  manualOnly: boolean;
  /** How many more references hide behind "+N". */
  more: number;
  outdated: boolean;
}

export function drawingRefCellView(entry: PositionDrawingRefs): DrawingRefCellView {
  const total = entry.refs.length + (entry.manual ? 1 : 0);
  const first = entry.refs[0] ?? null;
  return {
    first,
    manualOnly: first === null && entry.manual !== null,
    more: Math.max(0, total - 1),
    outdated: entry.outdated || entry.refs.some((r) => r.outdated),
  };
}

const fallbackT: T = (key, opts) =>
  String(opts?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));

export function DrawingRefCellRenderer(params: ICellRendererParams) {
  const { data } = params;
  const ctx = params.context as DrawingRefGridContext | undefined;
  if (!data || data._isFooter || data._isSection || data._isResource || data._isAddResource) return null;
  const id = data.id as string | undefined;
  if (!id) return null;
  const t = ctx?.t ?? fallbackT;
  const entry = ctx?.drawingRefs?.get(id);

  if (!entry || (entry.refs.length === 0 && !entry.manual)) {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          ctx?.onOpenDrawingRefs?.(id);
        }}
        title={t('boq.drawing_ref.add_tip', { defaultValue: 'Note the drawing this line comes from' })}
        data-testid={`drawing-ref-add-${id}`}
        className="flex h-full w-full items-center text-content-quaternary opacity-0 hover:opacity-100 focus:opacity-100"
      >
        <Plus size={12} />
      </button>
    );
  }

  const view = drawingRefCellView(entry);
  const ref = view.first;
  const manual = entry.manual;
  const label = ref ? drawingRefLabel(ref, t) : manual ? drawingRefLabel(manual, t) : '';
  const tip = ref
    ? [
        ref.drawing_title,
        t('boq.drawing_ref.page_n', { defaultValue: 'page {{page}}', page: ref.page }),
        t('boq.drawing_ref.open_tip', { defaultValue: 'Click to open the drawing' }),
      ]
        .filter(Boolean)
        .join(' · ')
    : t('boq.drawing_ref.manual_tip', { defaultValue: 'Entered by hand. Click to edit.' });

  const chipCls = view.manualOnly
    ? 'border border-dashed border-border-light bg-transparent text-content-secondary'
    : 'bg-surface-secondary text-content-primary';

  return (
    <div className="flex h-full w-full min-w-0 items-center gap-1" data-testid={`drawing-ref-cell-${id}`}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          if (ref) ctx?.onOpenDrawingRef?.(ref);
          else ctx?.onOpenDrawingRefs?.(id);
        }}
        title={tip}
        data-testid={`drawing-ref-chip-${id}`}
        className={`inline-flex min-w-0 items-center gap-1 rounded px-1.5 py-0.5 text-2xs font-mono hover:underline ${chipCls}`}
      >
        <FileText size={10} className="shrink-0" />
        <span className="truncate">{label}</span>
      </button>
      {view.outdated && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            const stale = entry.refs.find((r) => r.outdated) ?? ref;
            if (stale && stale.compare) ctx?.onCompareDrawingRef?.(stale);
            else ctx?.onOpenDrawingRefs?.(id);
          }}
          title={t('boq.drawing_ref.revised_tip', {
            defaultValue: 'A newer revision of this drawing exists: {{rev}}. Click to see what changed.',
            rev: (entry.refs.find((r) => r.outdated) ?? ref)?.current_revision ?? '',
          })}
          data-testid={`drawing-ref-revised-${id}`}
          className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-2xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
        >
          {t('boq.drawing_ref.revised', { defaultValue: 'Revised' })}
        </button>
      )}
      {view.more > 0 && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            ctx?.onOpenDrawingRefs?.(id);
          }}
          title={t('boq.drawing_ref.more_tip', { defaultValue: 'Show all source drawings' })}
          data-testid={`drawing-ref-more-${id}`}
          className="shrink-0 text-2xs text-content-tertiary hover:text-content-primary"
        >
          +{view.more}
        </button>
      )}
    </div>
  );
}
