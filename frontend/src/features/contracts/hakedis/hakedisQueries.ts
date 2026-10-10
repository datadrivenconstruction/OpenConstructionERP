// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cached reads of one payment certificate, and how a refusal from the
// server is read.
//
// A certificate is derived from its source document, so its key hangs under
// that document's own: every screen that already refreshes a progress claim
// (a line edit, populate, each status transition) refreshes its certificate
// with no extra wiring, the same way the submission check does.
//
// The certificate is certified by the source document's own transition (the
// claim's Certify, the pay application's finance approval), which lives on
// another component. When that transition is refused because the certificate
// is not complete, the refusal is recorded here under the certificate's key
// and the panel reads it from the cache, so the two components need not know
// each other.

import type { QueryClient } from '@tanstack/react-query';

import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { claimKey } from '../claimQueries';
import type { HakedisFinding, HakedisLocale, HakedisSource } from './api';

/** Every cached read of one document's certificate, whatever the language. */
export function hakedisBaseKey(source: HakedisSource) {
  return source.kind === 'progress_claim'
    ? ([...claimKey(source.id), 'hakedis'] as const)
    : (['subcontractors', 'hakedis', source.id] as const);
}

export function hakedisKey(source: HakedisSource, locale: HakedisLocale) {
  return [...hakedisBaseKey(source), locale] as const;
}

/** The stored statutory tax lines of the document, read from the tax module. */
export function hakedisStatutoryKey(source: HakedisSource) {
  return ['hakedis', 'statutory', source.kind, source.id] as const;
}

/** The last refusal of the certifying transition. Not under the document's key: it is not refetched. */
export function hakedisRefusalKey(source: HakedisSource) {
  return ['hakedis', 'refusal', source.kind, source.id] as const;
}

/**
 * The language the certificate is read in on screen: Turkish for a Turkish
 * interface, English for every other, because the server words its labels in
 * those two only. The printed language is chosen separately, on the export
 * control.
 */
export function screenLocale(language: string | null | undefined): HakedisLocale {
  return (language ?? '').toLowerCase().split('-')[0] === 'tr' ? 'tr' : 'en';
}

/** A refusal as the screen needs it, whichever module wrote it. */
export interface HakedisRefusal {
  status: number | null;
  /** `detail.error` (certificate routes) or `detail.code` (tax routes); empty when the answer names none. */
  code: string;
  /** The i18n key the tax routes send with a refusal; empty otherwise. */
  key: string;
  /** The server's own sentence. */
  message: string;
  /** Request validation messages by field name (`amount`, `pct`, `note`, ...). */
  fields: Record<string, string>;
  /** Findings sent with a refused certification. */
  findings: HakedisFinding[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asFinding(value: unknown): HakedisFinding | null {
  if (!isRecord(value) || typeof value.rule_id !== 'string' || typeof value.message !== 'string') return null;
  return {
    rule_id: value.rule_id,
    rule_name: typeof value.rule_name === 'string' ? value.rule_name : '',
    severity: typeof value.severity === 'string' ? value.severity : 'error',
    message: value.message,
    suggestion: typeof value.suggestion === 'string' ? value.suggestion : null,
    element_ref: typeof value.element_ref === 'string' ? value.element_ref : null,
    details: isRecord(value.details) ? value.details : {},
    engine_error: value.engine_error === true,
  };
}

/**
 * Read a thrown error into its parts.
 *
 * Three shapes reach this screen: a structured `detail` object with `error`
 * (certificate routes) or `code` and `key` (tax routes), FastAPI's request
 * validation list with a `loc` per entry, and a plain string.
 */
export function readRefusal(err: unknown): HakedisRefusal {
  const refusal: HakedisRefusal = { status: null, code: '', key: '', message: '', fields: {}, findings: [] };
  if (!(err instanceof ApiError)) {
    refusal.message = getErrorMessage(err);
    return refusal;
  }
  refusal.status = err.status;
  const detail = isRecord(err.body) ? err.body.detail : undefined;
  if (Array.isArray(detail)) {
    for (const entry of detail) {
      if (!isRecord(entry) || typeof entry.msg !== 'string') continue;
      const path = Array.isArray(entry.loc)
        ? entry.loc.filter((part): part is string => typeof part === 'string' && part !== 'body')
        : [];
      const field = path[path.length - 1];
      if (field && !(field in refusal.fields)) refusal.fields[field] = entry.msg;
    }
  } else if (isRecord(detail)) {
    if (typeof detail.error === 'string') refusal.code = detail.error;
    else if (typeof detail.code === 'string') refusal.code = detail.code;
    if (typeof detail.key === 'string') refusal.key = detail.key;
    if (typeof detail.message === 'string') refusal.message = detail.message;
    if (Array.isArray(detail.findings)) {
      refusal.findings = detail.findings
        .map(asFinding)
        .filter((finding): finding is HakedisFinding => finding !== null);
    }
  }
  if (!refusal.message) refusal.message = err.message;
  return refusal;
}

/** True for the answer of a contract that has no certificate layout. */
export function isHakedisNotAvailable(err: unknown): boolean {
  const refusal = readRefusal(err);
  return refusal.status === 404 && refusal.code === 'hakedis_not_available';
}

/**
 * Record a refused certifying transition, for the panel to show against the
 * lines. Returns true when the refusal was the certificate's, so the caller
 * can word its own message accordingly.
 *
 * Such a refusal also refreshes the certificate: the findings it shows should
 * be the ones the server just judged it on.
 */
export function recordHakedisRefusal(qc: QueryClient, source: HakedisSource, err: unknown): boolean {
  const refusal = readRefusal(err);
  const own = refusal.code === 'hakedis_not_ready';
  qc.setQueryData<HakedisRefusal | null>(hakedisRefusalKey(source), own ? refusal : null);
  if (own) void qc.invalidateQueries({ queryKey: hakedisBaseKey(source) });
  return own;
}

/** Forget a recorded refusal, after anything that changes what the server would answer. */
export function clearHakedisRefusal(qc: QueryClient, source: HakedisSource): void {
  qc.setQueryData<HakedisRefusal | null>(hakedisRefusalKey(source), null);
}
