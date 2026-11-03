// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Capital plan: which projects fit the money, and what if we delay one.
// One page: plan picker, scenario tabs, a projects x years grid with the
// Envelope / Demand / Gap rows underneath, and the actions that work on it.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Download, GitCompare, Plus, Sparkles, Wallet } from 'lucide-react';

import { Button, Card, CardContent, EmptyState, ModuleGuideButton, Skeleton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import {
  capitalPlanApi,
  type AutofundResult,
  type CapitalItem,
  type CapitalPlan,
  type ItemStatus,
} from './api';
import { capitalPlanGuide } from './capitalPlanGuide';
import { formatMoney, gapTone, isSingleSource, shiftedStart, withYearAmount } from './logic';

const KEY = ['capital_plan'] as const;
const STATUSES: ItemStatus[] = ['proposed', 'funded', 'deferred'];
const FIELD =
  'rounded-lg border border-border bg-surface-primary px-2 py-1 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40';

function statusLabel(t: (k: string, o?: Record<string, unknown>) => string, s: string): string {
  const defaults: Record<string, string> = { proposed: 'Proposed', funded: 'Funded', deferred: 'Deferred' };
  return t(`capital_plan.status.${s}`, { defaultValue: defaults[s] ?? s });
}

export function CapitalPlanPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [planId, setPlanId] = useState<string | null>(null);
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [cloneName, setCloneName] = useState<string | null>(null);
  const [compareWith, setCompareWith] = useState<string>('');
  const [suggestion, setSuggestion] = useState<AutofundResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ name: '', currency: 'EUR', start_year: new Date().getFullYear(), horizon: 5 });

  const plansQ = useQuery({ queryKey: [...KEY, 'plans'], queryFn: capitalPlanApi.listPlans, retry: false });
  const plans = plansQ.data ?? [];
  const plan: CapitalPlan | undefined = plans.find((p) => p.id === planId) ?? plans[0];

  const scenariosQ = useQuery({
    queryKey: [...KEY, 'scenarios', plan?.id],
    queryFn: () => capitalPlanApi.listScenarios(plan!.id),
    enabled: !!plan,
    retry: false,
  });
  const scenarios = scenariosQ.data ?? [];
  const scenario = scenarios.find((s) => s.id === scenarioId) ?? scenarios.find((s) => s.is_baseline) ?? scenarios[0];

  const envelopesQ = useQuery({
    queryKey: [...KEY, 'envelopes', plan?.id],
    queryFn: () => capitalPlanApi.listEnvelopes(plan!.id),
    enabled: !!plan,
    retry: false,
  });
  const itemsQ = useQuery({
    queryKey: [...KEY, 'items', scenario?.id],
    queryFn: () => capitalPlanApi.listItems(scenario!.id),
    enabled: !!scenario,
    retry: false,
  });
  const summaryQ = useQuery({
    queryKey: [...KEY, 'summary', scenario?.id],
    queryFn: () => capitalPlanApi.summary(scenario!.id),
    enabled: !!scenario,
    retry: false,
  });
  const compareQ = useQuery({
    queryKey: [...KEY, 'compare', plan?.id, scenario?.id, compareWith],
    queryFn: () => capitalPlanApi.compare(plan!.id, scenario!.id, compareWith),
    enabled: !!plan && !!scenario && !!compareWith && compareWith !== scenario.id,
    retry: false,
  });

  const items = itemsQ.data ?? [];
  const summary = summaryQ.data;
  const envelopes = envelopesQ.data ?? [];
  const currency = plan?.currency ?? '';
  const spendById = useMemo(() => new Map((summary?.items ?? []).map((i) => [i.id, i.spend])), [summary]);

  const refresh = () => qc.invalidateQueries({ queryKey: KEY });
  const fail = (e: unknown) => setError(getErrorMessage(e));

  const createPlan = useMutation({
    mutationFn: () =>
      capitalPlanApi.createPlan({
        name: draft.name.trim(),
        currency: draft.currency.trim().toUpperCase(),
        start_year: draft.start_year,
        horizon_years: draft.horizon,
      }),
    onSuccess: (p) => {
      setError(null);
      setPlanId(p.id);
      setScenarioId(null);
      refresh();
    },
    onError: fail,
  });
  const patchItem = useMutation({
    mutationFn: (v: { id: string; body: Parameters<typeof capitalPlanApi.patchItem>[1] }) =>
      capitalPlanApi.patchItem(v.id, v.body),
    onSuccess: () => {
      setError(null);
      setSuggestion(null);
      refresh();
    },
    onError: fail,
  });
  const saveEnvelopes = useMutation({
    mutationFn: (body: ReturnType<typeof withYearAmount>) => capitalPlanApi.replaceEnvelopes(plan!.id, body),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: fail,
  });
  const clone = useMutation({
    mutationFn: (name: string) => capitalPlanApi.cloneScenario(plan!.id, scenario!.id, name),
    onSuccess: (s) => {
      setError(null);
      setCloneName(null);
      setScenarioId(s.id);
      setSuggestion(null);
      refresh();
    },
    onError: fail,
  });
  const importProjects = useMutation({
    mutationFn: () => capitalPlanApi.importProjects(plan!.id, scenario!.id),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: fail,
  });
  const suggest = useMutation({
    mutationFn: () => capitalPlanApi.autofund(scenario!.id),
    onSuccess: (r) => {
      setError(null);
      setSuggestion(r);
    },
    onError: fail,
  });
  const apply = useMutation({
    mutationFn: (changes: { id: string; status: ItemStatus }[]) => capitalPlanApi.applyStatuses(scenario!.id, changes),
    onSuccess: () => {
      setError(null);
      setSuggestion(null);
      refresh();
    },
    onError: fail,
  });

  const titleOf = (id: string) => items.find((i) => i.id === id)?.title ?? id;
  const changes = (suggestion?.items ?? []).filter((s) => s.changed);
  const statusOf = (id: string) => items.find((i) => i.id === id)?.status ?? 'proposed';
  const money = (v: string | number) => formatMoney(v, currency);
  const ruleText = (f: { rule_id: string; message: string; details: Record<string, unknown> }) =>
    t(`capital_plan.rule.${f.rule_id}`, { defaultValue: f.message, ...f.details });

  const header = (
    <PageHeader
      srTitle={t('capital_plan.title', { defaultValue: 'Capital plan' })}
      subtitle={t('capital_plan.subtitle', {
        defaultValue: 'Rank projects against the yearly budget and see what happens if one is delayed.',
      })}
      actions={
        <>
          <ModuleGuideButton content={capitalPlanGuide} />
          {plans.length > 0 && (
            <select
              aria-label={t('capital_plan.plan', { defaultValue: 'Plan' })}
              className={FIELD}
              value={plan?.id ?? ''}
              onChange={(e) => {
                setPlanId(e.target.value);
                setScenarioId(null);
                setSuggestion(null);
                setCompareWith('');
              }}
            >
              {plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </>
      }
    />
  );

  if (plansQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!plan) {
    const valid = draft.name.trim().length > 0 && draft.currency.trim().length === 3;
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        {plansQ.isError && <p role="alert" className="text-sm text-semantic-error">{getErrorMessage(plansQ.error)}</p>}
        <Card>
          <CardContent className="space-y-4 p-6">
            <EmptyState
              icon={<Wallet size={36} className="text-content-tertiary" />}
              title={t('capital_plan.no_plans_title', { defaultValue: 'No capital plan yet' })}
              description={t('capital_plan.no_plans_desc', {
                defaultValue: 'Create a plan with a currency and a start year, then add the yearly budget and the projects.',
              })}
            />
            <div className="flex flex-wrap items-end justify-center gap-3">
              <label className="text-sm">
                <span className="mb-1 block text-content-secondary">{t('capital_plan.name', { defaultValue: 'Name' })}</span>
                <input className={FIELD} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-content-secondary">{t('capital_plan.currency', { defaultValue: 'Currency' })}</span>
                <input
                  className={`${FIELD} w-24 uppercase`}
                  maxLength={3}
                  value={draft.currency}
                  onChange={(e) => setDraft({ ...draft, currency: e.target.value })}
                />
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-content-secondary">{t('capital_plan.start_year', { defaultValue: 'Start year' })}</span>
                <input
                  type="number"
                  className={`${FIELD} w-28`}
                  value={draft.start_year}
                  onChange={(e) => setDraft({ ...draft, start_year: Number(e.target.value) })}
                />
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-content-secondary">{t('capital_plan.horizon', { defaultValue: 'Years' })}</span>
                <input
                  type="number"
                  min={1}
                  max={15}
                  className={`${FIELD} w-20`}
                  value={draft.horizon}
                  onChange={(e) => setDraft({ ...draft, horizon: Number(e.target.value) })}
                />
              </label>
              <Button variant="primary" disabled={!valid} loading={createPlan.isPending} onClick={() => createPlan.mutate()}>
                {t('capital_plan.create_plan', { defaultValue: 'Create plan' })}
              </Button>
            </div>
            {error && <p role="alert" className="text-center text-sm text-semantic-error">{error}</p>}
          </CardContent>
        </Card>
      </div>
    );
  }

  const years = summary?.years ?? Array.from({ length: plan.horizon_years }, (_, i) => plan.start_year + i);
  const others = scenarios.filter((s) => s.id !== scenario?.id);

  return (
    <div className="space-y-5 animate-fade-in">
      {header}

      {/* Scenario tabs: the baseline, the what-ifs, and a way to copy the current one. */}
      <div className="flex flex-wrap items-center gap-2" role="tablist">
        {scenarios.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={s.id === scenario?.id}
            onClick={() => {
              setScenarioId(s.id);
              setSuggestion(null);
              setCompareWith('');
            }}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              s.id === scenario?.id
                ? 'bg-surface-primary text-content-primary shadow-sm ring-1 ring-border'
                : 'text-content-tertiary hover:text-content-secondary'
            }`}
          >
            {s.is_baseline ? t('capital_plan.baseline', { defaultValue: 'Baseline' }) : s.name}
          </button>
        ))}
        {cloneName === null ? (
          <Button variant="ghost" size="sm" icon={<Plus size={14} />} disabled={!scenario} onClick={() => setCloneName('')}>
            {t('capital_plan.new_scenario', { defaultValue: 'New scenario' })}
          </Button>
        ) : (
          <span className="inline-flex items-center gap-2">
            <input
              autoFocus
              className={FIELD}
              placeholder={t('capital_plan.scenario_name', { defaultValue: 'Scenario name' })}
              aria-label={t('capital_plan.scenario_name', { defaultValue: 'Scenario name' })}
              value={cloneName}
              onChange={(e) => setCloneName(e.target.value)}
            />
            <Button size="sm" variant="primary" disabled={!cloneName.trim()} loading={clone.isPending} onClick={() => clone.mutate(cloneName.trim())}>
              {t('capital_plan.copy_scenario', { defaultValue: 'Copy this scenario' })}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setCloneName(null)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" loading={importProjects.isPending} disabled={!scenario} onClick={() => importProjects.mutate()}>
          {t('capital_plan.import_projects', { defaultValue: 'Import projects' })}
        </Button>
        <Button variant="secondary" size="sm" icon={<Sparkles size={14} />} loading={suggest.isPending} disabled={!scenario || items.length === 0} onClick={() => suggest.mutate()}>
          {t('capital_plan.suggest', { defaultValue: 'Suggest funding' })}
        </Button>
        <label className="inline-flex items-center gap-2 text-sm text-content-secondary">
          <GitCompare size={14} />
          <select
            aria-label={t('capital_plan.compare', { defaultValue: 'Compare' })}
            className={FIELD}
            value={compareWith}
            disabled={others.length === 0}
            onChange={(e) => setCompareWith(e.target.value)}
          >
            <option value="">{t('capital_plan.compare', { defaultValue: 'Compare' })}</option>
            {others.map((s) => (
              <option key={s.id} value={s.id}>
                {s.is_baseline ? t('capital_plan.baseline', { defaultValue: 'Baseline' }) : s.name}
              </option>
            ))}
          </select>
        </label>
        <Button variant="secondary" size="sm" icon={<Download size={14} />} disabled={!scenario} onClick={() => scenario && capitalPlanApi.exportXlsx(scenario.id).catch(fail)}>
          {t('capital_plan.export', { defaultValue: 'Export' })}
        </Button>
      </div>

      {error && <p role="alert" className="text-sm text-semantic-error">{error}</p>}

      {suggestion && (
        <Card data-testid="suggestion">
          <CardContent className="space-y-3 p-4">
            <h2 className="text-sm font-semibold text-content-primary">
              {t('capital_plan.suggestion_title', { defaultValue: 'Suggested funding' })}
            </h2>
            {changes.length === 0 ? (
              <p className="text-sm text-content-secondary">
                {t('capital_plan.suggestion_none', { defaultValue: 'Nothing would change.' })}
              </p>
            ) : (
              <ul className="space-y-1 text-sm">
                {changes.map((c) => (
                  <li key={c.id} className="flex flex-wrap gap-x-2">
                    <span className="font-medium">{titleOf(c.id)}</span>
                    <span className="text-content-secondary">
                      {statusLabel(t, statusOf(c.id))} {'->'} {statusLabel(t, c.status)}
                    </span>
                    <span className="text-content-tertiary">
                      {c.reason} ({Math.round(c.confidence * 100)}%)
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs text-content-tertiary">
              {t('capital_plan.suggestion_note', { defaultValue: 'This is a proposal. Nothing changes until you apply it.' })}
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="primary"
                disabled={changes.length === 0}
                loading={apply.isPending}
                onClick={() => apply.mutate(changes.map((c) => ({ id: c.id, status: c.status })))}
              >
                {t('capital_plan.apply', { defaultValue: 'Apply' })}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSuggestion(null)}>
                {t('capital_plan.dismiss', { defaultValue: 'Dismiss' })}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {!itemsQ.isSuccess && !itemsQ.isError && <Skeleton className="h-64 w-full" />}
      {itemsQ.isError && (
        <p role="alert" className="text-sm text-semantic-error">
          {getErrorMessage(itemsQ.error)}
        </p>
      )}

      {itemsQ.isSuccess && items.length === 0 && (
        <EmptyState
          icon={<Wallet size={36} className="text-content-tertiary" />}
          title={t('capital_plan.empty_title', { defaultValue: 'No projects in this scenario yet' })}
          description={t('capital_plan.empty_desc', {
            defaultValue: 'Import the projects of this programme to see how their cost lands on the yearly budget.',
          })}
          action={{
            label: t('capital_plan.import_projects', { defaultValue: 'Import projects' }),
            onClick: () => importProjects.mutate(),
          }}
        />
      )}

      {items.length > 0 && (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-tertiary">
                  <th className="px-3 py-2">{t('capital_plan.col.project', { defaultValue: 'Project' })}</th>
                  <th className="px-2 py-2">{t('capital_plan.col.priority', { defaultValue: 'Priority' })}</th>
                  <th className="px-2 py-2">{t('capital_plan.col.status', { defaultValue: 'Status' })}</th>
                  <th className="px-2 py-2 text-right">{t('capital_plan.col.cost', { defaultValue: 'Cost' })}</th>
                  <th className="px-2 py-2 text-center">{t('capital_plan.col.start', { defaultValue: 'Start' })}</th>
                  {years.map((y) => (
                    <th key={y} className="px-2 py-2 text-right">
                      {y}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item: CapitalItem) => (
                  <tr key={item.id} className="border-b border-border/60" data-testid={`row-${item.id}`}>
                    <td className="px-3 py-1.5 font-medium text-content-primary">{item.title}</td>
                    <td className="px-2 py-1.5">
                      <select
                        aria-label={t('capital_plan.col.priority', { defaultValue: 'Priority' })}
                        className={FIELD}
                        value={item.priority}
                        onChange={(e) => patchItem.mutate({ id: item.id, body: { priority: Number(e.target.value) } })}
                      >
                        {[1, 2, 3, 4, 5].map((p) => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-1.5">
                      <select
                        aria-label={t('capital_plan.col.status', { defaultValue: 'Status' })}
                        className={FIELD}
                        value={item.status}
                        onChange={(e) => patchItem.mutate({ id: item.id, body: { status: e.target.value as ItemStatus } })}
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {statusLabel(t, s)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{money(item.total_cost)}</td>
                    <td className="px-2 py-1.5">
                      <span className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          data-testid={`earlier-${item.id}`}
                          aria-label={t('capital_plan.start_earlier', { defaultValue: 'Start one year earlier' })}
                          className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                          onClick={() => patchItem.mutate({ id: item.id, body: { start_year: shiftedStart(item, -1) } })}
                        >
                          <ChevronLeft size={14} />
                        </button>
                        <span className="w-10 text-center tabular-nums">{item.start_year}</span>
                        <button
                          type="button"
                          data-testid={`later-${item.id}`}
                          aria-label={t('capital_plan.start_later', { defaultValue: 'Start one year later' })}
                          className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                          onClick={() => patchItem.mutate({ id: item.id, body: { start_year: shiftedStart(item, 1) } })}
                        >
                          <ChevronRight size={14} />
                        </button>
                      </span>
                    </td>
                    {years.map((y) => {
                      const v = Number(spendById.get(item.id)?.[String(y)] ?? 0);
                      return (
                        <td
                          key={y}
                          data-testid={`cell-${item.id}-${y}`}
                          className={`px-2 py-1.5 text-right tabular-nums ${
                            item.status === 'deferred' ? 'text-content-tertiary line-through' : ''
                          } ${v > 0 ? 'bg-oe-blue/5' : 'text-content-tertiary'}`}
                        >
                          {v > 0 ? money(v) : '-'}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border">
                  <th colSpan={5} className="px-3 py-2 text-left font-semibold">
                    {t('capital_plan.row.envelope', { defaultValue: 'Envelope' })}
                  </th>
                  {years.map((y) => {
                    const row = summary?.rows.find((r) => r.year === y);
                    const single = isSingleSource(envelopes, y);
                    return (
                      <td key={y} className="px-2 py-1.5 text-right" data-testid={`envelope-${y}`}>
                        {single ? (
                          <input
                            type="number"
                            min={0}
                            aria-label={`${t('capital_plan.row.envelope', { defaultValue: 'Envelope' })} ${y}`}
                            className={`${FIELD} w-28 text-right`}
                            defaultValue={Number(row?.envelope ?? 0)}
                            key={`${y}-${row?.envelope ?? '0'}`}
                            onBlur={(e) => {
                              const next = String(Math.max(0, Number(e.target.value) || 0));
                              if (Number(next) !== Number(row?.envelope ?? 0)) {
                                saveEnvelopes.mutate(withYearAmount(envelopes, y, next));
                              }
                            }}
                          />
                        ) : (
                          <span title={t('capital_plan.sources', { defaultValue: 'Several funding sources' })}>
                            {money(row?.envelope ?? 0)}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
                <tr>
                  <th colSpan={5} className="px-3 py-1.5 text-left font-semibold">
                    {t('capital_plan.row.demand', { defaultValue: 'Demand' })}
                  </th>
                  {years.map((y) => (
                    <td key={y} className="px-2 py-1.5 text-right tabular-nums" data-testid={`demand-${y}`}>
                      {money(summary?.rows.find((r) => r.year === y)?.demand ?? 0)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th colSpan={5} className="px-3 py-1.5 text-left font-semibold">
                    {t('capital_plan.row.gap', { defaultValue: 'Gap' })}
                  </th>
                  {years.map((y) => {
                    const row = summary?.rows.find((r) => r.year === y);
                    const tone = gapTone(row?.gap ?? 0);
                    return (
                      <td
                        key={y}
                        data-testid={`gap-${y}`}
                        data-tone={tone}
                        title={`${t('capital_plan.cumulative', { defaultValue: 'Cumulative' })}: ${money(row?.cumulative_gap ?? 0)}`}
                        className={`px-2 py-1.5 text-right font-semibold tabular-nums ${
                          tone === 'short' ? 'bg-semantic-error/10 text-semantic-error' : 'text-content-primary'
                        }`}
                      >
                        {money(row?.gap ?? 0)}
                      </td>
                    );
                  })}
                </tr>
              </tfoot>
            </table>
          </CardContent>
        </Card>
      )}

      {compareWith && compareQ.data && (
        <Card data-testid="compare">
          <CardContent className="space-y-3 p-4">
            <h2 className="text-sm font-semibold">{t('capital_plan.compare_title', { defaultValue: 'Compared with the other scenario' })}</h2>
            <table className="text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-content-tertiary">
                  <th className="pr-4">{t('capital_plan.col.year', { defaultValue: 'Year' })}</th>
                  <th className="pr-4 text-right">{t('capital_plan.delta_demand', { defaultValue: 'Demand change' })}</th>
                  <th className="text-right">{t('capital_plan.delta_gap', { defaultValue: 'Gap change' })}</th>
                </tr>
              </thead>
              <tbody>
                {compareQ.data.years.map((y) => (
                  <tr key={y.year}>
                    <td className="pr-4">{y.year}</td>
                    <td className="pr-4 text-right tabular-nums">{money(y.delta_demand)}</td>
                    <td className="text-right tabular-nums">{money(y.delta_gap)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {compareQ.data.changed_items.length > 0 && (
              <ul className="list-disc pl-5 text-sm text-content-secondary">
                {compareQ.data.changed_items.map((c) => (
                  <li key={`${c.title}-${c.change}`}>
                    {c.title}:{' '}
                    {c.change === 'changed'
                      ? `${c.start_year_a} -> ${c.start_year_b}, ${statusLabel(t, c.status_a ?? '')} -> ${statusLabel(t, c.status_b ?? '')}`
                      : t(`capital_plan.change.${c.change}`, { defaultValue: c.change })}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      {summary && summary.findings.length > 0 && (
        <Card data-testid="findings">
          <CardContent className="space-y-2 p-4">
            <h2 className="text-sm font-semibold">{t('capital_plan.findings', { defaultValue: 'Checks' })}</h2>
            <ul className="space-y-1 text-sm">
              {summary.findings.map((f, i) => (
                <li key={`${f.rule_id}-${f.element_ref}-${i}`} className={f.severity === 'error' ? 'text-semantic-error' : 'text-content-secondary'}>
                  {ruleText(f)}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
