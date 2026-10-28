// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Public share-link landing page (``/share/:token``).
 *
 * Rendered for unauthenticated visitors who follow a share URL.
 * Flow:
 *    1. ``GET /v1/documents/share-links/{token}/`` — fetch
 *       filename + flags. 404 → render "Link not found".
 *    2. If ``expired`` → render "expired" notice.
 *    3. If ``requires_password`` → render a password input. Submit
 *       calls ``POST /share-links/{token}/access/``; 401 → show
 *       inline error; 200 → redirect to ``download_url``.
 *    4. If no password is required → auto-call access and redirect.
 *
 * Brand-aware: shows the OpenConstructionERP logo + project tagline
 * without the authenticated app shell (no sidebar). The page handles
 * its own loading / error states.
 */

import { useEffect, useState, type FormEvent } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Clock,
  Download,
  FileText,
  Loader2,
  Lock,
  ShieldX,
} from 'lucide-react';
import { Logo } from '@/shared/ui';
import { accessShareLink, fetchShareLinkInfo } from './api';
import type { ShareLinkPublicInfo } from './types';

type FetchState =
  | { kind: 'loading' }
  | { kind: 'not_found' }
  | { kind: 'expired'; info: ShareLinkPublicInfo }
  | { kind: 'open'; info: ShareLinkPublicInfo };

export function SharePage() {
  const { t } = useTranslation();
  const { token } = useParams<{ token: string }>();

  const [state, setState] = useState<FetchState>({ kind: 'loading' });
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  // 1. Initial probe.
  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setState({ kind: 'not_found' });
      return;
    }
    (async () => {
      try {
        const info = await fetchShareLinkInfo(token);
        if (cancelled) return;
        if (info.expired) {
          setState({ kind: 'expired', info });
        } else {
          setState({ kind: 'open', info });
        }
      } catch {
        if (!cancelled) setState({ kind: 'not_found' });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  // 2. If the link is open + no password required, auto-resolve.
  useEffect(() => {
    if (state.kind !== 'open') return;
    if (state.info.requires_password) return;
    if (!token || downloadUrl) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await accessShareLink(token, undefined);
        if (!cancelled) setDownloadUrl(res.download_url);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [state, token, downloadUrl]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token || submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const res = await accessShareLink(token, password);
      setDownloadUrl(res.download_url);
    } catch (e) {
      const msg = (e as Error).message;
      if (msg === 'UNAUTHORIZED') {
        setError(
          t('share.page.bad_password', {
            defaultValue: 'Wrong password. Please try again.',
          }),
        );
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-surface-secondary via-surface-primary to-surface-elevated flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <header className="flex items-center justify-center mb-6">
          <Logo size="lg" />
        </header>

        <div className="rounded-xl border border-border-light bg-surface-elevated shadow-xl p-6 sm:p-8 space-y-5">
          <div className="text-center">
            <h1 className="text-base font-semibold text-content-primary">
              {t('share.page.title', { defaultValue: 'Shared file' })}
            </h1>
            <p className="mt-1 text-xs text-content-tertiary">
              {t('share.page.subtitle', {
                defaultValue:
                  'Someone shared a file with you via OpenConstructionERP.',
              })}
            </p>
          </div>

          {/* Loading state */}
          {state.kind === 'loading' && (
            <div className="flex flex-col items-center gap-2 py-6 text-content-tertiary">
              <Loader2 size={20} className="animate-spin" />
              <p className="text-xs">
                {t('share.page.loading', { defaultValue: 'Loading link…' })}
              </p>
            </div>
          )}

          {/* Not found / revoked */}
          {state.kind === 'not_found' && (
            <div
              data-testid="share-not-found"
              className="rounded-lg border border-semantic-error/30 bg-semantic-error/5 p-4 text-center space-y-2"
            >
              <ShieldX
                size={28}
                strokeWidth={1.5}
                className="mx-auto text-semantic-error"
              />
              <h2 className="text-sm font-semibold text-content-primary">
                {t('share.page.not_found_title', {
                  defaultValue: 'Link not found',
                })}
              </h2>
              <p className="text-xs text-content-secondary">
                {t('share.page.not_found_body', {
                  defaultValue: 'The link is invalid or has been revoked.',
                })}
              </p>
            </div>
          )}

          {/* Expired */}
          {state.kind === 'expired' && (
            <div
              data-testid="share-expired"
              className="rounded-lg border border-amber-300/40 bg-amber-50 dark:bg-amber-900/20 p-4 text-center space-y-2"
            >
              <Clock
                size={28}
                strokeWidth={1.5}
                className="mx-auto text-amber-600 dark:text-amber-400"
              />
              <h2 className="text-sm font-semibold text-content-primary">
                {t('share.page.expired_title', {
                  defaultValue: 'This link has expired',
                })}
              </h2>
              <p className="text-xs text-content-secondary">
                {t('share.page.expired_body', {
                  defaultValue: 'Ask the sender to share a new link.',
                })}
              </p>
            </div>
          )}

          {/* Open: password prompt or auto-resolved download */}
          {state.kind === 'open' && (
            <>
              <div className="flex items-start gap-3 rounded-lg bg-surface-secondary/40 border border-border-light p-3">
                <FileText
                  size={18}
                  strokeWidth={1.75}
                  className="text-oe-blue shrink-0 mt-0.5"
                />
                <div className="min-w-0">
                  <p className="text-2xs uppercase tracking-wide text-content-tertiary">
                    {t('share.page.filename_label', { defaultValue: 'File' })}
                  </p>
                  <p
                    className="text-sm font-medium text-content-primary truncate"
                    title={state.info.filename}
                    data-testid="share-filename"
                  >
                    {state.info.filename}
                  </p>
                </div>
              </div>

              {state.info.requires_password && !downloadUrl && (
                <form onSubmit={handleSubmit} className="space-y-3">
                  <div>
                    <label
                      htmlFor="share-password"
                      className="block text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5"
                    >
                      <Lock size={11} className="inline-block me-1 -mt-0.5" />
                      {t('share.page.password_prompt', {
                        defaultValue: 'Enter the password to download.',
                      })}
                    </label>
                    <input
                      id="share-password"
                      data-testid="share-password-input"
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={t('share.page.password_placeholder', {
                        defaultValue: 'Password',
                      })}
                      autoFocus
                      autoComplete="off"
                      className="w-full h-10 px-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/50"
                    />
                  </div>
                  {error && (
                    <div
                      data-testid="share-error"
                      role="alert"
                      className="flex items-start gap-2 p-2.5 rounded-lg bg-semantic-error/10 text-semantic-error text-xs"
                    >
                      <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                      <p>{error}</p>
                    </div>
                  )}
                  <button
                    type="submit"
                    data-testid="share-unlock-button"
                    disabled={submitting || password.length === 0}
                    className="w-full inline-flex items-center justify-center gap-2 h-10 px-4 rounded-lg bg-oe-blue text-white text-sm font-medium hover:bg-oe-blue-hover disabled:opacity-50"
                  >
                    {submitting ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Download size={14} />
                    )}
                    {submitting
                      ? t('share.page.unlocking', { defaultValue: 'Verifying…' })
                      : t('share.page.unlock', {
                          defaultValue: 'Unlock and download',
                        })}
                  </button>
                </form>
              )}

              {downloadUrl && (
                <div className="space-y-2">
                  <p className="text-xs text-content-secondary text-center">
                    {t('share.page.ready_body', {
                      defaultValue: 'Click the button below to download the file.',
                    })}
                  </p>
                  <a
                    href={downloadUrl}
                    data-testid="share-download-link"
                    className="w-full inline-flex items-center justify-center gap-2 h-10 px-4 rounded-lg bg-oe-blue text-white text-sm font-medium hover:bg-oe-blue-hover"
                  >
                    <Download size={14} />
                    {t('share.page.download', { defaultValue: 'Download file' })}
                  </a>
                </div>
              )}

              {/* Auto-resolved (no password) but the API errored */}
              {!state.info.requires_password && !downloadUrl && error && (
                <div
                  data-testid="share-error"
                  role="alert"
                  className="flex items-start gap-2 p-2.5 rounded-lg bg-semantic-error/10 text-semantic-error text-xs"
                >
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  <p>{error}</p>
                </div>
              )}
            </>
          )}
        </div>

        <p className="mt-4 text-center text-2xs text-content-quaternary">
          OpenConstructionERP · datadrivenconstruction.io
        </p>
      </div>
    </div>
  );
}
