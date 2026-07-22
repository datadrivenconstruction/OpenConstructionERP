// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * HeaderNewsButton - a "What's new" entry point in the top app header.
 *
 * Clicking opens a small popup that links to the latest release news on the
 * marketing site (openconstructionerp.com/news.html). We open the site in a
 * new tab rather than embedding it: the site sends X-Frame-Options SAMEORIGIN,
 * so a self-hosted or desktop build (a different origin) could not iframe it,
 * and a real navigation is what makes the visit count in the site's own
 * analytics. The popup is a clear, one-step heads-up before leaving the app:
 * it names the destination, explains the site uses anonymised analytics
 * cookies, and links the cookie policy. The actual cookie choice is collected
 * by the site's own GDPR consent banner (the single source of truth), so we do
 * not duplicate a consent dialog here.
 *
 * A small dot marks an unacknowledged feature release, using the same
 * `oe.last_seen_version` flag as the WhatsNewCard so the two stay in sync -
 * opening the popup here also clears the dashboard card.
 *
 * Icon-only to match the other header controls (notifications, help); the
 * label rides in the tooltip and aria-label.
 */

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Newspaper, X, ExternalLink } from 'lucide-react';
import clsx from 'clsx';

import { APP_VERSION } from '@/shared/lib/version';
import { openLink } from '@/shared/lib/desktop';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

/** Shared with WhatsNewCard: which release the user has acknowledged. */
const LAST_SEEN_KEY = 'oe.last_seen_version';

/**
 * Latest news on the marketing site. The UTM tags let the site's analytics
 * attribute the pageview to the in-app News button, which is exactly the
 * "counts as a site visit" signal we want. news.html is the news index
 * (newest first), so it never needs a per-release URL bump.
 */
const NEWS_URL =
  'https://openconstructionerp.com/news.html?utm_source=erp_app&utm_medium=news_button';
const COOKIE_POLICY_URL = 'https://openconstructionerp.com/cookie-policy.html';

/**
 * True when the current release is a newer feature version (major.minor)
 * than the one the user last acknowledged. Patch bumps do not light the dot.
 * Wrapped so a hardened browser without localStorage just reports "nothing
 * new" rather than throwing.
 */
function hasUnseenRelease(current: string): boolean {
  if (!current) return false;
  try {
    const lastSeen = window.localStorage.getItem(LAST_SEEN_KEY);
    if (!lastSeen) return true;
    const c = current.split('.').map((x) => parseInt(x, 10) || 0);
    const p = lastSeen.split('.').map((x) => parseInt(x, 10) || 0);
    if ((c[0] ?? 0) !== (p[0] ?? 0)) return (c[0] ?? 0) > (p[0] ?? 0);
    return (c[1] ?? 0) > (p[1] ?? 0);
  } catch {
    return false;
  }
}

export function HeaderNewsButton({ className }: { className?: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [unseen, setUnseen] = useState(false);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useFocusTrap(panelRef, open);

  useEffect(() => {
    setUnseen(hasUnseenRelease(APP_VERSION));
  }, []);

  // Close on Escape while the popup is open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  const label = t('header.whats_new', { defaultValue: "What's new" });

  /** Acknowledge this release so the dot here and the dashboard card quiet down. */
  const acknowledge = () => {
    try {
      window.localStorage.setItem(LAST_SEEN_KEY, APP_VERSION);
    } catch {
      /* localStorage unavailable - ignore */
    }
    setUnseen(false);
  };

  const handleButtonClick = () => {
    acknowledge();
    setOpen(true);
  };

  const handleOpenNews = () => {
    openLink(NEWS_URL);
    setOpen(false);
  };

  // Fallback for users who would rather read the in-app changelog than leave
  // the app. Kept quiet (a text link) so the primary path stays obvious.
  const handleViewInApp = () => {
    setOpen(false);
    navigate('/about#changelog');
  };

  return (
    <>
      <button
        type="button"
        onClick={handleButtonClick}
        aria-label={label}
        title={label}
        data-testid="header-whats-new"
        className={clsx(
          'relative flex h-8 w-8 items-center justify-center rounded-lg',
          'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
          'transition-colors focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
          className,
        )}
      >
        <Newspaper size={16} strokeWidth={1.9} />
        {unseen && (
          <span
            aria-hidden="true"
            className="absolute right-1 top-1 h-2 w-2 rounded-full bg-rose-500 ring-2 ring-surface-primary"
          />
        )}
      </button>

      {open &&
        createPortal(
          <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setOpen(false);
            }}
          >
            <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px]" aria-hidden="true" />
            <div
              ref={panelRef}
              tabIndex={-1}
              role="dialog"
              aria-modal="true"
              aria-label={label}
              className={clsx(
                'relative w-full max-w-md rounded-2xl border border-border-light',
                'bg-surface-elevated shadow-2xl focus:outline-none animate-fade-in',
              )}
            >
              {/* Header */}
              <div className="flex items-start gap-3 border-b border-border-light p-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
                  <Newspaper size={18} strokeWidth={1.9} />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-content-primary">{label}</h2>
                  <p className="mt-0.5 text-xs text-content-tertiary">
                    {t('header.news.source', { defaultValue: 'From openconstructionerp.com' })}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label={t('common.close', { defaultValue: 'Close' })}
                  className="shrink-0 rounded-lg p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
                >
                  <X size={16} />
                </button>
              </div>

              {/* Body */}
              <div className="space-y-2 p-4">
                <p className="text-sm text-content-secondary">
                  {t('header.news.body', {
                    defaultValue:
                      'Read the latest OpenConstructionERP release news on our site.',
                  })}
                </p>
                <p className="text-xs leading-relaxed text-content-tertiary">
                  {t('header.news.cookie_note', {
                    defaultValue:
                      'This opens openconstructionerp.com in a new tab. The site uses anonymised analytics cookies; you can accept or decline there.',
                  })}{' '}
                  <a
                    href={COOKIE_POLICY_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-oe-blue-text underline underline-offset-2 hover:text-oe-blue-hover"
                  >
                    {t('header.news.cookie_policy', { defaultValue: 'Cookie policy' })}
                  </a>
                </p>
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between gap-2 border-t border-border-light p-4">
                <button
                  type="button"
                  onClick={handleViewInApp}
                  className="text-xs font-medium text-content-tertiary hover:text-content-primary transition-colors"
                >
                  {t('header.news.view_in_app', { defaultValue: 'View in-app changelog' })}
                </button>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    className="rounded-lg px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary transition-colors"
                  >
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </button>
                  <button
                    type="button"
                    onClick={handleOpenNews}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white hover:bg-oe-blue-hover transition-colors focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                  >
                    <ExternalLink size={13} strokeWidth={2} />
                    {t('header.news.open', { defaultValue: 'Open the latest news' })}
                  </button>
                </div>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

export default HeaderNewsButton;
