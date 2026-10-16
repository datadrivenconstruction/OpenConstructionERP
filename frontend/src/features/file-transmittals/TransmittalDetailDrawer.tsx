// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Slide-out drawer showing a single transmittal: items + recipients +
// ack timeline + "Download cover" button.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Eye, FileText, Mail, CheckCircle2, Clock, X } from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { InlinePdfPreviewModal } from '@/features/file-references/InlinePdfPreviewModal';

import { downloadTransmittalCover } from './api';
import { useTransmittal } from './hooks';
import type { TransmittalItem, TransmittalRecipient } from './types';
import { RecordPartiesPanel } from '@/features/teams/RecordPartiesPanel';

// English fallbacks for the computed `files.transmittals.reason.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const TRANSMITTALS_REASON_LABELS: Record<string, string> = {
  for_review: 'For review', for_construction: 'For construction', for_approval: 'For approval',
  for_information: 'For information', for_record: 'For record'
};


/** A transmittal item is previewable inline when it is a document-kind PDF -
 *  those resolve to the bearer-protected `/documents/{id}/download/` route the
 *  inline viewer can fetch. Other kinds keep their plain text row (#246). */
function pdfPreviewUrl(item: TransmittalItem): string | null {
  if (item.file_kind !== 'document') return null;
  if (!/\.pdf$/i.test(item.canonical_name_snapshot ?? '')) return null;
  return `/api/v1/documents/${item.file_id}/download/`;
}

interface TransmittalDetailDrawerProps {
  open: boolean;
  transmittalId: string | null;
  onClose: () => void;
}

export function TransmittalDetailDrawer({
  open,
  transmittalId,
  onClose,
}: TransmittalDetailDrawerProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useTransmittal(transmittalId);
  const addToast = useToastStore((s) => s.addToast);
  // Inline PDF preview (#246) - opens a referenced document without leaving
  // the drawer. Holds the URL + title of the item being previewed, or null.
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(
    null,
  );

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  async function handleDownload() {
    if (!transmittalId) return;
    try {
      await downloadTransmittalCover(transmittalId, data?.number ?? 'transmittal');
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.transmittals.cover_download_failed', {
          defaultValue: 'Cover sheet download failed',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }

  if (!open) return null;

  const reasonLabel = (code: string): string =>
    t(`files.transmittals.reason.${code}`, {
      defaultValue: TRANSMITTALS_REASON_LABELS[code] ?? code
        .split('_')
        .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
        .join(' '),
    });

  const sortedRecipients: TransmittalRecipient[] = data?.recipients
    ? [...data.recipients].sort((a, b) => {
        // Acked first, then unacked, alpha by email within group.
        if (Boolean(a.acknowledged_at) !== Boolean(b.acknowledged_at)) {
          return a.acknowledged_at ? -1 : 1;
        }
        return a.email.localeCompare(b.email);
      })
    : [];

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={t('files.transmittals.detail_title', {
          defaultValue: 'Transmittal details',
        })}
        className={clsx(
          'fixed inset-y-0 right-0 z-50 w-full max-w-md',
          'bg-surface-elevated border-l border-border-light shadow-2xl',
          'flex flex-col animate-slide-in-right',
        )}
      >
        <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-border-light">
          <div className="min-w-0">
            <p className="font-mono text-xs text-content-tertiary">
              {data?.number ?? '—'}
            </p>
            <h2 className="text-base font-semibold text-content-primary truncate">
              {data?.subject ?? t('common.loading', { defaultValue: 'Loading…' })}
            </h2>
            {data && (
              <p className="text-xs text-content-secondary mt-0.5">
                {reasonLabel(data.reason_code)} · <DateDisplay value={data.sent_at} />
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="text-content-tertiary hover:text-content-primary"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
          {isLoading && (
            <p className="text-sm text-content-tertiary text-center py-6">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </p>
          )}

          {data && (
            <>
              <RecordPartiesPanel
                projectId={data.project_id}
                entityType="file_transmittal"
                entityId={data.id}
              />
              <section>
                <h3 className="text-xs font-semibold text-content-secondary uppercase mb-2">
                  {t('files.transmittals.items', { defaultValue: 'Items' })}
                </h3>
                {data.items.length === 0 ? (
                  <p className="text-xs text-content-tertiary italic">
                    {t('files.transmittals.no_items_short', {
                      defaultValue: 'No items.',
                    })}
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {data.items.map((it) => {
                      const previewUrl = pdfPreviewUrl(it);
                      return (
                        <li
                          key={it.id}
                          className="flex items-center gap-2 text-sm py-1"
                        >
                          <FileText size={14} className="text-content-tertiary shrink-0" />
                          <span className="truncate flex-1">
                            {it.canonical_name_snapshot}
                            {it.file_version_snapshot && (
                              <span className="text-xs text-content-tertiary ml-1">
                                v{it.file_version_snapshot}
                              </span>
                            )}
                          </span>
                          {previewUrl && (
                            <button
                              type="button"
                              onClick={() =>
                                setPreview({
                                  url: previewUrl,
                                  title: it.canonical_name_snapshot,
                                })
                              }
                              data-testid={`transmittal-item-preview-${it.id}`}
                              title={t('files.preview.open_inline', {
                                defaultValue: 'Preview here',
                              })}
                              className="inline-flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue shrink-0"
                            >
                              <Eye size={14} />
                            </button>
                          )}
                          <span className="text-xs text-content-tertiary">
                            {it.file_kind}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="text-xs font-semibold text-content-secondary uppercase mb-2">
                  {t('files.transmittals.ack_timeline', {
                    defaultValue: 'Acknowledgements',
                  })}
                </h3>
                {sortedRecipients.length === 0 ? (
                  <p className="text-xs text-content-tertiary italic">
                    {t('files.transmittals.no_recipients_short', {
                      defaultValue: 'No recipients.',
                    })}
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {sortedRecipients.map((r) => {
                      const acked = r.acknowledged_at !== null;
                      const Icon = acked ? CheckCircle2 : Clock;
                      return (
                        <li
                          key={r.id}
                          className="flex items-start gap-2 text-sm py-1"
                        >
                          <Icon
                            size={14}
                            className={clsx(
                              'mt-0.5 shrink-0',
                              acked
                                ? 'text-semantic-success'
                                : 'text-content-tertiary',
                            )}
                          />
                          <div className="min-w-0 flex-1">
                            <p className="font-medium truncate">
                              {r.display_name || r.email}
                            </p>
                            <p className="text-xs text-content-tertiary truncate">
                              {r.email}
                              {r.role ? ` · ${r.role}` : ''}
                            </p>
                            {acked && r.acknowledged_at && (
                              <p className="text-xs text-semantic-success mt-0.5">
                                <DateDisplay value={r.acknowledged_at} />
                              </p>
                            )}
                          </div>
                          {acked ? (
                            <Badge variant="success" size="sm">
                              {t('files.transmittals.ack_done', {
                                defaultValue: 'Acked',
                              })}
                            </Badge>
                          ) : (
                            <Badge variant="neutral" size="sm">
                              {t('files.transmittals.ack_pending', {
                                defaultValue: 'Pending',
                              })}
                            </Badge>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              {data.notes && (
                <section>
                  <h3 className="text-xs font-semibold text-content-secondary uppercase mb-2">
                    {t('files.transmittals.notes', { defaultValue: 'Notes' })}
                  </h3>
                  <p className="text-sm text-content-secondary whitespace-pre-wrap">
                    {data.notes}
                  </p>
                </section>
              )}
            </>
          )}
        </div>

        <footer className="shrink-0 px-5 py-3 border-t border-border-light bg-surface-primary/30 flex items-center justify-between gap-2">
          <Mail size={14} className="text-content-tertiary" />
          <Button
            variant="primary"
            onClick={handleDownload}
            icon={<Download size={14} />}
            disabled={!data}
          >
            {t('files.transmittals.download_cover', {
              defaultValue: 'Download cover',
            })}
          </Button>
        </footer>
      </aside>

      {/* Inline PDF preview for document items (#246). */}
      <InlinePdfPreviewModal
        open={preview !== null}
        downloadUrl={preview?.url ?? null}
        title={preview?.title ?? ''}
        onClose={() => setPreview(null)}
      />
    </>
  );
}
