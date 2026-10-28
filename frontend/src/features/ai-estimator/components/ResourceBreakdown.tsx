// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Expandable resource sub-rows for a chosen rate. The breakdown comes
// straight from the cost DB (CostItem.components scaled by factor x qty);
// it is never fabricated by the AI. Rendered inside the match card and
// the assembly preview. Accepts either the group `ResourceOut` shape or
// the preview `PreviewResourceRow` shape (normalised below).

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import type { ResourceOut, PreviewResourceRow } from '../api';
import { fmtMoneyStr, resourceTypeBadge } from '../helpers';
import { fmtFixed } from '@/shared/lib/formatters';

interface NormalisedRow {
  name: string;
  code: string | null;
  type: string;
  quantity: number;
  unit: string;
  unit_rate: string;
  /** Line cost = quantity * unit_rate, computed when absent. */
  cost: string;
}

function normalise(r: ResourceOut | PreviewResourceRow): NormalisedRow {
  const name = 'name' in r ? r.name : r.description;
  const code = 'code' in r ? r.code : null;
  const cost = fmtFixed(r.quantity * Number(r.unit_rate || 0), 2);
  return {
    name,
    code,
    type: r.type,
    quantity: r.quantity,
    unit: r.unit,
    unit_rate: r.unit_rate,
    cost,
  };
}

export function ResourceBreakdown({
  resources,
  currency,
  locale,
  className,
}: {
  resources: (ResourceOut | PreviewResourceRow)[];
  currency: string | null | undefined;
  locale?: string;
  className?: string;
}) {
  const { t } = useTranslation();

  if (!resources || resources.length === 0) {
    return (
      <p className={clsx('text-xs text-content-tertiary', className)}>
        {t('aiest.resources.none', {
          defaultValue: 'No resource breakdown for this rate.',
        })}
      </p>
    );
  }

  const rows = resources.map(normalise);

  return (
    <div className={clsx('overflow-hidden rounded-lg border border-border-light', className)}>
      <table className="w-full text-xs">
        <thead className="bg-surface-secondary text-content-tertiary">
          <tr>
            <th className="px-2.5 py-1.5 text-left font-medium">
              {t('aiest.resources.resource', { defaultValue: 'Resource' })}
            </th>
            <th className="px-2.5 py-1.5 text-left font-medium">
              {t('aiest.resources.type', { defaultValue: 'Type' })}
            </th>
            <th className="px-2.5 py-1.5 text-right font-medium">
              {t('aiest.resources.qty', { defaultValue: 'Qty' })}
            </th>
            <th className="px-2.5 py-1.5 text-right font-medium">
              {t('aiest.resources.rate', { defaultValue: 'Rate' })}
            </th>
            <th className="px-2.5 py-1.5 text-right font-medium">
              {t('aiest.resources.cost', { defaultValue: 'Cost' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.code ?? r.name}-${i}`} className="border-t border-border-light/60">
              <td className="px-2.5 py-1.5">
                <span className="font-medium text-content-primary">{r.name}</span>
                {r.code && (
                  <span className="ml-1.5 font-mono text-[10px] text-content-tertiary">
                    {r.code}
                  </span>
                )}
              </td>
              <td className="px-2.5 py-1.5">
                <span
                  className={clsx(
                    'inline-block rounded px-1.5 py-0.5 text-[10px] font-medium capitalize',
                    resourceTypeBadge(r.type),
                  )}
                >
                  {r.type}
                </span>
              </td>
              <td className="px-2.5 py-1.5 text-right tabular-nums text-content-secondary">
                {r.quantity} {r.unit}
              </td>
              <td className="px-2.5 py-1.5 text-right tabular-nums text-content-secondary">
                {fmtMoneyStr(r.unit_rate, currency, locale)}
              </td>
              <td className="px-2.5 py-1.5 text-right tabular-nums font-medium text-content-primary">
                {fmtMoneyStr(r.cost, currency, locale)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
