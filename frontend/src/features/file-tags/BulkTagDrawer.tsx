// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Bottom drawer for bulk tag/untag operations.
 *
 * Visible when one or more files are selected in the file manager.
 * Composes :class:`TagPickerModal` so the user can pick existing tags
 * or create a new one inline; the drawer then iterates by file kind
 * and dispatches the assign/unassign mutations.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Tag as TagIcon, Loader2 } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { TagPickerModal } from './TagPickerModal';
import { useAssignTag, useFileTags, useUnassignTag } from './hooks';
import type { FileKind } from './types';

interface BulkTagSelectionRow {
  id: string;
  kind: FileKind;
}

interface BulkTagDrawerProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Rows currently selected in the file grid/list. */
  selectedRows: BulkTagSelectionRow[];
}

export function BulkTagDrawer({
  open,
  onClose,
  projectId,
  selectedRows,
}: BulkTagDrawerProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [mode, setMode] = useState<'assign' | 'unassign'>('assign');
  const tagsQuery = useFileTags(projectId);
  const assignMutation = useAssignTag();
  const unassignMutation = useUnassignTag();

  if (!open || selectedRows.length === 0) return null;

  const rowsByKind = groupByKind(selectedRows);

  async function applyTags(tagIds: string[]) {
    if (tagIds.length === 0) return;
    const mutation = mode === 'assign' ? assignMutation : unassignMutation;
    let changedTotal = 0;
    let errorTotal = 0;
    for (const tagId of tagIds) {
      for (const [kind, rows] of rowsByKind) {
        try {
          const result = await mutation.mutateAsync({
            tagId,
            projectId,
            payload: {
              file_kind: kind,
              file_ids: rows.map((r) => r.id),
            },
          });
          changedTotal += result.changed;
        } catch {
          errorTotal += 1;
        }
      }
    }
    if (errorTotal === 0) {
      addToast({
        type: 'success',
        title:
          mode === 'assign'
            ? t('files.tags.bulk.assigned', {
                defaultValue: '{{count}} assignment(s) created',
                count: changedTotal,
              })
            : t('files.tags.bulk.unassigned', {
                defaultValue: '{{count}} assignment(s) removed',
                count: changedTotal,
              }),
      });
    } else {
      addToast({
        type: 'warning',
        title: t('files.tags.bulk.partial', {
          defaultValue: '{{changed}} succeeded, {{failed}} failed',
          changed: changedTotal,
          failed: errorTotal,
        }),
      });
    }
  }

  const tagOptions = tagsQuery.data ?? [];

  return (
    <>
      <div
        className="fixed inset-x-0 bottom-0 z-40 bg-surface-elevated border-t border-border-light shadow-lg"
        role="dialog"
        aria-label={t('files.tags.bulk.drawer_label', {
          defaultValue: 'Bulk tag operations',
        })}
      >
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 max-w-7xl mx-auto">
          <div className="flex items-center gap-2">
            <TagIcon size={14} className="text-content-secondary" />
            <span className="text-sm font-medium text-content-primary">
              {t('files.tags.bulk.title', {
                defaultValue: 'Tag {{count}} file(s)',
                count: selectedRows.length,
              })}
            </span>
          </div>

          <div className="ms-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setMode('assign');
                setPickerOpen(true);
              }}
              disabled={tagOptions.length === 0 && tagsQuery.isLoading}
              className="inline-flex items-center gap-1.5 h-8 px-3 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover disabled:opacity-50"
            >
              {assignMutation.isPending && (
                <Loader2 size={12} className="animate-spin" />
              )}
              {t('files.tags.bulk.add_tags', {
                defaultValue: 'Add tags…',
              })}
            </button>
            <button
              type="button"
              onClick={() => {
                setMode('unassign');
                setPickerOpen(true);
              }}
              disabled={tagOptions.length === 0}
              className="inline-flex items-center gap-1.5 h-8 px-3 text-xs font-medium rounded-lg border border-border-light text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
            >
              {unassignMutation.isPending && (
                <Loader2 size={12} className="animate-spin" />
              )}
              {t('files.tags.bulk.remove_tags', {
                defaultValue: 'Remove tags…',
              })}
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="inline-flex items-center justify-center h-8 w-8 rounded-lg text-content-tertiary hover:bg-surface-secondary"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      </div>

      <TagPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        projectId={projectId}
        selectedTagIds={[]}
        onSave={applyTags}
        title={
          mode === 'assign'
            ? t('files.tags.bulk.picker_assign', {
                defaultValue: 'Add tags to selected files',
              })
            : t('files.tags.bulk.picker_unassign', {
                defaultValue: 'Remove tags from selected files',
              })
        }
      />
    </>
  );
}

function groupByKind(
  rows: BulkTagSelectionRow[],
): Map<FileKind, BulkTagSelectionRow[]> {
  const out = new Map<FileKind, BulkTagSelectionRow[]>();
  for (const row of rows) {
    const bucket = out.get(row.kind);
    if (bucket) bucket.push(row);
    else out.set(row.kind, [row]);
  }
  return out;
}
