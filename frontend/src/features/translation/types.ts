// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * TypeScript types mirroring the backend translation router schemas.
 *
 * Source of truth: ``backend/app/core/translation/router.py`` and
 * ``backend/app/core/translation/downloader.py``.  Until the OpenAPI
 * generator (``npm run api:generate``) is wired with a running backend,
 * keep these in lock-step manually.
 *
 * Server-supplied fields are ``readonly`` so the settings tab cannot
 * accidentally mutate response data shared across React Query consumers.
 */

/* ── Translate (test harness) ─────────────────────────────────────────── */

export type TranslationTier =
  | 'lookup_muse'
  | 'lookup_iate'
  | 'cache'
  | 'llm'
  | 'fallback';

export interface TranslateRequestBody {
  readonly text: string;
  readonly source_lang: string;
  readonly target_lang: string;
  readonly domain?: string;
}

export interface TranslateResponse {
  readonly translated: string;
  readonly source_lang: string;
  readonly target_lang: string;
  readonly tier_used: TranslationTier;
  readonly confidence: number;
  readonly cost_usd: number | null;
}

/* ── Lookup-table download trigger ────────────────────────────────────── */

export type LookupKind = 'muse' | 'iate';

export interface DownloadRequestBody {
  readonly kind: LookupKind;
  readonly source_lang?: string;
  readonly target_lang?: string;
  readonly url?: string;
  readonly local_tbx_path?: string;
}

export interface DownloadResponse {
  readonly task_id: string;
  readonly kind: string;
  readonly status: string; // "queued"
}

/* ── Status report ────────────────────────────────────────────────────── */

/** One row inside ``StatusResponse.dictionaries[kind]`` — see
 *  ``downloader.list_downloaded`` in the backend. */
export interface DictionaryEntry {
  readonly pair: string;
  readonly path: string;
  readonly size_bytes: number;
  /** Unix epoch seconds, as a float (``stat.st_mtime``). */
  readonly modified_at: number;
}

export interface CacheStats {
  readonly rows: number;
  readonly hits: number;
}

/** One in-flight download task — owner is filtered server-side per
 *  Phase 0 fix; the client never sees other users' tasks. */
export interface InFlightTask {
  readonly task_id: string;
  readonly kind: LookupKind;
  readonly status: 'queued' | 'running' | 'done' | 'failed';
  readonly progress: number; // 0.0 .. 1.0
  readonly error?: string;
  readonly path?: string;
  readonly pairs?: Readonly<Record<string, string>>;
}

export interface StatusResponse {
  readonly dictionaries: {
    readonly muse?: ReadonlyArray<DictionaryEntry>;
    readonly iate?: ReadonlyArray<DictionaryEntry>;
  };
  readonly cache: CacheStats;
  readonly in_flight: ReadonlyArray<InFlightTask>;
}
