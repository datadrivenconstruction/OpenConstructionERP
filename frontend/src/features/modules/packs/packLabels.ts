// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Words and icons the packs screens share: type badges, band headings, and
 *  country and language names in the reader's own language. */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Building2, Globe, HardHat, Sparkles, type LucideIcon } from 'lucide-react';
import type { PackType } from '@/shared/hooks/usePartnerPack';
import type { PackMarketBand } from '@/shared/lib/regionalPack';
import type { PackSort, PackStatus } from './packCatalog';

export const PACK_TYPE_META: Record<
  PackType,
  { labelKey: string; defaultLabel: string; icon: LucideIcon; variant: 'blue' | 'neutral' | 'success' | 'warning' }
> = {
  country: { labelKey: 'modules.pack_type_country', defaultLabel: 'Country', icon: Globe, variant: 'blue' },
  industry: { labelKey: 'modules.pack_type_industry', defaultLabel: 'Industry', icon: HardHat, variant: 'neutral' },
  partner: { labelKey: 'modules.pack_type_partner', defaultLabel: 'Partner', icon: Building2, variant: 'success' },
  showcase: { labelKey: 'modules.pack_type_showcase', defaultLabel: 'Showcase', icon: Sparkles, variant: 'warning' },
};

/**
 * The heading over each band of packs.
 *
 * One literal `t()` call per band rather than a computed
 * `modules.packs_band_${band}`, so every string this page can render is
 * greppable from the locale files and the orphan-key gate can see all seven.
 */
export function useBandLabels(): Record<PackMarketBand, string> {
  const { t } = useTranslation();
  return {
    home: t('modules.packs_band_home', { defaultValue: 'Suggested for your region' }),
    americas: t('modules.packs_band_americas', { defaultValue: 'Americas' }),
    china: t('modules.packs_band_china', { defaultValue: 'China' }),
    india: t('modules.packs_band_india', { defaultValue: 'India' }),
    europe: t('modules.packs_band_europe', { defaultValue: 'Europe' }),
    rest: t('modules.packs_band_rest', { defaultValue: 'Other markets' }),
    'cross-region': t('modules.packs_band_cross_region', {
      defaultValue: 'Industry and cross-region',
    }),
  };
}

export function useSortLabels(): Record<PackSort, string> {
  const { t } = useTranslation();
  return {
    recommended: t('packs.sort_recommended', { defaultValue: 'Recommended' }),
    name: t('packs.sort_name', { defaultValue: 'Name (A to Z)' }),
    region: t('packs.sort_region', { defaultValue: 'Region' }),
  };
}

export function useStatusLabels(): Record<PackStatus, string> {
  const { t } = useTranslation();
  return {
    active: t('packs.status_active', { defaultValue: 'Active' }),
    available: t('packs.status_available', { defaultValue: 'Not active' }),
  };
}

function displayNames(locale: string, type: 'region' | 'language'): Intl.DisplayNames | null {
  try {
    return new Intl.DisplayNames([locale, 'en'], { type });
  } catch {
    return null;
  }
}

/** Country and language names in the reader's language, from the runtime. */
export function useDisplayNames(): {
  locale: string;
  countryName: (iso: string) => string | null;
  languageName: (code: string) => string | null;
} {
  const { i18n } = useTranslation();
  const locale = i18n.language || 'en';
  return useMemo(() => {
    const regions = displayNames(locale, 'region');
    const languages = displayNames(locale, 'language');
    return {
      locale,
      countryName: (iso: string) => {
        try {
          return regions?.of(iso.toUpperCase()) ?? null;
        } catch {
          return null;
        }
      },
      languageName: (code: string) => {
        try {
          const name = languages?.of(code) ?? null;
          // Capitalise for list use: several locales name languages in lower case.
          return name ? name.charAt(0).toLocaleUpperCase(locale) + name.slice(1) : null;
        } catch {
          return null;
        }
      },
    };
  }, [locale]);
}
