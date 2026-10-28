// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';

import { formatControlsValue, kpiByCurrency, kpiMultiCurrency } from './format';

/**
 * When a money KPI spans more than one currency (portfolio mode), the
 * headline value is only the dominant currency's slice. This badge renders
 * the full per-currency split so the tile is honest and never blends.
 */
export function MultiCurrencyBadge({
  breakdown,
  unit,
}: {
  breakdown: Record<string, unknown> | undefined;
  unit: string | null | undefined;
}) {
  const { t } = useTranslation();
  const groups = kpiByCurrency(breakdown);
  if (!kpiMultiCurrency(breakdown) || groups.length < 2) return null;
  return (
    <div className="mt-2">
      <span className="rounded bg-surface-tertiary px-1.5 py-0.5 text-2xs font-medium text-content-tertiary">
        {t('controls.multi_currency', { defaultValue: 'multi-currency' })}
      </span>
      <div className="mt-1 flex flex-col gap-0.5 text-2xs text-content-tertiary">
        {groups.map((g) => (
          <div
            key={g.currency}
            className="flex justify-between gap-3 tabular-nums"
          >
            <span className="font-medium">{g.currency}</span>
            <span>{formatControlsValue(g.amount, unit, g.currency)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
