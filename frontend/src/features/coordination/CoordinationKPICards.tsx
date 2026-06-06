/**
 * KPI cards row for the Coordination Hub dashboard.
 *
 * Four glass-effect cards with per-metric color accents:
 *  • Open Clashes — orange/red accent (alert)
 *  • Cost Impact — amber accent (money)
 *  • Rule Packs   — emerald accent (passing)
 *  • Federations  — sky accent (structural)
 *
 * The colored accent lives as a 2 px gradient bar on top + a faint
 * radial glow behind the icon, so it reads as "themed" without
 * fighting the glass texture. Loading skeleton mirrors the same
 * footprint so the page doesn't reflow when data lands.
 */

import {
  Radar,
  Coins,
  ClipboardCheck,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Eye,
  FileText,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { InfoHint } from '@/shared/ui';
import type { CoordinationDashboard } from './types';

export interface CoordinationKPICardsProps {
  data: CoordinationDashboard | undefined;
  isLoading?: boolean;
}

type Accent = 'rose' | 'amber' | 'emerald' | 'sky';

const ACCENT_STYLES: Record<
  Accent,
  { bar: string; glow: string; iconBg: string; iconText: string }
> = {
  rose: {
    bar: 'from-rose-400/80 via-rose-500/80 to-orange-400/80',
    glow: 'from-rose-500/20',
    iconBg: 'bg-rose-50 dark:bg-rose-500/10',
    iconText: 'text-rose-600 dark:text-rose-400',
  },
  amber: {
    bar: 'from-amber-400/80 via-amber-500/80 to-yellow-400/80',
    glow: 'from-amber-500/20',
    iconBg: 'bg-amber-50 dark:bg-amber-500/10',
    iconText: 'text-amber-600 dark:text-amber-400',
  },
  emerald: {
    bar: 'from-emerald-400/80 via-emerald-500/80 to-teal-400/80',
    glow: 'from-emerald-500/20',
    iconBg: 'bg-emerald-50 dark:bg-emerald-500/10',
    iconText: 'text-emerald-600 dark:text-emerald-400',
  },
  sky: {
    bar: 'from-sky-400/80 via-blue-500/80 to-indigo-400/80',
    glow: 'from-sky-500/20',
    iconBg: 'bg-sky-50 dark:bg-sky-500/10',
    iconText: 'text-sky-600 dark:text-sky-400',
  },
};

interface KPICardProps {
  accent: Accent;
  icon: React.ReactNode;
  label: string;
  primary: React.ReactNode;
  delta?: { value: number; direction: 'up' | 'down' | 'flat'; label: string } | null;
  secondary?: React.ReactNode;
  /** Optional one-line caveat surfaced via an (i) tooltip next to the label. */
  hint?: string;
  testId?: string;
}

function KPICard({ accent, icon, label, primary, delta, secondary, hint, testId }: KPICardProps) {
  const styles = ACCENT_STYLES[accent];
  return (
    <div
      data-testid={testId}
      className={clsx(
        'group relative overflow-hidden rounded-2xl',
        'border border-border-light',
        'bg-surface-elevated/90',
        'shadow-xs',
        'transition-shadow duration-normal ease-oe',
        'hover:shadow-sm',
      )}
    >
      {/* Top accent bar */}
      <div
        aria-hidden
        className={clsx(
          'absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r opacity-80',
          styles.bar,
        )}
      />
      {/* Soft radial glow behind icon */}
      <div
        aria-hidden
        className={clsx(
          'pointer-events-none absolute -top-12 -right-12 h-32 w-32 rounded-full bg-gradient-radial to-transparent blur-2xl opacity-60',
          styles.glow,
        )}
      />
      <div className="relative p-5">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            <div
              className={clsx(
                'flex h-9 w-9 items-center justify-center rounded-xl',
                styles.iconBg,
                styles.iconText,
              )}
            >
              {icon}
            </div>
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
              {label}
              {hint ? <InfoHint inline text={hint} /> : null}
            </span>
          </div>
          {delta ? (
            <span
              data-testid={testId ? `${testId}-delta` : undefined}
              className={clsx(
                'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold',
                delta.direction === 'up' &&
                  'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
                delta.direction === 'down' &&
                  'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
                delta.direction === 'flat' &&
                  'bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300',
              )}
            >
              {delta.direction === 'up' && <ArrowUpRight size={11} />}
              {delta.direction === 'down' && <ArrowDownRight size={11} />}
              {delta.direction === 'flat' && <Minus size={11} />}
              {Math.abs(delta.value)}
            </span>
          ) : null}
        </div>
        <div className="mt-4 text-3xl font-bold tracking-tight text-content-primary">
          {primary}
        </div>
        {secondary ? (
          <div className="mt-1.5 text-xs text-content-tertiary">{secondary}</div>
        ) : (
          <div className="mt-1.5 h-4" />
        )}
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-border-light bg-surface-elevated/90 p-5 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
      <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-slate-200 to-slate-100 dark:from-slate-700 dark:to-slate-800" />
      <div className="flex items-center gap-2.5">
        <div className="h-9 w-9 animate-pulse rounded-xl bg-slate-200 dark:bg-slate-700" />
        <div className="h-3 w-24 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      </div>
      <div className="mt-4 h-8 w-3/4 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-2 h-3 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
    </div>
  );
}

interface StatTileProps {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  footer?: React.ReactNode;
  /** Optional caveat surfaced via an (i) tooltip next to the label. */
  hint?: string;
}

/** Lightweight supporting stat — used for the BCF / smart-view strip below
 *  the four headline KPI cards. Glass treatment matches the cards but with
 *  less visual weight (no accent bar, smaller type). */
function StatTile({ icon, label, value, footer, hint }: StatTileProps) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-border-light bg-surface-elevated/90 px-4 py-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
      <div className="flex items-center gap-2 text-content-tertiary">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-slate-100 text-content-secondary dark:bg-slate-800">
          {icon}
        </span>
        <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider">
          {label}
          {hint ? <InfoHint inline text={hint} /> : null}
        </span>
      </div>
      <div className="mt-1.5 text-base font-semibold text-content-primary">
        {value}
      </div>
      {footer ? (
        <div className="mt-0.5 text-xs text-content-tertiary">{footer}</div>
      ) : null}
    </div>
  );
}

export function CoordinationKPICards({
  data,
  isLoading,
}: CoordinationKPICardsProps) {
  const { t } = useTranslation();

  if (isLoading || !data) {
    return (
      <div
        data-testid="coordination-kpi-skeleton"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  const newCount = data.clashes.delta_since_last_run.new;
  const resolvedCount = data.clashes.delta_since_last_run.resolved;

  let clashDelta: KPICardProps['delta'] = null;
  if (newCount > 0) {
    clashDelta = {
      value: newCount,
      direction: 'up',
      label: t('coordination.delta_since_last_run', {
        defaultValue: 'since last run',
      }),
    };
  } else if (resolvedCount > 0) {
    clashDelta = {
      value: resolvedCount,
      direction: 'down',
      label: t('coordination.delta_resolved', { defaultValue: 'resolved' }),
    };
  }

  return (
    <>
    <div
      data-testid="coordination-kpi-cards"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <KPICard
        accent="rose"
        testId="kpi-open-clashes"
        icon={<Radar size={18} />}
        label={t('coordination.open_clashes', { defaultValue: 'Open Clashes' })}
        primary={data.clashes.open_count.toLocaleString()}
        delta={clashDelta}
        secondary={
          data.clashes.last_run_at ? (
            <span className="inline-flex items-center gap-1">
              {t('coordination.resolved_clashes', {
                defaultValue: '{{n}} resolved',
                n: data.clashes.resolved_count,
              })}
              {' · '}
              {t('coordination_hub.last_run', { defaultValue: 'as of' })}{' '}
              <DateDisplay value={data.clashes.last_run_at} format="relative" />
            </span>
          ) : (
            t('coordination.resolved_clashes', {
              defaultValue: '{{n}} resolved',
              n: data.clashes.resolved_count,
            })
          )
        }
      />
      <KPICard
        accent="amber"
        testId="kpi-cost-impact"
        icon={<Coins size={18} />}
        label={t('coordination.cost_impact_open', {
          defaultValue: 'Open Cost Impact',
        })}
        primary={
          <MoneyDisplay
            amount={data.open_cost_impact_total}
            currency={data.currency}
            compact
          />
        }
        secondary={t('coordination_hub.cost_across_clashes', {
          defaultValue: 'Across {{n}} open clash(es)',
          n: data.clashes.open_count,
        })}
      />
      <KPICard
        accent="emerald"
        testId="kpi-rule-pack"
        icon={<ClipboardCheck size={18} />}
        label={t('coordination.rule_pack_status', { defaultValue: 'Rule Packs' })}
        primary={data.rule_packs.installed_count.toLocaleString()}
        secondary={t('coordination_hub.rules_active_disabled', {
          defaultValue: '{{p}} active · {{f}} disabled',
          p: data.rule_packs.last_check_pass_count,
          f: data.rule_packs.last_check_fail_count,
        })}
        hint={t('coordination_hub.rules_hint', {
          defaultValue:
            'These are configuration states (rules switched on vs off), not the result of a model evaluation run.',
        })}
      />
      <KPICard
        accent="sky"
        testId="kpi-federations"
        icon={<Layers size={18} />}
        label={t('coordination.federations_count', { defaultValue: 'Federations' })}
        primary={data.federations.count.toLocaleString()}
        secondary={t('coordination.federations_members', {
          defaultValue: '{{m}} members · {{e}} elements',
          m: data.federations.total_members,
          e: data.federations.total_elements,
        })}
      />
    </div>

    {/* Secondary stat strip — surfaces the BCF-activity + smart-view
        figures the dashboard payload already carries (and the page
        subtitle advertises) but that the four KPI cards above never
        render. Lighter chrome than a full KPI card so it reads as
        supporting context, not a fifth headline metric. */}
    <div
      data-testid="coordination-stat-strip"
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
    >
      <StatTile
        icon={<FileText size={15} />}
        label={t('coordination_hub.bcf_activity', {
          defaultValue: 'BCF activity (30d)',
        })}
        value={t('coordination_hub.bcf_io', {
          defaultValue: '{{out}} exported · {{in}} imported',
          out: data.bcf_activity.topics_exported_30d,
          in: data.bcf_activity.topics_imported_30d,
        })}
        footer={
          data.bcf_activity.last_export_at ? (
            <>
              {t('coordination_hub.bcf_last', { defaultValue: 'Last activity' })}{' '}
              <DateDisplay
                value={data.bcf_activity.last_export_at}
                format="relative"
              />
            </>
          ) : (
            t('coordination_hub.bcf_none', {
              defaultValue: 'No BCF topics in the last 30 days',
            })
          )
        }
        hint={t('coordination_hub.bcf_hint', {
          defaultValue:
            'Coarse activity signal. Import vs export is approximated from topic authoring metadata, not a dedicated direction flag.',
        })}
      />
      <StatTile
        icon={<Eye size={15} />}
        label={t('coordination_hub.smart_views_project', {
          defaultValue: 'Project smart views',
        })}
        value={data.smart_views.project_count.toLocaleString()}
        footer={t('coordination_hub.smart_views_project_footer', {
          defaultValue: 'Saved views scoped to this project',
        })}
      />
      <StatTile
        icon={<Eye size={15} />}
        label={t('coordination_hub.smart_views_personal', {
          defaultValue: 'Personal smart views',
        })}
        value={data.smart_views.user_count.toLocaleString()}
        footer={t('coordination_hub.smart_views_personal_footer', {
          defaultValue: 'Across all projects',
        })}
        hint={t('coordination_hub.smart_views_personal_hint', {
          defaultValue:
            'Personal (user-scoped) views are not tied to a project, so this is a global count across every project you can access, not a per-project figure.',
        })}
      />
    </div>
    </>
  );
}
