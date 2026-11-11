// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
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
import {
  Breadcrumb,
  Button,
  DismissibleInfo,
  EmptyState,
  MoneyDisplay,
} from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useNumberLocale } from '@/stores/usePreferencesStore';
import { projectsApi, type Project } from '@/features/projects/api';
import {
  runSimulation,
  generateDefaultParams,
  type RiskParameter,
  type SimulationResult,
  type DistributionType,
  type BOQPositionForRisk,
} from './data/montecarlo';
import { fmtPercent } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

// ---------------------------------------------------------------------------
// Money formatting
// ---------------------------------------------------------------------------

/**
 * Build a compact, currency-aware money string formatter.
 *
 * ``MoneyDisplay`` is the canonical money component but it returns JSX, so it
 * cannot be used inside ``title`` attributes or chart axis labels. This hook
 * mirrors its behaviour (project currency + user number-locale, compact
 * notation) for those string-only call sites. It NEVER emits a bare number:
 * with no project currency it returns an em-dash, matching MoneyDisplay's
 * strict no-silent-fallback policy.
 */
function useCompactMoney(currency: string | undefined): (n: number) => string {
  const numberLocale = useNumberLocale();
  return useCallback(
    (n: number): string => {
      const trimmed = typeof currency === 'string' ? currency.trim() : currency;
      if (!trimmed || !/^[A-Z]{3}$/.test(trimmed)) return '—';
      try {
        return new Intl.NumberFormat(numberLocale, {
          style: 'currency',
          currency: trimmed,
          notation: 'compact',
          minimumFractionDigits: 0,
          maximumFractionDigits: 1,
        }).format(n);
      } catch {
        return `${n.toFixed(0)} ${trimmed}`;
      }
    },
    [currency, numberLocale],
  );
}

// ---------------------------------------------------------------------------
// Percentile Card
// ---------------------------------------------------------------------------

function PercentileCard({
  label,
  value,
  currency,
  variant = 'default',
}: {
  label: string;
  value: number;
  currency: string | undefined;
  variant?: 'default' | 'green' | 'orange' | 'red';
}) {
  const borderClass =
    variant === 'green'
      ? 'border-semantic-success/50 bg-semantic-success/10'
      : variant === 'orange'
        ? 'border-semantic-warning/50 bg-semantic-warning/10'
        : variant === 'red'
          ? 'border-semantic-error/50 bg-semantic-error/10'
          : 'border-border-light bg-surface-secondary/30';

  const valueClass =
    variant === 'green'
      ? 'text-semantic-success'
      : variant === 'orange'
        ? 'text-semantic-warning'
        : variant === 'red'
          ? 'text-semantic-error'
          : 'text-content-primary';

  return (
    <div className={`rounded-lg border px-3 py-2.5 ${borderClass}`}>
      <div className="oe-overline">
        {label}
      </div>
      <div className={`text-sm font-semibold tabular-nums mt-0.5 ${valueClass}`}>
        <MoneyDisplay amount={value} currency={currency} compact />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Histogram
// ---------------------------------------------------------------------------

function Histogram({
  result,
  currency,
  t,
}: {
  result: SimulationResult;
  currency: string | undefined;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const fmtMoney = useCompactMoney(currency);
  const { histogram, percentiles } = result;
  const maxCount = useMemo(() => Math.max(...histogram.map((b) => b.count), 1), [histogram]);
  const minVal = histogram[0]?.binStart ?? 0;
  const maxVal = histogram[histogram.length - 1]?.binEnd ?? 0;
  const range = maxVal - minVal;

  const p50Pct = range > 0 ? ((percentiles.p50 - minVal) / range) * 100 : 50;
  const p80Pct = range > 0 ? ((percentiles.p80 - minVal) / range) * 100 : 80;

  return (
    <div className="space-y-2">
      <h4 className="oe-overline">
        {t('risk.distribution', { defaultValue: 'Cost Distribution (Histogram)' })}
      </h4>
      <div className="relative">
        <div className="flex items-end gap-px h-36">
          {histogram.map((bin) => {
            const heightPct = maxCount > 0 ? (bin.count / maxCount) * 100 : 0;
            const binMid = (bin.binStart + bin.binEnd) / 2;
            const isLeftOfP50 = binMid < percentiles.p50;
            const isRightOfP80 = binMid > percentiles.p80;

            let barColor = 'bg-blue-400/70 hover:bg-blue-500';
            if (isLeftOfP50) barColor = 'bg-semantic-success/60 hover:bg-semantic-success';
            else if (isRightOfP80) barColor = 'bg-semantic-error/60 hover:bg-semantic-error';

            return (
              <div
                key={`${bin.binStart}-${bin.binEnd}`}
                className="flex-1 flex flex-col justify-end"
                title={`${fmtMoney(bin.binStart)} – ${fmtMoney(bin.binEnd)}: ${bin.count} (${fmtPercent(bin.frequency * 100)})`}
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
              className="absolute bottom-0 top-0 w-px border-l-2 border-dashed border-semantic-success/60 pointer-events-none"
              style={{ left: `${Math.min(Math.max(p50Pct, 0), 100)}%` }}
            >
              <span className="absolute -top-5 -translate-x-1/2 text-2xs font-semibold text-semantic-success whitespace-nowrap bg-surface-primary/80 px-1 rounded">
                P50
              </span>
            </div>
            <div
              className="absolute bottom-0 top-0 w-px border-l-2 border-dashed border-semantic-warning/60 pointer-events-none"
              style={{ left: `${Math.min(Math.max(p80Pct, 0), 100)}%` }}
            >
              <span className="absolute -top-5 -translate-x-1/2 text-2xs font-semibold text-semantic-warning whitespace-nowrap bg-surface-primary/80 px-1 rounded">
                P80
              </span>
            </div>
          </>
        )}
      </div>

      <div className="flex justify-between text-2xs text-content-quaternary tabular-nums">
        <span>{fmtMoney(minVal)}</span>
        <span>{fmtMoney(maxVal)}</span>
      </div>

      <div className="flex items-center justify-center gap-5 pt-1">
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-semantic-success/60" />
          <span className="text-2xs text-content-tertiary">{'< P50'}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-blue-400/70" />
          <span className="text-2xs text-content-tertiary">P50 – P80</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-semantic-error/60" />
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
  currency,
  t,
}: {
  drivers: SimulationResult['riskDrivers'];
  currency: string | undefined;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  if (drivers.length === 0) return null;
  const top = drivers.slice(0, 10);

  return (
    <div className="space-y-2">
      <h4 className="oe-overline">
        {t('risk.top_drivers', { defaultValue: 'Top 10 Risk Drivers' })}
      </h4>
      <div className="border border-border-light rounded-lg overflow-hidden">
        <table className="oe-table-compact w-full">
          <thead>
            <tr className="bg-surface-tertiary/50">
              <th>
                {t('boq.ordinal', { defaultValue: 'Ordinal' })}
              </th>
              <th>
                {t('boq.description', { defaultValue: 'Description' })}
              </th>
              <th className="text-right">
                {t('risk.base_cost', { defaultValue: 'Base Cost' })}
              </th>
              <th className="text-right">
                {t('risk.variance_share', { defaultValue: 'Variance Share' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {top.map((driver, idx) => (
              <tr
                key={driver.positionId}
                className={`hover:bg-surface-secondary/30 transition-colors ${idx % 2 === 0 ? 'bg-surface-primary/50' : ''}`}
              >
                <td className="font-mono text-content-tertiary">{driver.ordinal}</td>
                <td className="max-w-[240px] truncate" title={driver.description}>
                  {driver.description || '—'}
                </td>
                <td className="text-right tabular-nums font-medium">
                  <MoneyDisplay amount={driver.baseCost} currency={currency} compact />
                </td>
                <td className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20 h-2 bg-surface-tertiary rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-semantic-error/70"
                        style={{ width: `${Math.min(driver.contributionPct, 100)}%` }}
                      />
                    </div>
                    <span className="tabular-nums font-medium text-content-secondary w-12 text-right">
                      {fmtPercent(driver.contributionPct)}
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
  currency,
  onChange,
}: {
  param: RiskParameter;
  currency: string | undefined;
  onChange: (updated: RiskParameter) => void;
}) {
  const { t } = useTranslation();
  return (
    <tr className="hover:bg-surface-secondary/30 transition-colors">
      <td className="px-3 py-1.5 font-mono text-2xs text-content-tertiary">{param.ordinal}</td>
      <td className="px-3 py-1.5 text-xs text-content-primary max-w-[200px] truncate" title={param.description}>
        {param.description || '—'}
      </td>
      <td className="px-3 py-1.5 text-right text-xs tabular-nums">
        <MoneyDisplay amount={param.baseCost} currency={currency} compact />
      </td>
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

interface BOQ {
  id: string;
  name: string;
  project_id: string;
  created_at?: string;
}

export default function RiskAnalysisModule() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  // Project context — selection happens ONCE, globally, in the top bar. This
  // page reads the active project from the shared store instead of holding a
  // local project picker (Module Style Guide §2).
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeBOQId = useProjectContextStore((s) => s.activeBOQId);
  const setActiveBOQ = useProjectContextStore((s) => s.setActiveBOQ);

  // BOQ selection (a project has many BOQs, so the BOQ picker stays). Seed
  // from the shared context so a returning user lands on the same BOQ.
  const [selectedBoqId, setSelectedBoqId] = useState(activeBOQId ?? '');
  const [autoLoadedBoqId, setAutoLoadedBoqId] = useState<string | null>(null);

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

  // Active project (for name + currency). Money on this page is always shown
  // in the project's currency — never a hardcoded EUR/USD.
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 5 * 60_000,
  });
  const activeProject = useMemo(
    () => projects.find((p) => p.id === activeProjectId),
    [projects, activeProjectId],
  );
  const projectCurrency = activeProject?.currency?.trim() || undefined;
  const projectName = activeProject?.name ?? '';

  // Fetch BOQs for the active project
  const { data: boqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-project', activeProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${activeProjectId}`),
    enabled: !!activeProjectId,
  });

  // Most-recent BOQ for the project (auto-pick so a result appears in 2 clicks).
  const mostRecentBoqId = useMemo(() => {
    if (boqs.length === 0) return '';
    const sorted = [...boqs].sort((a, b) =>
      (b.created_at ?? '').localeCompare(a.created_at ?? ''),
    );
    return sorted[0]?.id ?? '';
  }, [boqs]);

  // Auto-select the most-recent BOQ once they load, unless the user already
  // picked one (or the shared context already carries a valid BOQ).
  useEffect(() => {
    if (boqs.length === 0) return;
    const stillValid = selectedBoqId && boqs.some((b) => b.id === selectedBoqId);
    if (!stillValid) {
      setSelectedBoqId(mostRecentBoqId);
    }
  }, [boqs, mostRecentBoqId, selectedBoqId]);

  // Reset selection when the active PROJECT changes (not the BOQ — this page
  // writes the active BOQ back into the store on auto-load, and depending on
  // activeBOQId here would loop with that write).
  useEffect(() => {
    setSelectedBoqId(useProjectContextStore.getState().activeBOQId ?? '');
    setParams([]);
    setResult(null);
    setAutoLoadedBoqId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId]);

  // Fetch positions for selected BOQ (via BOQ detail endpoint)
  const { data: positions = [], isLoading: loadingPositions } = useQuery<BOQPositionForRisk[]>({
    queryKey: ['boq-positions-risk', selectedBoqId],
    queryFn: async () => {
      const boq = await apiGet<{ positions?: BOQPositionForRisk[] }>(`/v1/boq/boqs/${selectedBoqId}`);
      return boq.positions ?? [];
    },
    enabled: !!selectedBoqId,
  });

  // Build risk parameters from positions.
  const loadParams = useCallback(
    (silent: boolean) => {
      if (positions.length === 0) return;
      const newParams = generateDefaultParams(positions, defaultOptimistic, defaultPessimistic, defaultDistribution);
      setParams(newParams);
      setResult(null);
      if (!silent) {
        addToast({
          type: 'success',
          title: t('risk.positions_loaded', { defaultValue: 'Positions loaded' }),
          message: t('risk.positions_loaded_msg', {
            defaultValue: '{{count}} positions with costs ready for simulation',
            count: newParams.length,
          }),
        });
      }
    },
    [positions, defaultOptimistic, defaultPessimistic, defaultDistribution, addToast, t],
  );

  // Auto-load positions once they arrive for the selected BOQ, so a result is
  // reachable in 2 clicks (sidebar -> Run). Persist the BOQ into the shared
  // context so siblings (/5d, /risks) stay in sync.
  useEffect(() => {
    if (!selectedBoqId || positions.length === 0) return;
    if (autoLoadedBoqId === selectedBoqId) return;
    setAutoLoadedBoqId(selectedBoqId);
    setActiveBOQ(selectedBoqId);
    loadParams(true);
    // loadParams intentionally omitted: it changes with default sliders and we
    // only want the first auto-load per BOQ, not on every slider tweak.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBoqId, positions, autoLoadedBoqId, setActiveBOQ]);

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
      `Currency,${projectCurrency ?? ''}`,
      '',
      'Top Risk Drivers',
      'Ordinal,Description,Base Cost,Variance Share %',
      ...result.riskDrivers.slice(0, 10).map(
        (d) => `"${d.ordinal}","${d.description}",${d.baseCost.toFixed(2)},${d.contributionPct.toFixed(2)}`,
      ),
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    triggerDownload(blob, 'risk-analysis-results.csv');
  }, [result, projectCurrency]);

  const infoLinks = useMemo(
    () => [
      {
        label: t('risk.link_risks', { defaultValue: 'Risk register' }),
        onClick: () => navigate('/risks'),
      },
      {
        label: t('risk.link_5d', { defaultValue: '5D simulation' }),
        onClick: () => navigate('/5d'),
      },
    ],
    [navigate, t],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb — canonical project-scoped trail */}
      <Breadcrumb
        items={
          activeProjectId
            ? [
                { label: projectName || t('common.project', { defaultValue: 'Project' }), to: `/projects/${activeProjectId}` },
                { label: t('nav.risk_analysis', { defaultValue: 'Risk Analysis' }) },
              ]
            : [{ label: t('nav.risk_analysis', { defaultValue: 'Risk Analysis' }) }]
        }
      />

      {/* Header row — no in-page H1 (top bar owns the module name + icon) */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-sm text-content-tertiary">
          {t('risk.subtitle', { defaultValue: 'Probabilistic cost estimation with Monte Carlo simulation' })}
        </p>
      </div>

      {/* Info block — what this page is + how it relates to /risks and /5d */}
      <DismissibleInfo
        storageKey="risk-analysis"
        title={t('risk.info_title', { defaultValue: 'Probabilistic cost analysis' })}
        links={infoLinks}
      >
        {t('risk.info_body', {
          defaultValue:
            'Run a Monte Carlo simulation over a BOQ to get a probability distribution of total cost and a data-driven contingency (P80 − P50). This focuses on cost uncertainty per BOQ position; for the qualitative risk register use Risks, and for schedule-driven cost-time uncertainty use the 5D simulation.',
        })}
      </DismissibleInfo>

      {/* No project active — honest empty state */}
      {!activeProjectId ? (
        <EmptyState
          icon={<Dices className="h-7 w-7" />}
          title={t('risk.no_project_title', { defaultValue: 'Select a project to begin' })}
          description={t('risk.no_project_desc', {
            defaultValue:
              'Pick a project in the top bar. Its most recent BOQ loads automatically so you can run a simulation in one click.',
          })}
        />
      ) : (
        <>
          {/* Step 1: BOQ selection (project comes from the global context) */}
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <h3 className="oe-card-title mb-3">
              {t('risk.select_boq', { defaultValue: '1. Select BOQ' })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="sm:col-span-2">
                <label className="oe-label">
                  {t('boq.title', { defaultValue: 'Bill of Quantities' })}
                </label>
                <select
                  value={selectedBoqId}
                  onChange={(e) => {
                    setSelectedBoqId(e.target.value);
                    setParams([]);
                    setResult(null);
                    setAutoLoadedBoqId(null);
                  }}
                  disabled={boqs.length === 0}
                  className="oe-select w-full"
                >
                  <option value="">{t('risk.select_boq_item', { defaultValue: '- Select BOQ -' })}</option>
                  {boqs.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
              </div>

              <div className="flex items-end">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => loadParams(false)}
                  disabled={!selectedBoqId || loadingPositions || positions.length === 0}
                  loading={loadingPositions}
                  className="w-full"
                >
                  {t('risk.reload_positions', { defaultValue: 'Reload Positions' })}
                </Button>
              </div>
            </div>
            {selectedBoqId && positions.length === 0 && !loadingPositions && (
              <p className="mt-3 text-xs text-content-tertiary">
                {t('risk.boq_empty', {
                  defaultValue: 'This BOQ has no priced positions yet. Add positions with costs to run a simulation.',
                })}
              </p>
            )}
          </div>

          {/* Step 2: Simulation Settings */}
          {params.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-5">
              <button
                onClick={() => setShowSettings((v) => !v)}
                className="flex w-full items-center justify-between"
              >
                <h3 className="oe-card-title flex items-center gap-2">
                  <Settings2 size={16} />
                  {t('risk.settings', { defaultValue: '2. Simulation Settings' })}
                </h3>
                {showSettings ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>

              {showSettings && (
                <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mt-4">
                  <div>
                    <label className="oe-label">
                      {t('risk.iterations', { defaultValue: 'Iterations' })}
                    </label>
                    <select
                      value={iterations}
                      onChange={(e) => setIterations(Number(e.target.value))}
                      className="oe-select w-full"
                    >
                      <option value={1000}>1,000</option>
                      <option value={5000}>5,000</option>
                      <option value={10000}>10,000</option>
                      <option value={25000}>25,000</option>
                      <option value={50000}>50,000</option>
                    </select>
                  </div>
                  <div>
                    <label className="oe-label">
                      {t('risk.default_optimistic', { defaultValue: 'Default Optimistic' })}
                    </label>
                    <input
                      type="number"
                      step="0.05"
                      min="0.50"
                      max="1.00"
                      value={defaultOptimistic}
                      onChange={(e) => setDefaultOptimistic(parseFloat(e.target.value) || 0.85)}
                      className="oe-input w-full"
                    />
                  </div>
                  <div>
                    <label className="oe-label">
                      {t('risk.default_pessimistic', { defaultValue: 'Default Pessimistic' })}
                    </label>
                    <input
                      type="number"
                      step="0.05"
                      min="1.00"
                      max="3.00"
                      value={defaultPessimistic}
                      onChange={(e) => setDefaultPessimistic(parseFloat(e.target.value) || 1.25)}
                      className="oe-input w-full"
                    />
                  </div>
                  <div>
                    <label className="oe-label">
                      {t('risk.distribution_label', { defaultValue: 'Distribution' })}
                    </label>
                    <select
                      value={defaultDistribution}
                      onChange={(e) => setDefaultDistribution(e.target.value as DistributionType)}
                      className="oe-select w-full"
                    >
                      <option value="triangular">{t('risk.dist_triangular', { defaultValue: 'Triangular' })}</option>
                      <option value="pert">{t('risk.dist_pert_beta', { defaultValue: 'PERT (Beta)' })}</option>
                      <option value="uniform">{t('risk.dist_uniform', { defaultValue: 'Uniform' })}</option>
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
                <h3 className="oe-card-title">
                  {t('risk.parameters', { defaultValue: '3. Risk Parameters' })}
                  <span className="ml-2 text-xs font-normal text-content-tertiary">
                    ({params.length} {t('risk.positions_label', { defaultValue: 'positions' })})
                  </span>
                </h3>
                {showParams ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>

              {showParams && (
                <div className="border-t border-border-light overflow-x-auto">
                  <table className="oe-table-compact w-full">
                    <thead>
                      <tr className="bg-surface-tertiary/50">
                        <th>{t('boq.ordinal', { defaultValue: 'Ord.' })}</th>
                        <th>{t('boq.description', { defaultValue: 'Description' })}</th>
                        <th className="text-right">{t('risk.base_cost', { defaultValue: 'Base Cost' })}</th>
                        <th className="text-center">{t('risk.optimistic_x', { defaultValue: 'Opt. (x)' })}</th>
                        <th className="text-center">{t('risk.pessimistic_x', { defaultValue: 'Pess. (x)' })}</th>
                        <th className="text-center">{t('risk.distribution_label', { defaultValue: 'Distribution' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {params.map((param) => (
                        <ParamRow key={param.positionId} param={param} currency={projectCurrency} onChange={handleParamChange} />
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
                icon={isRunning ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                onClick={handleRun}
                disabled={isRunning}
              >
                {isRunning
                  ? t('risk.running', { defaultValue: 'Running simulation...' })
                  : t('risk.run', { defaultValue: 'Run Monte Carlo Simulation' })
                }
              </Button>
              {result && (
                <Button variant="ghost" size="sm" icon={<Download size={16} />} onClick={handleExportCSV}>
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
                <div className="flex flex-wrap items-center gap-4 text-xs text-content-secondary">
                  <span>
                    {t('risk.base_total', { defaultValue: 'Base Total' })}:{' '}
                    <span className="font-semibold text-content-primary tabular-nums">
                      <MoneyDisplay amount={result.baseTotal} currency={projectCurrency} compact />
                    </span>
                  </span>
                  <span className="text-content-quaternary">|</span>
                  <span>
                    {t('risk.iterations', { defaultValue: 'Iterations' })}:{' '}
                    <span className="font-semibold text-content-primary">{result.iterations.toLocaleString(getNumberLocale())}</span>
                  </span>
                  <span className="text-content-quaternary">|</span>
                  <span>
                    {t('risk.std_dev', { defaultValue: 'Std Dev' })}:{' '}
                    <span className="font-semibold text-content-primary tabular-nums">
                      <MoneyDisplay amount={result.stdDev} currency={projectCurrency} compact />
                    </span>
                  </span>
                </div>

                {/* Percentile cards */}
                <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
                  <PercentileCard label="P5" value={result.percentiles.p5} currency={projectCurrency} />
                  <PercentileCard label="P10" value={result.percentiles.p10} currency={projectCurrency} />
                  <PercentileCard label="P25" value={result.percentiles.p25} currency={projectCurrency} />
                  <PercentileCard label="P50" value={result.percentiles.p50} currency={projectCurrency} variant="green" />
                  <PercentileCard label="P75" value={result.percentiles.p75} currency={projectCurrency} />
                  <PercentileCard label="P80" value={result.percentiles.p80} currency={projectCurrency} variant="orange" />
                  <PercentileCard label="P90" value={result.percentiles.p90} currency={projectCurrency} variant="red" />
                  <PercentileCard label="P95" value={result.percentiles.p95} currency={projectCurrency} variant="red" />
                </div>

                {/* Contingency */}
                <div className="rounded-lg border border-blue-400/50 bg-blue-50/50 dark:bg-blue-950/20 px-4 py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="oe-overline">
                        {t('risk.contingency', { defaultValue: 'Contingency (P80 − P50)' })}
                      </div>
                      <div className="text-lg font-semibold text-blue-700 dark:text-blue-400 tabular-nums mt-0.5">
                        <MoneyDisplay amount={result.contingency} currency={projectCurrency} compact />{' '}
                        <span className="text-sm font-medium text-blue-600/70">({fmtPercent(result.contingencyPct)})</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="oe-overline">
                        {t('risk.recommended_budget', { defaultValue: 'Recommended Budget (P80)' })}
                      </div>
                      <div className="text-lg font-semibold text-content-primary tabular-nums mt-0.5">
                        <MoneyDisplay amount={result.percentiles.p80} currency={projectCurrency} compact />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Histogram */}
              <div className="rounded-xl border border-border bg-surface-primary p-5">
                <Histogram result={result} currency={projectCurrency} t={t} />
              </div>

              {/* Risk drivers */}
              <div className="rounded-xl border border-border bg-surface-primary p-5">
                <RiskDriversTable drivers={result.riskDrivers} currency={projectCurrency} t={t} />
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
        </>
      )}
    </div>
  );
}
