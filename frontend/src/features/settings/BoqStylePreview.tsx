// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A miniature bill of quantities drawn with the live design tokens, so every
 * change to style, text size, contrast or theme shows here the moment it lands.
 * Static sample rows, no data fetched.
 */
import { useTranslation } from 'react-i18next';
import { fmtNumber } from '@/shared/lib/formatters';
import { projectColor } from '@/shared/lib/projectColor';

const ROWS = [
  { pos: '01.001', key: 'concrete', label: 'Concrete C30/37, foundations', qty: 42.5, unit: 'm³', rate: 168 },
  { pos: '01.002', key: 'rebar', label: 'Reinforcement steel B500B', qty: 3.8, unit: 't', rate: 1240 },
  { pos: '01.003', key: 'formwork', label: 'Formwork to walls', qty: 186, unit: 'm²', rate: 38.5 },
] as const;

export function BoqStylePreview() {
  const { t } = useTranslation();
  const num = (v: number) => fmtNumber(v, 2);
  const total = ROWS.reduce((s, r) => s + r.qty * r.rate, 0);
  const stripe = projectColor({ id: 'preview-project' });

  return (
    <figure className="m-0" aria-label={t('settings.style_preview_title', { defaultValue: 'Live preview' })}>
      <figcaption className="mb-2 text-sm font-medium text-content-primary">
        {t('settings.style_preview_title', { defaultValue: 'Live preview' })}
      </figcaption>
      <div aria-hidden className="overflow-hidden rounded-xl border border-border bg-surface-page">
        <div className="h-1" style={{ background: stripe ?? undefined }} />
        <div className="flex items-center justify-between gap-2 border-b border-border-light bg-surface-elevated px-3 py-2">
          <span className="truncate text-sm font-semibold text-content-primary">
            {t('settings.style_preview_boq', { defaultValue: 'Bill of quantities' })}
          </span>
          <span className="rounded-md bg-oe-blue px-2 py-0.5 text-xs font-medium text-oe-on-accent">
            {t('settings.style_preview_action', { defaultValue: 'Add position' })}
          </span>
        </div>
        <table className="oe-table-compact bg-surface-elevated">
          <thead>
            <tr className="bg-surface-tertiary text-start text-content-secondary">
              <th>
                {t('settings.style_preview_pos', { defaultValue: 'Pos.' })}
              </th>
              <th>
                {t('settings.style_preview_description', { defaultValue: 'Description' })}
              </th>
              <th className="text-end">
                {t('settings.style_preview_qty', { defaultValue: 'Qty' })}
              </th>
              <th className="hidden text-end sm:table-cell">
                {t('settings.style_preview_rate', { defaultValue: 'Rate' })}
              </th>
              <th className="text-end">
                {t('settings.style_preview_total', { defaultValue: 'Total' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r, i) => (
              <tr
                key={r.pos}
                className={`border-t border-border-light ${i === 1 ? 'bg-oe-blue-subtle' : ''}`}
              >
                <td className="tabular-nums text-content-tertiary">{r.pos}</td>
                <td className="max-w-[12rem] truncate">
                  {t(`settings.style_preview_row_${r.key}`, { defaultValue: r.label })}
                </td>
                <td className="whitespace-nowrap text-end tabular-nums">
                  {num(r.qty)} <span className="text-content-tertiary">{r.unit}</span>
                </td>
                <td className="hidden text-end tabular-nums sm:table-cell">{num(r.rate)}</td>
                <td className="text-end tabular-nums">{num(r.qty * r.rate)}</td>
              </tr>
            ))}
            <tr className="border-t-2">
              <td colSpan={3} className="sm:hidden">
                {t('settings.style_preview_sum', { defaultValue: 'Total' })}
              </td>
              <td colSpan={4} className="hidden sm:table-cell">
                {t('settings.style_preview_sum', { defaultValue: 'Total' })}
              </td>
              <td className="text-end tabular-nums text-oe-blue-text">{num(total)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </figure>
  );
}
