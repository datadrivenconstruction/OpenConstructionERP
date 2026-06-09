import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Search, FileText, Link2, Loader2 } from 'lucide-react';
import { Button, Input, WideModal, Badge } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import type { CloseoutSlot } from './api';

interface DocumentItem {
  id: string;
  name: string;
  category?: string | null;
  discipline?: string | null;
  cde_state?: string | null;
}

interface BindDocumentModalProps {
  open: boolean;
  projectId: string;
  slot: CloseoutSlot;
  onClose: () => void;
  onBind: (payload: {
    document_id?: string | null;
    external_url?: string | null;
    mark_verified: boolean;
  }) => Promise<void> | void;
  saving?: boolean;
}

/**
 * Bind a closeout slot to a CDE document (searchable list, filtered to match
 * the slot's category / discipline) or to an external URL. A "mark verified"
 * toggle lets a manager bind and sign off in one step.
 */
export default function BindDocumentModal({
  open,
  projectId,
  slot,
  onClose,
  onBind,
  saving = false,
}: BindDocumentModalProps) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [externalUrl, setExternalUrl] = useState('');
  const [markVerified, setMarkVerified] = useState(false);

  // Debounce the search term and push it to the server so large projects do
  // not have to ship every document to the client (server-side filter + cap).
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(handle);
  }, [search]);

  const docsQuery = useQuery({
    queryKey: ['closeout-bind-documents', projectId, debouncedSearch],
    queryFn: () => {
      const params = new URLSearchParams({ project_id: projectId, limit: '50' });
      if (debouncedSearch) params.set('search', debouncedSearch);
      return apiGet<DocumentItem[]>(`/v1/documents/?${params.toString()}`);
    },
    enabled: open && !!projectId,
  });
  const docs = docsQuery.data ?? [];

  const filtered = useMemo(() => {
    // Soft-rank documents whose category / discipline matches the slot. The
    // text filter itself is now applied server-side via the search param.
    const matchesSlot = (d: DocumentItem) => {
      const cat = (d.category || '').toLowerCase();
      const disc = (d.discipline || '').toLowerCase();
      const slotCat = (slot.category || '').toLowerCase();
      const slotDisc = (slot.discipline || '').toLowerCase();
      return (
        (slotCat && cat && (cat.includes(slotCat) || slotCat.includes(cat))) ||
        (slotDisc && disc && disc === slotDisc)
      );
    };
    return [...docs].sort((a, b) => Number(matchesSlot(b)) - Number(matchesSlot(a)));
  }, [docs, slot.category, slot.discipline]);

  const canSubmit = !!selectedDocId || externalUrl.trim().length > 0;

  const handleBind = async () => {
    if (!canSubmit) return;
    await onBind({
      document_id: selectedDocId,
      external_url: selectedDocId ? null : externalUrl.trim() || null,
      mark_verified: markVerified,
    });
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('closeout.bind.title', { defaultValue: 'Bind evidence' })}
      subtitle={slot.title}
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleBind} disabled={!canSubmit || saving} loading={saving}>
            {t('closeout.bind.confirm', { defaultValue: 'Bind' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div>
          <div className="flex items-center gap-2 mb-2 text-sm font-medium text-content-primary">
            <FileText className="h-4 w-4" />
            {t('closeout.bind.from_documents', { defaultValue: 'From project documents' })}
          </div>
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-content-tertiary" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('closeout.bind.search', { defaultValue: 'Search documents' })}
              className="pl-8"
            />
          </div>
          <div className="max-h-64 overflow-y-auto rounded-lg border border-border divide-y divide-border">
            {docsQuery.isLoading ? (
              <div className="flex items-center justify-center gap-2 p-4 text-sm text-content-tertiary">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('common.loading', { defaultValue: 'Loading' })}
              </div>
            ) : filtered.length === 0 ? (
              <div className="p-4 text-sm text-content-tertiary">
                {debouncedSearch
                  ? t('closeout.bind.no_search_results', {
                      defaultValue: 'No documents match "{{query}}"',
                      query: debouncedSearch,
                    })
                  : t('closeout.bind.no_documents', {
                      defaultValue: 'No documents found for this project',
                    })}
              </div>
            ) : (
              filtered.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => {
                    setSelectedDocId(d.id);
                    setExternalUrl('');
                  }}
                  className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-surface-secondary ${
                    selectedDocId === d.id ? 'bg-surface-secondary' : ''
                  }`}
                >
                  <span className="truncate text-content-primary">{d.name}</span>
                  <span className="flex shrink-0 items-center gap-1">
                    {d.discipline ? (
                      <Badge variant="neutral" size="sm">
                        {d.discipline}
                      </Badge>
                    ) : null}
                    {d.cde_state === 'published' ? (
                      <Badge variant="success" size="sm">
                        {t('closeout.bind.published', { defaultValue: 'Published' })}
                      </Badge>
                    ) : null}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center gap-2 mb-2 text-sm font-medium text-content-primary">
            <Link2 className="h-4 w-4" />
            {t('closeout.bind.external_url', { defaultValue: 'Or paste an external URL' })}
          </div>
          <Input
            value={externalUrl}
            onChange={(e) => {
              setExternalUrl(e.target.value);
              if (e.target.value.trim()) setSelectedDocId(null);
            }}
            placeholder="https://"
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-content-secondary">
          <input
            type="checkbox"
            checked={markVerified}
            onChange={(e) => setMarkVerified(e.target.checked)}
            className="h-4 w-4 rounded border-border"
          />
          {t('closeout.bind.mark_verified', {
            defaultValue: 'Mark this evidence as verified (sign-off)',
          })}
        </label>
      </div>
    </WideModal>
  );
}
