// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wording of the "Review changes from Excel" dialog.
 *
 * Every field code the server sends is shown in the reader's language through
 * the keys below. An unknown code is shown as it came, so a newer server never
 * hides a change. Counts are written as "label: number" so no language has to
 * agree a noun with the number next to it.
 */
import type { ExcelReviewPreview, ReviewChoices } from './excelReviewApi';

type Translate = (key: string, opts?: Record<string, unknown>) => string;

export function fieldLabel(t: Translate, field: string): string {
  switch (field) {
    case 'description':
      return t('boq.excel_review.field_description', { defaultValue: 'Description' });
    case 'unit':
      return t('boq.excel_review.field_unit', { defaultValue: 'Unit' });
    case 'ordinal':
      return t('boq.excel_review.field_ordinal', { defaultValue: 'Pos.' });
    case 'quantity':
      return t('boq.excel_review.field_quantity', { defaultValue: 'Quantity' });
    case 'unit_rate':
      return t('boq.excel_review.field_unit_rate', { defaultValue: 'Unit rate' });
    case 'classification':
      return t('boq.excel_review.field_classification', { defaultValue: 'Classification' });
    default:
      return field;
  }
}

/** A value for display: an empty one reads as a dash. */
export function valueText(value: string | null | undefined): string {
  return value == null || value === '' ? '-' : value;
}

export function tabLabel(t: Translate, tab: ReviewTab, count: number): string {
  const name =
    tab === 'changed'
      ? t('boq.excel_review.tab_changed', { defaultValue: 'Changed' })
      : tab === 'new'
        ? t('boq.excel_review.tab_new', { defaultValue: 'New' })
        : tab === 'removed'
          ? t('boq.excel_review.tab_removed', { defaultValue: 'Removed in Excel' })
          : t('boq.excel_review.tab_conflicts', { defaultValue: 'Conflicts' });
  return `${name}: ${count}`;
}

export type ReviewTab = 'changed' | 'new' | 'removed' | 'conflicts';

/** The tab to open on: the first one that has rows, conflicts first because they need a decision. */
export function firstTab(preview: ExcelReviewPreview): ReviewTab {
  if (preview.counts.conflicts > 0) return 'conflicts';
  if (preview.counts.updated > 0) return 'changed';
  if (preview.counts.created > 0) return 'new';
  return 'removed';
}

/** Per-row decision for a stale row: the app value stays unless the person picks Excel. */
export type ConflictChoice = 'app' | 'excel';

export interface ReviewState {
  /** Changed rows the person unticked. */
  unticked: ReadonlySet<string>;
  /** Missing rows the person ticked for deletion. */
  deleting: ReadonlySet<string>;
  /** Stale rows by the person's choice; absent means "keep the app value". */
  conflictChoice: Readonly<Record<string, ConflictChoice>>;
}

export const EMPTY_REVIEW_STATE: ReviewState = {
  unticked: new Set(),
  deleting: new Set(),
  conflictChoice: {},
};

/**
 * How many changes the Apply button will make: ticked changed rows, every new
 * row, stale rows set to the Excel value and missing rows ticked for deletion.
 * Nothing is preselected that deletes or overwrites, so a fresh state counts
 * only the plain edits and the new rows.
 */
export function applyCount(preview: ExcelReviewPreview, state: ReviewState): number {
  const changed = preview.updated.filter((u) => !state.unticked.has(u.position_id)).length;
  const overwritten = preview.conflicts.filter((c) => state.conflictChoice[c.position_id] === 'excel').length;
  const deleted = preview.would_delete.filter((r) => state.deleting.has(r.position_id)).length;
  return changed + overwritten + deleted + preview.counts.created;
}

/**
 * The lists the apply call sends. Unticked changes and stale rows left on the
 * app value are skipped explicitly, so the server never writes them; only
 * ticked missing rows are listed for deletion.
 */
export function buildChoices(preview: ExcelReviewPreview, state: ReviewState): ReviewChoices {
  const skipIds = [
    ...preview.updated.filter((u) => state.unticked.has(u.position_id)).map((u) => u.position_id),
    ...preview.conflicts.filter((c) => state.conflictChoice[c.position_id] !== 'excel').map((c) => c.position_id),
  ];
  const acceptIds = preview.conflicts.filter((c) => state.conflictChoice[c.position_id] === 'excel').map((c) => c.position_id);
  const deleteIds = preview.would_delete.filter((r) => state.deleting.has(r.position_id)).map((r) => r.position_id);
  return { skipIds, acceptIds, deleteIds };
}
