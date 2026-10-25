// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ``/packs``: everything that sets the platform up in one step.
 *
 * One catalogue of packs, filtered by type. A country pack localises the
 * whole platform for a market (currency, tax, standards, language, cost data,
 * demo projects) and keeps every module; industry, partner and showcase packs
 * take the same slot. A company-type pack is a company profile: the modules,
 * and with them the menu, a kind of company works with. One of each is the
 * reader's setup, shown at the top as two slots.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import { ArrowUpRight, BookOpen, Building2, Globe2, Layers3, Plus, Power } from 'lucide-react';
import { Breadcrumb } from '@/shared/ui';
import { PackEmblem } from '@/shared/ui/PackEmblem';
import { useAuthStore } from '@/stores/useAuthStore';
import { PartnerPackDeactivateDialog } from '../PartnerPackDeactivateDialog';
import { canInstallPacks } from '../partnerPacks';
import {
  FULL_PROFILE_KEY,
  ProfileSwitchDialog,
  getPresetIcon,
  useCompanyProfiles,
  type CompanyProfilesState,
} from '../companyProfiles';
import { EMPTY_PACK_FILTERS, parsePackFilters, writePackFilters, type PackEntry } from './packCatalog';
import { PacksCatalog, usePackCatalogData } from './PacksCatalog';
import { PACK_TYPE_META, useBandLabels } from './packLabels';

/** The two kinds of pack a setup slot asks for. */
type SlotKind = 'country' | 'company';

function scrollToCatalog() {
  const el = document.getElementById('packs-catalog');
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

/* ── Page ───────────────────────────────────────────────────────────────── */

export function PacksPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const canInstall = canInstallPacks(useAuthStore((s) => s.userRole));
  const { list, entries, activeSlug, activeSource } = usePackCatalogData();
  const profiles = useCompanyProfiles();
  const [deactivateOpen, setDeactivateOpen] = useState(false);

  const activeEntry = useMemo(() => entries.find((e) => e.slug === activeSlug) ?? null, [entries, activeSlug]);
  const countries = useMemo(() => new Set(entries.map((e) => e.country).filter(Boolean)).size, [entries]);
  const languages = useMemo(() => new Set(entries.flatMap((e) => e.languages)).size, [entries]);
  const packCount = entries.length + (profiles.presets?.length ?? 0);

  // Links from before the single catalogue carried ``family=company``; read
  // it once as the company-type filter so they still land on the right list.
  const legacyFamily = searchParams.get('family');
  useEffect(() => {
    if (legacyFamily === null) return;
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.delete('family');
        return legacyFamily === 'company' ? writePackFilters(params, { ...parsePackFilters(params), company: true }) : params;
      },
      { replace: true },
    );
  }, [legacyFamily, setSearchParams]);

  // A slot's Choose and Change buttons open the catalogue on that kind of pack.
  const showKind = useCallback(
    (kind: SlotKind) => {
      setSearchParams(
        (prev) =>
          writePackFilters(prev, {
            ...EMPTY_PACK_FILTERS,
            sort: parsePackFilters(prev).sort,
            ...(kind === 'company' ? { company: true } : { types: ['country'] }),
          }),
        { replace: true },
      );
      requestAnimationFrame(scrollToCatalog);
    },
    [setSearchParams],
  );

  const stat = (value: number | string, label: string) => (
    <div className="min-w-[5.5rem]">
      <dd className="text-2xl font-bold tabular-nums text-content-primary">{value}</dd>
      <dt className="text-xs text-content-tertiary">{label}</dt>
    </div>
  );

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
          {stat(list.isLoading || profiles.presetsLoading ? '–' : packCount, t('nav.packs', { defaultValue: 'Packs' }))}
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
            onChange={() => showKind('country')}
            onDeactivate={() => setDeactivateOpen(true)}
          />
          <div className="flex items-center justify-center" aria-hidden>
            <span className="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-surface-primary text-content-tertiary">
              <Plus size={16} />
            </span>
          </div>
          <CompanySlot profiles={profiles} onChange={() => showKind('company')} />
        </div>
      </section>

      <HowPacksWork />

      {/* Every pack in one catalogue: country, industry, partner, showcase and company type. */}
      <section id="packs-catalog" className="scroll-mt-[calc(var(--oe-header-height)+16px)]">
        <PacksCatalog spotlight={false} companies={profiles} />
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
