// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Modal for creating + managing password-protected share links.
 *
 * Lets the file owner mint a 32-char URL token with an optional
 * password and expiry, copy the public URL, and revoke any existing
 * link. Mounted from the file-preview action stack next to the
 * existing "Email link" button.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  Loader2,
  Lock,
  Share2,
  Trash2,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { copyToClipboard } from '../lib/tauri';
import {
  createShareLink,
  listShareLinks,
  revokeShareLink,
} from '../api';
import type { FileRow, ShareLinkResponse } from '../types';
import { getIntlLocale } from '@/shared/lib/formatters';

interface ShareLinkModalProps {
  open: boolean;
  row: FileRow | null;
  onClose: () => void;
}

interface ExpiryPreset {
  value: number | null;
  labelKey: string;
  defaultLabel: string;
}

const EXPIRY_PRESETS: ExpiryPreset[] = [
  { value: 1, labelKey: 'files.share.expiry_1d', defaultLabel: '1 day' },
  { value: 7, labelKey: 'files.share.expiry_7d', defaultLabel: '7 days' },
  { value: 30, labelKey: 'files.share.expiry_30d', defaultLabel: '30 days' },
  { value: null, labelKey: 'files.share.expiry_never', defaultLabel: 'Never' },
];

/** Convert a token-relative path (``/share/abc``) to an absolute URL.
 *  Falls back to the path itself in non-browser contexts (SSR / tests). */
function absoluteShareUrl(path: string): string {
  if (typeof window === 'undefined' || !window.location) return path;
  return `${window.location.origin}${path}`;
}

export function ShareLinkModal({ open, row, onClose }: ShareLinkModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [password, setPassword] = useState('');
  const [expiryDays, setExpiryDays] = useState<number | null>(7);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [justCreated, setJustCreated] = useState<ShareLinkResponse | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const { data: existingLinks = [], isLoading: listLoading } = useQuery({
    queryKey: ['document-share-links', row?.id ?? null],
    queryFn: () => (row ? listShareLinks(row.id) : Promise.resolve([])),
    enabled: open && !!row,
    staleTime: 10_000,
  });

  useEffect(() => {
    if (!open) {
      setPassword('');
      setExpiryDays(7);
      setCreating(false);
      setCreateError(null);
      setJustCreated(null);
      setCopiedToken(null);
      setRevokingId(null);
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

  const invalidate = useCallback(() => {
    if (!row) return;
    queryClient.invalidateQueries({
      queryKey: ['document-share-links', row.id],
    });
  }, [queryClient, row]);

  async function handleCreate() {
    if (!row) return;
    setCreating(true);
    setCreateError(null);
    try {
      const payload: { password?: string; expires_in_days?: number } = {};
      if (password.trim()) payload.password = password.trim();
      if (expiryDays !== null) payload.expires_in_days = expiryDays;
      const link = await createShareLink(row.id, payload);
      setJustCreated(link);
      setPassword('');
      invalidate();
    } catch (e) {
      setCreateError((e as Error).message);
      addToast({
        type: 'error',
        title: t('files.share.error_create', {
          defaultValue: 'Could not create the share link.',
        }),
      });
    } finally {
      setCreating(false);
    }
  }

  async function handleCopy(link: ShareLinkResponse) {
    const absolute = absoluteShareUrl(link.url);
    const ok = await copyToClipboard(absolute);
    if (ok) {
      setCopiedToken(link.token);
      setTimeout(() => {
        setCopiedToken((current) => (current === link.token ? null : current));
      }, 1500);
    }
  }

  async function handleRevoke(link: ShareLinkResponse) {
    if (!row) return;
    setRevokingId(link.id);
    try {
      await revokeShareLink(row.id, link.id);
      // Clear the freshly-minted card if it was just revoked.
      setJustCreated((current) => (current && current.id === link.id ? null : current));
      invalidate();
    } catch (e) {
      addToast({
        type: 'error',
        title: t('files.share.error_revoke', {
          defaultValue: 'Could not revoke the share link.',
        }),
        message: (e as Error).message,
      });
    } finally {
      setRevokingId(null);
    }
  }

  if (!open || !row) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-link-modal-title"
    >
      <div
        className="relative w-full max-w-md mx-4 rounded-xl border border-border-light bg-surface-elevated shadow-xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <div className="min-w-0">
            <h2
              id="share-link-modal-title"
              className="text-sm font-semibold text-content-primary flex items-center gap-2"
            >
              <Share2 size={14} strokeWidth={2.25} />
              {t('files.share.title', {
                defaultValue: 'Password-protected share link',
              })}
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

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* ── Create new link ───────────────────────────────────── */}
          <section className="space-y-3">
            <div>
              <label
                htmlFor="share-link-password"
                className="block text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5"
              >
                <Lock size={10} className="inline-block me-1 -mt-0.5" />
                {t('files.share.password_label', {
                  defaultValue: 'Password (optional)',
                })}
              </label>
              <input
                id="share-link-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('files.share.password_placeholder', {
                  defaultValue: 'Leave blank for an open link',
                })}
                autoComplete="off"
                className="w-full h-9 px-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/50"
              />
            </div>

            <div>
              <span className="block text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                {t('files.share.expiry_label', { defaultValue: 'Expires after' })}
              </span>
              <div
                className="flex flex-wrap gap-1.5"
                role="radiogroup"
                aria-label={t('files.share.expiry_label', {
                  defaultValue: 'Expires after',
                })}
              >
                {EXPIRY_PRESETS.map((p) => (
                  <button
                    key={p.labelKey}
                    type="button"
                    role="radio"
                    aria-checked={expiryDays === p.value}
                    onClick={() => setExpiryDays(p.value)}
                    className={clsx(
                      'px-3 h-8 rounded-full text-xs font-medium border transition-colors',
                      expiryDays === p.value
                        ? 'bg-oe-blue text-white border-oe-blue'
                        : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    {t(p.labelKey, { defaultValue: p.defaultLabel })}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              onClick={handleCreate}
              disabled={creating}
              className="w-full inline-flex items-center justify-center gap-2 h-10 px-4 rounded-lg bg-oe-blue text-white text-sm font-medium hover:bg-oe-blue-hover disabled:opacity-50"
            >
              {creating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Share2 size={14} />
              )}
              {creating
                ? t('files.share.creating', { defaultValue: 'Creating link…' })
                : t('files.share.create', { defaultValue: 'Create link' })}
            </button>

            {createError && (
              <div className="flex items-start gap-2 p-2.5 rounded-lg bg-semantic-error/10 text-semantic-error text-xs">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <p>{createError}</p>
              </div>
            )}

            {justCreated && (
              <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-2xs uppercase tracking-wide text-content-tertiary">
                    {t('files.share.url_label', { defaultValue: 'Share URL' })}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleCopy(justCreated)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-2xs font-medium text-oe-blue hover:bg-oe-blue/10"
                  >
                    {copiedToken === justCreated.token ? (
                      <>
                        <CheckCircle2 size={11} />
                        {t('files.share.copied', { defaultValue: 'Copied' })}
                      </>
                    ) : (
                      <>
                        <Copy size={11} />
                        {t('files.share.copy', { defaultValue: 'Copy' })}
                      </>
                    )}
                  </button>
                </div>
                <div
                  data-testid="share-link-url"
                  className="font-mono text-[10px] text-content-secondary break-all leading-relaxed"
                >
                  {absoluteShareUrl(justCreated.url)}
                </div>
                {justCreated.expires_at && (
                  <div className="text-2xs text-content-tertiary">
                    {t('files.share.expires_label', { defaultValue: 'Expires' })}
                    :{' '}
                    <span className="text-content-secondary">
                      {new Date(justCreated.expires_at).toLocaleString(getIntlLocale())}
                    </span>
                  </div>
                )}
              </div>
            )}
          </section>

          {/* ── Existing links ────────────────────────────────────── */}
          <section className="space-y-2 border-t border-border-light pt-4">
            <h3 className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('files.share.existing_title', { defaultValue: 'Existing links' })}
            </h3>
            {listLoading ? (
              <div className="h-3 rounded bg-surface-secondary animate-pulse" />
            ) : existingLinks.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('files.share.existing_empty', {
                  defaultValue: 'No share links yet - create one above.',
                })}
              </p>
            ) : (
              <ul className="space-y-2">
                {existingLinks.map((link) => (
                  <li
                    key={link.id}
                    data-testid="existing-share-link"
                    className="rounded-lg border border-border-light bg-surface-primary p-2.5 text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0 flex items-center gap-1.5">
                        {link.requires_password && (
                          <Lock
                            size={11}
                            strokeWidth={2}
                            className="text-content-tertiary shrink-0"
                            aria-label={t('files.share.requires_password', {
                              defaultValue: 'Password protected',
                            })}
                          />
                        )}
                        <span className="font-mono text-[10px] text-content-secondary truncate">
                          {absoluteShareUrl(link.url)}
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => handleCopy(link)}
                          aria-label={t('files.share.copy', { defaultValue: 'Copy' })}
                          className="inline-flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:text-oe-blue hover:bg-surface-secondary"
                          title={t('files.share.copy', { defaultValue: 'Copy' })}
                        >
                          {copiedToken === link.token ? (
                            <CheckCircle2 size={12} />
                          ) : (
                            <Copy size={12} />
                          )}
                        </button>
                        <a
                          href={absoluteShareUrl(link.url)}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={t('files.share.open_link', {
                            defaultValue: 'Open link',
                          })}
                          className="inline-flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:text-oe-blue hover:bg-surface-secondary"
                          title={t('files.share.open_link', {
                            defaultValue: 'Open link',
                          })}
                        >
                          <ExternalLink size={12} />
                        </a>
                        <button
                          type="button"
                          onClick={() => handleRevoke(link)}
                          disabled={revokingId === link.id}
                          aria-label={t('files.share.revoke', { defaultValue: 'Revoke' })}
                          className="inline-flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:text-semantic-error hover:bg-semantic-error/10 disabled:opacity-50"
                          title={t('files.share.revoke', { defaultValue: 'Revoke' })}
                        >
                          {revokingId === link.id ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <Trash2 size={12} />
                          )}
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-content-tertiary">
                      <span>
                        {link.expires_at
                          ? `${t('files.share.expires_label', { defaultValue: 'Expires' })}: ${new Date(link.expires_at).toLocaleString(getIntlLocale())}`
                          : t('files.share.never_expires', {
                              defaultValue: 'Never expires',
                            })}
                      </span>
                      <span className="tabular-nums">
                        {t('files.share.download_count', {
                          count: link.download_count,
                          defaultValue_one: '{{count}} download',
                          defaultValue_other: '{{count}} downloads',
                        })}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
