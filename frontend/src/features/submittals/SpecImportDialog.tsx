/**
 * "Build register from spec": pick a specification book, review the submittals it
 * asks for with a confidence each, tick what is right, create drafts. Nothing is
 * created before the last click.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { ConfidenceBadge } from '@/shared/ui/ConfidenceBadge';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchDocuments } from '@/features/documents/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  confirmSpecImport,
  defaultSelection,
  getSpecImport,
  getSpecProposals,
  groupBySection,
  startSpecImport,
} from './specImportApi';

export function SpecImportDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [documentId, setDocumentId] = useState('');
  const [useOcr, setUseOcr] = useState(false);
  const [importId, setImportId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [titles, setTitles] = useState<Record<string, string>>({});

  const { data: docs } = useQuery({
    queryKey: ['spec-import-docs', projectId],
    queryFn: () => fetchDocuments(projectId, { limit: 200 }),
  });
  const books = useMemo(
    () => (docs?.items ?? []).filter((d) => (d.mime_type ?? '').includes('pdf') || d.name.toLowerCase().endsWith('.pdf')),
    [docs],
  );

  const status = useQuery({
    queryKey: ['spec-import', importId],
    queryFn: () => getSpecImport(importId as string),
    enabled: !!importId,
    refetchInterval: (q) => (q.state.data && ['uploaded'].includes(q.state.data.status) ? 1500 : false),
  });
  const parsed = status.data?.status === 'parsed' || status.data?.status === 'confirmed';
  const proposals = useQuery({
    queryKey: ['spec-import-proposals', importId],
    queryFn: () => getSpecProposals(importId as string),
    enabled: !!importId && parsed,
  });

  useEffect(() => {
    if (proposals.data) setSelected(defaultSelection(proposals.data.items));
  }, [proposals.data]);

  const start = useMutation({
    mutationFn: () => startSpecImport(projectId, documentId, useOcr),
    onSuccess: (s) => setImportId(s.id),
    onError: (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const confirm = useMutation({
    mutationFn: () => {
      const edits: Record<string, { title: string }> = {};
      for (const id of selected) if (titles[id] !== undefined) edits[id] = { title: titles[id] };
      return confirmSpecImport(importId as string, [...selected], edits);
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['submittals'] });
      addToast({
        type: 'success',
        title: t('submittals.spec_created', {
          defaultValue: '{{count}} submittals created as drafts',
          count: r.created.length,
        }),
      });
      onClose();
    },
    onError: (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const failed = status.data?.status === 'failed' || status.data?.error_code === 'no_sections_found';
  const groups = groupBySection(proposals.data?.items ?? []);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <WideModal
      open
      onClose={onClose}
      busy={confirm.isPending}
      size="xl"
      title={t('submittals.spec_title', { defaultValue: 'Build register from spec' })}
      subtitle={t('submittals.spec_subtitle', {
        defaultValue: 'The specification is read for the submittals it asks for. You confirm what is created.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={confirm.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {!importId ? (
            <Button variant="primary" onClick={() => start.mutate()} disabled={!documentId || start.isPending}>
              {t('submittals.spec_read', { defaultValue: 'Read specification' })}
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => confirm.mutate()}
              disabled={selected.size === 0 || confirm.isPending || !parsed}
            >
              {t('submittals.spec_create', {
                defaultValue: 'Create {{count}} submittals',
                count: selected.size,
              })}
            </Button>
          )}
        </>
      }
    >
      {!importId && (
        <div className="space-y-3">
          <p className="text-sm text-content-secondary">
            {t('submittals.spec_formats', {
              defaultValue:
                'Pick a specification book (PDF). Sections written as "SECTION 03 30 00 - Title" (MasterFormat), "Leistungsbereich 013" or NBS codes are understood; SUBMITTALS clauses become proposals.',
            })}
          </p>
          <select
            value={documentId}
            onChange={(e) => setDocumentId(e.target.value)}
            aria-label={t('submittals.spec_pick', { defaultValue: 'Specification document' })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm"
          >
            <option value="">{t('submittals.spec_pick', { defaultValue: 'Specification document' })}</option>
            {books.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
          {books.length === 0 && (
            <p className="text-sm text-content-tertiary">
              {t('submittals.spec_no_docs', {
                defaultValue: 'No PDF documents in this project yet. Upload the specification in Documents first.',
              })}
            </p>
          )}
          <label className="inline-flex items-center gap-2 text-sm text-content-secondary">
            <input type="checkbox" checked={useOcr} onChange={(e) => setUseOcr(e.target.checked)} />
            {t('submittals.spec_ocr', { defaultValue: 'The book is a scan: use OCR if there is no text' })}
          </label>
        </div>
      )}

      {importId && !parsed && !failed && (
        <p className="text-sm text-content-secondary" role="status">
          {t('submittals.spec_progress', {
            defaultValue: 'Reading page {{done}} of {{total}}',
            done: status.data?.pages_done ?? 0,
            total: status.data?.pages_total ?? 0,
          })}
        </p>
      )}

      {importId && failed && (
        <p className="text-sm text-semantic-error" role="alert">
          {status.data?.error_code === 'no_sections_found'
            ? t('submittals.spec_no_sections', {
                defaultValue:
                  'No specification sections were found. If the book is a scan, start again with OCR on.',
              })
            : t('submittals.spec_failed', { defaultValue: 'The specification could not be read.' })}
        </p>
      )}

      {importId && parsed && groups.length === 0 && !failed && (
        <p className="text-sm text-content-secondary">
          {t('submittals.spec_empty', { defaultValue: 'No submittal requirements were found in this book.' })}
        </p>
      )}

      {groups.map(([section, items]) => (
        <section key={section} className="mb-4">
          <h3 className="mb-1 text-sm font-semibold text-content-primary">
            {section} <span className="font-normal text-content-secondary">{items[0].section_title}</span>
          </h3>
          <ul className="divide-y divide-border-light rounded-lg border border-border-light">
            {items.map((it) => (
              <li key={it.id} className="flex items-center gap-3 px-3 py-2">
                <input
                  type="checkbox"
                  checked={selected.has(it.id)}
                  disabled={it.submittal_id !== null}
                  onChange={() => toggle(it.id)}
                  aria-label={it.title}
                />
                <input
                  value={titles[it.id] ?? it.title}
                  onChange={(e) => setTitles((p) => ({ ...p, [it.id]: e.target.value }))}
                  aria-label={t('submittals.spec_title_field', { defaultValue: 'Submittal title' })}
                  className="h-8 min-w-0 flex-1 rounded border border-border bg-surface-primary px-2 text-sm"
                />
                <ConfidenceBadge score={it.confidence} showScore />
                {it.duplicate && (
                  <span className="text-xs text-semantic-warning">
                    {t('submittals.spec_duplicate', { defaultValue: 'Already in register' })}
                  </span>
                )}
                <span className="whitespace-nowrap text-xs text-content-tertiary" title={it.source_excerpt}>
                  {t('submittals.spec_page', { defaultValue: 'p. {{page}}', page: it.source_page })}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}

      {(proposals.data?.warnings ?? []).map((w) => (
        <p key={`${w.rule_id}-${w.spec_section}`} className="mb-1 text-xs text-semantic-warning">
          {w.message}
        </p>
      ))}
    </WideModal>
  );
}
