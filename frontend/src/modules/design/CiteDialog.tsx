// Design module (ERP side of the design editor link).
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Button, WideModal } from '@/shared/ui';
import { fetchDocuments } from '@/features/documents/api';
import { fieldLabel, tr } from './BriefFields';

export interface CiteDialogProps {
  projectId: string;
  /** The value being cited, as a pointer into the brief; null closes the dialog. */
  pointer: string | null;
  onClose: () => void;
  onCite: (pointer: string, source: { document_id: string; page?: number; quote?: string }) => void;
}

/** Pick a project document, an optional page and quote, and record it as the source of one value. */
export function CiteDialog({ projectId, pointer, onClose, onCite }: CiteDialogProps) {
  const { t } = useTranslation();
  const docs = useQuery({
    queryKey: ['design-brief-documents', projectId],
    queryFn: () => fetchDocuments(projectId, { limit: 100 }),
    enabled: !!pointer,
  });
  const [documentId, setDocumentId] = useState('');
  const [page, setPage] = useState('');
  const [quote, setQuote] = useState('');
  // Every opening starts empty, whether the last one ended with Add, Cancel, Escape or a click outside.
  useEffect(() => {
    setDocumentId('');
    setPage('');
    setQuote('');
  }, [pointer]);
  const items = docs.data?.items ?? [];
  const pageNumber = page.trim() === '' ? undefined : Number(page);
  const pageBad = pageNumber !== undefined && (!Number.isInteger(pageNumber) || pageNumber < 1);

  const submit = () => {
    if (!pointer || !documentId || pageBad) return;
    onCite(pointer, { document_id: documentId, page: pageNumber, quote });
    setDocumentId('');
    setPage('');
    setQuote('');
    onClose();
  };

  return (
    <WideModal
      open={pointer !== null}
      onClose={onClose}
      size="md"
      title={tr(t, 'design.cite.title')}
      subtitle={pointer ? fieldLabel(t, pointer) : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{tr(t, 'design.cite.cancel')}</Button>
          <Button onClick={submit} disabled={!documentId || pageBad}>{tr(t, 'design.cite.add')}</Button>
        </>
      }
    >
      <div className="space-y-4">
        <label className="flex flex-col gap-1 text-sm font-medium">
          {tr(t, 'design.cite.document')}
          <select
            className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm"
            value={documentId}
            onChange={(e) => setDocumentId(e.target.value)}
          >
            <option value="">{tr(t, 'design.cite.choose')}</option>
            {items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
        {docs.isSuccess && items.length === 0 && (
          <p className="text-sm text-content-tertiary">{tr(t, 'design.cite.no_documents')}</p>
        )}
        {docs.isError && <p role="alert" className="text-sm text-semantic-error">{tr(t, 'design.cite.load_failed')}</p>}
        <label className="flex flex-col gap-1 text-sm font-medium">
          {tr(t, 'design.cite.page')}
          <input
            className="h-9 w-28 rounded-lg border border-border bg-surface-primary px-3 text-sm"
            inputMode="numeric"
            value={page}
            aria-invalid={pageBad}
            onChange={(e) => setPage(e.target.value)}
          />
          {pageBad && <span role="alert" className="text-xs text-semantic-error">{tr(t, 'design.error.not_an_integer')}</span>}
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {tr(t, 'design.cite.quote')}
          <textarea
            className="min-h-20 rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
            maxLength={1000}
            value={quote}
            onChange={(e) => setQuote(e.target.value)}
          />
        </label>
      </div>
    </WideModal>
  );
}
