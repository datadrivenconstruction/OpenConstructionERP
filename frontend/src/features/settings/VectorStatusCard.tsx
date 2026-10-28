// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * VectorStatusCard — admin panel for the cross-module semantic memory.
 *
 * Renders a per-collection table fetched from `/api/v1/search/status/`
 * with one-click reindex buttons that hit the matching per-module
 * `/vector/reindex/` endpoint.
 *
 * Lives in Settings → Vector Search.  Anyone with admin access to a
 * tenant can verify the indexing health of every collection at a
 * glance and trigger a backfill without dropping into the API or CLI.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Database,
  Loader2,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button } from '@/shared/ui';
import { apiPost } from '@/shared/lib/api';
import {
  collectionLabel,
  fetchSearchStatus,
  type SearchStatusCollection,
} from '@/features/search/api';
import { useToastStore } from '@/stores/useToastStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/** Map of collection name → backend reindex endpoint path.
 *
 * Paths are passed to ``apiPost`` which already prepends the ``/api``
 * base URL, so they must start at ``/v1/...`` — not ``/api/v1/...``.
 * A stray ``/api`` prefix here turned every reindex click into a 404
 * hitting ``/api/api/v1/...`` ("Not Found" in the Settings toast). */
const REINDEX_PATH: Record<string, string> = {
  oe_boq_positions: '/v1/boq/vector/reindex/',
  oe_documents: '/v1/documents/vector/reindex/',
  oe_tasks: '/v1/tasks/vector/reindex/',
  oe_risks: '/v1/risk/vector/reindex/',
  oe_bim_elements: '/v1/bim_hub/vector/reindex/',
  oe_requirements: '/v1/requirements/vector/reindex/',
  oe_validation: '/v1/validation/vector/reindex/',
  oe_chat: '/v1/erp_chat/vector/reindex/',
};

interface ReindexResult {
  indexed: number;
  skipped: number;
  purged: boolean;
  collection: string;
  /** How much of the collection the pass actually walked, against the ceiling
   *  it was allowed to walk, and whether it stopped on that ceiling with rows
   *  left over. Every reindex endpoint reports these; they are optional here
   *  because a client can outlive the server it is talking to, and a missing
   *  `truncated` has to read as "not truncated" rather than as a crash. */
  scanned?: number;
  cap?: number;
  truncated?: boolean;
}

export default function VectorStatusCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [purgeFirst, setPurgeFirst] = useState(false);
  // Last truncated pass per collection. A toast is read once and dismissed;
  // "part of this collection is not in the index" is a state of the system,
  // so it stays on the row it belongs to until a later pass covers it.
  const [truncated, setTruncated] = useState<
    Record<string, { scanned: number; cap: number }>
  >({});

  const statusQuery = useQuery({
    queryKey: ['vector-search-status'],
    queryFn: fetchSearchStatus,
    staleTime: 30 * 1000,
  });

  const reindexMut = useMutation({
    mutationFn: async (collection: string): Promise<ReindexResult> => {
      const path = REINDEX_PATH[collection];
      if (!path) {
        throw new Error(`No reindex endpoint for ${collection}`);
      }
      const url = `${path}${purgeFirst ? '?purge_first=true' : ''}`;
      return apiPost<ReindexResult>(url, {});
    },
    onSuccess: (result, collection) => {
      // A collection too large for one pass is indexed up to a ceiling and the
      // rest is left out of the search index entirely. That is reported first
      // because it changes how every other number in this response reads: an
      // `indexed` count that looks like a complete backfill is a count of the
      // part that fit. The operator is the only party who can act on it, and
      // until now they were the only party the response did not tell. The
      // remedy is stated conditionally: narrowing the pass to one project
      // helps only where the collection spans several, and the BIM elements
      // of one converted model can exceed the ceiling on their own.
      if (result.truncated) {
        setTruncated((prev) => ({
          ...prev,
          [collection]: { scanned: result.scanned ?? 0, cap: result.cap ?? 0 },
        }));
        addToast({
          type: 'warning',
          title: t('vector_status.reindex_truncated', {
            defaultValue: 'Reindex stopped at the row limit',
          }),
          message: t('vector_status.reindex_truncated_msg', {
            defaultValue:
              '{{collection}}: {{indexed}} of the first {{scanned}} records were indexed, then the pass stopped at its {{cap}}-record limit. The rest of the collection was not reindexed. If it spans several projects, reindexing them one at a time will cover more of it.',
            collection,
            indexed: result.indexed,
            scanned: result.scanned ?? 0,
            cap: result.cap ?? 0,
          }),
        });
        qc.invalidateQueries({ queryKey: ['vector-search-status'] });
        return;
      }
      // A pass that completed clears any limit warning left by an earlier one,
      // so the note under a collection always describes its last reindex.
      setTruncated((prev) => {
        if (!(collection in prev)) return prev;
        const next = { ...prev };
        delete next[collection];
        return next;
      });

      // A 200 means the request completed, not that anything was indexed.
      // index_many() drops a row whose text will not encode and only logs it
      // at debug, so an unreachable or missing encoder returns every row as
      // "skipped" with a perfectly healthy status code. Reporting that in
      // green under "Reindex complete" tells the operator the collection is
      // searchable when nothing was written to it at all, which is the same
      // dishonesty the 503 contract removed from semantic search itself.
      //
      // Partial skipping stays a success on purpose: rows with no indexable
      // text are ordinary and always skipped, so warning on them would cry
      // wolf on every healthy run. Indexing nothing is the case that is
      // never ordinary.
      if (result.indexed === 0 && result.skipped > 0) {
        addToast({
          type: 'warning',
          title: t('vector_status.reindex_nothing', {
            defaultValue: 'Nothing was indexed',
          }),
          message: t('vector_status.reindex_nothing_msg', {
            defaultValue:
              '{{collection}}: all {{skipped}} records were skipped, so this collection is not searchable yet. This usually means the embedding model is unavailable.',
            collection,
            skipped: result.skipped,
          }),
        });
      } else if (result.indexed === 0) {
        addToast({
          type: 'info',
          title: t('vector_status.reindex_empty', {
            defaultValue: 'Nothing to index',
          }),
          message: t('vector_status.reindex_empty_msg', {
            defaultValue: '{{collection}} has no records to index yet.',
            collection,
          }),
        });
      } else {
        addToast({
          type: 'success',
          title: t('vector_status.reindex_done', {
            defaultValue: 'Reindex complete',
          }),
          message: t('vector_status.reindex_summary', {
            defaultValue: '{{collection}}: {{indexed}} indexed, {{skipped}} skipped',
            collection,
            indexed: result.indexed,
            skipped: result.skipped,
          }),
        });
      }
      qc.invalidateQueries({ queryKey: ['vector-search-status'] });
    },
    onError: (err: Error, collection) => {
      addToast({
        type: 'error',
        title: t('vector_status.reindex_failed', {
          defaultValue: 'Reindex failed',
        }),
        message: `${collection}: ${err.message || String(err)}`,
      });
    },
  });

  const totalIndexed = useMemo(() => {
    const collections = statusQuery.data?.collections ?? [];
    let total = 0;
    for (const c of collections) total += c.vectors_count;
    return total;
  }, [statusQuery.data]);

  return (
    <Card className="animate-card-in" style={{ animationDelay: '480ms' }}>
      <CardHeader
        title={t('vector_status.title', { defaultValue: 'Semantic Search Status' })}
        subtitle={t('vector_status.subtitle', {
          defaultValue:
            'Per-collection indexing health for the cross-module vector store',
        })}
      />
      <CardContent>
        {statusQuery.isLoading && (
          <div className="flex items-center gap-2 text-sm text-content-tertiary py-4">
            <Loader2 size={14} className="animate-spin" />
            {t('common.loading', { defaultValue: 'Loading…' })}
          </div>
        )}

        {statusQuery.data && (
          <>
            {/* Engine summary */}
            <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-content-secondary">
              <div className="inline-flex items-center gap-1.5">
                <Database size={12} className="text-content-tertiary" />
                <span className="font-mono">{statusQuery.data.engine || 'unknown'}</span>
              </div>
              {statusQuery.data.model_name && (
                <div className="inline-flex items-center gap-1.5">
                  <span className="text-content-tertiary">model:</span>
                  <span className="font-mono">{statusQuery.data.model_name}</span>
                </div>
              )}
              {statusQuery.data.embedding_dim > 0 && (
                <div className="inline-flex items-center gap-1.5">
                  <span className="text-content-tertiary">dim:</span>
                  <span className="font-mono tabular-nums">
                    {statusQuery.data.embedding_dim}
                  </span>
                </div>
              )}
              <div className="inline-flex items-center gap-1.5">
                <span className="text-content-tertiary">total indexed:</span>
                <span className="font-mono font-semibold tabular-nums">
                  {totalIndexed.toLocaleString(getNumberLocale())}
                </span>
              </div>
              {statusQuery.data.connected ? (
                <div className="inline-flex items-center gap-1 text-emerald-600">
                  <CheckCircle2 size={11} />
                  {t('vector_status.connected', { defaultValue: 'Connected' })}
                </div>
              ) : (
                <div className="inline-flex items-center gap-1 text-amber-600">
                  <AlertCircle size={11} />
                  {t('vector_status.disconnected', { defaultValue: 'Disconnected' })}
                </div>
              )}
            </div>

            {/* Collection table */}
            <div className="space-y-1">
              {(statusQuery.data.collections ?? []).map(
                (col: SearchStatusCollection) => {
                  const isReindexing =
                    reindexMut.isPending && reindexMut.variables === col.collection;
                  // Read once. An element access by a non-literal key is not
                  // narrowed by a truthiness test on the same expression, so
                  // the reads inside the branch would each be optional again.
                  const lastTruncation = truncated[col.collection];
                  return (
                    <div
                      key={col.collection}
                      className="flex items-center justify-between gap-2 px-3 py-2 rounded border border-border-light bg-surface-secondary/40"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-content-primary">
                            {/* `col.label` is the server's English; the
                                collection key is what this app can localise. */}
                            {collectionLabel(t, col.collection)}
                          </span>
                          {col.ready ? (
                            <CheckCircle2
                              size={11}
                              className="text-emerald-500"
                              aria-label={t('vector_status.collection_ready', { defaultValue: 'ready' })}
                            />
                          ) : (
                            <span
                              className="inline-block h-1.5 w-1.5 rounded-full bg-slate-300"
                              aria-label={t('vector_status.collection_empty', { defaultValue: 'empty' })}
                            />
                          )}
                        </div>
                        <div className="text-[11px] text-content-tertiary font-mono">
                          {col.collection}
                          {' • '}
                          <span className="tabular-nums">
                            {col.vectors_count.toLocaleString(getNumberLocale())}
                          </span>{' '}
                          vectors
                        </div>
                        {lastTruncation && (
                          <div className="mt-1 flex items-start gap-1 text-[11px] text-amber-600">
                            <AlertCircle size={11} className="mt-0.5 shrink-0" />
                            <span>
                              {t('vector_status.truncated_note', {
                                defaultValue:
                                  'Last reindex covered {{scanned}} records and stopped at its {{cap}}-record limit. The remainder was not reindexed.',
                                scanned: lastTruncation.scanned.toLocaleString(
                                  getNumberLocale(),
                                ),
                                cap: lastTruncation.cap.toLocaleString(getNumberLocale()),
                              })}
                            </span>
                          </div>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => reindexMut.mutate(col.collection)}
                        disabled={isReindexing}
                      >
                        {isReindexing ? (
                          <>
                            <Loader2 size={12} className="animate-spin me-1" />
                            {t('vector_status.reindexing', {
                              defaultValue: 'Reindexing…',
                            })}
                          </>
                        ) : (
                          <>
                            <RefreshCw size={12} className="me-1" />
                            {t('vector_status.reindex', {
                              defaultValue: 'Reindex',
                            })}
                          </>
                        )}
                      </Button>
                    </div>
                  );
                },
              )}
            </div>

            {/* Purge toggle */}
            <label className="mt-3 flex items-center gap-2 text-[11px] text-content-tertiary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={purgeFirst}
                onChange={(e) => setPurgeFirst(e.target.checked)}
                className="h-3 w-3 accent-oe-blue"
              />
              {t('vector_status.purge_first', {
                defaultValue:
                  'Purge collection before reindex (use after changing the embedding model)',
              })}
            </label>
          </>
        )}

        {statusQuery.isError && (
          <div className="text-sm text-rose-600 py-2">
            {t('vector_status.error', {
              defaultValue: 'Could not load vector store status',
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
