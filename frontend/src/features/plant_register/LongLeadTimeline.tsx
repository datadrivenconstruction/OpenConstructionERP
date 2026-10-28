// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The long-lead items on one time axis, the tightest first. Each bar runs
// from the latest day the order can be placed to the day the plant is needed
// on site; the vertical line is today. A bar that starts left of the line is
// an order that is already late.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { CalendarClock } from 'lucide-react';
import clsx from 'clsx';

import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';

import type { PlantCatalogue, PlantItem } from './api';
import { ORDER_STATUS, vocab, type LabelContext } from './labels';
import { LeadChip, ToneBadge } from './PlantBits';
import { ORDER_TONE, buildTimeline, orderDateOpen } from './rules';

export interface LongLeadTimelineProps {
  /** Every item of the project; the long-lead ones are picked here. */
  items: PlantItem[];
  catalogue: PlantCatalogue;
  labels: LabelContext;
  today: string;
  onOpen: (itemId: string) => void;
}

/** Long-lead items that are still live, least float first; items without a float go last. */
export function longLeadOrder(items: PlantItem[]): PlantItem[] {
  return items
    .filter((i) => i.long_lead && i.status !== 'cancelled')
    .sort((a, b) => {
      if (a.float_days === null) return b.float_days === null ? 0 : 1;
      if (b.float_days === null) return -1;
      return a.float_days - b.float_days;
    });
}

export function LongLeadTimeline({ items, catalogue, labels, today, onOpen }: LongLeadTimelineProps) {
  const { t } = useTranslation();
  const timeline = useMemo(() => buildTimeline(longLeadOrder(items), today), [items, today]);

  if (timeline.rows.length === 0) {
    return (
      <EmptyState
        icon={<CalendarClock size={28} />}
        title={t('plant.timeline.empty_title', { defaultValue: 'No long-lead items' })}
        description={t('plant.timeline.empty_body', {
          defaultValue:
            'An item appears here once its lead time reaches {{weeks}} weeks. Add lead times to the items in the register to see which ones have to be ordered early.',
          weeks: catalogue.long_lead_threshold_weeks,
        })}
      />
    );
  }

  return (
    <div className="space-y-3" data-testid="plant-timeline">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-content-secondary">
        <span>
          {t('plant.timeline.legend', {
            defaultValue: 'Each bar runs from the latest order date to the need date. The line is today.',
          })}
        </span>
        <span>
          {t('plant.common.date_range', {
            defaultValue: '{{from}} to {{to}}',
            from: fmtDate(timeline.start),
            to: fmtDate(timeline.end),
          })}
        </span>
      </div>
      <ul className="space-y-2">
        {timeline.rows.map(({ item, orderAt, needAt }) => {
          const open = orderDateOpen(item);
          const late = open && item.order_status === 'overdue';
          return (
            <li key={item.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="timeline-row">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <button type="button" className="font-mono text-sm text-oe-blue-text hover:underline" onClick={() => onOpen(item.id)}>
                  {item.code}
                </button>
                <span className="min-w-0 flex-1 truncate text-sm text-content-primary">{item.title}</span>
                {open && item.latest_order_date && (
                  <ToneBadge tone={ORDER_TONE[item.order_status]}>{vocab(t, ORDER_STATUS, item.order_status)}</ToneBadge>
                )}
                {item.float_days !== null && (
                  <span className={clsx('text-xs tabular-nums', item.float_days < 0 ? 'font-semibold text-semantic-error' : 'text-content-secondary')}>
                    {t('plant.timeline.float', { defaultValue: 'Float {{days}} days', days: fmtNumber(item.float_days, 0) })}
                  </span>
                )}
              </div>
              <div className="relative mt-2 h-3 rounded-full bg-surface-secondary" aria-hidden>
                {orderAt !== null && needAt !== null && (
                  <span
                    data-testid="timeline-bar"
                    className={clsx('absolute inset-y-0 rounded-full', late ? 'bg-semantic-error' : 'bg-oe-blue')}
                    style={{ insetInlineStart: `${orderAt}%`, width: `${Math.max(needAt - orderAt, 1)}%` }}
                  />
                )}
                <span
                  className="absolute -inset-y-1 w-px bg-content-primary"
                  style={{ insetInlineStart: `${timeline.todayAt}%` }}
                />
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-content-secondary">
                <LeadChip item={item} catalogue={catalogue} labels={labels} />
                {item.latest_order_date && item.need_date ? (
                  <span>
                    {t('plant.timeline.dates', {
                      defaultValue: 'Order by {{order}}, needed {{need}}',
                      order: fmtDate(item.latest_order_date),
                      need: fmtDate(item.need_date),
                    })}
                  </span>
                ) : (
                  <span className="text-semantic-error">
                    {t('plant.timeline.no_need_date', {
                      defaultValue: 'No need date yet, so no order date can be worked out.',
                    })}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
