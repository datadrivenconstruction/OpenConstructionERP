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
import { fetchSearchStatus, type SearchStatusCollection } from '@/features/search/api';
import { useToastStore } from '@/stores/useToastStore';

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
}

export default function VectorStatusCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [purgeFirst, setPurgeFirst] = useState(false);

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
                  {totalIndexed.toLocaleString()}
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
                  return (
                    <div
                      key={col.collection}
                      className="flex items-center justify-between gap-2 px-3 py-2 rounded border border-border-light bg-surface-secondary/40"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-content-primary">
                            {col.label}
                          </span>
                          {col.ready ? (
                            <CheckCircle2
                              size={11}
                              className="text-emerald-500"
                              aria-label="ready"
                            />
                          ) : (
                            <span
                              className="inline-block h-1.5 w-1.5 rounded-full bg-slate-300"
                              aria-label="empty"
                            />
                          )}
                        </div>
                        <div className="text-[11px] text-content-tertiary font-mono">
                          {col.collection}
                          {' • '}
                          <span className="tabular-nums">
                            {col.vectors_count.toLocaleString()}
                          </span>{' '}
                          vectors
                        </div>
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
