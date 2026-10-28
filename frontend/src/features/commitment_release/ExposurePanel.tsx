// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "What would it cost to stop on this date?" One row per item: what is
// already spent, what is committed and not yet spent, the cancellation charge
// and what can be recovered. The answer is the residual loss.
//
// An item without abort terms has no residual loss to show. It reads
// "unknown", it is left out of the total, and the total says how many items
// it leaves out.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Save, ShieldQuestion } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate } from '@/shared/lib/formatters';

import { localToday, saveScenario, type CommitmentItem, type ExposureRow, type ProjectCan } from './api';
import { projectVerdict } from './access';
import { Amount, FIELD_CLASS, ITEM_STATUS_TONE, ReasonedButton, RefusalBox, ToneBadge, refusalText } from './CommitmentBits';
import { useExposure, useScenarios } from './hooks';
import { EXPOSURE_REASON, ITEM_STATUS, vocab } from './labels';
import { nothingCommitted } from './rules';

/**
 * How many rows have a residual loss and how many read "unknown". A row with
 * nothing committed is neither: there is nothing to lose on it yet.
 */
export function exposureCounts(rows: ReadonlyArray<Pick<ExposureRow, 'residual_loss' | 'note' | 'lines'>>): {
  known: number;
  unknown: number;
} {
  let known = 0;
  let unknown = 0;
  for (const row of rows) {
    if (row.residual_loss != null) known += 1;
    else if (!nothingCommitted(row)) unknown += 1;
  }
  return { known, unknown };
}

export interface ExposurePanelProps {
  projectId: string;
  /** The matrix items, for the title behind each code. */
  items: CommitmentItem[];
  /** The project capabilities the server sent; undefined while they load. */
  can: ProjectCan | null | undefined;
  onOpenItem: (itemId: string) => void;
}

export function ExposurePanel({ projectId, items, can, onOpenItem }: ExposurePanelProps) {
  const { t } = useTranslation();
  const [asOf, setAsOf] = useState(localToday());
  const [saving, setSaving] = useState(false);
  const [label, setLabel] = useState('');
  const exposureQ = useExposure(projectId, asOf);
  const scenariosQ = useScenarios(projectId);
  const titles = new Map(items.map((i) => [i.id, i.title]));
  const saveV = projectVerdict(can, 'save_scenario');

  const save = useMutation({
    mutationFn: () => saveScenario(projectId, { as_of: asOf, label: label.trim() }),
    onSuccess: () => {
      setSaving(false);
      setLabel('');
      scenariosQ.refetch();
    },
  });

  const data = exposureQ.data;
  // The server counts an item with nothing committed and no abort terms as
  // unknown. Stopping it costs nothing, and its row says so, so the warning
  // under the total counts only the rows that really read "unknown".
  const { unknown, known } = exposureCounts(data?.items ?? []);
  const scenarios = scenariosQ.data ?? [];

  return (
    <div className="space-y-5" data-testid="exposure-panel">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="exposure-as-of" className="mb-1 block text-sm font-medium text-content-primary">
            {t('commitment.exposure.as_of', { defaultValue: 'If the project stopped on' })}
          </label>
          <input
            id="exposure-as-of"
            type="date"
            className={FIELD_CLASS}
            value={asOf}
            onChange={(e) => setAsOf(e.target.value || localToday())}
          />
        </div>
        {!saving && (
          <ReasonedButton
            variant="secondary"
            icon={<Save size={14} />}
            verdict={saveV}
            disabled={!data || data.items.length === 0}
            onClick={() => {
              save.reset();
              setSaving(true);
            }}
            data-testid="scenario-start"
          >
            {t('commitment.exposure.save_scenario', { defaultValue: 'Save this view' })}
          </ReasonedButton>
        )}
      </div>

      {saving && (
        <div className="space-y-2 rounded-lg bg-surface-secondary p-3" data-testid="scenario-form">
          {save.isError && <RefusalBox message={refusalText(t, save.error)} />}
          <label htmlFor="scenario-label" className="block text-sm font-medium text-content-primary">
            {t('commitment.exposure.scenario_label', { defaultValue: 'Name for this view' })}
          </label>
          <input
            id="scenario-label"
            className={FIELD_CLASS}
            placeholder={t('commitment.exposure.scenario_placeholder', {
              defaultValue: 'For example: stop before the facade order',
            })}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <div className="flex gap-2">
            <Button size="sm" loading={save.isPending} onClick={() => save.mutate()} data-testid="scenario-save">
              {t('commitment.exposure.save_scenario', { defaultValue: 'Save this view' })}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSaving(false)}>
              {t('commitment.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}

      {exposureQ.isLoading ? (
        <SkeletonTable rows={4} columns={6} />
      ) : exposureQ.isError ? (
        <ErrorState
          title={t('commitment.exposure.load_failed', { defaultValue: 'The abort exposure could not be loaded' })}
          hint={getErrorMessage(exposureQ.error)}
          onRetry={() => exposureQ.refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={<ShieldQuestion size={28} />}
          title={t('commitment.exposure.empty_title', { defaultValue: 'Nothing to stop yet' })}
          description={t('commitment.exposure.empty_body', {
            defaultValue: 'Add commitment items first. Each one then shows here what stopping it would cost, once its abort terms are entered.',
          })}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
          <table className="w-full min-w-[56rem] text-sm" data-testid="exposure-table">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary text-left text-xs text-content-tertiary">
                <th scope="col" className="px-3 py-2 font-medium">{t('commitment.grid.item', { defaultValue: 'Item' })}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.exposure.sunk', { defaultValue: 'Already spent' })}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.exposure.committed_not_spent', { defaultValue: 'Committed, not yet spent' })}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.exposure.cancellation_charge', { defaultValue: 'Cancellation charge' })}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.exposure.recoverable', { defaultValue: 'Recoverable (transfer and salvage)' })}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.exposure.residual_loss', { defaultValue: 'Residual loss' })}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => {
                const nothing = nothingCommitted(row);
                return (
                  <tr key={row.item_id} className="border-b border-border-light/60 align-top" data-testid="exposure-row">
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="text-left font-medium text-content-primary hover:text-oe-blue focus:outline-none focus-visible:underline"
                        onClick={() => onOpenItem(row.item_id)}
                      >
                        {titles.get(row.item_id) ?? row.code}
                      </button>
                      <p className="flex flex-wrap items-center gap-x-2 text-xs text-content-tertiary">
                        <span className="font-mono">{row.code}</span>
                        <ToneBadge tone={ITEM_STATUS_TONE[row.status] ?? 'neutral'}>{vocab(t, ITEM_STATUS, row.status)}</ToneBadge>
                      </p>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums"><Amount value={row.sunk} currency={row.currency} /></td>
                    <td className="px-3 py-2 text-right tabular-nums"><Amount value={row.committed_not_spent} currency={row.currency} /></td>
                    <td className="px-3 py-2 text-right tabular-nums"><Amount value={row.cancellation_charge} currency={row.currency} /></td>
                    <td className="px-3 py-2 text-right tabular-nums"><Amount value={row.recoverable} currency={row.currency} /></td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums" data-testid="exposure-row-residual">
                      {nothing ? (
                        <span className="font-normal text-content-tertiary">
                          {t('commitment.grid.nothing_committed', { defaultValue: 'Nothing committed' })}
                        </span>
                      ) : (
                        <Amount
                          value={row.residual_loss}
                          currency={row.currency}
                          unknownLabel={
                            row.reason
                              ? vocab(t, EXPOSURE_REASON, row.reason)
                              : t('commitment.exposure.incomplete', { defaultValue: 'Unknown: a contract figure is missing' })
                          }
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="bg-surface-secondary font-semibold text-content-primary">
                <th scope="row" colSpan={5} className="px-3 py-2 text-left">
                  {t('commitment.exposure.total', {
                    defaultValue: 'Residual loss of the items with known terms, {{date}}',
                    date: fmtDate(data.as_of),
                  })}
                  {unknown > 0 && (
                    <p className="text-xs font-normal text-semantic-warning" data-testid="exposure-unknown-count">
                      {t('commitment.grid.unknown_residual', {
                        defaultValue: '{{count}} items with unknown terms',
                        count: unknown,
                      })}
                    </p>
                  )}
                </th>
                <td className="px-3 py-2 text-right tabular-nums" data-testid="exposure-total">
                  <Amount value={unknown > 0 && known === 0 ? null : data.total_residual_loss} currency={data.currency} />
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <p className="text-xs text-content-tertiary">
        {t('commitment.exposure.delay_note', {
          defaultValue: 'The cost of the delay itself is not in these figures. No figure is assumed for it.',
        })}
      </p>

      <section data-testid="scenarios">
        <h3 className="mb-2 text-sm font-semibold text-content-primary">
          {t('commitment.exposure.scenarios', { defaultValue: 'Saved views' })}
        </h3>
        {scenariosQ.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('commitment.loading', { defaultValue: 'Loading' })}</p>
        ) : scenariosQ.isError ? (
          <ErrorState
            compact
            title={t('commitment.exposure.scenarios_failed', { defaultValue: 'The saved views could not be loaded' })}
            hint={getErrorMessage(scenariosQ.error)}
            onRetry={() => scenariosQ.refetch()}
          />
        ) : scenarios.length === 0 ? (
          <p className="text-sm text-content-tertiary" data-testid="scenarios-empty">
            {t('commitment.exposure.scenarios_empty', {
              defaultValue: 'No view is saved yet. Pick a date above and save the view to compare it later.',
            })}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {scenarios.map((s) => {
              const counts = exposureCounts(s.payload?.items ?? []);
              return (
                <li
                  key={s.id}
                  data-testid="scenario-row"
                  className="flex flex-wrap items-baseline justify-between gap-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-2.5 text-sm"
                >
                  <span className="text-content-primary">
                    {s.label || t('commitment.exposure.scenario_unnamed', { defaultValue: 'Unnamed view' })}
                  </span>
                  <span className="flex flex-wrap items-baseline gap-x-3 text-content-secondary">
                    <span>{fmtDate(s.as_of)}</span>
                    <span className="font-medium tabular-nums text-content-primary">
                      <Amount
                        value={counts.unknown > 0 && counts.known === 0 ? null : s.payload?.total_residual_loss}
                        currency={s.payload?.currency ?? ''}
                      />
                    </span>
                    {counts.unknown > 0 && (
                      <span className="text-xs text-semantic-warning">
                        {t('commitment.grid.unknown_residual', {
                          defaultValue: '{{count}} items with unknown terms',
                          count: counts.unknown,
                        })}
                      </span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
