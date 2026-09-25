// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The reader-language name of a regional markup template.
 *
 * A template that stands for countries lists their ISO 3166 codes and is
 * named by the runtime's own country names (`Intl.DisplayNames`), joined with
 * the locale's own list pattern when there are several (DACH reads
 * "Deutschland, Österreich und Schweiz" in German). A template that stands
 * for no fixed set of countries is described in words through a locale key.
 * The name of the national method or document under it (Troškovnik, NRM,
 * GAEB) is a proper name and is shown as it is.
 */
import { regionOptionLabel } from '@/features/projects/regionLabel';

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: Record<string, unknown>) => string;

export interface MarkupRegion {
  /** Backend key in DEFAULT_MARKUP_TEMPLATES. */
  code: string;
  flag: string;
  /** Proper name of the national method or document, not translated. */
  standard: string;
  /** ISO 3166-1 alpha-2 codes the template stands for; defaults to `code`. */
  countries?: string[];
  /** Locale key and English default for a template with no fixed countries. */
  labelKey?: string;
  labelDefault?: string;
}

const listsByLang = new Map<string, Intl.ListFormat | null>();

function listFormat(lang: string): Intl.ListFormat | null {
  const cached = listsByLang.get(lang);
  if (cached !== undefined) return cached;
  let list: Intl.ListFormat | null = null;
  try {
    list = new Intl.ListFormat([lang || 'en'], { style: 'long', type: 'conjunction' });
  } catch {
    list = null;
  }
  listsByLang.set(lang, list);
  return list;
}

export function markupRegionLabel(region: MarkupRegion, lang: string, t: Translate): string {
  if (region.labelKey) return t(region.labelKey, { defaultValue: region.labelDefault ?? region.code });
  const names = (region.countries ?? [region.code]).map((iso) =>
    regionOptionLabel({ value: iso, label: iso, iso }, lang),
  );
  if (names.length === 1) return names[0]!;
  return listFormat(lang)?.format(names) ?? names.join(', ');
}
