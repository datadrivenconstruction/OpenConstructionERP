// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Estimate Copilot — a single guided path from a rough conceptual number to a
// defensible, documented estimate. It sequences four capabilities the platform
// already exposes (conceptual estimate, scope coverage, quality audit, basis of
// estimate) into one obvious flow, showing each result and letting the
// estimator confirm before moving on. Pure frontend orchestration: every step
// is an existing HTTP endpoint, human-confirmed, nothing auto-applied.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  FileText,
  Gauge,
  Lock,
  Play,
  RotateCcw,
  Sparkles,
} from 'lucide-react';

import {
  AIDisclaimerBanner,
  BOQPicker,
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
} from '@/shared/ui';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { HistoricalCostPerArea } from '@/features/analytics/HistoricalRange';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import {
  COPILOT_STEPS,
  COPILOT_STEP_COUNT,
  type CopilotStepId,
  type FlowReadiness,
  type StepPhase,
  type StepReadiness,
} from './steps';
import {
  useCopilotFlow,
  type BasisOfEstimateResult,
  type ConceptualEstimateResult,
  type CopilotStepView,
  type QualityAuditResult,
  type ScopeCoverageResult,
} from './useCopilotFlow';
import { fmtList } from '@/shared/lib/formatters';

/** Icon per step, keyed by id so the rail reads at a glance. */
const STEP_ICON: Record<CopilotStepId, React.ReactNode> = {
  conceptual: <Sparkles size={16} strokeWidth={1.8} />,
  scope: <ClipboardCheck size={16} strokeWidth={1.8} />,
  audit: <Gauge size={16} strokeWidth={1.8} />,
  basis: <FileText size={16} strokeWidth={1.8} />,
};

/** Shared field styling for the conceptual step's ROM inputs (mirrors the ROM page). */
const ROM_INPUT_CLASS =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary ' +
  'placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue ' +
  'disabled:cursor-not-allowed disabled:opacity-60';

export function EstimateCopilotPage() {
  const { t } = useTranslation();

  const ctxProjectId = useProjectContextStore((s) => s.activeProjectId);
  const ctxBoqId = useProjectContextStore((s) => s.activeBOQId);
  const setActiveBOQ = useProjectContextStore((s) => s.setActiveBOQ);

  const [projectId, setProjectId] = useState<string | null>(ctxProjectId);
  const [boqId, setBoqId] = useState<string | null>(ctxBoqId);

  const inputsReady = Boolean(projectId && boqId);

  return (
    <div className="space-y-5">
      <PageHeader
        subtitle={t('copilot.subtitle', {
          defaultValue:
            'One guided path from a first-pass number to a documented estimate: conceptual estimate, scope coverage, quality audit, then the basis of estimate.',
        })}
      />

      <AIDisclaimerBanner variant="compact" />

      <Card padding="md" className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-content-primary">
            {t('copilot.pick_title', { defaultValue: 'Choose what to work on' })}
          </h2>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {t('copilot.pick_desc', {
              defaultValue:
                'Pick the project and bill of quantities the copilot should walk through.',
            })}
          </p>
        </div>
        <BOQPicker
          projectId={projectId}
          selectedBoqId={boqId}
          onSelectProject={(id) => {
            setProjectId(id);
            setBoqId(null);
          }}
          onSelectBoq={(id) => {
            setBoqId(id);
            setActiveBOQ(id);
          }}
        />
      </Card>

      {inputsReady && projectId && boqId ? (
        // Remount the flow when the selection changes so step state resets
        // cleanly instead of carrying a stale confirm count into a new BOQ.
        <CopilotFlowPanel key={`${projectId}:${boqId}`} projectId={projectId} boqId={boqId} />
      ) : (
        <EmptyState
          icon={<Sparkles size={22} strokeWidth={1.6} />}
          title={t('copilot.empty_title', { defaultValue: 'Select a bill of quantities to begin' })}
          description={t('copilot.empty_desc', {
            defaultValue:
              'The copilot runs against one estimate at a time. Choose a project and BOQ above to start the guided flow.',
          })}
        />
      )}
    </div>
  );
}

// ── Flow panel ───────────────────────────────────────────────────────────────

interface CopilotFlowPanelProps {
  projectId: string;
  boqId: string;
}

function CopilotFlowPanel({ projectId, boqId }: CopilotFlowPanelProps) {
  const { t } = useTranslation();
  const flow = useCopilotFlow({ projectId, boqId });

  return (
    <div className="space-y-4">
      <ReadinessSummary readiness={flow.readiness} progress={flow.progress} />

      <ol className="space-y-3">
        {flow.steps.map((step) => (
          <li key={step.def.id}>
            <StepCard
              step={step}
              flow={flow}
            />
          </li>
        ))}
      </ol>

      {flow.isComplete && (
        <Card
          padding="md"
          className="border-semantic-success/40 bg-semantic-success/5 flex flex-wrap items-center justify-between gap-3"
        >
          <div className="flex items-start gap-2">
            <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-semantic-success" />
            <div>
              <p className="text-sm font-semibold text-content-primary">
                {t('copilot.done_title', { defaultValue: 'Estimate is ready to defend' })}
              </p>
              <p className="text-xs text-content-tertiary">
                {t('copilot.done_desc', {
                  defaultValue:
                    'You confirmed a conceptual number, scope coverage, a quality audit and the basis of estimate. Review or export from each module as needed.',
                })}
              </p>
            </div>
          </div>
          <Button variant="secondary" size="sm" icon={<RotateCcw size={14} />} onClick={flow.reset}>
            {t('copilot.start_over', { defaultValue: 'Start over' })}
          </Button>
        </Card>
      )}
    </div>
  );
}

// ── Readiness summary ────────────────────────────────────────────────────────

/**
 * At-a-glance panel: a progress bar, a per-step checklist of what is done, and a
 * clear "review-ready" state once every step has been run and confirmed. The
 * per-step "done" markers are driven by the confirmed count, so they survive a
 * reload exactly as the persisted flow state does.
 */
function ReadinessSummary({
  readiness,
  progress,
}: {
  readiness: FlowReadiness;
  progress: number;
}) {
  const { t } = useTranslation();
  const { reviewReady, confirmedCount, total, steps } = readiness;
  return (
    <Card
      padding="md"
      className={
        reviewReady
          ? 'space-y-3 border-semantic-success/40 bg-semantic-success/5'
          : 'space-y-3'
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          {reviewReady ? (
            <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-semantic-success" />
          ) : (
            <Gauge size={18} className="mt-0.5 shrink-0 text-oe-blue" />
          )}
          <div>
            <p className="text-sm font-semibold text-content-primary">
              {reviewReady
                ? t('copilot.readiness.ready_title', { defaultValue: 'Estimate is review-ready' })
                : t('copilot.readiness.title', { defaultValue: 'Estimate readiness' })}
            </p>
            <p className="text-xs text-content-tertiary">
              {reviewReady
                ? t('copilot.readiness.ready_desc', {
                    defaultValue:
                      'All four checks have been run and confirmed. The estimate is ready to review and defend.',
                  })
                : t('copilot.readiness.subtitle', {
                    defaultValue:
                      'Run and confirm each check to make the estimate ready to review.',
                  })}
            </p>
          </div>
        </div>
        <span className="tabular-nums text-xs font-medium text-content-secondary">
          {t('copilot.readiness.count', {
            defaultValue: '{{done}} of {{total}} confirmed',
            done: confirmedCount,
            total,
          })}
        </span>
      </div>

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary"
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={
            reviewReady
              ? 'h-full rounded-full bg-semantic-success transition-all duration-300'
              : 'h-full rounded-full bg-oe-blue transition-all duration-300'
          }
          style={{ width: `${progress}%` }}
        />
      </div>

      <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {steps.map((step) => (
          <ReadinessRow key={step.id} step={step} />
        ))}
      </ul>
    </Card>
  );
}

function ReadinessRow({ step }: { step: StepReadiness }) {
  const { t } = useTranslation();
  const def = COPILOT_STEPS.find((d) => d.id === step.id);
  if (!def) return null;
  return (
    <li className="flex items-center gap-2 text-xs">
      <ReadinessMarker step={step} />
      <span
        className={
          step.confirmed
            ? 'text-content-secondary'
            : step.phase === 'active'
              ? 'font-medium text-content-primary'
              : 'text-content-tertiary'
        }
      >
        {t(def.titleKey, { defaultValue: def.titleFallback })}
      </span>
      {!step.confirmed && step.hasResult && (
        <Badge variant="blue" size="sm">
          {t('copilot.readiness.ready_to_confirm', { defaultValue: 'Ready to confirm' })}
        </Badge>
      )}
    </li>
  );
}

function ReadinessMarker({ step }: { step: StepReadiness }) {
  if (step.confirmed) {
    return <CheckCircle2 size={15} className="shrink-0 text-semantic-success" />;
  }
  if (step.phase === 'active') {
    return <CircleDot size={15} className="shrink-0 text-oe-blue" />;
  }
  return <Lock size={13} strokeWidth={1.8} className="shrink-0 text-content-tertiary" />;
}

// ── Step card ────────────────────────────────────────────────────────────────

const PHASE_BADGE: Record<StepPhase, { key: string; fallback: string; tone: 'neutral' | 'blue' | 'success' }> = {
  locked: { key: 'copilot.phase.locked', fallback: 'Locked', tone: 'neutral' },
  active: { key: 'copilot.phase.active', fallback: 'In progress', tone: 'blue' },
  confirmed: { key: 'copilot.phase.confirmed', fallback: 'Confirmed', tone: 'success' },
};

function StepCard({
  step,
  flow,
}: {
  step: CopilotStepView;
  flow: ReturnType<typeof useCopilotFlow>;
}) {
  const { t } = useTranslation();
  const { def, phase } = step;
  const isLast = def.order === COPILOT_STEP_COUNT - 1;
  const badge = PHASE_BADGE[phase];

  return (
    <Card
      padding="md"
      className={
        phase === 'active'
          ? 'border-oe-blue/40 ring-1 ring-oe-blue/20'
          : phase === 'locked'
            ? 'opacity-70'
            : undefined
      }
    >
      <div className="flex items-start gap-3">
        <StepMarker order={def.order} phase={phase} icon={STEP_ICON[def.id]} />

        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-content-primary">
              {t(def.titleKey, { defaultValue: def.titleFallback })}
            </h3>
            <Badge variant={badge.tone} size="sm">
              {t(badge.key, { defaultValue: badge.fallback })}
            </Badge>
          </div>
          <p className="text-xs text-content-tertiary">
            {t(def.descKey, { defaultValue: def.descFallback })}
          </p>

          {phase === 'locked' && (
            <p className="text-xs text-content-tertiary">
              {t('copilot.locked_hint', {
                defaultValue: 'Confirm the previous step to unlock this one.',
              })}
            </p>
          )}

          {phase === 'active' && <ActiveStepBody step={step} flow={flow} isLast={isLast} />}

          {phase === 'confirmed' && (
            <div className="space-y-2">
              <ResultView id={def.id} flow={flow} compact />
              <Button
                variant="ghost"
                size="sm"
                icon={<RotateCcw size={13} />}
                onClick={() => flow.revisit(def.id)}
              >
                {t('copilot.redo', { defaultValue: 'Redo this step' })}
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

function StepMarker({
  order,
  phase,
  icon,
}: {
  order: number;
  phase: StepPhase;
  icon: React.ReactNode;
}) {
  const base =
    'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold';
  if (phase === 'confirmed') {
    return (
      <div className={`${base} bg-semantic-success/15 text-semantic-success`}>
        <CheckCircle2 size={18} />
      </div>
    );
  }
  if (phase === 'locked') {
    return (
      <div className={`${base} bg-surface-tertiary text-content-tertiary`}>
        <Lock size={14} strokeWidth={1.8} />
      </div>
    );
  }
  return (
    <div className={`${base} bg-oe-blue/15 text-oe-blue`}>
      <span className="sr-only">{order + 1}</span>
      {icon}
    </div>
  );
}

function ActiveStepBody({
  step,
  flow,
  isLast,
}: {
  step: CopilotStepView;
  flow: ReturnType<typeof useCopilotFlow>;
  isLast: boolean;
}) {
  const { t } = useTranslation();
  const { def, isRunning, error, hasResult, canRun, canConfirm } = step;
  const isConceptual = def.id === 'conceptual';

  return (
    <div className="space-y-3">
      {isConceptual && <ConceptualInputFields flow={flow} disabled={isRunning} />}

      {hasResult && <ResultView id={def.id} flow={flow} />}

      {error && !isRunning && (
        <div className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-xs text-semantic-error">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">
              {t('copilot.step_failed', { defaultValue: 'This step could not complete' })}
            </p>
            <p className="mt-0.5 break-words opacity-90">{error.message}</p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {!hasResult ? (
          <Button
            variant="primary"
            size="sm"
            loading={isRunning}
            disabled={!canRun}
            icon={<Play size={14} />}
            onClick={() => flow.run(def.id)}
          >
            {isRunning
              ? t('copilot.running', { defaultValue: 'Working…' })
              : error
                ? t('copilot.retry', { defaultValue: 'Try again' })
                : t(def.ctaKey, { defaultValue: def.ctaFallback })}
          </Button>
        ) : (
          <>
            <Button
              variant="primary"
              size="sm"
              disabled={!canConfirm}
              icon={<CheckCircle2 size={14} />}
              onClick={() => flow.confirm(def.id)}
            >
              {isLast
                ? t('copilot.confirm_finish', { defaultValue: 'Confirm and finish' })
                : t('copilot.confirm_continue', { defaultValue: 'Confirm and continue' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              loading={isRunning}
              icon={<RotateCcw size={13} />}
              onClick={() => flow.run(def.id)}
            >
              {t('copilot.rerun', { defaultValue: 'Re-run' })}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Conceptual step inputs ───────────────────────────────────────────────────

/**
 * Inputs for the conceptual step: the four values the ROM calculator needs.
 * Building type and area gate the run; quality and region default from the
 * reference table. Rendered only inside the conceptual step's active body.
 */
function ConceptualInputFields({
  flow,
  disabled,
}: {
  flow: ReturnType<typeof useCopilotFlow>;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const { reference, conceptualInputs, setConceptualInput } = flow;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div>
        <label
          htmlFor="copilot-rom-type"
          className="mb-1 block text-xs font-medium text-content-secondary"
        >
          {t('copilot.conceptual.building_type', { defaultValue: 'Building type' })}
        </label>
        <select
          id="copilot-rom-type"
          value={conceptualInputs.buildingType}
          disabled={disabled}
          onChange={(e) => setConceptualInput({ buildingType: e.target.value })}
          className={ROM_INPUT_CLASS}
        >
          <option value="">
            {t('copilot.conceptual.building_type_placeholder', {
              defaultValue: 'Select a building type…',
            })}
          </option>
          {(reference?.building_types ?? []).map((opt) => (
            <option key={opt.key} value={opt.key}>
              {t(`romEstimate.type_${opt.key}`, { defaultValue: opt.label })}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label
          htmlFor="copilot-rom-area"
          className="mb-1 block text-xs font-medium text-content-secondary"
        >
          {t('copilot.conceptual.gross_floor_area', { defaultValue: 'Gross floor area (m²)' })}
        </label>
        <input
          id="copilot-rom-area"
          type="number"
          min={1}
          step="any"
          value={conceptualInputs.grossFloorArea}
          disabled={disabled}
          onChange={(e) => setConceptualInput({ grossFloorArea: e.target.value })}
          placeholder={t('copilot.conceptual.area_placeholder', { defaultValue: 'e.g. 1200' })}
          className={`${ROM_INPUT_CLASS} tabular-nums`}
        />
      </div>

      <div>
        <label
          htmlFor="copilot-rom-quality"
          className="mb-1 block text-xs font-medium text-content-secondary"
        >
          {t('copilot.conceptual.quality', { defaultValue: 'Quality level' })}
        </label>
        <select
          id="copilot-rom-quality"
          value={conceptualInputs.quality}
          disabled={disabled}
          onChange={(e) => setConceptualInput({ quality: e.target.value })}
          className={ROM_INPUT_CLASS}
        >
          {(reference?.quality_levels ?? []).map((opt) => (
            <option key={opt.key} value={opt.key}>
              {t(`romEstimate.quality_${opt.key}`, { defaultValue: opt.label })}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label
          htmlFor="copilot-rom-region"
          className="mb-1 block text-xs font-medium text-content-secondary"
        >
          {t('copilot.conceptual.region', { defaultValue: 'Region' })}
        </label>
        <select
          id="copilot-rom-region"
          value={conceptualInputs.region}
          disabled={disabled}
          onChange={(e) => setConceptualInput({ region: e.target.value })}
          className={ROM_INPUT_CLASS}
        >
          {(reference?.regions ?? []).map((opt) => (
            <option key={opt.key} value={opt.key}>
              {t(`romEstimate.region_${opt.key}`, { defaultValue: opt.label })}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

// ── Per-step result views ────────────────────────────────────────────────────

function ResultView({
  id,
  flow,
  compact = false,
}: {
  id: CopilotStepId;
  flow: ReturnType<typeof useCopilotFlow>;
  compact?: boolean;
}) {
  if (id === 'conceptual') return <ConceptualResult data={flow.conceptual} compact={compact} />;
  if (id === 'scope') return <ScopeResult data={flow.scope} compact={compact} />;
  if (id === 'audit') return <AuditResult data={flow.audit} compact={compact} />;
  return <BasisResult data={flow.basis} compact={compact} />;
}

function ResultShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface-secondary/50 px-3 py-2.5 text-xs">
      {children}
    </div>
  );
}

function ConceptualResult({
  data,
  compact,
}: {
  data: ConceptualEstimateResult | undefined;
  compact: boolean;
}) {
  const { t } = useTranslation();
  if (!data) return null;
  const currency = data.currency || undefined;
  const { accuracy } = data;
  const low = formatCurrency(accuracy.low_amount, currency, undefined, { maximumFractionDigits: 0 });
  const high = formatCurrency(accuracy.high_amount, currency, undefined, {
    maximumFractionDigits: 0,
  });
  return (
    <ResultShell>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-content-tertiary">
          {t('copilot.conceptual.headline', { defaultValue: 'First-pass total' })}
        </span>
        <span className="text-base font-semibold tabular-nums text-content-primary">
          {formatCurrency(data.total, currency, undefined, { maximumFractionDigits: 0 })}
        </span>
        {accuracy.estimate_class_label && (
          <Badge variant="neutral" size="sm">
            {accuracy.estimate_class_label}
          </Badge>
        )}
      </div>
      {!compact && (
        <p className="mt-1.5 tabular-nums text-content-secondary">
          {t('copilot.conceptual.range', {
            defaultValue: 'Likely range {{low}} to {{high}}',
            low,
            high,
          })}
        </p>
      )}
      {!compact && data.cost_per_m2 && (
        <p className="mt-1 text-content-tertiary">
          {t('copilot.conceptual.per_m2', {
            defaultValue: '{{rate}} per m²',
            rate: formatCurrency(data.cost_per_m2, currency),
          })}
        </p>
      )}
      {!compact && accuracy.note && <p className="mt-1 text-content-tertiary">{accuracy.note}</p>}
      {/* Outturn history from your own completed projects, apart from the class range above. */}
      {!compact && data.cost_per_m2 && data.currency && (
        <div className="mt-2">
          <HistoricalCostPerArea costPerArea={toNum(data.cost_per_m2)} currency={data.currency} />
        </div>
      )}
    </ResultShell>
  );
}

function ScopeResult({ data, compact }: { data: ScopeCoverageResult | undefined; compact: boolean }) {
  const { t } = useTranslation();
  const pct = useMemo(() => Math.round(toNum(data?.completeness_score) * 100), [data]);
  if (!data) return null;
  const missing = data.missing_items ?? [];
  const top = missing.slice(0, compact ? 0 : 4);
  return (
    <ResultShell>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-content-tertiary">
          {t('copilot.scope.coverage', { defaultValue: 'Scope coverage' })}
        </span>
        <span className="text-base font-semibold tabular-nums text-content-primary">{pct}%</span>
        <Badge variant={missing.length === 0 ? 'success' : 'warning'} size="sm">
          {t('copilot.scope.missing_count', {
            defaultValue: '{{count}} gaps',
            count: missing.length,
          })}
        </Badge>
      </div>
      {top.length > 0 && (
        <ul className="mt-2 space-y-1">
          {top.map((m, i) => (
            <li key={`${m.description}-${i}`} className="flex items-start gap-2 text-content-secondary">
              <span
                className={
                  m.priority === 'high'
                    ? 'mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-semantic-error'
                    : m.priority === 'medium'
                      ? 'mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-semantic-warning'
                      : 'mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-content-tertiary'
                }
              />
              <span className="min-w-0">{m.description}</span>
            </li>
          ))}
          {missing.length > top.length && (
            <li className="text-content-tertiary">
              {t('copilot.scope.more', {
                defaultValue: '+{{count}} more',
                count: missing.length - top.length,
              })}
            </li>
          )}
        </ul>
      )}
    </ResultShell>
  );
}

const AUDIT_TONE: Record<QualityAuditResult['status'], 'success' | 'warning' | 'error' | 'neutral'> = {
  passed: 'success',
  warnings: 'warning',
  errors: 'error',
  skipped: 'neutral',
};

function AuditResult({ data, compact }: { data: QualityAuditResult | undefined; compact: boolean }) {
  const { t } = useTranslation();
  const pct = useMemo(() => Math.round(toNum(data?.score) * 100), [data]);
  if (!data) return null;
  const statusLabel = t(`copilot.audit.status.${data.status}`, {
    defaultValue:
      data.status === 'passed'
        ? 'Passed'
        : data.status === 'warnings'
          ? 'Warnings'
          : data.status === 'errors'
            ? 'Errors'
            : 'Skipped',
  });
  return (
    <ResultShell>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Badge variant={AUDIT_TONE[data.status]} size="sm">
          {statusLabel}
        </Badge>
        <span className="text-content-tertiary">
          {t('copilot.audit.score', { defaultValue: 'Quality score' })}
        </span>
        <span className="text-base font-semibold tabular-nums text-content-primary">{pct}%</span>
      </div>
      {!compact && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-content-secondary">
          <span>
            {t('copilot.audit.errors', { defaultValue: 'Errors: {{n}}', n: data.error_count })}
          </span>
          <span>
            {t('copilot.audit.warnings', {
              defaultValue: 'Warnings: {{n}}',
              n: data.warning_count,
            })}
          </span>
          <span>
            {t('copilot.audit.passed', { defaultValue: 'Passed: {{n}}', n: data.passed_count })}
          </span>
        </div>
      )}
      {!compact && data.unsupported_rule_sets && data.unsupported_rule_sets.length > 0 && (
        <p className="mt-1.5 text-content-tertiary">
          {t('copilot.audit.unsupported', {
            defaultValue: 'Not run (unavailable rules): {{sets}}',
            sets: fmtList(data.unsupported_rule_sets),
          })}
        </p>
      )}
    </ResultShell>
  );
}

function BasisResult({ data, compact }: { data: BasisOfEstimateResult | undefined; compact: boolean }) {
  const { t } = useTranslation();
  if (!data) return null;
  const sections = data.sections ?? [];
  return (
    <ResultShell>
      <div className="flex items-center gap-2 text-content-tertiary">
        <FileText size={13} className="shrink-0" />
        <span>{t('copilot.basis.ready', { defaultValue: 'Basis of estimate drafted' })}</span>
      </div>
      {!compact && data.narrative && (
        <p className="mt-1.5 whitespace-pre-wrap text-content-secondary">{data.narrative}</p>
      )}
      {!compact && sections.length > 0 && (
        <div className="mt-2 space-y-2">
          {sections.map((s, i) => (
            <div key={`${s.title}-${i}`}>
              <p className="font-medium text-content-primary">{s.title}</p>
              <p className="whitespace-pre-wrap text-content-secondary">{s.body}</p>
            </div>
          ))}
        </div>
      )}
    </ResultShell>
  );
}
