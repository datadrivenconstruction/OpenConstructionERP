// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// HowItWorksPage — a single, searchable "How it works" hub that explains
// every user-facing module in plain language: what it is, how it works step
// by step, pro tips and when to use it. Each module can also dim the rest of
// the app and spotlight its own sidebar entry ("Show me where"), reusing the
// tested ModuleGuide spotlight, so a new user sees exactly where it lives.
//
// Content lives in ./moduleExplanations (one file per domain). Every string is
// read via t(key, { defaultValue }) so English renders immediately and the
// other locales fill in as translations land.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  // chrome
  Activity,
  GraduationCap,
  Search,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  ArrowUpDown,
  Compass,
  Lightbulb,
  // module icons (curated set; unknown names fall back to Boxes)
  LayoutDashboard,
  FolderKanban,
  FolderOpen,
  Calculator,
  FileText,
  Wand2,
  Link2,
  Brain,
  Layers3,
  Ruler,
  PencilRuler,
  Box,
  Database,
  Map,
  Mountain,
  Library,
  Boxes,
  BarChart3,
  CalendarDays,
  GanttChartSquare,
  ClipboardList,
  ClipboardCheck,
  TrendingUp,
  Dices,
  Gauge,
  Network,
  Sparkles,
  Scan,
  Building2,
  Home,
  Handshake,
  FileSignature,
  ShoppingCart,
  Truck,
  HardHat,
  Leaf,
  Recycle,
  MessageSquare,
  Mail,
  Send,
  FileBarChart,
  PieChart,
  Bot,
  MessageCircle,
  Plug,
  Settings,
  ShieldAlert,
  ShieldCheck,
  GitCompare,
  Workflow,
  Users,
  type LucideIcon,
} from 'lucide-react';

import { ModuleGuide, type ModuleGuideContent } from '@/shared/ui';
import { StepScene } from '@/features/cases/StepScene';
import {
  MODULE_EXPLANATIONS,
  groupByCategory,
  type ModuleExplanation,
} from './moduleExplanations';
import { useHelpOrderStore, type HelpSortMode } from './useHelpOrderStore';
import { useNameCollator } from '@/shared/lib/collator';

/* ── Icon resolution ────────────────────────────────────────────────────── */

const ICONS: Record<string, LucideIcon> = {
  Activity,
  LayoutDashboard,
  FolderKanban,
  FolderOpen,
  Calculator,
  FileText,
  Wand2,
  Link2,
  Brain,
  Layers3,
  Ruler,
  PencilRuler,
  Box,
  Database,
  Map,
  Mountain,
  Library,
  Boxes,
  BarChart3,
  CalendarDays,
  GanttChartSquare,
  ClipboardList,
  ClipboardCheck,
  TrendingUp,
  Dices,
  Gauge,
  Network,
  Sparkles,
  Scan,
  Building2,
  Home,
  Handshake,
  FileSignature,
  ShoppingCart,
  Truck,
  HardHat,
  Leaf,
  Recycle,
  MessageSquare,
  Mail,
  Send,
  FileBarChart,
  PieChart,
  Bot,
  MessageCircle,
  Plug,
  Settings,
  ShieldAlert,
  ShieldCheck,
  GitCompare,
  Workflow,
  Users,
};

function iconFor(name: string): LucideIcon {
  return ICONS[name] ?? Boxes;
}

/* ── A single expandable module card ────────────────────────────────────── */

interface CardProps {
  module: ModuleExplanation;
  /** 1-based position within its section, shown as a sequence badge so the
   *  intended reading order is obvious at a glance. */
  index: number;
  expanded: boolean;
  onToggle: () => void;
  onLocate: () => void;
  onOpen: () => void;
}

function ModuleCard({ module, index, expanded, onToggle, onLocate, onOpen }: CardProps) {
  const { t } = useTranslation();
  const Icon = iconFor(module.icon);

  const title = t(module.titleKey, { defaultValue: module.titleDefault });
  const summary = t(module.summaryKey, { defaultValue: module.summaryDefault });
  const what = t(module.whatKey, { defaultValue: module.whatDefault });
  const when =
    module.whenKey && module.whenDefault
      ? t(module.whenKey, { defaultValue: module.whenDefault })
      : null;

  const panelId = `howto-panel-${module.id}`;

  return (
    <div
      data-testid={`howto-card-${module.id}`}
      className={clsx(
        'rounded-2xl border bg-surface-elevated transition-colors',
        expanded
          ? 'border-oe-blue/40 shadow-md'
          : 'border-border-light hover:border-oe-blue/30 hover:shadow-sm',
      )}
    >
      {/* Header — the always-visible summary row, toggles the detail panel. */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="flex w-full items-start gap-3 rounded-2xl p-4 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
      >
        <span
          aria-hidden="true"
          className="relative mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-oe-blue/15 to-oe-blue/5 text-oe-blue ring-1 ring-inset ring-oe-blue/15"
        >
          <Icon size={19} strokeWidth={2} />
          {/* Sequence badge - makes the intended reading order obvious. */}
          <span className="absolute -left-1.5 -top-1.5 flex h-5 min-w-[1.25rem] items-center justify-center rounded-full border border-surface-elevated bg-slate-900/85 px-1 text-2xs font-bold tabular-nums text-white shadow-sm dark:bg-slate-700">
            {index}
          </span>
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-content-primary">
              {title}
            </span>
            {module.beta && (
              <span className="shrink-0 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
                {t('howto.beta', { defaultValue: 'Beta' })}
              </span>
            )}
          </span>
          <span className="mt-0.5 block text-xs leading-relaxed text-content-secondary">
            {summary}
          </span>
        </span>
        <ChevronDown
          size={16}
          className={clsx(
            'mt-1 shrink-0 text-content-tertiary transition-transform',
            expanded && 'rotate-180',
          )}
          aria-hidden="true"
        />
      </button>

      {/* Detail panel. */}
      {expanded && (
        <div id={panelId} className="px-4 pb-4">
          {/* Line-art visual of what this module does (reuses the cases scenes). */}
          <StepScene
            icon={module.icon}
            fallbackIcon={Icon}
            title={title}
            className="mb-3 h-28 w-full"
          />
          <div className="rounded-xl bg-surface-secondary/50 p-3.5">
            <p className="text-[13px] leading-relaxed text-content-secondary">{what}</p>

            {/* How it works — ordered steps. */}
            <p className="mt-3.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('howto.how_heading', { defaultValue: 'How it works' })}
            </p>
            <ol className="mt-1.5 space-y-1.5">
              {module.how.map((step, i) => (
                <li key={step.key} className="flex gap-2.5 text-[13px] text-content-secondary">
                  <span
                    aria-hidden="true"
                    className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-semibold tabular-nums text-oe-blue"
                  >
                    {i + 1}
                  </span>
                  <span className="leading-relaxed">
                    {t(step.key, { defaultValue: step.default })}
                  </span>
                </li>
              ))}
            </ol>

            {/* Tips. */}
            {module.tips && module.tips.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {module.tips.map((tip) => (
                  <li
                    key={tip.key}
                    className="flex gap-2 rounded-lg bg-amber-500/5 px-2.5 py-1.5 text-xs leading-relaxed text-content-secondary ring-1 ring-inset ring-amber-500/10"
                  >
                    <Lightbulb size={13} className="mt-0.5 shrink-0 text-amber-500" aria-hidden="true" />
                    <span>{t(tip.key, { defaultValue: tip.default })}</span>
                  </li>
                ))}
              </ul>
            )}

            {/* When to use. */}
            {when && (
              <p className="mt-3 text-xs leading-relaxed text-content-tertiary">
                <span className="font-semibold text-content-secondary">
                  {t('howto.when_heading', { defaultValue: 'When to use it: ' })}
                </span>
                {when}
              </p>
            )}
          </div>

          {/* Actions. */}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onLocate}
              data-testid={`howto-locate-${module.id}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <Compass size={13} />
              {t('howto.show_me', { defaultValue: 'Show me where' })}
            </button>
            <button
              type="button"
              onClick={onOpen}
              data-testid={`howto-open-${module.id}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              {t('howto.open_module', { defaultValue: 'Open module' })}
              <ArrowRight size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Sort control ───────────────────────────────────────────────────────── */

const SORT_OPTIONS: { mode: HelpSortMode; labelKey: string; labelDefault: string }[] = [
  { mode: 'lifecycle', labelKey: 'howto.sort.lifecycle', labelDefault: 'Lifecycle' },
  { mode: 'alphabetical', labelKey: 'howto.sort.alphabetical', labelDefault: 'Alphabetical' },
  { mode: 'custom', labelKey: 'howto.sort.custom', labelDefault: 'Custom' },
];

/* ── Page ───────────────────────────────────────────────────────────────── */

export function HowItWorksPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [locate, setLocate] = useState<ModuleExplanation | null>(null);

  const { mode, customOrder, setMode, moveCategory } = useHelpOrderStore();

  // Resolve searchable text per module in the active locale, so search works
  // in whatever language the user reads.
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return MODULE_EXPLANATIONS;
    return MODULE_EXPLANATIONS.filter((m) => {
      const hay = [
        t(m.titleKey, { defaultValue: m.titleDefault }),
        t(m.summaryKey, { defaultValue: m.summaryDefault }),
        t(m.whatKey, { defaultValue: m.whatDefault }),
        m.keywords ?? '',
        m.id,
      ]
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [query, t]);

  // `groups` comes back in the canonical lifecycle order. Re-order the sections
  // per the user's chosen sort mode: keep lifecycle as-is, sort alphabetically
  // by the localized section label, or follow the saved custom order.
  const compareNames = useNameCollator();
  const groups = useMemo(() => groupByCategory(filtered), [filtered]);
  const orderedGroups = useMemo(() => {
    if (mode === 'alphabetical') {
      // These labels are already translated, so "alphabetical" means the
      // alphabet of the language they are written in - the one the reader
      // picked, which is not necessarily the browser's.
      return [...groups].sort((a, b) =>
        compareNames(
          t(a.category.labelKey, { defaultValue: a.category.labelDefault }),
          t(b.category.labelKey, { defaultValue: b.category.labelDefault }),
        ),
      );
    }
    if (mode === 'custom') {
      // `customOrder` holds every category (reconciled on load), so indexOf
      // always resolves. (`Map` is a lucide icon in this file, so avoid it.)
      return [...groups].sort(
        (a, b) => customOrder.indexOf(a.category.id) - customOrder.indexOf(b.category.id),
      );
    }
    return groups;
  }, [groups, mode, customOrder, t, compareNames]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Build a one-card ModuleGuide that dims the app and spotlights the module's
  // sidebar entry. Degrades to a centred card if the entry is not on screen
  // (module disabled, group collapsed, or no sidebar link).
  const guideContent: ModuleGuideContent | null = useMemo(() => {
    if (!locate) return null;
    return {
      titleKey: locate.titleKey,
      titleDefault: locate.titleDefault,
      sections: [
        {
          icon: 'Search',
          titleKey: 'howto.locate.title',
          titleDefault: 'Where to find it',
          bodyKey: locate.summaryKey,
          bodyDefault: locate.summaryDefault,
          spotlightSelector: `[data-testid="app-sidebar"] a[href="${locate.spotlightRoute ?? locate.route}"]`,
        },
      ],
      ctaKey: 'howto.locate.open',
      ctaDefault: 'Open this module',
    };
  }, [locate]);

  const totalCount = MODULE_EXPLANATIONS.length;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6" data-testid="how-it-works-page">
      {/* Header. */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-oe-blue">
          <GraduationCap size={18} strokeWidth={2} />
          <span className="text-2xs font-semibold uppercase tracking-wide">
            {t('howto.eyebrow', { defaultValue: 'Help center' })}
          </span>
        </div>
        <h1 className="mt-1 text-2xl font-bold text-content-primary">
          {t('howto.page_title', { defaultValue: 'How it works' })}
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-content-secondary">
          {t('howto.page_subtitle', {
            defaultValue:
              'A plain-language guide to every module: what it does, how to use it step by step, and where to find it. Search below, expand any card to learn more, or use "Show me where" to have the app point it out for you.',
          })}
        </p>
      </div>

      {/* Search + section order control. */}
      <div className="sticky top-0 z-10 -mx-4 mb-6 bg-surface/80 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              size={16}
              className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary"
              aria-hidden="true"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-testid="howto-search"
              placeholder={t('howto.search_placeholder', {
                defaultValue: 'Search modules - e.g. "cost", "schedule", "clash"...',
              })}
              aria-label={t('howto.search_placeholder', { defaultValue: 'Search modules' })}
              className="w-full rounded-xl border border-border-light bg-surface-elevated py-2.5 ps-9 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/40 focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
            />
          </div>

          {/* Sort: how the sections read top to bottom. */}
          <div className="flex shrink-0 items-center gap-2">
            <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              <ArrowUpDown size={12} aria-hidden="true" />
              {t('howto.sort.label', { defaultValue: 'Sort' })}
            </span>
            <div
              role="group"
              aria-label={t('howto.sort.aria', { defaultValue: 'Order the sections' })}
              className="inline-flex rounded-lg border border-border-light bg-surface-elevated p-0.5"
            >
              {SORT_OPTIONS.map((opt) => (
                <button
                  key={opt.mode}
                  type="button"
                  onClick={() => setMode(opt.mode)}
                  aria-pressed={mode === opt.mode}
                  data-testid={`howto-sort-${opt.mode}`}
                  className={clsx(
                    'rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                    mode === opt.mode
                      ? 'bg-oe-blue text-white shadow-sm'
                      : 'text-content-secondary hover:text-content-primary',
                  )}
                >
                  {t(opt.labelKey, { defaultValue: opt.labelDefault })}
                </button>
              ))}
            </div>
          </div>
        </div>

        <p className="mt-1.5 text-2xs text-content-tertiary">
          {query.trim()
            ? t('howto.result_count', {
                defaultValue: '{{count}} of {{total}} modules',
                count: filtered.length,
                total: totalCount,
              })
            : mode === 'custom'
              ? t('howto.sort.custom_hint', {
                  defaultValue:
                    'Custom order - use the up and down arrows on each section to arrange them.',
                })
              : t('howto.total_count', {
                  defaultValue: '{{total}} modules explained',
                  total: totalCount,
                })}
        </p>
      </div>

      {/* Grouped sections. */}
      {orderedGroups.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border py-16 text-center">
          <p className="text-sm text-content-secondary">
            {t('howto.no_results', { defaultValue: 'No modules match your search.' })}
          </p>
        </div>
      ) : (
        <div className="space-y-10">
          {orderedGroups.map(({ category, modules }) => {
            const rank = customOrder.indexOf(category.id);
            const canMoveUp = mode === 'custom' && rank > 0;
            const canMoveDown = mode === 'custom' && rank >= 0 && rank < customOrder.length - 1;
            return (
              <section key={category.id} data-testid={`howto-section-${category.id}`}>
                <div className="mb-3 flex items-start justify-between gap-3 border-b border-border-light pb-2">
                  <div className="min-w-0">
                    <h2 className="text-base font-semibold text-content-primary">
                      {t(category.labelKey, { defaultValue: category.labelDefault })}
                      <span className="ml-2 text-xs font-normal text-content-tertiary">
                        {modules.length}
                      </span>
                    </h2>
                    <p className="mt-0.5 text-xs text-content-tertiary">
                      {t(category.descKey, { defaultValue: category.descDefault })}
                    </p>
                  </div>
                  {/* Custom order: nudge this section up or down. */}
                  {mode === 'custom' && (
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => moveCategory(category.id, -1)}
                        disabled={!canMoveUp}
                        data-testid={`howto-move-up-${category.id}`}
                        aria-label={t('howto.sort.move_up', {
                          defaultValue: 'Move section up',
                        })}
                        className="flex h-7 w-7 items-center justify-center rounded-lg border border-border-light text-content-secondary transition-colors hover:border-oe-blue/30 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-light disabled:hover:text-content-secondary"
                      >
                        <ChevronUp size={15} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => moveCategory(category.id, 1)}
                        disabled={!canMoveDown}
                        data-testid={`howto-move-down-${category.id}`}
                        aria-label={t('howto.sort.move_down', {
                          defaultValue: 'Move section down',
                        })}
                        className="flex h-7 w-7 items-center justify-center rounded-lg border border-border-light text-content-secondary transition-colors hover:border-oe-blue/30 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-light disabled:hover:text-content-secondary"
                      >
                        <ChevronDown size={15} aria-hidden="true" />
                      </button>
                    </div>
                  )}
                </div>
                {/* Row-major grid so cards read left-to-right, top-to-bottom in
                    order (CSS columns filled one column fully first, which read
                    out of sequence). `items-start` keeps an expanded card from
                    stretching its row neighbour. */}
                <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2">
                  {modules.map((m, i) => (
                    <ModuleCard
                      key={m.id}
                      module={m}
                      index={i + 1}
                      expanded={expanded.has(m.id)}
                      onToggle={() => toggle(m.id)}
                      onLocate={() => setLocate(m)}
                      onOpen={() => navigate(m.route)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Spotlight overlay. */}
      {locate && guideContent && (
        <ModuleGuide
          open
          content={guideContent}
          onClose={() => setLocate(null)}
          onCta={() => {
            const route = locate.route;
            setLocate(null);
            navigate(route);
          }}
        />
      )}
    </div>
  );
}

export default HowItWorksPage;
