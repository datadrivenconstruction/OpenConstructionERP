// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RulePackLibrary — top-level Rule Library browser.
 *
 * Renders a filterable / searchable grid of the seed `RulePackCard`s
 * shipped in `SEED_PACKS.ts`. A "Paste your own YAML" CTA opens the
 * preview/install modal in custom mode. Selecting a card opens it in
 * seed mode with the YAML pre-loaded.
 *
 * Every template ships in two flavours — one written against IFC entity
 * classes, one against Revit categories — so a prominent format switch
 * swaps the shown set between the two. A dismissible explainer states, in
 * plain language, what a requirement template is and how it runs at import.
 *
 * Filtering is purely client-side: the seed packs are inlined so the
 * library functions offline. Search matches against `name + description`
 * case-insensitively; format is a two-way toggle and category pills are an
 * exclusive single-select.
 */

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardEdit, Search, BookOpenCheck, Boxes } from 'lucide-react';
import clsx from 'clsx';

import { EmptyState, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { RulePackCard } from './RulePackCard';
import { RulePackPreviewModal } from './RulePackPreviewModal';
import {
  SEED_PACKS,
  type SeedPack,
  type SeedPackCategory,
  type SeedPackFormat,
} from './SEED_PACKS';

export interface RulePackLibraryProps {
  /** Active project id — required to install a pack. */
  projectId: string | null;
  /** data-testid prefix override. */
  testId?: string;
}

type CategoryFilter = 'all' | SeedPackCategory;

const FORMAT_FILTERS: Array<{
  value: SeedPackFormat;
  labelKey: string;
  defaultLabel: string;
  hintKey: string;
  hintDefault: string;
}> = [
  {
    value: 'ifc',
    labelKey: 'rulePacks.format_ifc',
    defaultLabel: 'IFC',
    hintKey: 'rulePacks.format_hint_ifc',
    hintDefault:
      'IFC templates select by entity class (IfcWall, IfcSpace) and check Pset property names.',
  },
  {
    value: 'revit',
    labelKey: 'rulePacks.format_revit',
    defaultLabel: 'Revit®',
    hintKey: 'rulePacks.format_hint_revit',
    hintDefault:
      'Revit® templates select by category (Walls, Rooms, Doors) and check Revit parameters, noting Type, Instance and Shared parameters.',
  },
];

const CATEGORY_FILTERS: Array<{
  value: CategoryFilter;
  labelKey: string;
  defaultLabel: string;
}> = [
  { value: 'all', labelKey: 'rulePacks.category_all', defaultLabel: 'All' },
  {
    value: 'Accessibility',
    labelKey: 'rulePacks.category_accessibility',
    defaultLabel: 'Accessibility',
  },
  {
    value: 'Cost Classification',
    labelKey: 'rulePacks.category_cost',
    defaultLabel: 'Cost',
  },
  { value: 'Fire Safety', labelKey: 'rulePacks.category_fire', defaultLabel: 'Fire' },
  { value: 'MEP', labelKey: 'rulePacks.category_mep', defaultLabel: 'MEP' },
  { value: 'Naming', labelKey: 'rulePacks.category_naming', defaultLabel: 'Naming' },
];

type ModalState =
  | { kind: 'closed' }
  | { kind: 'seed'; pack: SeedPack }
  | { kind: 'custom' };

export function RulePackLibrary({ projectId, testId = 'rule-pack-library' }: RulePackLibraryProps) {
  const { t } = useTranslation();
  const [format, setFormat] = useState<SeedPackFormat>('ifc');
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [query, setQuery] = useState('');
  const [modal, setModal] = useState<ModalState>({ kind: 'closed' });

  const categoryIds = useMemo<readonly CategoryFilter[]>(
    () => CATEGORY_FILTERS.map((f) => f.value),
    [],
  );
  const onCategoryKeyDown = useTabKeyboardNav<CategoryFilter>({
    ids: categoryIds,
    activeId: category,
    onChange: setCategory,
    orientation: 'horizontal',
  });

  const visiblePacks = useMemo(() => {
    const q = query.trim().toLowerCase();
    return SEED_PACKS.filter((pack) => {
      if (pack.format !== format) return false;
      if (category !== 'all' && pack.category !== category) return false;
      if (!q) return true;
      return (
        pack.name.toLowerCase().includes(q) ||
        pack.description.toLowerCase().includes(q)
      );
    });
  }, [format, category, query]);

  const activeFormatHint = useMemo(
    () => FORMAT_FILTERS.find((f) => f.value === format) ?? FORMAT_FILTERS[0]!,
    [format],
  );

  const handleSelectPack = useCallback((pack: SeedPack) => {
    setModal({ kind: 'seed', pack });
  }, []);

  const handleOpenCustom = useCallback(() => {
    setModal({ kind: 'custom' });
  }, []);

  const handleCloseModal = useCallback(() => {
    setModal({ kind: 'closed' });
  }, []);

  return (
    <div className="flex flex-col gap-5" data-testid={testId}>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold text-content-primary">
            <BookOpenCheck size={18} className="text-oe-blue" />
            {t('rulePacks.title', { defaultValue: 'Rule Library' })}
          </h2>
        </div>
        <button
          type="button"
          onClick={handleOpenCustom}
          data-testid={`${testId}-paste-custom`}
          className="flex items-center gap-1.5 rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-3 py-1.5 text-[12px] font-medium text-oe-blue hover:bg-oe-blue/10"
        >
          <ClipboardEdit size={14} />
          {t('rulePacks.paste_custom', { defaultValue: 'Paste your own YAML' })}
        </button>
      </div>

      {/* Plain-language explainer: what a template is + how it runs at import */}
      <DismissibleInfo
        storageKey="rule-library"
        title={t('rulePacks.intro_title', {
          defaultValue: 'What a requirement template is',
        })}
        more={
          <IntroRichText
            text={t('rulePacks.intro_more', {
              defaultValue:
                '**How it is used at import.** When you import a BIM model the platform runs every installed template against it before the model is stored.\n\n1. Each rule selects the elements it applies to, by IFC entity class or Revit® category.\n2. It checks that the required property or parameter is present and valid on each matched element.\n3. You get a traffic-light report, pass, warning or error, linked back to the exact element.\n\n**Two flavours, one intent.** Every requirement ships for both formats. IFC templates read Pset property names on IFC entity classes; Revit templates read Revit parameters on Revit categories and note whether each is a Type, Instance or Shared parameter. Pick the format your models arrive in.\n\n**Preview before you install.** Open any template to read its rules in plain language and, when a model is loaded, dry-run it to see exactly what would pass or fail.',
            })}
          />
        }
      >
        {t('rulePacks.intro_body', {
          defaultValue:
            'A requirement template is a checklist of the data a delivered model must carry, its properties, classifications and dimensions. Install one and it runs automatically at import: every element is checked and you get a pass, warning or error report you can act on.',
        })}
      </DismissibleInfo>

      {/* Model-format switch — swaps the whole library between the IFC and
          Revit flavours of the same templates. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-content-secondary">
          <Boxes size={14} className="text-content-tertiary" />
          {t('rulePacks.format_label', { defaultValue: 'Model format' })}
        </span>
        <div
          role="group"
          aria-label={t('rulePacks.format_aria', {
            defaultValue: 'Choose the model format the templates target',
          })}
          data-testid={`${testId}-formats`}
          className="inline-flex items-center rounded-lg border border-border-light bg-surface-secondary p-0.5"
        >
          {FORMAT_FILTERS.map((f) => {
            const active = format === f.value;
            return (
              <button
                key={f.value}
                type="button"
                aria-pressed={active}
                onClick={() => setFormat(f.value)}
                data-testid={`${testId}-format-${f.value}`}
                className={clsx(
                  'rounded-md px-3 py-1 text-[12px] font-semibold transition-colors',
                  active
                    ? 'bg-oe-blue text-white shadow-sm'
                    : 'text-content-secondary hover:text-content-primary',
                )}
              >
                {t(f.labelKey, { defaultValue: f.defaultLabel })}
              </button>
            );
          })}
        </div>
        <span
          className="text-[11px] text-content-tertiary"
          data-testid={`${testId}-format-hint`}
        >
          {t(activeFormatHint.hintKey, { defaultValue: activeFormatHint.hintDefault })}
        </span>
      </div>

      {/* Filter pills + search */}
      <div className="flex flex-wrap items-center gap-3">
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="tablist"
          aria-label={t('rulePacks.filter_aria', {
            defaultValue: 'Filter rule packs by category',
          })}
          onKeyDown={onCategoryKeyDown}
          data-testid={`${testId}-filters`}
        >
          {CATEGORY_FILTERS.map((f) => {
            const active = category === f.value;
            const slug = f.value.toLowerCase().replace(/\s+/g, '-');
            return (
              <button
                key={f.value}
                type="button"
                role="tab"
                id={`rule-pack-category-tab-${slug}`}
                aria-selected={active}
                aria-controls={`rule-pack-category-panel-${slug}`}
                tabIndex={active ? 0 : -1}
                onClick={() => setCategory(f.value)}
                data-testid={`${testId}-filter-${slug}`}
                className={clsx(
                  'rounded-full border px-3 py-1 text-[11px] font-medium transition-colors',
                  active
                    ? 'border-oe-blue bg-oe-blue text-white shadow-sm'
                    : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                )}
              >
                {t(f.labelKey, { defaultValue: f.defaultLabel })}
              </button>
            );
          })}
        </div>
        <div className="relative ml-auto min-w-[220px] flex-1 max-w-sm">
          <Search
            size={14}
            className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('rulePacks.search_placeholder', {
              defaultValue: 'Search packs…',
            })}
            data-testid={`${testId}-search`}
            className="h-9 w-full rounded-lg border border-border-light bg-surface-primary ps-8 pe-3 text-[12px] text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </div>
      </div>

      {/* Grid */}
      {visiblePacks.length === 0 ? (
        <EmptyState
          icon={<Search size={24} strokeWidth={1.5} />}
          title={t('rulePacks.empty_title', { defaultValue: 'No matching rule packs' })}
          description={t('rulePacks.empty_desc', {
            defaultValue:
              'Try a different category, clear the search, or switch the model format.',
          })}
        />
      ) : (
        <div
          className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3"
          data-testid={`${testId}-grid`}
        >
          {visiblePacks.map((pack) => (
            <RulePackCard key={pack.id} pack={pack} onSelect={handleSelectPack} />
          ))}
        </div>
      )}

      {/* Preview / install modal */}
      <RulePackPreviewModal
        open={modal.kind !== 'closed'}
        onClose={handleCloseModal}
        seedPack={modal.kind === 'seed' ? modal.pack : null}
        projectId={projectId}
      />
    </div>
  );
}

export default RulePackLibrary;
