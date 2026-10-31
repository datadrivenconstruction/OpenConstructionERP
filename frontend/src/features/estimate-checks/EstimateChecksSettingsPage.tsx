// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Estimate check settings: the user's own display choice, and (for managers)
 * which figures the company checks and the ranges it accepts.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Button, Card } from '@/shared/ui';
import type { CheckSettings, DisplayMode, KpiSetting } from './api';
import { useCheckSettings, useDisplayMode, useSaveCheckSettings, useSaveDisplayMode } from './hooks';
import { GROUP_ORDER, tx } from './labels';

const MODES: DisplayMode[] = ['badge', 'issues', 'all', 'off'];

function toNum(v: string): number | null {
  if (v.trim() === '') return null;
  const n = Number(v.replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

export function EstimateChecksSettingsPage() {
  const { t } = useTranslation();
  const { data: mode } = useDisplayMode(true);
  const saveMode = useSaveDisplayMode();
  const { data: settings, isLoading } = useCheckSettings();
  const save = useSaveCheckSettings();
  const [draft, setDraft] = useState<CheckSettings | null>(null);

  useEffect(() => {
    if (settings && !draft) {
      setDraft({
        comparables: settings.comparables,
        min_comparables: settings.min_comparables,
        warning_margin: settings.warning_margin,
        database_rate_tolerance_pct: settings.database_rate_tolerance_pct,
        count_warning_share_pct: settings.count_warning_share_pct,
        kpis: settings.kpis,
      });
    }
  }, [settings, draft]);

  const setKpi = (id: string, patch: Partial<KpiSetting>) =>
    setDraft((d) => (d ? { ...d, kpis: { ...d.kpis, [id]: { ...(d.kpis[id] ?? { enabled: true }), ...patch } } } : d));

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6" data-testid="estimate-checks-settings">
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{tx(t, 'estimate_checks.settings.title')}</h1>
        <p className="text-sm text-content-secondary">{tx(t, 'estimate_checks.settings.subtitle')}</p>
      </div>

      <Card>
        <h2 className="mb-3 text-sm font-semibold text-content-primary">
          {tx(t, 'estimate_checks.settings.display_title')}
        </h2>
        <div className="grid gap-2 sm:grid-cols-2" role="radiogroup">
          {MODES.map((m) => (
            <label
              key={m}
              className={clsx(
                'flex cursor-pointer gap-2 rounded-lg border px-3 py-2',
                mode === m ? 'border-oe-blue bg-surface-secondary' : 'border-border-light',
              )}
            >
              <input
                type="radio"
                name="estimate-check-display"
                checked={mode === m}
                onChange={() => saveMode.mutate(m)}
                className="mt-1"
              />
              <span>
                <span className="block text-sm text-content-primary">
                  {tx(t, `estimate_checks.settings.display.${m}`)}
                </span>
                <span className="block text-xs text-content-secondary">
                  {tx(t, `estimate_checks.settings.display.${m}_hint`)}
                </span>
              </span>
            </label>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="text-sm font-semibold text-content-primary">
          {tx(t, 'estimate_checks.settings.workspace_title')}
        </h2>
        <p className="mb-4 text-xs text-content-secondary">{tx(t, 'estimate_checks.settings.workspace_hint')}</p>
        {isLoading || !draft || !settings ? (
          <p className="text-sm text-content-secondary">{tx(t, 'estimate_checks.loading')}</p>
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(draft);
            }}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-xs text-content-secondary">
                {tx(t, 'estimate_checks.settings.comparables')}
                <select
                  className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
                  value={draft.comparables}
                  onChange={(e) => setDraft({ ...draft, comparables: e.target.value as CheckSettings['comparables'] })}
                >
                  {(['auto', 'currency', 'all'] as const).map((c) => (
                    <option key={c} value={c}>
                      {tx(t, `estimate_checks.settings.comparables.${c}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-content-secondary">
                {tx(t, 'estimate_checks.settings.min_comparables')}
                <input
                  type="number"
                  min={2}
                  max={200}
                  className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
                  value={draft.min_comparables}
                  onChange={(e) => setDraft({ ...draft, min_comparables: Number(e.target.value) || 2 })}
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-content-secondary">
                {tx(t, 'estimate_checks.settings.db_tolerance')}
                <input
                  type="number"
                  min={1}
                  className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
                  value={draft.database_rate_tolerance_pct}
                  onChange={(e) =>
                    setDraft({ ...draft, database_rate_tolerance_pct: Number(e.target.value) || 30 })
                  }
                />
              </label>
            </div>

            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-content-tertiary">
                  <th className="py-1 font-medium">{tx(t, 'estimate_checks.settings.col_check')}</th>
                  <th className="w-12 py-1 font-medium">{tx(t, 'estimate_checks.settings.col_on')}</th>
                  <th className="w-24 py-1 font-medium">{tx(t, 'estimate_checks.settings.col_low')}</th>
                  <th className="w-24 py-1 font-medium">{tx(t, 'estimate_checks.settings.col_high')}</th>
                </tr>
              </thead>
              {GROUP_ORDER.map((g) => (
                <tbody key={g} className="border-t border-border-light">
                  <tr>
                    <td colSpan={4} className="pt-3 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                      {tx(t, `estimate_checks.group.${g}`)}
                    </td>
                  </tr>
                  {settings.catalog
                    .filter((c) => c.group === g)
                    .map((c) => {
                      const cfg = draft.kpis[c.kpi_id] ?? { enabled: true };
                      return (
                        <tr key={c.kpi_id}>
                          <td className="py-1 text-content-primary">{tx(t, `estimate_checks.kpi.${c.kpi_id}`)}</td>
                          <td className="py-1">
                            <input
                              type="checkbox"
                              aria-label={tx(t, `estimate_checks.kpi.${c.kpi_id}`)}
                              checked={cfg.enabled}
                              onChange={(e) => setKpi(c.kpi_id, { enabled: e.target.checked })}
                            />
                          </td>
                          {c.kind === 'historical' ? (
                            (['low', 'high'] as const).map((side) => (
                              <td key={side} className="py-1 pr-2">
                                <input
                                  type="text"
                                  inputMode="decimal"
                                  className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs"
                                  placeholder={
                                    (side === 'low' ? c.default_low : c.default_high)?.toString() ?? ''
                                  }
                                  value={cfg[side] ?? ''}
                                  onChange={(e) => setKpi(c.kpi_id, { [side]: toNum(e.target.value) })}
                                />
                              </td>
                            ))
                          ) : (
                            <td colSpan={2} className="py-1 text-xs text-content-tertiary">
                              {tx(t, 'estimate_checks.expected_none')}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                </tbody>
              ))}
            </table>

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={save.isPending}>
                {tx(t, 'estimate_checks.settings.save')}
              </Button>
              {save.isSuccess && (
                <span className="text-xs text-content-secondary">{tx(t, 'estimate_checks.settings.saved')}</span>
              )}
              {save.isError && (
                <span className="text-xs text-red-600">{tx(t, 'estimate_checks.settings.save_error')}</span>
              )}
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}

export default EstimateChecksSettingsPage;
