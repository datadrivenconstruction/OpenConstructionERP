// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Typed fetch wrappers around the translation HTTP routes.
 *
 *   POST /api/v1/translation/translate                  → TranslateResponse
 *   POST /api/v1/translation/lookup-tables/download     → DownloadResponse
 *   GET  /api/v1/translation/lookup-tables/status       → StatusResponse
 *
 * Auth, Accept-Language, JSON serialization and error extraction are all
 * handled by the shared ``apiGet`` / ``apiPost`` helpers.
 */

import { apiGet, apiPost } from '@/shared/lib/api';
import type {
  DownloadRequestBody,
  DownloadResponse,
  StatusResponse,
  TranslateRequestBody,
  TranslateResponse,
} from './types';

/* ── SSRF allowlist (mirrors the backend) ─────────────────────────────── */

/**
 * Allowlist of URL prefixes that the IATE downloader will accept.  This
 * MUST stay in lock-step with ``_IATE_ALLOWED_PREFIXES`` in
 * ``backend/app/core/translation/downloader.py`` — that constant is the
 * source of truth.  Mirrored on the client only so we can short-circuit
 * obviously bad URLs (and explain *why* they're rejected) before round-
 * tripping to the backend.
 *
 * ``OE_IATE_EXTRA_HOSTS`` env-var overrides (per-deployment self-hosted
 * mirrors) are NOT mirrored here — those are validated server-side and
 * the user can simply paste them into the URL field.  We surface a
 * server 422/400 if the deployment hasn't allowlisted them.
 */
export const IATE_ALLOWED_PREFIXES: readonly string[] = [
  'https://iate.europa.eu/',
  'https://datadrivenconstruction.io/',
  'https://openconstructionerp.com/',
  'https://github.com/datadrivenconstruction/',
  'https://raw.githubusercontent.com/datadrivenconstruction/',
];

/** Returns ``true`` if ``url`` starts with one of the allowed prefixes. */
export function isIateUrlAllowed(url: string): boolean {
  if (typeof url !== 'string') return false;
  const trimmed = url.trim();
  if (!trimmed) return false;
  return IATE_ALLOWED_PREFIXES.some((p) => trimmed.startsWith(p));
}

/* ── Endpoints ────────────────────────────────────────────────────────── */

/**
 * Fetch the current dictionary inventory, cache stats, and the caller's
 * in-flight download tasks.
 */
export async function getTranslationStatus(): Promise<StatusResponse> {
  return apiGet<StatusResponse>('/v1/translation/lookup-tables/status');
}

/**
 * Kick off a MUSE / IATE download in the background.  Returns the task
 * id immediately; poll the status endpoint to track progress.
 */
export async function triggerLookupDownload(
  body: DownloadRequestBody,
): Promise<DownloadResponse> {
  return apiPost<DownloadResponse, DownloadRequestBody>(
    '/v1/translation/lookup-tables/download',
    body,
  );
}

/**
 * Translate one term — primarily a QA / debug surface; the matcher
 * runs the cascade automatically inside ``/v1/match/element``.
 */
export async function translateOne(
  body: TranslateRequestBody,
): Promise<TranslateResponse> {
  return apiPost<TranslateResponse, TranslateRequestBody>(
    '/v1/translation/translate',
    body,
  );
}
