// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The packs catalogue: filters, sections by market, cards and the dialogs
 * that activate or deactivate a pack.
 *
 * One implementation for two places. ``/packs`` draws it under its own
 * header; the Modules page draws it inside its Packs tab (``embedded``). The
 * filters live in the query string in both, so a filtered view is a link that
 * can be shared and survives a reload.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowUpRight,
  Briefcase,
  ChevronDown,
  Package,
  PackageOpen,
  Power,
  RefreshCw,
  Search,
  SearchX,
  UploadCloud,
  X,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { PackEmblem } from '@/shared/ui/PackEmblem';
import { detectCountry } from '@/app/i18n';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import { packNameSlug, packSummary } from '@/shared/lib/regionalPack';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { PartnerPackApplyDialog } from '../PartnerPackApplyDialog';
import { PartnerPackDeactivateDialog } from '../PartnerPackDeactivateDialog';
import { canInstallPacks, useAppliedPack, useInstalledPackList, type AppliedInfo } from '../partnerPacks';
import { CompanyProfileCard, sortPresets, type CompanyPresetAPI, type CompanyProfilesState } from '../companyProfiles';
import {
  buildPackEntries,
  companyPackMatches,
  filterPackEntries,
  foldText,
  groupPackEntries,
  hasActivePackFilters,
  packFacetCounts,
  packSectionId,
  parsePackFilters,
  writePackFilters,
  EMPTY_PACK_FILTERS,
  PACK_REGIONS,
  PACK_SORTS,
  PACK_STATUSES,
  PACK_TYPES,
  type CompanyPackEntry,
  type PackEntry,
  type PackFilters,
  type PackGroup,
} from './packCatalog';
import { PackCard } from './PackCard';
import { InstallPackPanel, ViewerPackNotice } from './InstallPackPanel';
import {
  PACK_TYPE_META,
  useBandLabels,
  useDisplayNames,
  useSortLabels,
  useStatusLabels,
} from './packLabels';

/** How long the search box waits after the last keystroke before it writes the URL. */
const SEARCH_URL_DELAY_MS = 250;

/* ── Data ───────────────────────────────────────────────────────────────── */

/** The catalogue's data, worked out once per fetch and per language. */
export function usePackCatalogData() {
  const { t } = useTranslation();
  const list = useInstalledPackList();
  const applied = useAppliedPack();
  const names = useDisplayNames();
  const homeCountry = useMemo(() => detectCountry(), []);
  const packs = useMemo(() => list.data?.installed ?? [], [list.data]);
  const activeSlug = list.data?.active_slug ?? null;
  const activeSource: AppliedInfo['source'] = applied.data?.applied ? applied.data.source ?? null : null;

  const entries = useMemo(
    () =>
      buildPackEntries(packs, {
        homeCountry,
        // Sort and search on the string the card renders. Written inline
        // because the computed-key gate recognises `modules.pp_name_*` only
        // in this exact shape.
        nameOf: (p) => t(`modules.pp_name_${packNameSlug(p.slug)}`, { defaultValue: p.partner_name }),
        summaryOf: (p) => t(`modules.pp_desc_${packNameSlug(p.slug)}`, { defaultValue: p.description }),
        countryNameOf: names.countryName,
        languageNameOf: names.languageName,
      }),
    [packs, homeCountry, t, names],
  );

  return { list, applied, entries, activeSlug, activeSource, names };
}

/* ── Scroll spy ─────────────────────────────────────────────────────────── */

/** The first section in document order that crosses the upper part of the
 *  viewport. Falls back to the first section when nothing is observed. */
function useScrollSpy(ids: readonly string[]): string | null {
  const key = ids.join('|');
  const [active, setActive] = useState<string | null>(ids[0] ?? null);
  useEffect(() => {
    const list = key ? key.split('|') : [];
    setActive((current) => (current && list.includes(current) ? current : list[0] ?? null));
    if (!list.length || typeof IntersectionObserver === 'undefined') return undefined;
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (records) => {
        for (const r of records) {
          if (r.isIntersecting) visible.add(r.target.id);
          else visible.delete(r.target.id);
        }
        const first = list.find((id) => visible.has(id));
        if (first) setActive(first);
      },
      { rootMargin: '-120px 0px -55% 0px', threshold: 0 },
    );
    for (const id of list) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [key]);
  return active;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
}

/** Scroll a section into view and move focus to its heading, so a keyboard
 *  reader lands where a pointer reader looks. */
function jumpToSection(sectionId: string) {
  const el = document.getElementById(sectionId);
  if (!el) return;
  el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
  el.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true });
}

/* ── Small controls ─────────────────────────────────────────────────────── */

function FilterSelect({
  label,
  value,
  onChange,
  children,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
  testId?: string;
}) {
  const id = useId();
  const active = value !== '';
  return (
    <div
      className={clsx(
        'relative inline-flex h-9 min-w-0 items-center rounded-lg border bg-surface-primary text-sm transition-colors',
        'focus-within:ring-2 focus-within:ring-oe-blue/30',
        active ? 'border-oe-blue/50 bg-oe-blue/5' : 'border-border hover:border-content-tertiary/50',
      )}
    >
      <label htmlFor={id} className="shrink-0 ps-3 text-xs text-content-tertiary">
        {label}
      </label>
      <select
        id={id}
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={clsx(
          'h-full min-w-0 flex-1 cursor-pointer appearance-none truncate bg-transparent pe-8 ps-1.5 text-sm outline-none',
          active ? 'font-medium text-oe-blue' : 'text-content-primary',
        )}
      >
        {children}
      </select>
      <ChevronDown size={14} aria-hidden className="pointer-events-none absolute end-2.5 text-content-tertiary" />
    </div>
  );
}

/* ── Active pack spotlight ──────────────────────────────────────────────── */

function ActivePackSpotlight({
  entry,
  applied,
  activeSource,
  canInstall,
  regionLabel,
  languageName,
  backTo,
  onDeactivate,
  onUpdate,
}: {
  entry: PackEntry;
  applied: AppliedInfo | undefined;
  activeSource: AppliedInfo['source'];
  canInstall: boolean;
  regionLabel: string;
  languageName: (code: string) => string | null;
  backTo: string;
  onDeactivate: () => void;
  onUpdate: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { pack } = entry;
  const summary = packSummary(
    t(`modules.pp_desc_${packNameSlug(pack.slug)}`, { defaultValue: pack.description }),
  );
  const appliedAt = useMemo(() => {
    if (!applied?.applied_at) return null;
    const d = new Date(applied.applied_at);
    if (Number.isNaN(d.getTime())) return null;
    return fmtDate(applied.applied_at, { dateStyle: 'medium' });
  }, [applied?.applied_at, i18n.language]);
  const accent = pack.branding.accent_color ?? pack.branding.primary_color;
  const languages = fmtList(entry.languages.map((l) => languageName(l) ?? l.toUpperCase()));

  return (
    <section
      aria-labelledby="packs-active-title"
      data-testid="packs-active-spotlight"
      className="relative overflow-hidden rounded-2xl border border-semantic-success/40 bg-surface-elevated p-5 shadow-sm"
    >
      {/* A wash of the pack's own colours, faint enough for text in both themes. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.07] dark:opacity-[0.12]"
        style={{ background: `linear-gradient(120deg, ${pack.branding.primary_color} 0%, ${accent} 55%, transparent 85%)` }}
      />
      <div className="relative flex flex-col gap-4 md:flex-row md:items-center">
        <PackEmblem pack={pack} size={60} />
        <div className="min-w-0 flex-1">
          <p className="inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-semantic-success">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-semantic-success opacity-60 motion-safe:animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-semantic-success" />
            </span>
            {t('packs.active_eyebrow', { defaultValue: 'Active pack' })}
          </p>
          <h2 id="packs-active-title" className="mt-1 text-lg font-bold leading-snug text-content-primary">
            {entry.name}
          </h2>
          {summary && <p className="mt-0.5 text-sm text-content-secondary">{summary}</p>}
          <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-content-tertiary">
            <span>{entry.countryName ? `${entry.countryName} · ${regionLabel}` : regionLabel}</span>
            <span aria-hidden>·</span>
            <span className="font-mono">{pack.default_currency}</span>
            {languages && (
              <>
                <span aria-hidden>·</span>
                <span>{languages}</span>
              </>
            )}
            <span aria-hidden>·</span>
            <span className="font-mono">v{pack.pack_version}</span>
            {appliedAt && (
              <>
                <span aria-hidden>·</span>
                <span>{t('packs.active_since', { defaultValue: 'Active since {{date}}', date: appliedAt })}</span>
              </>
            )}
          </p>
          {activeSource === 'env' && (
            <p className="mt-2 text-xs text-content-tertiary">
              {t('modules.pack_active_via_env', { defaultValue: 'Active via environment (OE_PACK)' })}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 md:flex-col md:items-stretch">
          <Link
            to={`/packs/${encodeURIComponent(pack.slug)}`}
            state={{ backTo }}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 text-sm font-medium text-content-primary shadow-xs transition-colors hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            {t('packs.see_changes', { defaultValue: 'See what it changed' })}
            <ArrowUpRight size={14} aria-hidden className="rtl:-scale-x-100" />
          </Link>
          {canInstall && applied?.update_available && activeSource !== 'env' && (
            <Button variant="primary" size="sm" icon={<RefreshCw size={14} />} onClick={onUpdate}>
              {t('packs.update_to', {
                defaultValue: 'Update to v{{version}}',
                version: applied.available_version ?? '',
              })}
            </Button>
          )}
          {canInstall && activeSource !== 'env' && (
            <Button variant="ghost" size="sm" icon={<Power size={14} />} onClick={onDeactivate}>
              {t('modules.pack_deactivate', { defaultValue: 'Deactivate' })}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

/* ── Skeleton ───────────────────────────────────────────────────────────── */

function CardSkeleton() {
  return (
    <div className="flex h-[15.5rem] flex-col rounded-xl border border-border-light bg-surface-elevated p-4" aria-hidden>
      <div className="flex items-start gap-3">
        <div className="h-11 w-11 animate-pulse rounded-xl bg-surface-secondary" />
        <div className="flex-1 space-y-2 pt-1">
          <div className="h-4 w-2/3 animate-pulse rounded bg-surface-secondary" />
          <div className="h-3 w-1/3 animate-pulse rounded bg-surface-secondary" />
        </div>
      </div>
      <div className="mt-4 space-y-2">
        <div className="h-3 w-full animate-pulse rounded bg-surface-secondary" />
        <div className="h-3 w-4/5 animate-pulse rounded bg-surface-secondary" />
      </div>
      <div className="mt-4 flex gap-1.5">
        <div className="h-5 w-16 animate-pulse rounded-md bg-surface-secondary" />
        <div className="h-5 w-10 animate-pulse rounded-md bg-surface-secondary" />
        <div className="h-5 w-14 animate-pulse rounded-md bg-surface-secondary" />
      </div>
      <div className="mt-auto flex justify-between">
        <div className="h-4 w-14 animate-pulse rounded bg-surface-secondary" />
        <div className="h-8 w-24 animate-pulse rounded-lg bg-surface-secondary" />
      </div>
    </div>
  );
}

const CARD_GRID = 'grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,17.5rem),1fr))]';

const COMPANY_SECTION_ID = 'packs-section-company';

interface CompanyCatalogEntry extends CompanyPackEntry {
  preset: CompanyPresetAPI;
}

/* ── Catalogue ──────────────────────────────────────────────────────────── */

export interface PacksCatalogProps {
  /** Drawn inside the Modules page tab rather than on its own page. */
  embedded?: boolean;
  /** Pin the active pack above the sections. The packs page shows it in its
   *  "your setup" strip instead, so it passes false. */
  spotlight?: boolean;
  /** Company types to list as one more kind of pack, beside the installed
   *  ones. Left out, the catalogue shows installed packs only. */
  companies?: CompanyProfilesState;
}

export function PacksCatalog({ embedded = false, spotlight: withSpotlight = embedded, companies }: PacksCatalogProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const addToast = useToastStore((s) => s.addToast);
  const canInstall = canInstallPacks(useAuthStore((s) => s.userRole));
  const { list, applied, entries, activeSlug, activeSource, names } = usePackCatalogData();
  const bandLabels = useBandLabels();
  const sortLabels = useSortLabels();
  const statusLabels = useStatusLabels();

  /* Filters: the URL is the source of truth, except the search box, which
     filters on every keystroke and writes the URL once typing pauses. */
  const urlFilters = useMemo(() => parsePackFilters(searchParams), [searchParams]);
  const [qInput, setQInput] = useState(urlFilters.q);
  useEffect(() => setQInput(urlFilters.q), [urlFilters.q]);
  const filters: PackFilters = useMemo(() => ({ ...urlFilters, q: qInput }), [urlFilters, qInput]);

  const setFilters = useCallback(
    (patch: Partial<PackFilters>) => {
      setSearchParams((prev) => writePackFilters(prev, { ...parsePackFilters(prev), ...patch }), { replace: true });
    },
    [setSearchParams],
  );

  const qTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (qTimer.current) clearTimeout(qTimer.current);
  }, []);
  const onSearch = (value: string) => {
    setQInput(value);
    if (qTimer.current) clearTimeout(qTimer.current);
    qTimer.current = setTimeout(() => setFilters({ q: value }), SEARCH_URL_DELAY_MS);
  };
  const clearAll = () => {
    if (qTimer.current) clearTimeout(qTimer.current);
    setQInput('');
    setFilters({ ...EMPTY_PACK_FILTERS, sort: urlFilters.sort });
  };

  const filtering = hasActivePackFilters(filters);
  const filtered = useMemo(() => filterPackEntries(entries, filters, activeSlug), [entries, filters, activeSlug]);
  const counts = useMemo(() => packFacetCounts(entries, filters, activeSlug), [entries, filters, activeSlug]);
  const activeEntry = useMemo(() => entries.find((e) => e.slug === activeSlug) ?? null, [entries, activeSlug]);
  // The active pack is pinned above the sections while nothing is filtered,
  // and joins the results like any other pack once something is.
  const spotlight = withSpotlight && !filtering ? activeEntry : null;
  const groups = useMemo(
    () =>
      groupPackEntries(
        spotlight ? filtered.filter((e) => e !== spotlight) : filtered,
        filters.sort,
        names.locale,
      ),
    [filtered, spotlight, filters.sort, names.locale],
  );
  const presets = companies?.presets;
  const profileName = companies?.profileName;
  const activeProfileKey = companies?.activeProfileKey ?? null;
  const companyEntries = useMemo<CompanyCatalogEntry[]>(
    () =>
      profileName
        ? sortPresets(presets ?? []).map((p) => ({
            preset: p,
            key: p.key,
            haystack: foldText(
              [
                profileName(p),
                p.label,
                p.description,
                t(`onboarding.company_${p.key}_desc`, { defaultValue: p.description }),
                ...(p.tags ?? []),
              ].join(' '),
            ),
          }))
        : [],
    [presets, profileName, t],
  );
  const shownCompanies = useMemo(
    () => companyEntries.filter((e) => companyPackMatches(e, filters, activeProfileKey)),
    [companyEntries, filters, activeProfileKey],
  );
  const companyCount = useMemo(
    () => companyEntries.filter((e) => companyPackMatches(e, filters, activeProfileKey, 'type')).length,
    [companyEntries, filters, activeProfileKey],
  );
  const companyStatusCounts = useMemo(() => {
    const n = { active: 0, available: 0 };
    for (const e of companyEntries) {
      if (companyPackMatches(e, filters, activeProfileKey, 'status')) n[e.key === activeProfileKey ? 'active' : 'available'] += 1;
    }
    return n;
  }, [companyEntries, filters, activeProfileKey]);

  const companiesLabel = t('packs.stat_company_types', { defaultValue: 'Company types' });
  const sections = useMemo(() => {
    // ``group: null`` is the company-type section, which is not a market band.
    const list: { id: string; group: PackGroup['id'] | null; count: number }[] = groups.map((g) => ({
      id: packSectionId(g.id),
      group: g.id,
      count: g.entries.length,
    }));
    if (shownCompanies.length) list.push({ id: COMPANY_SECTION_ID, group: null, count: shownCompanies.length });
    return list;
  }, [groups, shownCompanies.length]);
  const sectionIds = useMemo(() => sections.map((s) => s.id), [sections]);
  const spied = useScrollSpy(sectionIds);
  const showNav = sections.length > 1;

  const languageOptions = useMemo(() => {
    const all = new Set<string>();
    for (const e of entries) for (const l of e.languages) all.add(l);
    const collator = new Intl.Collator(names.locale, { sensitivity: 'base' });
    return [...all]
      .map((code) => ({ code, name: names.languageName(code) ?? code.toUpperCase() }))
      .sort((a, b) => collator.compare(a.name, b.name));
  }, [entries, names]);

  const groupLabel = (id: PackGroup['id']) =>
    id === 'all' ? t('packs.section_all', { defaultValue: 'All packs' }) : bandLabels[id];

  /* Dialogs: one of each for the whole catalogue rather than two per card. */
  const [applyTarget, setApplyTarget] = useState<PackEntry | null>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const onActivate = useCallback(
    (entry: PackEntry) => {
      if (activeSource === 'env') {
        addToast({
          type: 'warning',
          title: t('modules.pack_active_via_env', { defaultValue: 'Active via environment (OE_PACK)' }),
          message: t('modules.env_pinned_warning', {
            defaultValue:
              'A partner pack is pinned via the OE_PARTNER_PACK environment variable. Ask your administrator to change it.',
          }),
        });
        return;
      }
      setApplyTarget(entry);
      setApplyOpen(true);
    },
    [activeSource, addToast, t],
  );
  const onDeactivate = useCallback(() => setDeactivateOpen(true), []);

  const [installOpen, setInstallOpen] = useState(false);
  const installRegionId = useId();
  const backTo = `${location.pathname}${location.search}`;

  const typeChip = (key: 'all' | 'company' | PackEntry['type']) => {
    const selected =
      key === 'all'
        ? filters.types.length === 0 && !filters.company
        : key === 'company'
          ? filters.company
          : filters.types.includes(key);
    const count =
      key === 'all'
        ? PACK_TYPES.reduce((n, k) => n + counts.types[k], 0) + companyCount
        : key === 'company'
          ? companyCount
          : counts.types[key];
    const meta = key === 'all' || key === 'company' ? null : PACK_TYPE_META[key];
    const Icon = key === 'company' ? Briefcase : meta?.icon ?? Package;
    const label = meta
      ? t(meta.labelKey, { defaultValue: meta.defaultLabel })
      : key === 'company'
        ? t('packs.slot_company', { defaultValue: 'Company type' })
        : t('packs.type_all', { defaultValue: 'All types' });
    return (
      <button
        key={key}
        type="button"
        aria-pressed={selected}
        data-testid={`packs-type-${key}`}
        disabled={key !== 'all' && count === 0 && !selected}
        onClick={() => {
          if (key === 'all') setFilters({ types: [], company: false });
          else if (key === 'company') setFilters({ company: !selected });
          else
            setFilters({
              types: selected ? filters.types.filter((x) => x !== key) : [...filters.types, key],
            });
        }}
        className={clsx(
          'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
          'disabled:cursor-not-allowed disabled:opacity-40',
          selected
            ? 'border-oe-blue bg-oe-blue text-content-inverse shadow-xs'
            : 'border-border bg-surface-primary text-content-secondary hover:border-content-tertiary/60 hover:text-content-primary',
        )}
      >
        <Icon size={13} aria-hidden />
        {label}
        <span
          className={clsx(
            'min-w-[1.25rem] rounded-full px-1.5 text-center text-2xs tabular-nums',
            selected ? 'bg-white/20' : 'bg-surface-secondary text-content-tertiary',
          )}
        >
          {count}
        </span>
      </button>
    );
  };

  const loading = list.isLoading;
  const failed = list.isError && !list.data;
  const total = entries.length + companyEntries.length;
  const shownTotal = filtered.length + shownCompanies.length;

  return (
    <div className="space-y-5" data-testid="packs-catalog">
      {/* Secondary actions: build your own, install (admins), open as a page. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {embedded && (
          <Link
            to="/packs"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:underline"
            data-testid="packs-open-page"
          >
            <PackageOpen size={15} aria-hidden />
            {t('packs.open_page', { defaultValue: 'Open the packs page' })}
          </Link>
        )}
        {canInstall && (
          <button
            type="button"
            aria-expanded={installOpen}
            aria-controls={installRegionId}
            onClick={() => setInstallOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-content-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 rounded"
            data-testid="packs-install-toggle"
          >
            <UploadCloud size={15} aria-hidden />
            {t('packs.install_custom', { defaultValue: 'Install a custom pack' })}
            <ChevronDown size={14} aria-hidden className={clsx('transition-transform', installOpen && 'rotate-180')} />
          </button>
        )}
      </div>
      {canInstall && installOpen && (
        <div id={installRegionId}>
          <InstallPackPanel onChanged={() => void list.refetch()} />
        </div>
      )}
      <ViewerPackNotice />

      {spotlight && (
        <ActivePackSpotlight
          entry={spotlight}
          applied={applied.data}
          activeSource={activeSource}
          canInstall={canInstall}
          regionLabel={bandLabels[spotlight.region]}
          languageName={names.languageName}
          backTo={backTo}
          onDeactivate={onDeactivate}
          onUpdate={() => onActivate(spotlight)}
        />
      )}

      {/* Filters */}
      <div
        role="search"
        aria-label={t('packs.filters_label', { defaultValue: 'Filter packs' })}
        className="space-y-3 rounded-xl border border-border-light bg-surface-elevated p-3 shadow-xs sm:p-4"
      >
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-0 flex-1">
            <Search size={16} aria-hidden className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
            <input
              type="search"
              value={qInput}
              onChange={(e) => onSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape' && qInput) {
                  e.preventDefault();
                  onSearch('');
                }
              }}
              aria-label={t('packs.search_label', { defaultValue: 'Search packs' })}
              placeholder={t('packs.search_placeholder', {
                defaultValue: 'Search by name, country, language or standard',
              })}
              data-testid="packs-search"
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pe-9 ps-9 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/60 focus:outline-none focus:ring-2 focus:ring-oe-blue/25 [&::-webkit-search-cancel-button]:hidden"
            />
            {qInput && (
              <button
                type="button"
                onClick={() => onSearch('')}
                aria-label={t('packs.search_clear', { defaultValue: 'Clear search' })}
                className="absolute end-2 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
              >
                <X size={14} aria-hidden />
              </button>
            )}
          </div>
          <FilterSelect
            label={t('packs.sort_label', { defaultValue: 'Sort' })}
            value={filters.sort === 'recommended' ? '' : filters.sort}
            onChange={(v) => setFilters({ sort: (v || 'recommended') as PackFilters['sort'] })}
            testId="packs-sort"
          >
            {PACK_SORTS.map((s) => (
              <option key={s} value={s === 'recommended' ? '' : s}>
                {sortLabels[s]}
              </option>
            ))}
          </FilterSelect>
        </div>

        <div
          role="group"
          aria-label={t('packs.type_label', { defaultValue: 'Pack type' })}
          className="flex flex-wrap gap-1.5"
        >
          {typeChip('all')}
          {PACK_TYPES.map((k) => typeChip(k))}
          {companies && typeChip('company')}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <FilterSelect
            label={t('packs.region_label', { defaultValue: 'Region' })}
            value={filters.region ?? ''}
            onChange={(v) => setFilters({ region: (v || null) as PackFilters['region'] })}
            testId="packs-region"
          >
            <option value="">{t('packs.region_all', { defaultValue: 'All regions' })}</option>
            {PACK_REGIONS.map((r) => (
              <option key={r} value={r} disabled={counts.regions[r] === 0 && filters.region !== r}>
                {`${bandLabels[r]} (${counts.regions[r]})`}
              </option>
            ))}
          </FilterSelect>
          <FilterSelect
            label={t('packs.language_label', { defaultValue: 'Language' })}
            value={filters.lang ?? ''}
            onChange={(v) => setFilters({ lang: v || null })}
            testId="packs-lang"
          >
            <option value="">{t('packs.language_all', { defaultValue: 'All languages' })}</option>
            {languageOptions.map((l) => {
              const n = counts.langs.get(l.code) ?? 0;
              return (
                <option key={l.code} value={l.code} disabled={n === 0 && filters.lang !== l.code}>
                  {`${l.name} (${n})`}
                </option>
              );
            })}
          </FilterSelect>
          <FilterSelect
            label={t('packs.status_label', { defaultValue: 'Status' })}
            value={filters.status ?? ''}
            onChange={(v) => setFilters({ status: (v || null) as PackFilters['status'] })}
            testId="packs-status"
          >
            <option value="">{t('packs.status_all', { defaultValue: 'Any status' })}</option>
            {PACK_STATUSES.map((s) => (
              <option key={s} value={s}>
                {`${statusLabels[s]} (${counts.status[s] + companyStatusCounts[s]})`}
              </option>
            ))}
          </FilterSelect>
          {filtering && (
            <button
              type="button"
              onClick={clearAll}
              data-testid="packs-clear"
              className="inline-flex h-9 items-center gap-1 rounded-lg px-2.5 text-sm font-medium text-oe-blue hover:bg-oe-blue/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <X size={14} aria-hidden />
              {t('common.clear_filters', { defaultValue: 'Clear filters' })}
            </button>
          )}
        </div>
      </div>

      {/* Result line + the phone's section jump. */}
      <div className="flex min-h-[2.25rem] flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-content-secondary" aria-live="polite" data-testid="packs-result-count">
          {loading || failed
            ? ' '
            : filtering
              ? t('packs.shown_of', {
                  defaultValue: 'Shown: {{shown}} of {{total}}',
                  shown: shownTotal,
                  total,
                })
              : t('packs.total_n', { defaultValue: 'Packs: {{n}}', n: total })}
        </p>
        {showNav && (
          <label className="xl:hidden">
            <span className="sr-only">{t('packs.jump_to', { defaultValue: 'Jump to section' })}</span>
            <select
              value={spied ?? ''}
              onChange={(e) => jumpToSection(e.target.value)}
              data-testid="packs-jump"
              className="h-9 max-w-[16rem] cursor-pointer rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary"
            >
              {sections.map((s) => (
                <option key={s.id} value={s.id}>
                  {`${s.group ? groupLabel(s.group) : companiesLabel} (${s.count})`}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {loading ? (
        <div className={CARD_GRID} aria-busy="true" aria-label={t('packs.loading', { defaultValue: 'Loading packs' })}>
          {Array.from({ length: 6 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : failed ? (
        <div role="alert" className="rounded-xl border border-border-light bg-surface-elevated py-14 text-center">
          <AlertTriangle size={36} className="mx-auto mb-3 text-semantic-warning" strokeWidth={1.5} aria-hidden />
          <p className="text-sm font-medium text-content-primary">
            {t('modules.packs_load_failed', { defaultValue: 'Failed to load packs' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('modules.packs_load_failed_hint', { defaultValue: 'Check your connection and try again.' })}
          </p>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={14} />}
            onClick={() => void list.refetch()}
            loading={list.isFetching}
            className="mt-4"
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      ) : total === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-14 text-center">
          <Package size={36} className="mx-auto mb-3 text-content-tertiary" aria-hidden />
          <p className="text-sm font-medium text-content-secondary">
            {t('modules.no_packs', { defaultValue: 'No packs available' })}
          </p>
          <p className="mx-auto mt-1 max-w-md text-xs text-content-tertiary">
            {t('modules.no_packs_hint', {
              defaultValue:
                'Packs ship pre-configured regional settings, validation standards, default modules and branding for a specific country, industry, partner or showcase.',
            })}
          </p>
        </div>
      ) : shownTotal === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-14 text-center" data-testid="packs-empty">
          <SearchX size={36} className="mx-auto mb-3 text-content-tertiary" strokeWidth={1.5} aria-hidden />
          <p className="text-sm font-medium text-content-primary">
            {t('packs.empty_title', { defaultValue: 'No packs match these filters' })}
          </p>
          <p className="mx-auto mt-1 max-w-sm text-xs text-content-tertiary">
            {t('packs.empty_hint', {
              defaultValue: 'Try another spelling, a country in your own language, or fewer filters.',
            })}
          </p>
          <Button variant="secondary" size="sm" icon={<X size={14} />} onClick={clearAll} className="mt-4">
            {t('common.clear_filters', { defaultValue: 'Clear filters' })}
          </Button>
        </div>
      ) : (
        <div className={clsx(showNav && 'xl:grid xl:grid-cols-[12.5rem_minmax(0,1fr)] xl:gap-6')}>
          {showNav && (
            <nav
              aria-label={t('packs.sections_label', { defaultValue: 'Pack sections' })}
              className="hidden xl:block"
            >
              <ul
                className="sticky space-y-0.5"
                style={{ top: 'calc(var(--oe-header-height) + 16px)' }}
                data-testid="packs-section-nav"
              >
                {sections.map(({ id, group, count }) => {
                  const current = spied === id;
                  return (
                    <li key={id}>
                      <a
                        href={`#${id}`}
                        aria-current={current ? 'location' : undefined}
                        onClick={(e) => {
                          e.preventDefault();
                          jumpToSection(id);
                        }}
                        className={clsx(
                          'flex items-center justify-between gap-2 rounded-lg border-s-2 px-3 py-1.5 text-sm transition-colors',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                          current
                            ? 'border-oe-blue bg-oe-blue/5 font-medium text-oe-blue'
                            : 'border-transparent text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                        )}
                      >
                        <span className="truncate">{group ? groupLabel(group) : companiesLabel}</span>
                        <span className="text-2xs tabular-nums text-content-tertiary">{count}</span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </nav>
          )}
          <div className="min-w-0 space-y-8">
            {groups.map((g) => {
              const id = packSectionId(g.id);
              return (
                <section
                  key={g.id}
                  id={id}
                  aria-labelledby={`${id}-title`}
                  className="scroll-mt-[calc(var(--oe-header-height)+16px)]"
                >
                  {(showNav || g.id !== 'all') && (
                    <div className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <h2
                        id={`${id}-title`}
                        tabIndex={-1}
                        className="text-base font-semibold text-content-primary focus:outline-none"
                      >
                        {groupLabel(g.id)}
                      </h2>
                      <span className="text-xs tabular-nums text-content-tertiary">{g.entries.length}</span>
                      {g.id === 'home' && (
                        <span className="text-xs text-content-tertiary">
                          {t('modules.packs_band_home_hint', {
                            defaultValue: 'Guessed from your browser. Any other pack is one click away.',
                          })}
                        </span>
                      )}
                    </div>
                  )}
                  {!(showNav || g.id !== 'all') && (
                    <h2 id={`${id}-title`} className="sr-only">
                      {groupLabel(g.id)}
                    </h2>
                  )}
                  <div className={CARD_GRID}>
                    {g.entries.map((entry) => (
                      <PackCard
                        key={entry.slug}
                        entry={entry}
                        isActive={entry.slug === activeSlug}
                        envPinned={activeSource === 'env'}
                        canInstall={canInstall}
                        regionLabel={bandLabels[entry.region]}
                        languageName={names.languageName}
                        backTo={backTo}
                        onActivate={onActivate}
                        onDeactivate={onDeactivate}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
            {companies && shownCompanies.length > 0 && (
              <section
                id={COMPANY_SECTION_ID}
                aria-labelledby={`${COMPANY_SECTION_ID}-title`}
                className="scroll-mt-[calc(var(--oe-header-height)+16px)]"
                data-testid="packs-company-types"
              >
                <div className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <h2
                    id={`${COMPANY_SECTION_ID}-title`}
                    tabIndex={-1}
                    className="text-base font-semibold text-content-primary focus:outline-none"
                  >
                    {companiesLabel}
                  </h2>
                  <span className="text-xs tabular-nums text-content-tertiary">{shownCompanies.length}</span>
                  <span className="text-xs text-content-tertiary">
                    {t('packs.family_company_hint', { defaultValue: 'Module and menu presets for a kind of company' })}
                  </span>
                </div>
                <div className={CARD_GRID}>
                  {shownCompanies.map(({ preset }) => (
                    <CompanyProfileCard
                      key={preset.key}
                      preset={preset}
                      isActive={preset.key === activeProfileKey}
                      shape={companies.shapes.get(preset.key)}
                      onSelect={companies.requestSwitch}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        </div>
      )}

      {/* Shared dialogs. The apply dialog keeps its last pack while it closes. */}
      {applyTarget && (
        <PartnerPackApplyDialog
          open={applyOpen}
          onClose={() => setApplyOpen(false)}
          slug={applyTarget.slug}
          partnerName={applyTarget.pack.partner_name}
        />
      )}
      {activeEntry && (
        <PartnerPackDeactivateDialog
          open={deactivateOpen}
          onClose={() => setDeactivateOpen(false)}
          partnerName={activeEntry.pack.partner_name}
        />
      )}
    </div>
  );
}
