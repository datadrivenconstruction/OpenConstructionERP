/**
 * LinkDocumentToBIMModal — pick an existing document and link it to one
 * or more BIM elements without leaving the viewer.
 *
 * Lists every document in the active project, lets the user search by
 * name / category / drawing-number, click a row → POST to /documents/bim-links/
 * for every (document, element) pair → invalidate the bim-elements query
 * → done.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { X, Search, FileText, Link2, Loader2 } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { createDocumentBIMLink } from './api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import { useToastStore } from '@/stores/useToastStore';

interface DocumentItem {
  id: string;
  name: string;
  category: string | null;
  file_size: number;
  mime_type: string | null;
  drawing_number?: string | null;
  discipline?: string | null;
  created_at: string;
}

interface LinkDocumentToBIMModalProps {
  projectId: string;
  elements: BIMElementData[];
  onClose: () => void;
  onLinked?: () => void;
}

export default function LinkDocumentToBIMModal({
  projectId,
  elements,
  onClose,
  onLinked,
}: LinkDocumentToBIMModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');

  // Reset transient UI state whenever the modal is opened with a new
  // element selection.  Mirrors the pattern in AddToBOQModal.
  useEffect(() => {
    setSearch('');
  }, [elements]);

  const docsQuery = useQuery({
    queryKey: ['documents-for-bim-link', projectId],
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
        (d.name || '') +
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
    mutationFn: async (documentId: string) => {
      // Create one link per BIM element
      let created = 0;
      for (const el of elements) {
        try {
          await createDocumentBIMLink({
            document_id: documentId,
            bim_element_id: el.id,
            link_type: 'manual',
          });
          created++;
        } catch (e: unknown) {
          // 409 / "already linked" is fine in bulk mode — keep going
          const err = e as { message?: string };
          if (!err?.message?.toLowerCase().includes('already')) {
            // Re-throw other errors so the toast surfaces them
            throw e;
          }
        }
      }
      return created;
    },
    onSuccess: (count) => {
      addToast({
        type: 'success',
        title: t('bim.doc_linked_title', { defaultValue: 'Document linked' }),
        message: t('bim.doc_linked_msg', {
          defaultValue: 'Linked to {{count}} BIM element(s)',
          count,
        }),
      });
      qc.invalidateQueries({ queryKey: ['bim-elements'] });
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
              {t('bim.link_doc_title', { defaultValue: 'Link a document' })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {elements.length === 1
                ? '→ ' + (elements[0]!.name || elements[0]!.element_type)
                : t('bim.link_doc_bulk', {
                    defaultValue: '→ {{count}} elements',
                    count: elements.length,
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
              placeholder={t('bim.search_documents', {
                defaultValue: 'Search by name, category, drawing number, discipline…',
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
                ? t('bim.no_docs', {
                    defaultValue: 'No documents in this project yet — upload one first',
                  })
                : t('bim.no_doc_match', { defaultValue: 'No documents match your search' })}
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => linkMut.mutate(d.id)}
                    disabled={linkMut.isPending}
                    className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded text-start hover:bg-violet-50 dark:hover:bg-violet-950/30 border border-transparent hover:border-violet-300/50 disabled:opacity-50 transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-content-primary truncate">
                          {d.name}
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
