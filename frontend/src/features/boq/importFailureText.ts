// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wording for a bill import the server refused as a whole.
 *
 * ``/import/auto/`` and ``/import/preview/`` answer a file they cannot read
 * with a coded ``detail``: ``{code, params, message}``. The code names the
 * failure (``xpwe_not_well_formed``, ``workbook_password_protected``, ...),
 * ``params`` carries the values its wording needs, and ``message`` is the
 * server's English fallback. The wording lives under
 * ``boq.import_error.<code>``, so the reader sees it in their own language; a
 * test walks every code the importers raise and checks en.ts has it.
 *
 * The same detail comes back from a background import job as ``error_code``,
 * ``error_params`` and ``error``.
 */

import { fmtDate, fmtList } from '@/shared/lib/formatters';

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: Record<string, unknown>) => string;

export interface ImportFailure {
  code?: string | null;
  params?: Record<string, unknown> | null;
  message?: string | null;
}

/** The coded detail in ``value``, or null when it is not one (a plain string, a 422 list). */
export function asImportFailure(value: unknown): ImportFailure | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const candidate = value as ImportFailure;
  return typeof candidate.code === 'string' || typeof candidate.message === 'string' ? candidate : null;
}

/** The values a wording interpolates, formatted for the reader. */
function wordingValues(params: Record<string, unknown>): Record<string, unknown> {
  const values: Record<string, unknown> = { ...params };
  if (Array.isArray(params.columns)) values.columns = fmtList(params.columns.map(String));
  if (typeof params.imported_at === 'string') values.imported_at = fmtDate(params.imported_at);
  return values;
}

/** A refused import in the reader's language; ``fallback`` when nothing better is known. */
export function importFailureText(failure: ImportFailure, t: Translate, fallback: string): string {
  const message = failure.message || fallback;
  if (!failure.code) return message;
  return t(`boq.import_error.${failure.code}`, { defaultValue: message, ...wordingValues(failure.params ?? {}) });
}

/** The wording for an error response body whose ``detail`` is coded, or null to let the caller word it. */
export function importFailureFromBody(body: unknown, t: Translate, fallback: string): string | null {
  const detail = typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined;
  const failure = asImportFailure(detail);
  return failure ? importFailureText(failure, t, fallback) : null;
}

/** Whether an error response says the file was already imported into this bill (409). */
export function alreadyImported(status: number, body: unknown): ImportFailure | null {
  if (status !== 409) return null;
  const detail = typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined;
  const failure = asImportFailure(detail);
  return failure?.code === 'import_already_done' ? failure : null;
}
