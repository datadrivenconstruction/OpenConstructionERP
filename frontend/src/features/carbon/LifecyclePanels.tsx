// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Life-cycle tab (budget, checks, hotspots, A4 / A5 lines, EPD import) and the
// company climate report tab (ESRS E1, SECR, US state) with audit-ready exports.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, Download, FileUp, Flame, Truck } from 'lucide-react';

import { Badge, Button, Card, EmptyState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';

import { listInventories } from './api';
import {
  addSiteEnergyA5,
  addTransportA4,
  exportCompanyReport,
  generateCompanyReport,
  getBudget,
  getChecks,
  getHotspots,
  importEpdFile,
  listCompanyReports,
  type ClassificationSystem,
  type CompanyReport,
  type ExportFormat,
  type ReportTemplate,
} from './lifecycleApi';
import { budgetTone, failingChecks, kgToTonnes, qualityTone } from './lifecycle';

const inputCls = 'h-9 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary';

export function LifecyclePanel({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [system, setSystem] = useState<ClassificationSystem>('din276');
  const [a4, setA4] = useState({ mass_kg: '', distance_km: '', mode: 'road_truck' });
  const [a5, setA5] = useState({ diesel: '', kwh: '' });
  const [msg, setMsg] = useState<string | null>(null);

  const invQ = useQuery({ queryKey: ['carbon', 'inventories', projectId], queryFn: () => listInventories(projectId) });
  const inventoryId = invQ.data?.[invQ.data.length - 1]?.id ?? '';
  const budgetQ = useQuery({ queryKey: ['carbon', 'budget', projectId], queryFn: () => getBudget(projectId) });
  const checksQ = useQuery({ queryKey: ['carbon', 'checks', projectId], queryFn: () => getChecks(projectId) });
  const hotQ = useQuery({
    queryKey: ['carbon', 'hotspots', inventoryId, system],
    queryFn: () => getHotspots(inventoryId, system),
    enabled: !!inventoryId,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['carbon'] });
  };
  const a4M = useMutation({
    mutationFn: () => addTransportA4(inventoryId, a4),
    onSuccess: () => {
      setMsg(t('carbon.lc.line_added', { defaultValue: 'Line added to the inventory.' }));
      refresh();
    },
    onError: (e) => setMsg(getErrorMessage(e)),
  });
  const a5M = useMutation({
    mutationFn: () =>
      addSiteEnergyA5(inventoryId, {
        fuel_litres: a5.diesel ? { diesel: a5.diesel } : {},
        electricity_kwh: a5.kwh || '0',
      }),
    onSuccess: () => {
      setMsg(t('carbon.lc.line_added', { defaultValue: 'Line added to the inventory.' }));
      refresh();
    },
    onError: (e) => setMsg(getErrorMessage(e)),
  });
  const epdM = useMutation({
    mutationFn: (f: File) => importEpdFile(f),
    onSuccess: (r) => {
      setMsg(t('carbon.lc.epd_imported', { defaultValue: '{{count}} EPD(s) imported.', count: r.imported.length }));
      refresh();
    },
    onError: (e) => setMsg(getErrorMessage(e)),
  });

  const b = budgetQ.data;
  const tone = budgetTone(b);
  const failing = failingChecks(checksQ.data);
  const checkLabel: Record<string, string> = {
    no_factor: t('carbon.lc.check_no_factor', { defaultValue: 'Lines without an emission factor' }),
    outdated_factor_set: t('carbon.lc.check_outdated', { defaultValue: 'Factor set older than five years' }),
    expired_epd: t('carbon.lc.check_expired_epd', { defaultValue: 'Expired EPD in use' }),
    unit_mismatch: t('carbon.lc.check_unit', { defaultValue: 'Unit does not match the factor unit' }),
    over_budget: t('carbon.lc.check_over_budget', { defaultValue: 'Project is over its carbon budget' }),
  };

  return (
    <div className="space-y-4">
      {msg && (
        <div role="status" className="rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm">
          {msg}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('carbon.lc.budget_title', { defaultValue: 'Carbon budget' })}
          </h3>
          {b && Number(b.budget_kg) > 0 ? (
            <>
              <p className="mt-2 text-sm text-content-secondary">
                {t('carbon.lc.budget_line', {
                  defaultValue: '{{actual}} of {{budget}} tCO2e ({{pct}}%)',
                  actual: kgToTonnes(b.actual_kg, i18n.language),
                  budget: kgToTonnes(b.budget_kg, i18n.language),
                  pct: b.used_pct,
                })}
              </p>
              <div className="mt-2 h-2 w-full rounded bg-surface-secondary" aria-hidden>
                <div
                  className={clsx('h-2 rounded', {
                    'bg-semantic-success': tone === 'success',
                    'bg-semantic-warning': tone === 'warning',
                    'bg-semantic-error': tone === 'error',
                  })}
                  style={{ width: `${Math.min(100, b.used_pct)}%` }}
                />
              </div>
            </>
          ) : (
            <p className="mt-2 text-sm text-content-tertiary">
              {t('carbon.lc.budget_none', {
                defaultValue: 'No budget yet. Add a target of type "budget" on the Targets tab.',
              })}
            </p>
          )}
        </Card>
        <Card>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('carbon.lc.checks_title', { defaultValue: 'Carbon checks' })}
          </h3>
          {failing.length === 0 ? (
            <p className="mt-2 text-sm text-content-secondary">
              {t('carbon.lc.checks_ok', { defaultValue: 'All checks passed.' })}
            </p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {failing.map((f) => (
                <li key={f.key} className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-semantic-warning" aria-hidden />
                  <span>{checkLabel[f.key]}</span>
                  {f.key !== 'over_budget' && <Badge size="sm">{f.count}</Badge>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('carbon.lc.hotspots_title', { defaultValue: 'Hotspots by cost group' })}
          </h3>
          <select
            aria-label={t('carbon.lc.classification', { defaultValue: 'Classification' })}
            className={inputCls}
            value={system}
            onChange={(e) => setSystem(e.target.value as ClassificationSystem)}
          >
            <option value="din276">DIN 276</option>
            <option value="nrm">NRM</option>
            <option value="masterformat">MasterFormat</option>
          </select>
        </div>
        {(hotQ.data ?? []).length === 0 ? (
          <EmptyState
            title={t('carbon.lc.hotspots_empty', { defaultValue: 'No carbon lines linked to BOQ positions yet' })}
          />
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-content-tertiary">
                <th className="py-1">{t('carbon.lc.group', { defaultValue: 'Group' })}</th>
                <th className="py-1 text-right">tCO2e</th>
                <th className="py-1 text-right">%</th>
              </tr>
            </thead>
            <tbody>
              {(hotQ.data ?? []).map((h) => (
                <tr key={h.group} className="border-t border-border-light">
                  <td className="py-1">
                    {h.group === 'unclassified'
                      ? t('carbon.lc.unclassified', { defaultValue: 'Unclassified' })
                      : h.group}
                  </td>
                  <td className="py-1 text-right tabular-nums">{kgToTonnes(h.carbon_kg, i18n.language)}</td>
                  <td className="py-1 text-right tabular-nums">{h.share_pct.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Truck className="h-4 w-4" aria-hidden />
            {t('carbon.lc.a4_title', { defaultValue: 'Transport to site (A4)' })}
          </h3>
          <div className="mt-2 flex flex-col gap-2">
            <input
              className={inputCls}
              inputMode="decimal"
              placeholder={t('carbon.lc.mass_kg', { defaultValue: 'Mass, kg' })}
              value={a4.mass_kg}
              onChange={(e) => setA4({ ...a4, mass_kg: e.target.value })}
            />
            <input
              className={inputCls}
              inputMode="decimal"
              placeholder={t('carbon.lc.distance_km', { defaultValue: 'Supplier distance, km' })}
              value={a4.distance_km}
              onChange={(e) => setA4({ ...a4, distance_km: e.target.value })}
            />
            <select className={inputCls} value={a4.mode} onChange={(e) => setA4({ ...a4, mode: e.target.value })}>
              {['road_truck', 'road_van', 'rail', 'inland_barge', 'sea_container', 'air'].map((m) => (
                <option key={m} value={m}>
                  {t(`carbon.lc.mode_${m}`, { defaultValue: m })}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              disabled={!inventoryId || !a4.mass_kg || !a4.distance_km}
              loading={a4M.isPending}
              onClick={() => a4M.mutate()}
            >
              {t('carbon.lc.add_line', { defaultValue: 'Add line' })}
            </Button>
          </div>
        </Card>
        <Card>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Flame className="h-4 w-4" aria-hidden />
            {t('carbon.lc.a5_title', { defaultValue: 'Site energy and fuel (A5)' })}
          </h3>
          <div className="mt-2 flex flex-col gap-2">
            <input
              className={inputCls}
              inputMode="decimal"
              placeholder={t('carbon.lc.diesel_l', { defaultValue: 'Diesel, litres' })}
              value={a5.diesel}
              onChange={(e) => setA5({ ...a5, diesel: e.target.value })}
            />
            <input
              className={inputCls}
              inputMode="decimal"
              placeholder={t('carbon.lc.meter_kwh', { defaultValue: 'Electricity meter, kWh' })}
              value={a5.kwh}
              onChange={(e) => setA5({ ...a5, kwh: e.target.value })}
            />
            <Button
              size="sm"
              disabled={!inventoryId || (!a5.diesel && !a5.kwh)}
              loading={a5M.isPending}
              onClick={() => a5M.mutate()}
            >
              {t('carbon.lc.add_line', { defaultValue: 'Add line' })}
            </Button>
          </div>
        </Card>
        <Card>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <FileUp className="h-4 w-4" aria-hidden />
            {t('carbon.lc.epd_import_title', { defaultValue: 'Import EPD' })}
          </h3>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('carbon.lc.epd_import_hint', { defaultValue: 'EN 15804 ILCD+EPD XML or CSV' })}
          </p>
          <input
            className="mt-2 text-sm"
            type="file"
            accept=".xml,.csv"
            aria-label={t('carbon.lc.epd_import_title', { defaultValue: 'Import EPD' })}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) epdM.mutate(f);
              e.target.value = '';
            }}
          />
        </Card>
      </div>
    </div>
  );
}

const EXPORTS: ExportFormat[] = ['xlsx', 'pdf', 'xbrl_csv'];

export function CompanyReportPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [form, setForm] = useState({
    reporting_year: new Date().getFullYear(),
    template: 'esrs_e1' as ReportTemplate,
    company_name: '',
    net_revenue: '',
    currency: 'EUR',
  });
  const [err, setErr] = useState<string | null>(null);
  const reportsQ = useQuery({ queryKey: ['carbon', 'company-reports'], queryFn: listCompanyReports });
  const genM = useMutation({
    mutationFn: () => generateCompanyReport({ ...form, net_revenue: form.net_revenue || '0' }),
    onSuccess: () => {
      setErr(null);
      qc.invalidateQueries({ queryKey: ['carbon', 'company-reports'] });
    },
    onError: (e) => setErr(getErrorMessage(e)),
  });
  const reports = reportsQ.data ?? [];
  const current: CompanyReport | undefined = reports[0];
  const templateLabel: Record<ReportTemplate, string> = {
    esrs_e1: t('carbon.lc.tpl_esrs_e1', { defaultValue: 'CSRD / ESRS E1' }),
    uk_secr: t('carbon.lc.tpl_uk_secr', { defaultValue: 'UK SECR' }),
    us_state: t('carbon.lc.tpl_us_state', { defaultValue: 'US state disclosure' }),
  };
  const qualityLabel = {
    measured: t('carbon.lc.q_measured', { defaultValue: 'Measured' }),
    calculated: t('carbon.lc.q_calculated', { defaultValue: 'Calculated' }),
    estimated: t('carbon.lc.q_estimated', { defaultValue: 'Estimated' }),
  };

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('carbon.lc.company_title', { defaultValue: 'Company climate report' })}
        </h3>
        <p className="mt-1 text-xs text-content-tertiary">
          {t('carbon.lc.company_hint', {
            defaultValue:
              'Adds up scope 1, 2 and 3 across your projects, fleet fuel and offices. Every figure links to its source records.',
          })}
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <input
            className={clsx(inputCls, 'w-24')}
            type="number"
            aria-label={t('carbon.lc.year', { defaultValue: 'Year' })}
            value={form.reporting_year}
            onChange={(e) => setForm({ ...form, reporting_year: Number(e.target.value) })}
          />
          <select
            className={inputCls}
            aria-label={t('carbon.lc.template', { defaultValue: 'Template' })}
            value={form.template}
            onChange={(e) => setForm({ ...form, template: e.target.value as ReportTemplate })}
          >
            {(Object.keys(templateLabel) as ReportTemplate[]).map((k) => (
              <option key={k} value={k}>
                {templateLabel[k]}
              </option>
            ))}
          </select>
          <input
            className={inputCls}
            placeholder={t('carbon.lc.company_name', { defaultValue: 'Company name' })}
            value={form.company_name}
            onChange={(e) => setForm({ ...form, company_name: e.target.value })}
          />
          <input
            className={clsx(inputCls, 'w-36')}
            inputMode="decimal"
            placeholder={t('carbon.lc.net_revenue', { defaultValue: 'Net revenue' })}
            value={form.net_revenue}
            onChange={(e) => setForm({ ...form, net_revenue: e.target.value })}
          />
          <input
            className={clsx(inputCls, 'w-20')}
            maxLength={3}
            aria-label={t('carbon.lc.currency', { defaultValue: 'Currency' })}
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
          />
          <Button size="sm" loading={genM.isPending} onClick={() => genM.mutate()}>
            {t('carbon.lc.generate', { defaultValue: 'Generate report' })}
          </Button>
        </div>
        {err && <p className="mt-2 text-sm text-semantic-error">{err}</p>}
      </Card>

      {!current ? (
        <EmptyState title={t('carbon.lc.company_empty', { defaultValue: 'No company report yet' })} />
      ) : (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-content-primary">
              {current.company_name || templateLabel[current.template]} · {current.reporting_year}
            </h3>
            <div className="flex gap-2">
              {EXPORTS.map((f) => (
                <Button
                  key={f}
                  size="sm"
                  variant="secondary"
                  icon={<Download className="h-4 w-4" />}
                  onClick={() => exportCompanyReport(current, f).catch((e) => setErr(getErrorMessage(e)))}
                >
                  {t(`carbon.lc.export_${f}`, { defaultValue: f.toUpperCase() })}
                </Button>
              ))}
            </div>
          </div>
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-content-tertiary">
                <th className="py-1">{t('carbon.lc.datapoint', { defaultValue: 'Data point' })}</th>
                <th className="py-1 text-right">{t('carbon.lc.value', { defaultValue: 'Value' })}</th>
                <th className="py-1">{t('carbon.lc.unit', { defaultValue: 'Unit' })}</th>
                <th className="py-1">{t('carbon.lc.quality', { defaultValue: 'Data quality' })}</th>
                <th className="py-1 text-right">{t('carbon.lc.sources', { defaultValue: 'Sources' })}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(current.datapoints).map(([id, d]) => (
                <tr key={id} className="border-t border-border-light">
                  <td className="py-1">
                    <span className="font-mono text-xs text-content-tertiary">{id}</span>{' '}
                    {t(`carbon.lc.dp_${id.replace(/-/g, '_')}`, { defaultValue: d.label })}
                  </td>
                  <td className="py-1 text-right tabular-nums">{d.value}</td>
                  <td className="py-1">{d.unit}</td>
                  <td className="py-1">
                    <Badge size="sm" variant={qualityTone(d.data_quality) === 'neutral' ? 'blue' : qualityTone(d.data_quality) as 'success' | 'warning'}>
                      {qualityLabel[d.data_quality]}
                    </Badge>
                  </td>
                  <td className="py-1 text-right tabular-nums">{d.source_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
