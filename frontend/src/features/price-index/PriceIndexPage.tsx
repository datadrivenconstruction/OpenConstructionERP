// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Price Index - bring costs from a base period and region to a target period
 * and region using stored construction cost index series and regional factors.
 *
 * Three areas, all working against platform-wide reference data:
 *   1. Index series: manage named cost indices and their period/value points.
 *   2. Regional factors: manage per-region cost factors.
 *   3. Adjust: post amounts and see base vs adjusted with the applied factor.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Trash2,
  Calculator,
  LineChart,
  MapPin,
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  ArrowRight,
  CalendarClock,
  Inbox,
  Building2,
  Library,
  Download,
} from 'lucide-react';
import { Button, Badge, Card, CardHeader, EmptyState, ErrorState, Input, PageHeader } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { parseDecimalInput, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import type { Project } from '@/features/projects/api';
import {
  listSeries,
  fetchSeries,
  createSeries,
  deleteSeries,
  addPoint,
  deletePoint,
  listLocationFactors,
  createLocationFactor,
  deleteLocationFactor,
  adjustAmounts,
  blankAdjustLine,
  isValidPeriod,
  isAdjustLineReady,
  formatFactor,
  factorDirection,
  escalatePreview,
  downloadEscalatePreviewCsv,
  listCostRegions,
  listCostCategories,
  isValidIsoDate,
  hasEscalateSelector,
  type AdjustLineInput,
  type AdjustResponse,
  type FactorDirection,
  type CostIndexSeries,
  type EscalatePreviewResponse,
} from './api';

const QK = {
  series: ['price-index', 'series'] as const,
  seriesDetail: (id: string) => ['price-index', 'series', id] as const,
  locations: ['price-index', 'locations'] as const,
};

export function PriceIndexPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('price_index.title', { defaultValue: 'Price Index' })}
        subtitle={t('price_index.subtitle', {
          defaultValue:
            'Bring an old rate library or a foreign benchmark to current-period money and your region using cost index series and regional factors.',
        })}
      />
      <PriceIndexContent />
    </div>
  );
}

function FactorArrow({ direction }: { direction: FactorDirection }) {
  if (direction === 'up') return <TrendingUp className="h-3.5 w-3.5 text-semantic-warning" aria-hidden />;
  if (direction === 'down') return <TrendingDown className="h-3.5 w-3.5 text-semantic-success" aria-hidden />;
  return <Minus className="h-3.5 w-3.5 text-content-tertiary" aria-hidden />;
}

function PriceIndexContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedSeriesId, setSelectedSeriesId] = useState<string | null>(null);

  const seriesListQ = useQuery({ queryKey: QK.series, queryFn: listSeries });
  const locationsQ = useQuery({ queryKey: QK.locations, queryFn: listLocationFactors });
  const seriesDetailQ = useQuery({
    queryKey: selectedSeriesId ? QK.seriesDetail(selectedSeriesId) : QK.seriesDetail('none'),
    queryFn: () => fetchSeries(selectedSeriesId as string),
    enabled: !!selectedSeriesId,
  });

  const seriesList = useMemo(() => seriesListQ.data ?? [], [seriesListQ.data]);
  const locations = useMemo(() => locationsQ.data ?? [], [locationsQ.data]);

  // Auto-select the first series once the list arrives so the points panel and
  // the adjust dropdown are never empty when data exists.
  useEffect(() => {
    if (selectedSeriesId) return;
    const first = seriesList[0];
    if (first) setSelectedSeriesId(first.id);
  }, [seriesList, selectedSeriesId]);

  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  // ── Series form state ──────────────────────────────────────────────────
  const [newSeriesName, setNewSeriesName] = useState('');

  const createSeriesMut = useMutation({
    mutationFn: () => createSeries({ name: newSeriesName.trim() }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: QK.series });
      setNewSeriesName('');
      setSelectedSeriesId(created.id);
    },
    onError,
  });

  const deleteSeriesMut = useMutation({
    mutationFn: (id: string) => deleteSeries(id),
    onSuccess: (_res, id) => {
      queryClient.invalidateQueries({ queryKey: QK.series });
      if (selectedSeriesId === id) setSelectedSeriesId(null);
    },
    onError,
  });

  // ── Point form state ───────────────────────────────────────────────────
  const [newPeriod, setNewPeriod] = useState('');
  const [newPointFactor, setNewPointFactor] = useState('');

  const addPointMut = useMutation({
    mutationFn: () =>
      addPoint(selectedSeriesId as string, {
        period: newPeriod.trim(),
        factor: toDecimalPayloadString(newPointFactor),
      }),
    onSuccess: () => {
      if (selectedSeriesId) queryClient.invalidateQueries({ queryKey: QK.seriesDetail(selectedSeriesId) });
      queryClient.invalidateQueries({ queryKey: QK.series });
      setNewPeriod('');
      setNewPointFactor('');
    },
    onError,
  });

  const deletePointMut = useMutation({
    mutationFn: (pointId: string) => deletePoint(selectedSeriesId as string, pointId),
    onSuccess: () => {
      if (selectedSeriesId) queryClient.invalidateQueries({ queryKey: QK.seriesDetail(selectedSeriesId) });
      queryClient.invalidateQueries({ queryKey: QK.series });
    },
    onError,
  });

  // ── Location factor form state ─────────────────────────────────────────
  const [newRegionCode, setNewRegionCode] = useState('');
  const [newRegionLabel, setNewRegionLabel] = useState('');
  const [newRegionFactor, setNewRegionFactor] = useState('');

  const createLocationMut = useMutation({
    mutationFn: () =>
      createLocationFactor({
        region_code: newRegionCode.trim(),
        label: newRegionLabel.trim(),
        factor: toDecimalPayloadString(newRegionFactor),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QK.locations });
      setNewRegionCode('');
      setNewRegionLabel('');
      setNewRegionFactor('');
    },
    onError,
  });

  const deleteLocationMut = useMutation({
    mutationFn: (id: string) => deleteLocationFactor(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QK.locations }),
    onError,
  });

  // ── Adjust panel state ─────────────────────────────────────────────────
  const [adjustSeriesId, setAdjustSeriesId] = useState('');
  const [lines, setLines] = useState<AdjustLineInput[]>([blankAdjustLine()]);
  const [adjustResult, setAdjustResult] = useState<AdjustResponse | null>(null);

  const effectiveAdjustSeries = adjustSeriesId || selectedSeriesId || seriesList[0]?.id || '';

  const adjustMut = useMutation({
    mutationFn: () => adjustAmounts(effectiveAdjustSeries, lines.filter(isAdjustLineReady)),
    onSuccess: (res) => setAdjustResult(res),
    onError,
  });

  const updateLine = (idx: number, patch: Partial<AdjustLineInput>) =>
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  const addLine = () => setLines((prev) => [...prev, blankAdjustLine()]);
  const removeLine = (idx: number) =>
    setLines((prev) => (prev.length <= 1 ? prev : prev.filter((_l, i) => i !== idx)));

  const readyLineCount = lines.filter(isAdjustLineReady).length;
  const canAdjust = !!effectiveAdjustSeries && readyLineCount > 0 && !adjustMut.isPending;

  const seriesDetail = seriesDetailQ.data;
  const points = seriesDetail?.points ?? [];

  const parsedPointFactor = parseDecimalInput(newPointFactor);
  const parsedRegionFactor = parseDecimalInput(newRegionFactor);
  const pointFactorValid = parsedPointFactor !== null && parsedPointFactor > 0;
  const regionFactorValid = parsedRegionFactor !== null && parsedRegionFactor > 0;

  if (seriesListQ.isError) {
    return (
      <ErrorState
        title={t('price_index.load_error', { defaultValue: 'Could not load price index data' })}
        onRetry={() => seriesListQ.refetch()}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        {/* ── Index series ─────────────────────────────────────────── */}
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <LineChart className="h-4 w-4 text-oe-blue" aria-hidden />
                {t('price_index.series_title', { defaultValue: 'Cost index series' })}
              </span>
            }
            subtitle={t('price_index.series_subtitle', {
              defaultValue: 'A named index and its value at each period. Escalation is the ratio between two periods.',
            })}
          />
          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap gap-2">
              {seriesListQ.isLoading ? (
                <span className="inline-flex items-center gap-2 text-sm text-content-tertiary">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  {t('common.loading', { defaultValue: 'Loading...' })}
                </span>
              ) : seriesList.length === 0 ? (
                <span className="text-sm text-content-tertiary">
                  {t('price_index.no_series', { defaultValue: 'No index series yet. Create one below.' })}
                </span>
              ) : (
                seriesList.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setSelectedSeriesId(s.id)}
                    className={
                      'rounded-lg border px-3 py-1.5 text-sm transition-colors ' +
                      (s.id === selectedSeriesId
                        ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                        : 'border-border text-content-secondary hover:border-content-tertiary')
                    }
                  >
                    {s.name}
                    <span className="ml-2 text-xs text-content-tertiary">
                      {t('price_index.point_count', { defaultValue: '{{count}} pts', count: s.point_count })}
                    </span>
                  </button>
                ))
              )}
            </div>

            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Input
                  label={t('price_index.new_series_name', { defaultValue: 'New series name' })}
                  value={newSeriesName}
                  onChange={(e) => setNewSeriesName(e.target.value)}
                  placeholder={t('price_index.new_series_ph', { defaultValue: 'e.g. General building index' })}
                />
              </div>
              <Button
                variant="secondary"
                icon={<Plus className="h-4 w-4" />}
                disabled={newSeriesName.trim() === '' || createSeriesMut.isPending}
                loading={createSeriesMut.isPending}
                onClick={() => createSeriesMut.mutate()}
              >
                {t('price_index.add_series', { defaultValue: 'Add series' })}
              </Button>
            </div>

            {/* Selected series points */}
            {selectedSeriesId && (
              <div className="rounded-lg border border-border-light p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-medium text-content-primary">
                    {seriesDetail?.name ?? t('price_index.points', { defaultValue: 'Index points' })}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 className="h-3.5 w-3.5" />}
                    onClick={() => deleteSeriesMut.mutate(selectedSeriesId)}
                    loading={deleteSeriesMut.isPending}
                  >
                    {t('price_index.delete_series', { defaultValue: 'Delete series' })}
                  </Button>
                </div>

                {seriesDetailQ.isLoading ? (
                  <span className="text-sm text-content-tertiary">
                    {t('common.loading', { defaultValue: 'Loading...' })}
                  </span>
                ) : points.length === 0 ? (
                  <span className="text-sm text-content-tertiary">
                    {t('price_index.no_points', { defaultValue: 'No points yet. Add a period and its index value.' })}
                  </span>
                ) : (
                  <ul className="divide-y divide-border-light">
                    {points.map((p) => (
                      <li key={p.id} className="flex items-center justify-between py-1.5 text-sm">
                        <span className="font-mono text-content-secondary">{p.period}</span>
                        <span className="flex items-center gap-3">
                          <span className="font-medium text-content-primary">{formatFactor(p.factor)}</span>
                          <button
                            type="button"
                            aria-label={t('common.delete', { defaultValue: 'Delete' })}
                            className="text-content-tertiary hover:text-semantic-error"
                            onClick={() => deletePointMut.mutate(p.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="mt-3 flex items-end gap-2">
                  <Input
                    label={t('price_index.period', { defaultValue: 'Period' })}
                    value={newPeriod}
                    onChange={(e) => setNewPeriod(e.target.value)}
                    placeholder="2026-01"
                    className="font-mono"
                    error={
                      newPeriod !== '' && !isValidPeriod(newPeriod)
                        ? t('price_index.period_invalid', { defaultValue: 'Use YYYY-MM' })
                        : undefined
                    }
                  />
                  <Input
                    label={t('price_index.index_value', { defaultValue: 'Index value' })}
                    value={newPointFactor}
                    onChange={(e) => setNewPointFactor(e.target.value)}
                    placeholder="1.00"
                    inputMode="decimal"
                  />
                  <Button
                    variant="secondary"
                    icon={<Plus className="h-4 w-4" />}
                    disabled={!isValidPeriod(newPeriod) || !pointFactorValid || addPointMut.isPending}
                    loading={addPointMut.isPending}
                    onClick={() => addPointMut.mutate()}
                  >
                    {t('price_index.add_point', { defaultValue: 'Add' })}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* ── Regional factors ─────────────────────────────────────── */}
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <MapPin className="h-4 w-4 text-oe-blue" aria-hidden />
                {t('price_index.regions_title', { defaultValue: 'Regional factors' })}
              </span>
            }
            subtitle={t('price_index.regions_subtitle', {
              defaultValue: 'How each region sits relative to a national baseline of 1. A missing region is treated as 1.',
            })}
          />
          <div className="mt-4 space-y-4">
            {locationsQ.isLoading ? (
              <span className="text-sm text-content-tertiary">
                {t('common.loading', { defaultValue: 'Loading...' })}
              </span>
            ) : locations.length === 0 ? (
              <EmptyState
                icon={<MapPin className="h-5 w-5" />}
                title={t('price_index.no_regions', { defaultValue: 'No regional factors yet' })}
                description={t('price_index.no_regions_desc', {
                  defaultValue: 'Add a region code and its cost factor to adjust across locations.',
                })}
              />
            ) : (
              <ul className="divide-y divide-border-light">
                {locations.map((lf) => (
                  <li key={lf.id} className="flex items-center justify-between py-1.5 text-sm">
                    <span className="min-w-0">
                      <span className="font-mono text-content-primary">{lf.region_code}</span>
                      {lf.label && <span className="ml-2 text-content-tertiary">{lf.label}</span>}
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="inline-flex items-center gap-1 font-medium text-content-primary">
                        <FactorArrow direction={factorDirection(lf.factor)} />
                        {formatFactor(lf.factor)}
                      </span>
                      <button
                        type="button"
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        className="text-content-tertiary hover:text-semantic-error"
                        onClick={() => deleteLocationMut.mutate(lf.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <div className="grid grid-cols-2 gap-2">
              <Input
                label={t('price_index.region_code', { defaultValue: 'Region code' })}
                value={newRegionCode}
                onChange={(e) => setNewRegionCode(e.target.value)}
                placeholder="HIGH_COST_METRO"
                className="font-mono"
              />
              <Input
                label={t('price_index.region_factor', { defaultValue: 'Factor' })}
                value={newRegionFactor}
                onChange={(e) => setNewRegionFactor(e.target.value)}
                placeholder="1.15"
                inputMode="decimal"
              />
              <div className="col-span-2">
                <Input
                  label={t('price_index.region_label', { defaultValue: 'Label (optional)' })}
                  value={newRegionLabel}
                  onChange={(e) => setNewRegionLabel(e.target.value)}
                  placeholder={t('price_index.region_label_ph', { defaultValue: 'High-cost metro area' })}
                />
              </div>
              <div className="col-span-2">
                <Button
                  variant="secondary"
                  icon={<Plus className="h-4 w-4" />}
                  disabled={newRegionCode.trim() === '' || !regionFactorValid || createLocationMut.isPending}
                  loading={createLocationMut.isPending}
                  onClick={() => createLocationMut.mutate()}
                >
                  {t('price_index.add_region', { defaultValue: 'Add regional factor' })}
                </Button>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* ── Adjust panel ───────────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Calculator className="h-4 w-4 text-oe-blue" aria-hidden />
              {t('price_index.adjust_title', { defaultValue: 'Adjust amounts' })}
            </span>
          }
          subtitle={t('price_index.adjust_subtitle', {
            defaultValue: 'Bring amounts from a base period and region to a target period and region.',
          })}
        />
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-content-primary">
                {t('price_index.index_series', { defaultValue: 'Index series' })}
              </span>
              <select
                value={effectiveAdjustSeries}
                onChange={(e) => setAdjustSeriesId(e.target.value)}
                className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              >
                {seriesList.length === 0 && (
                  <option value="">{t('price_index.no_series_option', { defaultValue: 'No series available' })}</option>
                )}
                {seriesList.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="space-y-2">
            {lines.map((line, idx) => (
              <div key={idx} className="grid grid-cols-1 items-end gap-2 sm:grid-cols-12">
                <div className="sm:col-span-3">
                  <Input
                    label={idx === 0 ? t('price_index.amount', { defaultValue: 'Amount' }) : undefined}
                    value={line.amount}
                    onChange={(e) => updateLine(idx, { amount: e.target.value })}
                    placeholder="1000.00"
                    inputMode="decimal"
                  />
                </div>
                <div className="sm:col-span-2">
                  <Input
                    label={idx === 0 ? t('price_index.base_period', { defaultValue: 'Base period' }) : undefined}
                    value={line.base_period}
                    onChange={(e) => updateLine(idx, { base_period: e.target.value })}
                    placeholder="2019-01"
                    className="font-mono"
                  />
                </div>
                <div className="sm:col-span-2">
                  <Input
                    label={idx === 0 ? t('price_index.target_period', { defaultValue: 'Target period' }) : undefined}
                    value={line.target_period}
                    onChange={(e) => updateLine(idx, { target_period: e.target.value })}
                    placeholder="2026-01"
                    className="font-mono"
                  />
                </div>
                <div className="sm:col-span-2">
                  <RegionSelect
                    label={idx === 0 ? t('price_index.base_region', { defaultValue: 'Base region' }) : undefined}
                    value={line.base_region ?? ''}
                    options={locations.map((l) => l.region_code)}
                    onChange={(v) => updateLine(idx, { base_region: v })}
                    baselineLabel={t('price_index.baseline', { defaultValue: 'National (1)' })}
                  />
                </div>
                <div className="sm:col-span-2">
                  <RegionSelect
                    label={idx === 0 ? t('price_index.target_region', { defaultValue: 'Target region' }) : undefined}
                    value={line.target_region ?? ''}
                    options={locations.map((l) => l.region_code)}
                    onChange={(v) => updateLine(idx, { target_region: v })}
                    baselineLabel={t('price_index.baseline', { defaultValue: 'National (1)' })}
                  />
                </div>
                <div className="flex sm:col-span-1">
                  <button
                    type="button"
                    aria-label={t('price_index.remove_line', { defaultValue: 'Remove line' })}
                    className="h-9 px-2 text-content-tertiary hover:text-semantic-error disabled:opacity-30"
                    disabled={lines.length <= 1}
                    onClick={() => removeLine(idx)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="ghost" size="sm" icon={<Plus className="h-4 w-4" />} onClick={addLine}>
              {t('price_index.add_line', { defaultValue: 'Add line' })}
            </Button>
            <Button
              variant="primary"
              icon={<Calculator className="h-4 w-4" />}
              disabled={!canAdjust}
              loading={adjustMut.isPending}
              onClick={() => adjustMut.mutate()}
            >
              {t('price_index.run_adjust', { defaultValue: 'Adjust' })}
            </Button>
          </div>

          {adjustResult && <AdjustResults result={adjustResult} />}
        </div>
      </Card>

      {/* ── Escalate the estimate's own stored rates to a date ─────── */}
      <EscalatePanel seriesList={seriesList} />
    </div>
  );
}

function RegionSelect({
  label,
  value,
  options,
  onChange,
  baselineLabel,
}: {
  label?: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  baselineLabel: string;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      {label && <span className="font-medium text-content-primary">{label}</span>}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
      >
        <option value="">{baselineLabel}</option>
        {options.map((code) => (
          <option key={code} value={code}>
            {code}
          </option>
        ))}
      </select>
    </label>
  );
}

function AdjustResults({ result }: { result: AdjustResponse }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto rounded-lg border border-border-light">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
            <th className="px-3 py-2 font-medium">{t('price_index.col_amount', { defaultValue: 'Base amount' })}</th>
            <th className="px-3 py-2 font-medium">{t('price_index.col_move', { defaultValue: 'From / to' })}</th>
            <th className="px-3 py-2 text-right font-medium">
              {t('price_index.col_factor', { defaultValue: 'Applied factor' })}
            </th>
            <th className="px-3 py-2 text-right font-medium">
              {t('price_index.col_adjusted', { defaultValue: 'Adjusted amount' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {result.results.map((r, i) => (
            <tr key={i} className="border-b border-border-light last:border-0">
              <td className="px-3 py-2 font-mono text-content-secondary">{r.amount}</td>
              <td className="px-3 py-2 text-content-secondary">
                <span className="inline-flex flex-wrap items-center gap-1">
                  <span className="font-mono">{r.base_period}</span>
                  {r.base_region && <span className="text-content-tertiary">/{r.base_region}</span>}
                  <ArrowRight className="h-3 w-3 text-content-tertiary" aria-hidden />
                  <span className="font-mono">{r.target_period}</span>
                  {r.target_region && <span className="text-content-tertiary">/{r.target_region}</span>}
                </span>
                {r.note && <div className="text-xs text-semantic-warning">{r.note}</div>}
                {r.error && <div className="text-xs text-semantic-error">{r.error}</div>}
              </td>
              <td className="px-3 py-2 text-right">
                {r.applied_factor ? (
                  <span className="inline-flex items-center justify-end gap-1 font-medium">
                    <FactorArrow direction={factorDirection(r.applied_factor)} />
                    {formatFactor(r.applied_factor)}
                  </span>
                ) : (
                  <span className="text-content-tertiary">&mdash;</span>
                )}
              </td>
              <td className="px-3 py-2 text-right font-semibold text-content-primary">
                {r.adjusted_amount ?? (
                  <Badge variant="error" size="sm">
                    {t('price_index.not_adjusted', { defaultValue: 'not adjusted' })}
                  </Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Escalate the estimate's OWN stored cost rates to a chosen date. Unlike the
 * Adjust panel (which escalates numbers you type in), this reads the stored
 * cost items, brings each rate from its own capture date (price_as_of) to the
 * target date on the chosen series, and shows which lines move and by how much.
 * Strictly read-only: nothing is written back to the cost items or the BOQ.
 */
type EscalateScope = 'catalogue' | 'project';

function EscalatePanel({ seriesList }: { seriesList: CostIndexSeries[] }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [scope, setScope] = useState<EscalateScope>('catalogue');
  const [targetDate, setTargetDate] = useState('');
  const [seriesId, setSeriesId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [region, setRegion] = useState('');
  const [category, setCategory] = useState('');
  const [result, setResult] = useState<EscalatePreviewResponse | null>(null);

  const projectMode = scope === 'project';

  // Facets from the cost catalogue so the selectors offer the same region
  // codes and categories the escalate-preview endpoint actually filters on.
  const regionsQ = useQuery({ queryKey: ['price-index', 'cost-regions'], queryFn: listCostRegions });
  const categoriesQ = useQuery({
    queryKey: ['price-index', 'cost-categories', region],
    queryFn: () => listCostCategories(region || null),
  });
  const regions = regionsQ.data ?? [];
  const categories = categoriesQ.data ?? [];

  // Projects for the "this project" scope. Fetched only in project mode; the
  // app-wide active project seeds the picker so it lands on what the user is
  // already working on.
  const projectsQ = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
    enabled: projectMode,
  });
  const projects = projectsQ.data ?? [];

  const noSeries = seriesList.length === 0;
  const seriesRequired = seriesList.length > 1;

  // With exactly one series, adopt it so the request is explicit (the backend
  // would default to the sole series anyway, but selecting keeps the UI honest).
  useEffect(() => {
    if (seriesId) return;
    if (seriesList.length === 1) {
      const only = seriesList[0];
      if (only) setSeriesId(only.id);
    }
  }, [seriesList, seriesId]);

  // Default the project picker to the active project (or the first one) once
  // the user switches to project scope.
  useEffect(() => {
    if (!projectMode || projectId) return;
    const fallback = activeProjectId || projects[0]?.id || '';
    if (fallback) setProjectId(fallback);
  }, [projectMode, projectId, activeProjectId, projects]);

  const dateValid = isValidIsoDate(targetDate);
  // In project scope the project itself is the selector (region/category only
  // narrow it); in catalogue scope a region or category is required.
  const selectorReady = projectMode ? projectId !== '' : hasEscalateSelector({ region, category });
  const seriesReady = !seriesRequired || seriesId !== '';

  const previewMut = useMutation({
    mutationFn: () =>
      escalatePreview({
        target_date: targetDate,
        series_id: seriesId || null,
        project_id: projectMode ? projectId || null : null,
        region: region || null,
        category: category || null,
      }),
    onSuccess: (res) => setResult(res),
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      }),
  });

  const canPreview = !noSeries && dateValid && selectorReady && seriesReady && !previewMut.isPending;

  const selectClass =
    'h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary ' +
    'focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-oe-blue" aria-hidden />
            {t('price_index.escalate_title', { defaultValue: 'Escalate estimate to date' })}
          </span>
        }
        subtitle={t('price_index.escalate_subtitle', {
          defaultValue:
            'Bring your stored cost rates forward to a chosen date using an index series, so you can see which lines move and by how much. Read-only, nothing is written back.',
        })}
      />
      <div className="mt-4 space-y-4">
        <p className="text-xs text-content-tertiary">
          {t('price_index.escalate_help', {
            defaultValue:
              'Each rate is escalated from its own capture date (price_as_of) to the target date. Rates with no capture date on record are listed but left unescalated.',
          })}
        </p>

        {noSeries ? (
          <EmptyState
            icon={<LineChart className="h-5 w-5" />}
            title={t('price_index.escalate_no_series', { defaultValue: 'No index series yet' })}
            description={t('price_index.escalate_no_series_desc', {
              defaultValue:
                'Create a cost index series above and add its period points, then escalate your rates against it.',
            })}
          />
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium text-content-primary">
                  {t('price_index.escalate_scope', { defaultValue: 'Rates to escalate' })}
                </span>
                <div className="inline-flex overflow-hidden rounded-lg border border-border">
                  <button
                    type="button"
                    aria-pressed={scope === 'catalogue'}
                    onClick={() => setScope('catalogue')}
                    className={
                      'inline-flex h-9 items-center gap-1.5 px-3 text-sm transition-colors ' +
                      (scope === 'catalogue'
                        ? 'bg-oe-blue/10 text-oe-blue'
                        : 'text-content-secondary hover:bg-surface-secondary')
                    }
                  >
                    <Library className="h-3.5 w-3.5" aria-hidden />
                    {t('price_index.escalate_scope_catalogue', { defaultValue: 'Whole catalogue' })}
                  </button>
                  <button
                    type="button"
                    aria-pressed={scope === 'project'}
                    onClick={() => setScope('project')}
                    className={
                      'inline-flex h-9 items-center gap-1.5 border-l border-border px-3 text-sm transition-colors ' +
                      (scope === 'project'
                        ? 'bg-oe-blue/10 text-oe-blue'
                        : 'text-content-secondary hover:bg-surface-secondary')
                    }
                  >
                    <Building2 className="h-3.5 w-3.5" aria-hidden />
                    {t('price_index.escalate_scope_project', { defaultValue: 'This project' })}
                  </button>
                </div>
              </label>

              <div className="w-44">
                <Input
                  type="date"
                  label={t('price_index.target_date', { defaultValue: 'Target date' })}
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                />
              </div>

              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium text-content-primary">
                  {t('price_index.index_series', { defaultValue: 'Index series' })}
                </span>
                <select value={seriesId} onChange={(e) => setSeriesId(e.target.value)} className={selectClass}>
                  {seriesRequired && (
                    <option value="">
                      {t('price_index.escalate_pick_series', { defaultValue: 'Select a series' })}
                    </option>
                  )}
                  {seriesList.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>

              {projectMode && (
                <label className="flex flex-col gap-1.5 text-sm">
                  <span className="font-medium text-content-primary">
                    {t('price_index.escalate_project', { defaultValue: 'Project' })}
                  </span>
                  <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className={selectClass}>
                    {projects.length === 0 && (
                      <option value="">
                        {projectsQ.isLoading
                          ? t('common.loading', { defaultValue: 'Loading...' })
                          : t('price_index.escalate_no_projects', { defaultValue: 'No projects' })}
                      </option>
                    )}
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium text-content-primary">
                  {t('price_index.escalate_region', { defaultValue: 'Region' })}
                </span>
                <select
                  value={region}
                  onChange={(e) => {
                    setRegion(e.target.value);
                    setCategory('');
                  }}
                  className={selectClass}
                >
                  <option value="">{t('price_index.escalate_any_region', { defaultValue: 'Any region' })}</option>
                  {regions.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium text-content-primary">
                  {t('price_index.escalate_category', { defaultValue: 'Category' })}
                </span>
                <select value={category} onChange={(e) => setCategory(e.target.value)} className={selectClass}>
                  <option value="">
                    {t('price_index.escalate_any_category', { defaultValue: 'Any category' })}
                  </option>
                  {categories.map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>
              </label>

              <Button
                variant="primary"
                icon={<CalendarClock className="h-4 w-4" />}
                disabled={!canPreview}
                loading={previewMut.isPending}
                onClick={() => previewMut.mutate()}
              >
                {t('price_index.escalate_run', { defaultValue: 'Preview escalation' })}
              </Button>
            </div>

            {projectMode ? (
              <p className="text-xs text-content-tertiary">
                {t('price_index.escalate_project_hint', {
                  defaultValue:
                    'Escalates only the cost rates used by this project. A region or category narrows that set further.',
                })}
              </p>
            ) : (
              !selectorReady && (
                <p className="text-xs text-content-tertiary">
                  {t('price_index.escalate_need_selector', {
                    defaultValue: 'Pick a region or a category to choose which stored rates to escalate.',
                  })}
                </p>
              )
            )}

            {previewMut.isPending ? (
              <span className="inline-flex items-center gap-2 text-sm text-content-tertiary">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {t('common.loading', { defaultValue: 'Loading...' })}
              </span>
            ) : (
              result && <EscalateResults result={result} />
            )}
          </>
        )}
      </div>
    </Card>
  );
}

/** Append an ISO 4217 currency label to a decimal string without touching the
 *  number itself. Pure string join - never float math on money. */
function withCurrency(value: string, currency: string): string {
  return currency ? `${value} ${currency}` : value;
}

function EscalateResults({ result }: { result: EscalatePreviewResponse }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  if (result.item_count === 0) {
    return (
      <EmptyState
        icon={<Inbox className="h-5 w-5" />}
        title={t('price_index.escalate_no_items', { defaultValue: 'No cost items matched' })}
        description={t('price_index.escalate_no_items_desc', {
          defaultValue: 'No stored cost rates matched these filters. Widen the region or category and preview again.',
        })}
      />
    );
  }

  const skipped = result.item_count - result.escalatable_count;
  // Deep-link target for the "Open estimate" exit: only in project scope, and
  // only when the response actually carries the project id (const so the
  // truthiness narrowing below holds inside the click handler).
  const projectId = result.scope === 'project' ? result.project_id : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {result.scope === 'project' && result.project_name && (
            <Badge variant="blue" size="sm">
              {t('price_index.escalate_scope_project_badge', {
                defaultValue: 'rates used in {{project}}',
                project: result.project_name,
              })}
            </Badge>
          )}
          <Badge variant="success" size="sm">
            {t('price_index.escalate_count_ok', {
              defaultValue: '{{count}} escalatable',
              count: result.escalatable_count,
            })}
          </Badge>
          {skipped > 0 && (
            <Badge variant="neutral" size="sm">
              {t('price_index.escalate_count_skipped', {
                defaultValue: '{{count}} left as-is',
                count: skipped,
              })}
            </Badge>
          )}
          <span className="text-content-tertiary">
            {t('price_index.escalate_summary_to', {
              defaultValue: 'to {{period}} using {{series}}',
              period: result.target_period,
              series: result.series_name,
            })}
          </span>
        </div>

        {/* Give the read-only result an exit: export the exact rates as CSV,
            and in project scope jump straight to that project's estimate. */}
        <div className="flex flex-wrap items-center gap-2">
          {projectId && (
            <Button
              variant="secondary"
              size="sm"
              icon={<ArrowRight className="h-4 w-4" />}
              onClick={() => {
                setActiveProject(projectId, result.project_name ?? '');
                navigate(`/boq?project=${encodeURIComponent(projectId)}`);
              }}
            >
              {t('price_index.escalate_open_estimate', { defaultValue: 'Open estimate' })}
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            icon={<Download className="h-4 w-4" />}
            onClick={() => downloadEscalatePreviewCsv(result)}
          >
            {t('price_index.escalate_export_csv', { defaultValue: 'Export escalated rates (CSV)' })}
          </Button>
        </div>
      </div>

      {result.project_fallback && (
        <p className="text-xs text-semantic-warning">
          {t('price_index.escalate_fallback_note', {
            defaultValue:
              'No cost-item links were found on this project, so its region catalogue rates are shown instead.',
          })}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-border-light">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
              <th className="px-3 py-2 font-medium">{t('price_index.escalate_col_code', { defaultValue: 'Code' })}</th>
              <th className="px-3 py-2 font-medium">{t('price_index.escalate_col_unit', { defaultValue: 'Unit' })}</th>
              <th className="px-3 py-2 text-right font-medium">
                {t('price_index.escalate_col_base', { defaultValue: 'Base rate' })}
              </th>
              <th className="px-3 py-2 font-medium">
                {t('price_index.escalate_col_base_date', { defaultValue: 'Base date' })}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('price_index.escalate_col_factor', { defaultValue: 'Factor' })}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('price_index.escalate_col_escalated', { defaultValue: 'Escalated rate' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {result.results.map((r) => (
              <tr
                key={r.cost_item_id}
                className={
                  'border-b border-border-light last:border-0 ' +
                  (r.escalatable ? '' : 'bg-surface-secondary/40 text-content-tertiary')
                }
              >
                <td className="px-3 py-2 font-mono text-content-secondary">{r.code}</td>
                <td className="px-3 py-2 text-content-secondary">{r.unit || '-'}</td>
                <td className="px-3 py-2 text-right font-mono text-content-secondary">
                  {r.base_rate != null ? withCurrency(r.base_rate, r.currency) : '-'}
                </td>
                <td className="px-3 py-2 font-mono text-content-secondary">{r.base_date ?? '-'}</td>
                {r.escalatable ? (
                  <>
                    <td className="px-3 py-2 text-right">
                      <span className="inline-flex items-center justify-end gap-1 font-medium text-content-primary">
                        <FactorArrow direction={factorDirection(r.factor)} />
                        {formatFactor(r.factor)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono font-semibold text-content-primary">
                      {r.escalated_rate != null ? withCurrency(r.escalated_rate, r.currency) : '-'}
                    </td>
                  </>
                ) : (
                  <td className="px-3 py-2 text-xs text-semantic-warning" colSpan={2}>
                    {r.note ?? t('price_index.escalate_skipped', { defaultValue: 'cannot escalate' })}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
