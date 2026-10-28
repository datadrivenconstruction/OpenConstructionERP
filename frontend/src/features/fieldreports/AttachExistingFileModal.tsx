// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * AttachExistingFileModal - pick one or more files that are ALREADY in the
 * project and attach them to a field report, instead of uploading a new copy.
 *
 * Field-report attachments are references to project documents (the report
 * stores a list of document ids), so attaching an existing file is just a
 * matter of linking its id. This avoids the duplicate-file problem the field
 * team hits when the only option is to upload again a file that is already in
 * project files.
 *
 * Files already attached to this report are shown as such and cannot be
 * selected again.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { X, Search, FileText, Image as ImageIcon, Check, Loader2, Paperclip } from 'lucide-react';
import { apiGet, type Page } from '@/shared/lib/api';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import { linkReportDocuments } from './api';

interface ProjectDocument {
  id: string;
  name: string;
  category: string | null;
  file_size: number;
  mime_type: string | null;
  drawing_number?: string | null;
  discipline?: string | null;
}

interface AttachExistingFileModalProps {
  reportId: string;
  projectId: string;
  /** Ids already attached to this report, shown as attached and not selectable. */
  attachedIds: string[];
  onClose: () => void;
}

export default function AttachExistingFileModal({
  reportId,
  projectId,
  attachedIds,
  onClose,
}: AttachExistingFileModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const attached = useMemo(() => new Set(attachedIds), [attachedIds]);

  const docsQuery = useQuery({
    queryKey: ['fieldreports', 'project-documents', projectId],
    queryFn: () =>
      apiGet<Page<ProjectDocument>>(`/v1/documents/?project_id=${encodeURIComponent(projectId)}`),
    enabled: !!projectId,
  });
  const docs = docsQuery.data?.items ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return docs;
    return docs.filter((d) => {
      const hay = `${d.name || ''} ${d.category || ''} ${d.drawing_number || ''} ${d.discipline || ''}`;
      return hay.toLowerCase().includes(q);
    });
  }, [docs, search]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const linkMut = useMutation({
    mutationFn: () => linkReportDocuments(reportId, Array.from(selected)),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['fieldreports', 'documents', reportId] });
      addToast({
        type: 'success',
        title: '',
        message: t('fieldreports.attached_existing', {
          defaultValue: '{{count}} file(s) attached',
          count: selected.size,
        }),
      });
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
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-lg p-4"
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
            <Paperclip size={16} className="text-oe-blue" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('fieldreports.attach_existing_title', {
                defaultValue: 'Attach a file from project files',
              })}
            </h2>
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
              placeholder={t('fieldreports.search_project_files', {
                defaultValue: 'Search project files by name or category…',
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
                ? t('fieldreports.no_project_files', {
                    defaultValue: 'No files in this project yet - upload one first.',
                  })
                : t('fieldreports.no_file_match', {
                    defaultValue: 'No files match your search.',
                  })}
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.map((d) => {
                const isAttached = attached.has(d.id);
                const isSelected = selected.has(d.id);
                const isImage = (d.mime_type || '').startsWith('image/');
                return (
                  <li key={d.id}>
                    <button
                      type="button"
                      disabled={isAttached}
                      onClick={() => toggle(d.id)}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded text-start border transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                        isSelected
                          ? 'bg-oe-blue-subtle border-oe-blue/40'
                          : 'border-transparent hover:bg-surface-secondary hover:border-border-light'
                      }`}
                    >
                      <span
                        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                          isSelected
                            ? 'bg-oe-blue border-oe-blue text-white'
                            : 'border-border-strong'
                        }`}
                      >
                        {isSelected && <Check size={11} strokeWidth={3} />}
                      </span>
                      {isImage ? (
                        <ImageIcon size={14} className="shrink-0 text-content-tertiary" />
                      ) : (
                        <FileText size={14} className="shrink-0 text-content-tertiary" />
                      )}
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
                        {d.category && (
                          <span className="text-[10px] uppercase tracking-wider text-content-tertiary">
                            {d.category}
                          </span>
                        )}
                      </div>
                      {isAttached && (
                        <span className="text-[10px] text-content-tertiary shrink-0">
                          {t('fieldreports.already_attached', { defaultValue: 'Attached' })}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {/* A picker cannot page. Gated on the server page, not on the
              search-filtered rows: the sentence is about the register. */}
          {docsQuery.data ? <TruncationNotice page={docsQuery.data} className="pt-2" /> : null}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-5 py-3 border-t border-border-light shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-content-tertiary hover:text-content-primary px-2"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            disabled={selected.size === 0 || linkMut.isPending}
            onClick={() => linkMut.mutate()}
            className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90 disabled:opacity-50 transition-colors"
          >
            {linkMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Paperclip size={14} />}
            {t('fieldreports.attach_selected', {
              defaultValue: 'Attach selected ({{count}})',
              count: selected.size,
            })}
          </button>
        </div>
      </div>
    </div>
  );
}
