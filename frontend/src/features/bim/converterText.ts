import type { TFunction } from 'i18next';

/**
 * Display text of a DDC converter. The backend (`converter_source.PACKAGES`)
 * is the only place that knows a converter's version and the source-format
 * range it reads; both arrive in the API row and are only interpolated here.
 * Names and descriptions are translated by converter id, with the English the
 * API sent as the fallback for an id this build does not know.
 */
export interface ConverterTextSource {
  id: string;
  name: string;
  description?: string;
  format_range?: string;
}

export function converterName(t: TFunction, c: ConverterTextSource): string {
  return t(`converters.name_${c.id}`, { defaultValue: c.name });
}

export function converterDescription(t: TFunction, c: ConverterTextSource): string {
  return t(`converters.desc_${c.id}`, {
    defaultValue: c.description ?? '',
    range: c.format_range ?? '',
  });
}

/** `v0.6.8`. The version the installer stamped, else the build this release ships. */
export function converterVersionLabel(
  installedVersion: string | null | undefined,
  shippedVersion: string,
): string {
  return `v${installedVersion || shippedVersion}`;
}

/** Why a converter cannot be installed on this host, and what to do instead. */
export function converterPlatformMessage(t: TFunction, converterId: string): string {
  return t('api_errors.converter_platform_unsupported', {
    format: converterId.toUpperCase(),
    defaultValue:
      'The {{format}} converter runs on Windows 10/11 x64 only. Run OpenConstructionERP on Windows to convert these files.',
  });
}
