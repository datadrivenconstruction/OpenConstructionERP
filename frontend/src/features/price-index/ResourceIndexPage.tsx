// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Resource-index estimate (Russia) - the breakdown of a local smeta priced by
 * the resource-index method, with every multiplication on screen.
 *
 * Each resource of a norm is taken at base prices and multiplied by its own
 * group's regional quarterly index; overheads (NR) and estimated profit (SP)
 * are charged on the wage fund FOT = workers' wages + operators' wages; then
 * the total and VAT for the chosen date. The page reads a BOQ, never writes to
 * its positions, and stores only the person's own choices (region, quarter,
 * work types). Every number is the decimal string the server computed.
 */

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Calculator, FlaskConical, Info, Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { BOQPicker, Badge, Button, Card, CardHeader, Input, PageHeader } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import {
  RESOURCE_GROUPS,
  computeBoq,
  computeExplicit,
  createOverheadNorm,
  createResourceIndex,
  deleteOverheadNorm,
  deleteResourceIndex,
  formatAmount,
  formatFactorString,
  getBoqSettings,
  listOverheadNorms,
  listResourceIndices,
  missingGroups,
  normaliseQuarter,
  quartersOf,
  refusalOf,
  regionsOf,
  saveBoqSettings,
  updateOverheadNorm,
  updateResourceIndex,
  workedExamplePositions,
  type BOQResourceIndexSettings,
  type ExcludedReason,
  type LineOut,
  type OverheadNorm,
  type PositionOut,
  type ResourceGroup,
  type ResourceIndexEstimate,
  type ResourceIndexRefusal,
  type ResourceIndexValue,
  type WorkedExampleLabels,
} from './resourceIndexApi';

const QK = {
  indices: ['price-index', 'resource-index', 'indices'] as const,
  norms: ['price-index', 'resource-index', 'norms'] as const,
  settings: (boqId: string) => ['price-index', 'resource-index', 'settings', boqId] as const,
};

const EMPTY_SETTINGS: BOQResourceIndexSettings = {
  region_code: '',
  quarter: '',
  default_work_type: '',
  work_types: {},
  resources_at_base_prices: false,
};

const selectClass =
  'h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary ' +
  'focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

function todayIso(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Translated name of an index group. */
function useGroupLabel(): (group: ResourceGroup) => string {
  const { t } = useTranslation();
  return (group) => {
    switch (group) {
      case 'labor':
        return t('price_index.ri.group_labor', { defaultValue: "Workers' wages (OT)" });
      case 'machine':
        return t('price_index.ri.group_machine', { defaultValue: 'Machine operation (EM)' });
      case 'operator_wages':
        return t('price_index.ri.group_operator_wages', { defaultValue: "Operators' wages (OTm)" });
      case 'material':
        return t('price_index.ri.group_material', { defaultValue: 'Materials (M)' });
      default:
        return group;
    }
  };
}

export function ResourceIndexPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('price_index.ri.title', { defaultValue: 'Resource-index estimate' })}
        subtitle={t('price_index.ri.subtitle', {
          defaultValue:
            'Price a Russian local estimate by the resource-index method: each resource group at base prices times its own regional quarterly index, then overheads and estimated profit on the wage fund, then VAT. Every multiplication is shown.',
        })}
      />
      <ResourceIndexContent />
    </div>
  );
}

function ResourceIndexContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [params] = useSearchParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [projectId, setProjectId] = useState<string | null>(params.get('project') || activeProjectId || null);
  const [boqId, setBoqId] = useState<string | null>(params.get('boq') || null);
  const [settings, setSettings] = useState<BOQResourceIndexSettings>(EMPTY_SETTINGS);
  const [onDate, setOnDate] = useState<string>(todayIso());
  const [result, setResult] = useState<ResourceIndexEstimate | null>(null);
  const [refusal, setRefusal] = useState<ResourceIndexRefusal | null>(null);
  const [dirty, setDirty] = useState(false);
  // The result on screen was computed before an index or norm was changed.
  const [stale, setStale] = useState(false);
  // Which calculation produced the result on screen, so a stale one can be re-run.
  const [lastRun, setLastRun] = useState<'boq' | 'example' | null>(null);
  // The BOQ whose stored choices have been loaded into the form. A refetch of
  // the same BOQ's settings (after Save, or any invalidation) must not reset
  // the form or wipe the breakdown on screen; only picking a BOQ does.
  const loadedFor = useRef<string | null>(null);

  const indicesQ = useQuery({ queryKey: QK.indices, queryFn: listResourceIndices });
  const normsQ = useQuery({ queryKey: QK.norms, queryFn: listOverheadNorms });
  const settingsQ = useQuery({
    queryKey: QK.settings(boqId ?? 'none'),
    queryFn: () => getBoqSettings(boqId as string),
    enabled: !!boqId,
  });

  const indices = useMemo(() => indicesQ.data ?? [], [indicesQ.data]);
  const norms = useMemo(() => normsQ.data ?? [], [normsQ.data]);
  const regions = useMemo(() => regionsOf(indices), [indices]);
  const quarters = useMemo(() => quartersOf(indices, settings.region_code), [indices, settings.region_code]);
  const normLabel = useMemo(() => new Map(norms.map((n) => [n.work_type_code, n.label])), [norms]);

  // Load the stored choices once per picked BOQ; a fresh BOQ starts empty.
  useEffect(() => {
    if (!boqId) {
      loadedFor.current = null;
      return;
    }
    if (!settingsQ.data || loadedFor.current === boqId) return;
    loadedFor.current = boqId;
    setSettings({ ...EMPTY_SETTINGS, ...settingsQ.data, work_types: { ...settingsQ.data.work_types } });
    setDirty(false);
    setResult(null);
    setRefusal(null);
  }, [boqId, settingsQ.data]);

  // Offer the first region and its newest quarter when nothing is chosen yet.
  useEffect(() => {
    if (settings.region_code || regions.length === 0) return;
    const region = regions[0];
    if (!region) return;
    const quarter = quartersOf(indices, region)[0] ?? '';
    setSettings((s) => ({ ...s, region_code: region, quarter: s.quarter || quarter }));
  }, [regions, indices, settings.region_code]);

  const missing = useMemo(
    () =>
      settings.region_code && settings.quarter ? missingGroups(indices, settings.region_code, settings.quarter) : [],
    [indices, settings.region_code, settings.quarter],
  );

  const onRefusalOrError = (e: unknown) => {
    const r = refusalOf(e);
    if (r) {
      setRefusal(r);
      setResult(null);
      return;
    }
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
  };

  const computeMut = useMutation({
    mutationFn: (next: BOQResourceIndexSettings) => computeBoq(boqId as string, { ...next, on_date: onDate }),
    onSuccess: (r) => {
      setResult(r);
      setRefusal(null);
      setStale(false);
      setLastRun('boq');
    },
    onError: onRefusalOrError,
  });

  const exampleLabels: WorkedExampleLabels = {
    concreteBlinding: t('price_index.ri.ex_concrete_blinding', { defaultValue: 'Concrete blinding (example)' }),
    handExcavation: t('price_index.ri.ex_hand_excavation', { defaultValue: 'Trench excavation by hand (example)' }),
    workersGrade35: t('price_index.ri.ex_workers_35', { defaultValue: 'Workers, average grade 3.5' }),
    workersGrade2: t('price_index.ri.ex_workers_2', { defaultValue: 'Workers, average grade 2' }),
    concretePump: t('price_index.ri.ex_concrete_pump', { defaultValue: 'Concrete pump' }),
    pumpOperator: t('price_index.ri.ex_pump_operator', { defaultValue: 'Pump operator' }),
    concrete: t('price_index.ri.ex_concrete', { defaultValue: 'Concrete B7.5' }),
    sand: t('price_index.ri.ex_sand', { defaultValue: 'Sand' }),
    gravel: t('price_index.ri.ex_gravel', { defaultValue: 'Gravel' }),
    manHour: t('price_index.ri.ex_man_hour', { defaultValue: 'man-h' }),
    machineHour: t('price_index.ri.ex_machine_hour', { defaultValue: 'mach-h' }),
  };

  const exampleMut = useMutation({
    mutationFn: () => {
      const first = norms[0]?.work_type_code ?? '';
      const second = norms[1]?.work_type_code ?? first;
      return computeExplicit({
        region_code: settings.region_code,
        quarter: settings.quarter,
        on_date: onDate,
        positions: workedExamplePositions(first, second, exampleLabels),
      });
    },
    onSuccess: (r) => {
      setResult(r);
      setRefusal(null);
      setStale(false);
      setLastRun('example');
    },
    onError: onRefusalOrError,
  });

  const saveMut = useMutation({
    mutationFn: () => saveBoqSettings(boqId as string, settings),
    onSuccess: (saved) => {
      queryClient.setQueryData(QK.settings(boqId as string), saved);
      setDirty(false);
      addToast({
        type: 'success',
        title: t('price_index.ri.saved', { defaultValue: 'Choices saved on the estimate' }),
      });
    },
    onError: onRefusalOrError,
  });

  const update = (patch: Partial<BOQResourceIndexSettings>) => {
    setSettings((s) => ({ ...s, ...patch }));
    setDirty(true);
  };

  const setPositionWorkType = (ref: string, code: string) => {
    const next: BOQResourceIndexSettings = {
      ...settings,
      work_types: { ...settings.work_types, [ref]: code },
    };
    if (!code) delete next.work_types[ref];
    setSettings(next);
    setDirty(true);
    // Re-price straight away so the person sees the effect of the choice.
    if (boqId && result?.boq_id) computeMut.mutate(next);
  };

  const ready = !!settings.region_code && !!normaliseQuarter(settings.quarter);
  const busy = computeMut.isPending || exampleMut.isPending;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t('price_index.ri.setup_title', { defaultValue: 'Estimate and indices' })}
          subtitle={t('price_index.ri.setup_subtitle', {
            defaultValue:
              'Pick the estimate, the region and quarter of the indices, and the date the VAT rate is read for. Resource prices on the estimate must be at base prices.',
          })}
        />
        <div className="mt-4 space-y-4">
          <BOQPicker
            projectId={projectId}
            selectedBoqId={boqId}
            onSelectProject={(id) => {
              setProjectId(id);
              setBoqId(null);
              setResult(null);
            }}
            onSelectBoq={(id) => {
              setBoqId(id);
              setResult(null);
            }}
          />
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('price_index.ri.region', { defaultValue: 'Region' })}
              <select
                className={selectClass}
                value={settings.region_code}
                onChange={(e) => {
                  const region = e.target.value;
                  update({ region_code: region, quarter: quartersOf(indices, region)[0] ?? '' });
                }}
              >
                {regions.length === 0 && <option value="">{t('price_index.ri.no_regions', { defaultValue: 'No indices entered' })}</option>}
                {settings.region_code && !regions.includes(settings.region_code) && (
                  <option value={settings.region_code}>{settings.region_code}</option>
                )}
                {regions.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('price_index.ri.quarter', { defaultValue: 'Quarter' })}
              <select className={selectClass} value={settings.quarter} onChange={(e) => update({ quarter: e.target.value })}>
                {settings.quarter && !quarters.includes(settings.quarter) && (
                  <option value={settings.quarter}>{settings.quarter}</option>
                )}
                {quarters.map((q) => (
                  <option key={q} value={q}>
                    {q}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('price_index.ri.vat_date', { defaultValue: 'VAT date' })}
              <input
                type="date"
                className={selectClass}
                value={onDate}
                onChange={(e) => setOnDate(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('price_index.ri.default_work_type', { defaultValue: 'Default work type' })}
              <select
                className={selectClass}
                value={settings.default_work_type}
                onChange={(e) => update({ default_work_type: e.target.value })}
              >
                <option value="">{t('price_index.ri.none_chosen', { defaultValue: 'Not chosen' })}</option>
                {norms.map((n) => (
                  <option key={n.id} value={n.work_type_code}>
                    {n.label || n.work_type_code}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={() => computeMut.mutate(settings)}
              disabled={!boqId || !ready || busy}
            >
              {computeMut.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Calculator className="mr-1 h-4 w-4" aria-hidden />
              )}
              {t('price_index.ri.calculate', { defaultValue: 'Calculate estimate' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => saveMut.mutate()}
              disabled={!boqId || !dirty || saveMut.isPending}
            >
              <Save className="mr-1 h-4 w-4" aria-hidden />
              {t('price_index.ri.save_choices', { defaultValue: 'Save choices' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => exampleMut.mutate()}
              disabled={!ready || norms.length === 0 || busy}
              title={t('price_index.ri.example_hint', {
                defaultValue: 'Price two example positions with the selected indices to see how the method works',
              })}
            >
              <FlaskConical className="mr-1 h-4 w-4" aria-hidden />
              {t('price_index.ri.example', { defaultValue: 'Worked example' })}
            </Button>
            {dirty && boqId && (
              <span className="text-xs text-content-tertiary">
                {t('price_index.ri.unsaved', { defaultValue: 'Choices not saved yet' })}
              </span>
            )}
          </div>
          <label className="flex items-start gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0"
              checked={settings.resources_at_base_prices}
              onChange={(e) => update({ resources_at_base_prices: e.target.checked })}
            />
            <span>
              {t('price_index.ri.base_prices_confirm', {
                defaultValue:
                  'The resource prices on this estimate are base prices of the 2022 federal base (FSNB-2022). Tick this only if they are: prices in current money, such as a resource split of current rates, would be indexed a second time. Without it only lines marked as priced from the norm base are indexed.',
              })}
            </span>
          </label>
          {ready && missing.length > 0 && (
            <MissingIndexNote groups={missing} region={settings.region_code} quarter={settings.quarter} />
          )}
        </div>
      </Card>

      {refusal && <RefusalBox refusal={refusal} />}

      {result && stale && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
          <span className="flex-1">
            {t('price_index.ri.stale_banner', {
              defaultValue:
                'An index or norm was changed after this calculation. The figures below are the old ones until you recalculate.',
            })}
          </span>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || (lastRun === 'boq' && !boqId)}
            onClick={() => (lastRun === 'example' ? exampleMut.mutate() : computeMut.mutate(settings))}
          >
            <RefreshCw className="mr-1 h-4 w-4" aria-hidden />
            {t('price_index.ri.recalculate', { defaultValue: 'Recalculate' })}
          </Button>
        </div>
      )}

      {result && (
        <EstimateBreakdown
          result={result}
          norms={norms}
          normLabel={normLabel}
          onWorkTypeChange={result.boq_id ? setPositionWorkType : undefined}
          chosen={settings.work_types}
        />
      )}

      <ReferenceData
        indices={indices}
        norms={norms}
        region={settings.region_code}
        quarter={settings.quarter}
        onChanged={() => setStale(true)}
      />
    </div>
  );
}

/* ── Notes and refusals ─────────────────────────────────────────────────── */

function MissingIndexNote({ groups, region, quarter }: { groups: ResourceGroup[]; region: string; quarter: string }) {
  const { t } = useTranslation();
  const label = useGroupLabel();
  return (
    <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
      <span>
        {t('price_index.ri.missing_note', {
          defaultValue:
            'No index entered for {{groups}} in {{region}}, {{quarter}}. Positions that use these groups cannot be priced until you enter them below.',
          groups: groups.map(label).join(', '),
          region,
          quarter,
        })}
      </span>
    </div>
  );
}

function RefusalBox({ refusal }: { refusal: ResourceIndexRefusal }) {
  const { t } = useTranslation();
  const label = useGroupLabel();
  let text: string;
  switch (refusal.code) {
    case 'missing_index':
      text = t('price_index.ri.err_missing_index', {
        defaultValue:
          'The estimate needs an index for {{groups}} in {{region}}, {{quarter}}, and none is entered. Enter it from the quarterly letter below; a missing index is never taken as 1.',
        groups: (refusal.groups ?? []).map(label).join(', '),
        region: refusal.region_code ?? '',
        quarter: refusal.quarter ?? '',
      });
      break;
    case 'missing_overhead_norm':
      text = t('price_index.ri.err_missing_norm', {
        defaultValue: 'No overhead and profit percentages are entered for work type {{types}}. Enter them below.',
        types: (refusal.work_types ?? []).join(', '),
      });
      break;
    case 'missing_operator_wages':
      text = t('price_index.ri.err_missing_operator', {
        defaultValue:
          "Position {{positions}} has machine lines but no operator line, so the operators' wages would enter the wage fund as zero. Split the operators' wages out of the machine price into an operator line, with zero if the machine has no operator.",
        positions: (refusal.positions ?? []).join(', '),
      });
      break;
    case 'vat_unresolved':
      text = t('price_index.ri.err_vat', {
        defaultValue:
          'The tax tables give no VAT rate for Russia on {{date}}, so the estimate has no VAT line to show. Check the tax settings.',
        date: refusal.on_date ?? '',
      });
      break;
    case 'settings_incomplete':
      text = t('price_index.ri.err_settings', { defaultValue: 'Choose the region and the quarter of the indices first.' });
      break;
    case 'invalid_index':
      text = t('price_index.ri.err_invalid_index', {
        defaultValue: 'An index the estimate needs is zero or negative. Correct it below.',
      });
      break;
    case 'invalid_input':
      text = t('price_index.ri.err_invalid_input', {
        defaultValue: 'The estimate cannot be priced as entered: {{reason}}',
        reason: refusal.message,
      });
      break;
    default:
      text = refusal.message;
  }
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-semantic-error/40 bg-semantic-error-bg px-3 py-2 text-sm text-content-primary"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-error" aria-hidden />
      <span>{text}</span>
    </div>
  );
}

/* ── Breakdown ──────────────────────────────────────────────────────────── */

function Money({ value, strong }: { value: string; strong?: boolean }) {
  return (
    <span className={'font-mono tabular-nums ' + (strong ? 'font-semibold text-content-primary' : 'text-content-secondary')}>
      {formatAmount(value)}
    </span>
  );
}

function FormulaRow({ label, formula, value, strong }: { label: string; formula?: string; value: string; strong?: boolean }) {
  return (
    <tr className="border-b border-border-light last:border-0">
      <td className={'px-3 py-1.5 ' + (strong ? 'font-semibold text-content-primary' : 'text-content-secondary')}>{label}</td>
      <td className="px-3 py-1.5 font-mono text-xs text-content-tertiary">{formula}</td>
      <td className="px-3 py-1.5 text-right">
        <Money value={value} strong={strong} />
      </td>
    </tr>
  );
}

export function EstimateBreakdown({
  result,
  norms,
  normLabel,
  onWorkTypeChange,
  chosen,
}: {
  result: ResourceIndexEstimate;
  norms: OverheadNorm[];
  normLabel: Map<string, string>;
  onWorkTypeChange?: (ref: string, code: string) => void;
  chosen: Record<string, string>;
}) {
  const { t } = useTranslation();
  const label = useGroupLabel();
  const tt = result.totals;
  const vatPct = formatFactorString(result.vat_rate_pct);
  const f = formatAmount;

  return (
    <div className="space-y-5">
      {result.uses_sample_data && (
        <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
          <span>
            {t('price_index.ri.sample_banner', {
              defaultValue:
                'This calculation uses sample indices or norms shipped for demonstration. They are not official values; replace them with the Minstroy quarterly letter for your region and the percentages of orders 812/pr and 774/pr before relying on the total.',
            })}
          </span>
        </div>
      )}
      {!result.is_complete && (
        <div className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm">
          <div className="flex items-start gap-2">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
            <span>
              {t('price_index.ri.partial_banner', {
                defaultValue:
                  'Partial: {{priced}}, {{excluded}}. The totals below cover only the priced positions and are not the estimate total.',
                priced: t('price_index.ri.priced_count', {
                  count: result.priced_count,
                  defaultValue: '{{count}} position priced',
                  defaultValue_other: '{{count}} positions priced',
                }),
                excluded: t('price_index.ri.excluded_count', {
                  count: result.excluded_count,
                  defaultValue: '{{count}} position not priced',
                  defaultValue_other: '{{count}} positions not priced',
                }),
              })}
            </span>
          </div>
          <ExcludedList result={result} norms={norms} onWorkTypeChange={onWorkTypeChange} />
        </div>
      )}

      <Card>
        <CardHeader
          title={
            result.is_complete
              ? t('price_index.ri.totals_title', { defaultValue: 'Estimate totals' })
              : t('price_index.ri.totals_title_partial', { defaultValue: 'Totals of the priced positions' })
          }
          subtitle={t('price_index.ri.totals_subtitle', {
            defaultValue: '{{region}}, {{quarter}} indices; VAT as of {{date}}; amounts in {{currency}}',
            region: result.region_code,
            quarter: result.quarter,
            date: result.on_date,
            currency: result.currency,
          })}
        />
        <div className="mt-3 overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-sm">
            <tbody>
              <FormulaRow label={label('labor')} value={tt.ot} />
              <FormulaRow label={label('machine')} value={tt.em} />
              <FormulaRow
                label={t('price_index.ri.of_which_otm', { defaultValue: "of which operators' wages (OTm)" })}
                value={tt.otm}
              />
              <FormulaRow label={label('material')} value={tt.m} />
              <FormulaRow
                label={t('price_index.ri.direct', { defaultValue: 'Direct cost' })}
                formula={`${f(tt.ot)} + ${f(tt.em)} + ${f(tt.m)}`}
                value={tt.direct}
                strong
              />
              <FormulaRow
                label={t('price_index.ri.fot', { defaultValue: 'Wage fund (FOT)' })}
                formula={`${f(tt.ot)} + ${f(tt.otm)}`}
                value={tt.fot}
              />
              <FormulaRow
                label={t('price_index.ri.nr', { defaultValue: 'Overheads (NR)' })}
                formula={t('price_index.ri.sum_by_position', { defaultValue: 'sum by position' })}
                value={tt.nr}
              />
              <FormulaRow
                label={t('price_index.ri.sp', { defaultValue: 'Estimated profit (SP)' })}
                formula={t('price_index.ri.sum_by_position', { defaultValue: 'sum by position' })}
                value={tt.sp}
              />
              <FormulaRow
                label={t('price_index.ri.total', { defaultValue: 'Total excluding VAT' })}
                formula={`${f(tt.direct)} + ${f(tt.nr)} + ${f(tt.sp)}`}
                value={tt.total}
                strong
              />
              <FormulaRow
                label={t('price_index.ri.vat', { defaultValue: 'VAT {{pct}}%', pct: vatPct })}
                formula={`${f(tt.total)} × ${vatPct}%`}
                value={tt.vat}
              />
              <FormulaRow
                label={t('price_index.ri.total_with_vat', { defaultValue: 'Total including VAT' })}
                formula={`${f(tt.total)} + ${f(tt.vat)}`}
                value={tt.total_with_vat}
                strong
              />
            </tbody>
          </table>
        </div>
        <div className="mt-2 text-xs text-content-tertiary">
          {t('price_index.ri.base_direct_note', {
            defaultValue: 'Direct cost at base prices: {{amount}}. Each product is rounded to kopecks; each sum adds the rounded figures.',
            amount: f(tt.base_direct),
          })}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('price_index.ri.indices_used', { defaultValue: 'Indices applied' })} />
          <ul className="mt-3 space-y-1.5 text-sm">
            {result.indices_used.map((i) => (
              <li key={i.resource_group} className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-content-secondary">{label(i.resource_group)}</span>
                <span className="flex items-center gap-2">
                  <span className="font-mono font-semibold">{formatFactorString(i.index_value)}</span>
                  {i.is_sample && (
                    <Badge variant="warning" size="sm">
                      {t('price_index.ri.sample', { defaultValue: 'sample' })}
                    </Badge>
                  )}
                </span>
                {i.source && <span className="w-full text-xs text-content-tertiary">{i.source}</span>}
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title={t('price_index.ri.by_work_type', { defaultValue: 'Overheads and profit by work type' })} />
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
                  <th className="px-2 py-1.5 font-medium">{t('price_index.ri.work_type', { defaultValue: 'Work type' })}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t('price_index.ri.fot_short', { defaultValue: 'FOT' })}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t('price_index.ri.nr_short', { defaultValue: 'NR' })}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t('price_index.ri.sp_short', { defaultValue: 'SP' })}</th>
                </tr>
              </thead>
              <tbody>
                {result.by_work_type.map((w) => (
                  <tr key={w.work_type} className="border-b border-border-light last:border-0">
                    <td className="px-2 py-1.5 text-content-secondary">
                      {w.label || w.work_type}
                      {result.norms_used.some((n) => n.work_type_code === w.work_type && n.is_sample) && (
                        <Badge variant="warning" size="sm" className="ml-1">
                          {t('price_index.ri.sample', { defaultValue: 'sample' })}
                        </Badge>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <Money value={w.fot} />
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <Money value={w.nr} />
                      <div className="text-xs text-content-tertiary">{formatFactorString(w.nr_pct)}%</div>
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <Money value={w.sp} />
                      <div className="text-xs text-content-tertiary">{formatFactorString(w.sp_pct)}%</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader
          title={t('price_index.ri.positions_title', { defaultValue: 'Positions' })}
          subtitle={t('price_index.ri.positions_subtitle', {
            defaultValue: 'Base amount = position quantity × consumption × base price; current amount = base amount × index.',
          })}
        />
        <div className="mt-3 space-y-4">
          {result.positions.map((p) => (
            <PositionBlock
              key={p.ref}
              position={p}
              norms={norms}
              normLabel={normLabel}
              onWorkTypeChange={onWorkTypeChange}
              chosen={chosen[p.ref] ?? ''}
            />
          ))}
          {result.positions.length === 0 && (
            <p className="text-sm text-content-tertiary">
              {t('price_index.ri.no_priced', { defaultValue: 'No position could be priced yet.' })}
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}

function ExcludedList({
  result,
  norms,
  onWorkTypeChange,
}: {
  result: ResourceIndexEstimate;
  norms: OverheadNorm[];
  onWorkTypeChange?: (ref: string, code: string) => void;
}) {
  const { t } = useTranslation();
  const reason = (r: ExcludedReason, detail: string): string => {
    switch (r) {
      case 'no_resources':
        return t('price_index.ri.reason_no_resources', { defaultValue: 'no resource breakdown on the position' });
      case 'unmapped_resource_type':
        return t('price_index.ri.reason_unmapped', {
          defaultValue: 'resource type {{types}} has no group in the method; set it to labour, machine, operator or material',
          types: detail,
        });
      case 'foreign_currency':
        return t('price_index.ri.reason_currency', { defaultValue: 'resources priced in {{currency}}', currency: detail });
      case 'no_work_type':
        return t('price_index.ri.reason_no_work_type', { defaultValue: 'no work type chosen' });
      case 'bad_number':
        return t('price_index.ri.reason_bad_number', { defaultValue: 'a quantity or price is not a number' });
      case 'not_base_prices':
        return t('price_index.ri.reason_not_base_prices', {
          defaultValue: 'priced from {{basis}}, which is current money; only base prices are indexed',
          basis: detail,
        });
      case 'base_prices_unconfirmed':
        return t('price_index.ri.reason_base_prices_unconfirmed', {
          defaultValue:
            'not confirmed as base prices; tick the base-price statement above if the resource prices of this estimate are FSNB-2022 base prices',
        });
      case 'estimated_resources':
        return t('price_index.ri.reason_estimated_resources', {
          defaultValue: 'the resource split was generated from the current rate, so it is current money, not base prices',
        });
      case 'machine_without_operator_wages':
        return t('price_index.ri.reason_machine_without_operator', {
          defaultValue:
            "machine lines with no operator line; add the operators' wages as an operator resource (zero if the machine has none)",
        });
      default:
        return r;
    }
  };
  return (
    <ul className="mt-2 max-h-48 space-y-0.5 overflow-y-auto pl-6 text-xs text-content-secondary">
      {result.excluded.map((e) => (
        <li key={e.position_id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span>
            <span className="font-mono">{e.ordinal}</span> {e.description}: {reason(e.reason, e.detail)}
          </span>
          {e.reason === 'no_work_type' && onWorkTypeChange && norms.length > 0 && (
            <select
              aria-label={t('price_index.ri.work_type', { defaultValue: 'Work type' })}
              className={selectClass + ' h-7 text-xs'}
              value=""
              onChange={(ev) => onWorkTypeChange(e.position_id, ev.target.value)}
            >
              <option value="">{t('price_index.ri.choose_work_type', { defaultValue: 'Choose work type' })}</option>
              {norms.map((n) => (
                <option key={n.id} value={n.work_type_code}>
                  {n.label || n.work_type_code}
                </option>
              ))}
            </select>
          )}
        </li>
      ))}
    </ul>
  );
}

function LineRows({ line }: { line: LineOut }) {
  const { t } = useTranslation();
  const label = useGroupLabel();
  const f = formatAmount;
  return (
    <Fragment>
      <tr className="border-b border-border-light">
        <td className="px-2 py-1 font-mono text-xs">{line.code}</td>
        <td className="px-2 py-1 text-content-secondary">
          {line.name}
          {line.kind === 'operator' && (
            <span className="ml-1 text-xs text-content-tertiary">
              ({t('price_index.ri.operator_line', { defaultValue: 'operator' })})
            </span>
          )}
        </td>
        <td className="px-2 py-1 text-xs text-content-tertiary">{label(line.index_group)}</td>
        <td className="px-2 py-1 text-right font-mono text-xs text-content-tertiary">
          {`${line.position_quantity} × ${line.quantity} × ${f(line.base_unit_price)} = `}
          <Money value={line.base_amount} />
        </td>
        <td className="px-2 py-1 text-right font-mono text-xs text-content-tertiary">
          {`× ${formatFactorString(line.index)} = `}
          <Money value={line.current_amount} strong />
        </td>
      </tr>
      {line.operator_wage_current != null && line.operator_wage_index != null && (
        <tr className="border-b border-border-light bg-surface-secondary/40">
          <td />
          <td className="px-2 py-1 text-xs text-content-tertiary" colSpan={2}>
            {t('price_index.ri.of_which_otm', { defaultValue: "of which operators' wages (OTm)" })}
          </td>
          <td className="px-2 py-1 text-right font-mono text-xs text-content-tertiary">{f(line.base_amount)}</td>
          <td className="px-2 py-1 text-right font-mono text-xs text-content-tertiary">
            {`× ${formatFactorString(line.operator_wage_index)} = `}
            <Money value={line.operator_wage_current} />
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function PositionBlock({
  position: p,
  norms,
  normLabel,
  onWorkTypeChange,
  chosen,
}: {
  position: PositionOut;
  norms: OverheadNorm[];
  normLabel: Map<string, string>;
  onWorkTypeChange?: (ref: string, code: string) => void;
  chosen: string;
}) {
  const { t } = useTranslation();
  const label = useGroupLabel();
  const f = formatAmount;
  const nrPct = formatFactorString(p.nr_pct);
  const spPct = formatFactorString(p.sp_pct);
  return (
    <div className="rounded-lg border border-border-light">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light px-3 py-2">
        <div className="min-w-0">
          <span className="font-mono text-xs text-content-tertiary">{p.ordinal}</span>{' '}
          <span className="font-medium text-content-primary">{p.description}</span>{' '}
          <span className="text-xs text-content-tertiary">
            {p.quantity} {p.unit}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {onWorkTypeChange ? (
            <select
              aria-label={t('price_index.ri.work_type', { defaultValue: 'Work type' })}
              className={selectClass + ' h-8 text-xs'}
              value={chosen}
              onChange={(e) => onWorkTypeChange(p.ref, e.target.value)}
            >
              <option value="">
                {t('price_index.ri.use_default', { defaultValue: 'Default: {{label}}', label: normLabel.get(p.work_type) ?? p.work_type })}
              </option>
              {norms.map((n) => (
                <option key={n.id} value={n.work_type_code}>
                  {n.label || n.work_type_code}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-content-secondary">{normLabel.get(p.work_type) ?? p.work_type}</span>
          )}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
              <th className="px-2 py-1 font-medium">{t('price_index.ri.col_code', { defaultValue: 'Code' })}</th>
              <th className="px-2 py-1 font-medium">{t('price_index.ri.col_resource', { defaultValue: 'Resource' })}</th>
              <th className="px-2 py-1 font-medium">{t('price_index.ri.col_group', { defaultValue: 'Index group' })}</th>
              <th className="px-2 py-1 text-right font-medium">
                {t('price_index.ri.col_base', { defaultValue: 'Q × consumption × base price' })}
              </th>
              <th className="px-2 py-1 text-right font-medium">{t('price_index.ri.col_current', { defaultValue: '× index = current' })}</th>
            </tr>
          </thead>
          <tbody>
            {p.lines.map((line, i) => (
              <LineRows key={`${line.code}-${i}`} line={line} />
            ))}
          </tbody>
        </table>
      </div>
      <table className="w-full text-sm">
        <tbody>
          <FormulaRow label={label('labor')} value={p.ot} />
          <FormulaRow
            label={label('machine')}
            formula={
              p.otm !== '0.00'
                ? t('price_index.ri.em_of_which', { defaultValue: 'of which OTm {{otm}}', otm: f(p.otm) })
                : undefined
            }
            value={p.em}
          />
          <FormulaRow label={label('material')} value={p.m} />
          <FormulaRow
            label={t('price_index.ri.direct', { defaultValue: 'Direct cost' })}
            formula={`${f(p.ot)} + ${f(p.em)} + ${f(p.m)}`}
            value={p.direct}
          />
          <FormulaRow
            label={t('price_index.ri.fot', { defaultValue: 'Wage fund (FOT)' })}
            formula={`${f(p.ot)} + ${f(p.otm)}`}
            value={p.fot}
          />
          <FormulaRow
            label={t('price_index.ri.nr', { defaultValue: 'Overheads (NR)' })}
            formula={`${f(p.fot)} × ${nrPct}%`}
            value={p.nr}
          />
          <FormulaRow
            label={t('price_index.ri.sp', { defaultValue: 'Estimated profit (SP)' })}
            formula={`${f(p.fot)} × ${spPct}%`}
            value={p.sp}
          />
          <FormulaRow
            label={t('price_index.ri.position_total', { defaultValue: 'Position total' })}
            formula={`${f(p.direct)} + ${f(p.nr)} + ${f(p.sp)}`}
            value={p.total}
            strong
          />
        </tbody>
      </table>
    </div>
  );
}

/* ── Reference data ─────────────────────────────────────────────────────── */

/**
 * An index or percentage edited in place. The draft follows the server value
 * whenever that changes, and goes back to it when the save is refused, so the
 * field never keeps showing a number that was not stored.
 */
function InlineDecimal({
  value,
  ariaLabel,
  widthClass,
  onCommit,
}: {
  value: string;
  ariaLabel: string;
  widthClass: string;
  onCommit: (next: string) => Promise<unknown>;
}) {
  const shown = formatFactorString(value);
  const [draft, setDraft] = useState(shown);
  useEffect(() => setDraft(shown), [shown]);
  return (
    <input
      aria-label={ariaLabel}
      className={selectClass + ' h-8 text-right font-mono ' + widthClass}
      inputMode="decimal"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        const v = toDecimalPayloadString(draft, '');
        if (!v) {
          setDraft(shown);
          return;
        }
        if (v === shown) return;
        onCommit(v).catch(() => setDraft(shown));
      }}
    />
  );
}

function ReferenceData({
  indices,
  norms,
  region,
  quarter,
  onChanged,
}: {
  indices: ResourceIndexValue[];
  norms: OverheadNorm[];
  region: string;
  quarter: string;
  /** Called after an index or norm was stored or removed. */
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const label = useGroupLabel();
  // Entering, editing and removing reference data is price_index.manage on the
  // server; a person without it reads the tables and is not offered controls
  // that could only answer 403.
  const canManage = useHasPermission('price_index.manage');
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
  const refresh = () => {
    // Only the reference lists: the BOQ settings query shares the prefix, and
    // refetching it would race the person's unsaved choices.
    void queryClient.invalidateQueries({ queryKey: QK.indices });
    void queryClient.invalidateQueries({ queryKey: QK.norms });
    onChanged();
  };

  // New index form, prefilled with the selected region and quarter.
  const [newRegion, setNewRegion] = useState(region);
  const [newQuarter, setNewQuarter] = useState(quarter);
  const [newGroup, setNewGroup] = useState<ResourceGroup>('labor');
  const [newValue, setNewValue] = useState('');
  const [newSource, setNewSource] = useState('');
  useEffect(() => setNewRegion((r) => r || region), [region]);
  useEffect(() => setNewQuarter((q) => q || quarter), [quarter]);

  const createIdx = useMutation({
    mutationFn: () =>
      createResourceIndex({
        region_code: newRegion.trim(),
        quarter: normaliseQuarter(newQuarter) ?? newQuarter,
        resource_group: newGroup,
        index_value: toDecimalPayloadString(newValue),
        source: newSource.trim(),
      }),
    onSuccess: () => {
      setNewValue('');
      refresh();
    },
    onError,
  });
  const updateIdx = useMutation({
    mutationFn: (v: { id: string; index_value: string }) => updateResourceIndex(v.id, { index_value: v.index_value }),
    onSuccess: refresh,
    onError,
  });
  const deleteIdx = useMutation({ mutationFn: deleteResourceIndex, onSuccess: refresh, onError });

  const [nCode, setNCode] = useState('');
  const [nLabel, setNLabel] = useState('');
  const [nNr, setNNr] = useState('');
  const [nSp, setNSp] = useState('');
  const [nSource, setNSource] = useState('');
  const createNorm = useMutation({
    mutationFn: () =>
      createOverheadNorm({
        work_type_code: nCode.trim(),
        label: nLabel.trim(),
        nr_pct: toDecimalPayloadString(nNr),
        sp_pct: toDecimalPayloadString(nSp),
        source: nSource.trim(),
      }),
    onSuccess: () => {
      setNCode('');
      setNLabel('');
      setNNr('');
      setNSp('');
      refresh();
    },
    onError,
  });
  const updateNorm = useMutation({
    mutationFn: (v: { id: string; nr_pct?: string; sp_pct?: string }) =>
      updateOverheadNorm(v.id, { nr_pct: v.nr_pct, sp_pct: v.sp_pct }),
    onSuccess: refresh,
    onError,
  });
  const deleteNorm = useMutation({ mutationFn: deleteOverheadNorm, onSuccess: refresh, onError });

  const shown = region ? indices.filter((i) => i.region_code === region) : indices;
  const canAddIndex = newRegion.trim() !== '' && normaliseQuarter(newQuarter) !== null && newValue.trim() !== '';
  const canAddNorm = nCode.trim() !== '' && nNr.trim() !== '' && nSp.trim() !== '';

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader
          title={t('price_index.ri.ref_indices', { defaultValue: 'Resource indices' })}
          subtitle={t('price_index.ri.ref_indices_subtitle', {
            defaultValue: 'One index per group, region and quarter, from the Minstroy quarterly letter. Editing a sample makes it your own value.',
          })}
        />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              {shown.map((i) => (
                <tr key={i.id} className="border-b border-border-light last:border-0">
                  <td className="px-2 py-1.5 font-mono text-xs">{i.region_code}</td>
                  <td className="px-2 py-1.5 font-mono text-xs">{i.quarter}</td>
                  <td className="px-2 py-1.5 text-content-secondary">
                    {label(i.resource_group)}
                    {i.is_sample && (
                      <Badge variant="warning" size="sm" className="ml-1">
                        {t('price_index.ri.sample', { defaultValue: 'sample' })}
                      </Badge>
                    )}
                    {i.source && <div className="text-xs text-content-tertiary">{i.source}</div>}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {canManage ? (
                      <InlineDecimal
                        value={i.index_value}
                        ariaLabel={t('price_index.ri.index_value', { defaultValue: 'Index' })}
                        widthClass="w-24"
                        onCommit={(v) => updateIdx.mutateAsync({ id: i.id, index_value: v })}
                      />
                    ) : (
                      <span className="font-mono">{formatFactorString(i.index_value)}</span>
                    )}
                  </td>
                  <td className="px-1 py-1.5 text-right">
                    {canManage && (
                      <button
                        type="button"
                        className="rounded p-1 text-content-tertiary hover:text-semantic-error"
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        onClick={() => deleteIdx.mutate(i.id)}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && (
            <p className="py-2 text-sm text-content-tertiary">
              {t('price_index.ri.no_indices', { defaultValue: 'No indices entered for this region yet.' })}
            </p>
          )}
        </div>
        {canManage && (
          <>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Input
                placeholder={t('price_index.ri.region_ph', { defaultValue: 'Region, e.g. RU-MOW' })}
                value={newRegion}
                onChange={(e) => setNewRegion(e.target.value)}
              />
              <Input
                placeholder={t('price_index.ri.quarter_ph', { defaultValue: 'Quarter, e.g. 2026-Q2' })}
                value={newQuarter}
                onChange={(e) => setNewQuarter(e.target.value)}
              />
              <select className={selectClass} value={newGroup} onChange={(e) => setNewGroup(e.target.value as ResourceGroup)}>
                {RESOURCE_GROUPS.map((g) => (
                  <option key={g} value={g}>
                    {label(g)}
                  </option>
                ))}
              </select>
              <Input
                placeholder={t('price_index.ri.index_value', { defaultValue: 'Index' })}
                inputMode="decimal"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
              />
              <Input
                className="sm:col-span-2"
                placeholder={t('price_index.ri.source_ph', { defaultValue: 'Source, e.g. the letter number and date' })}
                value={newSource}
                onChange={(e) => setNewSource(e.target.value)}
              />
            </div>
            <Button className="mt-2" size="sm" variant="secondary" disabled={!canAddIndex || createIdx.isPending} onClick={() => createIdx.mutate()}>
              <Plus className="mr-1 h-4 w-4" aria-hidden />
              {t('price_index.ri.add_index', { defaultValue: 'Add index' })}
            </Button>
          </>
        )}
      </Card>

      <Card>
        <CardHeader
          title={t('price_index.ri.ref_norms', { defaultValue: 'Overheads and profit by work type' })}
          subtitle={t('price_index.ri.ref_norms_subtitle', {
            defaultValue: 'NR (order 812/pr) and SP (order 774/pr) as percentages of the wage fund.',
          })}
        />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
                <th className="px-2 py-1 font-medium">{t('price_index.ri.work_type', { defaultValue: 'Work type' })}</th>
                <th className="px-2 py-1 text-right font-medium">{t('price_index.ri.nr_pct', { defaultValue: 'NR %' })}</th>
                <th className="px-2 py-1 text-right font-medium">{t('price_index.ri.sp_pct', { defaultValue: 'SP %' })}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {norms.map((n) => (
                <tr key={n.id} className="border-b border-border-light last:border-0">
                  <td className="px-2 py-1.5 text-content-secondary">
                    {n.label || n.work_type_code}
                    <span className="ml-1 font-mono text-xs text-content-tertiary">{n.work_type_code}</span>
                    {n.is_sample && (
                      <Badge variant="warning" size="sm" className="ml-1">
                        {t('price_index.ri.sample', { defaultValue: 'sample' })}
                      </Badge>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {canManage ? (
                      <InlineDecimal
                        value={n.nr_pct}
                        ariaLabel={t('price_index.ri.nr_pct', { defaultValue: 'NR %' })}
                        widthClass="w-20"
                        onCommit={(v) => updateNorm.mutateAsync({ id: n.id, nr_pct: v })}
                      />
                    ) : (
                      <span className="font-mono">{formatFactorString(n.nr_pct)}</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {canManage ? (
                      <InlineDecimal
                        value={n.sp_pct}
                        ariaLabel={t('price_index.ri.sp_pct', { defaultValue: 'SP %' })}
                        widthClass="w-20"
                        onCommit={(v) => updateNorm.mutateAsync({ id: n.id, sp_pct: v })}
                      />
                    ) : (
                      <span className="font-mono">{formatFactorString(n.sp_pct)}</span>
                    )}
                  </td>
                  <td className="px-1 py-1.5 text-right">
                    {canManage && (
                      <button
                        type="button"
                        className="rounded p-1 text-content-tertiary hover:text-semantic-error"
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        onClick={() => deleteNorm.mutate(n.id)}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canManage && (
          <>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Input
                placeholder={t('price_index.ri.work_type_code_ph', { defaultValue: 'Code' })}
                value={nCode}
                onChange={(e) => setNCode(e.target.value)}
              />
              <Input
                className="sm:col-span-3"
                placeholder={t('price_index.ri.work_type_label_ph', { defaultValue: 'Work type name' })}
                value={nLabel}
                onChange={(e) => setNLabel(e.target.value)}
              />
              <Input
                placeholder={t('price_index.ri.nr_pct', { defaultValue: 'NR %' })}
                inputMode="decimal"
                value={nNr}
                onChange={(e) => setNNr(e.target.value)}
              />
              <Input
                placeholder={t('price_index.ri.sp_pct', { defaultValue: 'SP %' })}
                inputMode="decimal"
                value={nSp}
                onChange={(e) => setNSp(e.target.value)}
              />
              <Input
                className="col-span-2"
                placeholder={t('price_index.ri.norm_source_ph', { defaultValue: 'Source, e.g. order and item' })}
                value={nSource}
                onChange={(e) => setNSource(e.target.value)}
              />
            </div>
            <Button className="mt-2" size="sm" variant="secondary" disabled={!canAddNorm || createNorm.isPending} onClick={() => createNorm.mutate()}>
              <Plus className="mr-1 h-4 w-4" aria-hidden />
              {t('price_index.ri.add_norm', { defaultValue: 'Add work type' })}
            </Button>
          </>
        )}
      </Card>
    </div>
  );
}
