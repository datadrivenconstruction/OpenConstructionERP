// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Handover documents / digital closeout package (item #25).
 *
 * Rendered per-Handover inside PropertyDevPage's HandoverPlotRow, between
 * the certificate-generation buttons and the SnagsBlock. Owns the full
 * closeout-document clickflow:
 *
 *   - Lazy-load the handover-doc bundle on expand (avoids fan-out on long
 *     handover lists).
 *   - Traffic-light compliance badge: Ready (all required docs delivered)
 *     vs N required document(s) missing.
 *   - Add / edit / delete document entries (doc-type, title, file URL,
 *     required flag) via modals.
 *   - Toggle delivered status inline (stamps delivered_at server-side).
 *   - Export Package: authenticated ZIP download of certificates + every
 *     delivered local document + snag photos. Primary action once the
 *     bundle is ready.
 *
 * All copy goes through i18n with inline English defaults so it renders
 * before the locale sweep lands the translations.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Trash2,
  Pencil,
  Check,
  ChevronDown,
  ChevronRight,
  FileCheck2,
  Download,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react';

import { Button, Badge, ConfirmDialog } from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';

import {
  getHandoverBundle,
  createHandoverDoc,
  updateHandoverDoc,
  deleteHandoverDoc,
  exportHandoverPackage,
  type Handover,
  type HandoverDoc,
  type HandoverDocType,
} from './api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** Canonical doc-type order — drives the dropdown + table grouping. */
const DOC_TYPES: HandoverDocType[] = [
  'warranty',
  'manual',
  'key_receipt',
  'hs_file',
  'epc',
  'nhbc',
  'inspection_cert',
  'certificate_completion',
  'insurance',
  'other',
];

function docTypeLabel(t: ReturnType<typeof useTranslation>['t'], type: string) {
  const defaults: Record<string, string> = {
    warranty: 'Warranty',
    manual: 'Manual / instructions',
    key_receipt: 'Key receipt',
    hs_file: 'Health & Safety file',
    epc: 'Energy performance (EPC)',
    nhbc: 'NHBC certificate',
    inspection_cert: 'Inspection certificate',
    certificate_completion: 'Certificate of completion',
    insurance: 'Insurance',
    other: 'Other',
  };
  return t(`propdev.doc_type.${type}`, { defaultValue: defaults[type] ?? type });
}

interface DocDraft {
  doc_type: HandoverDocType;
  title: string;
  file_url: string;
  is_required: boolean;
  is_delivered: boolean;
}

const EMPTY_DRAFT: DocDraft = {
  doc_type: 'warranty',
  title: '',
  file_url: '',
  is_required: false,
  is_delivered: false,
};

export function HandoverDocumentsSection({
  handover,
}: {
  handover: Handover;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [expanded, setExpanded] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [editDoc, setEditDoc] = useState<HandoverDoc | null>(null);
  const [draft, setDraft] = useState<DocDraft>(EMPTY_DRAFT);
  const [exporting, setExporting] = useState(false);
  const [statusFilter, setStatusFilter] = useState<
    'all' | 'delivered' | 'pending'
  >('all');
  const { confirm, ...confirmProps } = useConfirm();

  const bundleQ = useQuery({
    queryKey: ['propdev', 'handover-docs', handover.id],
    queryFn: () => getHandoverBundle(handover.id),
    enabled: expanded,
    staleTime: 30_000,
  });
  const bundle = bundleQ.data;
  const docs = bundle?.docs ?? [];
  const visibleDocs = docs.filter((d) =>
    statusFilter === 'all'
      ? true
      : statusFilter === 'delivered'
        ? d.is_delivered
        : !d.is_delivered,
  );

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ['propdev', 'handover-docs', handover.id] });

  const createMu = useMutation({
    mutationFn: () =>
      createHandoverDoc({
        handover_id: handover.id,
        doc_type: draft.doc_type,
        title: draft.title.trim() || undefined,
        file_url: draft.file_url.trim() || null,
        is_required: draft.is_required,
        is_delivered: draft.is_delivered,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.handover_doc_added', { defaultValue: 'Document added' }),
      });
      invalidate();
      setAddOpen(false);
      setDraft(EMPTY_DRAFT);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const editMu = useMutation({
    mutationFn: () => {
      if (!editDoc) throw new Error('no doc');
      return updateHandoverDoc(editDoc.id, {
        title: draft.title.trim(),
        file_url: draft.file_url.trim() || null,
        is_required: draft.is_required,
        is_delivered: draft.is_delivered,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.handover_doc_updated', { defaultValue: 'Document updated' }),
      });
      invalidate();
      setEditDoc(null);
      setDraft(EMPTY_DRAFT);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const toggleDeliveredMu = useMutation({
    mutationFn: ({ id, delivered }: { id: string; delivered: boolean }) =>
      updateHandoverDoc(id, { is_delivered: delivered }),
    onSuccess: () => invalidate(),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMu = useMutation({
    mutationFn: (id: string) => deleteHandoverDoc(id),
    onSuccess: () => {
      invalidate();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  async function handleExport() {
    setExporting(true);
    try {
      const { blob, filename } = await exportHandoverPackage(handover.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      addToast({
        type: 'success',
        title: t('propdev.handover_package_exported', {
          defaultValue: 'Closeout package downloaded',
        }),
      });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setExporting(false);
    }
  }

  function openEdit(doc: HandoverDoc) {
    setDraft({
      doc_type: doc.doc_type,
      title: doc.title,
      file_url: doc.file_url ?? '',
      is_required: doc.is_required,
      is_delivered: doc.is_delivered,
    });
    setEditDoc(doc);
  }

  const ready = bundle?.ready_for_handover ?? false;
  const requiredCount = bundle?.required_count ?? 0;
  const missingCount = bundle?.missing_required.length ?? 0;

  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded"
          aria-expanded={expanded}
          data-testid={`handover-docs-toggle-${handover.id}`}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <FileCheck2 size={12} />
          {t('propdev.handover_package', { defaultValue: 'Closeout package' })}
          {expanded && bundleQ.isLoading ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            bundle && (
              <span className="text-content-tertiary">
                ({bundle.delivered_count}/{docs.length}
                {t('propdev.delivered_short', { defaultValue: ' delivered' })})
              </span>
            )
          )}
        </button>
        <Button
          size="sm"
          variant="ghost"
          icon={<Plus size={12} />}
          onClick={() => {
            setExpanded(true);
            setDraft(EMPTY_DRAFT);
            setAddOpen(true);
          }}
          data-testid={`add-handover-doc-${handover.id}`}
        >
          {t('propdev.add_document', { defaultValue: 'Add document' })}
        </Button>
      </div>

      {expanded && (
        <>
          {bundleQ.isLoading ? (
            <p className="mt-2 text-xs text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </p>
          ) : bundleQ.isError ? (
            <p className="mt-2 text-xs text-error">
              {getErrorMessage(bundleQ.error)}
            </p>
          ) : (
            <>
              {/* Compliance traffic-light + export */}
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                {requiredCount === 0 ? (
                  <Badge variant="neutral">
                    {t('propdev.handover_package.no_required', {
                      defaultValue: 'No required documents',
                    })}
                  </Badge>
                ) : ready ? (
                  <Badge variant="success" dot>
                    <CheckCircle2 size={11} className="mr-1 inline" />
                    {t('propdev.handover_package.ready', {
                      defaultValue: 'Ready - all required documents delivered',
                    })}
                  </Badge>
                ) : (
                  <Badge variant="warning" dot>
                    <AlertTriangle size={11} className="mr-1 inline" />
                    {t('propdev.missing_docs', {
                      defaultValue: '{{count}} required document(s) missing',
                      count: missingCount,
                    })}
                  </Badge>
                )}
                <Button
                  size="sm"
                  variant={ready ? 'primary' : 'secondary'}
                  icon={
                    exporting ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Download size={12} />
                    )
                  }
                  onClick={handleExport}
                  disabled={exporting}
                  data-testid={`export-handover-${handover.id}`}
                >
                  {t('propdev.export_package', {
                    defaultValue: 'Export package (ZIP)',
                  })}
                </Button>
              </div>

              {docs.length === 0 ? (
                <p className="mt-2 text-xs text-content-tertiary italic">
                  {t('propdev.no_handover_docs', {
                    defaultValue:
                      'No closeout documents recorded yet. Add the warranty, manuals, key receipt and any required certificates.',
                  })}
                </p>
              ) : (
                <>
                  <div className="mt-2 flex items-center gap-1.5 text-xs">
                    <span className="text-content-tertiary">
                      {t('propdev.filter_by_status', { defaultValue: 'Filter:' })}
                    </span>
                    <select
                      value={statusFilter}
                      onChange={(e) =>
                        setStatusFilter(
                          e.target.value as 'all' | 'delivered' | 'pending',
                        )
                      }
                      className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                      aria-label={t('propdev.filter_by_status', {
                        defaultValue: 'Filter by delivery status',
                      })}
                      data-testid={`handover-docs-filter-${handover.id}`}
                    >
                      <option value="all">
                        {t('propdev.filter_all', { defaultValue: 'All' })}
                      </option>
                      <option value="delivered">
                        {t('propdev.delivered', { defaultValue: 'Delivered' })}
                      </option>
                      <option value="pending">
                        {t('propdev.pending', { defaultValue: 'Pending' })}
                      </option>
                    </select>
                  </div>
                  {visibleDocs.length === 0 ? (
                    <p className="mt-2 text-xs text-content-tertiary italic">
                      {t('propdev.no_docs_match_filter', {
                        defaultValue: 'No documents match this filter.',
                      })}
                    </p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {visibleDocs.map((doc) => (
                    <li
                      key={doc.id}
                      className="rounded-md border border-border-light bg-surface-secondary/40 px-3 py-2 text-xs"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <label className="inline-flex cursor-pointer items-center gap-1.5">
                          <input
                            type="checkbox"
                            checked={doc.is_delivered}
                            onChange={(e) =>
                              toggleDeliveredMu.mutate({
                                id: doc.id,
                                delivered: e.target.checked,
                              })
                            }
                            disabled={toggleDeliveredMu.isPending}
                            className="h-3.5 w-3.5 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                            aria-label={t('propdev.mark_delivered', {
                              defaultValue: 'Mark delivered',
                            })}
                          />
                          {doc.is_delivered ? (
                            <Badge variant="success" dot>
                              {t('propdev.delivered', { defaultValue: 'Delivered' })}
                            </Badge>
                          ) : (
                            <Badge variant="neutral" dot>
                              {t('propdev.pending', { defaultValue: 'Pending' })}
                            </Badge>
                          )}
                        </label>
                        <span className="font-medium text-content-primary">
                          {docTypeLabel(t, doc.doc_type)}
                        </span>
                        {doc.is_required && (
                          <Badge variant="blue">
                            {t('propdev.required', { defaultValue: 'Required' })}
                          </Badge>
                        )}
                        {doc.delivered_at && (
                          <span className="text-content-tertiary">
                            · <DateDisplay value={doc.delivered_at} />
                          </span>
                        )}
                      </div>
                      {doc.title && (
                        <p className="mt-1 text-content-secondary">{doc.title}</p>
                      )}
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        {doc.file_url &&
                          /^https?:\/\//i.test(doc.file_url) && (
                            <a
                              href={doc.file_url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-0.5 text-oe-blue hover:underline"
                            >
                              <ExternalLink size={10} />
                              {t('propdev.open_file', { defaultValue: 'Open file' })}
                            </a>
                          )}
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Pencil size={11} />}
                          onClick={() => openEdit(doc)}
                        >
                          {t('common.edit', { defaultValue: 'Edit' })}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={11} />}
                          onClick={async () => {
                            const ok = await confirm({
                              title: t('propdev.delete_doc_title', {
                                defaultValue: 'Remove document?',
                              }),
                              message: t('propdev.confirm_delete_doc', {
                                defaultValue:
                                  'Remove this closeout document from the package? This cannot be undone.',
                              }),
                              confirmLabel: t('common.delete', {
                                defaultValue: 'Delete',
                              }),
                              variant: 'danger',
                            });
                            if (!ok) return;
                            deleteMu.mutate(doc.id);
                          }}
                          disabled={deleteMu.isPending}
                        >
                          {t('common.delete', { defaultValue: 'Delete' })}
                        </Button>
                      </div>
                    </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}

      {(addOpen || editDoc) && (
        <WideModal
          open
          onClose={() => {
            setAddOpen(false);
            setEditDoc(null);
            setDraft(EMPTY_DRAFT);
          }}
          title={
            editDoc
              ? t('propdev.edit_document', { defaultValue: 'Edit document' })
              : t('propdev.add_document', { defaultValue: 'Add document' })
          }
          size="md"
          busy={createMu.isPending || editMu.isPending}
          footer={
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  setAddOpen(false);
                  setEditDoc(null);
                  setDraft(EMPTY_DRAFT);
                }}
                disabled={createMu.isPending || editMu.isPending}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => (editDoc ? editMu.mutate() : createMu.mutate())}
                loading={createMu.isPending || editMu.isPending}
                icon={editDoc ? <Check size={14} /> : <Plus size={14} />}
              >
                {editDoc
                  ? t('common.save', { defaultValue: 'Save' })
                  : t('propdev.add_document', { defaultValue: 'Add document' })}
              </Button>
            </>
          }
        >
          <WideModalSection columns={2}>
            <WideModalField
              label={t('propdev.doc_type_label', { defaultValue: 'Document type' })}
            >
              <select
                value={draft.doc_type}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    doc_type: e.target.value as HandoverDocType,
                  })
                }
                className={inputCls}
                disabled={!!editDoc}
              >
                {DOC_TYPES.map((dt) => (
                  <option key={dt} value={dt}>
                    {docTypeLabel(t, dt)}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('propdev.doc_title', { defaultValue: 'Title' })}
            >
              <input
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                className={inputCls}
                placeholder={t('propdev.doc_title_placeholder', {
                  defaultValue: 'e.g. 10-year structural warranty',
                })}
                maxLength={255}
              />
            </WideModalField>
            <WideModalField
              label={t('propdev.doc_file_url', { defaultValue: 'File URL' })}
              span={2}
            >
              <input
                value={draft.file_url}
                onChange={(e) =>
                  setDraft({ ...draft, file_url: e.target.value })
                }
                className={inputCls}
                placeholder="https://… or uploads/…"
                maxLength={1024}
              />
            </WideModalField>
            <WideModalField
              label={t('propdev.doc_flags', { defaultValue: 'Status' })}
              span={2}
            >
              <div className="flex flex-wrap gap-4">
                <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.is_required}
                    onChange={(e) =>
                      setDraft({ ...draft, is_required: e.target.checked })
                    }
                    className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                  />
                  {t('propdev.doc_required', {
                    defaultValue: 'Required for handover',
                  })}
                </label>
                <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.is_delivered}
                    onChange={(e) =>
                      setDraft({ ...draft, is_delivered: e.target.checked })
                    }
                    className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                  />
                  {t('propdev.doc_delivered', {
                    defaultValue: 'Already delivered',
                  })}
                </label>
              </div>
            </WideModalField>
          </WideModalSection>
        </WideModal>
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
