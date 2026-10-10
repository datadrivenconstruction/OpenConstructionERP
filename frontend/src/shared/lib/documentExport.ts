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
 * A document catalogue is narrower than the interface's language list, so the
 * languages a control may offer are listed here per document family and have
 * to be kept in step with the backend catalogue named beside each list.
 */
import { API_BASE, activeLanguageTag, downloadWithAuth } from './api';

export type DocumentFormat = 'pdf' | 'xlsx';

/**
 * Languages of the registers and record forms built on
 * `backend/app/core/register_export.py` (`DocumentCatalogue.supported` of the
 * rfi register, submittals, correspondence, changeorders, transmittals,
 * variations and claims_evidence catalogues).
 */
export const REGISTER_DOCUMENT_LOCALES: readonly string[] = ['en', 'tr'];

/**
 * Languages of the daily diary PDF (`SUPPORTED_PDF_LOCALES` in
 * `backend/app/modules/daily_diary/pdf_translations.py`).
 */
export const DIARY_DOCUMENT_LOCALES: readonly string[] = ['en', 'de', 'tr'];

/**
 * Each language under its own name, which is how a reader looks for it in a
 * list. These are data, like the names in the language picker, and are not
 * translated.
 */
const LOCALE_ENDONYMS: Record<string, string> = {
  en: 'English',
  de: 'Deutsch',
  tr: 'Türkçe',
};

/** The name a language goes by in a document-language choice. */
export function documentLocaleName(locale: string): string {
  return LOCALE_ENDONYMS[locale] ?? locale.toUpperCase();
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
