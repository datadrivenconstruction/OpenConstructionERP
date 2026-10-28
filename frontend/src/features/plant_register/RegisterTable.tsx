// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The register: every plant item on one line, with the three facts that
// decide whether it is in trouble (where the lead time comes from, when it
// must be ordered, how much float is left). The filter chips narrow it to the
// long-lead, the critical or the overdue ones.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import { Badge } from '@/shared/ui/Badge';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';

import type { PlantCatalogue, PlantItem } from './api';
import { ITEM_STATE, ORDER_STATUS, catalogueName, vocab, type KeyText, type LabelContext } from './labels';
import { ITEM_STATE_TONE, LeadChip, ToneBadge } from './PlantBits';
import { ORDER_TONE, filterCounts, filterItems, orderDateOpen, type RegisterFilter } from './rules';

const FILTERS: RegisterFilter[] = ['all', 'long_lead', 'critical', 'overdue'];

export const REGISTER_FILTER: Record<RegisterFilter, KeyText> = {
  all: ['plant.register.filter.all', 'All'],
  long_lead: ['plant.register.filter.long_lead', 'Long-lead'],
  critical: ['plant.register.filter.critical', 'Critical'],
  overdue: ['plant.register.filter.overdue', 'Order overdue'],
};

export interface RegisterTableProps {
  items: PlantItem[];
  /** How many items the project has; more than `items.length` when the list was cut. */
  total: number;
  catalogue: PlantCatalogue;
  labels: LabelContext;
  onOpen: (itemId: string) => void;
}

export function RegisterTable({ items, total, catalogue, labels, onOpen }: RegisterTableProps) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<RegisterFilter>('all');
  const counts = useMemo(() => filterCounts(items), [items]);
  const shown = useMemo(() => filterItems(items, filter), [items, filter]);
  const dash = t('plant.common.none', { defaultValue: 'Not set' });

  return (
    <div className="space-y-3" data-testid="plant-register">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('plant.register.filter_label', { defaultValue: 'Filter the register' })}>
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={filter === f}
            data-testid={`register-filter-${f}`}
            onClick={() => setFilter(f)}
            className={clsx(
              'rounded-full border px-3 py-1 text-xs',
              filter === f ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary',
            )}
          >
            {vocab(t, REGISTER_FILTER, f)} <span className="text-content-tertiary">{counts[f]}</span>
          </button>
        ))}
      </div>

      {total > items.length && (
        <p role="status" className="text-xs text-content-secondary">
          {t('plant.register.truncated', {
            defaultValue: 'Showing the first {{shown}} of {{total}} items.',
            shown: items.length,
            total,
          })}
        </p>
      )}

      {shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-content-tertiary" data-testid="register-none">
          {t('plant.register.none_in_filter', { defaultValue: 'No item matches this filter.' })}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
          <table className="w-full min-w-[56rem] text-left text-sm">
            <thead className="bg-surface-secondary text-xs text-content-secondary">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">{t('plant.field.code', { defaultValue: 'Code' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('plant.field.title', { defaultValue: 'Title' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('plant.field.state', { defaultValue: 'State' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('plant.field.lead_weeks', { defaultValue: 'Lead time (weeks)' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('plant.field.need_date', { defaultValue: 'Need date' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('plant.field.latest_order_date', { defaultValue: 'Latest order date' })}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">{t('plant.field.float_days', { defaultValue: 'Float (days)' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('plant.field.route', { defaultValue: 'Procurement route' })}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {shown.map((item) => (
                <tr
                  key={item.id}
                  data-testid="register-row"
                  className="cursor-pointer hover:bg-surface-secondary"
                  onClick={() => onOpen(item.id)}
                >
                  <td className="px-3 py-2 align-top">
                    <button
                      type="button"
                      className="font-mono text-oe-blue-text hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpen(item.id);
                      }}
                    >
                      {item.code}
                    </button>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <span className="text-content-primary">{item.title}</span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-content-tertiary">
                      {catalogueName(labels, catalogue, 'component_classes', item.component_class_code)}
                      {item.critical && (
                        <Badge variant="error" size="sm">
                          {t('plant.field.critical', { defaultValue: 'Critical' })}
                        </Badge>
                      )}
                      {item.long_lead && (
                        <Badge variant="warning" size="sm">
                          {t('plant.item.long_lead', { defaultValue: 'Long-lead' })}
                        </Badge>
                      )}
                    </span>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <ToneBadge tone={ITEM_STATE_TONE[item.status]}>{vocab(t, ITEM_STATE, item.status)}</ToneBadge>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <LeadChip item={item} catalogue={catalogue} labels={labels} />
                  </td>
                  <td className="px-3 py-2 align-top text-content-secondary">{item.need_date ? fmtDate(item.need_date) : dash}</td>
                  <td className="px-3 py-2 align-top text-content-secondary">
                    {item.latest_order_date ? fmtDate(item.latest_order_date) : dash}
                    {orderDateOpen(item) && item.latest_order_date && item.order_status !== 'ok' && (
                      <span className="mt-0.5 block">
                        <ToneBadge tone={ORDER_TONE[item.order_status]}>{vocab(t, ORDER_STATUS, item.order_status)}</ToneBadge>
                      </span>
                    )}
                  </td>
                  <td
                    className={clsx(
                      'px-3 py-2 text-right align-top tabular-nums',
                      item.float_days !== null && item.float_days < 0 ? 'font-semibold text-semantic-error' : 'text-content-secondary',
                    )}
                  >
                    {item.float_days === null ? dash : fmtNumber(item.float_days, 0)}
                  </td>
                  <td className="px-3 py-2 align-top text-content-secondary">
                    {item.procurement_route ? catalogueName(labels, catalogue, 'procurement_routes', item.procurement_route) : dash}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
