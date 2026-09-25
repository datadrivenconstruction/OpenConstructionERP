// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The reader-language name of a project region option.
 *
 * The region picker used to print its English labels in every language, so a
 * Croatian estimator scanning for "Hrvatska" found only "Croatia". An option
 * that stands for one country carries its ISO 3166 code and is named by the
 * runtime's own country names (`Intl.DisplayNames`), which cover every locale
 * we ship without a single new string. Multi-country groupings ("DACH",
 * "Nordics") have no code and keep their label.
 */

export interface RegionOption {
  value: string;
  label: string;
  /** ISO 3166-1 alpha-2 code when the option is a single country. */
  iso?: string;
}

const namesByLang = new Map<string, Intl.DisplayNames | null>();

function regionNames(lang: string): Intl.DisplayNames | null {
  const cached = namesByLang.get(lang);
  if (cached !== undefined) return cached;
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames([lang || 'en'], { type: 'region', fallback: 'none' });
  } catch {
    names = null;
  }
  namesByLang.set(lang, names);
  return names;
}

export function regionOptionLabel(option: RegionOption, lang: string): string {
  if (!option.iso) return option.label;
  return regionNames(lang)?.of(option.iso) ?? option.label;
}
