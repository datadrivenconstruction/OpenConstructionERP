// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CustomCategoryList — the "My categories" group in the /costs sidebar.
 *
 * Lists the distinct ``classification.collection`` values the user typed
 * onto their OWN custom cost items (region='CUSTOM'). The built-in
 * classification tree below it is region-scoped and never lists these, so
 * a user-created category like "Structural Steel" was previously only
 * reachable via free-text search. Each entry is a clickable browse target
 * that filters the items list to that collection.
 *
 * Pure presentational: the parent owns the query (and the gate that only
 * shows this on the "All" regions tab, where custom items are browsable)
 * and passes the resolved list down, mirroring how `CatalogsSection`
 * receives ``selectedId`` / ``onSelect``.
 */
import { House } from 'lucide-react';
import type { TFunction } from 'i18next';

export interface CustomCategoryListProps {
  /** Distinct custom collection names, already de-duplicated by the backend. */
  categories: string[];
  /** Currently selected collection ('' = none). */
  selectedCategory: string;
  /** Toggle handler: emits the category to select, or '' to clear. */
  onSelect: (category: string) => void;
  /** Humanizes a raw collection token into a display label. */
  labelFor: (category: string) => string;
  /** Translation function from the parent's `useTranslation`. */
  t: TFunction;
}

export function CustomCategoryList({
  categories,
  selectedCategory,
  onSelect,
  labelFor,
  t,
}: CustomCategoryListProps) {
  if (categories.length === 0) return null;

  return (
    <div
      className="border-b border-border-light px-2 py-2"
      data-testid="costs-custom-categories"
    >
      <p className="px-1 pb-1.5 text-2xs font-semibold uppercase tracking-wide text-content-quaternary">
        {t('costs.my_categories', { defaultValue: 'My categories' })}
      </p>
      <div className="flex flex-col gap-0.5">
        {categories.map((cat) => {
          const isSelected = selectedCategory === cat;
          const label = labelFor(cat);
          return (
            <button
              key={cat}
              type="button"
              // Clicking the active category clears it, mirroring the
              // catalog-chip and tree toggle behaviour.
              onClick={() => onSelect(isSelected ? '' : cat)}
              aria-pressed={isSelected}
              title={label}
              className={`group flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors ${
                isSelected
                  ? 'bg-oe-blue text-white'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              <House
                size={12}
                className={`shrink-0 ${isSelected ? 'text-white/80' : 'text-oe-blue'}`}
              />
              <span className="flex-1 truncate text-left">{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
