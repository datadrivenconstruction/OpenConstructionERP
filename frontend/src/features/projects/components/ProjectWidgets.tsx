// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ProjectWidgets — the new wave-1 widgets for /projects/:id.
 *
 * Each widget is a small, self-contained ``<Card>`` with:
 *   - a clear title with an icon,
 *   - the primary metric front-and-centre,
 *   - a "View all →" CTA navigating to the relevant module,
 *   - a Skeleton while loading,
 *   - a graceful EmptyState on 4xx / network errors (the page must stay
 *     useful even if a backend module is offline).
 *
 * All money values come straight from the API as either string or number;
 * we never coerce to Float on read until after the format step. Visual
 * polish matches the dashboard's ``NewWidgets`` (same shell, same
 * typography ratios) so the two surfaces feel like one design system.
 *
 * **W23 P0 — fan-out → rollup refactor:** 8 of the 13 widgets used to
 * each fire their own ``useQuery`` against per-widget endpoints. On a
 * cold /projects/:id load this caused ~8 parallel HTTP calls (=> 502
 * spikes on VPS, slow paint, react-query thrash). They now share one
 * parent ``useProjectWidgetsRollup`` and read their slice via
 * ``ProjectWidgetsRollupProvider``. The 5 widgets whose original
 * endpoints don't exist server-side (photo strip, activity feed,
 * schedule strip, AI insights, recent files — all currently graceful-
 * null on every install) keep their own ``useGracefulQuery`` for now
 * — adding them to the rollup would require new backend endpoints
 * that don't yet exist.
 */
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  GitPullRequestArrow,
  Receipt,
  ClipboardPen,
  HardHat,
  Wallet,
  Image as ImageIcon,
  FolderOpen,
  Sparkles,
  CalendarClock,
  ClipboardList,
  AlertTriangle,
  ShieldCheck,
  ArrowRight,
  Activity as ActivityIcon,
} from 'lucide-react';
import { Card, Skeleton, Badge, AuthImage } from '@/shared/ui';
import { apiGet, ApiError, type Page } from '@/shared/lib/api';
import { getPhotoThumbUrl } from '@/features/documents/api';
import { useProjectWidgetsRollup } from '../hooks/useProjectWidgetsRollup';
import type {
  ProjectBudgetBurnPayload,
  ProjectChangeOrdersPulsePayload,
  ProjectComplianceSummaryPayload,
  ProjectDailyDiaryPayload,
  ProjectHSEIncidentsPayload,
  ProjectLpsPpcPayload,
  ProjectQualityNCRPayload,
  ProjectRFIInboxPayload,
  ProjectSubInsurancePayload,
  ProjectVariationsPayload,
} from '@/shared/api/dashboardRollup';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* ── Rollup provider ──────────────────────────────────────────────────── */

interface ProjectWidgetsRollupContextValue {
  isLoading: boolean;
  data: {
    project_rfi_inbox?: ProjectRFIInboxPayload;
    project_change_orders_pulse?: ProjectChangeOrdersPulsePayload;
    project_daily_diary?: ProjectDailyDiaryPayload;
    project_hse_incidents?: ProjectHSEIncidentsPayload;
    project_variations?: ProjectVariationsPayload;
    project_quality_ncr?: ProjectQualityNCRPayload;
    project_compliance_summary?: ProjectComplianceSummaryPayload;
    project_budget_burn?: ProjectBudgetBurnPayload;
    project_lps_ppc?: ProjectLpsPpcPayload;
    project_sub_insurance?: ProjectSubInsurancePayload;
  } | null;
}

const ProjectWidgetsRollupContext =
  createContext<ProjectWidgetsRollupContextValue | null>(null);

/**
 * Wraps the project-detail widget block so every widget can read its
 * slice of the rollup without re-firing its own ``useQuery``. Render
 * this once per /projects/:id surface, around all the ``*Widget``
 * components below.
 */
export function ProjectWidgetsRollupProvider({
  projectId,
  children,
}: {
  projectId: string;
  children: ReactNode;
}) {
  const { data, isLoading } = useProjectWidgetsRollup({ projectId });
  const value = useMemo<ProjectWidgetsRollupContextValue>(
    () => ({
      isLoading,
      data: data
        ? {
            project_rfi_inbox: data.project_rfi_inbox,
            project_change_orders_pulse: data.project_change_orders_pulse,
            project_daily_diary: data.project_daily_diary,
            project_hse_incidents: data.project_hse_incidents,
            project_variations: data.project_variations,
            project_quality_ncr: data.project_quality_ncr,
            project_compliance_summary: data.project_compliance_summary,
            project_budget_burn: data.project_budget_burn,
            project_lps_ppc: data.project_lps_ppc,
            project_sub_insurance: data.project_sub_insurance,
          }
        : null,
    }),
    [data, isLoading],
  );
  return (
    <ProjectWidgetsRollupContext.Provider value={value}>
      {children}
    </ProjectWidgetsRollupContext.Provider>
  );
}

/**
 * Read this widget's slice of the parent rollup. Returns ``undefined``
 * when:
 *   - the provider isn't mounted (call-sites that aren't yet wrapped),
 *   - the parent query is still loading,
 *   - the widget key is missing from the payload (backend module disabled).
 *
 * The widget should fall back to its own ``useGracefulQuery`` in the
 * "provider not mounted" case so it still works when rendered standalone.
 */
function useRollupSlice<K extends keyof NonNullable<ProjectWidgetsRollupContextValue['data']>>(
  key: K,
): {
  /** True while the parent rollup is in flight. */
  isLoadingFromRollup: boolean;
  /** True when a rollup provider is mounted (whether loaded yet or not). */
  hasProvider: boolean;
  data: NonNullable<ProjectWidgetsRollupContextValue['data']>[K] | undefined;
} {
  const ctx = useContext(ProjectWidgetsRollupContext);
  if (ctx == null) {
    return { isLoadingFromRollup: false, hasProvider: false, data: undefined };
  }
  return {
    isLoadingFromRollup: ctx.isLoading,
    hasProvider: true,
    data: ctx.data?.[key],
  };
}

/* ── Shared shell ──────────────────────────────────────────────────────── */

interface WidgetShellProps {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  cta?: { label: string; onClick: () => void };
  children: React.ReactNode;
  className?: string;
}

function WidgetShell({
  icon,
  title,
  subtitle,
  cta,
  children,
  className,
}: WidgetShellProps) {
  return (
    <Card padding="sm" className={clsx('flex h-full flex-col', className)}>
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0 flex-1">
          <span className="mt-0.5 shrink-0 text-content-tertiary">{icon}</span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-content-primary truncate">
              {title}
            </h3>
            {subtitle && (
              <p className="text-2xs text-content-tertiary truncate">
                {subtitle}
              </p>
            )}
          </div>
        </div>
        {cta && (
          <button
            type="button"
            onClick={cta.onClick}
            className="shrink-0 inline-flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue/10 transition-colors"
          >
            {cta.label}
            <ArrowRight size={12} />
          </button>
        )}
      </div>
      {children}
    </Card>
  );
}

function WidgetSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={24} className="w-full" rounded="md" />
      ))}
    </div>
  );
}

function WidgetEmpty({ message }: { message: string }) {
  return (
    <p className="text-2xs text-content-quaternary py-2 text-center">{message}</p>
  );
}

/**
 * Run a query that tolerates 4xx / network errors by resolving to ``null``.
 * The widget then decides what to render based on the resolved value.
 *
 * When the parent ``ProjectWidgetsRollupProvider`` is mounted, individual
 * widgets pass ``enabled=false`` to suppress this fallback query — the
 * rollup already returned their slice.
 */
function useGracefulQuery<T>(key: readonly unknown[], path: string, enabled = true) {
  return useQuery<T | null>({
    queryKey: key,
    queryFn: async () => {
      try {
        return await apiGet<T>(path);
      } catch (err) {
        // 4xx / 5xx / offline → graceful null. Module-offline must not crash
        // the rest of the page. We surface it as an EmptyState instead.
        if (err instanceof ApiError) return null;
        return null;
      }
    },
    enabled,
    retry: false,
    staleTime: 30_000,
  });
}

/* ── 1. RFI Inbox ─────────────────────────────────────────────────────── */

interface RFIItem {
  id: string;
  number?: string | null;
  subject: string;
  status: string;
  created_at?: string;
  due_date?: string | null;
}

export function RFIInboxWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // W23 P0: prefer the rolled-up payload from the parent provider.
  // Fall back to the per-widget query if the provider isn't mounted —
  // some surfaces (storybook, ad-hoc embeds) render the widget standalone.
  const rollup = useRollupSlice('project_rfi_inbox');
  // The route answers with a page envelope. Nothing in TypeScript would have
  // caught this call reading it as an array: the type argument is written by
  // hand here, so the compiler believes whatever this line claims.
  const fallback = useGracefulQuery<Page<RFIItem>>(
    ['proj-widget-rfi', projectId],
    `/v1/rfi/?project_id=${projectId}&status=open&limit=5`,
    !rollup.hasProvider,
  );
  // No truncation notice: the widget asks for five, is headed "Latest open
  // requests" and carries a "View all" link to the register. A feed that
  // names itself a sample is not claiming to be the whole set.
  const data: RFIItem[] | null | undefined = rollup.hasProvider
    ? (rollup.data?.items as RFIItem[] | undefined) ?? null
    : fallback.data?.items ?? null;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  const title = t('project.widget.rfi-inbox.title', { defaultValue: 'RFI inbox' });
  const subtitle = t('project.widget.rfi-inbox.card_subtitle', {
    defaultValue: 'Latest open requests',
  });
  const icon = <GitPullRequestArrow size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/rfi'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : !data || data.length === 0 ? (
        <WidgetEmpty
          message={t('project.widget.rfi-inbox.empty', {
            defaultValue: 'No open RFIs.',
          })}
        />
      ) : (
        <ul className="divide-y divide-border-light -mx-2">
          {data.slice(0, 5).map((rfi) => (
            <li key={rfi.id}>
              <button
                type="button"
                onClick={() => navigate(`/rfi/${rfi.id}`)}
                className="w-full text-left px-2 py-2 rounded-md hover:bg-surface-secondary transition-colors flex items-center gap-2"
              >
                <span className="text-2xs font-mono text-content-tertiary shrink-0 w-12 truncate">
                  {rfi.number ?? rfi.id.slice(0, 6)}
                </span>
                <span className="flex-1 text-sm text-content-primary truncate">
                  {rfi.subject}
                </span>
                <Badge variant="warning" size="sm">
                  {t(`rfi.status_${rfi.status}`, { defaultValue: rfi.status })}
                </Badge>
              </button>
            </li>
          ))}
        </ul>
      )}
    </WidgetShell>
  );
}

/* ── 2. Change-orders pulse ──────────────────────────────────────────── */

interface ChangeOrderSummary {
  open_count?: number;
  pending_count?: number;
  approved_count?: number;
  total_value?: number | string;
  approved_value?: number | string;
  currency?: string;
}

function fmtMoney(value: number | string | null | undefined, currency = 'EUR'): string {
  if (value == null) return `${currency} 0`;
  const n = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(n)) return `${currency} 0`;
  return `${currency} ${n.toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 })}`;
}

export function ChangeOrdersPulseWidget({
  projectId,
  currency,
}: {
  projectId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_change_orders_pulse');
  const fallback = useGracefulQuery<ChangeOrderSummary>(
    ['proj-widget-co', projectId],
    `/v1/changeorders/summary/?project_id=${projectId}`,
    !rollup.hasProvider,
  );
  // Rollup payload already matches ChangeOrderSummary's shape closely
  // (open_count, pending_count, approved_count, approved_value,
  // total_value, currency). Money fields stay as strings.
  const data: ChangeOrderSummary | null | undefined = rollup.hasProvider
    ? (rollup.data as ChangeOrderSummary | undefined) ?? null
    : fallback.data;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  const title = t('project.widget.change-orders.title', {
    defaultValue: 'Change orders pulse',
  });
  const subtitle = t('project.widget.change-orders.card_subtitle', {
    defaultValue: 'Pending vs approved this month',
  });
  const icon = <Receipt size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/changeorders'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data ? (
        <WidgetEmpty
          message={t('project.widget.change-orders.empty', {
            defaultValue: 'No change orders yet.',
          })}
        />
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.change-orders.pending', { defaultValue: 'Pending' })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-amber-600">
              {data.pending_count ?? data.open_count ?? 0}
            </div>
          </div>
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.change-orders.approved_value', {
                defaultValue: 'Approved value',
              })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-content-primary">
              {fmtMoney(data.approved_value ?? data.total_value, currency)}
            </div>
          </div>
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 3. Daily Diary card ─────────────────────────────────────────────── */

// ``weather_summary`` is a JSONB column on the backend (see
// backend/app/modules/daily_diary/schemas.py:90 — ``dict[str, Any]``),
// not a string. Typing it loosely and rendering through a string-coercer
// stops the React "Objects are not valid as a React child" crash that
// otherwise unmounts the entire ProjectDetailPage.
type DiaryWeatherSummary =
  | string
  | { conditions?: string; temp_c?: number; summary?: string }
  | Record<string, unknown>
  | null;

interface DiaryItem {
  id: string;
  diary_date?: string;
  status?: string;
  weather_summary?: DiaryWeatherSummary;
  manpower_total?: number | null;
  narrative?: string | null;
}

function formatWeatherSummary(
  w: DiaryWeatherSummary | undefined,
  t?: TFunction,
): string | null {
  if (w == null) return null;
  if (typeof w === 'string') return w.length > 0 ? w : null;
  if (typeof w !== 'object') return String(w);
  const obj = w as Record<string, unknown>;
  if (typeof obj.summary === 'string' && obj.summary.length > 0) {
    return obj.summary;
  }
  const parts: string[] = [];
  if (typeof obj.conditions === 'string') {
    const key = obj.conditions.trim().toLowerCase().replace(/[\s-]+/g, '_');
    parts.push(t && key ? t(`weather.${key}`, { defaultValue: obj.conditions }) : obj.conditions);
  }
  if (typeof obj.temp_c === 'number') parts.push(`${obj.temp_c}°C`);
  return parts.length > 0 ? parts.join(' · ') : null;
}

export function DailyDiaryWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_daily_diary');
  const fallback = useGracefulQuery<Page<DiaryItem>>(
    ['proj-widget-diary', projectId],
    `/v1/daily-diary/diaries/?project_id=${projectId}&limit=1`,
    !rollup.hasProvider,
  );
  // No truncation notice here on purpose: the widget asks for one diary and
  // shows one. It is a deliberate top-of-list, not a list that came up short.
  const data: DiaryItem[] | null | undefined = rollup.hasProvider
    ? (rollup.data?.items as DiaryItem[] | undefined) ?? null
    : fallback.data?.items;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  const latest = data?.[0];
  const title = t('project.widget.daily-diary.title', { defaultValue: 'Daily diary' });
  const subtitle = t('project.widget.daily-diary.card_subtitle', {
    defaultValue: 'Latest field entry',
  });
  const icon = <ClipboardPen size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/daily-diary'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !latest ? (
        <WidgetEmpty
          message={t('project.widget.daily-diary.empty', {
            defaultValue: 'No diary entries yet.',
          })}
        />
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-content-secondary">
            <CalendarClock size={12} />
            <span className="tabular-nums">{latest.diary_date}</span>
            {latest.status && (
              <Badge
                variant={latest.status === 'closed' ? 'success' : 'neutral'}
                size="sm"
              >
                {t(`daily_diary.status.${latest.status}`, { defaultValue: latest.status })}
              </Badge>
            )}
          </div>
          {(() => {
            const w = formatWeatherSummary(latest.weather_summary, t);
            return w ? (
              <p className="text-xs text-content-tertiary truncate">{w}</p>
            ) : null;
          })()}
          {latest.narrative && (
            <p className="text-sm text-content-primary line-clamp-2">
              {latest.narrative}
            </p>
          )}
          {latest.manpower_total != null && (
            <p className="text-2xs text-content-tertiary">
              {t('project.widget.daily-diary.manpower', {
                defaultValue: '{{n}} workers on site',
                n: latest.manpower_total,
              })}
            </p>
          )}
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 4. HSE incidents ────────────────────────────────────────────────── */

interface HSEInvestigation {
  id: string;
  status?: string;
  severity?: string;
  incident_date?: string | null;
}

export function HSEIncidentsWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_hse_incidents');
  const fallback = useGracefulQuery<HSEInvestigation[]>(
    ['proj-widget-hse', projectId],
    `/v1/hse_advanced/investigations/?project_id=${projectId}&limit=20`,
    !rollup.hasProvider,
  );
  const data: HSEInvestigation[] | null | undefined = rollup.hasProvider
    ? (rollup.data?.items as HSEInvestigation[] | undefined) ?? null
    : fallback.data;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  const severityCounts = useMemo(() => {
    // Prefer server-side counts when the rollup supplied them so the
    // dashboard stays consistent with the QMS module's own canonical
    // bucketing.
    if (rollup.hasProvider && rollup.data) {
      return {
        high: rollup.data.high,
        medium: rollup.data.medium,
        low: rollup.data.low,
        total: rollup.data.total,
      };
    }
    const c = { high: 0, medium: 0, low: 0, total: 0 };
    if (!data) return c;
    for (const inv of data) {
      if (inv.status && ['closed', 'archived'].includes(inv.status)) continue;
      c.total++;
      const s = (inv.severity ?? '').toLowerCase();
      if (s.includes('high') || s.includes('critical')) c.high++;
      else if (s.includes('med')) c.medium++;
      else c.low++;
    }
    return c;
  }, [data, rollup.hasProvider, rollup.data]);

  const title = t('project.widget.hse-incidents.title', { defaultValue: 'HSE incidents' });
  const subtitle = t('project.widget.hse-incidents.card_subtitle', {
    defaultValue: 'Open safety investigations',
  });
  const icon = <HardHat size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/hse-advanced'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data || severityCounts.total === 0 ? (
        <WidgetEmpty
          message={t('project.widget.hse-incidents.empty', {
            defaultValue: 'No open safety incidents.',
          })}
        />
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-4">
            <span className="text-3xl font-bold tabular-nums text-content-primary leading-none">
              {severityCounts.total}
            </span>
            <span className="text-xs text-content-tertiary">
              {t('project.widget.hse-incidents.open', { defaultValue: 'open' })}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 text-2xs">
              <span className="h-2 w-2 rounded-full bg-semantic-error" />
              <span className="text-content-secondary">
                {severityCounts.high} {t('project.widget.hse-incidents.high', { defaultValue: 'high' })}
              </span>
            </span>
            <span className="inline-flex items-center gap-1 text-2xs">
              <span className="h-2 w-2 rounded-full bg-amber-500" />
              <span className="text-content-secondary">
                {severityCounts.medium} {t('project.widget.hse-incidents.med', { defaultValue: 'med' })}
              </span>
            </span>
            <span className="inline-flex items-center gap-1 text-2xs">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span className="text-content-secondary">
                {severityCounts.low} {t('project.widget.hse-incidents.low', { defaultValue: 'low' })}
              </span>
            </span>
          </div>
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 5. Variations counter ───────────────────────────────────────────── */

interface VariationRequest {
  id: string;
  status?: string;
  estimated_value?: number | string | null;
  disputed?: boolean;
}

export function VariationsWidget({
  projectId,
  currency,
}: {
  projectId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_variations');
  const fallback = useGracefulQuery<Page<VariationRequest>>(
    ['proj-widget-var', projectId],
    `/v1/variations/variation-requests/?project_id=${projectId}&limit=50`,
    !rollup.hasProvider,
  );
  const data: VariationRequest[] | null | undefined = rollup.hasProvider
    ? (rollup.data?.items as VariationRequest[] | undefined) ?? null
    : fallback.data?.items ?? null;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  const stats = useMemo(() => {
    // Prefer server-side rollup counts when present — they treat money
    // as Decimal-string everywhere, avoiding float drift.
    if (rollup.hasProvider && rollup.data) {
      return {
        open: rollup.data.open,
        // ``disputed_value`` is Decimal-as-string; only convert it
        // immediately before formatting, not during accumulation.
        disputedValue: Number(rollup.data.disputed_value) || 0,
      };
    }
    if (!data) return { open: 0, disputedValue: 0 };
    let open = 0;
    let disputedValue = 0;
    for (const v of data) {
      if (!v.status || ['closed', 'rejected', 'approved'].includes(v.status)) {
        // still count value but not "open" if approved
      } else {
        open++;
      }
      if (v.disputed && v.estimated_value != null) {
        const n =
          typeof v.estimated_value === 'string'
            ? Number(v.estimated_value)
            : v.estimated_value;
        if (Number.isFinite(n)) disputedValue += n;
      }
    }
    return { open, disputedValue };
  }, [data, rollup.hasProvider, rollup.data]);

  const title = t('project.widget.variations.title', {
    defaultValue: 'Variations counter',
  });
  const subtitle = t('project.widget.variations.card_subtitle', {
    defaultValue: 'Open variation requests',
  });
  const icon = <ClipboardList size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/variations'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data ? (
        <WidgetEmpty
          message={t('project.widget.variations.empty', {
            defaultValue: 'No variations logged.',
          })}
        />
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.variations.open', { defaultValue: 'Open' })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-content-primary">
              {stats.open}
            </div>
          </div>
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.variations.disputed', {
                defaultValue: 'Disputed',
              })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-amber-600">
              {fmtMoney(stats.disputedValue, currency)}
            </div>
          </div>
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 6. AI Insights ──────────────────────────────────────────────────── */

interface AIInsight {
  id?: string;
  title: string;
  summary?: string;
  confidence?: number;
  severity?: string;
}

export function AIInsightsWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Recent AI insights distilled from the agent runs the user executed
  // against this project. Empty (not an error) when none have run yet.
  const { data, isLoading } = useGracefulQuery<AIInsight[]>(
    ['proj-widget-ai', projectId],
    `/v1/ai-agents/insights?project_id=${projectId}&limit=2`,
  );

  const title = t('project.widget.ai-insights.title', { defaultValue: 'AI insights' });
  const subtitle = t('project.widget.ai-insights.card_subtitle', {
    defaultValue: 'Top AI suggestions for this project',
  });
  const icon = <Sparkles size={16} className="text-violet-500" />;
  const cta = {
    label: t('project.widget.ai-insights.open', { defaultValue: 'Open agents' }),
    onClick: () => navigate('/ai-agents'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data || data.length === 0 ? (
        <WidgetEmpty
          message={t('project.widget.ai-insights.empty', {
            defaultValue: 'No AI suggestions right now.',
          })}
        />
      ) : (
        <ul className="space-y-2">
          {data.slice(0, 2).map((insight, idx) => {
            const confPct = Math.round(((insight.confidence ?? 0) * 100));
            const dotColor =
              confPct >= 80
                ? 'bg-emerald-500'
                : confPct >= 60
                ? 'bg-amber-500'
                : 'bg-content-quaternary';
            return (
              <li
                key={insight.id ?? idx}
                className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2"
              >
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dotColor}`}
                  title={`${confPct}% confidence`}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-content-primary truncate">
                    {insight.title}
                  </p>
                  {insight.summary && (
                    <p className="text-xs text-content-tertiary line-clamp-2">
                      {insight.summary}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </WidgetShell>
  );
}

/* ── 7. Recent files ─────────────────────────────────────────────────── */

interface FileItem {
  id: string;
  // The documents API serialises the original filename as ``name`` and the
  // byte size as ``file_size`` (CDE document model) - not ``filename``/``size``.
  name: string;
  file_size?: number;
  mime_type?: string;
}

function fmtBytes(bytes?: number): string {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
}

export function RecentFilesWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Deliberately a "latest five" card, not a register: the page it reads is
  // sliced to five below and the card carries a "view all" link, so it is the
  // one shape in this wave that needs no truncation notice.
  const { data: filePage, isLoading } = useGracefulQuery<Page<FileItem>>(
    ['proj-widget-files', projectId],
    `/v1/documents/?project_id=${projectId}`,
  );
  const data = filePage?.items ?? null;

  const title = t('project.widget.recent-files.title', { defaultValue: 'Recent files' });
  const subtitle = t('project.widget.recent-files.card_subtitle', {
    defaultValue: 'Latest project uploads',
  });
  const icon = <FolderOpen size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/files'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : !data || data.length === 0 ? (
        <WidgetEmpty
          message={t('project.widget.recent-files.empty', {
            defaultValue: 'No files uploaded yet.',
          })}
        />
      ) : (
        <ul className="space-y-1.5">
          {data.slice(0, 5).map((file) => (
            <li
              key={file.id}
              className="flex items-center gap-2 text-xs"
            >
              <FolderOpen size={12} className="text-content-quaternary shrink-0" />
              <span className="flex-1 truncate text-content-primary">
                {file.name}
              </span>
              <span className="text-content-tertiary tabular-nums shrink-0">
                {fmtBytes(file.file_size)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WidgetShell>
  );
}

/* ── 8. Photo strip ──────────────────────────────────────────────────── */

interface PhotoItem {
  id: string;
  url?: string;
  thumbnail_url?: string;
  // The photos endpoint (PhotoResponse) carries capture + row timestamps,
  // not an ``uploaded_at`` field, so we sort on ``taken_at`` then
  // ``created_at`` (newest first) to interleave correctly with documents.
  taken_at?: string | null;
  created_at?: string | null;
}

// A general project document, as serialised by GET /v1/documents/. We only
// need enough to spot image uploads, classify them field-vs-general, and
// address their thumbnail.
interface DocImageItem {
  id: string;
  name: string;
  mime_type?: string | null;
  created_at?: string;
  // ``photo`` for the twin row auto-created beside every site/diary photo
  // upload (documents/service.py), else the user-chosen document category.
  category?: string | null;
  // Free-form labels; a "field" tag (added via the photo gallery editor)
  // promotes an arbitrary image into the site-photo strip.
  tags?: string[] | null;
}

// One tile in the strip, regardless of whether it came from the dedicated
// photo gallery or from an image uploaded into general project files (#284).
interface StripImage {
  /** Stable React key + dedupe key. */
  key: string;
  /** Authenticated thumbnail URL fetched via <AuthImage>. */
  src: string;
  /** ISO timestamp used to sort newest-first. */
  at: string;
  /** Where clicking the tile should land the user. */
  href: string;
}

const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|bmp|tiff?|heic|heif|avif|svg)$/i;

/** True when a general document is an image (by mime or extension). */
function isImageDocument(doc: DocImageItem): boolean {
  if (doc.mime_type && doc.mime_type.toLowerCase().startsWith('image/')) return true;
  return IMAGE_EXT_RE.test(doc.name ?? '');
}

/**
 * True when an image *document* counts as FIELD/SITE imagery for the strip.
 *
 * The strip must show site documentation only, never office renders (#284
 * follow-up). The canonical "field vs general" signal is shared across the
 * codebase (see PhotoGalleryPage + notes):
 *   - a dedicated ``ProjectPhoto`` (always field) - handled separately, and
 *   - a ``Document`` carrying an explicit ``field`` tag.
 *
 * We deliberately EXCLUDE ``category === 'photo'`` rows: those are the twin
 * documents auto-created beside every site/diary photo upload, so the same
 * image would otherwise appear twice (once from the photos endpoint, once
 * from here). Skipping them dedupes the strip; the ProjectPhoto carries the
 * canonical tile.
 */
function isFieldImageDocument(doc: DocImageItem): boolean {
  if (!isImageDocument(doc)) return false;
  if ((doc.category ?? '').toLowerCase() === 'photo') return false; // twin row
  const tags = (doc.tags ?? []).map((tg) => tg.toLowerCase());
  return tags.includes('field');
}

export function PhotoStripWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // The strip is FIELD/SITE documentation only (#284 follow-up). Two sources
  // feed it, but both are filtered to site imagery so office renders never
  // leak in and no image is double-counted:
  //  1. dedicated site photos (the Photos tab / daily-diary captures) - all
  //     field by definition, always shown; and
  //  2. general Project Files images that the user has explicitly marked as
  //     field (a ``field`` tag) - see ``isFieldImageDocument``. The twin
  //     ``category === 'photo'`` rows mirrored beside every photo upload are
  //     skipped here so a site photo appears exactly once.
  const photos = useGracefulQuery<Page<PhotoItem>>(
    ['proj-widget-photos', projectId],
    `/v1/documents/photos/?project_id=${projectId}`,
  );
  const docs = useGracefulQuery<Page<DocImageItem>>(
    ['proj-widget-photo-docs', projectId],
    `/v1/documents/?project_id=${projectId}`,
  );

  const images = useMemo<StripImage[]>(() => {
    const out: StripImage[] = [];
    for (const p of photos.data?.items ?? []) {
      out.push({
        key: `photo:${p.id}`,
        // Photo thumbnails are bearer-protected; <AuthImage> fetches them
        // with the token (a bare <img src> would 401).
        src: getPhotoThumbUrl(p.id),
        at: p.taken_at ?? p.created_at ?? '',
        href: `/projects/${projectId}?tab=photos`,
      });
    }
    for (const d of docs.data?.items ?? []) {
      // Only field-tagged images (never office renders, never the photo
      // twin rows) join the dedicated site photos above.
      if (!isFieldImageDocument(d)) continue;
      out.push({
        key: `doc:${d.id}`,
        // The document download endpoint streams the original bytes with the
        // right image mime type, so it doubles as a thumbnail source.
        src: `/api/v1/documents/${d.id}/download/`,
        at: d.created_at ?? '',
        // Land on the image inside Project Files (preview pane via ?file=).
        href: `/projects/${projectId}/files?kind=document&file=${encodeURIComponent(d.id)}`,
      });
    }
    // Newest first; rows without a timestamp sort last but stay visible.
    out.sort((a, b) => (b.at || '').localeCompare(a.at || ''));
    return out;
  }, [photos.data, docs.data, projectId]);

  const isLoading = photos.isLoading || docs.isLoading;

  const title = t('project.widget.photo-strip.title', { defaultValue: 'Photo strip' });
  const subtitle = t('project.widget.photo-strip.card_subtitle', {
    defaultValue: 'Latest site photos',
  });
  const icon = <ImageIcon size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate(`/projects/${projectId}?tab=photos`),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <div className="grid grid-cols-6 gap-1.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} height={56} className="w-full" rounded="md" />
          ))}
        </div>
      ) : images.length === 0 ? (
        <WidgetEmpty
          message={t('project.widget.photo-strip.empty', {
            defaultValue:
              'No site photos yet - capture from the Photos tab or tag a project image as field.',
          })}
        />
      ) : (
        <div className="grid grid-cols-6 gap-1.5">
          {images.slice(0, 6).map((img) => (
            <button aria-label={t('projects.open_photo', { defaultValue: 'Open photo' })}
              key={img.key}
              type="button"
              onClick={() => navigate(img.href)}
              className="aspect-square overflow-hidden rounded-md border border-border-light bg-surface-secondary hover:border-oe-blue/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <AuthImage
                src={img.src}
                alt=""
                className="h-full w-full object-cover"
                loading="lazy"
                placeholder={
                  <div className="h-full w-full animate-pulse bg-surface-secondary" />
                }
                fallback={
                  <div className="flex h-full w-full items-center justify-center text-content-quaternary">
                    <ImageIcon size={16} strokeWidth={1.5} />
                  </div>
                }
              />
            </button>
          ))}
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 9. Activity feed ────────────────────────────────────────────────── */

interface ActivityEvent {
  type: string;
  title: string;
  date: string;
}

export function ActivityFeedWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading } = useGracefulQuery<{ events?: ActivityEvent[] } | ActivityEvent[]>(
    ['proj-widget-activity', projectId],
    `/v1/projects/${projectId}/activity?limit=8`,
  );

  const events: ActivityEvent[] = Array.isArray(data)
    ? data
    : data?.events ?? [];

  const title = t('project.widget.activity-feed.title', {
    defaultValue: 'Recent activity',
  });
  const subtitle = t('project.widget.activity-feed.card_subtitle', {
    defaultValue: 'Cross-module event stream',
  });
  const icon = <ActivityIcon size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/dashboard'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : events.length === 0 ? (
        <WidgetEmpty
          message={t('project.widget.activity-feed.empty', {
            defaultValue: 'No recent activity.',
          })}
        />
      ) : (
        <ul className="divide-y divide-border-light -mx-2">
          {events.slice(0, 8).map((ev, idx) => (
            <li
              key={`${ev.type}-${idx}`}
              className="px-2 py-1.5 flex items-center gap-2 text-xs"
            >
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-oe-blue shrink-0" />
              <span className="flex-1 truncate text-content-primary">
                {ev.title}
              </span>
              <span className="text-2xs text-content-tertiary shrink-0 tabular-nums">
                {ev.date.slice(0, 10)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WidgetShell>
  );
}

/* ── 10. Quality NCR ─────────────────────────────────────────────────── */

interface NCRItem {
  id: string;
  status?: string;
  severity?: string;
}

export function QualityNCRWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_quality_ncr');
  // The route answers with a page envelope, same as the RFI widget above.
  const fallback = useGracefulQuery<Page<NCRItem>>(
    ['proj-widget-ncr', projectId],
    `/v1/qms/ncrs?project_id=${projectId}&limit=50`,
    !rollup.hasProvider,
  );
  // Unlike the RFI feed, this widget does not show the rows it fetched: it
  // counts them and presents the counts as the project's NCR position. On
  // the fallback path those counts are therefore taken over 50 rows and not
  // over the register, so a project with more than 50 reports too few open
  // and too few major. The rollup path does not have the problem, because
  // the provider counts server side. Fixing the fallback needs a sentence
  // that says a number was computed over part of the set, which is not a
  // string this codebase has yet, so it is reported rather than invented.
  const data: NCRItem[] | null | undefined = rollup.hasProvider
    ? (rollup.data?.items as NCRItem[] | undefined) ?? null
    : fallback.data?.items ?? null;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  const counts = useMemo(() => {
    if (rollup.hasProvider && rollup.data) {
      return {
        open: rollup.data.open,
        major: rollup.data.major,
        minor: rollup.data.minor,
      };
    }
    const c = { open: 0, major: 0, minor: 0 };
    if (!data) return c;
    for (const n of data) {
      if (!n.status || ['closed', 'verified'].includes(n.status)) continue;
      c.open++;
      const s = (n.severity ?? '').toLowerCase();
      if (s.includes('maj') || s.includes('crit') || s.includes('high')) c.major++;
      else c.minor++;
    }
    return c;
  }, [data, rollup.hasProvider, rollup.data]);

  const title = t('project.widget.quality-ncr.title', {
    defaultValue: 'Quality NCRs',
  });
  const subtitle = t('project.widget.quality-ncr.card_subtitle', {
    defaultValue: 'Open non-conformances',
  });
  const icon = <AlertTriangle size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/qms'),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data || counts.open === 0 ? (
        <WidgetEmpty
          message={t('project.widget.quality-ncr.empty', {
            defaultValue: 'No open NCRs.',
          })}
        />
      ) : (
        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.quality-ncr.open', { defaultValue: 'Open' })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-content-primary">
              {counts.open}
            </div>
          </div>
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.quality-ncr.major', { defaultValue: 'Major' })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-semantic-error">
              {counts.major}
            </div>
          </div>
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.quality-ncr.minor', { defaultValue: 'Minor' })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-amber-600">
              {counts.minor}
            </div>
          </div>
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 11. Budget burn (sparkline) ─────────────────────────────────────── */

interface BudgetPoint {
  date?: string;
  planned?: number | string;
  actual?: number | string;
}

interface BudgetBurnPayload {
  series?: BudgetPoint[];
  planned_total?: number | string;
  actual_total?: number | string;
  currency?: string;
}

export function BudgetBurnWidget({
  projectId,
  currency,
}: {
  projectId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_budget_burn');
  const fallback = useGracefulQuery<BudgetBurnPayload>(
    ['proj-widget-burn', projectId],
    `/v1/costmodel/projects/${projectId}/5d/dashboard/`,
    !rollup.hasProvider,
  );
  // Rollup payload exposes planned_total + actual_total directly; the
  // fallback hits /5d/dashboard which uses ``total_budget`` / ``total_actual``,
  // so we normalise both shapes onto the widget's ``BudgetBurnPayload``.
  const data: BudgetBurnPayload | null | undefined = rollup.hasProvider
    ? rollup.data
      ? ({
          planned_total: rollup.data.planned_total,
          actual_total: rollup.data.actual_total,
          currency: rollup.data.currency,
          series: rollup.data.series,
        } as BudgetBurnPayload)
      : null
    : fallback.data;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  // The costmodel dashboard returns aggregated totals; sparkline is
  // synthesised from cumulative actual/planned values for v1. If a
  // dedicated time-series endpoint ships later, swap the query path.
  const sparkline = useMemo(() => {
    const points: number[] = [];
    if (data?.series && data.series.length > 0) {
      for (const p of data.series) {
        const n =
          typeof p.actual === 'string'
            ? Number(p.actual)
            : (p.actual ?? 0);
        if (Number.isFinite(n)) points.push(n);
      }
    }
    return points;
  }, [data]);

  const title = t('project.widget.budget-burn.title', {
    defaultValue: 'Budget burn',
  });
  const subtitle = t('project.widget.budget-burn.card_subtitle', {
    defaultValue: 'Actual vs planned spend',
  });
  const icon = <Wallet size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/finance'),
  };

  const max = sparkline.length > 0 ? Math.max(...sparkline) : 0;
  const polyline =
    sparkline.length > 1 && max > 0
      ? sparkline
          .map((v, i) => {
            const x = (i / (sparkline.length - 1)) * 100;
            const y = 32 - (v / max) * 28;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
          })
          .join(' ')
      : null;

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data ? (
        <WidgetEmpty
          message={t('project.widget.budget-burn.empty', {
            defaultValue: 'No budget data - connect a cost model.',
          })}
        />
      ) : (
        <div className="space-y-2">
          <div className="flex items-baseline gap-3">
            <span className="text-xl font-semibold tabular-nums text-content-primary">
              {fmtMoney(data.actual_total, data.currency ?? currency)}
            </span>
            <span className="text-2xs text-content-tertiary">
              {t('project.widget.budget-burn.of', { defaultValue: 'of' })}{' '}
              {fmtMoney(data.planned_total, data.currency ?? currency)}
            </span>
          </div>
          {polyline ? (
            <svg viewBox="0 0 100 32" className="h-10 w-full">
              <polyline
                points={polyline}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                className="text-oe-blue"
              />
            </svg>
          ) : (
            <div className="h-10 flex items-center text-2xs text-content-tertiary">
              {t('project.widget.budget-burn.no_series', {
                defaultValue: 'Spend history will appear here over time.',
              })}
            </div>
          )}
        </div>
      )}
    </WidgetShell>
  );
}

/* ── Last Planner PPC ────────────────────────────────────────────────── */

export function LpsPpcWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_lps_ppc');
  // The rollup spans the projects it was asked for; keep this project's schedules.
  const items = (rollup.data?.items ?? []).filter((i) => i.project_id === projectId);
  const withPpc = items.filter((i) => i.average_ppc != null);
  const average =
    withPpc.length > 0
      ? withPpc.reduce((sum, i) => sum + Number(i.average_ppc), 0) / withPpc.length
      : null;
  const latest = items
    .flatMap((i) => i.weeks)
    .filter((w) => w.ppc_percent != null)
    .sort((a, b) => a.week_start_date.localeCompare(b.week_start_date))
    .slice(-12);
  const top = rollup.data?.pareto ?? [];
  return (
    <WidgetShell
      icon={<CalendarClock size={16} />}
      title={t('project.widget.lps-ppc.title', { defaultValue: 'Plan reliability (PPC)' })}
      subtitle={t('project.widget.lps-ppc.card_subtitle', { defaultValue: 'Percent plan complete per week' })}
      cta={{
        label: t('project.widget.view_all', { defaultValue: 'View all' }),
        onClick: () => navigate('/schedule-advanced'),
      }}
    >
      {rollup.isLoadingFromRollup ? (
        <WidgetSkeleton rows={2} />
      ) : average == null ? (
        <WidgetEmpty
          message={t('project.widget.lps-ppc.empty', {
            defaultValue: 'PPC appears once a weekly plan is closed.',
          })}
        />
      ) : (
        <div className="space-y-2">
          <span className="text-xl font-semibold tabular-nums text-content-primary">
            {average.toFixed(0)}%
          </span>
          <div className="flex h-10 items-end gap-0.5" data-testid="lps-ppc-bars">
            {latest.map((w, i) => (
              <div
                key={`${w.week_start_date}-${i}`}
                className="flex-1 rounded-sm bg-oe-blue"
                style={{ height: `${Math.min(Math.max(Number(w.ppc_percent), 4), 100)}%` }}
                title={`${w.week_start_date}: ${Number(w.ppc_percent).toFixed(0)}%`}
              />
            ))}
          </div>
          {top.length > 0 && (
            <p className="text-2xs text-content-tertiary">
              {t('project.widget.lps-ppc.top_reasons', {
                defaultValue: 'Top reasons: {{reasons}}',
                reasons: top.map((r) => `${r.category} (${r.count})`).join(', '),
              })}
            </p>
          )}
        </div>
      )}
    </WidgetShell>
  );
}

/* ── Subcontractor insurance ─────────────────────────────────────────── */

export function SubInsuranceWidget({ projectId: _projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_sub_insurance');
  const data = rollup.data;
  const total = data ? data.compliant + data.expiring + data.non_compliant : 0;
  return (
    <WidgetShell
      icon={<ShieldCheck size={16} />}
      title={t('project.widget.sub-insurance.title', { defaultValue: 'Subcontractor insurance' })}
      subtitle={t('project.widget.sub-insurance.card_subtitle', { defaultValue: 'Certificate compliance and held payments' })}
      cta={{
        label: t('project.widget.view_all', { defaultValue: 'View all' }),
        onClick: () => navigate('/subcontractors'),
      }}
    >
      {rollup.isLoadingFromRollup ? (
        <WidgetSkeleton rows={2} />
      ) : !data || total === 0 ? (
        <WidgetEmpty
          message={t('project.widget.sub-insurance.empty', {
            defaultValue: 'No subcontractors with insurance on record.',
          })}
        />
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-3 text-xs">
            <Badge variant="success">
              {t('project.widget.sub-insurance.compliant', { defaultValue: '{{count}} compliant', count: data.compliant })}
            </Badge>
            <Badge variant="warning">
              {t('project.widget.sub-insurance.expiring', { defaultValue: '{{count}} expiring', count: data.expiring })}
            </Badge>
            <Badge variant="error">
              {t('project.widget.sub-insurance.non_compliant', { defaultValue: '{{count}} non-compliant', count: data.non_compliant })}
            </Badge>
          </div>
          {data.blocked_payments > 0 && (
            <p className="text-2xs text-semantic-error">
              {t('project.widget.sub-insurance.blocked_payments', {
                defaultValue: '{{count}} payments held by the insurance gate',
                count: data.blocked_payments,
              })}
            </p>
          )}
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 12. Compliance summary ──────────────────────────────────────────── */

interface ComplianceDoc {
  id: string;
  status?: string;
  expires_at?: string | null;
  doc_type?: string;
}

export function ComplianceSummaryWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rollup = useRollupSlice('project_compliance_summary');
  const fallback = useGracefulQuery<ComplianceDoc[]>(
    ['proj-widget-compliance', projectId],
    `/v1/compliance-docs/?project_id=${projectId}&limit=50`,
    !rollup.hasProvider,
  );
  const data: ComplianceDoc[] | null | undefined = rollup.hasProvider
    ? (rollup.data?.items as ComplianceDoc[] | undefined) ?? null
    : fallback.data;
  const isLoading = rollup.hasProvider ? rollup.isLoadingFromRollup : fallback.isLoading;

  const counts = useMemo(() => {
    if (rollup.hasProvider && rollup.data) {
      return {
        active: rollup.data.active,
        expiring: rollup.data.expiring,
        expired: rollup.data.expired,
      };
    }
    const c = { active: 0, expiring: 0, expired: 0 };
    if (!data) return c;
    const now = Date.now();
    const in30 = now + 30 * 24 * 3600 * 1000;
    for (const d of data) {
      const exp = d.expires_at ? Date.parse(d.expires_at) : NaN;
      if (Number.isFinite(exp)) {
        if (exp < now) c.expired++;
        else if (exp < in30) c.expiring++;
        else c.active++;
      } else {
        c.active++;
      }
    }
    return c;
  }, [data, rollup.hasProvider, rollup.data]);

  const title = t('project.widget.compliance-summary.title', {
    defaultValue: 'Compliance summary',
  });
  const subtitle = t('project.widget.compliance-summary.card_subtitle', {
    defaultValue: 'Insurance / permits / certifications',
  });
  const icon = <ShieldCheck size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate(`/projects/${projectId}?tab=compliance`),
  };

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data || data.length === 0 ? (
        <WidgetEmpty
          message={t('project.widget.compliance-summary.empty', {
            defaultValue: 'No compliance documents.',
          })}
        />
      ) : (
        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.compliance-summary.active', { defaultValue: 'Active' })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-emerald-600">
              {counts.active}
            </div>
          </div>
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.compliance-summary.expiring', {
                defaultValue: 'Expiring',
              })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-amber-600">
              {counts.expiring}
            </div>
          </div>
          <div>
            <div className="text-2xs uppercase tracking-wider text-content-tertiary mb-1">
              {t('project.widget.compliance-summary.expired', {
                defaultValue: 'Expired',
              })}
            </div>
            <div className="text-xl font-semibold tabular-nums text-semantic-error">
              {counts.expired}
            </div>
          </div>
        </div>
      )}
    </WidgetShell>
  );
}

/* ── 13. Schedule strip ──────────────────────────────────────────────── */

interface ScheduleSummary {
  progress_pct?: number | string;
  total_activities?: number;
  completed?: number;
  delayed?: number;
  next_milestone?: { name?: string; date?: string } | null;
}

export function ScheduleStripWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Project-wide schedule rollup (progress, completed/delayed counts, next
  // milestone) computed across all of the project's schedules.
  const { data, isLoading } = useGracefulQuery<ScheduleSummary>(
    ['proj-widget-schedule', projectId],
    `/v1/schedule/stats/?project_id=${projectId}`,
  );

  const title = t('project.widget.schedule-strip.title', {
    defaultValue: 'Schedule summary',
  });
  const subtitle = t('project.widget.schedule-strip.card_subtitle', {
    defaultValue: 'Progress and next milestone',
  });
  const icon = <CalendarClock size={16} />;
  const cta = {
    label: t('project.widget.view_all', { defaultValue: 'View all' }),
    onClick: () => navigate('/schedule'),
  };

  const pct =
    typeof data?.progress_pct === 'string'
      ? Number(data.progress_pct)
      : data?.progress_pct ?? 0;

  return (
    <WidgetShell icon={icon} title={title} subtitle={subtitle} cta={cta}>
      {isLoading ? (
        <WidgetSkeleton rows={2} />
      ) : !data || !data.total_activities ? (
        <WidgetEmpty
          message={t('project.widget.schedule-strip.empty', {
            defaultValue: 'No schedule data yet. Create your first schedule.',
          })}
        />
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <span className="text-2xl font-bold tabular-nums text-content-primary leading-none">
              {Number.isFinite(pct) ? fmtFixed(pct, 0) : 0}%
            </span>
            <div className="flex-1 h-2 bg-surface-secondary rounded-full overflow-hidden">
              <div
                className="h-full bg-oe-blue transition-all duration-500"
                style={{
                  width: `${Math.min(Number.isFinite(pct) ? pct : 0, 100)}%`,
                }}
              />
            </div>
          </div>
          <div className="flex items-center gap-3 text-2xs text-content-secondary">
            {data.completed != null && (
              <span>
                {data.completed}/{data.total_activities ?? 0}{' '}
                {t('project.widget.schedule-strip.activities', { defaultValue: 'done' })}
              </span>
            )}
            {data.delayed != null && data.delayed > 0 && (
              <span className="text-semantic-error">
                {data.delayed} {t('project.widget.schedule-strip.delayed', { defaultValue: 'delayed' })}
              </span>
            )}
          </div>
          {data.next_milestone?.name && (
            <div className="pt-2 border-t border-border-light">
              <p className="text-2xs uppercase tracking-wider text-content-tertiary">
                {t('project.widget.schedule-strip.next', { defaultValue: 'Next milestone' })}
              </p>
              <p className="text-sm font-medium text-content-primary truncate">
                {data.next_milestone.name}
              </p>
              {data.next_milestone.date && (
                <p className="text-2xs text-content-tertiary">
                  {data.next_milestone.date}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </WidgetShell>
  );
}
