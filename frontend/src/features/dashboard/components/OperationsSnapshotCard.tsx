/**
 * OperationsSnapshotCard — consolidates the 9 "operations" wave-2 widgets
 * (BOQ Summary, Validation, Clash, Critical Path, Top Risks, HSE,
 * Procurement, Budget Variance, Change Orders) into a single card with
 * a 3-column grid of compact tiles.
 *
 * Pre-2026-05-25 those nine widgets each rendered as full-width empty
 * cards on fresh installs, which looked broken — nine "no data yet"
 * placeholders stacked vertically. This card replaces them with one
 * tight overview: per-tile name + key metric (or em-dash when empty)
 * + click-through to the relevant module. Data lights up automatically
 * as projects acquire BOQs / clashes / change orders / etc.
 *
 * Data comes from the shared ``DashboardRollupContext`` — same payload
 * the individual widgets consumed, no extra HTTP.
 */
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  FileSpreadsheet,
  GitBranch,
  ShieldAlert,
  HardHat,
  ShoppingCart,
  Wallet,
  ClipboardList,
  Cog,
  CheckSquare,
  ArrowRight,
} from 'lucide-react';
import { Card, CardContent, Skeleton } from '@/shared/ui';
import { useDashboardRollupContext } from '../context/DashboardRollupContext';

interface ProjectRef {
  id: string;
  name: string;
  currency: string;
}

function fmtMoney(value: string | number | null | undefined, currency: string): string {
  if (value == null) return `${currency} 0`;
  const n = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(n)) return `${currency} 0`;
  return `${currency} ${n.toLocaleString(undefined, { maximumFractionDigits: 0, notation: n >= 100000 ? 'compact' : 'standard' })}`;
}

interface Tile {
  key: string;
  icon: React.ReactNode;
  title: string;
  value: string;
  href: string;
  empty: boolean;
}

export function OperationsSnapshotCard({ projects }: { projects?: ProjectRef[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { isLoading, byWidget } = useDashboardRollupContext();
  const fallbackCurrency = projects?.[0]?.currency ?? 'EUR';

  const dash = '—';
  const iconCls = 'text-content-tertiary';

  const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
  const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

  const boq = byWidget('boq_summary') as {
    total_boqs?: number;
    total_value_eur?: string | number;
    // Per-currency subtotals + multi-currency flag added by the backend
    // rollup (dashboard/service.py). The shared rollup type does not yet
    // declare them, so we read them through this narrow inline shape.
    by_currency?: { currency: string; total_value: string }[];
    multi_currency?: boolean;
  } | null;
  const validation = byWidget('validation_score') as { passed?: number; warnings?: number; errors?: number } | null;
  const clash = byWidget('clash_health') as { total?: number; high?: number } | null;
  const schedule = byWidget('schedule_critical') as { top?: unknown[] } | null;
  const risk = byWidget('risk_top') as { top?: { score?: number }[] } | null;
  const hse = byWidget('hse_scorecard') as { total?: number; last_30d?: number; days_since_last?: number | null } | null;
  const proc = byWidget('procurement_pipeline') as { rfqs_pending?: number; pos_issued?: number; pos_received?: number } | null;
  const budget = byWidget('budget_variance') as { top_over?: { pct?: number }[] } | null;
  const co = byWidget('change_orders') as { open_count?: number; total_impact?: string | number; currency?: string } | null;

  const boqTotal = num(boq?.total_boqs);
  // Currency-correct BOQ value: when every project shares one currency we
  // show "{count} · {value CUR}"; across mixed currencies there is no
  // blended rate, so we render the BOQ count only (a wrong-currency total
  // would be financially meaningless). Falls back to the legacy scalar only
  // when an older backend omits ``by_currency``.
  const boqCurrencies = boq?.by_currency ?? [];
  const boqMultiCurrency = boq?.multi_currency ?? boqCurrencies.length > 1;
  const boqValueLabel = (() => {
    if (boqTotal === 0) return dash;
    if (boqMultiCurrency) {
      return t('dashboard.snapshot_boq_count', {
        defaultValue: '{{n}} BOQs · multi-currency',
        n: boqTotal,
      });
    }
    const onlyCur = boqCurrencies[0];
    if (boqCurrencies.length === 1 && onlyCur) {
      return `${boqTotal} · ${fmtMoney(onlyCur.total_value, onlyCur.currency)}`;
    }
    // No per-currency buckets at all (e.g. nothing priced yet) — show count.
    return `${boqTotal}`;
  })();
  const valSum = num(validation?.passed) + num(validation?.warnings) + num(validation?.errors);
  const clashTotal = num(clash?.total);
  const scheduleTop = arr<unknown>(schedule?.top);
  const riskTop = arr<{ score?: number }>(risk?.top);
  const hseTotal = num(hse?.total);
  const procSum = num(proc?.rfqs_pending) + num(proc?.pos_issued) + num(proc?.pos_received);
  const budgetOver = arr<{ pct?: number }>(budget?.top_over);
  const coOpen = num(co?.open_count);

  const tiles: Tile[] = [
    {
      key: 'boq',
      icon: <FileSpreadsheet size={14} className={iconCls} />,
      title: t('dashboard.layout.w_boq_summary', { defaultValue: 'BOQ Summary' }),
      value: boqValueLabel,
      href: '/boq',
      empty: boqTotal === 0,
    },
    {
      key: 'validation',
      icon: <CheckSquare size={14} className={iconCls} />,
      title: t('dashboard.layout.w_validation', { defaultValue: 'Validation Health' }),
      value: valSum === 0
        ? dash
        : `${num(validation?.passed)} / ${num(validation?.warnings)} / ${num(validation?.errors)}`,
      href: '/validation',
      empty: valSum === 0,
    },
    {
      key: 'clash',
      icon: <Cog size={14} className={iconCls} />,
      title: t('dashboard.layout.w_clash', { defaultValue: 'Clash Health' }),
      value: clashTotal === 0
        ? dash
        : t('dashboard.snapshot_clash_v', {
            defaultValue: '{{open}} open · {{high}} high',
            open: clashTotal,
            high: num(clash?.high),
          }),
      href: '/clash',
      empty: clashTotal === 0,
    },
    {
      key: 'schedule',
      icon: <GitBranch size={14} className={iconCls} />,
      title: t('dashboard.layout.w_schedule', { defaultValue: 'Critical Path' }),
      value: scheduleTop.length === 0
        ? dash
        : t('dashboard.snapshot_schedule_v', { defaultValue: '{{n}} at risk', n: scheduleTop.length }),
      href: '/schedule',
      empty: scheduleTop.length === 0,
    },
    {
      key: 'risk',
      icon: <ShieldAlert size={14} className={iconCls} />,
      title: t('dashboard.layout.w_risk', { defaultValue: 'Top Risks' }),
      value: riskTop.length === 0
        ? dash
        : t('dashboard.snapshot_risk_v', {
            defaultValue: '{{n}} risks · top {{s}}',
            n: riskTop.length,
            s: Math.round(num(riskTop[0]?.score)),
          }),
      href: '/risk-register',
      empty: riskTop.length === 0,
    },
    {
      key: 'hse',
      icon: <HardHat size={14} className={iconCls} />,
      title: t('dashboard.layout.w_hse', { defaultValue: 'HSE Scorecard' }),
      value: hseTotal === 0
        ? dash
        : t('dashboard.snapshot_hse_v', {
            defaultValue: '{{n}} in 30d · LTI {{d}}d',
            n: num(hse?.last_30d),
            d: num(hse?.days_since_last),
          }),
      href: '/hse',
      empty: hseTotal === 0,
    },
    {
      key: 'procurement',
      icon: <ShoppingCart size={14} className={iconCls} />,
      title: t('dashboard.layout.w_procurement', { defaultValue: 'Procurement' }),
      value: procSum === 0
        ? dash
        : t('dashboard.snapshot_proc_v', {
            defaultValue: '{{r}} RFQ · {{p}} PO',
            r: num(proc?.rfqs_pending),
            p: num(proc?.pos_issued),
          }),
      href: '/procurement',
      empty: procSum === 0,
    },
    {
      key: 'budget',
      icon: <Wallet size={14} className={iconCls} />,
      title: t('dashboard.layout.w_budget', { defaultValue: 'Budget Variance' }),
      value: budgetOver.length === 0
        ? dash
        : t('dashboard.snapshot_budget_v', {
            defaultValue: '{{n}} over · +{{p}}%',
            n: budgetOver.length,
            p: num(budgetOver[0]?.pct),
          }),
      href: '/finance',
      empty: budgetOver.length === 0,
    },
    {
      key: 'co',
      icon: <ClipboardList size={14} className={iconCls} />,
      title: t('dashboard.layout.w_changeorders', { defaultValue: 'Change Orders' }),
      value: coOpen === 0
        ? dash
        : `${coOpen} · ${fmtMoney(co?.total_impact, co?.currency ?? fallbackCurrency)}`,
      href: '/change-orders',
      empty: coOpen === 0,
    },
  ];

  return (
    <div className="animate-card-in" style={{ animationDelay: '160ms' }}>
      <Card className="!bg-surface-elevated/70">
        <div className="px-4 pt-3 pb-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboard.snapshot_title', { defaultValue: 'Operations snapshot' })}
          </h3>
          <p className="text-2xs text-content-tertiary">
            {t('dashboard.snapshot_subtitle', {
              defaultValue:
                'Health across nine operations modules - empty tiles light up as data lands.',
            })}
          </p>
        </div>
        <CardContent>
          {isLoading && tiles.every((tl) => tl.empty) ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {Array.from({ length: 9 }).map((_, i) => (
                <Skeleton key={i} height={56} rounded="md" />
              ))}
            </div>
          ) : (
            <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {tiles.map((tile) => (
                <li key={tile.key}>
                  <button
                    type="button"
                    onClick={() => navigate(tile.href)}
                    className="group flex w-full items-center gap-2.5 rounded-md border border-border-light bg-surface-secondary/40 px-3 py-2 text-left transition-colors hover:bg-surface-secondary hover:border-border-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                  >
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-elevated">
                      {tile.icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium text-content-primary">
                        {tile.title}
                      </span>
                      <span
                        className={`block truncate text-2xs tabular-nums ${
                          tile.empty
                            ? 'text-content-quaternary'
                            : 'text-content-secondary'
                        }`}
                      >
                        {tile.value}
                      </span>
                    </span>
                    <ArrowRight
                      size={12}
                      className="text-content-quaternary group-hover:text-content-secondary transition-colors"
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
