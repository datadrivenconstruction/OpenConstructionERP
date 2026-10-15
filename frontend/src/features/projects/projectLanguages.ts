// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { SUPPORTED_LANGUAGES } from '@/app/i18n';

export interface ProjectLanguageOption {
  value: string;
  label: string;
}

/**
 * The languages a project can be set to, read from the interface language
 * picker rather than written out a second time.
 *
 * The hand-written copy in the project form stopped at 25 languages while the
 * picker kept growing, so a Ukrainian user could run the whole interface in
 * Ukrainian and still not make it the language of their project. Every offered
 * language is answered by a backend locale file as well, which is what a
 * project language needs on the server side.
 *
 * Regional variants (en-GB, es-MX, pt-BR and the rest) stay out: their bundles
 * hold only the words a region says differently and fall back to the base
 * language for everything else, and the backend has no locale file for them.
 */
export const PROJECT_LANGUAGES: ProjectLanguageOption[] = SUPPORTED_LANGUAGES.filter(
  (l) => !l.code.includes('-'),
).map((l) => ({
  value: l.code,
  // The picker names the base entry "English (International)" to tell it apart
  // from the two regional ones, which do not appear here.
  label: l.code === 'en' ? 'English' : l.name,
}));
