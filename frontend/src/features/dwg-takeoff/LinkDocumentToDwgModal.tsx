/**
 * LinkDocumentToDwgModal — pick an existing document and link it to one
 * or more DWG entities without leaving the viewer.
 *
 * Mirrors LinkDocumentToBIMModal. Lists every document in the active
 * project, lets the user search by name / category / drawing-number,
 * click a row → PATCH /documents/{id} to append the DWG link to its
 * metadata (merges with existing metadata so we don't clobber other
 * consumers). Documents don't have a dedicated DWG-link table yet, so
 * the metadata-merge pattern keeps the footprint small.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { X, Search, FileText, Link2, Loader2 } from 'lucide-react';
import { apiGet, apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

interface DocumentItem {
  id: string;
  name?: string | null;
  filename?: string | null;
  category: string | null;
  file_size?: number | null;
  size_bytes?: number | null;
  mime_type: string | null;
  drawing_number?: string | null;
  discipline?: string | null;
  created_at: string;
  metadata?: Record<string, unknown> | null;
}

interface LinkDocumentToDwgModalProps {
  projectId: string;
  entityIds: string[];
  drawingId: string;
  entityLabel?: string;
  onClose: () => void;
  onLinked?: () => void;
}

export default function LinkDocumentToDwgModal({
  projectId,
  entityIds,
  drawingId,
  entityLabel,
  onClose,
  onLinked,
}: LinkDocumentToDwgModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');

  const docsQuery = useQuery({
    queryKey: ['documents-for-dwg-link', projectId],
    queryFn: () =>
      apiGet<DocumentItem[]>(
        `/v1/documents/?project_id=${encodeURIComponent(projectId)}`,
      ),
    enabled: !!projectId,
  });
  const docs = docsQuery.data ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return docs;
    return docs.filter((d) => {
      const hay =
        (d.name || d.filename || '') +
        ' ' +
        (d.category || '') +
        ' ' +
        (d.drawing_number || '') +
        ' ' +
        (d.discipline || '');
      return hay.toLowerCase().includes(q);
    });
  }, [docs, search]);

  const linkMut = useMutation({
    mutationFn: async (doc: DocumentItem) => {
      // Merge the DWG link into the doc's existing metadata so other
      // consumers (captions, tags, etc.) aren't clobbered.
      const existing = (doc.metadata ?? {}) as Record<string, unknown>;
      const existingIds = Array.isArray(existing['dwg_entity_ids'])
        ? (existing['dwg_entity_ids'] as string[])
        : [];
      const mergedIds = Array.from(new Set([...existingIds, ...entityIds]));
      const nextMetadata: Record<string, unknown> = {
        ...existing,
        dwg_drawing_id: drawingId,
        dwg_entity_ids: mergedIds,
      };
      await apiPatch<DocumentItem, { metadata: Record<string, unknown> }>(
        `/v1/documents/${encodeURIComponent(doc.id)}`,
        { metadata: nextMetadata },
      );
      return entityIds.length;
    },
    onSuccess: (count) => {
      addToast({
        type: 'success',
        title: t('dwg_takeoff.doc_linked_title', { defaultValue: 'Document linked' }),
        message: t('dwg_takeoff.doc_linked_msg', {
          defaultValue: 'Linked to {{count}} DWG entity/entities',
          count,
        }),
      });
      qc.invalidateQueries({ queryKey: ['documents'] });
      qc.invalidateQueries({ queryKey: ['documents-for-dwg-link', projectId] });
      onLinked?.();
      onClose();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message || String(err),
      });
    },
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="bg-surface-primary rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col border border-border-light"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-light shrink-0">
          <div className="flex items-center gap-2">
            <FileText size={16} className="text-violet-600" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('dwg_takeoff.link_doc_title', { defaultValue: 'Link a document' })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {entityIds.length === 1
                ? '→ ' + (entityLabel || t('dwg_takeoff.entity', { defaultValue: 'Entity' }))
                : t('dwg_takeoff.link_doc_bulk', {
                    defaultValue: '→ {{count}} entities',
                    count: entityIds.length,
                  })}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b border-border-light shrink-0">
          <div className="relative">
            <Search
              size={13}
              className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-quaternary pointer-events-none"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('dwg_takeoff.search_documents', {
                defaultValue: 'Search by name, category, drawing number…',
              })}
              autoFocus
              className="w-full ps-8 pe-3 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-3">
          {docsQuery.isLoading ? (
            <div className="flex items-center justify-center py-8 text-content-tertiary">
              <Loader2 size={16} className="animate-spin mr-2" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-8 text-[11px] text-content-tertiary italic">
              {docs.length === 0
                ? t('dwg_takeoff.no_docs', {
                    defaultValue: 'No documents in this project yet — upload one first',
                  })
                : t('dwg_takeoff.no_doc_match', {
                    defaultValue: 'No documents match your search',
                  })}
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => linkMut.mutate(d)}
                    disabled={linkMut.isPending}
                    className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded text-start hover:bg-violet-50 dark:hover:bg-violet-950/30 border border-transparent hover:border-violet-300/50 disabled:opacity-50 transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-content-primary truncate">
                          {d.name || d.filename || d.id}
                        </span>
                        {d.drawing_number && (
                          <span className="text-[10px] font-mono text-content-tertiary">
                            {d.drawing_number}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-content-tertiary">
                        {d.category && (
                          <span className="uppercase tracking-wider">{d.category}</span>
                        )}
                        {d.discipline && <span>{d.discipline}</span>}
                      </div>
                    </div>
                    <Link2 size={12} className="text-violet-600 shrink-0" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end px-5 py-3 border-t border-border-light shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-content-tertiary hover:text-content-primary px-2"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
        </div>
      </div>
    </div>
  );
}
