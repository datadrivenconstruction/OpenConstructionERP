// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Downloads of the printed site documents: a register as a PDF or a workbook,
 * and the form of one record as a PDF.
 *
 * The server renders these in a language of its own choosing: `?locale=`
 * first, then `Accept-Language`, then English. A download goes through
 * `downloadWithAuth`, which sends no `Accept-Language`, so the language always
 * travels as `?locale=`; without it a Turkish reader gets an English register.
 *
 * Which languages a document exists in is decided by the server. The lists
 * below are the single place the web client keeps them, one per document
 * family, and `test_register_documents_speak_every_language.py` fails when a
 * list stops matching the catalogues it names (`GET /api/v1/i18n/document-locales`
 * reports the same sets).
 */
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { API_BASE, activeLanguageTag, downloadWithAuth } from './api';

export type DocumentFormat = 'pdf' | 'xlsx';

/**
 * Languages of the registers and record forms built on
 * `backend/app/core/document_forms_i18n.py` (the submittals, rfi log, correspondence,
 * changeorders, transmittals, variations and claims_evidence catalogues): every
 * language the backend runs in except Bengali, which no bundled PDF face can draw
 * (`REGISTER_UNRENDERABLE` in `document_forms_i18n.py`).
 */
export const REGISTER_DOCUMENT_LOCALES: readonly string[] = [
  'en', 'de', 'ru', 'fr', 'es', 'pt', 'it', 'nl', 'pl', 'cs', 'hu', 'tr', 'ar', 'ur', 'zh', 'ja', 'ko', 'hi', 'sv', 'no',
  'da', 'fi', 'bg', 'hr', 'id', 'ro', 'th', 'vi', 'uk', 'uz', 'et', 'ky', 'kk', 'fil', 'fa', 'he', 'el',
];

/** Languages of the daily diary PDF: the same set as the registers. */
export const DIARY_DOCUMENT_LOCALES: readonly string[] = REGISTER_DOCUMENT_LOCALES;

/**
 * Languages of the purchase order, goods receipt, invoice and payment forms
 * (`procurement` and `finance` in `document_forms_i18n.py`).
 */
export const PURCHASING_DOCUMENT_LOCALES: readonly string[] = ['en', 'de', 'ru', 'ar', 'ur', 'fa', 'he'];

/**
 * A language under its own name, which is how a reader looks for it in a
 * list. The names are the ones in the interface's language picker
 * (`SUPPORTED_LANGUAGES`) without the regional qualifier, so "English
 * (International)" reads "English"; a code the picker does not list is named
 * by the runtime's own language names, and last of all by its upper-case code.
 */
export function documentLocaleName(locale: string): string {
  const entry = SUPPORTED_LANGUAGES.find((l) => l.code === locale);
  if (entry) return entry.name.replace(/\s*\(.*\)\s*$/, '');
  // A combined code such as the hakedis `tr-en` is not a language: it keeps its upper-case spelling.
  if (!/^[a-z]{2,3}$/.test(locale)) return locale.toUpperCase();
  try {
    return new Intl.DisplayNames([locale], { type: 'language' }).of(locale) ?? locale.toUpperCase();
  } catch {
    return locale.toUpperCase();
  }
}

/** The same language in English, which the search box also matches ("German" finds Deutsch). */
export function documentLocaleEnglishName(locale: string): string {
  const entry = SUPPORTED_LANGUAGES.find((l) => l.code === locale);
  if (entry && 'english' in entry && typeof entry.english === 'string') return entry.english.replace(/\s*\(.*\)\s*$/, '');
  if (locale === 'en') return 'English';
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' }).of(locale) ?? locale;
  } catch {
    return locale;
  }
}

/**
 * The language a document is offered in before the reader chooses one: the
 * interface language when the document exists in it, otherwise English, which
 * is what the server would fall back to anyway. Naming the fallback here means
 * the control shows the language the file will really be in.
 *
 * @param supported - Languages the document exists in.
 * @param active - The interface language; read from i18next when omitted.
 */
export function defaultDocumentLocale(
  supported: readonly string[] = REGISTER_DOCUMENT_LOCALES,
  active: string | null = activeLanguageTag(),
): string {
  const base = (active ?? '').split('-')[0]?.toLowerCase() ?? '';
  if (base && supported.includes(base)) return base;
  return supported.includes('en') ? 'en' : supported[0] ?? 'en';
}

/**
 * Absolute URL of a document route.
 *
 * @param path - Route below the API base, e.g. `/v1/submittals/export/`. The
 *   trailing slash is part of the route and is kept as given.
 * @param params - Query parameters; empty and undefined values are left out.
 */
export function documentExportUrl(
  path: string,
  params: Record<string, string | undefined> = {},
): string {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(name, value);
  }
  const qs = query.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
}

/**
 * Download a project register.
 *
 * The routes take the project, the format and the language and nothing else:
 * a register is printed whole, whatever filter the screen is showing.
 *
 * @param path - Register route below the API base.
 * @param projectId - The project whose register is wanted.
 * @param format - `pdf` for the printable register, `xlsx` for the workbook.
 * @param locale - Document language.
 * @param fallbackName - File name stem used only when the response names no file.
 * @throws Error carrying the server's message when the request is refused.
 */
export function downloadRegister(
  path: string,
  projectId: string,
  format: DocumentFormat,
  locale: string,
  fallbackName: string,
): Promise<void> {
  return downloadWithAuth(
    documentExportUrl(path, { project_id: projectId, format, locale }),
    `${fallbackName}.${format}`,
  );
}

/**
 * Download the printable PDF form of one record.
 *
 * @param path - Record route below the API base, ending in `/export/pdf/`.
 * @param locale - Document language.
 * @param fallbackName - File name stem used only when the response names no file.
 * @throws Error carrying the server's message when the request is refused.
 */
export function downloadRecordPdf(path: string, locale: string, fallbackName: string): Promise<void> {
  return downloadWithAuth(documentExportUrl(path, { locale }), `${fallbackName}.pdf`);
}
