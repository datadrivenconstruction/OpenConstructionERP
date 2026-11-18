// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Provincial fee programme (计费程序) of a Chinese project and the move to the
 * GB/T 50500-2024 edition. Renders nothing when the site lies outside every
 * jurisdiction the pack carries, so other provinces never see an empty table.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ExternalLink } from 'lucide-react';

import { getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';

import {
  applyEditionMove,
  fetchEditionMove,
  fetchProjectFees,
  findingKey,
  saveProjectFees,
  toFeeSettings,
} from './api';
import type { EditionMovePreview, FeeSettings } from './api';

const INPUT = 'w-full rounded-md border border-border bg-surface-primary px-2 py-1 text-sm text-content-primary';

export function ProvincialFeePanel({ projectId, edition }: { projectId: string; edition: string | null }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const feesQuery = useQuery({
    queryKey: ['china-tax', 'fees', projectId],
    queryFn: () => fetchProjectFees(projectId),
  });
  const [settings, setSettings] = useState<FeeSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<EditionMovePreview | null>(null);

  const fee = feesQuery.data?.fee ?? null;
  useEffect(() => {
    if (fee) setSettings(toFeeSettings(fee.settings ?? {}));
  }, [fee]);

  const save = useMutation({
    mutationFn: (body: FeeSettings) => saveProjectFees(projectId, toFeeSettings(body)),
    onSuccess: (data) => {
      setError(null);
      queryClient.setQueryData(['china-tax', 'fees', projectId], data);
      void queryClient.invalidateQueries({ queryKey: ['china-tax', 'check', projectId] });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const loadPreview = useMutation({ mutationFn: () => fetchEditionMove(projectId), onSuccess: setPreview });
  const applyMove = useMutation({
    mutationFn: () => applyEditionMove(projectId),
    onSuccess: (data) => {
      setPreview(data);
      void queryClient.invalidateQueries({ queryKey: ['china-tax'] });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const moveCard =
    edition === 'gb50500@2013' || preview ? (
      <Card>
        <h2 className="mb-1 text-sm font-semibold text-content-primary">
          {t('china_tax.move_title', { defaultValue: 'Move this project to GB/T 50500-2024' })}
        </h2>
        <p className="mb-3 text-xs text-content-tertiary">
          {t('china_tax.move_hint', {
            defaultValue:
              'See what changes first. Applied: the bill edition, and statutory-charge (规费) markups switched off. Lines and codes below are for you to move by hand.',
          })}
        </p>
        {preview && (
          <ul className="mb-3 space-y-1 text-xs text-content-secondary">
            <li>
              {t('china_tax.move_edition', { from: preview.from ?? '-', to: preview.to, defaultValue: 'Edition: {{from}} to {{to}}' })}
            </li>
            <li>
              {t('china_tax.move_guifei_lines', { count: preview.guifei_lines.length, defaultValue: 'Bill lines under the 规费 head to move: {{count}}' })}
            </li>
            <li>
              {t('china_tax.move_guifei_markups', { names: fmtList(preview.guifei_markups) || '-', defaultValue: '规费 markups to switch off: {{names}}' })}
            </li>
            <li>
              {t('china_tax.move_codes', { count: preview.codes_to_review_count, defaultValue: 'Item codes to review against the 2024 patterns: {{count}}' })}
            </li>
            {preview.fee_schedule_to && preview.fee_schedule_to !== preview.fee_schedule_from && (
              <li>
                {t('china_tax.move_schedule', { from: preview.fee_schedule_from ?? '-', to: preview.fee_schedule_to, defaultValue: 'Fee schedule: {{from}} to {{to}}' })}
              </li>
            )}
            {preview.applied && (
              <li className="text-semantic-success">
                {t('china_tax.move_done', { defaultValue: 'Applied. The project now uses GB/T 50500-2024.' })}
              </li>
            )}
          </ul>
        )}
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => loadPreview.mutate()} disabled={loadPreview.isPending}>
            {t('china_tax.move_preview', { defaultValue: 'Preview changes' })}
          </Button>
          {preview && preview.needed && !preview.applied && (
            <Button size="sm" onClick={() => applyMove.mutate()} disabled={applyMove.isPending}>
              {t('china_tax.move_apply', { defaultValue: 'Apply the move' })}
            </Button>
          )}
        </div>
      </Card>
    ) : null;

  if (!fee || !settings) return moveCard;

  const schedule = fee.schedule;
  const result = fee.result;
  const findings = feesQuery.data?.findings ?? [];
  const setRate = (code: string, value: string) => setSettings({ ...settings, rates: { ...settings.rates, [code]: value } });
  const setOption = (key: string, value: string) =>
    setSettings({ ...settings, options: { ...settings.options, [key]: value } });

  return (
    <>
      <Card>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('china_tax.fees_title', { defaultValue: 'Provincial fee programme' })}
            <span className="ml-2 font-normal text-content-tertiary">
              {fee.jurisdiction_name_zh} · {fee.jurisdiction_name_en}
            </span>
          </h2>
          {fee.price_station_url && (
            <a className="flex items-center gap-1 text-xs text-oe-blue" href={fee.price_station_url} target="_blank" rel="noreferrer">
              {t('china_tax.fees_station', { defaultValue: 'Cost station (信息价)' })}
              <ExternalLink size={12} />
            </a>
          )}
        </div>
        {!schedule ? (
          <p className="text-xs text-content-tertiary">
            {t('china_tax.fees_none', { date: fee.date ?? '-', defaultValue: 'No fee schedule we carry is in force on {{date}}.' })}
          </p>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="flex flex-col gap-1 text-xs text-content-secondary">
                <span>{t('china_tax.fees_schedule', { defaultValue: 'Fee schedule' })}</span>
                <select className={INPUT} value={settings.schedule_key ?? ''}
                  onChange={(e) => setSettings({ ...settings, schedule_key: e.target.value || null })}>
                  <option value="">
                    {t('china_tax.fees_by_date', { defaultValue: 'By tender date' })}
                  </option>
                  {fee.schedules.map((s) => (
                    <option key={s.key} value={s.key}>{s.name_zh}</option>
                  ))}
                </select>
              </label>
              {schedule.options.map((o) => (
                <label key={o.key} className="flex flex-col gap-1 text-xs text-content-secondary">
                  <span>{t(`china_tax.fees_option_${o.key}`, { defaultValue: o.key })}</span>
                  <select className={INPUT} value={settings.options[o.key] ?? o.default ?? ''}
                    onChange={(e) => setOption(o.key, e.target.value)}>
                    {o.values.map((v) => (
                      <option key={v} value={v}>{o.labels_zh?.[v] ?? v}</option>
                    ))}
                  </select>
                </label>
              ))}
              {schedule.labour_factor && (
                <label className="flex items-center gap-2 text-xs text-content-secondary">
                  <input type="checkbox" checked={settings.labour_includes_social_insurance}
                    onChange={(e) => setSettings({ ...settings, labour_includes_social_insurance: e.target.checked })} />
                  {t('china_tax.fees_labour_si', { factor: schedule.labour_factor, defaultValue: 'Labour prices already include social insurance (skip x{{factor}})' })}
                </label>
              )}
            </div>
            <p className="mb-2 text-2xs text-content-tertiary">
              {schedule.doc}
              {schedule.effective_from && ` · ${t('china_tax.fees_from', { date: schedule.effective_from, defaultValue: 'from {{date}}' })}`}
              {schedule.effective_to && ` · ${t('china_tax.fees_to', { date: schedule.effective_to, defaultValue: 'until {{date}}' })}`}
              {!schedule.bases_verified && ` · ${t('china_tax.fees_bases_unverified', { defaultValue: 'bases to confirm against your document' })}`}
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-2xs text-content-tertiary">
                  <th className="py-1">{t('china_tax.fees_line', { defaultValue: 'Fee line' })}</th>
                  <th className="py-1 text-right">{t('china_tax.fees_base', { defaultValue: 'Base' })}</th>
                  <th className="w-28 py-1 text-right">{t('china_tax.fees_rate', { defaultValue: 'Rate %' })}</th>
                  <th className="py-1 text-right">{t('china_tax.fees_amount', { defaultValue: 'Amount' })}</th>
                </tr>
              </thead>
              <tbody>
                {(result?.lines ?? []).map((row) => {
                  const meta = schedule.lines[row.code];
                  const band = meta?.band;
                  return (
                    <tr key={row.code} className="border-b border-border-light align-top">
                      <td className="py-1.5">
                        <div className="text-content-primary">
                          {meta?.name_zh} <span className="text-content-tertiary">{meta?.name_en}</span>
                        </div>
                        <div className="text-2xs text-content-tertiary">
                          {meta?.non_competitive && `${t('china_tax.fees_noncompetitive', { defaultValue: 'non-competitive' })} · `}
                          {band && `${t('china_tax.fees_band', { min: band.min ?? '-', max: band.max ?? '-', defaultValue: 'band {{min}}-{{max}}%' })} · `}
                          {row.coefficient !== '1' && `x${row.coefficient} · `}
                          {meta?.url ? (
                            <a href={meta.url} target="_blank" rel="noreferrer" className="text-oe-blue">{meta.doc}</a>
                          ) : (
                            t('china_tax.fees_no_source', { defaultValue: 'no official source held' })
                          )}
                          {meta?.needs_confirmation && ` · ${t('china_tax.fees_confirm', { defaultValue: 'to confirm' })}`}
                        </div>
                        {(meta?.reference_rates ?? []).length > 0 && (
                          <div className="text-2xs text-content-tertiary">
                            {t('china_tax.fees_reference', { defaultValue: 'Reference per chapter:' })}{' '}
                            {fmtList((meta?.reference_rates ?? []).map((r) => `${r.chapter_zh} ${r.rate}%`))}
                          </div>
                        )}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">
                        <MoneyDisplay amount={row.base} currency="CNY" />
                      </td>
                      <td className="py-1.5 text-right">
                        <input className={INPUT + ' text-right'} inputMode="decimal"
                          value={settings.rates[row.code] ?? ''}
                          placeholder={row.published ?? t('china_tax.fees_enter', { defaultValue: 'enter from your own document' })}
                          aria-label={meta?.name_en ?? row.code}
                          onChange={(e) => setRate(row.code, e.target.value)} />
                      </td>
                      <td className="py-1.5 text-right tabular-nums">
                        {row.status === 'missing' ? (
                          <span className="text-xs text-semantic-warning">{t('china_tax.fees_missing', { defaultValue: 'rate needed' })}</span>
                        ) : (
                          <MoneyDisplay amount={row.amount} currency="CNY" />
                        )}
                      </td>
                    </tr>
                  );
                })}
                {result && (
                  <>
                    <tr>
                      <td className="py-1.5 text-content-secondary" colSpan={3}>{t('china_tax.fees_pre_tax', { defaultValue: 'Pre-tax total' })}</td>
                      <td className="py-1.5 text-right tabular-nums"><MoneyDisplay amount={result.pre_tax} currency="CNY" /></td>
                    </tr>
                    <tr>
                      <td className="py-1.5 text-content-secondary" colSpan={3}>
                        {t('china_tax.fees_vat', { rate: result.vat_rate, defaultValue: 'VAT {{rate}}%' })}
                      </td>
                      <td className="py-1.5 text-right tabular-nums"><MoneyDisplay amount={result.vat} currency="CNY" /></td>
                    </tr>
                    <tr className="font-semibold">
                      <td className="py-1.5" colSpan={3}>{t('china_tax.fees_total', { defaultValue: 'Total' })}</td>
                      <td className="py-1.5 text-right tabular-nums"><MoneyDisplay amount={result.total} currency="CNY" /></td>
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </>
        )}
        {findings.length > 0 && (
          <ul className="mt-3 space-y-1">
            {findings.map((f, i) => (
              <li key={`${f.rule_id}-${f.element_ref ?? i}`} className="flex items-start gap-2 text-xs">
                <AlertTriangle size={12} className={f.severity === 'error' ? 'mt-0.5 text-semantic-error' : 'mt-0.5 text-semantic-warning'} />
                <span>
                  {t(findingKey(f.rule_id), {
                    ...Object.fromEntries(Object.entries(f.details ?? {}).map(([k, v]) => [k, String(v)])),
                    defaultValue: f.message,
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex items-center gap-3">
          <Button size="sm" onClick={() => save.mutate(settings)} disabled={save.isPending}>
            {t('china_tax.fees_save', { defaultValue: 'Save and recompute' })}
          </Button>
          {error && <span className="text-xs text-semantic-error">{error}</span>}
        </div>
      </Card>
      {moveCard}
    </>
  );
}
