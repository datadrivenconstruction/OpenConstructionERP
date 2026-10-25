// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The browsable half of the ready-made pack step: a search box, type chips
 * with counts, the packs grouped the way the /packs catalogue groups them, and
 * the company types as a second, optional choice.
 *
 * It reuses the catalogue's pure functions (`buildPackEntries`,
 * `filterPackEntries`, `packFacetCounts`, `groupPackEntries`,
 * `companyPackMatches`) so a search finds the same packs here as on /packs.
 * What a pack tile looks like on the inside is the wizard's business and comes
 * in as `renderTile`; this file owns the structure around the tiles.
 */

import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Briefcase, Check, Package, Search, SearchX, X } from 'lucide-react';
import { detectCountry } from '@/app/i18n';
import { packNameSlug } from '@/shared/lib/regionalPack';
import type { PackType } from '@/shared/hooks/usePartnerPack';
import {
  getPresetIcon,
  sortPresets,
  type CompanyPresetAPI,
  type CompanyProfilesState,
} from '@/features/modules/companyProfiles';
import {
  buildPackEntries,
  companyPackMatches,
  EMPTY_PACK_FILTERS,
  filterPackEntries,
  foldText,
  groupPackEntries,
  packFacetCounts,
  packSectionId,
  PACK_TYPES,
  type PackEntry,
  type PackFilters,
  type PackManifest,
} from '@/features/modules/packs/packCatalog';
import { PACK_TYPE_META, useBandLabels, useDisplayNames } from '@/features/modules/packs/packLabels';
import type { InstalledPartnerPack } from './partnerPacksApi';

export type ReadyPackTypeFilter = 'all' | PackType | 'company';

/** The three pack types that are not countries, each shown under its own heading. */
const OTHER_TYPES = ['industry', 'partner', 'showcase'] as const satisfies readonly PackType[];

interface ReadyPackBrowserProps {
  packs: InstalledPartnerPack[];
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  /** Locks every tile while an install runs. */
  disabled?: boolean;
  /** The inside of one pack tile; the browser draws the button around it. */
  renderTile: (entry: PackEntry, selected: boolean) => ReactNode;
  companies: CompanyProfilesState;
  companyKey: string | null;
  onCompanyChange: (preset: CompanyPresetAPI | null) => void;
  /** Rendered after the packs, inside the same filter (the curated market
   *  presets for countries no pack serves). Receives the folded search text. */
  children?: (query: string, typeFilter: ReadyPackTypeFilter) => ReactNode;
}

const TILE_GRID = 'grid w-full grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4';

export function ReadyPackBrowser({
  packs,
  selectedSlug,
  onSelect,
  disabled = false,
  renderTile,
  companies,
  companyKey,
  onCompanyChange,
  children,
}: ReadyPackBrowserProps) {
  const { t } = useTranslation();
  const names = useDisplayNames();
  const bandLabels = useBandLabels();
  const homeCountry = useMemo(() => detectCountry(), []);
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<ReadyPackTypeFilter>('all');

  // One entry per pack, worked out when the packs or the language change and
  // not on a keystroke.
  const entries = useMemo(
    () =>
      buildPackEntries(packs as unknown as PackManifest[], {
        homeCountry,
        nameOf: (p) => t(`modules.pp_name_${packNameSlug(p.slug)}`, { defaultValue: p.partner_name }),
        summaryOf: (p) => t(`modules.pp_desc_${packNameSlug(p.slug)}`, { defaultValue: p.description }),
        countryNameOf: names.countryName,
        languageNameOf: names.languageName,
      }),
    [packs, homeCountry, t, names],
  );

  const { presets, profileName } = companies;
  const companyEntries = useMemo(
    () =>
      sortPresets(presets ?? []).map((p) => ({
        preset: p,
        key: p.key,
        name: profileName(p),
        description: t(`onboarding.company_${p.key}_desc`, { defaultValue: p.description }),
        haystack: foldText(
          [
            profileName(p),
            p.label,
            p.description,
            t(`onboarding.company_${p.key}_desc`, { defaultValue: p.description }),
            ...(p.tags ?? []),
          ].join(' '),
        ),
      })),
    [presets, profileName, t],
  );

  const filters: PackFilters = useMemo(
    () => ({
      ...EMPTY_PACK_FILTERS,
      q: query,
      types: typeFilter === 'all' || typeFilter === 'company' ? [] : [typeFilter],
      company: typeFilter === 'company',
    }),
    [query, typeFilter],
  );

  const filtered = useMemo(() => filterPackEntries(entries, filters, null), [entries, filters]);
  const counts = useMemo(() => packFacetCounts(entries, filters, null), [entries, filters]);
  const shownCompanies = useMemo(
    () => companyEntries.filter((e) => companyPackMatches(e, filters, null)),
    [companyEntries, filters],
  );
  const companyCount = useMemo(
    () => companyEntries.filter((e) => companyPackMatches(e, filters, null, 'type')).length,
    [companyEntries, filters],
  );

  // Country packs by market band, the reader's own market first; every other
  // type under its own heading so a formwork or retail pack never sits between
  // two countries.
  const countryGroups = useMemo(
    () =>
      groupPackEntries(
        filtered.filter((e) => e.type === 'country'),
        'recommended',
        names.locale,
      ),
    [filtered, names.locale],
  );
  const otherSections = useMemo(() => {
    const collator = new Intl.Collator(names.locale, { sensitivity: 'base', numeric: true });
    return OTHER_TYPES.map((type) => ({
      type,
      entries: filtered.filter((e) => e.type === type).sort((a, b) => collator.compare(a.name, b.name)),
    })).filter((s) => s.entries.length > 0);
  }, [filtered, names.locale]);

  const total = entries.length + companyEntries.length;
  const shownTotal = filtered.length + shownCompanies.length;
  const filtering = query.trim() !== '' || typeFilter !== 'all';
  const chosenCompany = companyEntries.find((e) => e.key === companyKey) ?? null;

  const chipKeys: ReadyPackTypeFilter[] = ['all', ...PACK_TYPES, 'company'];

  const packTile = (entry: PackEntry) => {
    const selected = selectedSlug === entry.slug;
    return (
      <button
        key={entry.slug}
        type="button"
        onClick={() => onSelect(entry.slug)}
        disabled={disabled}
        aria-pressed={selected}
        title={entry.name}
        data-testid={`ready-pack-tile-${entry.slug}`}
        className={clsx(
          'group relative flex min-w-0 flex-col items-center gap-2 rounded-xl p-3 text-center transition-all duration-200',
          selected
            ? 'bg-oe-blue-subtle/50 ring-2 ring-oe-blue/45 shadow-sm'
            : 'bg-surface-secondary/70 ring-1 ring-transparent hover:bg-surface-secondary hover:shadow-sm hover:-translate-y-0.5',
          disabled && 'opacity-60 cursor-not-allowed',
        )}
      >
        {selected && (
          <span className="absolute end-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white shadow-sm">
            <Check size={12} strokeWidth={3} />
          </span>
        )}
        {renderTile(entry, selected)}
      </button>
    );
  };

  const headingClass = 'text-sm font-semibold text-content-primary';

  return (
    <div className="mt-6 w-full max-w-5xl" data-testid="ready-pack-browser">
      {/* Search */}
      <div className="relative">
        <Search
          size={16}
          aria-hidden
          className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary"
        />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && query) {
              e.preventDefault();
              setQuery('');
            }
          }}
          aria-label={t('packs.search_label', { defaultValue: 'Search packs' })}
          placeholder={t('packs.search_placeholder', {
            defaultValue: 'Search by name, country, language or standard',
          })}
          data-testid="ready-pack-search"
          className="h-10 w-full rounded-lg border border-border bg-surface-primary pe-9 ps-9 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/60 focus:outline-none focus:ring-2 focus:ring-oe-blue/25 [&::-webkit-search-cancel-button]:hidden"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery('')}
            aria-label={t('packs.search_clear', { defaultValue: 'Clear search' })}
            className="absolute end-2 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={14} aria-hidden />
          </button>
        )}
      </div>

      {/* Type chips, one choice at a time */}
      <div
        role="radiogroup"
        aria-label={t('packs.type_label', { defaultValue: 'Pack type' })}
        className="mt-3 flex flex-wrap gap-2"
      >
        {chipKeys.map((key) => {
          const selected = typeFilter === key;
          const count =
            key === 'all'
              ? PACK_TYPES.reduce((n, k) => n + counts.types[k], 0) + companyCount
              : key === 'company'
                ? companyCount
                : counts.types[key];
          const meta = key === 'all' || key === 'company' ? null : PACK_TYPE_META[key];
          const Icon = key === 'company' ? Briefcase : (meta?.icon ?? Package);
          const label = meta
            ? t(meta.labelKey, { defaultValue: meta.defaultLabel })
            : key === 'company'
              ? t('packs.slot_company', { defaultValue: 'Company type' })
              : t('packs.type_all', { defaultValue: 'All types' });
          return (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={selected}
              data-testid={`ready-pack-type-${key}`}
              disabled={key !== 'all' && count === 0 && !selected}
              onClick={() => setTypeFilter(key)}
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
        })}
      </div>

      <p className="mt-3 text-xs text-content-tertiary" aria-live="polite" data-testid="ready-pack-count">
        {filtering
          ? t('packs.shown_of', { defaultValue: 'Shown: {{shown}} of {{total}}', shown: shownTotal, total })
          : t('packs.total_n', { defaultValue: 'Packs: {{n}}', n: total })}
      </p>

      {/* Packs: countries by market band, then the other types */}
      <div className="mt-4 space-y-7">
        {countryGroups.map((g) => (
          <section key={g.id} aria-labelledby={`ready-${packSectionId(g.id)}`} data-testid={`ready-pack-group-${g.id}`}>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <h3 id={`ready-${packSectionId(g.id)}`} className={headingClass}>
                {g.id === 'all' ? t('packs.section_all', { defaultValue: 'All packs' }) : bandLabels[g.id]}
              </h3>
              <span className="text-xs tabular-nums text-content-tertiary">{g.entries.length}</span>
              {g.id === 'home' && (
                <span className="text-xs text-content-tertiary">
                  {t('modules.packs_band_home_hint', {
                    defaultValue: 'Guessed from your browser. Any other pack is one click away.',
                  })}
                </span>
              )}
            </div>
            <div className={TILE_GRID}>{g.entries.map(packTile)}</div>
          </section>
        ))}

        {otherSections.map((s) => {
          const meta = PACK_TYPE_META[s.type];
          return (
            <section
              key={s.type}
              aria-labelledby={`ready-pack-type-heading-${s.type}`}
              data-testid={`ready-pack-group-${s.type}`}
            >
              <div className="mb-3 flex flex-wrap items-baseline gap-x-2">
                <h3 id={`ready-pack-type-heading-${s.type}`} className={headingClass}>
                  {t(meta.labelKey, { defaultValue: meta.defaultLabel })}
                </h3>
                <span className="text-xs tabular-nums text-content-tertiary">{s.entries.length}</span>
              </div>
              <div className={TILE_GRID}>{s.entries.map(packTile)}</div>
            </section>
          );
        })}

        {filtered.length === 0 && shownCompanies.length === 0 && (
          <div className="rounded-xl border border-dashed border-border py-10 text-center" data-testid="ready-pack-empty">
            <SearchX size={32} className="mx-auto mb-2 text-content-tertiary" strokeWidth={1.5} aria-hidden />
            <p className="text-sm font-medium text-content-primary">
              {t('packs.empty_title', { defaultValue: 'No packs match these filters' })}
            </p>
            <p className="mx-auto mt-1 max-w-sm text-xs text-content-tertiary">
              {t('packs.empty_hint', {
                defaultValue: 'Try another spelling, a country in your own language, or fewer filters.',
              })}
            </p>
          </div>
        )}

        {children?.(foldText(query.trim()), typeFilter)}

        {/* Company types: a second, optional choice that combines with the pack */}
        {shownCompanies.length > 0 && (
          <section
            aria-labelledby="ready-pack-company-title"
            data-testid="ready-pack-company-types"
            className="rounded-2xl bg-surface-secondary/40 p-3 ring-1 ring-border-light sm:p-4"
          >
            <div className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <h3 id="ready-pack-company-title" className={headingClass}>
                {t('onboarding.ready_pack_company_title', { defaultValue: 'Your kind of company' })}
              </h3>
              <span className="text-xs tabular-nums text-content-tertiary">{shownCompanies.length}</span>
              <span className="text-xs text-content-tertiary">
                {t('onboarding.ready_pack_company_hint', {
                  defaultValue: 'Optional. Combine it with a pack to start with the modules and menu your trade needs.',
                })}
              </span>
            </div>
            <div className={TILE_GRID}>
              {shownCompanies.map((e) => {
                const selected = e.key === companyKey;
                const Icon = getPresetIcon(e.preset.icon);
                return (
                  <button
                    key={e.key}
                    type="button"
                    onClick={() => onCompanyChange(selected ? null : e.preset)}
                    disabled={disabled}
                    aria-pressed={selected}
                    title={e.name}
                    data-testid={`ready-pack-company-${e.key}`}
                    className={clsx(
                      'relative flex min-w-0 flex-col items-start gap-1.5 rounded-xl p-3 text-start transition-all duration-200',
                      selected
                        ? 'bg-oe-blue-subtle/50 ring-2 ring-oe-blue/45 shadow-sm'
                        : 'bg-surface-primary ring-1 ring-border-light hover:shadow-sm hover:-translate-y-0.5',
                      disabled && 'opacity-60 cursor-not-allowed',
                    )}
                  >
                    {selected && (
                      <span className="absolute end-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white shadow-sm">
                        <Check size={12} strokeWidth={3} />
                      </span>
                    )}
                    <Icon size={18} className="text-oe-blue-text" aria-hidden />
                    <span className="line-clamp-2 w-full break-words text-sm font-semibold text-content-primary">
                      {e.name}
                    </span>
                    <span className="line-clamp-2 w-full break-words text-2xs text-content-tertiary">
                      {e.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        {/* The chosen company type stays visible when a filter hides its tile. */}
        {chosenCompany && !shownCompanies.some((e) => e.key === chosenCompany.key) && (
          <p className="text-xs text-content-secondary" data-testid="ready-pack-company-hidden">
            {t('onboarding.ready_pack_company_chosen', {
              defaultValue: 'Company type: {{name}}',
              name: chosenCompany.name,
            })}
          </p>
        )}
      </div>
    </div>
  );
}
