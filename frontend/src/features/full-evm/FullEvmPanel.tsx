// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Full EVM — what a project has earned against what it planned and what it paid.
 *
 * Earned value is a method people quote and rarely read carefully, so the
 * screen is arranged to stop the three usual misreadings.
 *
 * An index near one is not ahead or behind. Every index here is banded through
 * `indexBand`, which treats anything within half a percent of 1.0 as on track,
 * because a project reported as "behind" at an SPI of 0.998 trains people to
 * ignore the colour entirely.
 *
 * The EAC formula that was asked for is not always the one that ran. When a
 * divisor is zero the register falls back to a simpler formula and says so in a
 * second field, and this screen prints which formula actually produced the
 * number rather than letting the request stand in for the answer.
 *
 * A baseline is approvable only where its own rules last passed, and the server
 * re-runs them before it decides. So the button here reads the last known
 * verdict and "check again" sits beside it, rather than the screen pretending
 * to be the authority.
 *
 * Every figure crosses the wire as a plain-decimal string and is rendered as
 * one. Nothing on this screen recomputes a metric the register already
 * published; what it does compute - the spread between EAC variants, how many
 * curve points carry no measurement - is arithmetic *about* those figures and
 * is labelled as derived where it appears.
 */

import { type ReactNode, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  BellOff,
  CheckCircle2,
  ClipboardCheck,
  LineChart,
  Plus,
  ShieldCheck,
  Trash2,
  TrendingUp,
} from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi } from '@/features/projects/api';

import {
  type Baseline,
  type EacMethod,
  type ForecastMethod,
  type Measure,
  type ValidationReport,
  acknowledgeForecastAlert,
  approveBaseline,
  calculateForecast,
  createBaseline,
  deleteBaseline,
  getBaselineSCurve,
  getMetricGlossary,
  listBaselines,
  listForecastAlerts,
  listForecasts,
  listMeasures,
  recordMeasure,
  snoozeForecastAlert,
  validateBaseline,
} from './api';
import {
  type IndexBand,
  type Tone,
  baselineStatusTone,
  canApprove,
  eacMethodWasHonoured,
  eacVariantSpread,
  fractionToPercent,
  indexBand,
  indexTone,
  latestMeasure,
  parseFigure,
  tcpiOutlook,
  tcpiTone,
  unmeasuredPoints,
  validationTone,
  varianceTone,
} from './evmIndicators';
import { fmtFixed } from '@/shared/lib/formatters';

type Tab = 'progress' | 'curve' | 'forecast';

const EAC_METHODS: EacMethod[] = ['auto', 'remaining', 'cpi', 'combined'];
const FORECAST_METHODS: ForecastMethod[] = ['auto', 'remaining', 'cpi', 'combined', 'spi_cpi'];

/* ── Reading a figure out loud ─────────────────────────────────────────── */

/** A wire figure with its currency, or an explicit "not computable". */
function Figure({ value, currency }: { value: string | null | undefined; currency?: string | null }) {
  const { t } = useTranslation();
  if (value === null || value === undefined || value === '') {
    return (
      <span className="text-content-tertiary">
        {t('full_evm.not_computable', { defaultValue: 'not computable' })}
      </span>
    );
  }
  return (
    <span className="tabular-nums">
      {value}
      {currency ? ` ${currency}` : ''}
    </span>
  );
}

function bandLabel(band: IndexBand, t: (k: string, o?: Record<string, unknown>) => string): string {
  switch (band) {
    case 'ahead':
      return t('full_evm.band_ahead', { defaultValue: 'ahead' });
    case 'on_track':
      return t('full_evm.band_on_track', { defaultValue: 'on track' });
    case 'behind':
      return t('full_evm.band_behind', { defaultValue: 'behind' });
    case 'undefined':
      return t('full_evm.band_undefined', { defaultValue: 'no reading' });
  }
}

/** One indicator: the figure the register published, banded but not recomputed. */
function IndexTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | null | undefined;
  hint?: string;
}) {
  const { t } = useTranslation();
  const band = indexBand(value);
  return (
    <div className="rounded-md border border-border bg-surface-primary p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-content-tertiary">{label}</span>
        <Badge variant={indexTone(band) as Tone} size="sm">
          {bandLabel(band, t)}
        </Badge>
      </div>
      <div className="mt-0.5 text-sm text-content-primary">
        <Figure value={value} />
      </div>
      {hint && <p className="mt-0.5 text-[11px] text-content-tertiary">{hint}</p>}
    </div>
  );
}

/**
 * The dot colours, written out.
 *
 * Tailwind reads class names statically, so a class assembled from a variable
 * is dropped at build time and the dot renders colourless. The map keeps every
 * class a literal the scanner can see.
 */
const TONE_DOT: Record<Tone, string> = {
  neutral: 'bg-content-tertiary',
  blue: 'bg-oe-blue',
  success: 'bg-semantic-success',
  warning: 'bg-[#b45309]',
  error: 'bg-semantic-error',
};

function MoneyTile({
  label,
  value,
  currency,
  tone,
  hint,
}: {
  label: string;
  value: string | null | undefined;
  currency?: string | null;
  tone?: Tone;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-surface-primary p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-content-tertiary">{label}</span>
        {tone && <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]}`} />}
      </div>
      <div className="mt-0.5 text-sm text-content-primary">
        <Figure value={value} currency={currency} />
      </div>
      {hint && <p className="mt-0.5 text-[11px] text-content-tertiary">{hint}</p>}
    </div>
  );
}

/* ── Findings, shared by baseline and measure ──────────────────────────── */

function Findings({ report }: { report: ValidationReport | null }) {
  const { t } = useTranslation();
  if (!report) return null;
  return (
    <div className="rounded-md border border-border bg-surface-secondary p-2.5">
      <div className="flex items-center gap-1.5">
        <ShieldCheck size={13} />
        <span className="text-xs font-medium text-content-primary">
          {t('full_evm.report_title', { defaultValue: 'What the rules found' })}
        </span>
        <Badge variant={validationTone(report.status) as Tone} size="sm">
          {report.status}
        </Badge>
      </div>
      {report.findings.length === 0 ? (
        <p className="mt-1 text-xs text-content-tertiary">
          {t('full_evm.report_clean', { defaultValue: 'Nothing to report on this baseline.' })}
        </p>
      ) : (
        <ul className="mt-1.5 space-y-1">
          {report.findings.map((finding, index) => (
            <li key={`${finding.rule_id}-${index}`} className="text-xs">
              <span className="text-content-primary">{finding.message}</span>
              {finding.suggestion && (
                <span className="block text-content-tertiary">{finding.suggestion}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Recording a measurement ───────────────────────────────────────────── */

function MeasureForm({
  baseline,
  onClose,
}: {
  baseline: Baseline;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [dataDate, setDataDate] = useState('');
  const [ev, setEv] = useState('');
  const [ac, setAc] = useState('');
  const [pv, setPv] = useState('');
  const [method, setMethod] = useState<EacMethod>('auto');
  const [notes, setNotes] = useState('');

  const mutation = useMutation({
    mutationFn: () =>
      recordMeasure(baseline.id, {
        data_date: dataDate,
        ev: ev.trim(),
        ac: ac.trim(),
        pv: pv.trim() || null,
        eac_method: method,
        source: 'manual',
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['full-evm', 'measures', baseline.id] });
      onClose();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('full_evm.measure_failed', { defaultValue: 'The measurement was not recorded' }),
        message: getErrorMessage(err),
      }),
  });

  const incomplete = dataDate === '' || ev.trim() === '' || ac.trim() === '';

  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface-primary p-3">
      <p className="text-xs text-content-tertiary">
        {t('full_evm.measure_intro', {
          defaultValue:
            'Earned value is what the work completed was worth at the planned rate, and actual cost is what it cost. Leave planned value empty to read it off the baseline curve at this date.',
        })}
      </p>
      <div className="grid gap-2 sm:grid-cols-4">
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('full_evm.field_data_date', { defaultValue: 'As at' })}
          </span>
          <input
            type="date"
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={dataDate}
            onChange={(e) => setDataDate(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('full_evm.field_ev', { defaultValue: 'Earned value' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm tabular-nums"
            value={ev}
            inputMode="decimal"
            onChange={(e) => setEv(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('full_evm.field_ac', { defaultValue: 'Actual cost' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm tabular-nums"
            value={ac}
            inputMode="decimal"
            onChange={(e) => setAc(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('full_evm.field_pv', { defaultValue: 'Planned value' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm tabular-nums"
            value={pv}
            inputMode="decimal"
            placeholder={t('full_evm.field_pv_placeholder', { defaultValue: 'from the curve' })}
            onChange={(e) => setPv(e.target.value)}
          />
        </label>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('full_evm.field_eac_method', { defaultValue: 'Forecast the outturn by' })}
          </span>
          <select
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={method}
            onChange={(e) => setMethod(e.target.value as EacMethod)}
          >
            {EAC_METHODS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('full_evm.field_notes', { defaultValue: 'Notes' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={incomplete}
          loading={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {t('full_evm.action_record', { defaultValue: 'Record it' })}
        </Button>
      </div>
    </div>
  );
}

/* ── One measurement, read out ─────────────────────────────────────────── */

function MeasureCard({ measure, currency }: { measure: Measure; currency: string | null }) {
  const { t } = useTranslation();
  const honoured = eacMethodWasHonoured(measure);
  const spread = eacVariantSpread(measure.eac_variants);
  const outlook = tcpiOutlook(measure.tcpi_eac, measure.cpi);
  const complete = fractionToPercent(measure.percent_complete);
  const spent = fractionToPercent(measure.percent_spent);

  return (
    <li className="space-y-2 rounded-lg border border-border bg-surface-primary p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-content-primary tabular-nums">
          {measure.data_date}
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="neutral" size="sm">
            {measure.source}
          </Badge>
          <Badge variant={validationTone(measure.validation_status) as Tone} size="sm">
            {measure.validation_status}
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-4">
        <IndexTile label="SPI" value={measure.spi} />
        <IndexTile label="CPI" value={measure.cpi} />
        <MoneyTile
          label="SV"
          value={measure.sv}
          currency={currency}
          tone={varianceTone(measure.sv) as Tone}
        />
        <MoneyTile
          label="CV"
          value={measure.cv}
          currency={currency}
          tone={varianceTone(measure.cv) as Tone}
        />
      </div>

      <div className="grid gap-2 sm:grid-cols-4">
        <MoneyTile label="EV" value={measure.ev} currency={currency} />
        <MoneyTile label="AC" value={measure.ac} currency={currency} />
        <MoneyTile label="PV" value={measure.pv} currency={currency} />
        <MoneyTile label="BAC" value={measure.bac} currency={currency} />
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <MoneyTile
          label={t('full_evm.metric_eac', { defaultValue: 'Outturn (EAC)' })}
          value={measure.eac}
          currency={currency}
          hint={
            honoured
              ? t('full_evm.eac_method_used', {
                  defaultValue: 'by {{method}}',
                  method: measure.eac_method_effective,
                })
              : t('full_evm.eac_method_substituted', {
                  defaultValue:
                    '{{asked}} could not be computed, so {{used}} produced this figure',
                  asked: measure.eac_method,
                  used: measure.eac_method_effective,
                })
          }
        />
        <MoneyTile
          label={t('full_evm.metric_etc', { defaultValue: 'Still to spend (ETC)' })}
          value={measure.etc}
          currency={currency}
        />
        <MoneyTile
          label={t('full_evm.metric_vac', { defaultValue: 'Against budget (VAC)' })}
          value={measure.vac}
          currency={currency}
          tone={varianceTone(measure.vac) as Tone}
        />
      </div>

      {!honoured && (
        <p className="flex items-start gap-1.5 text-xs text-[#b45309]">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          {t('full_evm.eac_substituted_note', {
            defaultValue:
              'The formula asked for needed a divisor this measurement does not have, which is ordinary before anything has been earned. The figure above is the fallback, not the formula requested.',
          })}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {complete !== null && (
          <Badge variant="neutral" size="sm">
            {t('full_evm.percent_complete', {
              defaultValue: '{{percent}}% of the work earned',
              percent: fmtFixed(complete, 1),
            })}
          </Badge>
        )}
        {spent !== null && (
          <Badge variant="neutral" size="sm">
            {t('full_evm.percent_spent', {
              defaultValue: '{{percent}}% of the budget spent',
              percent: fmtFixed(spent, 1),
            })}
          </Badge>
        )}
        {measure.tcpi_eac && (
          <Badge variant={tcpiTone(outlook) as Tone} size="sm">
            {t('full_evm.tcpi_badge', {
              defaultValue: 'needs {{value}} from here',
              value: measure.tcpi_eac,
            })}
          </Badge>
        )}
      </div>

      {outlook === 'above_achieved' && (
        <p className="text-xs text-[#b45309]">
          {t('full_evm.tcpi_above_note', {
            defaultValue:
              'The remaining work has to run more efficiently than anything achieved so far to land on this outturn. That is a plan, not a forecast, until something changes on site.',
          })}
        </p>
      )}

      {spread && (
        <p className="text-xs text-content-tertiary">
          {t('full_evm.eac_spread', {
            defaultValue:
              'The formulas disagree by {{spread}} on the outturn, from {{low}} to {{high}}. Worked out here from the variants the register published.',
            spread: fmtFixed(spread.spread, 2),
            low: fmtFixed(spread.low, 2),
            high: fmtFixed(spread.high, 2),
          })}
        </p>
      )}

      {measure.notes && <p className="text-xs italic text-content-tertiary">{measure.notes}</p>}
    </li>
  );
}

/* ── The panel ─────────────────────────────────────────────────────────── */

export function FullEvmPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('progress');
  const [measuring, setMeasuring] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newBac, setNewBac] = useState('');
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [forecastMethod, setForecastMethod] = useState<ForecastMethod>('auto');
  const [glossaryOpen, setGlossaryOpen] = useState(false);

  const projectQuery = useQuery({
    queryKey: ['project', activeProjectId],
    queryFn: () => projectsApi.get(activeProjectId as string),
    enabled: !!activeProjectId && creating,
    staleTime: 0,
  });
  const projectReady = projectQuery.isSuccess && projectQuery.fetchStatus === 'idle'
    && projectQuery.data.id === activeProjectId;

  const baselinesQuery = useQuery({
    queryKey: ['full-evm', 'baselines', activeProjectId],
    queryFn: () => listBaselines({ projectId: activeProjectId as string, limit: 50 }),
    enabled: !!activeProjectId,
  });

  const baselines = baselinesQuery.data?.items ?? [];
  const selected = baselines.find((b) => b.id === selectedId) ?? baselines[0] ?? null;

  const measuresQuery = useQuery({
    queryKey: ['full-evm', 'measures', selected?.id],
    queryFn: () => listMeasures({ baselineId: selected?.id as string, limit: 50 }),
    enabled: !!selected && tab === 'progress',
  });

  const curveQuery = useQuery({
    queryKey: ['full-evm', 'curve', selected?.id],
    queryFn: () => getBaselineSCurve(selected?.id as string),
    enabled: !!selected && tab === 'curve',
  });

  const forecastsQuery = useQuery({
    queryKey: ['full-evm', 'forecasts', activeProjectId],
    queryFn: () => listForecasts(activeProjectId as string),
    enabled: !!activeProjectId && tab === 'forecast',
  });

  const alertsQuery = useQuery({
    queryKey: ['full-evm', 'alerts', activeProjectId],
    queryFn: () => listForecastAlerts(activeProjectId as string),
    enabled: !!activeProjectId && tab === 'forecast',
  });

  const glossaryQuery = useQuery({
    queryKey: ['full-evm', 'glossary'],
    queryFn: getMetricGlossary,
    enabled: glossaryOpen,
    staleTime: 30 * 60 * 1000,
  });

  const measures = useMemo(() => measuresQuery.data?.items ?? [], [measuresQuery.data]);
  const newest = useMemo(() => latestMeasure(measures), [measures]);
  const uncounted = useMemo(
    () => (curveQuery.data ? unmeasuredPoints(curveQuery.data.points) : 0),
    [curveQuery.data],
  );

  const createMutation = useMutation({
    mutationFn: () => {
      if (!projectReady) throw new Error(t('common.error', { defaultValue: 'Error' }));
      return createBaseline({
        project_id: activeProjectId as string,
        name: newName.trim(),
        bac: newBac.trim(),
        // A successfully read but unset denomination stays unknown. The
        // server chooses precision; never relabel existing baselines here.
        currency: projectQuery.data.currency?.trim().toUpperCase() || null,
      });
    },
    onSuccess: (baseline) => {
      setCreating(false);
      setNewName('');
      setNewBac('');
      setSelectedId(baseline.id);
      queryClient.invalidateQueries({ queryKey: ['full-evm', 'baselines', activeProjectId] });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('full_evm.create_failed', { defaultValue: 'The baseline was not created' }),
        message: getErrorMessage(err),
      }),
  });

  const validateMutation = useMutation({
    mutationFn: () => validateBaseline(selected?.id as string),
    onSuccess: (data) => {
      setReport(data);
      queryClient.invalidateQueries({ queryKey: ['full-evm', 'baselines', activeProjectId] });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('full_evm.validate_failed', { defaultValue: 'The baseline could not be checked' }),
        message: getErrorMessage(err),
      }),
  });

  const approveMutation = useMutation({
    mutationFn: () => approveBaseline(selected?.id as string),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['full-evm', 'baselines', activeProjectId] }),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('full_evm.approve_failed', { defaultValue: 'The baseline was not approved' }),
        message: getErrorMessage(err),
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteBaseline(selected?.id as string),
    onSuccess: () => {
      setConfirmDelete(false);
      setSelectedId(null);
      queryClient.invalidateQueries({ queryKey: ['full-evm', 'baselines', activeProjectId] });
    },
    onError: (err) => {
      setConfirmDelete(false);
      addToast({
        type: 'error',
        title: t('full_evm.delete_failed', { defaultValue: 'The baseline was not deleted' }),
        message: getErrorMessage(err),
      });
    },
  });

  const forecastMutation = useMutation({
    mutationFn: () => calculateForecast(activeProjectId as string, forecastMethod),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['full-evm', 'forecasts', activeProjectId] });
      queryClient.invalidateQueries({ queryKey: ['full-evm', 'alerts', activeProjectId] });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('full_evm.forecast_failed', { defaultValue: 'The forecast did not run' }),
        message: getErrorMessage(err),
      }),
  });

  const ackMutation = useMutation({
    mutationFn: (id: string) => acknowledgeForecastAlert(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['full-evm', 'alerts', activeProjectId] }),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('full_evm.alert_failed', { defaultValue: 'The alert was not changed' }),
        message: getErrorMessage(err),
      }),
  });

  const snoozeMutation = useMutation({
    mutationFn: (id: string) => snoozeForecastAlert(id, 24),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['full-evm', 'alerts', activeProjectId] }),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('full_evm.alert_failed', { defaultValue: 'The alert was not changed' }),
        message: getErrorMessage(err),
      }),
  });

  /* Every hook is above this line; the guards start here. */

  if (!activeProjectId) {
    return (
      <EmptyState
        icon={<LineChart size={28} />}
        title={t('full_evm.no_project', { defaultValue: 'Pick a project first' })}
        description={t('full_evm.no_project_hint', {
          defaultValue: 'A baseline is the plan of one project and is measured against that project.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-medium text-content-primary">
          {t('full_evm.baselines_title', { defaultValue: 'Baselines' })}
        </h2>
        <div className="flex gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            icon={<ClipboardCheck size={13} />}
            onClick={() => setGlossaryOpen((open) => !open)}
          >
            {t('full_evm.action_glossary', { defaultValue: 'What these mean' })}
          </Button>
          {!creating && (
            <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setCreating(true)}>
              {t('full_evm.action_new_baseline', { defaultValue: 'New baseline' })}
            </Button>
          )}
        </div>
      </div>

      {glossaryOpen && (
        <div className="rounded-lg border border-border bg-surface-secondary p-3">
          {glossaryQuery.isLoading && (
            <p className="text-xs text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          )}
          {glossaryQuery.data && (
            <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
              {glossaryQuery.data.metrics.map((entry) => (
                <div key={entry.code}>
                  <dt className="text-xs font-medium text-content-primary">
                    {entry.code} - {entry.label}
                  </dt>
                  <dd className="text-xs text-content-tertiary">{entry.explanation}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}

      {creating && (
        <div className="space-y-2 rounded-lg border border-border bg-surface-primary p-3">
          {!projectReady && (
            projectQuery.fetchStatus === 'fetching' ? (
              <p role="status" className="text-xs text-content-tertiary">
                {t('common.loading', { defaultValue: 'Loading...' })}
              </p>
            ) : (
              <div role="alert" className="flex items-center gap-2 text-xs text-semantic-error">
                <span>{projectQuery.error ? getErrorMessage(projectQuery.error) : t('common.error', { defaultValue: 'Error' })}</span>
                <Button variant="ghost" size="sm" onClick={() => void projectQuery.refetch()}>
                  {t('common.retry', { defaultValue: 'Retry' })}
                </Button>
              </div>
            )
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs text-content-secondary">
                {t('full_evm.field_baseline_name', { defaultValue: 'Name' })}
              </span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs text-content-secondary">
                {t('full_evm.field_bac', { defaultValue: 'Budget at completion' })}
              </span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm tabular-nums"
                value={newBac}
                inputMode="decimal"
                onChange={(e) => setNewBac(e.target.value)}
              />
            </label>
          </div>
          <p className="text-xs text-content-tertiary">
            {t('full_evm.create_note', {
              defaultValue:
                'A baseline starts as a draft with no periods. Add the planned spend period by period, check it, then approve it - an approved baseline is what everything afterwards is measured against.',
            })}
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!projectReady || newName.trim() === '' || newBac.trim() === ''}
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {t('common.create', { defaultValue: 'Create' })}
            </Button>
          </div>
        </div>
      )}

      {baselinesQuery.isLoading && (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      )}

      {!baselinesQuery.isLoading && baselines.length === 0 && !creating && (
        <EmptyState
          icon={<LineChart size={28} />}
          title={t('full_evm.empty_title', { defaultValue: 'This project has no baseline' })}
          description={t('full_evm.empty_description', {
            defaultValue:
              'Earned value needs a plan to measure against: a budget, and how it was expected to be spent over time. Nothing here can be read without one.',
          })}
          action={{
            label: t('full_evm.action_new_baseline', { defaultValue: 'New baseline' }),
            onClick: () => setCreating(true),
          }}
        />
      )}

      {baselines.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {baselines.map((baseline) => (
            <button
              key={baseline.id}
              type="button"
              onClick={() => {
                setSelectedId(baseline.id);
                setReport(null);
              }}
              className={
                'rounded-md border px-2.5 py-1.5 text-left text-xs ' +
                (baseline.id === selected?.id
                  ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                  : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary')
              }
            >
              <span className="block font-medium">{baseline.name}</span>
              <span className="block tabular-nums text-content-tertiary">
                {baseline.bac} {baseline.currency ?? ''}
              </span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="space-y-3 rounded-lg border border-border bg-surface-primary p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium text-content-primary">{selected.name}</h3>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <Badge variant={baselineStatusTone(selected.status) as Tone} size="sm">
                  {selected.status}
                </Badge>
                <Badge variant={validationTone(selected.validation_status) as Tone} size="sm">
                  {selected.validation_status}
                </Badge>
                <span className="text-xs tabular-nums text-content-tertiary">
                  {selected.bac} {selected.currency ?? ''}
                </span>
                <span className="text-xs text-content-tertiary">
                  {t('full_evm.period_count', {
                    defaultValue: '{{count}} periods',
                    count: selected.periods.length,
                  })}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                icon={<ShieldCheck size={13} />}
                loading={validateMutation.isPending}
                onClick={() => validateMutation.mutate()}
              >
                {t('full_evm.action_validate', { defaultValue: 'Check again' })}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!canApprove(selected)}
                loading={approveMutation.isPending}
                icon={<CheckCircle2 size={13} />}
                onClick={() => approveMutation.mutate()}
              >
                {t('full_evm.action_approve', { defaultValue: 'Approve' })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Trash2 size={13} />}
                onClick={() => setConfirmDelete(true)}
              >
                {t('common.delete', { defaultValue: 'Delete' })}
              </Button>
            </div>
          </div>

          {!canApprove(selected) && selected.status !== 'approved' && (
            <p className="text-xs text-content-tertiary">
              {t('full_evm.approve_blocked', {
                defaultValue:
                  'The last check on this baseline found blocking errors, so approval is refused until they are fixed and it is checked again.',
              })}
            </p>
          )}

          {selected.periods.length === 0 && (
            <p className="flex items-start gap-1.5 rounded-md bg-semantic-warning-bg px-2 py-1.5 text-xs text-[#b45309]">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              {t('full_evm.no_periods', {
                defaultValue:
                  'This baseline has a budget but no spending plan, so there is no curve to measure against and planned value cannot be read at any date.',
              })}
            </p>
          )}

          <Findings report={report} />

          <div className="flex gap-1 border-b border-border">
            {(
              [
                ['progress', t('full_evm.tab_progress', { defaultValue: 'Progress' }), <Activity key="a" size={13} />],
                ['curve', t('full_evm.tab_curve', { defaultValue: 'The plan' }), <LineChart key="c" size={13} />],
                ['forecast', t('full_evm.tab_forecast', { defaultValue: 'Forecast' }), <TrendingUp key="f" size={13} />],
              ] as Array<[Tab, string, ReactNode]>
            ).map(([key, label, icon]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={
                  'flex items-center gap-1.5 px-3 py-1.5 text-xs ' +
                  (tab === key
                    ? 'border-b-2 border-oe-blue text-oe-blue-text'
                    : 'text-content-secondary hover:text-content-primary')
                }
              >
                {icon}
                {label}
              </button>
            ))}
          </div>

          {tab === 'progress' && (
            <div className="space-y-3">
              <div className="flex justify-end">
                {!measuring && (
                  <Button variant="secondary" size="sm" icon={<Plus size={13} />} onClick={() => setMeasuring(true)}>
                    {t('full_evm.action_measure', { defaultValue: 'Record a measurement' })}
                  </Button>
                )}
              </div>
              {measuring && <MeasureForm baseline={selected} onClose={() => setMeasuring(false)} />}

              {measuresQuery.isLoading && (
                <p className="text-sm text-content-tertiary">
                  {t('common.loading', { defaultValue: 'Loading...' })}
                </p>
              )}
              {!measuresQuery.isLoading && measures.length === 0 && (
                <p className="rounded-md bg-surface-secondary px-3 py-4 text-center text-xs text-content-tertiary">
                  {t('full_evm.no_measures', {
                    defaultValue:
                      'Nothing has been measured against this baseline yet, so there are no indices to read.',
                  })}
                </p>
              )}
              {newest && (
                <p className="text-xs text-content-tertiary">
                  {t('full_evm.latest_note', {
                    defaultValue: 'The most recent measurement is dated {{date}}.',
                    date: newest.data_date,
                  })}
                </p>
              )}
              {measures.length > 0 && (
                <ul className="space-y-2">
                  {measures.map((measure) => (
                    <MeasureCard key={measure.id} measure={measure} currency={selected.currency} />
                  ))}
                </ul>
              )}
            </div>
          )}

          {tab === 'curve' && (
            <div className="space-y-2">
              {curveQuery.isLoading && (
                <p className="text-sm text-content-tertiary">
                  {t('common.loading', { defaultValue: 'Loading...' })}
                </p>
              )}
              {curveQuery.data && (
                <>
                  {uncounted > 0 && (
                    <p className="text-xs text-content-tertiary">
                      {t('full_evm.curve_unmeasured', {
                        defaultValue:
                          '{{count}} of these points carry no measurement, so the plan is drawn there and nothing is claimed about what was earned.',
                        count: uncounted,
                      })}
                    </p>
                  )}
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[32rem] text-xs">
                      <thead>
                        <tr className="text-content-tertiary">
                          <th className="py-1 text-left font-normal">
                            {t('full_evm.col_period', { defaultValue: 'Period' })}
                          </th>
                          <th className="py-1 text-right font-normal">
                            {t('full_evm.col_planned', { defaultValue: 'Planned' })}
                          </th>
                          <th className="py-1 text-right font-normal">
                            {t('full_evm.col_earned', { defaultValue: 'Earned' })}
                          </th>
                          <th className="py-1 text-right font-normal">
                            {t('full_evm.col_actual', { defaultValue: 'Actual' })}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {curveQuery.data.points.map((point) => (
                          <tr key={point.as_of} className="border-t border-border">
                            <td className="py-1 text-content-primary">
                              {point.label || point.as_of}
                            </td>
                            <td className="py-1 text-right tabular-nums">{point.planned_value}</td>
                            <td className="py-1 text-right tabular-nums">
                              <Figure value={point.earned_value} />
                            </td>
                            <td className="py-1 text-right tabular-nums">
                              <Figure value={point.actual_cost} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}

          {tab === 'forecast' && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-end gap-2">
                <label className="block">
                  <span className="text-xs text-content-secondary">
                    {t('full_evm.field_forecast_method', { defaultValue: 'Forecast by' })}
                  </span>
                  <select
                    className="mt-1 rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                    value={forecastMethod}
                    onChange={(e) => setForecastMethod(e.target.value as ForecastMethod)}
                  >
                    {FORECAST_METHODS.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  variant="primary"
                  size="sm"
                  loading={forecastMutation.isPending}
                  icon={<TrendingUp size={13} />}
                  onClick={() => forecastMutation.mutate()}
                >
                  {t('full_evm.action_forecast', { defaultValue: 'Work it out' })}
                </Button>
              </div>

              {(alertsQuery.data?.items ?? []).length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-xs font-medium text-content-primary">
                    {t('full_evm.alerts_title', { defaultValue: 'Forecasts that tripped a threshold' })}
                  </span>
                  {(alertsQuery.data?.items ?? []).map((alert) => (
                    <div
                      key={alert.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-semantic-warning-bg bg-semantic-warning-bg/40 p-2 text-xs"
                    >
                      <span className="text-content-primary">
                        {t('full_evm.alert_line', {
                          defaultValue: 'On {{date}}, outturn {{eac}} against budget, variance {{vac}}',
                          date: alert.forecast_date,
                          eac: alert.eac,
                          vac: alert.vac,
                        })}
                      </span>
                      <span className="flex gap-1.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<CheckCircle2 size={12} />}
                          onClick={() => ackMutation.mutate(alert.id)}
                        >
                          {t('full_evm.action_ack', { defaultValue: 'Seen' })}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<BellOff size={12} />}
                          onClick={() => snoozeMutation.mutate(alert.id)}
                        >
                          {t('full_evm.action_snooze', { defaultValue: 'Not today' })}
                        </Button>
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {forecastsQuery.isLoading && (
                <p className="text-sm text-content-tertiary">
                  {t('common.loading', { defaultValue: 'Loading...' })}
                </p>
              )}
              {!forecastsQuery.isLoading && (forecastsQuery.data?.items ?? []).length === 0 && (
                <p className="rounded-md bg-surface-secondary px-3 py-4 text-center text-xs text-content-tertiary">
                  {t('full_evm.no_forecasts', {
                    defaultValue:
                      'No forecast has been worked out for this project. One needs at least one measurement to read from.',
                  })}
                </p>
              )}
              {(forecastsQuery.data?.items ?? []).length > 0 && (
                <ul className="space-y-1.5">
                  {(forecastsQuery.data?.items ?? []).map((forecast) => {
                    const low = parseFigure(forecast.confidence_range_low);
                    const high = parseFigure(forecast.confidence_range_high);
                    return (
                      <li key={forecast.id} className="rounded-md border border-border bg-surface-primary p-2.5 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="tabular-nums text-content-primary">
                            {forecast.forecast_date}
                          </span>
                          <Badge variant="neutral" size="sm">
                            {forecast.forecast_method}
                          </Badge>
                        </div>
                        <div className="mt-1 grid gap-2 sm:grid-cols-4">
                          <MoneyTile
                            label={t('full_evm.metric_eac', { defaultValue: 'Outturn (EAC)' })}
                            value={forecast.eac}
                            currency={selected.currency}
                          />
                          <MoneyTile
                            label={t('full_evm.metric_etc', { defaultValue: 'Still to spend (ETC)' })}
                            value={forecast.etc}
                            currency={selected.currency}
                          />
                          <MoneyTile
                            label={t('full_evm.metric_vac', { defaultValue: 'Against budget (VAC)' })}
                            value={forecast.vac}
                            currency={selected.currency}
                            tone={varianceTone(forecast.vac) as Tone}
                          />
                          <IndexTile label="TCPI" value={forecast.tcpi} />
                        </div>
                        {low !== null && high !== null && (
                          <p className="mt-1 text-content-tertiary">
                            {t('full_evm.forecast_range', {
                              defaultValue: 'Between {{low}} and {{high}} on the register’s own range.',
                              low: forecast.confidence_range_low,
                              high: forecast.confidence_range_high,
                            })}
                          </p>
                        )}
                        {forecast.notes && (
                          <p className="mt-1 italic text-content-tertiary">{forecast.notes}</p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
        title={t('full_evm.delete_title', { defaultValue: 'Delete this baseline?' })}
        message={t('full_evm.delete_message', {
          defaultValue:
            'Every measurement taken against it goes too, and with them the record of what this project was measured against.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        variant="danger"
      />
    </div>
  );
}
