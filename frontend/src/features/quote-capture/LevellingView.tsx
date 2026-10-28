// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Levelling of the captured quotes of one tender package: one column per quote,
 * one row per scope item. A gap is filled with a plug rate (price list, BOQ or
 * the median of the other quotes) and marked, so the adjusted totals compare
 * like with like.
 */
import { useTranslation } from 'react-i18next';
import { formatCurrency } from '@/shared/lib/money';
import { useLevelling } from './api';
import { formatDecimal } from './format';

export function LevellingView({ packageId }: { packageId: string }) {
  const { t } = useTranslation();
  const q = useLevelling(packageId);
  if (q.isLoading) return <p className="text-sm text-content-secondary">{t('quote_capture.loading', 'Loading...')}</p>;
  if (!q.data || q.data.quotes.length === 0)
    return <p className="text-sm text-content-secondary">{t('quote_capture.levelling_empty', 'No quotes on this package yet.')}</p>;
  const { rows, quotes, currency } = q.data;
  const money = (v: string) => formatCurrency(v, currency);
  const plugLabel: Record<string, string> = {
    price_list: t('quote_capture.plug_price_list', 'plug: price list'),
    boq: t('quote_capture.plug_boq', 'plug: BOQ rate'),
    median_of_quotes: t('quote_capture.plug_median', 'plug: median of quotes'),
    none: t('quote_capture.plug_none', 'no plug rate'),
  };
  return (
    <div className="flex flex-col gap-3" data-testid="quote-levelling">
      {q.data.excluded_off_currency.length > 0 && (
        <p className="text-sm text-amber-700">
          {t('quote_capture.off_currency', '{{count}} quote(s) in another currency are left out.', {
            count: q.data.excluded_off_currency.length,
          })}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-left text-xs text-content-secondary">
              <th className="py-1">{t('quote_capture.col_item', 'Item')}</th>
              <th className="text-right">{t('quote_capture.col_qty', 'Qty')}</th>
              {quotes.map((s) => (
                <th key={s.quote_id} className="text-right">{s.supplier}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.position_id} className="border-t">
                <td className="py-1 pr-2" dir="auto">{`${r.ordinal} ${r.description}`.trim()}</td>
                <td className="text-right">{`${formatDecimal(r.quantity, 0)} ${r.unit}`}</td>
                {r.cells.map((c) => (
                  <td
                    key={c.quote_id}
                    data-testid={`cell-${c.status}`}
                    className={`text-right ${c.status === 'gap' ? 'bg-amber-50 italic dark:bg-amber-950/30' : ''} ${c.lowest ? 'font-semibold text-emerald-700' : ''}`}
                  >
                    {money(c.adjusted_total)}
                    {c.status === 'gap' && c.plug_source && (
                      <div className="text-2xs text-amber-700">{plugLabel[c.plug_source]}</div>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="text-sm">
            {(
              [
                ['quoted_total', t('quote_capture.sum_quoted', 'Quoted')],
                ['plug_total', t('quote_capture.sum_plugs', 'Scope gaps (plugs)')],
                ['extras_total', t('quote_capture.sum_extras', 'Extra lines')],
                ['adjusted_total', t('quote_capture.sum_adjusted', 'Adjusted total')],
              ] as const
            ).map(([key, label]) => (
              <tr key={key} className={`border-t ${key === 'adjusted_total' ? 'font-semibold' : ''}`}>
                <td className="py-1" colSpan={2}>{label}</td>
                {quotes.map((s) => (
                  <td key={s.quote_id} className="text-right" data-testid={`${key}-${s.quote_id}`}>
                    {money(s[key])}
                  </td>
                ))}
              </tr>
            ))}
            <tr className="border-t text-xs text-content-secondary">
              <td colSpan={2}>{t('quote_capture.rank_gaps', 'Rank, gaps, exclusions')}</td>
              {quotes.map((s) => (
                <td key={s.quote_id} className="text-right">{`#${s.rank} · ${s.gap_rows} · ${s.exclusions}`}</td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
