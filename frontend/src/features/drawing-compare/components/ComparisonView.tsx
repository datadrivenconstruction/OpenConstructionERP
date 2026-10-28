// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One stored compare: header with both revisions and the validation light,
 * the sheet viewer (PDF) or the layer table (DWG), and the change list.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Download, Loader2, Trash2 } from 'lucide-react';

import { Button, ConfirmDialog } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { drawingCompareApi, type Comparison } from '../api';
import { computeSheetDiff, DEFAULT_SETTINGS, pixelMatrix } from '../lib/sheetDiff';
import { asRaster, overlayCanvas, useSheetPair } from '../lib/useSheetPair';
import type { Affine } from '../lib/transform';
import { ChangeList } from './ChangeList';
import { CompareViewer, type ViewerMode, type ViewerRegion } from './CompareViewer';

interface ComparisonViewProps {
  comparison: Comparison;
  canWrite: boolean;
  canDelete: boolean;
  onDeleted: () => void;
}

const LIGHT: Record<string, string> = {
  passed: 'bg-emerald-500',
  warnings: 'bg-amber-500',
  errors: 'bg-red-500',
};

export function ComparisonView({ comparison, canWrite, canDelete, onDeleted }: ComparisonViewProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewerMode>('overlay');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const validation = useQuery({
    queryKey: ['drawing-compare', 'validation', comparison.id],
    queryFn: () => drawingCompareApi.validate(comparison.id),
  });
  const remove = useMutation({
    mutationFn: () => drawingCompareApi.remove(comparison.id),
    onSuccess: onDeleted,
    onError: (err) => addToast({ type: 'error', title: t('drawing_compare.action_failed', { defaultValue: 'The action did not go through' }), message: getErrorMessage(err) }),
  });

  const isPdf = comparison.source_kind === 'pdf';
  const pair = useSheetPair(
    isPdf ? comparison.old_ref_id : null,
    isPdf ? comparison.new_ref_id : null,
    comparison.old_page ?? 1,
    comparison.new_page ?? 1,
  );
  const matrix = (comparison.alignment.matrix ?? [1, 0, 0, 1, 0, 0]) as Affine;
  const diff = useMemo(() => {
    if (!pair.old || !pair.new) return null;
    const tolerance = Number(comparison.settings.tolerance ?? DEFAULT_SETTINGS.tolerance);
    return computeSheetDiff(asRaster(pair.old), asRaster(pair.new), {
      ...DEFAULT_SETTINGS,
      tolerance: Number.isFinite(tolerance) ? tolerance : DEFAULT_SETTINGS.tolerance,
      compareText: false,
      fixedMatrix: matrix,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pair.old, pair.new, comparison.id]);
  const overlay = useMemo(() => (diff ? overlayCanvas(diff.diff) : null), [diff]);
  const regions: ViewerRegion[] = useMemo(() => {
    const s = pair.new?.scale ?? 1;
    return comparison.changes.map((c) => ({ id: c.id, seq: c.seq, kind: c.kind, x: c.x * s, y: c.y * s, w: c.w * s, h: c.h * s }));
  }, [comparison.changes, pair.new]);

  const summary = comparison.summary;
  const side = (label: string, rev: string | null, page: number | null) =>
    `${label}${rev ? ` (${rev})` : ''}${isPdf && page ? `, ${t('drawing_compare.page_n', { defaultValue: 'Page {{page}}', page })}` : ''}`;
  const status = validation.data?.status ?? '';
  const failing = (validation.data?.results ?? []).filter((r) => !r.passed);

  return (
    <div className="flex flex-col gap-3" data-testid="drawing-compare-view">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-surface-primary p-3">
        <div className="min-w-0 space-y-0.5 text-sm">
          <h2 className="truncate text-base font-semibold">{comparison.name}</h2>
          <p className="truncate">
            <span className="font-medium text-red-600">{t('drawing_compare.old_revision', { defaultValue: 'Older revision' })}:</span>{' '}
            {side(comparison.old_label, comparison.old_revision, comparison.old_page)}
          </p>
          <p className="truncate">
            <span className="font-medium text-blue-600">{t('drawing_compare.new_revision', { defaultValue: 'Newer revision' })}:</span>{' '}
            {side(comparison.new_label, comparison.new_revision, comparison.new_page)}
          </p>
          <p className="text-xs text-content-secondary">
            {t('drawing_compare.summary_line', {
              defaultValue: '{{total}} changes: {{added}} added, {{removed}} removed, {{modified}} modified, {{text}} text',
              total: summary.total ?? 0,
              added: summary.added ?? 0,
              removed: summary.removed ?? 0,
              modified: summary.modified ?? 0,
              text: summary.text ?? 0,
            })}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2 text-xs" title={failing.map((r) => r.message).join('\n')}>
            <span className={clsx('h-2.5 w-2.5 rounded-full', LIGHT[status] ?? 'bg-slate-300')} />
            {validation.isLoading
              ? t('drawing_compare.validating', { defaultValue: 'Checking...' })
              : failing.length === 0
                ? t('drawing_compare.validation_ok', { defaultValue: 'All checks passed' })
                : t('drawing_compare.validation_issues', { defaultValue: 'Checks needing attention: {{n}}', n: failing.length })}
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={<Download size={13} />}
              onClick={() =>
                drawingCompareApi
                  .downloadReport(comparison.id, `revision_compare_${comparison.id.slice(0, 8)}.pdf`)
                  .catch((err) => addToast({ type: 'error', title: getErrorMessage(err) }))
              }
            >
              {t('drawing_compare.export_report', { defaultValue: 'Change report (PDF)' })}
            </Button>
            {canDelete && (
              <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={() => setConfirmDelete(true)}>
                {t('common.delete', { defaultValue: 'Delete' })}
              </Button>
            )}
          </div>
        </div>
      </div>
      {failing.length > 0 && (
        <ul className="space-y-0.5 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          {failing.map((r, i) => (
            <li key={`${r.rule_id}-${i}`}>{r.message}</li>
          ))}
        </ul>
      )}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0">
          {isPdf ? (
            pair.loading ? (
              <p className="flex items-center gap-2 text-sm text-content-secondary">
                <Loader2 size={14} className="animate-spin" />
                {t('drawing_compare.rendering', { defaultValue: 'Rendering both sheets...' })}
              </p>
            ) : pair.error ? (
              <p className="text-sm text-red-600">
                {t('drawing_compare.sheet_unavailable', { defaultValue: 'A revision could not be opened; the change list is still available.' })}
              </p>
            ) : pair.old && pair.new ? (
              <>
                <div className="mb-2 flex gap-1">
                  {(['overlay', 'side'] as ViewerMode[]).map((m) => (
                    <button key={m} type="button" onClick={() => setMode(m)} className={clsx('rounded border px-2 py-0.5 text-xs', mode === m ? 'border-oe-blue text-oe-blue' : 'border-border')}>
                      {m === 'overlay'
                        ? t('drawing_compare.mode_overlay', { defaultValue: 'Overlay' })
                        : t('drawing_compare.mode_side', { defaultValue: 'Side by side' })}
                    </button>
                  ))}
                </div>
                <CompareViewer
                  mode={mode}
                  newCanvas={pair.new.canvas}
                  oldCanvas={pair.old.canvas}
                  oldToNew={pixelMatrix(matrix, pair.old.scale, pair.new.scale)}
                  oldToNewUnaligned={pixelMatrix([1, 0, 0, 1, 0, 0], pair.old.scale, pair.new.scale)}
                  overlayCanvas={overlay}
                  regions={regions}
                  selectedId={selected}
                  onSelect={setSelected}
                />
              </>
            ) : null
          ) : (
            <DwgLayerTable comparison={comparison} />
          )}
        </div>
        <ChangeList comparison={comparison} selectedId={selected} onSelect={setSelected} canWrite={canWrite} />
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false);
          remove.mutate();
        }}
        title={t('drawing_compare.delete_title', { defaultValue: 'Delete this comparison?' })}
        message={t('drawing_compare.delete_message', {
          defaultValue: 'The change list and its triage are removed. RFIs, clouds and re-measure flags raised from it stay.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        variant="danger"
      />
    </div>
  );
}

function DwgLayerTable({ comparison }: { comparison: Comparison }) {
  const { t } = useTranslation();
  const rows = comparison.summary.by_layer ?? [];
  const entities = comparison.summary.entities;
  return (
    <div className="rounded-lg border border-border bg-surface-primary p-3 text-sm">
      {entities && (
        <p className="mb-2 text-xs text-content-secondary">
          {t('drawing_compare.entities_line', {
            defaultValue: 'Entities: {{added}} added, {{removed}} removed, {{modified}} modified, {{unchanged}} unchanged',
            ...entities,
          })}
        </p>
      )}
      {rows.length === 0 ? (
        <p className="text-content-secondary">{t('drawing_compare.no_changes_title', { defaultValue: 'No changes found' })}</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-content-tertiary">
              <th className="py-1">{t('drawing_compare.col_layer', { defaultValue: 'Layer' })}</th>
              <th>{t('drawing_compare.col_type', { defaultValue: 'Entity type' })}</th>
              <th className="text-right">{t('drawing_compare.kind_added', { defaultValue: 'Added' })}</th>
              <th className="text-right">{t('drawing_compare.kind_removed', { defaultValue: 'Removed' })}</th>
              <th className="text-right">{t('drawing_compare.kind_modified', { defaultValue: 'Modified' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.layer}-${r.entity_type}`} className="border-t border-border">
                <td className="py-1 font-mono">{r.layer}</td>
                <td>{r.entity_type}</td>
                <td className="text-right text-blue-600">{r.added}</td>
                <td className="text-right text-red-600">{r.removed}</td>
                <td className="text-right text-amber-700">{r.modified}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
