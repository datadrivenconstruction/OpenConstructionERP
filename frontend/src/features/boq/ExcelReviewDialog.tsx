// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Review changes from Excel": what an edited export would change in the bill,
 * shown before anything is written.
 *
 * Tabs: Changed (field by field, old to new), New, Removed in Excel (unticked
 * "Delete from BOQ") and Conflicts (rows changed in the app since the export,
 * default "Keep app value"). Nothing that deletes or overwrites is preselected.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, X } from 'lucide-react';
import type { ExcelReviewPreview, ReviewChoices, UpdatedRow } from './excelReviewApi';
import {
  applyCount,
  buildChoices,
  EMPTY_REVIEW_STATE,
  fieldLabel,
  firstTab,
  tabLabel,
  valueText,
  type ConflictChoice,
  type ReviewState,
  type ReviewTab,
} from './excelReviewText';

export interface ExcelReviewDialogProps {
  open: boolean;
  preview: ExcelReviewPreview;
  applying?: boolean;
  onApply: (choices: ReviewChoices) => void;
  onCancel: () => void;
}

function toggled(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function ChangeTable({ rows }: { rows: UpdatedRow[] }) {
  const { t } = useTranslation();
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-content-tertiary">
          <th className="py-1 pr-2 font-medium">{t('boq.excel_review.col_pos', { defaultValue: 'Pos.' })}</th>
          <th className="py-1 pr-2 font-medium">{t('boq.excel_review.col_field', { defaultValue: 'Field' })}</th>
          <th className="py-1 pr-2 font-medium">{t('boq.excel_review.col_old', { defaultValue: 'In the bill' })}</th>
          <th className="py-1 font-medium">{t('boq.excel_review.col_new', { defaultValue: 'In Excel' })}</th>
        </tr>
      </thead>
      <tbody>
        {rows.flatMap((row) =>
          row.changes.map((change, i) => (
            <tr key={`${row.position_id}-${change.field}`} className="border-t border-border-light align-top">
              <td className="py-1 pr-2 tabular-nums text-content-secondary">{i === 0 ? row.ordinal : ''}</td>
              <td className="py-1 pr-2">{fieldLabel(t, change.field)}</td>
              <td className="py-1 pr-2 text-content-tertiary line-through decoration-content-quaternary">
                {valueText(change.old)}
              </td>
              <td className="py-1 font-medium text-content-primary">{valueText(change.new)}</td>
            </tr>
          )),
        )}
      </tbody>
    </table>
  );
}

export function ExcelReviewDialog({ open, preview, applying = false, onApply, onCancel }: ExcelReviewDialogProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<ReviewTab>(() => firstTab(preview));
  const [state, setState] = useState<ReviewState>(EMPTY_REVIEW_STATE);

  const total = useMemo(() => applyCount(preview, state), [preview, state]);

  if (!open) return null;

  const tabs: { id: ReviewTab; count: number }[] = [
    { id: 'changed', count: preview.counts.updated },
    { id: 'new', count: preview.counts.created },
    { id: 'removed', count: preview.counts.would_delete },
    { id: 'conflicts', count: preview.counts.conflicts },
  ];

  const empty = (
    <p className="py-6 text-center text-xs text-content-tertiary">
      {t('boq.excel_review.empty', { defaultValue: 'Nothing here.' })}
    </p>
  );
  const truncatedNote = (shown: number) => (
    <p className="pt-2 text-2xs text-content-tertiary">
      {t('boq.excel_review.truncated', { defaultValue: 'The first {{shown}} rows are listed.', shown })}
    </p>
  );

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-lg"
      role="dialog"
      aria-modal="true"
      aria-label={t('boq.excel_review.title', { defaultValue: 'Review changes from Excel' })}
    >
      <div className="relative mx-4 flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border-light bg-surface-elevated shadow-xl">
        <div className="flex items-center justify-between border-b border-border-light px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-content-primary">
              {t('boq.excel_review.title', { defaultValue: 'Review changes from Excel' })}
            </h2>
            <p className="text-2xs text-content-tertiary">
              {t('boq.excel_review.subtitle', {
                defaultValue: 'Nothing is written until you apply.',
              })}
              {preview.unchanged > 0 &&
                ` ${t('boq.excel_review.unchanged', { defaultValue: 'Unchanged rows: {{rows}}', rows: preview.unchanged })}`}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={15} />
          </button>
        </div>

        <div role="tablist" className="flex gap-1 border-b border-border-light px-5 pt-2">
          {tabs.map(({ id, count }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={`rounded-t-lg px-3 py-1.5 text-xs transition-colors ${
                tab === id
                  ? 'border-b-2 border-oe-blue font-medium text-content-primary'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              {tabLabel(t, id, count)}
            </button>
          ))}
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-5">
          {tab === 'changed' &&
            (preview.updated.length === 0 ? (
              empty
            ) : (
              <>
                <ul className="space-y-3">
                  {preview.updated.map((row) => (
                    <li key={row.position_id} className="rounded-lg border border-border-light p-2">
                      <label className="flex items-start gap-2 text-xs">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={!state.unticked.has(row.position_id)}
                          onChange={() => setState((s) => ({ ...s, unticked: toggled(s.unticked, row.position_id) }))}
                          aria-label={`${t('boq.excel_review.apply_row', { defaultValue: 'Apply this change' })} ${row.ordinal}`}
                        />
                        <span className="flex-1">
                          <ChangeTable rows={[row]} />
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
                {preview.truncated.updated && truncatedNote(preview.updated.length)}
              </>
            ))}

          {tab === 'new' &&
            (preview.created.length === 0 ? (
              empty
            ) : (
              <>
                <p className="text-xs text-content-secondary">
                  {t('boq.excel_review.new_hint', {
                    defaultValue: 'These rows have no Position ID in the file and are added to the bill.',
                  })}
                </p>
                <ul className="divide-y divide-border-light text-xs">
                  {preview.created.map((row) => (
                    <li key={row.row} className="flex gap-3 py-1.5">
                      <span className="w-20 shrink-0 tabular-nums text-content-secondary">{row.ordinal}</span>
                      <span className="text-content-primary">{row.description}</span>
                    </li>
                  ))}
                </ul>
                {preview.truncated.created && truncatedNote(preview.created.length)}
              </>
            ))}

          {tab === 'removed' &&
            (preview.would_delete.length === 0 ? (
              empty
            ) : (
              <>
                <p className="text-xs text-content-secondary">
                  {t('boq.excel_review.removed_hint', {
                    defaultValue: 'These positions are in the bill but not in the file. They stay unless you tick them.',
                  })}
                </p>
                <ul className="divide-y divide-border-light text-xs">
                  {preview.would_delete.map((row) => (
                    <li key={row.position_id} className="py-1.5">
                      <label className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={state.deleting.has(row.position_id)}
                          onChange={() => setState((s) => ({ ...s, deleting: toggled(s.deleting, row.position_id) }))}
                        />
                        <span className="w-20 shrink-0 tabular-nums text-content-secondary">{row.ordinal}</span>
                        <span className="flex-1 text-content-primary">{row.description}</span>
                        <span className="text-content-tertiary">
                          {t('boq.excel_review.delete_from_boq', { defaultValue: 'Delete from BOQ' })}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
                {preview.truncated.would_delete && truncatedNote(preview.would_delete.length)}
              </>
            ))}

          {tab === 'conflicts' &&
            (preview.conflicts.length === 0 ? (
              empty
            ) : (
              <>
                <ul className="space-y-3">
                  {preview.conflicts.map((row) => {
                    const choice: ConflictChoice = state.conflictChoice[row.position_id] ?? 'app';
                    const name = `conflict-${row.position_id}`;
                    const pick = (next: ConflictChoice) =>
                      setState((s) => ({ ...s, conflictChoice: { ...s.conflictChoice, [row.position_id]: next } }));
                    return (
                      <li key={row.position_id} className="rounded-lg border border-semantic-warning/40 p-2">
                        <p className="mb-1 text-2xs font-medium text-semantic-warning">
                          {t('boq.excel_review.conflict_note', { defaultValue: 'Changed in the app since export' })}
                          {' · '}
                          {t('boq.excel_review.conflict_versions', {
                            defaultValue: 'Version in the app: {{stored}}, in the file: {{file}}',
                            stored: row.stored_version,
                            file: row.file_version ?? '-',
                          })}
                        </p>
                        <ChangeTable rows={[row]} />
                        <div className="mt-2 flex gap-4 text-xs">
                          <label className="flex items-center gap-1.5">
                            <input
                              type="radio"
                              name={name}
                              checked={choice === 'app'}
                              onChange={() => pick('app')}
                            />
                            {t('boq.excel_review.keep_app', { defaultValue: 'Keep app value' })}
                          </label>
                          <label className="flex items-center gap-1.5">
                            <input
                              type="radio"
                              name={name}
                              checked={choice === 'excel'}
                              onChange={() => pick('excel')}
                            />
                            {t('boq.excel_review.use_excel', { defaultValue: 'Use Excel value' })}
                          </label>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {preview.truncated.conflicts && truncatedNote(preview.conflicts.length)}
              </>
            ))}

          {preview.errors.length > 0 && (
            <div className="rounded-lg border border-semantic-error/40 p-2 text-xs text-semantic-error">
              <p className="font-medium">
                {t('boq.excel_review.errors_title', { defaultValue: 'Rows that cannot be read' })}
              </p>
              <ul className="mt-1 space-y-0.5">
                {preview.errors.slice(0, 20).map((e, i) => (
                  <li key={i}>
                    {e.row != null ? `${e.row}: ` : ''}
                    {e.error}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {preview.problems.length > 0 && (
            <div className="rounded-lg border border-border-light p-2 text-xs text-content-secondary">
              <p className="font-medium">{t('boq.excel_review.notes_title', { defaultValue: 'Notes' })}</p>
              <ul className="mt-1 space-y-0.5">
                {preview.problems.slice(0, 20).map((p, i) => (
                  <li key={i}>
                    {p.row != null ? `${p.row}: ` : ''}
                    {p.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-border-light px-5 py-3">
          <div className="flex-1" />
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg px-3 py-1.5 text-xs text-content-secondary transition-colors hover:bg-surface-secondary"
          >
            {t('boq.excel_review.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => onApply(buildChoices(preview, state))}
            disabled={applying || total === 0}
            className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-oe-blue/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {applying && <Loader2 size={12} className="animate-spin" />}
            {t('boq.excel_review.apply', { defaultValue: 'Apply changes ({{total}})', total })}
          </button>
        </div>
      </div>
    </div>
  );
}
