// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The paper trail of a package in one card: the file the bill was imported
 * from and whether the bill still matches it, the award file (GAEB X86), the
 * documents that go out with the package, and what each firm sent back.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, Download, FileText, Paperclip, X } from 'lucide-react';

import { Button } from '@/shared/ui';
import { formatDateValue } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  AwardExportError,
  attachPackageDocuments,
  detachPackageDocument,
  downloadAwardX86,
  downloadBidFile,
  fetchBillSource,
  listBidFiles,
  listPackageDocuments,
  searchProjectDocuments,
  type BillDifference,
} from './awardExchange';
import { bidInvitationsQueryKey } from './BidLinkCell';

interface ExchangePackage {
  id: string;
  name: string;
  project_id: string;
  status: string;
  boq_id?: string | null;
}

function shortHash(hash: string): string {
  return hash ? `${hash.slice(0, 12)}…` : '';
}

export function ExchangePanel({ pkg }: { pkg: ExchangePackage }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [picking, setPicking] = useState(false);
  const [search, setSearch] = useState('');
  const [refusal, setRefusal] = useState<{ code: string; differences: BillDifference[]; ordinals: string[] } | null>(null);

  const sourceQ = useQuery({
    queryKey: ['tendering-bill-source', pkg.id],
    queryFn: () => fetchBillSource(pkg.id),
    enabled: Boolean(pkg.boq_id),
    staleTime: 15_000,
  });
  const docsQ = useQuery({ queryKey: ['tendering-package-documents', pkg.id], queryFn: () => listPackageDocuments(pkg.id) });
  const filesQ = useQuery({ queryKey: ['tendering-bid-files', pkg.id], queryFn: () => listBidFiles(pkg.id) });
  const optionsQ = useQuery({
    queryKey: ['tendering-document-options', pkg.project_id, search],
    queryFn: () => searchProjectDocuments(pkg.project_id, search),
    enabled: picking,
    staleTime: 30_000,
  });

  const refreshDocs = () => {
    void queryClient.invalidateQueries({ queryKey: ['tendering-package-documents', pkg.id] });
  };
  const attach = useMutation({
    mutationFn: (documentId: string) => attachPackageDocuments(pkg.id, [documentId]),
    onSuccess: refreshDocs,
    onError: () => addToast({ type: 'error', title: t('tendering.exchange.attach_failed', { defaultValue: 'Could not add the document' }) }),
  });
  const detach = useMutation({
    mutationFn: (linkId: string) => detachPackageDocument(pkg.id, linkId),
    onSuccess: refreshDocs,
  });

  const onAward = async () => {
    setRefusal(null);
    try {
      await downloadAwardX86(pkg.id, pkg.name);
      void queryClient.invalidateQueries({ queryKey: bidInvitationsQueryKey(pkg.id) });
    } catch (err) {
      if (err instanceof AwardExportError) setRefusal({ code: err.code, differences: err.differences, ordinals: err.ordinals });
      else addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
    }
  };

  const state = sourceQ.data;
  const source = state?.source ?? null;
  const differences = refusal?.differences.length ? refusal.differences : (state?.differences ?? []);
  // The award file is GAEB; a bill imported from another format is answered in that format, not here.
  const showX86 = !source || source.format_id.toLowerCase().includes('gaeb');
  const attached = new Set((docsQ.data ?? []).map((d) => d.document_id));
  const fieldLabel = (field: string) =>
    t(`tendering.exchange.field_${field}`, { defaultValue: field });

  const refusalText = (code: string): string => {
    switch (code) {
      case 'bill_changed_since_import':
        return t('tendering.exchange.refused_changed', { defaultValue: 'The bill differs from the imported file, so no award file can be written.' });
      case 'no_awarded_bid':
        return t('tendering.exchange.refused_no_award', { defaultValue: 'Award a bid first; the award file carries its prices.' });
      case 'x86_unpriced_lines':
        return t('tendering.exchange.refused_unpriced', { defaultValue: 'The awarded bid leaves lines unpriced: {{items}}', items: (refusal?.ordinals ?? []).slice(0, 15).join(', ') });
      default:
        return t('tendering.export_failed', { defaultValue: 'Export failed' });
    }
  };

  return (
    <section className="mt-4 space-y-4 rounded-xl border border-border-light bg-surface-primary p-4" data-testid="exchange-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('tendering.exchange.title', { defaultValue: 'Bill file and award' })}
          </h3>
          {source ? (
            <p className="text-xs text-content-secondary" data-testid="exchange-source">
              {t('tendering.exchange.source', {
                defaultValue: 'Imported from {{file}}, lines: {{lines}}, SHA-256 {{hash}}',
                file: source.file_name,
                lines: source.line_count,
                hash: shortHash(source.file_sha256),
              })}
            </p>
          ) : (
            <p className="text-xs text-content-tertiary">
              {t('tendering.exchange.no_source', { defaultValue: 'The bill was not imported from a file; the award file is written from the bill as it stands.' })}
            </p>
          )}
          {source && state && (
            state.changed ? (
              <p className="inline-flex items-center gap-1 text-xs font-medium text-semantic-warning" data-testid="exchange-changed">
                <AlertTriangle size={13} aria-hidden />
                {t('tendering.exchange.changed', { defaultValue: 'Bill changed since the import. Differences: {{count}}', count: state.differences.length })}
              </p>
            ) : (
              <p className="inline-flex items-center gap-1 text-xs text-semantic-success" data-testid="exchange-unchanged">
                <CheckCircle2 size={13} aria-hidden />
                {t('tendering.exchange.unchanged', { defaultValue: 'Bill unchanged since the import' })}
              </p>
            )
          )}
        </div>
        {showX86 && (
          <Button variant="secondary" size="sm" disabled={!pkg.boq_id} onClick={() => void onAward()} data-testid="exchange-x86">
            <Download size={14} aria-hidden />
            {t('tendering.exchange.export_x86', { defaultValue: 'Award file (GAEB X86)' })}
          </Button>
        )}
      </div>

      {refusal && (
        <p className="rounded-lg bg-semantic-warning-bg p-2 text-xs text-content-primary" role="alert" data-testid="exchange-refusal">
          {refusalText(refusal.code)}
        </p>
      )}

      {differences.length > 0 && (
        <table className="oe-table w-full text-xs" data-testid="exchange-differences">
          <thead>
            <tr>
              <th className="text-left">{t('tendering.exchange.col_item', { defaultValue: 'Item' })}</th>
              <th className="text-left">{t('tendering.exchange.col_what', { defaultValue: 'What changed' })}</th>
              <th className="text-left">{t('tendering.exchange.col_was', { defaultValue: 'In the file' })}</th>
              <th className="text-left">{t('tendering.exchange.col_now', { defaultValue: 'On the bill' })}</th>
            </tr>
          </thead>
          <tbody>
            {differences.slice(0, 20).map((d, index) => (
              <tr key={`${d.ordinal}-${d.field}-${index}`}>
                <td className="font-mono">{d.ordinal}</td>
                <td>{fieldLabel(d.field)}</td>
                <td>{d.was}</td>
                <td>{d.now}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div>
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('tendering.exchange.documents', { defaultValue: 'Documents sent to bidders' })}
          </h4>
          <Button variant="ghost" size="sm" onClick={() => setPicking((p) => !p)} data-testid="exchange-add-document">
            <Paperclip size={14} aria-hidden />
            {t('tendering.exchange.add_document', { defaultValue: 'Add from project documents' })}
          </Button>
        </div>
        {(docsQ.data ?? []).length === 0 && !picking && (
          <p className="text-xs text-content-tertiary">
            {t('tendering.exchange.no_documents', { defaultValue: 'No documents yet. Bidders see the drawings and conditions you add here on their link.' })}
          </p>
        )}
        <ul className="mt-1 space-y-1 text-sm" data-testid="exchange-documents">
          {(docsQ.data ?? []).map((doc) => (
            <li key={doc.id} className="flex items-center justify-between gap-2">
              <span className="inline-flex min-w-0 items-center gap-2">
                <FileText size={14} className="shrink-0 text-content-tertiary" aria-hidden />
                <span className="truncate">{doc.name}</span>
              </span>
              <button
                type="button"
                className="rounded p-1 text-content-tertiary hover:bg-surface-secondary"
                aria-label={t('tendering.exchange.remove_document', { defaultValue: 'Stop sending this document' })}
                onClick={() => detach.mutate(doc.id)}
              >
                <X size={14} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
        {picking && (
          <div className="mt-2 space-y-1 rounded-lg border border-border-light p-2">
            <input
              className="oe-input oe-input-sm w-full"
              value={search}
              placeholder={t('tendering.exchange.search_documents', { defaultValue: 'Search project documents' })}
              onChange={(e) => setSearch(e.target.value)}
            />
            <ul className="max-h-48 space-y-0.5 overflow-y-auto text-sm" data-testid="exchange-document-options">
              {(optionsQ.data ?? [])
                .filter((d) => !attached.has(d.id))
                .map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      className="w-full truncate rounded px-2 py-1 text-left hover:bg-surface-secondary"
                      onClick={() => attach.mutate(d.id)}
                    >
                      {d.name}
                    </button>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </div>

      {(filesQ.data ?? []).length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('tendering.exchange.bid_files', { defaultValue: 'Files from bidders' })}
          </h4>
          <ul className="mt-1 space-y-1 text-sm" data-testid="exchange-bid-files">
            {(filesQ.data ?? []).map((f) => (
              <li key={f.id} className="flex flex-wrap items-center gap-x-3">
                <span className="font-medium text-content-primary">{f.company_name}</span>
                <button
                  type="button"
                  className="text-oe-blue hover:underline"
                  onClick={() => void downloadBidFile(pkg.id, f).catch(() => addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) }))}
                >
                  {f.file_name}
                </button>
                <span className="text-xs text-content-tertiary">{t(`bid_portal.files.kind_${f.kind}`, { defaultValue: f.kind })}</span>
                <span className="text-xs text-content-tertiary">{formatDateValue(f.uploaded_at, { dateStyle: 'medium', timeStyle: 'short' })}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
