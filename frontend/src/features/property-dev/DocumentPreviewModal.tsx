// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DocumentPreviewModal — preview and download Property Development PDFs.
//
// Wraps the two backend endpoints exposed by
// ``app.modules.property_dev.router``:
//   * POST /api/v1/property-dev/documents/preview → base64 + page count
//   * GET  /api/v1/property-dev/documents/{doc_type} → application/pdf stream
//
// Used from the SalesContract / Reservation / Handover drawers (and from
// the inline action buttons on PropertyDevPage). Renders six different
// PDFs depending on ``docType``:
//   reservation_receipt   — issued at deposit time
//   sales_contract        — the SPA (multi-page, jurisdiction-aware)
//   payment_receipt       — per instalment
//   handover_certificate  — at completion
//   warranty_certificate  — structural + finishing warranty
//   noc                   — No Objection Certificate for resale
//
// The languages offered are PROPERTY_DOCUMENT_LOCALES: every platform
// language the PDF layer can draw. The server prints a language it has no
// translation file for in English, key by key.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Loader2, Mail, Send, X } from 'lucide-react';

import { PROPERTY_DOCUMENT_LOCALES, defaultDocumentLocale } from '@/shared/lib/documentExport';
import { Button } from '@/shared/ui';
import { DocumentLanguageSelect } from '@/shared/ui/DocumentLanguageSelect';
import { WideModal } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';

import {
  downloadPropDevDocument,
  emailPropDevDocument,
  previewPropDevDocument,
  type PropDevDocPreview,
  type PropDevDocType,
} from './api';

// RFC 5322-lite — matches the backend guard; rejects obvious typos before
// the request so the user gets instant inline feedback.
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const DOC_TITLES: Record<PropDevDocType, { key: string; defaultValue: string }> = {
  reservation_receipt: {
    key: 'propdev.documents.reservation_receipt',
    defaultValue: 'Reservation Receipt',
  },
  sales_contract: {
    key: 'propdev.documents.sales_contract',
    defaultValue: 'Sales-Purchase Agreement',
  },
  payment_receipt: {
    key: 'propdev.documents.payment_receipt',
    defaultValue: 'Payment Receipt',
  },
  handover_certificate: {
    key: 'propdev.documents.handover_certificate',
    defaultValue: 'Handover Certificate',
  },
  warranty_certificate: {
    key: 'propdev.documents.warranty_certificate',
    defaultValue: 'Warranty Certificate',
  },
  noc: {
    key: 'propdev.documents.noc',
    defaultValue: 'No Objection Certificate',
  },
  tenant_lease_agreement: {
    key: 'propdev.documents.tenant_lease_agreement',
    defaultValue: 'Tenant Lease Agreement',
  },
  move_in_checklist: {
    key: 'propdev.documents.move_in_checklist',
    defaultValue: 'Move-In Checklist',
  },
  mortgage_clearance_letter: {
    key: 'propdev.documents.mortgage_clearance_letter',
    defaultValue: 'Mortgage Clearance Letter',
  },
  title_deed_transfer_request: {
    key: 'propdev.documents.title_deed_transfer_request',
    defaultValue: 'Title Deed Transfer Request',
  },
  escrow_release_authorization: {
    key: 'propdev.documents.escrow_release_authorization',
    defaultValue: 'Escrow Release Authorization',
  },
  refund_authorization: {
    key: 'propdev.documents.refund_authorization',
    defaultValue: 'Refund Authorization',
  },
};

export interface DocumentPreviewModalProps {
  open: boolean;
  onClose: () => void;
  docType: PropDevDocType;
  /** One of these must be set (the rest stay undefined). */
  contractId?: string;
  reservationId?: string;
  handoverId?: string;
  instalmentId?: string;
  /** Extra params forwarded to the backend (payment_method, etc.). */
  extraParams?: {
    payment_method?: string;
    payment_ref?: string;
    requested_by?: string;
    structural_warranty_years?: number;
    finishing_warranty_years?: number;
    noc_validity_days?: number;
  };
}

export function DocumentPreviewModal({
  open,
  onClose,
  docType,
  contractId,
  reservationId,
  handoverId,
  instalmentId,
  extraParams,
}: DocumentPreviewModalProps) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const defaultLocale = useMemo(
    () => defaultDocumentLocale(PROPERTY_DOCUMENT_LOCALES, i18n.language || null),
    [i18n.language],
  );

  const [locale, setLocale] = useState<string>(defaultLocale);
  const [preview, setPreview] = useState<PropDevDocPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Email-to-buyer flow. The composer is collapsed until the user clicks
  // "Email to buyer"; the recipient address is validated inline before the
  // request and the result toast reflects the backend delivery outcome.
  const [emailOpen, setEmailOpen] = useState(false);
  const [recipient, setRecipient] = useState('');
  const [recipientName, setRecipientName] = useState('');
  const [emailNote, setEmailNote] = useState('');
  const [sending, setSending] = useState(false);

  // Fetch on open + whenever locale changes.
  useEffect(() => {
    if (!open) {
      setPreview(null);
      setError(null);
      setEmailOpen(false);
      setRecipient('');
      setRecipientName('');
      setEmailNote('');
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    previewPropDevDocument({
      doc_type: docType,
      contract_id: contractId,
      reservation_id: reservationId,
      handover_id: handoverId,
      instalment_id: instalmentId,
      locale,
      ...extraParams,
    })
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    open,
    docType,
    locale,
    contractId,
    reservationId,
    handoverId,
    instalmentId,
    extraParams,
  ]);

  const handleDownload = async () => {
    try {
      const blob = await downloadPropDevDocument({
        doc_type: docType,
        contract_id: contractId,
        reservation_id: reservationId,
        handover_id: handoverId,
        instalment_id: instalmentId,
        locale,
        ...extraParams,
      });
      const filename = preview?.filename ?? `${docType}.pdf`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 200);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast({ type: 'error', title: t('common.download_failed', { defaultValue: 'Download failed' }), message });
    }
  };

  const recipientValid = EMAIL_RE.test(recipient.trim());

  const handleSendEmail = async () => {
    if (!recipientValid) return;
    setSending(true);
    try {
      const result = await emailPropDevDocument({
        doc_type: docType,
        contract_id: contractId,
        reservation_id: reservationId,
        handover_id: handoverId,
        instalment_id: instalmentId,
        locale,
        recipient_email: recipient.trim(),
        recipient_name: recipientName.trim() || undefined,
        note: emailNote.trim() || undefined,
        ...extraParams,
      });
      // ``delivered: false`` = the server fell back to the console backend
      // (SMTP not configured). Be honest: the message was logged, not sent.
      if (result.delivered) {
        addToast({
          type: 'success',
          title: t('propdev.documents.email_sent', { defaultValue: 'Document emailed' }),
          message: t('propdev.documents.email_sent_to', {
            defaultValue: 'Sent to {{email}}',
            email: result.recipient,
          }),
        });
      } else {
        addToast({
          type: 'info',
          title: t('propdev.documents.email_logged', {
            defaultValue: 'Email logged (SMTP not configured)',
          }),
          message: t('propdev.documents.email_logged_hint', {
            defaultValue:
              'Outbound email is not configured on this server, so the message ' +
              'was logged instead of delivered. Configure SMTP in settings to ' +
              'send for real.',
          }),
        });
      }
      setEmailOpen(false);
      setRecipient('');
      setRecipientName('');
      setEmailNote('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast({
        type: 'error',
        title: t('propdev.documents.email_failed', { defaultValue: 'Could not email document' }),
        message,
      });
    } finally {
      setSending(false);
    }
  };

  const title = t(DOC_TITLES[docType].key, {
    defaultValue: DOC_TITLES[docType].defaultValue,
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={
        preview
          ? t('propdev.documents.size_pages', {
              defaultValue: '{{pages}} page(s) · {{kb}} KB',
              pages: preview.page_count,
              kb: Math.max(1, Math.round(preview.size_bytes / 1024)),
            })
          : undefined
      }
      size="xl"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          <Button
            variant="ghost"
            onClick={() => setEmailOpen((v) => !v)}
            disabled={!preview || loading}
            aria-expanded={emailOpen}
            icon={<Mail className="h-4 w-4" />}
          >
            {t('propdev.documents.email_to_buyer', {
              defaultValue: 'Email to buyer',
            })}
          </Button>
          <Button
            variant="primary"
            onClick={handleDownload}
            disabled={!preview || loading}
            icon={<Download className="h-4 w-4" />}
          >
            {t('propdev.documents.download', { defaultValue: 'Download' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {/* Locale picker */}
        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor="propdev-document-locale" className="text-sm font-medium text-content-secondary">
            {t('propdev.documents.locale', { defaultValue: 'Locale' })}
          </label>
          <DocumentLanguageSelect
            id="propdev-document-locale"
            value={locale}
            onChange={setLocale}
            locales={PROPERTY_DOCUMENT_LOCALES}
            disabled={loading}
            data-testid="propdev-document-locale-trigger"
          />
          {loading && (
            <span className="flex items-center gap-1 text-sm text-content-tertiary">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t('propdev.documents.rendering', {
                defaultValue: 'Rendering…',
              })}
            </span>
          )}
        </div>

        {/* Email composer — collapsed until "Email to buyer" is clicked */}
        {emailOpen && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleSendEmail();
            }}
            className="space-y-3 rounded-lg border border-border bg-surface-secondary/60 p-4"
          >
            <p className="text-sm font-medium text-content-primary">
              {t('propdev.documents.email_compose_title', {
                defaultValue: 'Email this document',
              })}
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-content-secondary">
                  {t('propdev.documents.email_recipient', {
                    defaultValue: 'Recipient email',
                  })}
                  <span className="text-error"> *</span>
                </span>
                <input
                  type="email"
                  required
                  value={recipient}
                  onChange={(e) => setRecipient(e.target.value)}
                  placeholder="buyer@example.com"
                  className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                  disabled={sending}
                  aria-invalid={recipient.length > 0 && !recipientValid}
                />
                {recipient.length > 0 && !recipientValid && (
                  <span className="text-xs text-error">
                    {t('propdev.documents.email_invalid', {
                      defaultValue: 'Enter a valid email address',
                    })}
                  </span>
                )}
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-content-secondary">
                  {t('propdev.documents.email_recipient_name', {
                    defaultValue: 'Recipient name (optional)',
                  })}
                </span>
                <input
                  type="text"
                  value={recipientName}
                  onChange={(e) => setRecipientName(e.target.value)}
                  className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                  disabled={sending}
                />
              </label>
            </div>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-content-secondary">
                {t('propdev.documents.email_note', {
                  defaultValue: 'Note (optional)',
                })}
              </span>
              <textarea
                value={emailNote}
                onChange={(e) => setEmailNote(e.target.value)}
                rows={2}
                className="rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                disabled={sending}
              />
            </label>
            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setEmailOpen(false)}
                disabled={sending}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={!recipientValid || sending || !preview}
                icon={
                  sending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )
                }
              >
                {t('propdev.documents.email_send', { defaultValue: 'Send' })}
              </Button>
            </div>
          </form>
        )}

        {/* Preview surface */}
        <div className="min-h-[60vh] rounded-lg border border-border bg-surface-secondary">
          {error ? (
            <div className="flex h-full min-h-[60vh] flex-col items-center justify-center gap-2 p-6 text-center">
              <X className="h-10 w-10 text-error" />
              <p className="text-sm font-medium text-content-primary">
                {t('propdev.documents.preview_failed', {
                  defaultValue: 'Could not generate preview',
                })}
              </p>
              <p className="text-xs text-content-tertiary">{error}</p>
            </div>
          ) : preview ? (
            <iframe
              key={`${docType}-${locale}-${preview.size_bytes}`}
              src={`data:application/pdf;base64,${preview.base64}`}
              title={title}
              className="h-[60vh] w-full rounded-lg"
            />
          ) : (
            <div className="flex h-[60vh] items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-content-tertiary" />
            </div>
          )}
        </div>
      </div>
    </WideModal>
  );
}
