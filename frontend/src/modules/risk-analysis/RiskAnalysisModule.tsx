import { useState, useMemo, useCallback } from 'react';
import { triggerDownload } from '@/shared/lib/api';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Dices,
  Play,
  Settings2,
  Loader2,
  ChevronDown,
  ChevronRight,
  Info,
  Download,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  runSimulation,
  generateDefaultParams,
  type RiskParameter,
  type SimulationResult,
  type DistributionType,
  type BOQPositionForRisk,
} from './data/montecarlo';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCurrency(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${n < 0 ? '-' : ''}${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${n < 0 ? '-' : ''}${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(0);
}

// ---------------------------------------------------------------------------
// Percentile Card
// ---------------------------------------------------------------------------

function PercentileCard({
  label,
  value,
  variant = 'default',
}: {
  label: string;
  value: number;
  variant?: 'default' | 'green' | 'orange' | 'red';
}) {
  const borderClass =
    variant === 'green'
      ? 'border-emerald-400/50 bg-emerald-50/50 dark:bg-emerald-950/20'
      : variant === 'orange'
        ? 'border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20'
        : variant === 'red'
          ? 'border-rose-400/50 bg-rose-50/50 dark:bg-rose-950/20'
          : 'border-border-light bg-surface-secondary/30';

  const valueClass =
    variant === 'green'
      ? 'text-emerald-700 dark:text-emerald-400'
      : variant === 'orange'
        ? 'text-amber-700 dark:text-amber-400'
        : variant === 'red'
          ? 'text-rose-700 dark:text-rose-400'
          : 'text-content-primary';

  return (
    <div className={`rounded-lg border px-3 py-2.5 ${borderClass}`}>
      <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
        {label}
      </div>
      <div className={`text-sm font-bold tabular-nums mt-0.5 ${valueClass}`}>
        {fmtCurrency(value)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Histogram
// ---------------------------------------------------------------------------

function Histogram({
  result,
  t,
}: {
  result: SimulationResult;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const { histogram, percentiles } = result;
  const maxCount = useMemo(() => Math.max(...histogram.map((b) => b.count), 1), [histogram]);
  const minVal = histogram[0]?.binStart ?? 0;
  const maxVal = histogram[histogram.length - 1]?.binEnd ?? 0;
  const range = maxVal - minVal;

  const p50Pct = range > 0 ? ((percentiles.p50 - minVal) / range) * 100 : 50;
  const p80Pct = range > 0 ? ((percentiles.p80 - minVal) / range) * 100 : 80;

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
        {t('risk.distribution', { defaultValue: 'Cost Distribution (Histogram)' })}
      </h4>
      <div className="relative">
        <div className="flex items-end gap-px h-36">
          {histogram.map((bin, idx) => {
            const heightPct = maxCount > 0 ? (bin.count / maxCount) * 100 : 0;
            const binMid = (bin.binStart + bin.binEnd) / 2;
            const isLeftOfP50 = binMid < percentiles.p50;
            const isRightOfP80 = binMid > percentiles.p80;

            let barColor = 'bg-blue-400/70 hover:bg-blue-500';
            if (isLeftOfP50) barColor = 'bg-emerald-400/60 hover:bg-emerald-500';
            else if (isRightOfP80) barColor = 'bg-rose-400/60 hover:bg-rose-500';

            return (
              <div
                key={idx}
                className="flex-1 flex flex-col justify-end"
                title={`${fmtCurrency(bin.binStart)} – ${fmtCurrency(bin.binEnd)}: ${bin.count} (${(bin.frequency * 100).toFixed(1)}%)`}
              >
                <div
                  className={`w-full rounded-t-sm transition-colors ${barColor}`}
                  style={{ height: `${Math.max(heightPct, 1)}%` }}
                />
              </div>
            );
          })}
        </div>

        {range > 0 && (
          <>
            <div
              className="absolute bottom-0 top-0 w-px border-l-2 border-dashed border-emerald-600 dark:border-emerald-400 pointer-events-none"
              style={{ left: `${Math.min(Math.max(p50Pct, 0), 100)}%` }}
            >
              <span className="absolute -top-5 -translate-x-1/2 text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 whitespace-nowrap bg-surface-primary/80 px-1 rounded">
                P50
              </span>
            </div>
            <div
              className="absolute bottom-0 top-0 w-px border-l-2 border-dashed border-amber-600 dark:border-amber-400 pointer-events-none"
              style={{ left: `${Math.min(Math.max(p80Pct, 0), 100)}%` }}
            >
              <span className="absolute -top-5 -translate-x-1/2 text-[10px] font-semibold text-amber-700 dark:text-amber-400 whitespace-nowrap bg-surface-primary/80 px-1 rounded">
                P80
              </span>
            </div>
          </>
        )}
      </div>

      <div className="flex justify-between text-[10px] text-content-quaternary tabular-nums">
        <span>{fmtCurrency(minVal)}</span>
        <span>{fmtCurrency(maxVal)}</span>
      </div>

      <div className="flex items-center justify-center gap-5 pt-1">
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-emerald-400/60" />
          <span className="text-2xs text-content-tertiary">{'< P50'}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-blue-400/70" />
          <span className="text-2xs text-content-tertiary">P50 – P80</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-rose-400/60" />
          <span className="text-2xs text-content-tertiary">{'> P80'}</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Risk Drivers Table
// ---------------------------------------------------------------------------

function RiskDriversTable({
  drivers,
  t,
}: {
  drivers: SimulationResult['riskDrivers'];
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  if (drivers.length === 0) return null;
  const top = drivers.slice(0, 10);

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
        {t('risk.top_drivers', { defaultValue: 'Top 10 Risk Drivers' })}
      </h4>
      <div className="border border-border-light rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-surface-tertiary/50">
              <th className="px-3 py-2 text-left font-medium text-content-secondary">
                {t('boq.ordinal', { defaultValue: 'Ordinal' })}
              </th>
              <th className="px-3 py-2 text-left font-medium text-content-secondary">
                {t('boq.description', { defaultValue: 'Description' })}
              </th>
              <th className="px-3 py-2 text-right font-medium text-content-secondary">
                {t('risk.base_cost', { defaultValue: 'Base Cost' })}
              </th>
              <th className="px-3 py-2 text-right font-medium text-content-secondary">
                {t('risk.variance_share', { defaultValue: 'Variance Share' })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {top.map((driver, idx) => (
              <tr
                key={driver.positionId}
                className={`hover:bg-surface-secondary/30 transition-colors ${idx % 2 === 0 ? 'bg-surface-primary/50' : ''}`}
              >
                <td className="px-3 py-2 font-mono text-content-tertiary">{driver.ordinal}</td>
                <td className="px-3 py-2 text-content-primary max-w-[240px] truncate" title={driver.description}>
                  {driver.description || '-'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums font-medium text-content-primary">
                  {fmtCurrency(driver.baseCost)}
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20 h-2 bg-surface-tertiary rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-rose-500/70"
                        style={{ width: `${Math.min(driver.contributionPct, 100)}%` }}
                      />
                    </div>
                    <span className="tabular-nums font-medium text-content-secondary w-12 text-right">
                      {driver.contributionPct.toFixed(1)}%
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Parameter Editor Row
// ---------------------------------------------------------------------------

function ParamRow({
  param,
  onChange,
}: {
  param: RiskParameter;
  onChange: (updated: RiskParameter) => void;
}) {
  const { t } = useTranslation();
  return (
    <tr className="hover:bg-surface-secondary/30 transition-colors">
      <td className="px-3 py-1.5 font-mono text-2xs text-content-tertiary">{param.ordinal}</td>
      <td className="px-3 py-1.5 text-xs text-content-primary max-w-[200px] truncate" title={param.description}>
        {param.description || '-'}
      </td>
      <td className="px-3 py-1.5 text-right text-xs tabular-nums">{fmtCurrency(param.baseCost)}</td>
      <td className="px-1 py-1.5">
        <input
          type="number"
          step="0.01"
          min="0.01"
          max="1.00"
          value={param.optimistic}
          onChange={(e) => onChange({ ...param, optimistic: parseFloat(e.target.value) || 0.85 })}
          className="w-16 rounded border border-border bg-surface-secondary px-1.5 py-1 text-xs text-center tabular-nums"
          aria-label={`${t('risk.optimistic', { defaultValue: 'Optimistic' })} ${param.ordinal}`}
        />
      </td>
      <td className="px-1 py-1.5">
        <input
          type="number"
          step="0.01"
          min="0.50"
          max="3.00"
          value={param.pessimistic}
          onChange={(e) => onChange({ ...param, pessimistic: parseFloat(e.target.value) || 1.25 })}
          className="w-16 rounded border border-border bg-surface-secondary px-1.5 py-1 text-xs text-center tabular-nums"
          aria-label={`${t('risk.pessimistic', { defaultValue: 'Pessimistic' })} ${param.ordinal}`}
        />
      </td>
      <td className="px-1 py-1.5">
        <select
          value={param.distribution}
          onChange={(e) => onChange({ ...param, distribution: e.target.value as DistributionType })}
          className="w-24 rounded border border-border bg-surface-secondary px-1 py-1 text-xs"
          aria-label={`${t('risk.distribution', { defaultValue: 'Distribution' })} ${param.ordinal}`}
        >
          <option value="triangular">{t('risk.dist_triangular', { defaultValue: 'Triangular' })}</option>
          <option value="pert">{t('risk.dist_pert', { defaultValue: 'PERT' })}</option>
          <option value="uniform">{t('risk.dist_uniform', { defaultValue: 'Uniform' })}</option>
        </select>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main Module Component
// ---------------------------------------------------------------------------

interface Project {
  id: string;
  name: string;
}
interface BOQ {
  id: string;
  name: string;
  project_id: string;
}

export default function RiskAnalysisModule() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // Project & BOQ selection
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedBoqId, setSelectedBoqId] = useState('');

  // Simulation settings
  const [iterations, setIterations] = useState(10000);
  const [defaultOptimistic, setDefaultOptimistic] = useState(0.85);
  const [defaultPessimistic, setDefaultPessimistic] = useState(1.25);
  const [defaultDistribution, setDefaultDistribution] = useState<DistributionType>('triangular');

  // Risk parameters per position
  const [params, setParams] = useState<RiskParameter[]>([]);

  // Simulation result
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  // UI state
  const [showParams, setShowParams] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  // Fetch projects
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects-list'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  // Fetch BOQs for selected project
  const { data: boqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-project', selectedProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`),
    enabled: !!selectedProjectId,
  });

  // Fetch positions for selected BOQ (via BOQ detail endpoint)
  const { data: positions = [], isLoading: loadingPositions } = useQuery<BOQPositionForRisk[]>({
    queryKey: ['boq-positions-risk', selectedBoqId],
    queryFn: async () => {
      const boq = await apiGet<{ positions?: BOQPositionForRisk[] }>(`/v1/boq/boqs/${selectedBoqId}`);
      return boq.positions ?? [];
    },
    enabled: !!selectedBoqId,
  });

  // Generate params when positions change
  const handleLoadPositions = useCallback(() => {
    if (positions.length === 0) return;
    const newParams = generateDefaultParams(positions, defaultOptimistic, defaultPessimistic, defaultDistribution);
    setParams(newParams);
    setResult(null);
    addToast({
      type: 'success',
      title: t('risk.positions_loaded', { defaultValue: 'Positions loaded' }),
      message: `${newParams.length} positions with costs ready for simulation`,
    });
  }, [positions, defaultOptimistic, defaultPessimistic, defaultDistribution, addToast, t]);

  // Update single param
  const handleParamChange = useCallback((updated: RiskParameter) => {
    setParams((prev) => prev.map((p) => (p.positionId === updated.positionId ? updated : p)));
  }, []);

  // Run simulation
  const handleRun = useCallback(() => {
    if (params.length === 0) {
      addToast({ type: 'warning', title: t('risk.no_params', { defaultValue: 'No positions loaded' }) });
      return;
    }
    setIsRunning(true);
    // Use requestAnimationFrame to let the UI update before heavy computation
    requestAnimationFrame(() => {
      setTimeout(() => {
        const simResult = runSimulation(params, iterations);
        setResult(simResult);
        setIsRunning(false);
      }, 16);
    });
  }, [params, iterations, addToast, t]);

  // Export results as CSV
  const handleExportCSV = useCallback(() => {
    if (!result) return;
    const lines = [
      'Metric,Value',
      `Iterations,${result.iterations}`,
      `Base Total,${result.baseTotal.toFixed(2)}`,
      `Mean,${result.mean.toFixed(2)}`,
      `Std Dev,${result.stdDev.toFixed(2)}`,
      `P5,${result.percentiles.p5.toFixed(2)}`,
      `P10,${result.percentiles.p10.toFixed(2)}`,
      `P25,${result.percentiles.p25.toFixed(2)}`,
      `P50 (Median),${result.percentiles.p50.toFixed(2)}`,
      `P75,${result.percentiles.p75.toFixed(2)}`,
      `P80,${result.percentiles.p80.toFixed(2)}`,
      `P90,${result.percentiles.p90.toFixed(2)}`,
      `P95,${result.percentiles.p95.toFixed(2)}`,
      `Contingency (P80-P50),${result.contingency.toFixed(2)}`,
      `Contingency %,${result.contingencyPct.toFixed(2)}`,
      '',
      'Top Risk Drivers',
      'Ordinal,Description,Base Cost,Variance Share %',
      ...result.riskDrivers.slice(0, 10).map(
        (d) => `"${d.ordinal}","${d.description}",${d.baseCost.toFixed(2)},${d.contributionPct.toFixed(2)}`,
      ),
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    triggerDownload(blob, 'risk-analysis-results.csv');
  }, [result]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-100 dark:bg-rose-900/30">
          <Dices className="h-5 w-5 text-rose-600 dark:text-rose-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            {t('risk.title', { defaultValue: 'Risk Analysis (Monte Carlo)' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('risk.subtitle', { defaultValue: 'Probabilistic cost estimation with Monte Carlo simulation' })}
          </p>
        </div>
      </div>

      {/* Step 1: Project & BOQ Selection */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <h3 className="text-sm font-semibold text-content-primary mb-3">
          {t('risk.select_boq', { defaultValue: '1. Select BOQ' })}
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-content-tertiary mb-1">
              {t('common.project', { defaultValue: 'Project' })}
            </label>
            <select
              value={selectedProjectId}
              onChange={(e) => {
                setSelectedProjectId(e.target.value);
                setSelectedBoqId('');
                setParams([]);
                setResult(null);
              }}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
            >
              <option value="">{t('risk.select_project', { defaultValue: '— Select project —' })}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-content-tertiary mb-1">
              {t('boq.title', { defaultValue: 'Bill of Quantities' })}
            </label>
            <select
              value={selectedBoqId}
              onChange={(e) => {
                setSelectedBoqId(e.target.value);
                setParams([]);
                setResult(null);
              }}
              disabled={!selectedProjectId}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary disabled:opacity-50"
            >
              <option value="">{t('risk.select_boq_item', { defaultValue: '— Select BOQ —' })}</option>
              {boqs.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-end">
            <Button
              variant="primary"
              size="sm"
              onClick={handleLoadPositions}
              disabled={!selectedBoqId || loadingPositions}
              loading={loadingPositions}
              className="w-full"
            >
              {t('risk.load_positions', { defaultValue: 'Load Positions' })}
            </Button>
          </div>
        </div>
      </div>

      {/* Step 2: Simulation Settings */}
      {params.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <button
            onClick={() => setShowSettings((v) => !v)}
            className="flex w-full items-center justify-between"
          >
            <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2">
              <Settings2 size={15} />
              {t('risk.settings', { defaultValue: '2. Simulation Settings' })}
            </h3>
            {showSettings ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>

          {showSettings && (
            <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mt-4">
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('risk.iterations', { defaultValue: 'Iterations' })}
                </label>
                <select
                  value={iterations}
                  onChange={(e) => setIterations(Number(e.target.value))}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value={1000}>1,000</option>
                  <option value={5000}>5,000</option>
                  <option value={10000}>10,000</option>
                  <option value={25000}>25,000</option>
                  <option value={50000}>50,000</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('risk.optimistic', { defaultValue: 'Default Optimistic' })}
                </label>
                <input
                  type="number"
                  step="0.05"
                  min="0.50"
                  max="1.00"
                  value={defaultOptimistic}
                  onChange={(e) => setDefaultOptimistic(parseFloat(e.target.value) || 0.85)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('risk.pessimistic', { defaultValue: 'Default Pessimistic' })}
                </label>
                <input
                  type="number"
                  step="0.05"
                  min="1.00"
                  max="3.00"
                  value={defaultPessimistic}
                  onChange={(e) => setDefaultPessimistic(parseFloat(e.target.value) || 1.25)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('risk.distribution', { defaultValue: 'Distribution' })}
                </label>
                <select
                  value={defaultDistribution}
                  onChange={(e) => setDefaultDistribution(e.target.value as DistributionType)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value="triangular">Triangular</option>
                  <option value="pert">PERT (Beta)</option>
                  <option value="uniform">Uniform</option>
                </select>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Step 3: Risk Parameters Table (collapsible) */}
      {params.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-primary overflow-hidden">
          <button
            onClick={() => setShowParams((v) => !v)}
            className="flex w-full items-center justify-between px-5 py-3.5 hover:bg-surface-secondary/50 transition-colors"
          >
            <h3 className="text-sm font-semibold text-content-primary">
              {t('risk.parameters', { defaultValue: '3. Risk Parameters' })}
              <span className="ml-2 text-xs font-normal text-content-tertiary">
                ({params.length} {t('risk.positions_label', { defaultValue: 'positions' })})
              </span>
            </h3>
            {showParams ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>

          {showParams && (
            <div className="border-t border-border-light overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-surface-tertiary/50">
                    <th className="px-3 py-2 text-left font-medium text-content-secondary">{t('boq.ordinal', { defaultValue: 'Ord.' })}</th>
                    <th className="px-3 py-2 text-left font-medium text-content-secondary">{t('boq.description', { defaultValue: 'Description' })}</th>
                    <th className="px-3 py-2 text-right font-medium text-content-secondary">{t('risk.base_cost', { defaultValue: 'Base Cost' })}</th>
                    <th className="px-3 py-2 text-center font-medium text-content-secondary">{t('risk.optimistic', { defaultValue: 'Opt. (x)' })}</th>
                    <th className="px-3 py-2 text-center font-medium text-content-secondary">{t('risk.pessimistic', { defaultValue: 'Pess. (x)' })}</th>
                    <th className="px-3 py-2 text-center font-medium text-content-secondary">{t('risk.dist', { defaultValue: 'Distribution' })}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {params.map((param) => (
                    <ParamRow key={param.positionId} param={param} onChange={handleParamChange} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Run button */}
      {params.length > 0 && (
        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            icon={isRunning ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning
              ? t('risk.running', { defaultValue: 'Running simulation...' })
              : t('risk.run', { defaultValue: 'Run Monte Carlo Simulation' })
            }
          </Button>
          {result && (
            <Button variant="ghost" size="sm" icon={<Download size={15} />} onClick={handleExportCSV}>
              {t('risk.export_csv', { defaultValue: 'Export CSV' })}
            </Button>
          )}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-5">
          {/* Summary cards */}
          <div className="rounded-xl border border-border bg-surface-primary p-5 space-y-5">
            <div className="flex items-center gap-4 text-xs text-content-secondary">
              <span>
                {t('risk.base_total', { defaultValue: 'Base Total' })}:{' '}
                <span className="font-semibold text-content-primary tabular-nums">{fmtCurrency(result.baseTotal)}</span>
              </span>
              <span className="text-content-quaternary">|</span>
              <span>
                {t('risk.iterations', { defaultValue: 'Iterations' })}:{' '}
                <span className="font-semibold text-content-primary">{result.iterations.toLocaleString()}</span>
              </span>
              <span className="text-content-quaternary">|</span>
              <span>
                {t('risk.std_dev', { defaultValue: 'Std Dev' })}:{' '}
                <span className="font-semibold text-content-primary tabular-nums">{fmtCurrency(result.stdDev)}</span>
              </span>
            </div>

            {/* Percentile cards */}
            <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
              <PercentileCard label="P5" value={result.percentiles.p5} />
              <PercentileCard label="P10" value={result.percentiles.p10} />
              <PercentileCard label="P25" value={result.percentiles.p25} />
              <PercentileCard label="P50" value={result.percentiles.p50} variant="green" />
              <PercentileCard label="P75" value={result.percentiles.p75} />
              <PercentileCard label="P80" value={result.percentiles.p80} variant="orange" />
              <PercentileCard label="P90" value={result.percentiles.p90} variant="red" />
              <PercentileCard label="P95" value={result.percentiles.p95} variant="red" />
            </div>

            {/* Contingency */}
            <div className="rounded-lg border border-blue-400/50 bg-blue-50/50 dark:bg-blue-950/20 px-4 py-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('risk.contingency', { defaultValue: 'Contingency (P80 − P50)' })}
                  </div>
                  <div className="text-lg font-bold text-blue-700 dark:text-blue-400 tabular-nums mt-0.5">
                    {fmtCurrency(result.contingency)}{' '}
                    <span className="text-sm font-medium text-blue-600/70">({result.contingencyPct.toFixed(1)}%)</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('risk.recommended_budget', { defaultValue: 'Recommended Budget (P80)' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary tabular-nums mt-0.5">
                    {fmtCurrency(result.percentiles.p80)}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Histogram */}
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <Histogram result={result} t={t} />
          </div>

          {/* Risk drivers */}
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <RiskDriversTable drivers={result.riskDrivers} t={t} />
          </div>

          {/* Disclaimer */}
          <div className="flex items-start gap-2 text-xs text-content-quaternary">
            <Info className="h-4 w-4 mt-0.5 shrink-0" />
            <p>
              {t('risk.disclaimer', {
                defaultValue: 'Monte Carlo simulation uses random sampling to model cost uncertainty. Results are probabilistic estimates, not guarantees. The simulation assumes independent cost drivers. Adjust optimistic/pessimistic multipliers per position for more accurate results. Recommended: use P80 for budget planning.',
              })}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
