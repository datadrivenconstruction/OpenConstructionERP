// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RulePackCard — one tile in the Rule Library grid.
 *
 * Renders the pack name + category chip, a truncated description,
 * rule count, region chips and classification chips. The whole card
 * is keyboard-accessible: Enter / Space invoke onSelect so power users
 * can browse with a screen-reader.
 */

import { useCallback, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { Eye, Layers3 } from 'lucide-react';
import clsx from 'clsx';
import type { SeedPack, SeedPackCategory, SeedPackFormat } from './SEED_PACKS';

export interface RulePackCardProps {
  pack: SeedPack;
  onSelect: (pack: SeedPack) => void;
  testId?: string;
}

const FORMAT_LABEL: Record<SeedPackFormat, { key: string; fallback: string }> = {
  ifc: { key: 'rulePacks.format_ifc', fallback: 'IFC' },
  revit: { key: 'rulePacks.format_revit', fallback: 'Revit®' },
};

const CATEGORY_COLOR: Record<SeedPackCategory, string> = {
  Accessibility: 'bg-blue-50 text-blue-700 border-blue-100',
  'Cost Classification': 'bg-emerald-50 text-emerald-700 border-emerald-100',
  'Fire Safety': 'bg-red-50 text-red-700 border-red-100',
  MEP: 'bg-amber-50 text-amber-700 border-amber-100',
  Naming: 'bg-purple-50 text-purple-700 border-purple-100',
};

function categoryLabelKey(category: SeedPackCategory): string {
  // Reuse the same underscored keys the filter pills use
  // (RulePackLibrary.tsx) so the chip and the pill stay in sync and
  // resolve against the existing en.ts entries (rulePacks.category_*).
  switch (category) {
    case 'Accessibility':
      return 'rulePacks.category_accessibility';
    case 'Cost Classification':
      return 'rulePacks.category_cost';
    case 'Fire Safety':
      return 'rulePacks.category_fire';
    case 'MEP':
      return 'rulePacks.category_mep';
    case 'Naming':
      return 'rulePacks.category_naming';
  }
}

export function RulePackCard({ pack, onSelect, testId }: RulePackCardProps) {
  const { t } = useTranslation();

  const handleClick = useCallback(() => {
    onSelect(pack);
  }, [onSelect, pack]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect(pack);
      }
    },
    [onSelect, pack],
  );

  const testIdRoot = testId ?? `rule-pack-card-${pack.id}`;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      data-testid={testIdRoot}
      aria-label={pack.name}
      className="group flex h-full cursor-pointer flex-col gap-3 rounded-xl border border-border-light bg-surface-primary p-4 transition-all hover:-translate-y-0.5 hover:border-oe-blue/40 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="line-clamp-2 text-sm font-semibold text-content-primary">
          {pack.name}
        </h3>
        <div className="flex flex-shrink-0 items-center gap-1">
          <span
            className="rounded-full border border-border-light bg-surface-secondary px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-content-secondary"
            data-testid={`${testIdRoot}-format`}
          >
            {t(FORMAT_LABEL[pack.format].key, {
              defaultValue: FORMAT_LABEL[pack.format].fallback,
            })}
          </span>
          <span
            className={clsx(
              'rounded-full border px-2 py-0.5 text-[10px] font-medium',
              CATEGORY_COLOR[pack.category],
            )}
            data-testid={`${testIdRoot}-category`}
          >
            {t(categoryLabelKey(pack.category), { defaultValue: pack.category })}
          </span>
        </div>
      </div>

      <p
        className="line-clamp-2 text-xs leading-relaxed text-content-secondary"
        data-testid={`${testIdRoot}-description`}
      >
        {pack.description}
      </p>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="neutral" size="sm">
          <Layers3 size={10} className="mr-1 inline" />
          {t('rulePacks.rules_count', {
            defaultValue: '{{count}} rules',
            count: pack.rule_count,
          })}
        </Badge>
        {pack.classifications.map((cls) => (
          <span
            key={cls}
            className="rounded-md border border-border-light bg-surface-secondary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary"
            data-testid={`${testIdRoot}-classification-${cls}`}
          >
            {cls}
          </span>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1">
        {pack.regions.length === 0 ? (
          <span className="rounded-md bg-surface-tertiary px-1.5 py-0.5 text-[10px] font-medium uppercase text-content-tertiary">
            INT
          </span>
        ) : (
          pack.regions.map((region) => (
            <span
              key={region}
              className="rounded-md bg-surface-tertiary px-1.5 py-0.5 text-[10px] font-medium uppercase text-content-secondary"
              data-testid={`${testIdRoot}-region-${region}`}
            >
              {region}
            </span>
          ))
        )}
      </div>

      <div className="mt-auto flex items-center justify-end pt-2">
        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-oe-blue group-hover:underline">
          <Eye size={12} />
          {t('rulePacks.preview', { defaultValue: 'Preview & install' })}
        </span>
      </div>
    </div>
  );
}

export default RulePackCard;
