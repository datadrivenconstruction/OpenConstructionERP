// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Modal that mints a signed download URL with a chosen TTL. */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Loader2, Copy, Mail, Clock, AlertTriangle, CheckCircle2 } from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { mintEmailLink } from '../api';
import { copyToClipboard } from '../lib/tauri';
import type { EmailLinkResponse, FileRow } from '../types';
import { fmtFixed, getIntlLocale } from '@/shared/lib/formatters';

interface EmailDialogProps {
  open: boolean;
  row: FileRow | null;
  onClose: () => void;
}

const TTL_PRESETS: { hours: number; labelKey: string; defaultLabel: string }[] = [
  { hours: 1, labelKey: 'files.email.ttl_1h', defaultLabel: '1 hour' },
  { hours: 24, labelKey: 'files.email.ttl_24h', defaultLabel: '1 day' },
  { hours: 72, labelKey: 'files.email.ttl_72h', defaultLabel: '3 days' },
  { hours: 7 * 24, labelKey: 'files.email.ttl_7d', defaultLabel: '7 days' },
  { hours: 14 * 24, labelKey: 'files.email.ttl_14d', defaultLabel: '14 days' },
];

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

export function EmailDialog({ open, row, onClose }: EmailDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [ttlHours, setTtlHours] = useState(72);
  const [link, setLink] = useState<EmailLinkResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) {
      setLink(null);
      setLoading(false);
      setError(null);
      setCopied(false);
      setTtlHours(72);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open || !row) return null;

  async function handleMint() {
    if (!row) return;
    setLoading(true);
    setError(null);
    try {
      const r = await mintEmailLink(row.id, ttlHours);
      setLink(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCopyUrl() {
    if (!link) return;
    const ok = await copyToClipboard(link.url);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } else {
      addToast({
        type: 'error',
        title: t('files.toast.copy_failed', { defaultValue: 'Could not copy link' }),
      });
    }
  }

  const sampleSubject = t('files.email.sample_subject', {
    defaultValue: 'File: {{name}}',
    name: row.name,
  });
  const sampleBody = link
    ? t('files.email.sample_body', {
        defaultValue:
          'Hi,\n\nHere is the file you asked about - {{name}} ({{size}}).\nDownload link (expires {{expires}}):\n{{url}}\n\n- sent from OpenConstructionERP',
        name: row.name,
        size: fmtBytes(link.size_bytes),
        expires: new Date(link.expires_at).toLocaleString(getIntlLocale()),
        url: link.url,
      })
    : '';
  const mailto = link
    ? `mailto:?subject=${encodeURIComponent(sampleSubject)}&body=${encodeURIComponent(sampleBody)}`
    : '';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="relative w-full max-w-md mx-4 rounded-xl border border-border-light bg-surface-elevated shadow-xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-content-primary">
              {t('files.email.title', { defaultValue: 'Share via email' })}
            </h2>
            <p className="text-2xs text-content-tertiary truncate" title={row.name}>
              {row.name}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div>
            <label className="block text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
              <Clock size={10} className="inline-block me-1 -mt-0.5" />
              {t('files.email.ttl', { defaultValue: 'Link expires after' })}
            </label>
            <div className="flex flex-wrap gap-1.5">
              {TTL_PRESETS.map((p) => (
                <button
                  key={p.hours}
                  type="button"
                  onClick={() => {
                    setTtlHours(p.hours);
                    setLink(null);
                  }}
                  className={clsx(
                    'px-3 h-8 rounded-full text-xs font-medium border transition-colors',
                    ttlHours === p.hours
                      ? 'bg-oe-blue text-white border-oe-blue'
                      : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                  )}
                >
                  {t(p.labelKey, { defaultValue: p.defaultLabel })}
                </button>
              ))}
            </div>
          </div>

          {!link ? (
            <button
              type="button"
              onClick={handleMint}
              disabled={loading}
              className="w-full inline-flex items-center justify-center gap-2 h-10 px-4 rounded-lg bg-oe-blue text-white text-sm font-medium hover:bg-oe-blue-hover disabled:opacity-50"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />}
              {t('files.email.generate', { defaultValue: 'Generate share link' })}
            </button>
          ) : (
            <>
              <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-2xs uppercase tracking-wide text-content-tertiary">
                    {t('files.email.url', { defaultValue: 'Share URL' })}
                  </span>
                  <button
                    type="button"
                    onClick={handleCopyUrl}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-2xs font-medium text-oe-blue hover:bg-oe-blue/10"
                  >
                    {copied ? (
                      <>
                        <CheckCircle2 size={11} />
                        {t('files.toast.copied', { defaultValue: 'Copied' })}
                      </>
                    ) : (
                      <>
                        <Copy size={11} />
                        {t('files.actions.copy', { defaultValue: 'Copy' })}
                      </>
                    )}
                  </button>
                </div>
                <div className="font-mono text-[10px] text-content-secondary break-all leading-relaxed">
                  {link.url}
                </div>
              </div>

              <div className="text-2xs text-content-tertiary">
                {t('files.email.expires', { defaultValue: 'Expires' })}:{' '}
                <span className="text-content-secondary">
                  {new Date(link.expires_at).toLocaleString(getIntlLocale())}
                </span>
              </div>

              <div>
                <label className="block text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                  {t('files.email.paste_into_email', { defaultValue: 'Sample email body' })}
                </label>
                <textarea
                  readOnly
                  value={sampleBody}
                  rows={6}
                  className="w-full text-xs font-mono p-2.5 rounded-lg border border-border-light bg-surface-primary text-content-secondary resize-none"
                />
              </div>

              <a
                href={mailto}
                className="inline-flex items-center justify-center gap-2 h-9 px-4 w-full rounded-lg bg-oe-blue text-white text-xs font-medium hover:bg-oe-blue-hover"
              >
                <Mail size={13} />
                {t('files.email.open_mail_client', { defaultValue: 'Open email client' })}
              </a>
            </>
          )}

          {error && (
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-semantic-error/10 text-semantic-error text-xs">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <p>{error}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
