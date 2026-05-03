// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Translation settings tab — surfaces dictionary downloads, cache state
 * and in-flight tasks for the translation cascade
 * (``backend/app/core/translation``).
 *
 * Five sections:
 *   A — Cache stats (rowcount + hit count)
 *   B — Downloaded dictionaries table
 *   C — Download a MUSE language pair
 *   D — Trigger / process an IATE TBX dump (URL or local path)
 *   E — In-flight tasks card
 *
 * The component is mounted from ``ProjectSettingsPage.tsx`` and is
 * deep-linkable via ``#translation`` thanks to the existing hash-pulse
 * effect in that page (introduced for ``#fx-rates`` in Issue #105).
 *
 * Keep all user-facing strings in i18n with ``defaultValue`` per the
 * project convention (``CLAUDE.md`` → "i18n EVERYWHERE").
 */

import {
  memo,
  useCallback,
  useMemo,
  useState,
  type FormEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  Database,
  Download,
  FileText,
  Globe,
  HardDrive,
  Languages,
  Loader2,
  Sparkles,
} from 'lucide-react';
import { Badge, Button, Card, CardHeader, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { IATE_ALLOWED_PREFIXES, isIateUrlAllowed } from './api';
import { useTranslationStatus, useTriggerDownload } from './queries';
import type { DictionaryEntry, InFlightTask, LookupKind } from './types';

/* ── Constants ─────────────────────────────────────────────────────────── */

/** Pre-canned MUSE pairs — the canonical MUSE list is ~100 pairs but
 *  these are the ones most relevant for construction documents.  The
 *  "Other" option lets users type any code — MUSE 404s on missing pairs,
 *  surfaced as a backend error toast. */
const PRESET_MUSE_PAIRS: ReadonlyArray<{ src: string; tgt: string }> = [
  { src: 'en', tgt: 'de' },
  { src: 'de', tgt: 'en' },
  { src: 'en', tgt: 'fr' },
  { src: 'fr', tgt: 'en' },
  { src: 'en', tgt: 'es' },
  { src: 'es', tgt: 'en' },
  { src: 'en', tgt: 'it' },
  { src: 'it', tgt: 'en' },
  { src: 'en', tgt: 'ru' },
  { src: 'ru', tgt: 'en' },
  { src: 'en', tgt: 'pl' },
  { src: 'pl', tgt: 'en' },
  { src: 'en', tgt: 'tr' },
  { src: 'tr', tgt: 'en' },
  { src: 'en', tgt: 'nl' },
  { src: 'nl', tgt: 'en' },
  { src: 'de', tgt: 'fr' },
  { src: 'fr', tgt: 'de' },
  { src: 'de', tgt: 'es' },
  { src: 'es', tgt: 'de' },
];

const CUSTOM_PAIR_VALUE = '__custom__';

const LANG_CODE_RE = /^[a-z]{2,3}$/i;

/* ── Helpers ───────────────────────────────────────────────────────────── */

/** Format bytes as KB/MB/GB with one decimal place. */
function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const idx = Math.min(
    units.length - 1,
    Math.floor(Math.log(bytes) / Math.log(1024)),
  );
  const value = bytes / 1024 ** idx;
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

/** Render a Unix epoch (seconds) as a relative time string ("3 minutes ago").
 *  We avoid date-fns here to keep the bundle slim. */
function formatRelative(epochSeconds: number, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (!Number.isFinite(epochSeconds) || epochSeconds <= 0) return '—';
  const diffMs = Date.now() - epochSeconds * 1000;
  if (diffMs < 0) return t('common.just_now', { defaultValue: 'just now' });
  const seconds = Math.round(diffMs / 1000);
  if (seconds < 60) return t('common.just_now', { defaultValue: 'just now' });
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return t('common.minutes_ago', {
      defaultValue: '{{count}} minute ago',
      defaultValue_plural: '{{count}} minutes ago',
      count: minutes,
    });
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return t('common.hours_ago', {
      defaultValue: '{{count}} hour ago',
      defaultValue_plural: '{{count}} hours ago',
      count: hours,
    });
  }
  const days = Math.round(hours / 24);
  if (days < 30) {
    return t('common.days_ago', {
      defaultValue: '{{count}} day ago',
      defaultValue_plural: '{{count}} days ago',
      count: days,
    });
  }
  const months = Math.round(days / 30);
  return t('common.months_ago', {
    defaultValue: '{{count}} month ago',
    defaultValue_plural: '{{count}} months ago',
    count: months,
  });
}

/* ── Public component ──────────────────────────────────────────────────── */

export interface TranslationSettingsTabProps {
  /** Project id is reserved for project-scoped translation overrides
   *  (Phase 4) — the dictionaries themselves are user-scoped and live
   *  under ``~/.openestimate``. */
  readonly projectId?: string;
  /** Optional anchor id for the deep-link / pulse effect.  Defaults to
   *  ``"translation"`` so ``/projects/:id/settings#translation`` works. */
  readonly anchorId?: string;
}

export function TranslationSettingsTab({
  anchorId = 'translation',
}: TranslationSettingsTabProps) {
  const { t } = useTranslation();
  const statusQuery = useTranslationStatus();

  const dictionaries = statusQuery.data?.dictionaries ?? {};
  const cacheStats = statusQuery.data?.cache ?? { rows: 0, hits: 0 };
  const inFlight = statusQuery.data?.in_flight ?? [];

  const museEntries: ReadonlyArray<DictionaryEntry> = dictionaries.muse ?? [];
  const iateEntries: ReadonlyArray<DictionaryEntry> = dictionaries.iate ?? [];
  const allEntries: ReadonlyArray<{ kind: LookupKind; entry: DictionaryEntry }> =
    useMemo(
      () => [
        ...museEntries.map((e) => ({ kind: 'muse' as const, entry: e })),
        ...iateEntries.map((e) => ({ kind: 'iate' as const, entry: e })),
      ],
      [museEntries, iateEntries],
    );

  return (
    <Card padding="lg" id={anchorId}>
      <CardHeader
        title={t('translation.title', { defaultValue: 'Translation' })}
        subtitle={t('translation.subtitle', {
          defaultValue:
            'Bilingual dictionaries used by the cross-language matcher. Downloads run in the background; nothing fetches automatically.',
        })}
        action={
          <Badge variant={statusQuery.isLoading ? 'neutral' : 'blue'} size="sm">
            {statusQuery.isLoading
              ? t('common.loading', { defaultValue: 'Loading…' })
              : t('translation.dict_count', {
                  defaultValue: '{{count}} dictionary',
                  defaultValue_plural: '{{count}} dictionaries',
                  count: allEntries.length,
                })}
          </Badge>
        }
      />

      {statusQuery.isError && (
        <div
          className="mt-4 flex items-start gap-2 rounded-lg border border-semantic-error/40 bg-semantic-error/5 px-3 py-2 text-sm text-semantic-error"
          role="alert"
          data-testid="translation-status-error"
        >
          <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            {t('translation.status_error', {
              defaultValue: 'Could not load dictionary status: {{error}}',
              error: getErrorMessage(statusQuery.error),
            })}
          </span>
        </div>
      )}

      {/* Section A — cache stats */}
      <CacheStatsSection
        rows={cacheStats.rows}
        hits={cacheStats.hits}
        loading={statusQuery.isLoading}
      />

      {/* Section B — downloaded dictionaries */}
      <DictionariesTable entries={allEntries} loading={statusQuery.isLoading} />

      {/* Section C — MUSE form */}
      <MuseDownloadForm inFlight={inFlight} />

      {/* Section D — IATE form */}
      <IateDownloadForm inFlight={inFlight} />

      {/* Section E — in-flight tasks */}
      <InFlightTasksSection tasks={inFlight} />
    </Card>
  );
}

/* ─── Section A — Cache stats ──────────────────────────────────────────── */

const CacheStatsSection = memo(function CacheStatsSection({
  rows,
  hits,
  loading,
}: {
  rows: number;
  hits: number;
  loading: boolean;
}) {
  const { t } = useTranslation();
  return (
    <section className="mt-6" aria-labelledby="translation-cache-heading">
      <h4
        id="translation-cache-heading"
        className="text-sm font-semibold text-content-primary flex items-center gap-2"
      >
        <Database size={14} className="text-oe-blue" aria-hidden />
        {t('translation.cache.title', { defaultValue: 'Translation cache' })}
      </h4>
      <p
        className="mt-1.5 text-sm text-content-secondary"
        data-testid="translation-cache-stats"
      >
        {loading
          ? t('common.loading', { defaultValue: 'Loading…' })
          : t('translation.cache.summary', {
              defaultValue:
                '{{rows}} cached translations · {{hits}} hits since last reset',
              rows,
              hits,
            })}
      </p>
    </section>
  );
});

/* ─── Section B — Dictionary table ─────────────────────────────────────── */

const DictionariesTable = memo(function DictionariesTable({
  entries,
  loading,
}: {
  entries: ReadonlyArray<{ kind: LookupKind; entry: DictionaryEntry }>;
  loading: boolean;
}) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <section className="mt-6" data-testid="translation-dict-loading">
        <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
          <HardDrive size={14} className="text-oe-blue" aria-hidden />
          {t('translation.dict.title', {
            defaultValue: 'Downloaded dictionaries',
          })}
        </h4>
        <p className="mt-2 text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      </section>
    );
  }

  if (entries.length === 0) {
    return (
      <section className="mt-6">
        <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
          <HardDrive size={14} className="text-oe-blue" aria-hidden />
          {t('translation.dict.title', {
            defaultValue: 'Downloaded dictionaries',
          })}
        </h4>
        <div
          className="mt-3 rounded-lg border border-dashed border-border-light bg-surface-secondary/30 px-4 py-6 text-center"
          data-testid="translation-dict-empty"
        >
          <p className="text-sm text-content-tertiary">
            {t('translation.dict.empty', {
              defaultValue:
                'No dictionaries downloaded yet. Download a MUSE language pair below to enable cross-lingual lookup before the LLM tier.',
            })}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="mt-6">
      <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
        <HardDrive size={14} className="text-oe-blue" aria-hidden />
        {t('translation.dict.title', {
          defaultValue: 'Downloaded dictionaries',
        })}
      </h4>
      <div className="mt-3 overflow-hidden rounded-lg border border-border-light">
        <table
          className="min-w-full text-sm"
          data-testid="translation-dict-table"
        >
          <thead className="bg-surface-secondary/40">
            <tr className="text-left text-xs uppercase tracking-wide text-content-tertiary">
              <th className="px-4 py-2 font-medium">
                {t('translation.dict.col_kind', { defaultValue: 'Source' })}
              </th>
              <th className="px-4 py-2 font-medium">
                {t('translation.dict.col_pair', { defaultValue: 'Pair' })}
              </th>
              <th className="px-4 py-2 font-medium text-right">
                {t('translation.dict.col_size', { defaultValue: 'Size' })}
              </th>
              <th className="px-4 py-2 font-medium text-right">
                {t('translation.dict.col_modified', {
                  defaultValue: 'Modified',
                })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {entries.map(({ kind, entry }) => (
              <tr
                key={`${kind}-${entry.pair}`}
                className="hover:bg-surface-hover/40"
                data-testid={`translation-dict-row-${kind}-${entry.pair}`}
              >
                <td className="px-4 py-2.5">
                  <Badge
                    variant={kind === 'muse' ? 'blue' : 'success'}
                    size="sm"
                  >
                    {kind.toUpperCase()}
                  </Badge>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-content-primary">
                  {entry.pair}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-content-secondary">
                  {formatBytes(entry.size_bytes)}
                </td>
                <td className="px-4 py-2.5 text-right text-content-tertiary">
                  {formatRelative(entry.modified_at, t)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
});

/* ─── Section C — MUSE download form ───────────────────────────────────── */

function MuseDownloadForm({
  inFlight,
}: {
  inFlight: ReadonlyArray<InFlightTask>;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const trigger = useTriggerDownload();

  const [presetValue, setPresetValue] = useState<string>(`en|de`);
  const [customSrc, setCustomSrc] = useState<string>('');
  const [customTgt, setCustomTgt] = useState<string>('');

  // Resolve the effective (src, tgt) pair from current form state.
  const isCustom = presetValue === CUSTOM_PAIR_VALUE;
  const effective = useMemo<{ src: string; tgt: string } | null>(() => {
    if (isCustom) {
      const s = customSrc.trim().toLowerCase();
      const target = customTgt.trim().toLowerCase();
      if (!LANG_CODE_RE.test(s) || !LANG_CODE_RE.test(target)) return null;
      if (s === target) return null;
      return { src: s, tgt: target };
    }
    const [s, target] = presetValue.split('|');
    if (!s || !target) return null;
    return { src: s, tgt: target };
  }, [isCustom, presetValue, customSrc, customTgt]);

  // Is there already a MUSE download in-flight for the current pair?
  const pairInFlight = useMemo<InFlightTask | undefined>(() => {
    if (!effective) return undefined;
    return inFlight.find(
      (task) =>
        task.kind === 'muse' &&
        (task.status === 'queued' || task.status === 'running'),
    );
  }, [effective, inFlight]);

  const canSubmit = !!effective && !pairInFlight && !trigger.isPending;

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      if (!effective || !canSubmit) return;
      trigger.mutate(
        { kind: 'muse', source_lang: effective.src, target_lang: effective.tgt },
        {
          onSuccess: () => {
            addToast({
              type: 'success',
              title: t('translation.muse.queued_title', {
                defaultValue: 'Dictionary download queued',
              }),
              message: t('translation.muse.queued_message', {
                defaultValue: 'MUSE {{src}}-{{tgt}} is downloading in the background.',
                src: effective.src,
                tgt: effective.tgt,
              }),
            });
          },
          onError: (err) => {
            addToast({
              type: 'error',
              title: t('translation.muse.failed_title', {
                defaultValue: 'Download failed',
              }),
              message: getErrorMessage(err),
            });
          },
        },
      );
    },
    [addToast, canSubmit, effective, t, trigger],
  );

  return (
    <section
      className="mt-8 space-y-3"
      aria-labelledby="translation-muse-heading"
    >
      <h4
        id="translation-muse-heading"
        className="text-sm font-semibold text-content-primary flex items-center gap-2"
      >
        <Languages size={14} className="text-oe-blue" aria-hidden />
        {t('translation.muse.title', {
          defaultValue: 'Download MUSE language pair',
        })}
      </h4>
      <p className="text-xs text-content-tertiary max-w-2xl">
        {t('translation.muse.description', {
          defaultValue:
            'MUSE is a free bilingual dictionary set (Facebook AI Research, CC-BY-NC). Each pair adds ~5 MB and is consulted before the LLM tier of the translation cascade.',
        })}
      </p>

      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap items-end gap-3"
        data-testid="translation-muse-form"
      >
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="muse-pair"
            className="text-sm font-medium text-content-primary"
          >
            {t('translation.muse.pair_label', { defaultValue: 'Pair' })}
          </label>
          <select
            id="muse-pair"
            value={presetValue}
            onChange={(e) => setPresetValue(e.target.value)}
            className="h-10 min-w-[14rem] rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            data-testid="translation-muse-preset"
          >
            {PRESET_MUSE_PAIRS.map((p) => (
              <option key={`${p.src}-${p.tgt}`} value={`${p.src}|${p.tgt}`}>
                {p.src.toUpperCase()} → {p.tgt.toUpperCase()}
              </option>
            ))}
            <option value={CUSTOM_PAIR_VALUE}>
              {t('translation.muse.other_pair', {
                defaultValue: 'Other (xx-yy)',
              })}
            </option>
          </select>
        </div>

        {isCustom && (
          <>
            <div className="w-24">
              <Input
                label={t('translation.muse.src_label', { defaultValue: 'Source' })}
                value={customSrc}
                onChange={(e) =>
                  setCustomSrc(e.target.value.toLowerCase().slice(0, 3))
                }
                placeholder="en"
                maxLength={3}
                data-testid="translation-muse-custom-src"
              />
            </div>
            <div className="w-24">
              <Input
                label={t('translation.muse.tgt_label', { defaultValue: 'Target' })}
                value={customTgt}
                onChange={(e) =>
                  setCustomTgt(e.target.value.toLowerCase().slice(0, 3))
                }
                placeholder="de"
                maxLength={3}
                data-testid="translation-muse-custom-tgt"
              />
            </div>
          </>
        )}

        <Button
          variant="primary"
          size="sm"
          type="submit"
          icon={<Download size={14} />}
          loading={trigger.isPending}
          disabled={!canSubmit}
          data-testid="translation-muse-submit"
        >
          {t('translation.muse.download', { defaultValue: 'Download' })}
        </Button>

        {pairInFlight && (
          <span
            className="inline-flex items-center gap-1.5 text-xs text-content-secondary"
            data-testid="translation-muse-inflight"
          >
            <Loader2 size={12} className="animate-spin" aria-hidden />
            {t('translation.muse.in_flight', {
              defaultValue: 'A MUSE download is already running ({{pct}}%)',
              pct: Math.round((pairInFlight.progress ?? 0) * 100),
            })}
          </span>
        )}
      </form>
    </section>
  );
}

/* ─── Section D — IATE form ────────────────────────────────────────────── */

function IateDownloadForm({
  inFlight,
}: {
  inFlight: ReadonlyArray<InFlightTask>;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const trigger = useTriggerDownload();

  const [url, setUrl] = useState<string>('');
  const [localPath, setLocalPath] = useState<string>('');

  const urlIsAllowed = url.trim() === '' || isIateUrlAllowed(url.trim());
  const urlError =
    url.trim() !== '' && !urlIsAllowed
      ? t('translation.iate.url_not_allowlisted', {
          defaultValue:
            'URL must start with one of the allowed prefixes (see hint below).',
        })
      : undefined;

  const iateInFlight = useMemo(
    () =>
      inFlight.find(
        (task) =>
          task.kind === 'iate' &&
          (task.status === 'queued' || task.status === 'running'),
      ),
    [inFlight],
  );

  const submitUrl = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const trimmed = url.trim();
      if (!trimmed || !isIateUrlAllowed(trimmed)) return;
      trigger.mutate(
        { kind: 'iate', url: trimmed },
        {
          onSuccess: () => {
            addToast({
              type: 'success',
              title: t('translation.iate.queued_title', {
                defaultValue: 'IATE download queued',
              }),
              message: t('translation.iate.queued_url_message', {
                defaultValue: 'Fetching the TBX dump from the mirror.',
              }),
            });
          },
          onError: (err) => {
            addToast({
              type: 'error',
              title: t('translation.iate.failed_title', {
                defaultValue: 'IATE download failed',
              }),
              message: getErrorMessage(err),
            });
          },
        },
      );
    },
    [addToast, t, trigger, url],
  );

  const submitLocal = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const trimmed = localPath.trim();
      if (!trimmed) return;
      trigger.mutate(
        { kind: 'iate', local_tbx_path: trimmed },
        {
          onSuccess: () => {
            addToast({
              type: 'success',
              title: t('translation.iate.queued_title', {
                defaultValue: 'IATE processing queued',
              }),
              message: t('translation.iate.queued_local_message', {
                defaultValue: 'Parsing {{path}} into per-language TSV files.',
                path: trimmed,
              }),
            });
          },
          onError: (err) => {
            addToast({
              type: 'error',
              title: t('translation.iate.failed_title', {
                defaultValue: 'IATE processing failed',
              }),
              message: getErrorMessage(err),
            });
          },
        },
      );
    },
    [addToast, localPath, t, trigger],
  );

  return (
    <section className="mt-8 space-y-4" aria-labelledby="translation-iate-heading">
      <h4
        id="translation-iate-heading"
        className="text-sm font-semibold text-content-primary flex items-center gap-2"
      >
        <Globe size={14} className="text-oe-blue" aria-hidden />
        {t('translation.iate.title', {
          defaultValue: 'IATE EU termbase',
        })}
      </h4>

      <p className="text-xs text-content-tertiary max-w-2xl">
        {t('translation.iate.description', {
          defaultValue:
            'The IATE export is ~600 MB unzipped. Processing extracts term pairs into per-language TSV files. Most users download it manually from iate.europa.eu and point at the local file.',
        })}
      </p>

      {/* Local path — recommended path */}
      <form
        onSubmit={submitLocal}
        className="space-y-2 rounded-lg border border-border-light bg-surface-secondary/30 p-4"
        data-testid="translation-iate-local-form"
      >
        <h5 className="text-sm font-medium text-content-primary flex items-center gap-2">
          <FileText size={13} className="text-content-tertiary" aria-hidden />
          {t('translation.iate.local_title', {
            defaultValue: 'Process a local TBX file (recommended)',
          })}
        </h5>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[20rem]">
            <Input
              label={t('translation.iate.local_label', {
                defaultValue: 'Absolute path to .tbx or .tbx.zip',
              })}
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
              placeholder={t('translation.iate.local_placeholder', {
                defaultValue: '/home/me/Downloads/IATE_export.tbx',
              })}
              data-testid="translation-iate-local-input"
            />
          </div>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            icon={<Sparkles size={14} />}
            loading={trigger.isPending}
            disabled={!localPath.trim() || trigger.isPending}
            data-testid="translation-iate-local-submit"
          >
            {t('translation.iate.process', { defaultValue: 'Process file' })}
          </Button>
        </div>
      </form>

      {/* URL — alternate path with explicit allowlist hint */}
      <form
        onSubmit={submitUrl}
        className="space-y-2 rounded-lg border border-border-light bg-surface-secondary/30 p-4"
        data-testid="translation-iate-url-form"
      >
        <h5 className="text-sm font-medium text-content-primary flex items-center gap-2">
          <Globe size={13} className="text-content-tertiary" aria-hidden />
          {t('translation.iate.url_title', {
            defaultValue: 'Trigger download from a mirror URL',
          })}
        </h5>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[20rem]">
            <Input
              label={t('translation.iate.url_label', {
                defaultValue: 'TBX mirror URL',
              })}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://iate.europa.eu/exports/IATE_export.tbx.zip"
              error={urlError}
              data-testid="translation-iate-url-input"
            />
          </div>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            icon={<Download size={14} />}
            loading={trigger.isPending}
            disabled={!url.trim() || !urlIsAllowed || trigger.isPending}
            data-testid="translation-iate-url-submit"
          >
            {t('translation.iate.trigger', {
              defaultValue: 'Trigger download',
            })}
          </Button>
        </div>
        <p className="text-xs text-content-tertiary">
          {t('translation.iate.allowlist_hint', {
            defaultValue:
              'Allowed prefixes (mirrors backend SSRF guard): {{prefixes}}',
            prefixes: IATE_ALLOWED_PREFIXES.join(', '),
          })}
        </p>
      </form>

      {iateInFlight && (
        <p
          className="text-xs text-content-secondary inline-flex items-center gap-1.5"
          data-testid="translation-iate-inflight"
        >
          <Loader2 size={12} className="animate-spin" aria-hidden />
          {t('translation.iate.in_flight', {
            defaultValue:
              'IATE processing in progress ({{pct}}%) — large files may take several minutes.',
            pct: Math.round((iateInFlight.progress ?? 0) * 100),
          })}
        </p>
      )}
    </section>
  );
}

/* ─── Section E — In-flight tasks ──────────────────────────────────────── */

const InFlightTasksSection = memo(function InFlightTasksSection({
  tasks,
}: {
  tasks: ReadonlyArray<InFlightTask>;
}) {
  const { t } = useTranslation();
  const active = tasks.filter(
    (task) => task.status === 'queued' || task.status === 'running',
  );
  if (active.length === 0) return null;

  return (
    <section
      className="mt-8 space-y-2"
      aria-labelledby="translation-tasks-heading"
      data-testid="translation-tasks-section"
    >
      <h4
        id="translation-tasks-heading"
        className="text-sm font-semibold text-content-primary flex items-center gap-2"
      >
        <Loader2 size={14} className="text-oe-blue animate-spin" aria-hidden />
        {t('translation.tasks.title', {
          defaultValue: 'In-flight downloads',
        })}
      </h4>
      <ul className="space-y-2">
        {active.map((task) => {
          const pct = Math.max(0, Math.min(100, Math.round(task.progress * 100)));
          return (
            <li
              key={task.task_id}
              className="rounded-lg border border-border-light bg-surface-secondary/30 px-3 py-2 text-sm"
              data-testid={`translation-task-${task.task_id}`}
            >
              <div className="flex items-center gap-2">
                <Badge
                  variant={task.kind === 'muse' ? 'blue' : 'success'}
                  size="sm"
                >
                  {task.kind.toUpperCase()}
                </Badge>
                <span className="text-content-secondary">
                  {t(`translation.tasks.status.${task.status}`, {
                    defaultValue: task.status,
                  })}
                </span>
                <span className="ml-auto tabular-nums text-content-tertiary text-xs">
                  {pct}%
                </span>
              </div>
              <div
                className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-border-light"
                role="progressbar"
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={t('translation.tasks.progress_aria', {
                  defaultValue: 'Download progress',
                })}
              >
                <div
                  className="h-full bg-oe-blue transition-[width]"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
});

export default TranslationSettingsTab;
