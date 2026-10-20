// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ``/packs``: everything that sets the platform up in one step.
 *
 * Two families, and the page says how they combine. A country pack localises
 * the whole platform for a market (currency, tax, standards, language, cost
 * data, demo projects) and keeps every module. A company-type pack is a
 * company profile: the modules, and with them the menu, a kind of company
 * works with. One of each is the reader's setup, shown at the top as two
 * slots. Industry, partner and showcase packs sit in the first family as
 * filterable types, because they take the same single pack slot.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Building2,
  Globe2,
  Layers3,
  Plus,
  Power,
  RefreshCw,
  Search,
  SearchX,
  Users,
  X,
} from 'lucide-react';
import { Breadcrumb, Button } from '@/shared/ui';
import { PackEmblem } from '@/shared/ui/PackEmblem';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useAuthStore } from '@/stores/useAuthStore';
import { PartnerPackDeactivateDialog } from '../PartnerPackDeactivateDialog';
import { canInstallPacks } from '../partnerPacks';
import {
  CompanyProfileCard,
  FULL_PROFILE_KEY,
  ProfileSwitchDialog,
  getPresetIcon,
  sortPresets,
  useCompanyProfiles,
  type CompanyProfilesState,
} from '../companyProfiles';
import { foldText, PACK_FILTER_PARAMS, type PackEntry } from './packCatalog';
import { PacksCatalog, usePackCatalogData } from './PacksCatalog';
import { PACK_TYPE_META, useBandLabels } from './packLabels';

const FAMILIES = ['country', 'company'] as const;
type Family = (typeof FAMILIES)[number];

function familyOf(params: URLSearchParams): Family {
  return params.get('family') === 'company' ? 'company' : 'country';
}

function scrollToFamilies() {
  const el = document.getElementById('packs-families');
  if (!el) return;
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
}

/* ── Setup slots ────────────────────────────────────────────────────────── */

function SlotShell({
  label,
  icon: Icon,
  filled,
  children,
  testId,
}: {
  label: string;
  icon: typeof Globe2;
  filled: boolean;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <div
      data-testid={testId}
      className={clsx(
        'relative flex min-w-0 flex-1 flex-col rounded-2xl border p-4 sm:p-5',
        filled
          ? 'border-border-light bg-surface-elevated shadow-sm'
          : 'border-dashed border-border bg-surface-primary/60',
      )}
    >
      <p className="mb-3 inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
        <Icon size={13} aria-hidden />
        {label}
      </p>
      {children}
    </div>
  );
}

function slotLinkClass(primary = false) {
  return clsx(
    'inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition-colors',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
    primary
      ? 'bg-oe-blue text-content-inverse hover:bg-oe-blue-hover'
      : 'border border-border bg-surface-primary text-content-primary hover:bg-surface-secondary',
  );
}

function CountrySlot({
  entry,
  loading,
  envPinned,
  canInstall,
  onChange,
  onDeactivate,
}: {
  entry: PackEntry | null;
  loading: boolean;
  envPinned: boolean;
  canInstall: boolean;
  onChange: () => void;
  onDeactivate: () => void;
}) {
  const { t } = useTranslation();
  const bandLabels = useBandLabels();
  const label = t('packs.slot_country', { defaultValue: 'Country pack' });
  if (loading) {
    return (
      <SlotShell label={label} icon={Globe2} filled testId="packs-slot-country">
        <div className="flex items-center gap-3" aria-hidden>
          <div className="h-12 w-12 animate-pulse rounded-xl bg-surface-secondary" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-1/2 animate-pulse rounded bg-surface-secondary" />
            <div className="h-3 w-1/3 animate-pulse rounded bg-surface-secondary" />
          </div>
        </div>
      </SlotShell>
    );
  }
  if (!entry) {
    return (
      <SlotShell label={label} icon={Globe2} filled={false} testId="packs-slot-country">
        <p className="text-sm font-semibold text-content-primary">
          {t('packs.slot_country_empty', { defaultValue: 'No pack active' })}
        </p>
        <p className="mt-0.5 text-xs text-content-secondary">
          {t('packs.slot_country_empty_hint', {
            defaultValue: 'The platform runs with its neutral defaults. Pick your country to get its currency, tax, standards and cost data.',
          })}
        </p>
        <div className="mt-auto flex flex-wrap gap-2 pt-3">
          <button type="button" className={slotLinkClass(true)} onClick={onChange}>
            {t('packs.choose_country', { defaultValue: 'Choose a country pack' })}
          </button>
        </div>
      </SlotShell>
    );
  }
  const meta = PACK_TYPE_META[entry.type];
  return (
    <SlotShell label={label} icon={Globe2} filled testId="packs-slot-country">
      <div className="flex items-center gap-3">
        <PackEmblem pack={entry.pack} size={48} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-semibold text-content-primary">{entry.name}</p>
          <p className="truncate text-xs text-content-tertiary">
            {entry.type !== 'country' && `${t(meta.labelKey, { defaultValue: meta.defaultLabel })} · `}
            {entry.countryName ? `${entry.countryName} · ` : ''}
            {bandLabels[entry.region]} · <span className="font-mono">{entry.pack.default_currency}</span>
          </p>
        </div>
      </div>
      <div className="mt-auto flex flex-wrap gap-2 pt-3">
        <Link to={`/packs/${encodeURIComponent(entry.slug)}`} className={slotLinkClass()}>
          {t('packs.see_changes', { defaultValue: 'See what it changed' })}
          <ArrowUpRight size={13} aria-hidden className="rtl:-scale-x-100" />
        </Link>
        <button type="button" className={slotLinkClass()} onClick={onChange}>
          {t('packs.change', { defaultValue: 'Change' })}
        </button>
        {canInstall && !envPinned && (
          <button type="button" className={slotLinkClass()} onClick={onDeactivate} data-testid="packs-slot-deactivate">
            <Power size={13} aria-hidden />
            {t('modules.pack_deactivate', { defaultValue: 'Deactivate' })}
          </button>
        )}
      </div>
      {envPinned && (
        <p className="mt-2 text-2xs text-content-tertiary">
          {t('modules.pack_active_via_env', { defaultValue: 'Active via environment (OE_PACK)' })}
        </p>
      )}
    </SlotShell>
  );
}

function CompanySlot({ profiles, onChange }: { profiles: CompanyProfilesState; onChange: () => void }) {
  const { t } = useTranslation();
  const { activePreset, presets, presetsLoading, profileName } = profiles;
  const label = t('packs.slot_company', { defaultValue: 'Company type' });
  if (presetsLoading) {
    return (
      <SlotShell label={label} icon={Building2} filled testId="packs-slot-company">
        <div className="flex items-center gap-3" aria-hidden>
          <div className="h-12 w-12 animate-pulse rounded-xl bg-surface-secondary" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-1/2 animate-pulse rounded bg-surface-secondary" />
            <div className="h-3 w-1/3 animate-pulse rounded bg-surface-secondary" />
          </div>
        </div>
      </SlotShell>
    );
  }
  if (!activePreset) {
    return (
      <SlotShell label={label} icon={Building2} filled={false} testId="packs-slot-company">
        <p className="text-sm font-semibold text-content-primary">
          {t('packs.slot_company_empty', { defaultValue: 'No company type chosen' })}
        </p>
        <p className="mt-0.5 text-xs text-content-secondary">
          {t('packs.slot_company_empty_hint', {
            defaultValue: 'Every module stays on. Pick your kind of company to keep only the modules and menu it works with.',
          })}
        </p>
        <div className="mt-auto flex flex-wrap gap-2 pt-3">
          <button type="button" className={slotLinkClass(true)} onClick={onChange}>
            {t('packs.choose_company', { defaultValue: 'Choose a company type' })}
          </button>
        </div>
      </SlotShell>
    );
  }
  const Icon = getPresetIcon(activePreset.icon);
  const full = presets?.find((p) => p.key === FULL_PROFILE_KEY);
  return (
    <SlotShell label={label} icon={Building2} filled testId="packs-slot-company">
      <div className="flex items-center gap-3">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
          <Icon size={24} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-semibold text-content-primary">{profileName(activePreset)}</p>
          <p className="truncate text-xs text-content-tertiary">
            {activePreset.module_count} {t('modules.modules_active_label', { defaultValue: 'modules active' })}
          </p>
        </div>
      </div>
      <div className="mt-auto flex flex-wrap gap-2 pt-3">
        <button type="button" className={slotLinkClass()} onClick={onChange}>
          {t('packs.change', { defaultValue: 'Change' })}
        </button>
        {full && activePreset.key !== FULL_PROFILE_KEY && (
          <button
            type="button"
            className={slotLinkClass()}
            onClick={() => profiles.requestSwitch(full)}
            data-testid="packs-slot-company-reset"
          >
            <Power size={13} aria-hidden />
            {t('packs.use_all_modules', { defaultValue: 'Back to all modules' })}
          </button>
        )}
      </div>
    </SlotShell>
  );
}

/* ── How packs work ─────────────────────────────────────────────────────── */

function HowPacksWork() {
  const { t } = useTranslation();
  const steps = [
    {
      icon: Globe2,
      title: t('packs.how_1_title', { defaultValue: 'Pick your country' }),
      body: t('packs.how_1_body', {
        defaultValue: 'A country pack sets currency, tax, standards, calendar, language and cost data. All modules stay available.',
      }),
    },
    {
      icon: Building2,
      title: t('packs.how_2_title', { defaultValue: 'Pick your company type' }),
      body: t('packs.how_2_body', {
        defaultValue: 'A company-type pack keeps the modules and menu your kind of company works with, and hides the rest.',
      }),
    },
    {
      icon: Layers3,
      title: t('packs.how_3_title', { defaultValue: 'Swap or switch off any time' }),
      body: t('packs.how_3_body', {
        defaultValue: 'Industry, partner and showcase packs take the country slot instead. Deactivating restores the previous setup.',
      }),
    },
  ];
  return (
    <section aria-labelledby="packs-how-title" className="rounded-2xl border border-border-light bg-surface-elevated p-4 sm:p-5">
      <h2 id="packs-how-title" className="text-sm font-semibold text-content-primary">
        {t('packs.how_title', { defaultValue: 'How packs work' })}
      </h2>
      <ol className="mt-3 grid gap-3 md:grid-cols-3">
        {steps.map((s, i) => {
          const Icon = s.icon;
          return (
            <li key={i} className="flex gap-3">
              <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-oe-blue">
                <Icon size={17} aria-hidden />
                <span className="absolute -end-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-oe-blue text-[10px] font-bold text-content-inverse">
                  {i + 1}
                </span>
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-content-primary">{s.title}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">{s.body}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/* ── Company types ──────────────────────────────────────────────────────── */

function CompanyTypesPanel({ profiles }: { profiles: CompanyProfilesState }) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { presets, presetsLoading, presetsError, refetchPresets, shapes, activeProfileKey, profileName } = profiles;
  const [q, setQ] = useState(searchParams.get('q') ?? '');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const onSearch = (value: string) => {
    setQ(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set('q', value);
          else next.delete('q');
          return next;
        },
        { replace: true },
      );
    }, 250);
  };

  const sorted = useMemo(() => sortPresets(presets ?? []), [presets]);
  const shown = useMemo(() => {
    const needle = foldText(q.trim());
    if (!needle) return sorted;
    return sorted.filter((p) =>
      needle
        .split(/\s+/)
        .every((tok) =>
          foldText(
            [profileName(p), p.label, p.description, t(`onboarding.company_${p.key}_desc`, { defaultValue: p.description }), ...(p.tags ?? [])].join(' '),
          ).includes(tok),
        ),
    );
  }, [sorted, q, profileName, t]);

  return (
    <div className="space-y-4" data-testid="packs-company-types">
      <p className="max-w-3xl text-sm text-content-secondary">
        {t('packs.company_intro', {
          defaultValue:
            'Each company type is a preset: the modules your kind of company uses, and in Simple mode the menu built from them. Switching changes only which modules are on; your projects and data stay as they are.',
        })}
      </p>
      <div className="relative max-w-md">
        <Search size={16} aria-hidden className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
        <input
          type="search"
          value={q}
          onChange={(e) => onSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && q) {
              e.preventDefault();
              onSearch('');
            }
          }}
          aria-label={t('packs.company_search_label', { defaultValue: 'Search company types' })}
          placeholder={t('packs.company_search_placeholder', { defaultValue: 'For example contractor, developer or estimator' })}
          data-testid="packs-company-search"
          className="h-10 w-full rounded-lg border border-border bg-surface-primary pe-3 ps-9 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/60 focus:outline-none focus:ring-2 focus:ring-oe-blue/25"
        />
      </div>

      {presetsLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-[7.5rem] animate-pulse rounded-xl border border-border-light bg-surface-elevated" />
          ))}
        </div>
      ) : presetsError ? (
        <div role="alert" className="rounded-xl border border-border-light bg-surface-elevated py-12 text-center">
          <AlertTriangle size={36} className="mx-auto mb-3 text-semantic-warning" strokeWidth={1.5} aria-hidden />
          <p className="text-sm font-medium text-content-primary">
            {t('modules.profiles_load_failed', { defaultValue: 'Failed to load profiles' })}
          </p>
          <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} onClick={() => void refetchPresets()} className="mt-3">
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      ) : sorted.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-12 text-center">
          <Users size={36} className="mx-auto mb-3 text-content-tertiary" aria-hidden />
          <p className="text-sm font-medium text-content-secondary">
            {t('modules.no_profiles', { defaultValue: 'No company profiles available' })}
          </p>
        </div>
      ) : shown.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-12 text-center" data-testid="packs-company-empty">
          <SearchX size={36} className="mx-auto mb-3 text-content-tertiary" strokeWidth={1.5} aria-hidden />
          <p className="text-sm font-medium text-content-primary">
            {t('packs.company_empty', { defaultValue: 'No company type matches this search' })}
          </p>
          <Button variant="secondary" size="sm" icon={<X size={14} />} onClick={() => onSearch('')} className="mt-3">
            {t('packs.search_clear', { defaultValue: 'Clear search' })}
          </Button>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((preset) => (
            <CompanyProfileCard
              key={preset.key}
              preset={preset}
              isActive={preset.key === activeProfileKey}
              shape={shapes.get(preset.key)}
              onSelect={profiles.requestSwitch}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export function PacksPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const family = familyOf(searchParams);
  const canInstall = canInstallPacks(useAuthStore((s) => s.userRole));
  const { list, entries, activeSlug, activeSource } = usePackCatalogData();
  const profiles = useCompanyProfiles();
  const [deactivateOpen, setDeactivateOpen] = useState(false);

  const activeEntry = useMemo(() => entries.find((e) => e.slug === activeSlug) ?? null, [entries, activeSlug]);
  const countryCount = useMemo(() => entries.filter((e) => e.type === 'country').length, [entries]);
  const countries = useMemo(() => new Set(entries.map((e) => e.country).filter(Boolean)).size, [entries]);
  const languages = useMemo(() => new Set(entries.flatMap((e) => e.languages)).size, [entries]);
  const companyCount = profiles.presets?.length ?? 0;

  const selectFamily = useCallback(
    (next: Family) => {
      // Each family has its own filters; carrying one family's into the other
      // would filter a list by fields it does not have.
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          for (const key of PACK_FILTER_PARAMS) params.delete(key);
          if (next === 'company') params.set('family', 'company');
          else params.delete('family');
          return params;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  const onTabKeyDown = useTabKeyboardNav<Family>({
    ids: FAMILIES,
    activeId: family,
    onChange: selectFamily,
    orientation: 'horizontal',
  });
  const goTo = (next: Family) => {
    selectFamily(next);
    requestAnimationFrame(scrollToFamilies);
  };

  const stat = (value: number | string, label: string) => (
    <div className="min-w-[5.5rem]">
      <dd className="text-2xl font-bold tabular-nums text-content-primary">{value}</dd>
      <dt className="text-xs text-content-tertiary">{label}</dt>
    </div>
  );

  const tabs: { key: Family; icon: typeof Globe2; title: string; hint: string; count: number }[] = [
    {
      key: 'country',
      icon: Globe2,
      title: t('packs.family_country', { defaultValue: 'Country packs' }),
      hint: t('packs.family_country_hint', { defaultValue: 'The full platform for a market, plus industry and partner packs' }),
      count: entries.length,
    },
    {
      key: 'company',
      icon: Building2,
      title: t('packs.family_company', { defaultValue: 'Company-type packs' }),
      hint: t('packs.family_company_hint', { defaultValue: 'Module and menu presets for a kind of company' }),
      count: companyCount,
    },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.packs', { defaultValue: 'Packs' }) }]} />

      {/* Header */}
      <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-bold tracking-tight text-content-primary sm:text-3xl">
            {t('nav.packs', { defaultValue: 'Packs' })}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-content-secondary sm:text-base">
            {t('packs.lead', {
              defaultValue:
                'A pack sets the platform up in one step. Combine one country pack with one company-type pack, for example Germany plus General contractor.',
            })}
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <Link to="/modules/developer-guide#partner-packs" className="inline-flex items-center gap-1.5 font-medium text-oe-blue hover:underline">
              <BookOpen size={14} aria-hidden />
              {t('modules.packs_build_own', { defaultValue: 'Build your own pack and share it with others' })}
            </Link>
          </div>
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-3" aria-label={t('packs.stats_label', { defaultValue: 'Packs at a glance' })}>
          {stat(list.isLoading ? '–' : countryCount, t('packs.stat_country_packs', { defaultValue: 'Country packs' }))}
          {stat(profiles.presetsLoading ? '–' : companyCount, t('packs.stat_company_types', { defaultValue: 'Company types' }))}
          {stat(list.isLoading ? '–' : countries, t('packs.stat_countries', { defaultValue: 'Countries' }))}
          {stat(list.isLoading ? '–' : languages, t('packs.stat_languages', { defaultValue: 'Languages' }))}
        </dl>
      </header>

      {/* Your setup: one country pack + one company type. */}
      <section aria-labelledby="packs-setup-title" className="space-y-3">
        <h2 id="packs-setup-title" className="text-sm font-semibold text-content-primary">
          {t('packs.setup_title', { defaultValue: 'Your setup' })}
        </h2>
        <div className="flex flex-col items-stretch gap-3 md:flex-row">
          <CountrySlot
            entry={activeEntry}
            loading={list.isLoading}
            envPinned={activeSource === 'env'}
            canInstall={canInstall}
            onChange={() => goTo('country')}
            onDeactivate={() => setDeactivateOpen(true)}
          />
          <div className="flex items-center justify-center" aria-hidden>
            <span className="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-surface-primary text-content-tertiary">
              <Plus size={16} />
            </span>
          </div>
          <CompanySlot profiles={profiles} onChange={() => goTo('company')} />
        </div>
      </section>

      <HowPacksWork />

      {/* The two families */}
      <section id="packs-families" className="scroll-mt-[calc(var(--oe-header-height)+16px)] space-y-5">
        <div
          role="tablist"
          aria-label={t('packs.families_label', { defaultValue: 'Pack families' })}
          className="grid gap-2 sm:grid-cols-2"
          onKeyDown={onTabKeyDown}
        >
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const selected = family === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                id={`packs-tab-${tab.key}`}
                aria-selected={selected}
                aria-controls={`packs-panel-${tab.key}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectFamily(tab.key)}
                data-testid={`packs-family-${tab.key}`}
                className={clsx(
                  'flex items-center gap-3 rounded-xl border p-3.5 text-start transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                  selected
                    ? 'border-oe-blue bg-oe-blue/5 shadow-xs'
                    : 'border-border-light bg-surface-elevated hover:border-border',
                )}
              >
                <span
                  className={clsx(
                    'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                    selected ? 'bg-oe-blue text-content-inverse' : 'bg-surface-secondary text-content-secondary',
                  )}
                >
                  <Icon size={19} aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className={clsx('text-sm font-semibold', selected ? 'text-oe-blue' : 'text-content-primary')}>
                      {tab.title}
                    </span>
                    <span className="rounded-full bg-surface-secondary px-1.5 text-2xs tabular-nums text-content-secondary">
                      {tab.count}
                    </span>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-content-tertiary">{tab.hint}</span>
                </span>
              </button>
            );
          })}
        </div>

        <div role="tabpanel" id={`packs-panel-${family}`} aria-labelledby={`packs-tab-${family}`}>
          {family === 'country' ? <PacksCatalog spotlight={false} /> : <CompanyTypesPanel profiles={profiles} />}
        </div>
      </section>

      {activeEntry && (
        <PartnerPackDeactivateDialog
          open={deactivateOpen}
          onClose={() => setDeactivateOpen(false)}
          partnerName={activeEntry.pack.partner_name}
        />
      )}
      <ProfileSwitchDialog state={profiles} />
    </div>
  );
}

export default PacksPage;
