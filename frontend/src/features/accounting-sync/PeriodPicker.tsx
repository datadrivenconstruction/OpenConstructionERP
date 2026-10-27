// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** From and to date fields; an empty field leaves that end of the period open. */
import { useTranslation } from 'react-i18next';
import type { DateRange } from './api';
import { compactInputCls } from './ui';

export function PeriodPicker({ range, onChange }: { range: DateRange; onChange: (r: DateRange) => void }) {
  const { t } = useTranslation();
  const set = (k: keyof DateRange, v: string) => onChange({ ...range, [k]: v || undefined });
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-xs text-content-secondary">
        <span className="mb-1 block font-medium">{t('accountingSync.period.from', { defaultValue: 'From' })}</span>
        <input type="date" className={compactInputCls} value={range.date_from ?? ''} onChange={(e) => set('date_from', e.target.value)} />
      </label>
      <label className="text-xs text-content-secondary">
        <span className="mb-1 block font-medium">{t('accountingSync.period.to', { defaultValue: 'To' })}</span>
        <input type="date" className={compactInputCls} value={range.date_to ?? ''} onChange={(e) => set('date_to', e.target.value)} />
      </label>
    </div>
  );
}
