// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The bidder's file side of a link: download the tender documents, send a
 * priced GAEB X84 instead of typing prices, add an offer PDF or attachments,
 * or say the firm will not bid.
 *
 * An X84 is checked first and every line that does not fit the bill is shown
 * with its reason; only a clean file can be submitted.
 */

import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Ban, Download, FileText, FileUp, Paperclip } from 'lucide-react';

import { Button } from '@/shared/ui';
import { fmtList, fmtNumber, formatDateValue } from '@/shared/lib/formatters';

import {
  BidPortalError,
  bidPortalDocumentUrl,
  checkBidX84,
  declineBid,
  submitBidX84,
  uploadBidFile,
  type BidPortalErrorCode,
  type BidPortalView,
  type X84Preview,
} from './api';

function sizeText(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${fmtNumber(bytes / (1024 * 1024), 1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

const ISSUE_KEYS: Record<string, [string, string]> = {
  unknown_position: ['bid_portal.x84.issue_unknown', 'Not on the bill'],
  unit_mismatch: ['bid_portal.x84.issue_unit', 'Unit differs from the bill'],
  quantity_changed: ['bid_portal.x84.issue_quantity', 'Quantity differs from the bill'],
  duplicate_position: ['bid_portal.x84.issue_duplicate', 'Item appears twice'],
  unpriced: ['bid_portal.x84.issue_unpriced', 'No unit price'],
};

export function BidExchangeSection({
  token,
  view,
  onView,
}: {
  token: string;
  view: BidPortalView;
  onView: (view: BidPortalView) => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<'check' | 'submit' | 'file' | 'decline' | null>(null);
  const [error, setError] = useState<BidPortalErrorCode | null>(null);
  const [x84, setX84] = useState<{ file: File; preview: X84Preview } | null>(null);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState('');
  const x84Input = useRef<HTMLInputElement>(null);
  const pdfInput = useRef<HTMLInputElement>(null);
  const attachInput = useRef<HTMLInputElement>(null);

  const open = view.state === 'open';
  const documents = view.documents ?? [];
  const files = view.files ?? [];

  const fail = (err: unknown) => setError(err instanceof BidPortalError ? err.code : 'unknown');

  const onX84 = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setBusy('check');
    try {
      setX84({ file, preview: await checkBidX84(token, file) });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
      if (x84Input.current) x84Input.current.value = '';
    }
  };

  const sendX84 = async () => {
    if (!x84) return;
    setError(null);
    setBusy('submit');
    try {
      onView(await submitBidX84(token, x84.file));
      setX84(null);
    } catch (err) {
      if (err instanceof BidPortalError && err.preview) setX84({ file: x84.file, preview: err.preview });
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const onFile = async (file: File | undefined, kind: 'offer_pdf' | 'attachment') => {
    if (!file) return;
    setError(null);
    setBusy('file');
    try {
      onView(await uploadBidFile(token, file, kind));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
      for (const input of [pdfInput.current, attachInput.current]) if (input) input.value = '';
    }
  };

  const sendDecline = async () => {
    if (!reason.trim()) return;
    setError(null);
    setBusy('decline');
    try {
      onView(await declineBid(token, reason.trim()));
      setDeclining(false);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const bad = x84 ? x84.preview.lines.filter((l) => l.issues.length > 0) : [];

  return (
    <section className="mt-4 space-y-4" data-testid="bid-exchange">
      {view.state === 'declined' && (
        <div className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-secondary p-4" role="status" data-testid="bid-portal-declined">
          <Ban className="mt-0.5 shrink-0 text-content-tertiary" size={20} aria-hidden />
          <div className="text-sm text-content-secondary">
            <p className="font-medium text-content-primary">
              {t('bid_portal.decline.done', { defaultValue: 'You told the buyer you will not bid.' })}
            </p>
            {view.decline_reason && (
              <p>{t('bid_portal.decline.your_reason', { defaultValue: 'Your reason: {{reason}}', reason: view.decline_reason })}</p>
            )}
          </div>
        </div>
      )}

      {documents.length > 0 && (
        <div className="rounded-lg border border-border-light bg-surface-primary p-4">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('bid_portal.documents.title', { defaultValue: 'Tender documents' })}
          </h2>
          <ul className="mt-2 divide-y divide-border-light text-sm" data-testid="bid-portal-documents">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-center justify-between gap-3 py-1.5">
                <span className="inline-flex min-w-0 items-center gap-2">
                  <FileText size={14} className="shrink-0 text-content-tertiary" aria-hidden />
                  <span className="truncate">{doc.name}</span>
                  {doc.revision_code && <span className="text-xs text-content-tertiary">{doc.revision_code}</span>}
                </span>
                <a
                  href={bidPortalDocumentUrl(token, doc.id)}
                  rel="noreferrer noopener"
                  referrerPolicy="no-referrer"
                  className="inline-flex shrink-0 items-center gap-1 text-xs text-oe-blue hover:underline"
                >
                  <Download size={12} aria-hidden />
                  {t('bid_portal.documents.download', { defaultValue: 'Download' })} ({sizeText(doc.file_size)})
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {open && (
        <div className="rounded-lg border border-border-light bg-surface-primary p-4">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('bid_portal.files.title', { defaultValue: 'Send files' })}
          </h2>
          <p className="mt-1 text-xs text-content-secondary">
            {t('bid_portal.files.hint', {
              defaultValue:
                'Priced the bill in your own program? Upload the GAEB X84 file instead of typing prices. Add your offer letter as PDF and any attachments.',
            })}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <input ref={x84Input} type="file" accept=".x84,.xml" className="hidden" data-testid="bid-x84-input" onChange={(e) => void onX84(e.target.files?.[0])} />
            <input ref={pdfInput} type="file" accept=".pdf,application/pdf" className="hidden" data-testid="bid-pdf-input" onChange={(e) => void onFile(e.target.files?.[0], 'offer_pdf')} />
            <input ref={attachInput} type="file" className="hidden" data-testid="bid-attach-input" onChange={(e) => void onFile(e.target.files?.[0], 'attachment')} />
            <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => x84Input.current?.click()}>
              <FileUp size={14} aria-hidden />
              {t('bid_portal.x84.upload', { defaultValue: 'Upload priced X84' })}
            </Button>
            <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => pdfInput.current?.click()}>
              <FileText size={14} aria-hidden />
              {t('bid_portal.files.offer_pdf', { defaultValue: 'Upload offer PDF' })}
            </Button>
            <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => attachInput.current?.click()}>
              <Paperclip size={14} aria-hidden />
              {t('bid_portal.files.attachment', { defaultValue: 'Add attachment' })}
            </Button>
            <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => setDeclining((d) => !d)}>
              <Ban size={14} aria-hidden />
              {t('bid_portal.decline.open', { defaultValue: 'We will not bid' })}
            </Button>
          </div>

          {declining && (
            <div className="mt-3 space-y-2" data-testid="bid-decline-form">
              <label className="block text-xs text-content-secondary" htmlFor="bid-decline-reason">
                {t('bid_portal.decline.reason_label', { defaultValue: 'Why not? The buyer reads this.' })}
              </label>
              <textarea
                id="bid-decline-reason"
                className="w-full rounded-lg border border-border-light bg-surface-primary p-2 text-sm"
                rows={2}
                maxLength={2000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <Button variant="danger" size="sm" disabled={!reason.trim() || busy !== null} onClick={() => void sendDecline()}>
                {t('bid_portal.decline.confirm', { defaultValue: 'Send decline' })}
              </Button>
            </div>
          )}

          {x84 && (
            <div className="mt-3 space-y-2 text-sm" data-testid="bid-x84-preview">
              <p className="font-medium text-content-primary">{x84.preview.filename}</p>
              {bad.length === 0 && !x84.preview.blocking ? (
                <p className="text-semantic-success">
                  {t('bid_portal.x84.fits', {
                    defaultValue: 'Every line fits the bill. Lines: {{count}}, priced: {{priced}}.',
                    count: x84.preview.lines.length,
                    priced: x84.preview.priced,
                  })}
                </p>
              ) : (
                <>
                  <p className="text-semantic-error">
                    {t('bid_portal.x84.mismatch', {
                      defaultValue: 'Lines that do not fit the bill: {{count}}. Correct the file and upload it again.',
                      count: bad.length,
                    })}
                  </p>
                  <table className="oe-table w-full text-xs" data-testid="bid-x84-mismatches">
                    <thead>
                      <tr>
                        <th className="text-left">{t('bid_portal.col.ordinal', { defaultValue: 'Item no.' })}</th>
                        <th className="text-left">{t('bid_portal.x84.col_problem', { defaultValue: 'Problem' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bad.map((line, index) => (
                        <tr key={`${line.ordinal}-${index}`}>
                          <td className="font-mono">{line.ordinal}</td>
                          <td>
                            {fmtList(
                              line.issues.map((issue) => {
                                const [key, fallback] = ISSUE_KEYS[issue] ?? ['bid_portal.x84.issue_other', issue];
                                return t(key, { defaultValue: fallback });
                              }),
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
              {x84.preview.missing_ordinals.length > 0 && (
                <p className="text-content-secondary">
                  {t('bid_portal.x84.missing', {
                    defaultValue: 'Not in your file: {{items}}',
                    items: fmtList(x84.preview.missing_ordinals.slice(0, 20)),
                  })}
                </p>
              )}
              <div className="flex gap-2">
                <Button variant="primary" size="sm" disabled={x84.preview.blocking || busy !== null} onClick={() => void sendX84()}>
                  {t('bid_portal.x84.submit', { defaultValue: 'Submit bid from this file' })}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setX84(null)}>
                  {t('common.cancel', { defaultValue: 'Cancel' })}
                </Button>
              </div>
            </div>
          )}
          {error && (
            <p className="mt-2 text-sm text-semantic-error" role="alert">
              <ExchangeErrorText code={error} />
            </p>
          )}
        </div>
      )}

      {files.length > 0 && (
        <div className="rounded-lg border border-border-light bg-surface-primary p-4">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('bid_portal.files.sent', { defaultValue: 'Files you sent' })}
          </h2>
          <ul className="mt-2 space-y-1 text-sm" data-testid="bid-portal-files">
            {files.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center gap-x-3 text-content-secondary">
                <span className="text-content-primary">{f.file_name}</span>
                <span className="text-xs">{t(`bid_portal.files.kind_${f.kind}`, { defaultValue: f.kind })}</span>
                <span className="text-xs">{sizeText(f.file_size)}</span>
                <span className="text-xs">{formatDateValue(f.uploaded_at, { dateStyle: 'medium', timeStyle: 'short' })}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ExchangeErrorText({ code }: { code: BidPortalErrorCode }) {
  const { t } = useTranslation();
  switch (code) {
    case 'x84_mismatch':
      return <>{t('bid_portal.x84.refused', { defaultValue: 'The file does not fit the bill; see the lines above.' })}</>;
    case 'file_rejected':
      return <>{t('bid_portal.files.rejected', { defaultValue: 'This file type is not accepted. Use PDF, Office, image, ZIP or GAEB files.' })}</>;
    case 'file_too_large':
      return <>{t('bid_portal.files.too_large', { defaultValue: 'The file is larger than 25 MB.' })}</>;
    case 'too_many_files':
      return <>{t('bid_portal.files.too_many', { defaultValue: 'You have sent the most files allowed for this tender.' })}</>;
    case 'declined':
      return <>{t('bid_portal.decline.done', { defaultValue: 'You told the buyer you will not bid.' })}</>;
    case 'already_submitted':
      return <>{t('bid_portal.error.already_submitted', { defaultValue: 'This bid was already submitted.' })}</>;
    case 'closed':
      return <>{t('bid_portal.error.closed', { defaultValue: 'The tender is closed.' })}</>;
    case 'rate_limited':
      return <>{t('bid_portal.error.rate_limited', { defaultValue: 'Too many requests. Wait a minute and try again.' })}</>;
    default:
      return <>{t('bid_portal.error.unknown', { defaultValue: 'Something went wrong. Your entries are still on this page; try again.' })}</>;
  }
}
