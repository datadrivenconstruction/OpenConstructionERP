// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The commitment matrix: one row per thing the project will commit money to,
// with what is planned, what was released, what the linked documents bind,
// who has to approve and by when. A row opens the item.
//
// Item amounts are in the schedule currency; the totals row is in the
// project currency and says so, and says when a total leaves something out.

import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CalendarClock, Clock, HelpCircle, ListChecks } from 'lucide-react';
import clsx from 'clsx';

import { KpiBand } from '@/shared/ui/KpiBand';
import { fmtDate } from '@/shared/lib/formatters';

import type { CommitmentItem, CommitmentMatrix, ItemTotals } from './api';
import { Amount, ITEM_STATUS_TONE, ToneBadge } from './CommitmentBits';
import { EXPOSURE_REASON, ITEM_STATUS, codeName, humanizeCode, vocab, type KeyText, type LabelContext } from './labels';
import { groupItems, matrixCounts, nothingCommitted, releasedInForce, releasedLapsed, type GroupBy } from './rules';

const GROUPINGS: GroupBy[] = ['none', 'type', 'gate'];

export const GROUP_BY: Record<GroupBy, KeyText> = {
  none: ['commitment.grid.group_none', 'No grouping'],
  type: ['commitment.grid.group_by_type', 'Group by type'],
  gate: ['commitment.grid.group_by_gate', 'Group by gate'],
};

/** Which of the totals left an item out, as the words of its column. */
const TOTAL_COLUMN: Record<string, KeyText> = {
  planned: ['commitment.grid.planned', 'Planned'],
  released: ['commitment.grid.released', 'Released'],
  committed: ['commitment.grid.committed', 'Committed'],
};

export interface CommitmentGridProps {
  items: CommitmentItem[];
  totals: ItemTotals;
  matrix: CommitmentMatrix;
  labels: LabelContext;
  onOpenItem: (itemId: string) => void;
}

export function CommitmentGrid({ items, totals, matrix, labels, onOpenItem }: CommitmentGridProps) {
  const { t } = useTranslation();
  const [groupBy, setGroupBy] = useState<GroupBy>('none');
  const groups = groupItems(items, groupBy);
  const counts = matrixCounts(items);
  const tierName = (code: string | null) =>
    !code
      ? ''
      : code === 'escalate_outside'
        ? t('commitment.schedule.escalate_outside', { defaultValue: 'Consent outside the schedule' })
        : codeName(labels, 'tier', code, matrix.tiers.find((x) => x.code === code)?.name);
  const typeName = (code: string) =>
    codeName(labels, 'type', code, matrix.commitment_types.find((x) => x.code === code)?.name);
  const groupTitle = (key: string) =>
    groupBy === 'type'
      ? typeName(key)
      : key
        ? humanizeCode(key)
        : t('commitment.grid.no_gate', { defaultValue: 'Not tied to a gate' });
  // The released column shows the sum in force, so it is incomplete when either released total is.
  const left = new Set(totals.incomplete.map((k) => (k === 'released_in_force' ? 'released' : k)));
  const incomplete = Object.keys(TOTAL_COLUMN).filter((k) => left.has(k));

  return (
    <div className="space-y-4" data-testid="commitment-grid">
      <KpiBand
        columns={4}
        size="sm"
        items={[
          {
            key: 'waiting',
            label: t('commitment.kpi.waiting', { defaultValue: 'Waiting for a decision' }),
            value: counts.waitingForDecision,
            icon: Clock,
          },
          {
            key: 'overdue',
            label: t('commitment.kpi.overdue', { defaultValue: 'Decision overdue' }),
            value: counts.decisionOverdue,
            icon: CalendarClock,
            tone: counts.decisionOverdue > 0 ? 'danger' : undefined,
            tintValue: counts.decisionOverdue > 0,
          },
          {
            key: 'over',
            label: t('commitment.kpi.over_release', { defaultValue: 'Bound above the release' }),
            value: counts.overRelease,
            icon: AlertTriangle,
            tone: counts.overRelease > 0 ? 'danger' : undefined,
            tintValue: counts.overRelease > 0,
          },
          {
            key: 'unknown',
            label: t('commitment.kpi.unknown_terms', { defaultValue: 'Abort cost unknown' }),
            value: counts.unknownExposure,
            icon: HelpCircle,
            tone: counts.unknownExposure > 0 ? 'warning' : undefined,
          },
        ]}
      />

      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('commitment.grid.grouping', { defaultValue: 'Group the items' })}>
        {GROUPINGS.map((g) => (
          <button
            key={g}
            type="button"
            aria-pressed={groupBy === g}
            onClick={() => setGroupBy(g)}
            className={clsx(
              'rounded-full border px-3 py-1 text-xs',
              groupBy === g ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary',
            )}
          >
            {t(GROUP_BY[g][0], { defaultValue: GROUP_BY[g][1] })}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[60rem] text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary text-left text-xs text-content-tertiary">
              <th scope="col" className="px-3 py-2 font-medium">{t('commitment.grid.item', { defaultValue: 'Item' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.grid.planned', { defaultValue: 'Planned' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.grid.released', { defaultValue: 'Released' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.grid.committed', { defaultValue: 'Committed' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('commitment.grid.required_tier', { defaultValue: 'Required tier' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('commitment.grid.latest_decision_date', { defaultValue: 'Latest decision date' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('commitment.grid.residual_loss', { defaultValue: 'Residual loss' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('commitment.export.col_status', { defaultValue: 'Status' })}</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <Fragment key={group.key || 'all'}>
                {groupBy !== 'none' && (
                  <tr className="border-b border-border-light bg-surface-secondary/60" data-testid="grid-group">
                    <th scope="colgroup" colSpan={8} className="px-3 py-1.5 text-left text-xs font-semibold text-content-secondary">
                      {groupTitle(group.key)}
                    </th>
                  </tr>
                )}
                {group.items.map((item) => (
                  <tr
                    key={item.id}
                    data-testid="grid-row"
                    className="cursor-pointer border-b border-border-light/60 align-top hover:bg-surface-secondary/60"
                    onClick={() => onOpenItem(item.id)}
                  >
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="text-left font-medium text-content-primary hover:text-oe-blue focus:outline-none focus-visible:underline"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenItem(item.id);
                        }}
                      >
                        {item.title}
                      </button>
                      <p className="flex flex-wrap gap-x-2 text-xs text-content-tertiary">
                        <span className="font-mono">{item.code}</span>
                        <span>{typeName(item.commitment_type)}</span>
                        {item.open_preconditions > 0 && (
                          <span className="inline-flex items-center gap-1 text-semantic-warning" data-testid="grid-open-preconditions">
                            <ListChecks size={12} aria-hidden />
                            {t('commitment.grid.open_preconditions', {
                              defaultValue: '{{count}} preconditions open',
                              count: item.open_preconditions,
                            })}
                          </span>
                        )}
                      </p>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      <Amount value={item.planned.amount} currency={item.planned.currency} />
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      <Amount value={releasedInForce(item)} currency={item.schedule_currency} />
                      {releasedLapsed(item) && (
                        <p className="text-xs font-normal text-content-tertiary" data-testid="grid-released-lapsed">
                          {t('commitment.released_lapsed', { defaultValue: 'Lapsed, no longer available' })} <Amount value={releasedLapsed(item)} currency={item.schedule_currency} />
                        </p>
                      )}
                      {item.release_expired && (
                        <p className="text-xs font-normal text-semantic-warning" data-testid="grid-release-expired">
                          {t('commitment.grid.release_expired', { defaultValue: 'Release expired' })}
                        </p>
                      )}
                    </td>
                    <td className={clsx('px-3 py-2 text-right tabular-nums', item.over_release && 'font-semibold text-semantic-error')}>
                      <Amount value={item.committed} currency={item.schedule_currency} />
                    </td>
                    <td className="px-3 py-2 text-content-secondary">{tierName(item.required_tier_for_planned)}</td>
                    <td className="px-3 py-2">
                      {item.latest_decision_date ? (
                        <span className={clsx(item.decision_overdue ? 'font-medium text-semantic-error' : 'text-content-secondary')}>
                          {fmtDate(item.latest_decision_date)}
                        </span>
                      ) : (
                        <span className="text-content-tertiary">{t('commitment.item.no_date', { defaultValue: 'Not set' })}</span>
                      )}
                      {item.decision_overdue && (
                        <p className="text-xs font-medium text-semantic-error" data-testid="grid-overdue">
                          {t('commitment.grid.overdue', { defaultValue: 'Overdue' })}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums" data-testid="grid-residual">
                      {item.exposure && nothingCommitted(item.exposure) ? (
                        <span className="text-content-tertiary">
                          {t('commitment.grid.nothing_committed', { defaultValue: 'Nothing committed' })}
                        </span>
                      ) : (
                        <Amount
                          value={item.exposure?.residual_loss}
                          currency={item.exposure?.currency ?? totals.currency}
                          unknownLabel={
                            item.exposure?.reason
                              ? vocab(t, EXPOSURE_REASON, item.exposure.reason)
                              : undefined
                          }
                        />
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <ToneBadge tone={ITEM_STATUS_TONE[item.status] ?? 'neutral'} testId="grid-status">
                        {vocab(t, ITEM_STATUS, item.status)}
                      </ToneBadge>
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-surface-secondary font-semibold text-content-primary" data-testid="grid-totals">
              <th scope="row" className="px-3 py-2 text-left">
                {t('commitment.grid.totals', { defaultValue: 'Totals in {{currency}}', currency: totals.currency })}
                {totals.mixed_currency && (
                  <p className="text-xs font-normal text-content-tertiary" data-testid="grid-mixed-currency">
                    {t('commitment.grid.mixed_currency', { defaultValue: 'Converted from several currencies' })}
                  </p>
                )}
              </th>
              <td className="px-3 py-2 text-right tabular-nums">
                <Amount value={totals.planned} currency={totals.currency} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                <Amount value={releasedInForce(totals)} currency={totals.currency} />
                {releasedLapsed(totals) && (
                  <p className="text-xs font-normal text-content-tertiary" data-testid="grid-totals-lapsed">
                    {t('commitment.released_lapsed', { defaultValue: 'Lapsed, no longer available' })} <Amount value={releasedLapsed(totals)} currency={totals.currency} />
                  </p>
                )}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                <Amount value={totals.committed} currency={totals.currency} />
              </td>
              <td colSpan={4} className="px-3 py-2 text-xs font-normal text-content-tertiary">
                {incomplete.length > 0 && (
                  <ul data-testid="grid-totals-incomplete">
                    {incomplete.map((k) => (
                      <li key={k}>
                        {t('commitment.grid.total_incomplete', {
                          defaultValue: '{{column}} leaves out an item that has no amount or no exchange rate.',
                          column: t(TOTAL_COLUMN[k]![0], { defaultValue: TOTAL_COLUMN[k]![1] }),
                        })}
                      </li>
                    ))}
                  </ul>
                )}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
