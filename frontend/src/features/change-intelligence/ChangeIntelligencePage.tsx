// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Change Intelligence - one read surface over the change-adjacent modules.
// Six co-pilots, each a tab: what to act on first (coordination), waiting on
// whom (cycle time), who owes the next reply (correspondence digest), what the
// approved changes have committed (impact), what we mean to recover from others
// (cost recovery) and a stateless drafting helper (clarifier). Every panel is a
// thin view over its endpoint; money arrives as a string and is handed to
// MoneyDisplay untouched.

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  BrainCircuit,
  ListChecks,
  Clock,
  Mail,
  TrendingUp,
  Wallet,
  Sparkles,
  AlertTriangle,
  ArrowRight,
  Users,
  Inbox,
  Scale,
  GitCompareArrows,
  Radar,
  ShieldAlert,
  Import,
  Gauge,
  FileSearch,
  AlarmClock,
  Plus,
  Pencil,
  Trash2,
  SplitSquareHorizontal,
  ClipboardList,
  BarChart3,
  LineChart,
} from 'lucide-react';
import {
  Card,
  Badge,
  EmptyState,
  SkeletonTable,
  DismissibleInfo,
  TabBar,
  tabIds,
  WideModal,
  WideModalSection,
  WideModalField,
  ModuleGuideButton,
} from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  ProvabilityGauge,
  EvidenceThreadPanel,
  reconstructTypeForKind,
  type SubjectKind,
} from '@/features/claims-evidence';
import {
  getCoordinationPlan,
  getCycleTimeBoard,
  getCommsDigest,
  getImpactProjection,
  getRecoveryLedger,
  listBackCharges,
  getRecoveryPerformance,
  getBackChargeApportionment,
  apportionBackCharge,
  createBackCharge,
  updateBackCharge,
  clarifyChangeNote,
  getDisputeRiskBoard,
  getDecisionImpact,
  getChangeWatch,
  getIntakeProfiles,
  previewIntake,
  getDelayRiskBoard,
  getScopeAmbiguity,
  getNoticeRegister,
  getCommitmentRegister,
  getChangeDrivers,
  getChangeRunRate,
  type Urgency,
  type Awaiting,
  type BackCharge,
  type BackChargeApportionment,
  type BackChargeUpdateBody,
  type ClarifiedRequest,
  type ExposureBand,
  type WatchClass,
  type DelayBand,
  type ScopeBand,
  type IntakePreview,
  type NoticeClock,
  type NoticeStatus,
  type ParetoRow,
} from './api';
import { changeIntelligenceGuide } from './change_intelligenceGuide';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';
import { parseDecimalInput, toDecimalPayloadString } from '@/shared/lib/parseDecimal';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

interface ProjectLite {
  id: string;
  name?: string;
}

type Tab =
  | 'coordination'
  | 'cycle'
  | 'commitments'
  | 'comms'
  | 'impact'
  | 'drivers'
  | 'runrate'
  | 'recovery'
  | 'dispute'
  | 'decision'
  | 'watch'
  | 'clarifier'
  | 'intake'
  | 'delay'
  | 'scope'
  | 'notice';

const URGENCY_VARIANT: Record<Urgency, BadgeVariant> = {
  overdue: 'error',
  due_soon: 'warning',
  upcoming: 'blue',
  no_date: 'neutral',
};

const AWAITING_VARIANT: Record<Awaiting, BadgeVariant> = {
  us: 'warning',
  them: 'blue',
  none: 'neutral',
};

const EXPOSURE_VARIANT: Record<ExposureBand, BadgeVariant> = {
  high: 'error',
  elevated: 'warning',
  low: 'neutral',
};

const WATCH_VARIANT: Record<WatchClass, BadgeVariant> = {
  lost: 'error',
  stalled: 'warning',
  incomplete: 'blue',
  ok: 'success',
};

/**
 * Badge variant for a clarification-gap severity. The engine emits
 * 'required' / 'recommended' (not 'high' / 'medium'); map them to the
 * error / warning traffic-light, everything else neutral.
 */
function severityVariant(severity: string): BadgeVariant {
  if (severity === 'required') return 'error';
  if (severity === 'recommended') return 'warning';
  return 'neutral';
}

/** Best-effort title-case of an engine token like "due_soon" or "change_order". */
function humanize(token: string): string {
  return (token || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

function dateOnly(value: string | null | undefined): string {
  if (!value) return '-';
  return String(value).slice(0, 10);
}

/**
 * Render a recovery rate (a fraction string in [0, 1], or null) as a percent.
 * The rate is a pure ratio, not money, so Number() is safe here; null means the
 * cohort had no chargeable amount (an undefined ratio) and shows as a dash.
 */
function ratePercent(rate: string | null | undefined): string {
  if (rate === null || rate === undefined || rate === '') return '-';
  const n = Number(rate);
  if (!Number.isFinite(n)) return '-';
  return `${Math.round(n * 100)}%`;
}

/**
 * Render a 0-100 percentage number (the Pareto cost_pct / cumulative_pct, a pure
 * ratio) as a compact percent string, or a dash when it is not a finite number.
 */
function pctNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  return fmtPercent(value);
}

/**
 * Render a percentage carried as a string (already 0-100, e.g. "12.50", from the
 * run-rate curve and forecast) as a compact percent. The value is a ratio, not
 * money, so Number() is safe here; null means there was no usable contract value
 * to divide by, and shows as a dash.
 */
function pctString(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-';
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return fmtPercent(n);
}

/** Badge variant for a HIGH/LOW traceability cohort label. */
function cohortVariant(cohort: string): BadgeVariant {
  if (cohort === 'high' || cohort === 'strong') return 'success';
  if (cohort === 'moderate') return 'warning';
  return 'neutral';
}

// --- Small shared layout helpers -------------------------------------------

function StatTile({ label, value, tone }: { label: string; value: React.ReactNode; tone?: BadgeVariant }) {
  const toneClass =
    tone === 'error'
      ? 'text-semantic-error'
      : tone === 'warning'
        ? 'text-semantic-warning'
        : tone === 'success'
          ? 'text-semantic-success'
          : 'text-content-primary';
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </Card>
  );
}

function PanelState({
  loading,
  error,
  empty,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  children,
}: {
  loading: boolean;
  error: unknown;
  empty: boolean;
  emptyIcon: React.ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  children: React.ReactNode;
}) {
  if (loading) return <SkeletonTable />;
  if (error) {
    return (
      <Card className="p-4">
        <div className="flex items-center gap-2 text-sm text-semantic-error">
          <AlertTriangle className="h-4 w-4" />
          <span>{getErrorMessage(error)}</span>
        </div>
      </Card>
    );
  }
  if (empty) return <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />;
  return <>{children}</>;
}

// --- Tab: coordination ("what to act on first") ----------------------------

function CoordinationTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'coordination', projectId],
    queryFn: () => getCoordinationPlan(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const plan = q.data;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.coordination.tile.open_items', { defaultValue: 'Open items' })}
          value={plan?.total ?? 0}
        />
        <StatTile
          label={t('change_intelligence.coordination.tile.overdue', { defaultValue: 'Overdue' })}
          value={plan?.overdue_count ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.coordination.tile.due_soon', { defaultValue: 'Due soon' })}
          value={plan?.due_soon_count ?? 0}
          tone="warning"
        />
      </div>
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!plan || plan.steps.length === 0}
        emptyIcon={<ListChecks className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.coordination.empty_title', { defaultValue: 'Nothing waiting' })}
        emptyDescription={t('change_intelligence.coordination.empty_desc', {
          defaultValue: 'No open change items need an action right now.',
        })}
      >
        <div className="space-y-2">
          {plan?.steps.map((s) => (
            <Card key={s.ref_id} className="p-3">
              <div className="flex flex-wrap items-center gap-2">
                {/* Urgency / kind / action / reason arrive as stable engine
                    tokens (the reason 1:1 per urgency), so each is translated
                    by token with the wire text as the unknown-token fallback. */}
                <Badge variant={URGENCY_VARIANT[s.urgency]}>
                  {t(`change_intelligence.coordination.urgency.${s.urgency}`, { defaultValue: humanize(s.urgency) })}
                </Badge>
                <span className="text-xs text-content-tertiary">
                  {t(`claims_evidence.kind.${s.kind}`, { defaultValue: humanize(s.kind) })}
                </span>
                <span className="font-medium text-content-primary">
                  {s.title || t('change_intelligence.common.untitled', { defaultValue: '(untitled)' })}
                </span>
                <span className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-oe-blue">
                  {t(`change_intelligence.coordination.action.${s.recommended_action}`, {
                    defaultValue: humanize(s.recommended_action),
                  })}
                  <ArrowRight className="h-3.5 w-3.5" />
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-content-secondary">
                <span>
                  {t('change_intelligence.coordination.ball_in_court', { defaultValue: 'Ball in court:' })}{' '}
                  <span className="font-medium">
                    {s.ball_in_court === 'unassigned'
                      ? t('change_intelligence.coordination.unassigned', { defaultValue: 'Unassigned' })
                      : s.ball_in_court}
                  </span>
                </span>
                {s.days_to_due != null && (
                  <span>
                    {s.days_to_due < 0
                      ? t('change_intelligence.coordination.days_overdue', {
                          defaultValue: '{{days}}d overdue',
                          days: Math.abs(s.days_to_due),
                        })
                      : t('change_intelligence.coordination.days_to_due', {
                          defaultValue: '{{days}}d to due',
                          days: s.days_to_due,
                        })}
                  </span>
                )}
                <span className="text-content-tertiary">
                  {t(`change_intelligence.coordination.reason.${s.urgency}`, { defaultValue: s.reason })}
                </span>
              </div>
            </Card>
          ))}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: cycle time ("waiting on whom") -----------------------------------

function CycleTimeTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'cycle-time', projectId],
    queryFn: () => getCycleTimeBoard(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const board = q.data;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.cycle.tile.open', { defaultValue: 'Open' })}
          value={board?.total_open ?? 0}
        />
        <StatTile
          label={t('change_intelligence.cycle.tile.overdue', { defaultValue: 'Overdue' })}
          value={board?.total_overdue ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.cycle.tile.unassigned', { defaultValue: 'Unassigned' })}
          value={board?.unassigned_open ?? 0}
          tone="warning"
        />
      </div>
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!board || board.parties.length === 0}
        emptyIcon={<Users className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.cycle.empty_title', { defaultValue: 'No open changes' })}
        emptyDescription={t('change_intelligence.cycle.empty_desc', {
          defaultValue: 'There are no open change records to age right now.',
        })}
      >
        <Card className="overflow-hidden p-0">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-3 py-2">
                  {t('change_intelligence.cycle.col.party', { defaultValue: 'Party (ball in court)' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.cycle.col.open', { defaultValue: 'Open' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.cycle.col.overdue', { defaultValue: 'Overdue' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.cycle.col.avg_age', { defaultValue: 'Avg age (d)' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.cycle.col.oldest', { defaultValue: 'Oldest (d)' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {board?.parties.map((p) => (
                <tr key={p.party} className="border-t border-border-light">
                  <td className="px-3 py-2 font-medium text-content-primary">{p.party}</td>
                  <td className="px-3 py-2 text-right">{p.open_count}</td>
                  <td className="px-3 py-2 text-right text-semantic-error">{p.overdue_count || ''}</td>
                  <td className="px-3 py-2 text-right">{fmtFixed(p.avg_age_days, 1)}</td>
                  <td className="px-3 py-2 text-right">{fmtFixed(p.oldest_age_days, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </PanelState>
    </div>
  );
}

// --- Tab: correspondence digest --------------------------------------------

function CommsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'comms-digest', projectId],
    queryFn: () => getCommsDigest(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const digest = q.data;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.comms.tile.threads', { defaultValue: 'Threads' })}
          value={digest?.thread_count ?? 0}
        />
        <StatTile
          label={t('change_intelligence.comms.tile.open', { defaultValue: 'Open' })}
          value={digest?.open_count ?? 0}
        />
        <StatTile
          label={t('change_intelligence.comms.tile.awaiting_us', { defaultValue: 'Awaiting us' })}
          value={digest?.awaiting_us_count ?? 0}
          tone="warning"
        />
      </div>
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!digest || digest.threads.length === 0}
        emptyIcon={<Mail className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.comms.empty_title', { defaultValue: 'No correspondence' })}
        emptyDescription={t('change_intelligence.comms.empty_desc', {
          defaultValue: 'No letters or emails have been recorded for this project yet.',
        })}
      >
        <div className="space-y-2">
          {digest?.threads.map((th) => (
            <Card key={th.thread_key || th.subject} className="p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={AWAITING_VARIANT[th.awaiting]}>
                  {th.awaiting === 'none'
                    ? t('change_intelligence.comms.closed', { defaultValue: 'Closed' })
                    : t('change_intelligence.comms.awaiting', {
                        defaultValue: 'Awaiting {{party}}',
                        party: th.awaiting,
                      })}
                </Badge>
                <span className="font-medium text-content-primary">
                  {th.subject || t('change_intelligence.comms.no_subject', { defaultValue: '(no subject)' })}
                </span>
                <span className="ml-auto text-xs text-content-tertiary">
                  {t('change_intelligence.comms.msg_count', {
                    defaultValue: '{{count}} msg',
                    count: th.message_count,
                  })}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-4 text-sm text-content-secondary">
                <span>
                  {t('change_intelligence.comms.last', { defaultValue: 'Last:' })} {dateOnly(th.last_at)}
                </span>
                <span>
                  {t('change_intelligence.comms.direction_from', {
                    defaultValue: '{{direction}} from {{sender}}',
                    direction: humanize(th.last_direction),
                    sender: th.last_sender || t('change_intelligence.comms.unknown', { defaultValue: 'unknown' }),
                  })}
                </span>
                {th.participants.length > 0 && (
                  <span className="text-content-tertiary">
                    {t('change_intelligence.comms.participants', {
                      defaultValue: '{{count}} participant(s)',
                      count: th.participants.length,
                    })}
                  </span>
                )}
              </div>
            </Card>
          ))}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: impact (committed cost and schedule) -----------------------------

function ImpactTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'impact', projectId],
    queryFn: () => getImpactProjection(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const imp = q.data;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.impact.tile.approved_changes', { defaultValue: 'Approved changes' })}
          value={imp?.approved_count ?? 0}
        />
        <StatTile
          label={t('change_intelligence.impact.tile.committed_cost', { defaultValue: 'Committed cost' })}
          value={<MoneyDisplay amount={imp?.primary_currency_cost ?? '0'} currency={imp?.primary_currency} showCode colorize />}
        />
        <StatTile
          label={t('change_intelligence.impact.tile.schedule_delta', { defaultValue: 'Schedule delta (d)' })}
          value={imp?.total_schedule_delta_days ?? 0}
        />
      </div>
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!imp || imp.by_kind.length === 0}
        emptyIcon={<TrendingUp className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.impact.empty_title', { defaultValue: 'No committed impact' })}
        emptyDescription={t('change_intelligence.impact.empty_desc', {
          defaultValue: 'No approved change orders or agreed variation orders carry cost or schedule yet.',
        })}
      >
        <Card className="overflow-hidden p-0">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-3 py-2">
                  {t('change_intelligence.impact.col.by_kind', { defaultValue: 'By kind' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.impact.col.count', { defaultValue: 'Count' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.impact.col.cost', { defaultValue: 'Cost' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.impact.col.days', { defaultValue: 'Days' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {imp?.by_kind.map((k) => (
                <tr key={k.kind} className="border-t border-border-light">
                  <td className="px-3 py-2 font-medium text-content-primary">{humanize(k.kind)}</td>
                  <td className="px-3 py-2 text-right">{k.count}</td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={k.total_cost} currency={imp?.primary_currency} showCode colorize />
                  </td>
                  <td className="px-3 py-2 text-right">{k.total_days}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        {imp && imp.by_currency.length > 1 && (
          <p className="text-xs text-content-tertiary">
            {t('change_intelligence.impact.multi_currency', {
              defaultValue: 'Costs span {{count}} currencies; the headline uses {{currency}}.',
              count: imp.by_currency.length,
              currency:
                imp.primary_currency ||
                t('change_intelligence.impact.primary_currency_fallback', {
                  defaultValue: 'the primary currency',
                }),
            })}
          </p>
        )}
      </PanelState>
    </div>
  );
}

// --- Tab: cost recovery -----------------------------------------------------

// The commercial states a back-charge can hold (mirrors the backend
// STATUS_* set in back_charge.py). The first three are open; the last two close
// the item. The visible labels are translated at the call site.
const BACK_CHARGE_STATUSES = ['proposed', 'agreed', 'disputed', 'recovered', 'waived'] as const;

// Shared input styling so every field in the back-charge form matches the rest
// of the page's inputs (the decision-impact / clarifier inputs use the same).
const FORM_INPUT_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary p-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

// A money string is valid when blank (treated as 0) or a non-negative number.
// The value is kept and sent as a string (the lossless-Decimal convention);
// the parse is used only to validate, never to round-trip the amount.
// parseDecimalInput, not Number: this is typed by a person, and Number('1,5')
// is NaN, so the old check called a correct German amount invalid.
function isValidMoney(raw: string): boolean {
  const trimmed = raw.trim();
  if (trimmed === '') return true;
  const n = parseDecimalInput(trimmed);
  return n !== null && n >= 0;
}

// A chargeable percent is a number in [0, 100] in the UI; it is converted to a
// [0, 1] fraction string before being sent. Being a ratio rather than money
// does not make Number() safe: the separator is what breaks, and an
// apportionment of 12,5 percent is written that way across most of Europe.
function isValidPercent(raw: string): boolean {
  const trimmed = raw.trim();
  if (trimmed === '') return true;
  const n = parseDecimalInput(trimmed);
  return n !== null && n >= 0 && n <= 100;
}

// Convert a percent string (UI) to a [0, 1] fraction string (wire). Blank means
// "all of it" (1). The result is a plain decimal string for the Decimal field.
// An unparseable entry yields '0' rather than 'NaN', which the server rejects
// with a type error instead of the apportionment message the user needs.
function percentToFraction(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed === '') return '1';
  const n = parseDecimalInput(trimmed);
  return n === null ? '0' : String(n / 100);
}

// Convert a [0, 1] fraction string (wire) back to a whole-number percent string
// (UI) for seeding the edit form. Falls back to 100 on a non-finite input.
function fractionToPercent(raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return '100';
  return String(Math.round(n * 100));
}

/**
 * Create / edit a back-charge. The Recovery tab is otherwise read-only; this is
 * the one write surface for the cost-recovery ledger. Money fields are kept and
 * sent as strings (the lossless-Decimal convention) - never coerced to a number.
 * In edit mode the currency and source reference are fixed (the backend update
 * does not change them) and a recovered-amount field appears so progress can be
 * recorded.
 */
function BackChargeFormModal({
  open,
  onClose,
  projectId,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  editing: BackCharge | null;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = editing !== null;

  const [responsibleParty, setResponsibleParty] = useState('');
  const [description, setDescription] = useState('');
  const [grossAmount, setGrossAmount] = useState('');
  const [chargeablePct, setChargeablePct] = useState('');
  const [recoveredAmount, setRecoveredAmount] = useState('');
  const [currency, setCurrency] = useState('');
  const [basis, setBasis] = useState('');
  const [sourceRef, setSourceRef] = useState('');
  const [status, setStatus] = useState<string>('proposed');

  // Seed the fields from the row being edited (or reset to blanks for a create)
  // each time the modal opens. Keyed on the open flag and the edited id so a
  // re-open always starts from the current server values.
  const editingId = editing?.id ?? '';
  const [seededFor, setSeededFor] = useState<string | null>(null);
  const seedKey = open ? `${isEdit ? editingId : 'new'}` : null;
  if (seedKey !== seededFor) {
    setSeededFor(seedKey);
    if (open) {
      setResponsibleParty(editing?.responsible_party ?? '');
      setDescription(editing?.description ?? '');
      setGrossAmount(editing?.gross_amount ?? '');
      setChargeablePct(editing ? fractionToPercent(editing.chargeable_pct) : '');
      setRecoveredAmount(editing?.recovered_amount ?? '');
      setCurrency(editing?.currency ?? '');
      setBasis(editing?.basis ?? '');
      setSourceRef(editing?.source_ref ?? '');
      setStatus(editing?.status || 'proposed');
    }
  }

  const grossValid = isValidMoney(grossAmount);
  const pctValid = isValidPercent(chargeablePct);
  const recoveredValid = isValidMoney(recoveredAmount);
  const canSubmit = grossValid && pctValid && recoveredValid;

  const statusLabel = (s: string): string =>
    t(`change_intelligence.recovery.status.${s}`, { defaultValue: humanize(s) });

  const mutation = useMutation<BackCharge, unknown, void>({
    mutationFn: () => {
      if (isEdit && editing) {
        // Only what the user actually edited goes back. Correcting a percentage
        // used to rewrite the description and the recovered amount as they
        // stood when this ledger was read, undoing anyone else's edit to them
        // without a word. The update route dumps with `exclude_unset=True`, so
        // a field left out of the body is left alone in the database. Each
        // comparison uses the same expression that seeded the field above, so
        // an untouched field always reads as unchanged.
        const patch: BackChargeUpdateBody = {};
        if (responsibleParty !== (editing.responsible_party ?? '')) {
          patch.responsible_party = responsibleParty.trim();
        }
        if (description !== (editing.description ?? '')) patch.description = description.trim();
        if (basis !== (editing.basis ?? '')) patch.basis = basis.trim();
        if (grossAmount !== (editing.gross_amount ?? '')) {
          patch.gross_amount = toDecimalPayloadString(grossAmount);
        }
        if (chargeablePct !== fractionToPercent(editing.chargeable_pct)) {
          patch.chargeable_pct = percentToFraction(chargeablePct);
        }
        if (status !== (editing.status || 'proposed')) patch.status = status;
        if (recoveredAmount !== (editing.recovered_amount ?? '')) {
          patch.recovered_amount = toDecimalPayloadString(recoveredAmount);
        }
        return updateBackCharge(projectId, editing.id, patch);
      }
      return createBackCharge(projectId, {
        source_ref: sourceRef.trim(),
        responsible_party: responsibleParty.trim(),
        description: description.trim(),
        basis: basis.trim(),
        gross_amount: toDecimalPayloadString(grossAmount),
        chargeable_pct: percentToFraction(chargeablePct),
        currency: currency.trim(),
        status,
      });
    },
    onSuccess: () => {
      // The ledger rollup, the flat back-charge list and the recovery-rate index
      // all derive from these rows; refresh every recovery query for the project.
      void queryClient.invalidateQueries({
        queryKey: ['change-intelligence', 'recovery-ledger', projectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['change-intelligence', 'back-charges', projectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['change-intelligence', 'recovery-performance', projectId],
      });
      addToast({
        type: 'success',
        title: isEdit
          ? t('change_intelligence.recovery.form.updated', { defaultValue: 'Back-charge updated' })
          : t('change_intelligence.recovery.form.created', { defaultValue: 'Back-charge recorded' }),
      });
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: isEdit
          ? t('change_intelligence.recovery.form.update_failed', {
              defaultValue: 'Could not update the back-charge',
            })
          : t('change_intelligence.recovery.form.create_failed', {
              defaultValue: 'Could not record the back-charge',
            }),
        message: getErrorMessage(err),
      });
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={mutation.isPending}
      size="md"
      title={
        isEdit
          ? t('change_intelligence.recovery.form.edit_title', { defaultValue: 'Edit back-charge' })
          : t('change_intelligence.recovery.form.create_title', { defaultValue: 'Record a back-charge' })
      }
      subtitle={t('change_intelligence.recovery.form.subtitle', {
        defaultValue: 'A cost the project means to recover from the party held responsible.',
      })}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={mutation.isPending}
            className="rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            disabled={!canSubmit || mutation.isPending}
            onClick={() => mutation.mutate()}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90 disabled:opacity-40"
          >
            {mutation.isPending
              ? t('common.saving', { defaultValue: 'Saving...' })
              : isEdit
                ? t('change_intelligence.recovery.form.save', { defaultValue: 'Save changes' })
                : t('change_intelligence.recovery.form.submit', { defaultValue: 'Record back-charge' })}
          </button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('change_intelligence.recovery.form.responsible_party', {
            defaultValue: 'Responsible party',
          })}
          htmlFor="bc-party"
          span={2}
        >
          <input
            id="bc-party"
            value={responsibleParty}
            onChange={(e) => setResponsibleParty(e.target.value)}
            placeholder={t('change_intelligence.recovery.form.responsible_party_ph', {
              defaultValue: 'The subcontractor, supplier or party at fault',
            })}
            className={FORM_INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField
          label={t('change_intelligence.recovery.form.description', { defaultValue: 'Description' })}
          htmlFor="bc-description"
          span={2}
        >
          <input
            id="bc-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('change_intelligence.recovery.form.description_ph', {
              defaultValue: 'What the cost is for (e.g. rework after a defect)',
            })}
            className={FORM_INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField
          label={t('change_intelligence.recovery.form.gross_amount', { defaultValue: 'Gross amount' })}
          htmlFor="bc-gross"
          error={
            grossValid
              ? undefined
              : t('change_intelligence.recovery.form.amount_invalid', {
                  defaultValue: 'Enter a non-negative amount.',
                })
          }
          hint={t('change_intelligence.recovery.form.gross_hint', {
            defaultValue: 'The full cost incurred, before the chargeable share.',
          })}
        >
          <input
            id="bc-gross"
            inputMode="decimal"
            value={grossAmount}
            onChange={(e) => setGrossAmount(e.target.value)}
            placeholder="0.00"
            className={FORM_INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField
          label={t('change_intelligence.recovery.form.chargeable_pct', {
            defaultValue: 'Chargeable %',
          })}
          htmlFor="bc-pct"
          error={
            pctValid
              ? undefined
              : t('change_intelligence.recovery.form.pct_invalid', {
                  defaultValue: 'Enter a percent between 0 and 100.',
                })
          }
          hint={t('change_intelligence.recovery.form.pct_hint', {
            defaultValue: 'Share of the gross cost judged recoverable (defaults to 100%).',
          })}
        >
          <input
            id="bc-pct"
            inputMode="decimal"
            value={chargeablePct}
            onChange={(e) => setChargeablePct(e.target.value)}
            placeholder="100"
            className={FORM_INPUT_CLASS}
          />
        </WideModalField>
        {isEdit ? (
          <WideModalField
            label={t('change_intelligence.recovery.form.recovered_amount', {
              defaultValue: 'Recovered amount',
            })}
            htmlFor="bc-recovered"
            error={
              recoveredValid
                ? undefined
                : t('change_intelligence.recovery.form.amount_invalid', {
                    defaultValue: 'Enter a non-negative amount.',
                  })
            }
            hint={t('change_intelligence.recovery.form.recovered_hint', {
              defaultValue: 'How much has actually been collected so far.',
            })}
          >
            <input
              id="bc-recovered"
              inputMode="decimal"
              value={recoveredAmount}
              onChange={(e) => setRecoveredAmount(e.target.value)}
              placeholder="0.00"
              className={FORM_INPUT_CLASS}
            />
          </WideModalField>
        ) : (
          <WideModalField
            label={t('change_intelligence.recovery.form.currency', { defaultValue: 'Currency' })}
            htmlFor="bc-currency"
            hint={t('change_intelligence.recovery.form.currency_hint', {
              defaultValue: 'ISO code, e.g. USD or EUR.',
            })}
          >
            <input
              id="bc-currency"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              placeholder="USD"
              className={FORM_INPUT_CLASS}
            />
          </WideModalField>
        )}
        <WideModalField
          label={t('change_intelligence.recovery.form.status', { defaultValue: 'Status' })}
          htmlFor="bc-status"
        >
          <select
            id="bc-status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className={FORM_INPUT_CLASS}
          >
            {BACK_CHARGE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('change_intelligence.recovery.form.basis', { defaultValue: 'Basis' })}
          htmlFor="bc-basis"
          span={2}
          hint={t('change_intelligence.recovery.form.basis_hint', {
            defaultValue: 'What grounds the charge (a contract clause, an NCR reference).',
          })}
        >
          <input
            id="bc-basis"
            value={basis}
            onChange={(e) => setBasis(e.target.value)}
            placeholder={t('change_intelligence.recovery.form.basis_ph', {
              defaultValue: 'e.g. NCR-12 or contract clause 8.2',
            })}
            className={FORM_INPUT_CLASS}
          />
        </WideModalField>
        {!isEdit && (
          <WideModalField
            label={t('change_intelligence.recovery.form.source_ref', {
              defaultValue: 'Source reference',
            })}
            htmlFor="bc-source"
            span={2}
            hint={t('change_intelligence.recovery.form.source_ref_hint', {
              defaultValue: 'An optional external reference for this back-charge.',
            })}
          >
            <input
              id="bc-source"
              value={sourceRef}
              onChange={(e) => setSourceRef(e.target.value)}
              placeholder={t('change_intelligence.recovery.form.source_ref_ph', {
                defaultValue: 'e.g. a tracker row or document id',
              })}
              className={FORM_INPUT_CLASS}
            />
          </WideModalField>
        )}
      </WideModalSection>
      {mutation.isError && (
        <div className="flex items-center gap-2 text-sm text-semantic-error">
          <AlertTriangle className="h-4 w-4" />
          <span>{getErrorMessage(mutation.error)}</span>
        </div>
      )}
    </WideModal>
  );
}

/**
 * Recovery-performance index (#11): how much of what the project was entitled to
 * recover it actually recovered, split by how traceable the responsible owner
 * was. The high-vs-low contrast is the point - recovery tends to concentrate in
 * the high-traceability cohort, and absorbed cost in the low one.
 */
function RecoveryPerformanceCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'recovery-performance', projectId],
    queryFn: () => getRecoveryPerformance(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const perf = q.data;
  if (q.isLoading) return <SkeletonTable />;
  // Defensive: only render once we have a well-formed, non-empty performance.
  if (q.isError || !perf || !Array.isArray(perf.by_currency) || !perf.item_count) return null;
  // The primary currency carries the largest chargeable total; show its cohort
  // split so the high-vs-low rates are denominated in one currency.
  const primary = perf.by_currency.find((c) => c.currency === perf.primary_currency);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.recovery.perf.tile.rate', { defaultValue: 'Recovery rate' })}
          value={ratePercent(perf.primary_rate)}
          tone="success"
        />
        <StatTile
          label={t('change_intelligence.recovery.perf.tile.recovered', { defaultValue: 'Recovered' })}
          value={
            <MoneyDisplay
              amount={primary?.recovered_total ?? '0'}
              currency={perf.primary_currency}
              showCode
            />
          }
        />
        <StatTile
          label={t('change_intelligence.recovery.perf.tile.absorbed', { defaultValue: 'Absorbed' })}
          value={
            <MoneyDisplay
              amount={primary?.absorbed_total ?? '0'}
              currency={perf.primary_currency}
              showCode
            />
          }
          tone="error"
        />
      </div>
      {primary && primary.by_cohort.length > 0 && (
        <Card className="overflow-hidden p-0">
          <div className="border-b border-border-light px-3 py-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('change_intelligence.recovery.perf.heading', {
              defaultValue: 'Recovery rate by owner traceability ({{currency}})',
              currency: perf.primary_currency,
            })}
          </div>
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-3 py-2">
                  {t('change_intelligence.recovery.perf.col.traceability', { defaultValue: 'Traceability' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.recovery.perf.col.rate', { defaultValue: 'Rate' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.recovery.perf.col.chargeable', { defaultValue: 'Chargeable' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.recovery.perf.col.recovered', { defaultValue: 'Recovered' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('change_intelligence.recovery.perf.col.absorbed', { defaultValue: 'Absorbed' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {primary.by_cohort.map((c) => (
                <tr key={c.cohort} className="border-t border-border-light">
                  <td className="px-3 py-2">
                    <Badge variant={cohortVariant(c.cohort)}>{humanize(c.cohort)}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">{ratePercent(c.rate)}</td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={c.chargeable_total} currency={c.currency} showCode />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={c.recovered_total} currency={c.currency} showCode />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={c.absorbed_total} currency={c.currency} showCode />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-border-light px-3 py-2 text-xs leading-relaxed text-content-tertiary">
            {t('change_intelligence.recovery.perf.note', {
              defaultValue:
                'High traceability means the responsible owner is provable from the record (a timely notice or complete evidence). Back-charges with no scored evidence yet count as low, so this never overstates the high-traceability rate.',
            })}
          </p>
        </Card>
      )}
    </div>
  );
}

/**
 * Apportionment breakdown (#8): one back-charge's chargeable amount split across
 * the parties that share responsibility. Fetched on demand when the row is
 * expanded so the list view stays a single request.
 */
function ApportionmentDetail({
  projectId,
  backChargeId,
}: {
  projectId: string;
  backChargeId: string;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'apportionment', projectId, backChargeId],
    queryFn: () => getBackChargeApportionment(projectId, backChargeId),
    enabled: !!projectId && !!backChargeId,
    retry: false,
    staleTime: 30_000,
  });
  if (q.isLoading) {
    return (
      <div className="px-3 py-2 text-sm text-content-tertiary">
        {t('change_intelligence.recovery.apportionment.loading', { defaultValue: 'Loading split...' })}
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="px-3 py-2 text-sm text-semantic-error">{getErrorMessage(q.error)}</div>
    );
  }
  const data = q.data;
  if (!data || !data.is_apportioned || data.shares.length === 0) {
    return (
      <div className="px-3 py-2 text-sm text-content-tertiary">
        {t('change_intelligence.recovery.apportionment.none', {
          defaultValue: 'Not apportioned. The whole chargeable amount sits with the responsible party.',
        })}
      </div>
    );
  }
  return (
    <table className="w-full text-sm">
      <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
        <tr>
          <th className="px-3 py-2">
            {t('change_intelligence.recovery.apportionment.col.party', { defaultValue: 'Party' })}
          </th>
          <th className="px-3 py-2 text-right">
            {t('change_intelligence.recovery.apportionment.col.share', { defaultValue: 'Share' })}
          </th>
          <th className="px-3 py-2 text-right">
            {t('change_intelligence.recovery.apportionment.col.amount', { defaultValue: 'Amount' })}
          </th>
        </tr>
      </thead>
      <tbody>
        {data.shares.map((s) => (
          <tr key={s.id} className="border-t border-border-light">
            <td className="px-3 py-2 text-content-primary">{s.party}</td>
            <td className="px-3 py-2 text-right">{ratePercent(s.share_pct)}</td>
            <td className="px-3 py-2 text-right font-medium">
              <MoneyDisplay amount={s.share_amount} currency={s.currency} showCode />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Stable per-row key so adding / removing share rows never re-keys a sibling
// (which would move input focus). Not security-sensitive, just a render key.
let _apRowSeq = 0;
const nextRowKey = (): string => `apr-${(_apRowSeq += 1)}`;

interface ApportionShareRow {
  key: string;
  party: string;
  pct: string; // whole-number percent in the UI; sent as a [0,1] fraction
}

/**
 * Apportionment editor (#8, write side): split one back-charge's chargeable
 * amount across the parties that share responsibility. Percentages are entered
 * here and must total 100; they are sent as [0,1] fractions. Re-saving replaces
 * any previous split. The authoritative per-party amounts are computed
 * server-side (Decimal, rounded half-up); the figures shown here are a preview.
 */
function ApportionmentFormModal({
  open,
  onClose,
  projectId,
  backCharge,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  backCharge: BackCharge | null;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Pre-seed from any existing split once the modal opens; if none is recorded
  // the responsible party starts at 100%.
  const existingQ = useQuery({
    queryKey: ['change-intelligence', 'apportionment', projectId, backCharge?.id ?? ''],
    queryFn: () => getBackChargeApportionment(projectId, backCharge!.id),
    enabled: open && !!backCharge,
    retry: false,
    staleTime: 30_000,
  });

  const [rows, setRows] = useState<ApportionShareRow[]>([]);
  const [seededFor, setSeededFor] = useState<string | null>(null);
  const ready = open && !!backCharge && !existingQ.isLoading;
  const seedKey = ready && backCharge ? backCharge.id : null;
  if (seedKey !== seededFor) {
    setSeededFor(seedKey);
    if (ready && backCharge) {
      const data = existingQ.data;
      if (data && data.is_apportioned && data.shares.length > 0) {
        setRows(data.shares.map((s) => ({ key: s.id, party: s.party, pct: fractionToPercent(s.share_pct) })));
      } else {
        setRows([{ key: nextRowKey(), party: backCharge.responsible_party || '', pct: '100' }]);
      }
    }
  }

  const updateRow = (key: string, patch: Partial<ApportionShareRow>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const addRow = () => setRows((rs) => [...rs, { key: nextRowKey(), party: '', pct: '' }]);
  const removeRow = (key: string) => setRows((rs) => (rs.length <= 1 ? rs : rs.filter((r) => r.key !== key)));

  const chargeable = backCharge ? Number(backCharge.chargeable_amount) : 0;
  const currency = backCharge?.currency;
  const sumPct = rows.reduce((acc, r) => acc + (parseDecimalInput(r.pct) ?? 0), 0);
  const sumValid = Math.abs(sumPct - 100) < 0.01;
  const allPctValid = rows.every((r) => r.pct.trim() !== '' && isValidPercent(r.pct));
  const allPartiesValid = rows.every((r) => r.party.trim() !== '');
  const canSubmit = rows.length > 0 && allPctValid && allPartiesValid && sumValid;

  const mutation = useMutation<BackChargeApportionment, unknown, void>({
    mutationFn: () =>
      apportionBackCharge(
        projectId,
        backCharge!.id,
        rows.map((r) => ({ party: r.party.trim(), share_pct: percentToFraction(r.pct) })),
      ),
    onSuccess: () => {
      // The split feeds the per-party ledger and the recovery-rate rollups, so
      // refresh the apportionment detail and every recovery query for the project.
      void queryClient.invalidateQueries({
        queryKey: ['change-intelligence', 'apportionment', projectId, backCharge!.id],
      });
      void queryClient.invalidateQueries({ queryKey: ['change-intelligence', 'recovery-ledger', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['change-intelligence', 'back-charges', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['change-intelligence', 'recovery-performance', projectId] });
      addToast({
        type: 'success',
        title: t('change_intelligence.recovery.apportionment.saved', { defaultValue: 'Apportionment saved' }),
      });
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('change_intelligence.recovery.apportionment.save_failed', {
          defaultValue: 'Could not save the apportionment',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={mutation.isPending}
      size="md"
      title={t('change_intelligence.recovery.apportionment.form_title', { defaultValue: 'Apportion back-charge' })}
      subtitle={t('change_intelligence.recovery.apportionment.form_subtitle', {
        defaultValue:
          'Split the chargeable amount across the parties that share responsibility. Shares must total 100%.',
      })}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={mutation.isPending}
            className="rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            disabled={!canSubmit || mutation.isPending}
            onClick={() => mutation.mutate()}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90 disabled:opacity-40"
          >
            {mutation.isPending
              ? t('common.saving', { defaultValue: 'Saving...' })
              : t('change_intelligence.recovery.apportionment.save', { defaultValue: 'Save apportionment' })}
          </button>
        </>
      }
    >
      {existingQ.isLoading ? (
        <div className="py-6 text-center text-sm text-content-tertiary">
          {t('change_intelligence.recovery.apportionment.loading', { defaultValue: 'Loading split...' })}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-content-tertiary">
            <span>
              {t('change_intelligence.recovery.apportionment.chargeable', { defaultValue: 'Chargeable amount' })}
            </span>
            <span className="font-medium text-content-secondary">
              <MoneyDisplay amount={backCharge?.chargeable_amount ?? '0'} currency={currency} showCode />
            </span>
          </div>

          <ul className="space-y-2">
            {rows.map((r, i) => {
              const rowPct = parseDecimalInput(r.pct);
              const preview =
                chargeable > 0 && rowPct !== null ? fmtFixed((chargeable * rowPct) / 100, 2) : '0';
              return (
                <li key={r.key} className="flex items-end gap-2">
                  <WideModalField
                    label={
                      i === 0
                        ? t('change_intelligence.recovery.apportionment.col.party', { defaultValue: 'Party' })
                        : ''
                    }
                    htmlFor={`ap-party-${r.key}`}
                    className="flex-1"
                  >
                    <input
                      id={`ap-party-${r.key}`}
                      value={r.party}
                      onChange={(e) => updateRow(r.key, { party: e.target.value })}
                      placeholder={t('change_intelligence.recovery.apportionment.party_ph', {
                        defaultValue: 'Party name',
                      })}
                      className={FORM_INPUT_CLASS}
                    />
                  </WideModalField>
                  <WideModalField
                    label={
                      i === 0
                        ? t('change_intelligence.recovery.apportionment.col.share', { defaultValue: 'Share' })
                        : ''
                    }
                    htmlFor={`ap-pct-${r.key}`}
                    className="w-20"
                  >
                    <input
                      id={`ap-pct-${r.key}`}
                      inputMode="decimal"
                      value={r.pct}
                      onChange={(e) => updateRow(r.key, { pct: e.target.value })}
                      placeholder="0"
                      className={FORM_INPUT_CLASS}
                    />
                  </WideModalField>
                  <div className="w-28 pb-2 text-right text-xs text-content-tertiary">
                    <MoneyDisplay amount={preview} currency={currency} />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeRow(r.key)}
                    disabled={rows.length <= 1}
                    aria-label={t('change_intelligence.recovery.apportionment.remove', {
                      defaultValue: 'Remove party',
                    })}
                    className="mb-1 shrink-0 rounded-md p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error disabled:opacity-30"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={addRow}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('change_intelligence.recovery.apportionment.add_party', { defaultValue: 'Add party' })}
            </button>
            <span
              className={`text-xs font-medium tabular-nums ${sumValid ? 'text-semantic-success' : 'text-semantic-error'}`}
            >
              {t('change_intelligence.recovery.apportionment.total', {
                defaultValue: 'Total {{pct}}%',
                pct: Number.isFinite(sumPct) ? Math.round(sumPct * 100) / 100 : 0,
              })}
            </span>
          </div>
          {!sumValid && (
            <p className="text-xs text-semantic-error">
              {t('change_intelligence.recovery.apportionment.total_invalid', {
                defaultValue: 'Shares must total exactly 100%.',
              })}
            </p>
          )}
        </div>
      )}
    </WideModal>
  );
}

function RecoveryTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const ledgerQ = useQuery({
    queryKey: ['change-intelligence', 'recovery-ledger', projectId],
    queryFn: () => getRecoveryLedger(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const chargesQ = useQuery({
    queryKey: ['change-intelligence', 'back-charges', projectId],
    queryFn: () => listBackCharges(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const ledger = ledgerQ.data;
  const charges = chargesQ.data ?? [];
  const [openCharge, setOpenCharge] = useState<string | null>(null);
  // The write surface: a single modal that both creates a back-charge (editing
  // null) and edits an existing one (editing set to the row).
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<BackCharge | null>(null);
  // The back-charge whose apportionment is being edited (null = modal closed).
  const [apportionFor, setApportionFor] = useState<BackCharge | null>(null);

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };
  const openEdit = (bc: BackCharge) => {
    setEditing(bc);
    setFormOpen(true);
  };

  const loading = ledgerQ.isLoading || chargesQ.isLoading;
  const error = ledgerQ.isError ? ledgerQ.error : chargesQ.isError ? chargesQ.error : null;
  const isEmpty = !ledger || ledger.item_count === 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90"
        >
          <Plus className="h-4 w-4" />
          {t('change_intelligence.recovery.record', { defaultValue: 'Record back-charge' })}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.recovery.tile.back_charges', { defaultValue: 'Back-charges' })}
          value={ledger?.item_count ?? 0}
        />
        <StatTile
          label={t('change_intelligence.recovery.tile.open', { defaultValue: 'Open' })}
          value={ledger?.open_count ?? 0}
          tone="warning"
        />
        <StatTile
          label={t('change_intelligence.recovery.tile.outstanding', { defaultValue: 'Outstanding' })}
          value={<MoneyDisplay amount={ledger?.primary_outstanding ?? '0'} currency={ledger?.primary_currency} showCode />}
        />
      </div>
      {loading ? (
        <SkeletonTable />
      ) : error ? (
        <Card className="p-4">
          <div className="flex items-center gap-2 text-sm text-semantic-error">
            <AlertTriangle className="h-4 w-4" />
            <span>{getErrorMessage(error)}</span>
          </div>
        </Card>
      ) : isEmpty ? (
        <div className="space-y-3">
          <EmptyState
            icon={<Wallet className="h-6 w-6" />}
            title={t('change_intelligence.recovery.empty_title', { defaultValue: 'No back-charges' })}
            description={t('change_intelligence.recovery.empty_desc', {
              defaultValue: 'Record a back-charge to start tracking what the project means to recover.',
            })}
          />
          <div className="flex justify-center">
            <button
              type="button"
              onClick={openCreate}
              className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90"
            >
              <Plus className="h-4 w-4" />
              {t('change_intelligence.recovery.record', { defaultValue: 'Record back-charge' })}
            </button>
          </div>
        </div>
      ) : (
        <>
          <RecoveryPerformanceCard projectId={projectId} />
          <Card className="overflow-hidden p-0">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="px-3 py-2">
                    {t('change_intelligence.recovery.col.responsible_party', {
                      defaultValue: 'Responsible party',
                    })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.recovery.col.open', { defaultValue: 'Open' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.recovery.col.chargeable', { defaultValue: 'Chargeable' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.recovery.col.recovered', { defaultValue: 'Recovered' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.recovery.col.outstanding', { defaultValue: 'Outstanding' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {ledger?.by_party.map((p) => (
                  <tr key={`${p.party}-${p.currency}`} className="border-t border-border-light">
                    <td className="px-3 py-2 font-medium text-content-primary">{p.party}</td>
                    <td className="px-3 py-2 text-right">{p.open_count}</td>
                    <td className="px-3 py-2 text-right">
                      <MoneyDisplay amount={p.chargeable_total} currency={p.currency} showCode />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <MoneyDisplay amount={p.recovered_total} currency={p.currency} showCode />
                    </td>
                    <td className="px-3 py-2 text-right font-medium">
                      <MoneyDisplay amount={p.outstanding_total} currency={p.currency} showCode />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          {charges.length > 0 && (
            <Card className="overflow-hidden p-0">
              <div className="border-b border-border-light px-3 py-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('change_intelligence.recovery.apportionment_heading', {
                  defaultValue: 'Apportionment by back-charge',
                })}
              </div>
              <ul>
                {charges.map((bc) => {
                  const expanded = openCharge === bc.id;
                  return (
                    <li key={bc.id} className="border-t border-border-light first:border-t-0">
                      <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm hover:bg-surface-secondary">
                        <button
                          type="button"
                          onClick={() => setOpenCharge(expanded ? null : bc.id)}
                          aria-expanded={expanded}
                          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-left"
                        >
                          <ArrowRight
                            className={`h-3.5 w-3.5 shrink-0 text-content-tertiary transition-transform ${expanded ? 'rotate-90' : ''}`}
                          />
                          <span className="font-medium text-content-primary">
                            {bc.responsible_party ||
                              t('change_intelligence.recovery.unassigned', { defaultValue: '(unassigned)' })}
                          </span>
                          <span className="text-content-tertiary">{bc.description || bc.basis || bc.source_ref}</span>
                          <span className="ml-auto">
                            <MoneyDisplay amount={bc.chargeable_amount} currency={bc.currency} showCode />
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => openEdit(bc)}
                          aria-label={t('change_intelligence.recovery.edit', {
                            defaultValue: 'Edit back-charge',
                          })}
                          title={t('change_intelligence.recovery.edit', { defaultValue: 'Edit back-charge' })}
                          className="shrink-0 rounded-md p-1 text-content-tertiary hover:bg-surface-primary hover:text-content-primary"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      {expanded && (
                        <div className="border-t border-border-light bg-surface-primary">
                          <ApportionmentDetail projectId={projectId} backChargeId={bc.id} />
                          <div className="flex justify-end px-3 py-2">
                            <button
                              type="button"
                              onClick={() => setApportionFor(bc)}
                              className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
                            >
                              <SplitSquareHorizontal className="h-3.5 w-3.5" />
                              {t('change_intelligence.recovery.apportionment.edit_split', {
                                defaultValue: 'Edit split',
                              })}
                            </button>
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </>
      )}
      <BackChargeFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        projectId={projectId}
        editing={editing}
      />
      <ApportionmentFormModal
        open={apportionFor !== null}
        onClose={() => setApportionFor(null)}
        projectId={projectId}
        backCharge={apportionFor}
      />
    </div>
  );
}

// --- Tab: dispute risk (the dispute radar) ---------------------------------

function DisputeRiskTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [openId, setOpenId] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ['change-intelligence', 'dispute-risk', projectId],
    queryFn: () => getDisputeRiskBoard(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const board = q.data;
  const bands = board?.summary.band_counts ?? {};
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label={t('change_intelligence.dispute.tile.open_changes', { defaultValue: 'Open changes' })}
          value={board?.summary.item_count ?? 0}
        />
        <StatTile
          label={t('change_intelligence.dispute.tile.high', { defaultValue: 'High' })}
          value={bands.high ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.dispute.tile.elevated', { defaultValue: 'Elevated' })}
          value={bands.elevated ?? 0}
          tone="warning"
        />
        <StatTile
          label={t('change_intelligence.dispute.tile.low', { defaultValue: 'Low' })}
          value={bands.low ?? 0}
        />
      </div>
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!board || board.items.length === 0}
        emptyIcon={<Radar className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.dispute.empty_title', { defaultValue: 'No open changes' })}
        emptyDescription={t('change_intelligence.dispute.empty_desc', {
          defaultValue: 'There are no open changes to assess for dispute exposure right now.',
        })}
      >
        <div className="space-y-2">
          {board?.items.map((it) => {
            const expanded = openId === it.change_id;
            const reconstructType = reconstructTypeForKind(it.kind);
            return (
              <Card key={it.change_id} className="overflow-hidden p-0">
                <button
                  type="button"
                  onClick={() => setOpenId(expanded ? null : it.change_id)}
                  aria-expanded={expanded}
                  className="w-full px-3 py-3 text-left hover:bg-surface-secondary"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <ArrowRight
                      className={`h-3.5 w-3.5 shrink-0 text-content-tertiary transition-transform ${expanded ? 'rotate-90' : ''}`}
                    />
                    {/* The band shares its vocabulary (and translation) with the
                        summary tiles above; driver and cure are stable engine
                        tokens (cure text is 1:1 per driver), translated by token
                        with the wire text as the unknown-token fallback. */}
                    <Badge variant={EXPOSURE_VARIANT[it.band]}>
                      {t(`change_intelligence.dispute.tile.${it.band}`, { defaultValue: humanize(it.band) })}
                    </Badge>
                    <span className="text-sm font-semibold text-content-primary">{it.exposure_score}</span>
                    <span className="text-xs text-content-tertiary">
                      {t(`claims_evidence.kind.${it.kind}`, { defaultValue: humanize(it.kind) })}
                    </span>
                    <span className="font-medium text-content-primary">
                      {it.change_ref ? `${it.change_ref}: ` : ''}
                      {it.title || t('change_intelligence.common.untitled', { defaultValue: '(untitled)' })}
                    </span>
                    <span className="ml-auto inline-flex items-center gap-1 text-xs text-content-tertiary">
                      <ShieldAlert className="h-3.5 w-3.5" />
                      {t(`change_intelligence.dispute.driver.${it.dominant_driver}`, {
                        defaultValue: humanize(it.dominant_driver),
                      })}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 pl-5 text-sm text-content-secondary">
                    {it.currency ? (
                      <span>
                        {t('change_intelligence.dispute.at_risk', { defaultValue: 'At risk:' })}{' '}
                        <MoneyDisplay amount={it.money_basis} currency={it.currency} showCode />
                      </span>
                    ) : null}
                    <span className="text-content-tertiary">
                      {t(`change_intelligence.dispute.cure.${it.dominant_driver}`, {
                        defaultValue: it.recommended_cure,
                      })}
                    </span>
                  </div>
                </button>
                {expanded && (
                  <div className="space-y-3 border-t border-border-light bg-surface-primary p-3">
                    <ProvabilityGauge
                      projectId={projectId}
                      subjectKind={it.kind as SubjectKind}
                      subjectId={it.change_id}
                    />
                    {reconstructType ? (
                      <EvidenceThreadPanel
                        projectId={projectId}
                        subjectType={reconstructType}
                        subjectId={it.change_id}
                      />
                    ) : null}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: decision impact ("what does approving this add?") ----------------

function DecisionImpactTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [candidateId, setCandidateId] = useState('');
  const [submitted, setSubmitted] = useState('');
  const q = useQuery({
    queryKey: ['change-intelligence', 'decision-impact', projectId, submitted],
    queryFn: () => getDecisionImpact(projectId, submitted),
    enabled: !!projectId && !!submitted,
    retry: false,
    staleTime: 30_000,
  });
  const impact = q.data;
  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <label className="block text-sm font-medium text-content-secondary" htmlFor="ci-candidate">
          {t('change_intelligence.decision.candidate_label', { defaultValue: 'Candidate change id' })}
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <input
            id="ci-candidate"
            value={candidateId}
            onChange={(e) => setCandidateId(e.target.value)}
            placeholder={t('change_intelligence.decision.candidate_ph', {
              defaultValue: 'Paste the id of the change order, variation or MoC under decision',
            })}
            className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary p-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
          <button
            type="button"
            disabled={!candidateId.trim()}
            onClick={() => setSubmitted(candidateId.trim())}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            <GitCompareArrows className="h-4 w-4" />
            {t('change_intelligence.decision.preview', { defaultValue: 'Preview impact' })}
          </button>
        </div>
        <p className="text-xs text-content-tertiary">
          {t('change_intelligence.decision.helper', {
            defaultValue:
              'Previews what approving this change adds on top of everything already committed, per currency. Nothing is changed.',
          })}
        </p>
      </Card>
      {submitted ? (
        <PanelState
          loading={q.isLoading}
          error={q.isError ? q.error : null}
          empty={!impact || impact.totals_by_currency.length === 0}
          emptyIcon={<GitCompareArrows className="h-6 w-6" />}
          emptyTitle={t('change_intelligence.decision.empty_title', { defaultValue: 'No impact to show' })}
          emptyDescription={t('change_intelligence.decision.empty_desc', {
            defaultValue: 'This candidate carries no cost or schedule against the committed baseline.',
          })}
        >
          <Card className="overflow-hidden p-0">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="px-3 py-2">
                    {t('change_intelligence.decision.col.by_kind', { defaultValue: 'By kind' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.decision.col.committed', { defaultValue: 'Committed' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.decision.col.this_change', { defaultValue: 'This change' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.decision.col.resulting', { defaultValue: 'Resulting' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('change_intelligence.decision.col.days', { defaultValue: 'Days' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {impact?.rows.map((r) => (
                  <tr key={`${r.kind}-${r.currency}`} className="border-t border-border-light">
                    <td className="px-3 py-2 font-medium text-content-primary">
                      {humanize(r.kind)} <span className="text-content-tertiary">{r.currency}</span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <MoneyDisplay amount={r.current_committed_cost} currency={r.currency} showCode />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <MoneyDisplay amount={r.candidate_cost_delta} currency={r.currency} showCode colorize />
                    </td>
                    <td className="px-3 py-2 text-right font-medium">
                      <MoneyDisplay amount={r.resulting_cost} currency={r.currency} showCode />
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.current_committed_days} &rarr; {r.resulting_days}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          {impact && impact.totals_by_currency.length > 1 && (
            <p className="text-xs text-content-tertiary">
              {t('change_intelligence.decision.multi_currency', {
                defaultValue:
                  'This decision spans {{count}} currencies; totals are kept separate and never blended.',
                count: impact.totals_by_currency.length,
              })}
            </p>
          )}
        </PanelState>
      ) : (
        <EmptyState
          icon={<GitCompareArrows className="h-6 w-6" />}
          title={t('change_intelligence.decision.prompt_title', { defaultValue: 'Preview a decision' })}
          description={t('change_intelligence.decision.prompt_desc', {
            defaultValue:
              'Enter the id of a change under decision to see what approving it adds to the committed position.',
          })}
        />
      )}
    </div>
  );
}

// --- Tab: watch ("which open changes are quietly going wrong") -------------

function WatchTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'change-watch', projectId],
    queryFn: () => getChangeWatch(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const watch = q.data;
  const counts = watch?.counts ?? {};
  // Only the flagged items are worth listing; an "ok" change is not drifting.
  const flagged = (watch?.items ?? []).filter((r) => r.classification !== 'ok');
  // The "Incomplete" count is always 0 today: the backend hardcodes a
  // completeness_score of 1.0, so a change can never be classified incomplete.
  // Hide the tile until backend completeness scoring is wired so it never shows
  // a permanent, misleading zero.
  const showIncomplete = (counts.incomplete ?? 0) > 0;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.watch.tile.lost', { defaultValue: 'Lost' })}
          value={counts.lost ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.watch.tile.stalled', { defaultValue: 'Stalled' })}
          value={counts.stalled ?? 0}
          tone="warning"
        />
        {showIncomplete && (
          <StatTile
            label={t('change_intelligence.watch.tile.incomplete', { defaultValue: 'Incomplete' })}
            value={counts.incomplete ?? 0}
          />
        )}
        <StatTile
          label={t('change_intelligence.watch.tile.on_track', { defaultValue: 'On track' })}
          value={counts.ok ?? 0}
          tone="success"
        />
      </div>
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={flagged.length === 0}
        emptyIcon={<ShieldAlert className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.watch.empty_title', { defaultValue: 'Nothing drifting' })}
        emptyDescription={t('change_intelligence.watch.empty_desc', {
          defaultValue: 'No open change is stalled, lost or incomplete right now.',
        })}
      >
        <div className="space-y-2">
          {flagged.map((r) => (
            <Card key={r.change_id} className="p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={WATCH_VARIANT[r.classification]}>{humanize(r.classification)}</Badge>
                <span className="text-xs text-content-tertiary">{humanize(r.kind)}</span>
                <span className="ml-auto flex flex-wrap items-center gap-x-3 text-sm text-content-secondary">
                  <span>
                    {t('change_intelligence.watch.idle_days', {
                      defaultValue: '{{days}}d idle',
                      days: fmtFixed(r.idle_days, 0),
                    })}
                  </span>
                  {r.overdue_days > 0 && (
                    <span className="text-semantic-error">
                      {t('change_intelligence.watch.overdue_days', {
                        defaultValue: '{{days}}d overdue',
                        days: fmtFixed(r.overdue_days, 0),
                      })}
                    </span>
                  )}
                </span>
              </div>
              {r.reasons.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {r.reasons.map((reason) => (
                    <span key={reason} className="text-xs text-content-tertiary">
                      {humanize(reason)}
                    </span>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: clarifier co-pilot -----------------------------------------------

const CONTRACT_STANDARDS = ['', 'FIDIC', 'NEC4', 'JCT'];

function ClarifierTab() {
  const { t } = useTranslation();
  const [note, setNote] = useState('');
  const [standard, setStandard] = useState('');
  const m = useMutation<ClarifiedRequest, unknown, void>({
    mutationFn: () => clarifyChangeNote(note, standard),
  });
  const result = m.data;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="space-y-3 p-4">
        <label className="block text-sm font-medium text-content-secondary" htmlFor="ci-note">
          {t('change_intelligence.clarifier.note_label', { defaultValue: 'Rough change note' })}
        </label>
        <textarea
          id="ci-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={7}
          placeholder={t('change_intelligence.clarifier.note_ph', {
            defaultValue: 'Paste a quick description of the change as you would jot it down...',
          })}
          className="w-full rounded-md border border-border-light bg-surface-primary p-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        />
        <div className="flex items-center gap-3">
          <select
            value={standard}
            onChange={(e) => setStandard(e.target.value)}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
            aria-label={t('change_intelligence.clarifier.standard_label', { defaultValue: 'Contract standard' })}
          >
            {CONTRACT_STANDARDS.map((s) => (
              <option key={s || 'none'} value={s}>
                {s || t('change_intelligence.clarifier.no_standard', { defaultValue: 'No standard' })}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!note.trim() || m.isPending}
            onClick={() => m.mutate()}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {m.isPending
              ? t('change_intelligence.clarifier.analyzing', { defaultValue: 'Analyzing...' })
              : t('change_intelligence.clarifier.analyze', { defaultValue: 'Analyze' })}
          </button>
        </div>
        {m.isError && (
          <div className="flex items-center gap-2 text-sm text-semantic-error">
            <AlertTriangle className="h-4 w-4" />
            <span>{getErrorMessage(m.error)}</span>
          </div>
        )}
      </Card>

      <Card className="p-4">
        {!result ? (
          <EmptyState
            icon={<Sparkles className="h-6 w-6" />}
            title={t('change_intelligence.clarifier.empty_title', { defaultValue: 'Structured draft' })}
            description={t('change_intelligence.clarifier.empty_desc', {
              defaultValue:
                'Analyze a note to see a suggested title, classification, gaps to fill and likely contract clauses.',
            })}
          />
        ) : (
          <div className="space-y-3">
            <div>
              <div className="text-lg font-semibold text-content-primary">
                {result.title || t('change_intelligence.common.untitled', { defaultValue: '(untitled)' })}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Badge variant="blue">{humanize(result.detected_classification)}</Badge>
                <Badge variant={result.completeness >= 0.7 ? 'success' : result.completeness >= 0.4 ? 'warning' : 'error'}>
                  {t('change_intelligence.common.pct_complete', {
                    defaultValue: '{{pct}}% complete',
                    pct: Math.round(result.completeness * 100),
                  })}
                </Badge>
                {result.suggested_route && (
                  <span className="text-xs text-content-tertiary">
                    {t('change_intelligence.clarifier.route', {
                      defaultValue: 'Route: {{route}}',
                      route: humanize(result.suggested_route),
                    })}
                  </span>
                )}
              </div>
            </div>
            {result.normalized_summary && (
              <p className="text-sm text-content-secondary">{result.normalized_summary}</p>
            )}
            {result.missing.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('change_intelligence.clarifier.still_missing', { defaultValue: 'Still missing' })}
                </div>
                <ul className="mt-1 space-y-1 text-sm">
                  {result.missing.map((g) => (
                    <li key={g.field} className="flex items-start gap-2">
                      <Badge variant={severityVariant(g.severity)}>{g.severity}</Badge>
                      <span className="text-content-secondary">{g.question}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.clause_suggestions.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('change_intelligence.clarifier.likely_clauses', { defaultValue: 'Likely clauses' })}
                </div>
                <ul className="mt-1 space-y-1 text-sm">
                  {result.clause_suggestions.map((c) => (
                    <li key={`${c.standard}-${c.clause_ref}`} className="text-content-secondary">
                      <span className="font-medium">{c.standard} {c.clause_ref}</span> - {c.rationale}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

// --- Tab: multi-source intake ----------------------------------------------

const INTAKE_PLACEHOLDER = `{
  "Change Title": "Extra waterproofing to basement",
  "Estimated Cost": "$12,500.00",
  "Schedule Impact (days)": "5",
  "Raised By": "Site Engineer",
  "Change No": "CO-44"
}`;

function IntakeTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const profilesQ = useQuery({
    queryKey: ['change-intelligence', 'intake-profiles', projectId],
    queryFn: () => getIntakeProfiles(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const profiles = profilesQ.data?.profiles ?? [];
  const [profileName, setProfileName] = useState('');
  const [raw, setRaw] = useState('');
  const effectiveProfile = profileName || profiles[0]?.profile_name || '';

  const m = useMutation<IntakePreview, unknown, void>({
    mutationFn: () => {
      let record: unknown;
      try {
        record = JSON.parse(raw || '{}');
      } catch {
        throw new Error(
          t('change_intelligence.intake.error_not_json', { defaultValue: 'The record is not valid JSON.' }),
        );
      }
      if (typeof record !== 'object' || record === null || Array.isArray(record)) {
        throw new Error(
          t('change_intelligence.intake.error_not_object', {
            defaultValue: 'The record must be a JSON object of field: value pairs.',
          }),
        );
      }
      return previewIntake(projectId, effectiveProfile, record as Record<string, unknown>);
    },
  });
  const result = m.data;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="space-y-3 p-4">
        <label className="block text-sm font-medium text-content-secondary" htmlFor="ci-intake-record">
          {t('change_intelligence.intake.record_label', { defaultValue: 'Foreign change record (JSON)' })}
        </label>
        <textarea
          id="ci-intake-record"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={9}
          placeholder={INTAKE_PLACEHOLDER}
          className="w-full rounded-md border border-border-light bg-surface-primary p-2 font-mono text-xs focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        />
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={effectiveProfile}
            onChange={(e) => setProfileName(e.target.value)}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
            aria-label={t('change_intelligence.intake.profile_label', { defaultValue: 'Intake profile' })}
            disabled={profiles.length === 0}
          >
            {profiles.map((p) => (
              <option key={p.profile_name} value={p.profile_name}>
                {humanize(p.profile_name)}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!raw.trim() || !effectiveProfile || m.isPending}
            onClick={() => m.mutate()}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            <Import className="h-4 w-4" />
            {m.isPending
              ? t('change_intelligence.intake.reading', { defaultValue: 'Reading...' })
              : t('change_intelligence.intake.preview', { defaultValue: 'Preview' })}
          </button>
        </div>
        <p className="text-xs text-content-tertiary">
          {t('change_intelligence.intake.helper', {
            defaultValue:
              'Paste a row from a tracker spreadsheet or an email intake form. The record is normalized to a canonical change draft for preview only - nothing is saved.',
          })}
        </p>
        {m.isError && (
          <div className="flex items-center gap-2 text-sm text-semantic-error">
            <AlertTriangle className="h-4 w-4" />
            <span>{getErrorMessage(m.error)}</span>
          </div>
        )}
      </Card>

      <Card className="p-4">
        {!result ? (
          <EmptyState
            icon={<Import className="h-6 w-6" />}
            title={t('change_intelligence.intake.empty_title', { defaultValue: 'Canonical draft' })}
            description={t('change_intelligence.intake.empty_desc', {
              defaultValue:
                'Preview a foreign record to see the title, cost, schedule impact and what could not be mapped.',
            })}
          />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold text-content-primary">
                {result.draft.title || t('change_intelligence.intake.no_title', { defaultValue: '(no title)' })}
              </span>
              <Badge
                variant={result.completeness >= 0.7 ? 'success' : result.completeness >= 0.4 ? 'warning' : 'error'}
              >
                {t('change_intelligence.common.pct_complete', {
                  defaultValue: '{{pct}}% complete',
                  pct: Math.round(result.completeness * 100),
                })}
              </Badge>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <dt className="text-content-tertiary">
                {t('change_intelligence.intake.cost_impact', { defaultValue: 'Cost impact' })}
              </dt>
              <dd className="text-content-secondary">
                {result.draft.cost_impact !== null ? (
                  <MoneyDisplay amount={result.draft.cost_impact} currency={result.draft.currency ?? ''} showCode />
                ) : (
                  '-'
                )}
              </dd>
              <dt className="text-content-tertiary">
                {t('change_intelligence.intake.schedule_impact', { defaultValue: 'Schedule impact' })}
              </dt>
              <dd className="text-content-secondary">
                {result.draft.schedule_impact_days !== null
                  ? t('change_intelligence.intake.days_value', {
                      defaultValue: '{{days}} d',
                      days: result.draft.schedule_impact_days,
                    })
                  : '-'}
              </dd>
              <dt className="text-content-tertiary">
                {t('change_intelligence.intake.requested_by', { defaultValue: 'Requested by' })}
              </dt>
              <dd className="text-content-secondary">{result.draft.requested_by || '-'}</dd>
              <dt className="text-content-tertiary">
                {t('change_intelligence.intake.reference', { defaultValue: 'Reference' })}
              </dt>
              <dd className="text-content-secondary">{result.draft.source_ref || '-'}</dd>
            </dl>
            {result.draft.description && <p className="text-sm text-content-secondary">{result.draft.description}</p>}
            {result.missing_required.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('change_intelligence.intake.missing_required', { defaultValue: 'Missing required' })}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {result.missing_required.map((f) => (
                    <Badge key={f} variant="error">
                      {humanize(f)}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {result.unmapped_fields.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('change_intelligence.intake.unmapped_columns', { defaultValue: 'Unmapped columns' })}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {result.unmapped_fields.map((f) => (
                    <span
                      key={f}
                      className="rounded border border-border-light px-1.5 py-0.5 text-xs text-content-tertiary"
                    >
                      {f}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {result.warnings.length > 0 && (
              <ul className="space-y-1 text-xs text-content-secondary">
                {result.warnings.map((w) => (
                  <li key={w} className="flex items-start gap-1.5">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-semantic-error" />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

// --- Tab: predictive delay risk --------------------------------------------

const DELAY_VARIANT: Record<DelayBand, BadgeVariant> = {
  high: 'error',
  elevated: 'warning',
  low: 'neutral',
};

function DelayRiskTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'delay-risk', projectId],
    queryFn: () => getDelayRiskBoard(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const board = q.data;
  const counts = board?.band_counts ?? {};
  const items = board?.items ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <StatTile
          label={t('change_intelligence.delay.tile.high', { defaultValue: 'High' })}
          value={counts.high ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.delay.tile.elevated', { defaultValue: 'Elevated' })}
          value={counts.elevated ?? 0}
          tone="warning"
        />
        <StatTile
          label={t('change_intelligence.delay.tile.low', { defaultValue: 'Low' })}
          value={counts.low ?? 0}
          tone="success"
        />
      </div>
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={items.length === 0}
        emptyIcon={<Gauge className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.delay.empty_title', { defaultValue: 'No open changes' })}
        emptyDescription={t('change_intelligence.delay.empty_desc', {
          defaultValue: 'There are no open changes to score for delay risk right now.',
        })}
      >
        <div className="space-y-2">
          {items.map((it) => (
            <Card key={it.change_id} className="p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={DELAY_VARIANT[it.band]}>{humanize(it.band)}</Badge>
                <span className="font-medium text-content-primary">{it.change_ref || humanize(it.kind)}</span>
                <span className="text-xs text-content-tertiary">{it.title}</span>
                <span className="ml-auto flex flex-wrap items-center gap-x-3 text-sm text-content-secondary">
                  <span>
                    {t('change_intelligence.delay.risk_pct', {
                      defaultValue: '{{pct}}% risk',
                      pct: Math.round(it.risk * 100),
                    })}
                  </span>
                  {it.overdue && (
                    <span className="text-semantic-error">
                      {t('change_intelligence.delay.overdue', { defaultValue: 'overdue' })}
                    </span>
                  )}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary">
                <span>
                  {it.party
                    ? t('change_intelligence.delay.held_by', {
                        defaultValue: 'Held by {{party}}',
                        party: humanize(it.party),
                      })
                    : t('change_intelligence.delay.unassigned', { defaultValue: 'Unassigned' })}
                </span>
                {it.top_factors.slice(0, 3).map((f) => (
                  <span key={f.name}>{`${humanize(f.name)} ${Math.round(f.value * 100)}%`}</span>
                ))}
              </div>
            </Card>
          ))}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: pre-construction scope ambiguity ---------------------------------

const SCOPE_VARIANT: Record<ScopeBand, BadgeVariant> = {
  high: 'error',
  elevated: 'warning',
  low: 'neutral',
};

// Mirrors backend REASON_LABELS in scope_ambiguity.py - report-level
// top_reasons arrive as stable reason keys; map them to human wording here. The
// English fallbacks double as the i18n default values, keyed per reason.
const SCOPE_REASON_LABELS: Record<string, string> = {
  vague_language: 'Vague or placeholder wording',
  provisional_sum: 'Provisional sum or allowance',
  missing_quantity: 'Missing or zero quantity',
  missing_unit: 'Missing unit of measure',
  underspecified_description: 'Under-specified description',
};

function scopeReasonLabel(reason: string, t: TFunction): string {
  const fallback = SCOPE_REASON_LABELS[reason];
  if (fallback) {
    return t(`change_intelligence.scope.reason.${reason}`, { defaultValue: fallback });
  }
  return humanize(reason);
}

function ScopeRiskTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'scope-ambiguity', projectId],
    queryFn: () => getScopeAmbiguity(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const report = q.data;
  const counts = report?.counts_by_band ?? {};
  const lines = report?.lines ?? [];
  const index = Math.round(report?.ambiguity_index ?? 0);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label={t('change_intelligence.scope.tile.ambiguity_index', { defaultValue: 'Ambiguity index' })}
          value={report ? index : '-'}
          tone={index >= 50 ? 'error' : index >= 25 ? 'warning' : 'success'}
        />
        <StatTile
          label={t('change_intelligence.scope.tile.high', { defaultValue: 'High' })}
          value={counts.high ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.scope.tile.elevated', { defaultValue: 'Elevated' })}
          value={counts.elevated ?? 0}
          tone="warning"
        />
        <StatTile
          label={t('change_intelligence.scope.tile.low', { defaultValue: 'Low' })}
          value={counts.low ?? 0}
          tone="success"
        />
      </div>
      {report && report.top_reasons.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-content-tertiary">
            {t('change_intelligence.scope.top_drivers', { defaultValue: 'Top drivers' })}
          </span>
          {report.top_reasons.map((r) => (
            <Badge key={r} variant="neutral">
              {scopeReasonLabel(r, t)}
            </Badge>
          ))}
        </div>
      )}
      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={lines.length === 0}
        emptyIcon={<FileSearch className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.scope.empty_title', { defaultValue: 'No bill lines to grade' })}
        emptyDescription={t('change_intelligence.scope.empty_desc', {
          defaultValue:
            'Once this project carries a bill of quantities, its lines are graded here for the vague scope that breeds a change order later.',
        })}
      >
        <div className="space-y-2">
          {lines.map((ln) => (
            <Card key={ln.line_id} className="p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={SCOPE_VARIANT[ln.band]}>{humanize(ln.band)}</Badge>
                <span className="font-mono text-xs text-content-tertiary">{ln.line_id.slice(0, 8)}</span>
                <span className="ml-auto text-sm font-semibold text-content-secondary">{`${ln.score}/100`}</span>
              </div>
              {ln.labels.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
                  {ln.labels.map((label) => (
                    <span
                      key={label}
                      className="rounded-full bg-surface-secondary px-2 py-0.5 text-2xs text-content-secondary"
                    >
                      {label}
                    </span>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: contractual notice / time-bar register ---------------------------

const NOTICE_STATUS_VARIANT: Record<NoticeStatus, BadgeVariant> = {
  overdue: 'error',
  due_soon: 'warning',
  upcoming: 'success',
  met: 'success',
  unknown: 'neutral',
};

// Traffic-light chip labels. Explicit wording (not the raw humanized token) so
// "due_soon" reads "Due soon"; keyed per status for i18n like the scope reasons.
const NOTICE_STATUS_LABELS: Record<NoticeStatus, string> = {
  overdue: 'Overdue',
  due_soon: 'Due soon',
  upcoming: 'Upcoming',
  met: 'Met',
  unknown: 'Unknown',
};

function noticeStatusLabel(status: string, t: TFunction): string {
  const fallback = NOTICE_STATUS_LABELS[status as NoticeStatus];
  if (fallback) {
    return t(`change_intelligence.notice.status.${status}`, { defaultValue: fallback });
  }
  return humanize(status);
}

// The clock kinds the register derives. EOT stays the well-known acronym.
const NOTICE_TYPE_LABELS: Record<string, string> = {
  claim_notice: 'Claim notice',
  eot_notice: 'EOT notice',
  quotation: 'Quotation',
  assessment: 'Assessment',
  response: 'Response',
};

function noticeTypeLabel(noticeType: string, t: TFunction): string {
  const fallback = NOTICE_TYPE_LABELS[noticeType];
  if (fallback) {
    return t(`change_intelligence.notice.type.${noticeType}`, { defaultValue: fallback });
  }
  return humanize(noticeType);
}

// Standards the register recognises; '' means "use the project's own contract
// standard". These map cleanly onto the engine's standard normaliser (a free-text
// hint such as "NEC4" also resolves, but these are the clean tokens). Recognised
// is not the same as timed: the engine deliberately holds no notice periods for
// CCDC, so choosing it reports no deadline rather than borrowing a generic one,
// and that is the honest answer until the periods are sourced.
const NOTICE_STANDARDS = ['', 'FIDIC', 'NEC', 'JCT', 'AIA', 'ConsensusDocs', 'CCDC'];

// Canonical resolved-standard token -> display label for the resolved badge.
const NOTICE_STANDARD_DISPLAY: Record<string, string> = {
  FIDIC: 'FIDIC',
  NEC: 'NEC',
  JCT: 'JCT',
  AIA: 'AIA',
  CONSENSUSDOCS: 'ConsensusDocs',
  CCDC: 'CCDC',
};

/** Colour the signed countdown by urgency: overdue red, due-soon amber, else calm. */
function noticeCountdownTone(c: NoticeClock): string {
  if (c.status === 'overdue') return 'text-semantic-error';
  if (c.status === 'due_soon') return 'text-semantic-warning';
  return 'text-content-secondary';
}

/**
 * Render the signed countdown. days_remaining is a pure day count (negative once
 * overdue), null once the clock is stopped or undatable; when stopped we show the
 * date the action was served instead. Whole days are enough for the register.
 */
function noticeCountdown(c: NoticeClock, t: TFunction): string {
  if (c.days_remaining === null) {
    if (c.satisfied_at) {
      return t('change_intelligence.notice.served', {
        defaultValue: 'Served {{date}}',
        date: dateOnly(c.satisfied_at),
      });
    }
    return t('change_intelligence.notice.no_deadline', { defaultValue: 'No deadline' });
  }
  const days = Math.abs(Math.round(c.days_remaining));
  if (c.days_remaining < 0) {
    return t('change_intelligence.notice.days_overdue', { defaultValue: '{{days}}d overdue', days });
  }
  return t('change_intelligence.notice.days_left', { defaultValue: '{{days}}d left', days });
}

function NoticeRegisterTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [standard, setStandard] = useState('');
  const q = useQuery({
    queryKey: ['change-intelligence', 'notice-register', projectId, standard],
    queryFn: () => getNoticeRegister(projectId, { standard: standard || undefined }),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const register = q.data;
  const summary = register?.summary;
  const clocks = register?.clocks ?? [];
  const resolvedStandard = register?.contract_standard ?? '';
  const standardLabel =
    resolvedStandard && resolvedStandard !== 'UNKNOWN'
      ? (NOTICE_STANDARD_DISPLAY[resolvedStandard] ?? humanize(resolvedStandard))
      : t('change_intelligence.notice.standard_neutral', { defaultValue: 'Standard-neutral' });

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label={t('change_intelligence.notice.tile.overdue', { defaultValue: 'Overdue' })}
          value={summary?.overdue ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.notice.tile.due_soon', { defaultValue: 'Due soon' })}
          value={summary?.due_soon ?? 0}
          tone="warning"
        />
        <StatTile
          label={t('change_intelligence.notice.tile.at_risk', { defaultValue: 'At risk' })}
          value={summary?.at_risk ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.notice.tile.proof_missing', { defaultValue: 'Proof missing' })}
          value={summary?.proof_missing ?? 0}
          tone="warning"
        />
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <label className="flex items-center gap-2 text-sm text-content-secondary">
          <span>{t('change_intelligence.notice.filter_label', { defaultValue: 'Contract standard' })}</span>
          <select
            value={standard}
            onChange={(e) => setStandard(e.target.value)}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
            aria-label={t('change_intelligence.notice.filter_label', { defaultValue: 'Contract standard' })}
          >
            {NOTICE_STANDARDS.map((s) => (
              <option key={s || 'auto'} value={s}>
                {s || t('change_intelligence.notice.filter_auto', { defaultValue: 'Project default' })}
              </option>
            ))}
          </select>
        </label>
        {register && (
          <span className="inline-flex items-center gap-2 text-xs text-content-tertiary">
            <Badge variant="neutral">{standardLabel}</Badge>
            <span>
              {t('change_intelligence.notice.amber_window', {
                defaultValue: 'Amber window {{days}}d',
                days: register.due_soon_days,
              })}
            </span>
          </span>
        )}
      </div>

      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={clocks.length === 0}
        emptyIcon={<AlarmClock className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.notice.empty_title', { defaultValue: 'No notice clocks' })}
        emptyDescription={t('change_intelligence.notice.empty_desc', {
          defaultValue:
            'There are no open changes with a notice or response deadline to track right now.',
        })}
      >
        <div className="space-y-2">
          {clocks.map((c) => (
            <Card key={`${c.source_kind}:${c.source_id}:${c.notice_type}`} className="p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={NOTICE_STATUS_VARIANT[c.status]}>{noticeStatusLabel(c.status, t)}</Badge>
                <span className="font-medium text-content-primary">
                  {c.source_ref || humanize(c.source_kind)}
                </span>
                <span className="text-xs text-content-tertiary">{noticeTypeLabel(c.notice_type, t)}</span>
                {c.entitlement_at_risk && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-semantic-error/10 px-2 py-0.5 text-2xs font-medium text-semantic-error">
                    <AlertTriangle className="h-3 w-3" />
                    {t('change_intelligence.notice.at_risk', { defaultValue: 'Entitlement at risk' })}
                  </span>
                )}
                <span className={`ml-auto text-sm font-medium ${noticeCountdownTone(c)}`}>
                  {noticeCountdown(c, t)}
                </span>
              </div>
              {c.title && <div className="mt-1 text-sm text-content-secondary">{c.title}</div>}
              <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-content-tertiary">
                <span>{humanize(c.source_kind)}</span>
                {c.clause_ref && (
                  <span>
                    {t('change_intelligence.notice.clause', {
                      defaultValue: 'Clause {{ref}}',
                      ref: c.clause_ref,
                    })}
                  </span>
                )}
                {c.deadline && (
                  <span>
                    {t('change_intelligence.notice.deadline', {
                      defaultValue: 'Deadline {{date}}',
                      date: dateOnly(c.deadline),
                    })}
                  </span>
                )}
                {c.requires_notice &&
                  (c.proof_on_file ? (
                    <span className="text-semantic-success">
                      {t('change_intelligence.notice.proof_on_file', { defaultValue: 'Notice on file' })}
                    </span>
                  ) : (
                    <span className="font-medium text-semantic-error">
                      {t('change_intelligence.notice.proof_off_file', { defaultValue: 'No notice on file' })}
                    </span>
                  ))}
                {c.served_late && (
                  <span className="text-semantic-error">
                    {t('change_intelligence.notice.served_late', { defaultValue: 'Served late' })}
                  </span>
                )}
              </div>
            </Card>
          ))}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: commitment register ("who owes the next action") -----------------

// The origins the register consolidates. Mirrors the backend SOURCE_* tokens in
// action_register.py; "rfi" would humanize to an ugly "Rfi", so the labels are
// mapped explicitly here (keyed per source for i18n, like the scope reasons).
const COMMITMENT_SOURCE_LABELS: Record<string, string> = {
  meeting_action: 'Meeting action',
  risk_action: 'Risk mitigation',
  change_order: 'Change order',
  rfi: 'RFI',
  submittal: 'Submittal',
};

function commitmentSourceLabel(source: string, t: TFunction): string {
  const fallback = COMMITMENT_SOURCE_LABELS[source];
  if (fallback) {
    return t(`change_intelligence.commitments.source.${source}`, { defaultValue: fallback });
  }
  return humanize(source);
}

function CommitmentsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'commitments', projectId],
    queryFn: () => getCommitmentRegister(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const register = q.data;
  const owners = register?.by_owner ?? [];
  const items = register?.items ?? [];
  const sourceEntries = Object.entries(register?.by_source ?? {}).filter(([, n]) => n > 0);
  const unassigned = t('change_intelligence.commitments.unassigned', { defaultValue: '(unassigned)' });
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.commitments.tile.open', { defaultValue: 'Open commitments' })}
          value={register?.total_open ?? 0}
        />
        <StatTile
          label={t('change_intelligence.commitments.tile.overdue', { defaultValue: 'Overdue' })}
          value={register?.overdue_count ?? 0}
          tone="error"
        />
        <StatTile
          label={t('change_intelligence.commitments.tile.owners', { defaultValue: 'Owners' })}
          value={owners.length}
        />
      </div>

      {sourceEntries.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-content-tertiary">
            {t('change_intelligence.commitments.by_source', { defaultValue: 'By source' })}
          </span>
          {sourceEntries.map(([source, n]) => (
            <span
              key={source}
              className="rounded-full bg-surface-secondary px-2 py-0.5 text-xs text-content-secondary"
            >
              {`${commitmentSourceLabel(source, t)}: ${n}`}
            </span>
          ))}
        </div>
      )}

      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={items.length === 0}
        emptyIcon={<ClipboardList className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.commitments.empty_title', { defaultValue: 'Nothing outstanding' })}
        emptyDescription={t('change_intelligence.commitments.empty_desc', {
          defaultValue:
            'No open meeting actions, risk mitigations, change orders or RFIs are waiting on anyone right now.',
        })}
      >
        <div className="space-y-4">
          {owners.length > 0 && (
            <Card className="overflow-hidden p-0">
              <div className="border-b border-border-light px-3 py-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('change_intelligence.commitments.owner_load_heading', { defaultValue: 'Load by owner' })}
              </div>
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
                  <tr>
                    <th className="px-3 py-2">
                      {t('change_intelligence.commitments.col.owner', { defaultValue: 'Owner' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('change_intelligence.commitments.col.open', { defaultValue: 'Open' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('change_intelligence.commitments.col.overdue', { defaultValue: 'Overdue' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {owners.map((o) => (
                    <tr key={o.owner || '(unassigned)'} className="border-t border-border-light">
                      <td className="px-3 py-2 font-medium text-content-primary">{o.owner || unassigned}</td>
                      <td className="px-3 py-2 text-right">{o.open_count}</td>
                      <td className="px-3 py-2 text-right text-semantic-error">{o.overdue_count || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          <Card className="overflow-hidden p-0">
            <div className="border-b border-border-light px-3 py-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('change_intelligence.commitments.register_heading', {
                defaultValue: 'Open commitments, overdue first',
              })}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
                  <tr>
                    <th className="px-3 py-2">
                      {t('change_intelligence.commitments.col.owner', { defaultValue: 'Owner' })}
                    </th>
                    <th className="px-3 py-2">
                      {t('change_intelligence.commitments.col.commitment', { defaultValue: 'Commitment' })}
                    </th>
                    <th className="px-3 py-2">
                      {t('change_intelligence.commitments.col.source', { defaultValue: 'Source' })}
                    </th>
                    <th className="px-3 py-2">
                      {t('change_intelligence.commitments.col.due', { defaultValue: 'Due' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('change_intelligence.commitments.col.status', { defaultValue: 'Status' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((c) => (
                    <tr
                      key={`${c.source}:${c.ref_id}`}
                      className={`border-t border-border-light ${c.overdue ? 'bg-semantic-error/5' : ''}`}
                    >
                      <td className="px-3 py-2 font-medium text-content-primary">{c.owner || unassigned}</td>
                      <td className="px-3 py-2 text-content-secondary">
                        {c.code ? <span className="font-mono text-xs text-content-tertiary">{c.code} </span> : null}
                        {c.title || t('change_intelligence.common.untitled', { defaultValue: '(untitled)' })}
                      </td>
                      <td className="px-3 py-2 text-content-secondary">{commitmentSourceLabel(c.source, t)}</td>
                      <td className="px-3 py-2 text-content-secondary">{dateOnly(c.due_date)}</td>
                      <td className="px-3 py-2 text-right">
                        {c.overdue ? (
                          <Badge variant="error">
                            {t('change_intelligence.commitments.days_overdue', {
                              defaultValue: '{{days}}d overdue',
                              days: Math.round(c.days_overdue),
                            })}
                          </Badge>
                        ) : c.age_days != null ? (
                          <span className="text-content-tertiary">
                            {t('change_intelligence.commitments.days_open', {
                              defaultValue: '{{days}}d open',
                              days: Math.round(c.age_days),
                            })}
                          </span>
                        ) : (
                          '-'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: change drivers (Pareto by cause and responsible party) -----------

/** A thin inline share bar for a Pareto row; pct is already a 0-100 percentage. */
function ShareBar({ pct }: { pct: number }) {
  const width = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-surface-secondary">
      <div className="h-full rounded bg-oe-blue/70" style={{ width: `${width}%` }} />
    </div>
  );
}

/**
 * One Pareto table: rows ranked by cost with a share bar and a running
 * cumulative percentage. The heading and the key-column label are passed in
 * (already translated) so the same table serves the by-cause and by-party cuts.
 */
function ParetoCard({
  heading,
  keyLabel,
  rows,
  currency,
}: {
  heading: string;
  keyLabel: string;
  rows: ParetoRow[];
  currency: string;
}) {
  const { t } = useTranslation();
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-border-light px-3 py-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
        {heading}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th className="px-3 py-2">{keyLabel}</th>
              <th className="px-3 py-2 text-right">
                {t('change_intelligence.drivers.col.count', { defaultValue: 'Count' })}
              </th>
              <th className="px-3 py-2 text-right">
                {t('change_intelligence.drivers.col.cost', { defaultValue: 'Cost' })}
              </th>
              <th className="px-3 py-2 text-right">
                {t('change_intelligence.drivers.col.share', { defaultValue: 'Share' })}
              </th>
              <th className="px-3 py-2 text-right">
                {t('change_intelligence.drivers.col.cumulative', { defaultValue: 'Cumulative' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-t border-border-light">
                <td className="px-3 py-2 font-medium text-content-primary">{humanize(r.key)}</td>
                <td className="px-3 py-2 text-right">{r.count}</td>
                <td className="px-3 py-2 text-right">
                  <MoneyDisplay amount={r.cost} currency={currency} showCode colorize />
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-end gap-2">
                    <span className="hidden w-16 shrink-0 sm:block">
                      <ShareBar pct={r.cost_pct} />
                    </span>
                    <span className="tabular-nums text-content-secondary">{pctNum(r.cost_pct)}</span>
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-content-tertiary">
                  {pctNum(r.cumulative_pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function DriversTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'change-drivers', projectId],
    queryFn: () => getChangeDrivers(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const data = q.data;
  const byCause = data?.by_cause ?? [];
  const byParty = data?.by_party ?? [];
  const byCurrency = data?.by_currency ?? [];
  const trend = data?.trend ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label={t('change_intelligence.drivers.tile.changes', { defaultValue: 'Changes' })}
          value={data?.total_count ?? 0}
        />
        <StatTile
          label={t('change_intelligence.drivers.tile.total_cost', { defaultValue: 'Total change cost' })}
          value={
            <MoneyDisplay amount={data?.total_cost ?? '0'} currency={data?.primary_currency} showCode colorize />
          }
        />
        <StatTile
          label={t('change_intelligence.drivers.tile.causes', { defaultValue: 'Distinct causes' })}
          value={byCause.length}
        />
      </div>

      {byCurrency.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-content-tertiary">
            {t('change_intelligence.drivers.by_currency', { defaultValue: 'Per currency' })}
          </span>
          {byCurrency.map((c) => (
            <span
              key={c.currency}
              className="inline-flex items-center gap-1 rounded border border-border-light px-1.5 py-0.5 text-xs text-content-secondary"
            >
              <MoneyDisplay amount={c.cost} currency={c.currency} showCode />
              <span className="text-content-tertiary">{`(${c.count})`}</span>
            </span>
          ))}
        </div>
      )}

      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={byCause.length === 0 && byParty.length === 0}
        emptyIcon={<BarChart3 className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.drivers.empty_title', { defaultValue: 'No change drivers yet' })}
        emptyDescription={t('change_intelligence.drivers.empty_desc', {
          defaultValue:
            'Once this project carries change orders, claims or risks, their cost is ranked here by cause and responsible party.',
        })}
      >
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <ParetoCard
              heading={t('change_intelligence.drivers.by_cause_heading', { defaultValue: 'By cause' })}
              keyLabel={t('change_intelligence.drivers.col.cause', { defaultValue: 'Cause' })}
              rows={byCause}
              currency={data?.primary_currency ?? ''}
            />
            <ParetoCard
              heading={t('change_intelligence.drivers.by_party_heading', {
                defaultValue: 'By responsible party',
              })}
              keyLabel={t('change_intelligence.drivers.col.party', { defaultValue: 'Responsible party' })}
              rows={byParty}
              currency={data?.primary_currency ?? ''}
            />
          </div>

          {trend.length > 0 && (
            <Card className="overflow-hidden p-0">
              <div className="border-b border-border-light px-3 py-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('change_intelligence.drivers.trend_heading', { defaultValue: 'Month over month' })}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
                    <tr>
                      <th className="px-3 py-2">
                        {t('change_intelligence.drivers.col.month', { defaultValue: 'Month' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('change_intelligence.drivers.col.count', { defaultValue: 'Count' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('change_intelligence.drivers.col.cost', { defaultValue: 'Cost' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {trend.map((pt) => (
                      <tr key={pt.month} className="border-t border-border-light">
                        <td className="px-3 py-2 font-medium text-content-primary">{pt.month}</td>
                        <td className="px-3 py-2 text-right">{pt.count}</td>
                        <td className="px-3 py-2 text-right">
                          <MoneyDisplay amount={pt.cost} currency={data?.primary_currency} showCode colorize />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {byCurrency.length > 1 && (
            <p className="text-xs text-content-tertiary">
              {t('change_intelligence.drivers.multi_currency', {
                defaultValue:
                  'Change cost spans {{count}} currencies; the ranking is shown in {{currency}} and currencies are never blended.',
                count: byCurrency.length,
                currency:
                  data?.primary_currency ||
                  t('change_intelligence.drivers.primary_currency_fallback', {
                    defaultValue: 'the primary currency',
                  }),
              })}
            </p>
          )}
        </div>
      </PanelState>
    </div>
  );
}

// --- Tab: change run-rate (cumulative curve + burn-rate forecast) ----------

function RunRateTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['change-intelligence', 'run-rate', projectId],
    queryFn: () => getChangeRunRate(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const data = q.data;
  const points = data?.points ?? [];
  const forecast = data?.forecast ?? null;
  // Colour the current change % by how much of the contract it has eaten.
  const currentPct = data?.current_change_pct != null ? Number(data.current_change_pct) : null;
  const changePctTone: BadgeVariant | undefined =
    currentPct != null && Number.isFinite(currentPct)
      ? currentPct >= 10
        ? 'error'
        : currentPct >= 5
          ? 'warning'
          : undefined
      : undefined;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label={t('change_intelligence.runrate.tile.contract', { defaultValue: 'Contract value' })}
          value={
            data?.original_contract_value != null ? (
              <MoneyDisplay amount={data.original_contract_value} currency={data.currency} showCode />
            ) : (
              '-'
            )
          }
        />
        <StatTile
          label={t('change_intelligence.runrate.tile.change_to_date', { defaultValue: 'Change to date' })}
          value={
            <MoneyDisplay amount={data?.total_change_value ?? '0'} currency={data?.currency} showCode colorize />
          }
        />
        <StatTile
          label={t('change_intelligence.runrate.tile.change_pct', { defaultValue: 'Change %' })}
          value={pctString(data?.current_change_pct)}
          tone={changePctTone}
        />
        <StatTile
          label={t('change_intelligence.runrate.tile.intake', { defaultValue: 'Intake / month' })}
          value={data ? fmtFixed(data.intake_rate_per_month, 1) : '0'}
        />
      </div>

      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!data || (points.length === 0 && data.change_count === 0)}
        emptyIcon={<LineChart className="h-6 w-6" />}
        emptyTitle={t('change_intelligence.runrate.empty_title', { defaultValue: 'No change to trend yet' })}
        emptyDescription={t('change_intelligence.runrate.empty_desc', {
          defaultValue:
            'Once this project carries change orders or variations, their cumulative value is tracked here against the contract.',
        })}
      >
        <div className="space-y-4">
          <Card className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                <TrendingUp className="h-4 w-4" />
              </span>
              <span className="font-semibold text-content-primary">
                {t('change_intelligence.runrate.forecast_heading', { defaultValue: 'Forecast at completion' })}
              </span>
              <Badge variant="warning">
                {t('change_intelligence.runrate.estimate', { defaultValue: 'Estimate' })}
              </Badge>
            </div>
            {forecast ? (
              <>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
                      {t('change_intelligence.runrate.forecast.final_value', {
                        defaultValue: 'Projected final change',
                      })}
                    </div>
                    <div className="mt-1 text-xl font-semibold text-content-primary">
                      <MoneyDisplay
                        amount={forecast.final_change_value}
                        currency={data?.currency}
                        showCode
                        colorize
                      />
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
                      {t('change_intelligence.runrate.forecast.final_pct', { defaultValue: 'Projected change %' })}
                    </div>
                    <div className="mt-1 text-xl font-semibold text-content-primary">
                      {pctString(forecast.final_change_pct)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
                      {t('change_intelligence.runrate.forecast.at_date', { defaultValue: 'At completion' })}
                    </div>
                    <div className="mt-1 text-xl font-semibold text-content-primary">
                      {dateOnly(forecast.at_date)}
                    </div>
                  </div>
                </div>
                <p className="mt-3 text-xs leading-relaxed text-content-tertiary">
                  {t('change_intelligence.runrate.forecast_note', {
                    defaultValue:
                      'A simple linear projection from {{elapsed}} of {{total}} days elapsed at the current run-rate. It is an estimate to aid planning, not a commitment; confirm it against the live change picture before you act on it.',
                    elapsed: forecast.elapsed_days,
                    total: forecast.total_days,
                  })}
                </p>
              </>
            ) : (
              <p className="mt-2 text-sm text-content-tertiary">
                {t('change_intelligence.runrate.forecast_unavailable', {
                  defaultValue:
                    'Not enough dated changes and a project timeline to project a completion figure yet.',
                })}
              </p>
            )}
          </Card>

          {data && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-content-tertiary">
              <span>
                {t('change_intelligence.runrate.approved_label', { defaultValue: 'Approved' })}{' '}
                <MoneyDisplay amount={data.approved_value} currency={data.currency} showCode />
              </span>
              <span>
                {t('change_intelligence.runrate.pending_label', { defaultValue: 'Pending' })}{' '}
                <MoneyDisplay amount={data.pending_value} currency={data.currency} showCode />
              </span>
              <span>
                {t('change_intelligence.runrate.pending_hint', {
                  defaultValue: 'Pending value is not yet committed and may still change.',
                })}
              </span>
            </div>
          )}

          {points.length > 0 && (
            <Card className="overflow-hidden p-0">
              <div className="border-b border-border-light px-3 py-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('change_intelligence.runrate.curve_heading', { defaultValue: 'Cumulative change by month' })}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
                    <tr>
                      <th className="px-3 py-2">
                        {t('change_intelligence.runrate.col.month', { defaultValue: 'Month' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('change_intelligence.runrate.col.approved', { defaultValue: 'Approved' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('change_intelligence.runrate.col.pending', { defaultValue: 'Pending' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('change_intelligence.runrate.col.cumulative', { defaultValue: 'Cumulative' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('change_intelligence.runrate.col.pct', { defaultValue: 'vs contract' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {points.map((p) => (
                      <tr key={p.month} className="border-t border-border-light">
                        <td className="px-3 py-2 font-medium text-content-primary">{p.month}</td>
                        <td className="px-3 py-2 text-right">
                          <MoneyDisplay amount={p.approved_value} currency={data?.currency} showCode />
                        </td>
                        <td className="px-3 py-2 text-right text-content-secondary">
                          <MoneyDisplay amount={p.pending_value} currency={data?.currency} showCode />
                        </td>
                        <td className="px-3 py-2 text-right font-medium">
                          <MoneyDisplay amount={p.cumulative_value} currency={data?.currency} showCode />
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-content-tertiary">
                          {pctString(p.change_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </PanelState>
    </div>
  );
}

// --- Page -------------------------------------------------------------------

export function ChangeIntelligencePage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectLite[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });
  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';

  const [tab, setTab] = useState<Tab>('coordination');
  const ids = tabIds('change-intel');

  return (
    <div className="space-y-5 animate-fade-in">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <BrainCircuit className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-xl font-semibold text-content-primary">
            {t('change_intelligence.title', { defaultValue: 'Change Intelligence' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('change_intelligence.subtitle', {
              defaultValue: 'What to act on first, who owes the next action, and what the changes have committed.',
            })}
          </p>
        </div>
        <ModuleGuideButton content={changeIntelligenceGuide} className="ml-auto" />
      </header>

      <DismissibleInfo
        storageKey="change-intelligence"
        title={t('change_intelligence.intro_title', { defaultValue: 'One read of your change landscape' })}
      >
        {t('change_intelligence.intro_body', {
          defaultValue:
            'These co-pilots read your change orders, variations, management-of-change entries and correspondence in one place. Rank what needs action, see who the ball sits with and how long it has waited, total the committed cost and schedule of approved changes, track what you mean to recover, and turn a rough note into a structured request.',
        })}
      </DismissibleInfo>

      {!projectId ? (
        <EmptyState
          icon={<Inbox className="h-6 w-6" />}
          title={t('change_intelligence.no_project', { defaultValue: 'No project selected' })}
          description={t('change_intelligence.no_project_desc', {
            defaultValue: 'Select a project to see its change intelligence.',
          })}
        />
      ) : (
        <>
          <TabBar
            idPrefix="change-intel"
            ariaLabel={t('change_intelligence.title', { defaultValue: 'Change Intelligence' })}
            activeId={tab}
            onChange={(next) => setTab(next as Tab)}
            tabs={[
              {
                id: 'coordination',
                label: t('change_intelligence.tab.coordination', { defaultValue: 'Act first' }),
                icon: <ListChecks className="h-4 w-4" />,
              },
              {
                id: 'cycle',
                label: t('change_intelligence.tab.cycle', { defaultValue: 'Waiting on whom' }),
                icon: <Clock className="h-4 w-4" />,
              },
              {
                id: 'commitments',
                label: t('change_intelligence.tab.commitments', { defaultValue: 'Commitments' }),
                icon: <ClipboardList className="h-4 w-4" />,
              },
              {
                id: 'comms',
                label: t('change_intelligence.tab.comms', { defaultValue: 'Correspondence' }),
                icon: <Mail className="h-4 w-4" />,
              },
              {
                id: 'impact',
                label: t('change_intelligence.tab.impact', { defaultValue: 'Impact' }),
                icon: <TrendingUp className="h-4 w-4" />,
              },
              {
                id: 'drivers',
                label: t('change_intelligence.tab.drivers', { defaultValue: 'Change drivers' }),
                icon: <BarChart3 className="h-4 w-4" />,
              },
              {
                id: 'runrate',
                label: t('change_intelligence.tab.runrate', { defaultValue: 'Run rate' }),
                icon: <LineChart className="h-4 w-4" />,
              },
              {
                id: 'recovery',
                label: t('change_intelligence.tab.recovery', { defaultValue: 'Cost recovery' }),
                icon: <Wallet className="h-4 w-4" />,
              },
              {
                id: 'dispute',
                label: t('change_intelligence.tab.dispute', { defaultValue: 'Dispute risk' }),
                icon: <Radar className="h-4 w-4" />,
              },
              {
                id: 'decision',
                label: t('change_intelligence.tab.decision', { defaultValue: 'Decision impact' }),
                icon: <Scale className="h-4 w-4" />,
              },
              {
                id: 'watch',
                label: t('change_intelligence.tab.watch', { defaultValue: 'Watch' }),
                icon: <ShieldAlert className="h-4 w-4" />,
              },
              {
                id: 'clarifier',
                label: t('change_intelligence.tab.clarifier', { defaultValue: 'Clarifier' }),
                icon: <Sparkles className="h-4 w-4" />,
              },
              {
                id: 'intake',
                label: t('change_intelligence.tab.intake', { defaultValue: 'Intake' }),
                icon: <Import className="h-4 w-4" />,
              },
              {
                id: 'delay',
                label: t('change_intelligence.tab.delay', { defaultValue: 'Delay risk' }),
                icon: <Gauge className="h-4 w-4" />,
              },
              {
                id: 'scope',
                label: t('change_intelligence.tab.scope', { defaultValue: 'Scope risk' }),
                icon: <FileSearch className="h-4 w-4" />,
              },
              {
                id: 'notice',
                label: t('change_intelligence.tab.notice', { defaultValue: 'Time bar' }),
                icon: <AlarmClock className="h-4 w-4" />,
              },
            ]}
          />
          <div role="tabpanel" id={ids.panelId(tab)} aria-labelledby={ids.tabId(tab)}>
            {tab === 'coordination' && <CoordinationTab projectId={projectId} />}
            {tab === 'cycle' && <CycleTimeTab projectId={projectId} />}
            {tab === 'commitments' && <CommitmentsTab projectId={projectId} />}
            {tab === 'comms' && <CommsTab projectId={projectId} />}
            {tab === 'impact' && <ImpactTab projectId={projectId} />}
            {tab === 'drivers' && <DriversTab projectId={projectId} />}
            {tab === 'runrate' && <RunRateTab projectId={projectId} />}
            {tab === 'recovery' && <RecoveryTab projectId={projectId} />}
            {tab === 'dispute' && <DisputeRiskTab projectId={projectId} />}
            {tab === 'decision' && <DecisionImpactTab projectId={projectId} />}
            {tab === 'watch' && <WatchTab projectId={projectId} />}
            {tab === 'clarifier' && <ClarifierTab />}
            {tab === 'intake' && <IntakeTab projectId={projectId} />}
            {tab === 'delay' && <DelayRiskTab projectId={projectId} />}
            {tab === 'scope' && <ScopeRiskTab projectId={projectId} />}
            {tab === 'notice' && <NoticeRegisterTab projectId={projectId} />}
          </div>
        </>
      )}
    </div>
  );
}

export default ChangeIntelligencePage;
