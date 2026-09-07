// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pricing Engine — versioned, rule-driven property-dev sales pricing.
 *
 * Backed by /api/v1/property-dev/{developments,price-lists}/... (see
 * backend/app/modules/property_dev/router.py — pricing engine section).
 *
 * Four tabs:
 *   1. Price Lists  — table of versions (draft/active/superseded) + create form.
 *   2. Rules        — editor for the currently-active list (CRUD + reorder),
 *                     with inline conflict-resolution badges, time-window
 *                     pickers (quick chips + timeline + validation), currency
 *                     <select> from ISO 4217 top-30, and rule-type help with
 *                     example-calculation preview.
 *   3. Simulator    — pick plot + promo + buyer → live PriceQuote with
 *                     waterfall, side-by-side "Compare with previous quote",
 *                     currency-mismatch warning + print-friendly view.
 *   4. Quote History — historical price_breakdown_snapshot from reservations
 *                     with filtering (buyer/plot/date/status), sortable
 *                     columns and a click-through detail drawer that exposes
 *                     the snapshot indicator (snapshot-from-date vs live).
 *
 * i18n: EN strings live in `frontend/src/app/locales/en.ts`; the other
 * locales fall back to EN via i18next default.
 * Tabs collapse to a dropdown <768px.
 */

import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  AlertOctagon,
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CheckCircle2,
  ChevronUp,
  ChevronDown,
  Clock,
  Filter,
  History,
  Info,
  Loader2,
  PlayCircle,
  Plus,
  Printer,
  Receipt,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  InfoHint,
  IntroRichText,
  MoneyDisplay,
  SideDrawer,
  SkeletonTable,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  activatePriceList,
  createPriceList,
  createPricingRule,
  deletePricingRule,
  listBuyers,
  listPlots,
  listPriceLists,
  listPricingRules,
  listReservations,
  quotePrice,
  updatePricingRule,
  type Buyer,
  type CreatePricingRulePayload,
  type PriceList,
  type PriceQuote,
  type PricingRule,
  type PricingRuleType,
  type Plot,
  type Reservation,
  type ReservationStatus,
} from './api';
import { formatCurrency } from '@/shared/lib/money';
import { getIntlLocale } from '@/shared/lib/formatters';
import { compareNames } from '@/shared/lib/collator';

const RULE_TYPES: PricingRuleType[] = [
  'early_bird',
  'view_premium',
  'floor_premium',
  'corner_premium',
  'size_premium',
  'promo_code',
  'friends_family',
  'loyalty',
  'bulk_buy',
];

type Tab = 'lists' | 'rules' | 'sim' | 'history';
const PRICING_TAB_IDS: readonly Tab[] = ['lists', 'rules', 'sim', 'history'];

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const inputErrCls =
  'h-9 w-full rounded-lg border border-rose-400 bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-rose-300';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

/**
 * Top-30 ISO 4217 currencies by global construction & property usage.
 * Ordering puts DACH/EU at the top, then GBP/USD, then MENA, then APAC.
 * Tenants can extend this via a free-form fallback (handled below).
 */
const CURRENCY_OPTIONS: Array<{ code: string; label: string }> = [
  { code: 'EUR', label: 'EUR - Euro' },
  { code: 'USD', label: 'USD - US Dollar' },
  { code: 'GBP', label: 'GBP - Pound Sterling' },
  { code: 'CHF', label: 'CHF - Swiss Franc' },
  { code: 'AED', label: 'AED - UAE Dirham' },
  { code: 'SAR', label: 'SAR - Saudi Riyal' },
  { code: 'QAR', label: 'QAR - Qatari Riyal' },
  { code: 'KWD', label: 'KWD - Kuwaiti Dinar' },
  { code: 'BHD', label: 'BHD - Bahraini Dinar' },
  { code: 'OMR', label: 'OMR - Omani Rial' },
  { code: 'TRY', label: 'TRY - Turkish Lira' },
  { code: 'RUB', label: 'RUB - Russian Ruble' },
  { code: 'PLN', label: 'PLN - Polish Złoty' },
  { code: 'CZK', label: 'CZK - Czech Koruna' },
  { code: 'NOK', label: 'NOK - Norwegian Krone' },
  { code: 'SEK', label: 'SEK - Swedish Krona' },
  { code: 'DKK', label: 'DKK - Danish Krone' },
  { code: 'CAD', label: 'CAD - Canadian Dollar' },
  { code: 'AUD', label: 'AUD - Australian Dollar' },
  { code: 'NZD', label: 'NZD - New Zealand Dollar' },
  { code: 'JPY', label: 'JPY - Japanese Yen' },
  { code: 'CNY', label: 'CNY - Chinese Yuan' },
  { code: 'HKD', label: 'HKD - Hong Kong Dollar' },
  { code: 'SGD', label: 'SGD - Singapore Dollar' },
  { code: 'INR', label: 'INR - Indian Rupee' },
  { code: 'KRW', label: 'KRW - South Korean Won' },
  { code: 'IDR', label: 'IDR - Indonesian Rupiah' },
  { code: 'THB', label: 'THB - Thai Baht' },
  { code: 'ZAR', label: 'ZAR - South African Rand' },
  { code: 'BRL', label: 'BRL - Brazilian Real' },
];

// One quote, one number of decimals, decided where the decimals are decided.
//
// The formatter this replaces pinned a ceiling of two decimals with no floor,
// which reads as a claim that every currency a price list can be denominated
// in has at most two minor units. It does not: a yen line of 1234.50 printed
// "1.234,5 ¥", and a dinar total lost its third digit - or, on an engine
// without the ES2023 digit clamping, threw a `RangeError` out of the render
// because the currency's own floor of three cannot fit under a ceiling of two.
// `formatCurrency` reads the minor units off the engine per currency and
// cannot throw, so the waterfall, the chart tooltip and the rule preview all
// state the same amount the same way.
function fmtMoney(amount: string | number, currency: string): string {
  const n = typeof amount === 'string' ? Number(amount) : amount;
  if (!Number.isFinite(n)) return String(amount);
  return formatCurrency(n, currency);
}

function statusBadge(status: PriceList['status']): JSX.Element {
  const map: Record<
    PriceList['status'],
    { variant: 'success' | 'warning' | 'neutral'; label: string }
  > = {
    active: { variant: 'success', label: 'Active' },
    draft: { variant: 'warning', label: 'Draft' },
    superseded: { variant: 'neutral', label: 'Superseded' },
  };
  const m = map[status];
  return <Badge variant={m.variant}>{m.label}</Badge>;
}

// ── Currency picker (ISO 4217 top-30 + free-form fallback) ───────────

interface CurrencySelectProps {
  id?: string;
  value: string;
  onChange: (next: string) => void;
  ariaLabel?: string;
  className?: string;
}

function CurrencySelect({
  id,
  value,
  onChange,
  ariaLabel,
  className,
}: CurrencySelectProps): JSX.Element {
  // If the saved value isn't in the top-30, prepend it so the select can
  // still render it (avoids silently swapping to EUR on edit).
  const inList = CURRENCY_OPTIONS.some((o) => o.code === value);
  const extra = !inList && value ? [{ code: value, label: value }] : [];
  return (
    <select
      id={id}
      aria-label={ariaLabel}
      className={clsx(inputCls, className)}
      value={value || 'EUR'}
      onChange={(e) => onChange(e.target.value)}
    >
      {[...extra, ...CURRENCY_OPTIONS].map((o) => (
        <option key={o.code} value={o.code}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

// ── Tabs (compact responsive, delegates to shared TabBar) ────────────

interface TabsProps {
  tab: Tab;
  setTab: (t: Tab) => void;
}

function Tabs({ tab, setTab }: TabsProps): JSX.Element {
  const { t } = useTranslation();
  const onTabKeyDown = useTabKeyboardNav<Tab>({
    ids: PRICING_TAB_IDS,
    activeId: tab,
    onChange: setTab,
    orientation: 'horizontal',
  });
  const items: Array<{
    id: Tab;
    icon: JSX.Element;
    label: string;
  }> = [
    {
      id: 'lists',
      icon: <Receipt className="h-4 w-4" />,
      label: t('propdev.pricing.tab.lists', 'Price Lists'),
    },
    {
      id: 'rules',
      icon: <Settings2 className="h-4 w-4" />,
      label: t('propdev.pricing.tab.rules', 'Rules'),
    },
    {
      id: 'sim',
      icon: <Sparkles className="h-4 w-4" />,
      label: t('propdev.pricing.tab.sim', 'Simulator'),
    },
    {
      id: 'history',
      icon: <History className="h-4 w-4" />,
      label: t('propdev.pricing.tab.history', 'Quote History'),
    },
  ];
  return (
    <>
      {/* Mobile dropdown */}
      <div className="md:hidden">
        <select
          aria-label={t('propdev.pricing.tabs_aria', {
            defaultValue: 'Pricing engine sections',
          })}
          className={inputCls}
          value={tab}
          onChange={(e) => setTab(e.target.value as Tab)}
        >
          {items.map((it) => (
            <option key={it.id} value={it.id}>
              {it.label}
            </option>
          ))}
        </select>
      </div>
      {/* Desktop tab bar — preserve manual roving tabindex from existing
          implementation (TabBar fires onChange on arrow nav which is the
          same behaviour, but we keep the legacy keyboard-nav hook so
          E2E tests that watch for explicit role="tab" stay green). */}
      <div
        role="tablist"
        aria-label={t('propdev.pricing.tabs_aria', {
          defaultValue: 'Pricing engine sections',
        })}
        onKeyDown={onTabKeyDown}
        className="hidden md:flex items-center gap-1 border-b border-border"
      >
        {items.map((it) => (
          <button
            key={it.id}
            type="button"
            role="tab"
            id={`pricing-tab-${it.id}`}
            aria-selected={tab === it.id}
            aria-controls={`pricing-panel-${it.id}`}
            tabIndex={tab === it.id ? 0 : -1}
            onClick={() => setTab(it.id)}
            className={clsx(
              'flex items-center gap-2 px-3 py-2 -mb-px text-sm',
              tab === it.id
                ? 'border-b-2 border-oe-blue text-content-primary font-medium'
                : 'text-content-secondary hover:text-content-primary',
            )}
          >
            {it.icon}
            {it.label}
          </button>
        ))}
      </div>
    </>
  );
}

// ── Time-window picker (with quick-pick chips, timeline & validation) ─

interface TimeWindowPickerProps {
  from: string;
  to: string | null;
  onChange: (next: { from: string; to: string | null }) => void;
  /** Project context for the visual timeline overlay (optional). */
  projectFrom?: string | null;
  projectTo?: string | null;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function addMonths(iso: string, n: number): string {
  const d = new Date(iso);
  d.setMonth(d.getMonth() + n);
  return d.toISOString().slice(0, 10);
}

function startOfMonth(iso: string): string {
  const d = new Date(iso);
  d.setDate(1);
  return d.toISOString().slice(0, 10);
}

function endOfMonth(iso: string): string {
  const d = new Date(iso);
  d.setMonth(d.getMonth() + 1);
  d.setDate(0);
  return d.toISOString().slice(0, 10);
}

function startOfQuarter(iso: string): string {
  const d = new Date(iso);
  const qStart = Math.floor(d.getMonth() / 3) * 3;
  d.setMonth(qStart);
  d.setDate(1);
  return d.toISOString().slice(0, 10);
}

function endOfQuarter(iso: string): string {
  const d = new Date(iso);
  const qStart = Math.floor(d.getMonth() / 3) * 3;
  d.setMonth(qStart + 3);
  d.setDate(0);
  return d.toISOString().slice(0, 10);
}

function startOfYear(iso: string): string {
  return `${iso.slice(0, 4)}-01-01`;
}

function endOfYear(iso: string): string {
  return `${iso.slice(0, 4)}-12-31`;
}

function TimeWindowPicker({
  from,
  to,
  onChange,
  projectFrom,
  projectTo,
}: TimeWindowPickerProps): JSX.Element {
  const { t } = useTranslation();
  const today = todayISO();
  const validationErr = useMemo<string | null>(() => {
    if (from && to && from > to) {
      return t(
        'propdev.pricing.time.err_from_gt_to',
        'Start date must be on or before end date.',
      );
    }
    return null;
  }, [from, to, t]);

  const chips: Array<{ key: string; label: string; apply: () => void }> = [
    {
      key: 'all-year',
      label: t('propdev.pricing.time.all_year', 'All year'),
      apply: () =>
        onChange({ from: startOfYear(today), to: endOfYear(today) }),
    },
    {
      key: 'this-month',
      label: t('propdev.pricing.time.this_month', 'This month'),
      apply: () =>
        onChange({ from: startOfMonth(today), to: endOfMonth(today) }),
    },
    {
      key: 'next-quarter',
      label: t('propdev.pricing.time.next_quarter', 'Next quarter'),
      apply: () => {
        const start = startOfQuarter(addMonths(today, 3));
        onChange({ from: start, to: endOfQuarter(start) });
      },
    },
    {
      key: 'next-30d',
      label: t('propdev.pricing.time.next_30', 'Next 30 days'),
      apply: () => onChange({ from: today, to: addMonths(today, 1) }),
    },
    {
      key: 'no-end',
      label: t('propdev.pricing.time.no_end', 'No end date'),
      apply: () => onChange({ from: from || today, to: null }),
    },
    {
      key: 'clear',
      label: t('propdev.pricing.time.clear', 'Clear'),
      apply: () => onChange({ from: '', to: null }),
    },
  ];

  // Timeline render: project-window 100%, rule-window highlighted strip.
  const tl = useMemo(() => {
    const tlFrom = projectFrom || from || today;
    const tlTo = projectTo || to || addMonths(today, 12);
    const startMs = new Date(tlFrom).getTime();
    const endMs = new Date(tlTo).getTime();
    const span = Math.max(1, endMs - startMs);
    const ruleStartMs = from ? new Date(from).getTime() : startMs;
    const ruleEndMs = to ? new Date(to).getTime() : endMs;
    const leftPct = Math.max(0, ((ruleStartMs - startMs) / span) * 100);
    const widthPct = Math.max(
      2,
      Math.min(100 - leftPct, ((ruleEndMs - ruleStartMs) / span) * 100),
    );
    return {
      tlFrom,
      tlTo,
      leftPct,
      widthPct,
      hasProjectFrame: Boolean(projectFrom || projectTo),
    };
  }, [from, to, projectFrom, projectTo, today]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {chips.map((c) => (
          <button
            key={c.key}
            type="button"
            onClick={c.apply}
            className="rounded-full border border-border bg-surface-primary px-2.5 py-0.5 text-xs text-content-secondary hover:border-oe-blue hover:text-oe-blue"
          >
            {c.label}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div>
          <label className={labelCls} htmlFor="rule-from">
            {t('propdev.pricing.time.from', 'Valid from')}
          </label>
          <input
            id="rule-from"
            type="date"
            className={validationErr ? inputErrCls : inputCls}
            value={from}
            onChange={(e) => onChange({ from: e.target.value, to })}
          />
        </div>
        <div>
          <label className={labelCls} htmlFor="rule-to">
            {t('propdev.pricing.time.to', 'Valid until')}{' '}
            {!to && (
              <Badge variant="neutral" size="sm">
                {t('propdev.pricing.time.no_end_badge', 'no end date')}
              </Badge>
            )}
          </label>
          <input
            id="rule-to"
            type="date"
            className={validationErr ? inputErrCls : inputCls}
            value={to ?? ''}
            onChange={(e) => onChange({ from, to: e.target.value || null })}
          />
        </div>
      </div>
      {validationErr && (
        <p
          className="flex items-center gap-1.5 text-xs text-rose-600"
          role="alert"
        >
          <AlertOctagon className="h-3.5 w-3.5" />
          {validationErr}
        </p>
      )}
      {/* Visual timeline */}
      <div className="pt-1.5">
        <div className="relative h-2 w-full rounded-full bg-surface-secondary">
          <div
            className="absolute h-2 rounded-full bg-oe-blue/50"
            style={{ left: `${tl.leftPct}%`, width: `${tl.widthPct}%` }}
            aria-hidden="true"
          />
        </div>
        <div className="mt-1 flex justify-between text-2xs text-content-tertiary">
          <span>{tl.tlFrom}</span>
          <span>
            {tl.hasProjectFrame
              ? t('propdev.pricing.time.project_window', 'Project window')
              : t('propdev.pricing.time.next_12mo', 'Next 12 months')}
          </span>
          <span>{tl.tlTo}</span>
        </div>
      </div>
    </div>
  );
}

// ── Rule-type help (inline preview calculation) ──────────────────────

const RULE_TYPE_LABELS: Record<PricingRuleType, string> = {
  early_bird: 'Early bird',
  view_premium: 'View premium',
  floor_premium: 'Floor premium',
  corner_premium: 'Corner premium',
  size_premium: 'Size premium',
  promo_code: 'Promo code',
  friends_family: 'Friends & family',
  loyalty: 'Loyalty',
  bulk_buy: 'Bulk-buy',
};

const RULE_TYPE_HELP: Record<PricingRuleType, string> = {
  early_bird:
    'Adjusts price when the quote date is BEFORE a configured cutoff. Use a negative percentage for an early-bird discount.',
  view_premium:
    'Applies when the plot view matches a value list (e.g. ["sea", "park"]). Use a positive percentage to surcharge premium views.',
  floor_premium:
    'Applies when the plot floor is at or above a threshold (min_floor) or matches an exact floor. Typical for high-floor surcharges.',
  corner_premium:
    'Applies when the plot is flagged is_corner. Use a positive percentage or fixed amount to surcharge corner units.',
  size_premium:
    'Applies when plot area is within a range (min_area_m2 / max_area_m2). Common for large penthouses / villas.',
  promo_code:
    'Applies only when the user supplies the matching promo code at quote time. Case-insensitive match.',
  friends_family:
    'Applies when the buyer has the configured tag (default "ff") in their tags metadata.',
  loyalty:
    'Applies when the buyer has at least N prior reservations at this development.',
  bulk_buy:
    'Applies when the basket contains at least N plots. Common for investor block-purchase discounts.',
};

interface RuleTypePreviewProps {
  ruleType: PricingRuleType;
  adjustmentPct: string;
  adjustmentFixed: string | null;
  currency: string;
}

function RuleTypePreview({
  ruleType,
  adjustmentPct,
  adjustmentFixed,
  currency,
}: RuleTypePreviewProps): JSX.Element {
  const { t } = useTranslation();
  // Example baseline depends on rule type so the preview always feels
  // realistic — per-sqm rules pivot on a 100m² plot at €2 000/m²,
  // per-unit rules pivot on a €250 000 base, etc.
  const basePrice =
    ruleType === 'size_premium' || ruleType === 'view_premium' ? 200000 : 250000;
  const pct = Number(adjustmentPct || 0);
  const fixed = adjustmentFixed ? Number(adjustmentFixed) : 0;
  const delta = (basePrice * pct) / 100 + fixed;
  const total = basePrice + delta;
  const direction = delta < 0 ? 'discount' : delta > 0 ? 'surcharge' : 'neutral';
  return (
    <div className="rounded-lg border border-dashed border-border bg-surface-secondary/40 p-3 text-xs">
      <p className="mb-1 font-medium text-content-secondary">
        {t('propdev.pricing.help.preview_title', 'Example calculation')}
      </p>
      <p className="text-content-secondary">
        {t(
          'propdev.pricing.help.preview_line',
          'For a {{base}} base price, this rule applies as:',
          { base: fmtMoney(basePrice, currency || 'EUR') },
        )}
      </p>
      <p className="mt-1 font-mono">
        {fmtMoney(basePrice, currency || 'EUR')}{' '}
        <span
          className={clsx(
            direction === 'discount' && 'text-emerald-600',
            direction === 'surcharge' && 'text-amber-700',
          )}
        >
          {delta >= 0 ? '+' : '−'}
          {fmtMoney(Math.abs(delta), currency || 'EUR')}
        </span>{' '}
        ={' '}
        <span className="font-semibold">
          {fmtMoney(total, currency || 'EUR')}
        </span>
      </p>
    </div>
  );
}

// ── Conflict-resolution badge ────────────────────────────────────────
//
// The backend (`backend/app/modules/property_dev/pricing_engine.py`,
// function `compute_quote_pure`) sorts active rules by
// `(int(priority || 100), str(name))` ascending and applies them in
// sequence — each rule's adjustment compounds on the running subtotal,
// so the "winner" is rule with the LOWEST priority that matches first.
// Effective-window-narrower rules supersede in the same priority bucket
// because non-matching ones drop out at the date check, and explicit
// effective_to dates beat null (open-ended). We surface this verbatim
// in the tooltip so the user can audit the precedence.
//
// The "X rules apply" indicator on each rule row shows whether the
// rule is the WINNER among its conflict cohort (winner = same rule_type
// + same condition_json shape + same priority bucket).

interface ConflictGroup {
  /** All rule ids in the group (winner + losers). */
  ids: string[];
  /** Rule id that wins for this group (lowest priority, then name). */
  winnerId: string;
  /** Why the winner won — human-readable bullet list. */
  reason: string;
}

function describeRule(r: PricingRule): string {
  // A coarse grouping key — same `rule_type`, same JSON-ified condition
  // (sorted keys) means they target the same physical scope. We treat
  // them as a conflict cohort even if priorities differ.
  const cond =
    r.condition_json && typeof r.condition_json === 'object'
      ? JSON.stringify(
          Object.keys(r.condition_json)
            .sort()
            .reduce<Record<string, unknown>>((acc, k) => {
              acc[k] = (r.condition_json as Record<string, unknown>)[k];
              return acc;
            }, {}),
        )
      : '{}';
  return `${r.rule_type}|${cond}`;
}

function buildConflictGroups(rules: PricingRule[]): Map<string, ConflictGroup> {
  // Map: ruleId -> group describing that rule's conflict cohort.
  const groups = new Map<string, PricingRule[]>();
  for (const r of rules) {
    if (!r.active) continue;
    const key = describeRule(r);
    const arr = groups.get(key) ?? [];
    arr.push(r);
    groups.set(key, arr);
  }
  const out = new Map<string, ConflictGroup>();
  for (const [, arr] of groups) {
    if (arr.length < 2) continue;
    // Pick winner the same way the backend does: priority ASC, then name ASC.
    const sorted = [...arr].sort((a, b) => {
      const pa = a.priority ?? 100;
      const pb = b.priority ?? 100;
      if (pa !== pb) return pa - pb;
      return compareNames(a.name, b.name);
    });
    const winner = sorted[0]!;
    const reasons: string[] = [];
    const minPrio = Math.min(...arr.map((r) => r.priority ?? 100));
    const winnersAtMinPrio = arr.filter(
      (r) => (r.priority ?? 100) === minPrio,
    );
    if (winnersAtMinPrio.length === 1) {
      reasons.push(
        `Lowest priority value (${minPrio}) - applied first by the engine.`,
      );
    } else {
      reasons.push(
        `Lowest priority value (${minPrio}); tie broken alphabetically by name (winner "${winner.name}").`,
      );
    }
    // Time-window narrowing
    if (winner.effective_to && arr.some((r) => !r.effective_to)) {
      reasons.push(
        'Explicit end date - narrower time window beats open-ended siblings.',
      );
    }
    if (winner.max_uses !== null && winner.max_uses !== undefined) {
      reasons.push(
        `Max-uses cap (${winner.max_uses}) - once exhausted, the next-priority rule takes over.`,
      );
    }
    const reason = reasons.join(' ');
    const ids = arr.map((r) => r.id);
    for (const id of ids) {
      out.set(id, { ids, winnerId: winner.id, reason });
    }
  }
  return out;
}

interface ConflictBadgeProps {
  group: ConflictGroup;
  thisRule: PricingRule;
  allRules: PricingRule[];
}

function ConflictBadge({
  group,
  thisRule,
  allRules,
}: ConflictBadgeProps): JSX.Element {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const isWinner = group.winnerId === thisRule.id;
  const winner = allRules.find((r) => r.id === group.winnerId);
  const others = group.ids.length;
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium',
          isWinner
            ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
            : 'border-amber-300 bg-amber-50 text-amber-700',
        )}
        aria-expanded={open}
        aria-label={t(
          'propdev.pricing.conflict.aria',
          'Show rule precedence explanation',
        )}
      >
        <AlertTriangle className="h-3 w-3" />
        {isWinner
          ? t(
              'propdev.pricing.conflict.winner',
              '{{n}} rules apply - winner',
              { n: others },
            )
          : t(
              'propdev.pricing.conflict.loser',
              '{{n}} rules apply - superseded',
              { n: others },
            )}
      </button>
      {open && (
        <div
          className="absolute left-0 top-full z-30 mt-1 w-80 rounded-lg border border-border-light bg-surface-primary p-3 text-xs shadow-lg"
          role="tooltip"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="font-semibold text-content-primary">
              {t(
                'propdev.pricing.conflict.title',
                'Why "{{name}}" wins',
                { name: winner?.name ?? '—' },
              )}
            </p>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-content-tertiary hover:text-content-primary"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
          <p className="mt-1.5 leading-relaxed text-content-secondary">
            {group.reason}
          </p>
          <p className="mt-2 text-content-tertiary">
            {t(
              'propdev.pricing.conflict.engine',
              'Engine: rules sort by priority ascending; ties broken alphabetically; non-matching effective dates drop out; max_uses caps spill to next rule.',
            )}
          </p>
        </div>
      )}
    </span>
  );
}

// ── Price Lists tab ──────────────────────────────────────────────────

interface PriceListsTabProps {
  devId: string;
}

function PriceListsTab({ devId }: PriceListsTabProps): JSX.Element {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: '',
    effective_from: todayISO(),
    currency: 'EUR',
    notes: '',
  });

  const listsQuery = useQuery<PriceList[]>({
    queryKey: ['propdev', 'price-lists', devId],
    queryFn: () => listPriceLists(devId),
    enabled: Boolean(devId),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createPriceList(devId, {
        name: form.name.trim(),
        effective_from: form.effective_from,
        currency: form.currency.trim().toUpperCase(),
        notes: form.notes.trim() || null,
        entries: [],
        rules: [],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'price-lists', devId] });
      addToast({
        type: 'success',
        title: t('propdev.pricing.created', 'Price list created'),
      });
      setShowForm(false);
      setForm((f) => ({ ...f, name: '', notes: '' }));
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) => activatePriceList(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'price-lists', devId] });
      addToast({
        type: 'success',
        title: t('propdev.pricing.activated', 'Price list activated'),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const rows = listsQuery.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          {t('propdev.pricing.lists_title', 'Price lists')}
        </h2>
        <Button
          variant="primary"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm
            ? t('common.cancel', 'Cancel')
            : t('propdev.pricing.new', 'New price list')}
        </Button>
      </div>

      {showForm && (
        <Card padding="md">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="pl-name">
                {t('propdev.pricing.name', 'Name')}
              </label>
              <input
                id="pl-name"
                className={inputCls}
                value={form.name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, name: e.target.value }))
                }
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="pl-from">
                {t('propdev.pricing.effective_from', 'Effective from')}
              </label>
              <input
                id="pl-from"
                type="date"
                className={inputCls}
                value={form.effective_from}
                onChange={(e) =>
                  setForm((f) => ({ ...f, effective_from: e.target.value }))
                }
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="pl-cur">
                {t('propdev.pricing.currency', 'Currency')}
              </label>
              <CurrencySelect
                id="pl-cur"
                value={form.currency}
                onChange={(next) =>
                  setForm((f) => ({ ...f, currency: next.toUpperCase() }))
                }
                ariaLabel={t('propdev.pricing.currency', 'Currency')}
              />
            </div>
            <div className="sm:col-span-2">
              <label className={labelCls} htmlFor="pl-notes">
                {t('propdev.pricing.notes', 'Notes')}
              </label>
              <textarea
                id="pl-notes"
                className={clsx(inputCls, 'h-20')}
                value={form.notes}
                onChange={(e) =>
                  setForm((f) => ({ ...f, notes: e.target.value }))
                }
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              disabled={!form.name.trim() || createMutation.isPending}
              onClick={() => createMutation.mutate()}
              icon={
                createMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : undefined
              }
            >
              {t('common.create', 'Create')}
            </Button>
          </div>
        </Card>
      )}

      {listsQuery.isLoading ? (
        <SkeletonTable rows={3} columns={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Receipt className="h-8 w-8" />}
          title={t('propdev.pricing.empty_lists', 'No price lists yet')}
          description={t(
            'propdev.pricing.empty_lists_desc',
            'Create a draft list, add per-plot prices and rules, then activate it to start quoting.',
          )}
        />
      ) : (
        <Card padding="none" className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-secondary">
              <tr>
                <th className="px-3 py-2">{t('propdev.pricing.name', 'Name')}</th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.status', 'Status')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.effective_from', 'Effective from')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.currency', 'Currency')}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('common.actions', 'Actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((pl) => (
                <tr key={pl.id} className="border-t border-border">
                  <td className="px-3 py-2 font-medium">{pl.name}</td>
                  <td className="px-3 py-2">{statusBadge(pl.status)}</td>
                  <td className="px-3 py-2">{pl.effective_from}</td>
                  <td className="px-3 py-2">{pl.currency}</td>
                  <td className="px-3 py-2 text-right">
                    {pl.status === 'draft' && (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => activateMutation.mutate(pl.id)}
                        disabled={activateMutation.isPending}
                      >
                        {t('propdev.pricing.activate', 'Activate')}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

// ── Rules tab ────────────────────────────────────────────────────────

interface RulesTabProps {
  devId: string;
}

function defaultConditionFor(type: PricingRuleType): Record<string, unknown> {
  switch (type) {
    case 'early_bird':
      return { before: todayISO() };
    case 'view_premium':
      return { plot_attribute: 'view', values: ['sea'] };
    case 'floor_premium':
      return { min_floor: 10 };
    case 'corner_premium':
      return { plot_attribute: 'is_corner', value: true };
    case 'size_premium':
      return { min_area_m2: '100' };
    case 'promo_code':
      return { code: 'LAUNCH' };
    case 'friends_family':
      return { buyer_tag: 'ff' };
    case 'loyalty':
      return { prior_purchases_min: 1 };
    case 'bulk_buy':
      return { min_plots: 3 };
  }
}

function RulesTab({ devId }: RulesTabProps): JSX.Element {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const listsQuery = useQuery<PriceList[]>({
    queryKey: ['propdev', 'price-lists', devId],
    queryFn: () => listPriceLists(devId),
    enabled: Boolean(devId),
  });
  const active = useMemo(
    () => (listsQuery.data ?? []).find((p) => p.status === 'active') ?? null,
    [listsQuery.data],
  );

  const rulesQuery = useQuery<PricingRule[]>({
    queryKey: ['propdev', 'pricing-rules', active?.id],
    queryFn: () => listPricingRules(active!.id),
    enabled: Boolean(active?.id),
  });

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreatePricingRulePayload>({
    name: '',
    rule_type: 'early_bird',
    condition_json: defaultConditionFor('early_bird'),
    adjustment_pct: '0',
    adjustment_fixed: null,
    priority: 100,
    active: true,
    effective_from: '',
    effective_to: null,
    max_uses: null,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createPricingRule(active!.id, {
        ...form,
        adjustment_fixed:
          form.adjustment_fixed && String(form.adjustment_fixed).trim() !== ''
            ? form.adjustment_fixed
            : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ['propdev', 'pricing-rules', active?.id],
      });
      addToast({
        type: 'success',
        title: t('propdev.pricing.rule_created', 'Rule created'),
      });
      setShowForm(false);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMutation = useMutation({
    mutationFn: (ruleId: string) => deletePricingRule(active!.id, ruleId),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ['propdev', 'pricing-rules', active?.id],
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const reorderMutation = useMutation({
    mutationFn: (params: { ruleId: string; priority: number }) =>
      updatePricingRule(active!.id, params.ruleId, {
        priority: params.priority,
      }),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ['propdev', 'pricing-rules', active?.id],
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const rules = useMemo(() => rulesQuery.data ?? [], [rulesQuery.data]);
  const conflictMap = useMemo(() => buildConflictGroups(rules), [rules]);

  // Block submission when valid_from > valid_to (mirrors picker validation).
  const formInvalidDates = Boolean(
    form.effective_from && form.effective_to && form.effective_from > form.effective_to,
  );

  if (!active) {
    return (
      <EmptyState
        icon={<Settings2 className="h-8 w-8" />}
        title={t('propdev.pricing.no_active', 'No active price list')}
        description={t(
          'propdev.pricing.no_active_desc',
          'Activate a draft list on the Price Lists tab to start editing its rules.',
        )}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            {t('propdev.pricing.rules_title', 'Rules')}{' '}
            <span className="text-sm font-normal text-content-secondary">
              ({active.name})
            </span>
          </h2>
          <p className="text-xs text-content-secondary">
            {t(
              'propdev.pricing.rules_hint',
              'Lower priority value applies first. Click the up/down arrows to reorder. Conflicting rules show a coloured badge - hover for the precedence explanation.',
            )}
          </p>
        </div>
        <Button
          variant="primary"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm
            ? t('common.cancel', 'Cancel')
            : t('propdev.pricing.new_rule', 'New rule')}
        </Button>
      </div>

      {showForm && (
        <Card padding="md">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="rule-name">
                {t('propdev.pricing.rule_name', 'Rule name')}
              </label>
              <input
                id="rule-name"
                className={inputCls}
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <label
                className={clsx(labelCls, 'flex items-center gap-1.5')}
                htmlFor="rule-type"
              >
                {t('propdev.pricing.rule_type', 'Rule type')}
                <InfoHint
                  inline
                  text={RULE_TYPE_HELP[form.rule_type]}
                />
              </label>
              <select
                id="rule-type"
                className={inputCls}
                value={form.rule_type}
                onChange={(e) => {
                  const next = e.target.value as PricingRuleType;
                  setForm((f) => ({
                    ...f,
                    rule_type: next,
                    condition_json: defaultConditionFor(next),
                  }));
                }}
              >
                {RULE_TYPES.map((t2) => (
                  <option key={t2} value={t2}>
                    {RULE_TYPE_LABELS[t2]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="rule-pct">
                {t('propdev.pricing.adj_pct', 'Adjustment %')}
              </label>
              <input
                id="rule-pct"
                className={inputCls}
                inputMode="decimal"
                value={String(form.adjustment_pct)}
                onChange={(e) =>
                  setForm((f) => ({ ...f, adjustment_pct: e.target.value }))
                }
                placeholder="-5 = 5% off"
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="rule-fixed">
                {t('propdev.pricing.adj_fixed', 'Fixed adjustment')}
              </label>
              <input
                id="rule-fixed"
                className={inputCls}
                inputMode="decimal"
                value={String(form.adjustment_fixed ?? '')}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    adjustment_fixed: e.target.value || null,
                  }))
                }
                placeholder="-2500"
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="rule-prio">
                {t(
                  'propdev.pricing.priority',
                  'Priority (lower applies first)',
                )}
              </label>
              <input
                id="rule-prio"
                type="number"
                className={inputCls}
                value={form.priority}
                onChange={(e) =>
                  setForm((f) => ({ ...f, priority: Number(e.target.value) }))
                }
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="rule-max">
                {t(
                  'propdev.pricing.max_uses',
                  'Max uses (blank = unlimited)',
                )}
              </label>
              <input
                id="rule-max"
                type="number"
                className={inputCls}
                value={form.max_uses ?? ''}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    max_uses: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </div>
            <div className="sm:col-span-2">
              <RuleTypePreview
                ruleType={form.rule_type}
                adjustmentPct={String(form.adjustment_pct)}
                adjustmentFixed={
                  form.adjustment_fixed ? String(form.adjustment_fixed) : null
                }
                currency={active.currency}
              />
            </div>
            <div className="sm:col-span-2">
              <p className="mb-1 text-xs font-medium text-content-secondary">
                {t(
                  'propdev.pricing.time.section_title',
                  'Validity window',
                )}
              </p>
              <TimeWindowPicker
                from={form.effective_from ?? ''}
                to={form.effective_to ?? null}
                onChange={({ from, to }) =>
                  setForm((f) => ({
                    ...f,
                    effective_from: from,
                    effective_to: to,
                  }))
                }
                projectFrom={active.effective_from}
                projectTo={active.effective_to}
              />
            </div>
            <div className="sm:col-span-2">
              <label className={labelCls} htmlFor="rule-cond">
                {t('propdev.pricing.condition', 'Condition (JSON)')}
              </label>
              <textarea
                id="rule-cond"
                className={clsx(inputCls, 'h-24 font-mono')}
                value={JSON.stringify(form.condition_json, null, 2)}
                onChange={(e) => {
                  try {
                    const parsed = JSON.parse(e.target.value);
                    setForm((f) => ({ ...f, condition_json: parsed }));
                  } catch {
                    /* swallow — user is still typing */
                  }
                }}
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              onClick={() => createMutation.mutate()}
              disabled={
                !form.name.trim() ||
                createMutation.isPending ||
                formInvalidDates
              }
            >
              {t('common.create', 'Create')}
            </Button>
          </div>
        </Card>
      )}

      {rulesQuery.isLoading ? (
        <SkeletonTable rows={3} columns={5} />
      ) : rules.length === 0 ? (
        <EmptyState
          icon={<Settings2 className="h-8 w-8" />}
          title={t('propdev.pricing.empty_rules', 'No rules yet')}
          description={t(
            'propdev.pricing.empty_rules_desc',
            'Add a rule to apply discounts and premiums on top of the base price.',
          )}
        />
      ) : (
        <Card padding="none" className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-secondary">
              <tr>
                <th className="px-3 py-2 w-12">
                  {t('propdev.pricing.priority_short', 'Pri')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.rule_name', 'Name')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.rule_type', 'Type')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.adj_pct', 'Adj %')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.adj_fixed', 'Fixed')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.uses', 'Uses')}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.window', 'Window')}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('common.actions', 'Actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r, idx) => {
                const group = conflictMap.get(r.id);
                return (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-3 py-2">
                      <div className="flex flex-col items-center">
                        <button
                          type="button"
                          aria-label={t('common.move_up', { defaultValue: 'move up' })}
                          disabled={idx === 0}
                          onClick={() =>
                            reorderMutation.mutate({
                              ruleId: r.id,
                              priority: Math.max(0, r.priority - 10),
                            })
                          }
                          className="text-content-secondary hover:text-content-primary disabled:opacity-30"
                        >
                          <ChevronUp className="h-3 w-3" />
                        </button>
                        <span className="text-xs">{r.priority}</span>
                        <button
                          type="button"
                          aria-label={t('common.move_down', { defaultValue: 'move down' })}
                          disabled={idx === rules.length - 1}
                          onClick={() =>
                            reorderMutation.mutate({
                              ruleId: r.id,
                              priority: r.priority + 10,
                            })
                          }
                          className="text-content-secondary hover:text-content-primary disabled:opacity-30"
                        >
                          <ChevronDown className="h-3 w-3" />
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-2 font-medium">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span>{r.name}</span>
                        {group && (
                          <ConflictBadge
                            group={group}
                            thisRule={r}
                            allRules={rules}
                          />
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      {RULE_TYPE_LABELS[r.rule_type] ?? r.rule_type}
                    </td>
                    <td className="px-3 py-2">{r.adjustment_pct ?? '0'}</td>
                    <td className="px-3 py-2">{r.adjustment_fixed ?? '—'}</td>
                    <td className="px-3 py-2 text-content-secondary">
                      {r.times_used}
                      {r.max_uses ? `/${r.max_uses}` : ''}
                    </td>
                    <td className="px-3 py-2 text-2xs text-content-secondary whitespace-nowrap">
                      {r.effective_from || '—'}
                      {' → '}
                      {r.effective_to ? (
                        r.effective_to
                      ) : (
                        <Badge variant="neutral" size="sm">
                          {t('propdev.pricing.time.no_end_badge', 'no end date')}
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Trash2 className="h-3 w-3" />}
                        onClick={() => deleteMutation.mutate(r.id)}
                        aria-label="delete rule"
                      >
                        {t('common.delete', 'Delete')}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

// ── Simulator tab ────────────────────────────────────────────────────

function QuoteWaterfall({
  quote,
  printable,
}: {
  quote: PriceQuote;
  printable?: boolean;
}): JSX.Element {
  const { t } = useTranslation();
  const chartData = quote.lines.map((l, i) => {
    const value = Number(l.amount);
    return {
      idx: i,
      name: l.rule_name || l.rule_type,
      value,
      isBase: l.rule_type === 'base',
      isDiscount: value < 0,
    };
  });
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-content-secondary">
            {t('propdev.pricing.final_price', 'Final price')}
          </p>
          <p className="text-2xl font-semibold">
            {fmtMoney(quote.total, quote.currency)}
          </p>
        </div>
        <CheckCircle2 className="h-6 w-6 text-emerald-500" />
      </div>
      {!printable && (
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={((value: unknown) =>
                  fmtMoney(value as number, quote.currency)) as never}
              />
              <Bar dataKey="value">
                {chartData.map((d) => (
                  <Cell
                    key={d.idx}
                    fill={
                      d.isBase
                        ? '#0070f3'
                        : d.isDiscount
                          ? '#ef4444'
                          : '#22c55e'
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-secondary">
          <tr>
            <th className="px-3 py-2">{t('propdev.pricing.line', 'Line')}</th>
            <th className="px-3 py-2">{t('propdev.pricing.rule_type', 'Type')}</th>
            <th className="px-3 py-2 text-right">
              {t('propdev.pricing.amount', 'Amount')}
            </th>
          </tr>
        </thead>
        <tbody>
          {quote.lines.map((l, i) => {
            const amt = Number(l.amount);
            const isBase = l.rule_type === 'base';
            const arrow = isBase ? null : amt < 0 ? (
              <ArrowDown className="inline h-3 w-3 text-emerald-600" />
            ) : amt > 0 ? (
              <ArrowUp className="inline h-3 w-3 text-amber-700" />
            ) : (
              <ArrowRight className="inline h-3 w-3 text-content-tertiary" />
            );
            return (
              <tr key={i} className="border-t border-border">
                <td className="px-3 py-2">{l.rule_name || l.rule_type}</td>
                <td className="px-3 py-2 text-content-secondary">
                  {l.rule_type}
                </td>
                <td
                  className={clsx(
                    'px-3 py-2 text-right tabular-nums whitespace-nowrap',
                    !isBase && amt < 0 && 'text-emerald-600',
                    !isBase && amt > 0 && 'text-amber-700',
                  )}
                >
                  {arrow} {fmtMoney(l.amount, quote.currency)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SimulatorTab({ devId }: { devId: string }): JSX.Element {
  const { t } = useTranslation();
  const [plotId, setPlotId] = useState<string>('');
  const [promo, setPromo] = useState('');
  const [quote, setQuote] = useState<PriceQuote | null>(null);
  const [compareQuote, setCompareQuote] = useState<PriceQuote | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Persistent in-tab quote history so the "Compare" picker can reach
  // back N quotes without a new HTTP round-trip.
  const [savedQuotes, setSavedQuotes] = useState<PriceQuote[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const printRef = useRef<HTMLDivElement>(null);

  const listsQuery = useQuery<PriceList[]>({
    queryKey: ['propdev', 'price-lists', devId],
    queryFn: () => listPriceLists(devId),
    enabled: Boolean(devId),
  });
  const active = useMemo(
    () => (listsQuery.data ?? []).find((p) => p.status === 'active') ?? null,
    [listsQuery.data],
  );
  const plotsQuery = useQuery<Plot[]>({
    queryKey: ['propdev', 'plots', devId, 'simulator'],
    queryFn: () => listPlots({ development_id: devId, limit: 500 }),
    enabled: Boolean(devId),
  });

  useEffect(() => {
    const first = (plotsQuery.data ?? [])[0];
    if (!plotId && first) {
      setPlotId(first.id);
    }
  }, [plotsQuery.data, plotId]);

  const selectedPlot = useMemo(
    () => (plotsQuery.data ?? []).find((p) => p.id === plotId) ?? null,
    [plotsQuery.data, plotId],
  );

  const runQuote = async (): Promise<void> => {
    if (!active || !plotId) return;
    setBusy(true);
    setErr(null);
    try {
      const q = await quotePrice({
        priceListId: active.id,
        plot_id: plotId,
        promo_code: promo || undefined,
      });
      setQuote(q);
      setSavedQuotes((prev) => [q, ...prev].slice(0, 20));
    } catch (e) {
      setErr(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!active) {
    return (
      <EmptyState
        icon={<Sparkles className="h-8 w-8" />}
        title={t('propdev.pricing.no_active', 'No active price list')}
        description={t(
          'propdev.pricing.sim_no_active_desc',
          'Activate a price list to use the simulator.',
        )}
      />
    );
  }

  const plotCurrency = selectedPlot?.currency || '';
  const currencyMismatch =
    quote &&
    plotCurrency &&
    plotCurrency.toUpperCase() !== quote.currency.toUpperCase();

  const handlePrint = (): void => {
    // Use the browser native print — print-friendly CSS lives in the
    // .print-friendly class below + a media query injected once.
    window.print();
  };

  return (
    <div className="space-y-4" ref={printRef}>
      {/* Print-friendly CSS — single style tag so we don't need to add
          a global stylesheet for one feature. Hides chrome and the chart
          (chart is decorative; the table is the load-bearing render). */}
      <style>{`
        @media print {
          body * { visibility: hidden; }
          .pricing-printable, .pricing-printable * { visibility: visible; }
          .pricing-printable { position: absolute; left: 0; top: 0; width: 100%; }
          .pricing-no-print { display: none !important; }
          .recharts-wrapper, .recharts-surface { display: none !important; }
        }
      `}</style>

      <Card padding="md" className="pricing-no-print">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label className={labelCls} htmlFor="sim-plot">
              {t('propdev.pricing.sim_plot', 'Plot')}
            </label>
            <select
              id="sim-plot"
              className={inputCls}
              value={plotId}
              onChange={(e) => setPlotId(e.target.value)}
            >
              <option value="">{t('common.select', 'Select…')}</option>
              {(plotsQuery.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.plot_number}
                  {p.currency ? ` · ${p.currency}` : ''}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls} htmlFor="sim-promo">
              {t('propdev.pricing.sim_promo', 'Promo code (optional)')}
            </label>
            <input
              id="sim-promo"
              className={inputCls}
              value={promo}
              onChange={(e) => setPromo(e.target.value)}
            />
          </div>
          <div className="flex items-end gap-2">
            <Button
              variant="primary"
              icon={
                busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <PlayCircle className="h-4 w-4" />
                )
              }
              onClick={runQuote}
              disabled={busy || !plotId}
            >
              {t('propdev.pricing.compute', 'Compute quote')}
            </Button>
          </div>
        </div>
        {err && (
          <p className="mt-3 text-sm text-rose-600 flex items-center gap-2">
            <AlertOctagon className="h-4 w-4" />
            {err}
          </p>
        )}
        {currencyMismatch && (
          <p className="mt-3 flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {t(
              'propdev.pricing.sim.currency_mismatch',
              'Plot is denominated in {{plot}}, quote was computed in {{quote}}. Apply FX before contracting.',
              { plot: plotCurrency, quote: quote!.currency },
            )}
          </p>
        )}
      </Card>

      {quote && (
        <Card padding="md" className="pricing-printable">
          <div className="mb-3 flex items-center justify-between gap-2 pricing-no-print">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                icon={<Filter className="h-3.5 w-3.5" />}
                onClick={() => setCompareOpen((v) => !v)}
                disabled={savedQuotes.length < 2}
              >
                {compareOpen
                  ? t('propdev.pricing.sim.compare_close', 'Close compare')
                  : t(
                      'propdev.pricing.sim.compare_open',
                      'Compare with previous',
                    )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Printer className="h-3.5 w-3.5" />}
                onClick={handlePrint}
              >
                {t('propdev.pricing.sim.print', 'Print')}
              </Button>
            </div>
          </div>

          {compareOpen ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <p className="mb-2 text-xs font-medium text-content-secondary">
                  {t('propdev.pricing.sim.current', 'Current quote')}
                </p>
                <QuoteWaterfall quote={quote} />
              </div>
              <div>
                <p className="mb-2 text-xs font-medium text-content-secondary">
                  {t('propdev.pricing.sim.previous', 'Previous quote')}
                </p>
                <select
                  className={clsx(inputCls, 'mb-3')}
                  value={
                    compareQuote
                      ? (compareQuote.computed_at as unknown as string)
                      : ''
                  }
                  onChange={(e) => {
                    const found = savedQuotes.find(
                      (q) => String(q.computed_at) === e.target.value,
                    );
                    setCompareQuote(found ?? null);
                  }}
                >
                  <option value="">
                    {t('common.select', 'Select…')}
                  </option>
                  {savedQuotes
                    .filter(
                      (q) =>
                        String(q.computed_at) !==
                        String(quote.computed_at),
                    )
                    .map((q) => (
                      <option
                        key={String(q.computed_at)}
                        value={String(q.computed_at)}
                      >
                        {new Date(q.computed_at).toLocaleString(getIntlLocale())} —{' '}
                        {fmtMoney(q.total, q.currency)}
                      </option>
                    ))}
                </select>
                {compareQuote ? (
                  <QuoteWaterfall quote={compareQuote} />
                ) : (
                  <p className="text-xs text-content-tertiary">
                    {t(
                      'propdev.pricing.sim.pick_previous',
                      'Pick a previous quote from this session to compare side-by-side.',
                    )}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <QuoteWaterfall quote={quote} />
          )}
        </Card>
      )}
    </div>
  );
}

// ── Quote History tab ────────────────────────────────────────────────

type HistorySort = 'date_desc' | 'date_asc' | 'total_desc' | 'total_asc' | 'buyer_asc';
type StatusFilter = ReservationStatus | 'all';

function reservationStatusBadge(s: ReservationStatus): JSX.Element {
  const map: Record<
    ReservationStatus,
    { variant: 'success' | 'warning' | 'neutral' | 'error' | 'blue'; label: string }
  > = {
    active: { variant: 'success', label: 'Active' },
    expired: { variant: 'neutral', label: 'Expired' },
    converted: { variant: 'blue', label: 'Converted' },
    cancelled: { variant: 'error', label: 'Cancelled' },
    refunded: { variant: 'warning', label: 'Refunded' },
  };
  const m = map[s];
  return <Badge variant={m.variant}>{m.label}</Badge>;
}

interface HistoryDetailDrawerProps {
  reservation: Reservation | null;
  buyersById: Map<string, Buyer>;
  plotsById: Map<string, Plot>;
  activeListId: string | null;
  onClose: () => void;
}

function HistoryDetailDrawer({
  reservation,
  buyersById,
  plotsById,
  activeListId,
  onClose,
}: HistoryDetailDrawerProps): JSX.Element | null {
  const { t } = useTranslation();
  if (!reservation) return null;
  const snap = (reservation.price_breakdown_snapshot ?? {}) as {
    base_price?: string;
    total?: string;
    currency?: string;
    computed_at?: string;
    price_list_id?: string;
    lines?: Array<{ rule_name: string; rule_type?: string; amount: string }>;
  };
  const buyer = reservation.buyer_id ? buyersById.get(reservation.buyer_id) : null;
  const plot = plotsById.get(reservation.plot_id);
  const snapshotDate = snap.computed_at
    ? String(snap.computed_at).slice(0, 10)
    : null;
  const snapshotIsStale =
    activeListId &&
    snap.price_list_id &&
    snap.price_list_id !== activeListId;

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={
        <span>
          {t('propdev.pricing.history.drawer_title', 'Quote snapshot')}
          {' · '}
          {reservation.reservation_number}
        </span>
      }
      subtitle={`${plot?.plot_number ?? '—'} · ${buyer?.full_name ?? '—'}`}
    >
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          {snapshotDate && (
            <Badge variant="neutral">
              <Clock className="mr-1 inline h-3 w-3" />
              {t(
                'propdev.pricing.history.snapshot_from',
                'Snapshot from {{date}}',
                { date: snapshotDate },
              )}
            </Badge>
          )}
          {snapshotIsStale && (
            <Badge variant="warning">
              {t(
                'propdev.pricing.history.snapshot_stale',
                'Live price list has changed since',
              )}
            </Badge>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-xs text-content-tertiary">
              {t('propdev.pricing.base_price', 'Base')}
            </p>
            <p className="font-medium">
              {snap.base_price !== undefined ? (
                <MoneyDisplay
                  amount={snap.base_price}
                  currency={snap.currency ?? reservation.currency ?? 'EUR'}
                />
              ) : (
                '—'
              )}
            </p>
          </div>
          <div>
            <p className="text-xs text-content-tertiary">
              {t('propdev.pricing.total', 'Total')}
            </p>
            <p className="font-semibold">
              {snap.total !== undefined ? (
                <MoneyDisplay
                  amount={snap.total}
                  currency={snap.currency ?? reservation.currency ?? 'EUR'}
                />
              ) : (
                '—'
              )}
            </p>
          </div>
        </div>

        {snap.lines && snap.lines.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-content-secondary">
              {t('propdev.pricing.history.breakdown', 'Breakdown')}
            </p>
            <table className="w-full text-xs">
              <thead className="text-content-tertiary">
                <tr>
                  <th className="px-2 py-1 text-left">
                    {t('propdev.pricing.line', 'Line')}
                  </th>
                  <th className="px-2 py-1 text-right">
                    {t('propdev.pricing.amount', 'Amount')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {snap.lines.map((l, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="px-2 py-1">{l.rule_name}</td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      <MoneyDisplay
                        amount={l.amount}
                        currency={snap.currency ?? reservation.currency ?? 'EUR'}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div>
          <p className="mb-1 text-xs font-medium text-content-secondary">
            {t('propdev.pricing.history.audit', 'Audit')}
          </p>
          <dl className="grid grid-cols-2 gap-y-1 text-xs text-content-secondary">
            <dt>{t('propdev.pricing.history.created_at', 'Created')}</dt>
            <dd className="font-mono">{reservation.created_at}</dd>
            <dt>{t('propdev.pricing.status', 'Status')}</dt>
            <dd>{reservationStatusBadge(reservation.status)}</dd>
            <dt>{t('propdev.pricing.history.price_list', 'Price list')}</dt>
            <dd className="font-mono break-all">
              {snap.price_list_id ?? '—'}
            </dd>
          </dl>
        </div>
      </div>
    </SideDrawer>
  );
}

function QuoteHistoryTab({ devId }: { devId: string }): JSX.Element {
  const { t } = useTranslation();
  const reservationsQuery = useQuery<Reservation[]>({
    queryKey: ['propdev', 'reservations', devId, 'history'],
    queryFn: () =>
      listReservations({ development_id: devId, limit: 200 }) as Promise<
        Reservation[]
      >,
    enabled: Boolean(devId),
  });
  const plotsQuery = useQuery<Plot[]>({
    queryKey: ['propdev', 'plots', devId, 'history'],
    queryFn: () => listPlots({ development_id: devId, limit: 500 }),
    enabled: Boolean(devId),
  });
  // Fetch buyers per-status via useQueries — listBuyers requires a status
  // filter to be useful here we just take the full first page.
  const buyersQuery = useQuery<Buyer[]>({
    queryKey: ['propdev', 'buyers', devId, 'history'],
    queryFn: () => listBuyers({ development_id: devId, limit: 500 }),
    enabled: Boolean(devId),
  });
  const listsQuery = useQuery<PriceList[]>({
    queryKey: ['propdev', 'price-lists', devId],
    queryFn: () => listPriceLists(devId),
    enabled: Boolean(devId),
  });
  const activeListId = useMemo(
    () => (listsQuery.data ?? []).find((p) => p.status === 'active')?.id ?? null,
    [listsQuery.data],
  );

  const plotsById = useMemo(
    () => new Map((plotsQuery.data ?? []).map((p) => [p.id, p])),
    [plotsQuery.data],
  );
  const buyersById = useMemo(
    () => new Map((buyersQuery.data ?? []).map((b) => [b.id, b])),
    [buyersQuery.data],
  );

  // Filter & sort state
  const [filterBuyer, setFilterBuyer] = useState('');
  const [filterPlot, setFilterPlot] = useState('');
  const [filterFrom, setFilterFrom] = useState('');
  const [filterTo, setFilterTo] = useState('');
  const [filterStatus, setFilterStatus] = useState<StatusFilter>('all');
  const [sort, setSort] = useState<HistorySort>('date_desc');
  const [openRes, setOpenRes] = useState<Reservation | null>(null);

  const rows = useMemo(() => {
    const base = (reservationsQuery.data ?? []).filter(
      (r) =>
        r.price_breakdown_snapshot &&
        Object.keys(r.price_breakdown_snapshot).length > 0,
    );

    const buyerLower = filterBuyer.trim().toLowerCase();
    const plotLower = filterPlot.trim().toLowerCase();

    const filtered = base.filter((r) => {
      if (filterStatus !== 'all' && r.status !== filterStatus) return false;
      if (filterFrom && r.created_at && r.created_at.slice(0, 10) < filterFrom)
        return false;
      if (filterTo && r.created_at && r.created_at.slice(0, 10) > filterTo)
        return false;
      if (buyerLower) {
        const b = r.buyer_id ? buyersById.get(r.buyer_id) : null;
        if (!b || !b.full_name.toLowerCase().includes(buyerLower)) {
          return false;
        }
      }
      if (plotLower) {
        const p = plotsById.get(r.plot_id);
        if (!p || !p.plot_number.toLowerCase().includes(plotLower)) {
          return false;
        }
      }
      return true;
    });

    const num = (r: Reservation): number => {
      const t = (r.price_breakdown_snapshot as { total?: string })?.total;
      return t ? Number(t) : 0;
    };
    const buyerName = (r: Reservation): string => {
      const b = r.buyer_id ? buyersById.get(r.buyer_id) : null;
      return b?.full_name ?? '';
    };

    const sorted = [...filtered];
    switch (sort) {
      case 'date_asc':
        sorted.sort((a, b) =>
          (a.created_at ?? '').localeCompare(b.created_at ?? ''),
        );
        break;
      case 'date_desc':
        sorted.sort((a, b) =>
          (b.created_at ?? '').localeCompare(a.created_at ?? ''),
        );
        break;
      case 'total_asc':
        sorted.sort((a, b) => num(a) - num(b));
        break;
      case 'total_desc':
        sorted.sort((a, b) => num(b) - num(a));
        break;
      case 'buyer_asc':
        sorted.sort((a, b) => compareNames(buyerName(a), buyerName(b)));
        break;
    }
    return sorted;
  }, [
    reservationsQuery.data,
    filterStatus,
    filterFrom,
    filterTo,
    filterBuyer,
    filterPlot,
    sort,
    buyersById,
    plotsById,
  ]);

  if (reservationsQuery.isLoading)
    return <SkeletonTable rows={4} columns={4} />;
  if ((reservationsQuery.data ?? []).length === 0) {
    return (
      <EmptyState
        icon={<History className="h-8 w-8" />}
        title={t(
          'propdev.pricing.empty_history',
          'No quote snapshots yet',
        )}
        description={t(
          'propdev.pricing.empty_history_desc',
          'Quote snapshots appear here automatically when reservations are created against an active price list.',
        )}
      />
    );
  }

  const sortHeader = (
    label: string,
    asc: HistorySort,
    desc: HistorySort,
  ): ReactNode => (
    <button
      type="button"
      className="inline-flex items-center gap-1 text-xs uppercase tracking-wide text-content-secondary hover:text-content-primary"
      onClick={() => setSort(sort === desc ? asc : desc)}
    >
      {label}
      {sort === asc && <ArrowUp className="h-3 w-3" />}
      {sort === desc && <ArrowDown className="h-3 w-3" />}
    </button>
  );

  return (
    <div className="space-y-3">
      {/* Filter strip */}
      <Card padding="sm">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-5">
          <div>
            <label className={labelCls} htmlFor="hist-buyer">
              {t('propdev.pricing.history.filter_buyer', 'Buyer')}
            </label>
            <input
              id="hist-buyer"
              className={inputCls}
              value={filterBuyer}
              onChange={(e) => setFilterBuyer(e.target.value)}
              placeholder={t('common.search', 'Search…')}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="hist-plot">
              {t('propdev.pricing.history.filter_plot', 'Plot')}
            </label>
            <input
              id="hist-plot"
              className={inputCls}
              value={filterPlot}
              onChange={(e) => setFilterPlot(e.target.value)}
              placeholder={t('common.search', 'Search…')}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="hist-from">
              {t('propdev.pricing.history.filter_from', 'From')}
            </label>
            <input
              id="hist-from"
              type="date"
              className={inputCls}
              value={filterFrom}
              onChange={(e) => setFilterFrom(e.target.value)}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="hist-to">
              {t('propdev.pricing.history.filter_to', 'To')}
            </label>
            <input
              id="hist-to"
              type="date"
              className={inputCls}
              value={filterTo}
              onChange={(e) => setFilterTo(e.target.value)}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="hist-status">
              {t('propdev.pricing.status', 'Status')}
            </label>
            <select
              id="hist-status"
              className={inputCls}
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as StatusFilter)}
            >
              <option value="all">
                {t('propdev.pricing.history.status_all', 'All statuses')}
              </option>
              <option value="active">Active</option>
              <option value="expired">Expired</option>
              <option value="converted">Converted</option>
              <option value="cancelled">Cancelled</option>
              <option value="refunded">Refunded</option>
            </select>
          </div>
        </div>
        <p className="mt-2 flex items-center gap-1 text-2xs text-content-tertiary">
          <Info className="h-3 w-3" />
          {t(
            'propdev.pricing.history.filter_hint',
            'Click a row to open the breakdown drawer with audit log.',
          )}
        </p>
      </Card>

      {rows.length === 0 ? (
        <EmptyState
          icon={<History className="h-8 w-8" />}
          title={t(
            'propdev.pricing.history.no_match',
            'No matching snapshots',
          )}
          description={t(
            'propdev.pricing.history.no_match_desc',
            'Adjust the filters to see results.',
          )}
        />
      ) : (
        <Card padding="none" className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left">
              <tr>
                <th className="px-3 py-2">
                  {t('propdev.pricing.reservation_no', 'Reservation #')}
                </th>
                <th className="px-3 py-2">
                  {sortHeader(
                    t('propdev.pricing.created_at', 'Created'),
                    'date_asc',
                    'date_desc',
                  )}
                </th>
                <th className="px-3 py-2">
                  {sortHeader(
                    t('propdev.pricing.history.col_buyer', 'Buyer'),
                    'buyer_asc',
                    'buyer_asc',
                  )}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.history.col_plot', 'Plot')}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('propdev.pricing.base_price', 'Base')}
                </th>
                <th className="px-3 py-2 text-right">
                  {sortHeader(
                    t('propdev.pricing.total', 'Total'),
                    'total_asc',
                    'total_desc',
                  )}
                </th>
                <th className="px-3 py-2">
                  {t('propdev.pricing.status', 'Status')}
                </th>
                <th className="px-3 py-2 w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const snap = (r.price_breakdown_snapshot ?? {}) as {
                  base_price?: string;
                  total?: string;
                  currency?: string;
                  computed_at?: string;
                  price_list_id?: string;
                };
                const buyer = r.buyer_id ? buyersById.get(r.buyer_id) : null;
                const plot = plotsById.get(r.plot_id);
                const snapDate = snap.computed_at?.slice(0, 10);
                const stale =
                  activeListId &&
                  snap.price_list_id &&
                  snap.price_list_id !== activeListId;
                return (
                  <Fragment key={r.id}>
                    <tr
                      onClick={() => setOpenRes(r)}
                      className="cursor-pointer border-t border-border hover:bg-surface-secondary/60"
                    >
                      <td className="px-3 py-2 font-medium">
                        {r.reservation_number}
                      </td>
                      <td className="px-3 py-2 text-content-secondary whitespace-nowrap">
                        {r.created_at?.slice(0, 10) ?? '—'}
                      </td>
                      <td className="px-3 py-2">{buyer?.full_name ?? '—'}</td>
                      <td className="px-3 py-2">{plot?.plot_number ?? '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {snap.base_price ? (
                          <MoneyDisplay
                            amount={snap.base_price}
                            currency={snap.currency ?? r.currency ?? 'EUR'}
                          />
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {snap.total ? (
                          <MoneyDisplay
                            amount={snap.total}
                            currency={snap.currency ?? r.currency ?? 'EUR'}
                          />
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {reservationStatusBadge(r.status)}
                        {stale && snapDate && (
                          <span
                            title={t(
                              'propdev.pricing.history.snapshot_tip',
                              'Pricing snapshotted on {{date}} - current active list differs.',
                              { date: snapDate },
                            )}
                            className="ml-1 inline-flex items-center"
                          >
                            <Clock className="h-3 w-3 text-amber-600" />
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-content-tertiary">
                        <ArrowRight className="h-3 w-3" />
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      <HistoryDetailDrawer
        reservation={openRes}
        buyersById={buyersById}
        plotsById={plotsById}
        activeListId={activeListId}
        onClose={() => setOpenRes(null)}
      />
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────

export function PricingEnginePage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { devId = '' } = useParams<{ devId: string }>();
  const [tab, setTab] = useState<Tab>('lists');

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          {
            label: t('propdev.title', { defaultValue: 'Property Development' }),
            to: '/property-dev',
          },
          { label: t('propdev.pricing.title', { defaultValue: 'Pricing engine' }) },
        ]}
      />
      <PageHeader
        srTitle={t('propdev.pricing.title', { defaultValue: 'Pricing engine' })}
        subtitle={t('propdev.pricing.subtitle', {
          defaultValue:
            'Versioned, rule-driven sales pricing with simulator and audit history.',
        })}
      />
      <DismissibleInfo
        storageKey="propdev-pricing"
        title={t('propdev_pricing.intro_title', {
          defaultValue: 'Price units by rule, not by guess',
        })}
        more={t('propdev_pricing.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('propdev_pricing.intro_more')} /> : undefined}
        links={[
          {
            label: t('propdev.title', { defaultValue: 'Property Development' }),
            onClick: () => navigate('/property-dev'),
          },
          ...(devId
            ? [
                {
                  label: t('propdev.inventory_map.title', {
                    defaultValue: 'Inventory Map',
                  }),
                  onClick: () =>
                    navigate(
                      `/property-dev/developments/${devId}/inventory-map`,
                    ),
                },
              ]
            : []),
        ]}
      >
        {t('propdev_pricing.intro_body', {
          defaultValue:
            'Set versioned sales price lists and pricing rules for a development, then run the simulator to see what a unit would quote at before you publish it. Every quote is kept in an audit history, and the prices flow into the development’s reservations and buyer quotes.',
        })}
      </DismissibleInfo>
      <Tabs tab={tab} setTab={setTab} />
      {tab === 'lists' && <PriceListsTab devId={devId} />}
      {tab === 'rules' && <RulesTab devId={devId} />}
      {tab === 'sim' && <SimulatorTab devId={devId} />}
      {tab === 'history' && <QuoteHistoryTab devId={devId} />}
    </div>
  );
}
