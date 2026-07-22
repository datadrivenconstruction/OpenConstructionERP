// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Mail, Check } from 'lucide-react';
import clsx from 'clsx';
import { openLink } from '@/shared/lib/desktop';

/**
 * Newsletter Subscribe trigger in the header.
 *
 * Clicking opens the canonical newsletter form on the marketing site
 * (https://openconstructionerp.com/#newsletter) in a new tab. We do not
 * embed an inline form anymore — the site is the single source of
 * truth for subscriptions, runs its own SMTP-backed pipeline, and
 * carries the up-to-date privacy copy.
 *
 * We still persist a localStorage flag after a user has subscribed on
 * the site so the trigger can render as a subtle "Subscribed" check
 * pill on subsequent visits. The flag is set via a postMessage from
 * the marketing site once it confirms the subscription, or
 * heuristically (after the user has visibly clicked the button at
 * least once) so the next visit reads as subscribed.
 */

const STORAGE_KEY = 'oe.newsletter_subscribed';
const SUBSCRIBE_URL = 'https://openconstructionerp.com/#newsletter';

function getInitialSubscribed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export function SubscribeButton({ condensed = false }: { condensed?: boolean } = {}) {
  const { t } = useTranslation();
  const [subscribed, setSubscribed] = useState<boolean>(getInitialSubscribed);

  // Listen for confirmation pings from the marketing site (postMessage
  // sent by /api/subscribe success handler). Best-effort — the site may
  // not currently send it; we still flip the local flag below when the
  // user clicks the trigger so the second visit reads as subscribed.
  useEffect(() => {
    function handler(ev: MessageEvent) {
      if (
        ev.origin === 'https://openconstructionerp.com' &&
        ev.data?.type === 'newsletter:subscribed'
      ) {
        try {
          window.localStorage.setItem(STORAGE_KEY, '1');
        } catch {
          /* private mode — ignore */
        }
        setSubscribed(true);
      }
    }
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  function handleClick() {
    openLink(SUBSCRIBE_URL);
    // Optimistic flag — next visit shows the "Subscribed" pill even if
    // the site never sent us a postMessage. User who didn't actually
    // complete the form will still see the button and can re-click.
    try {
      window.localStorage.setItem(STORAGE_KEY, '1');
    } catch {
      /* ignore */
    }
    setSubscribed(true);
  }

  const buttonLabel = subscribed
    ? t('header.subscribe.subscribed', { defaultValue: 'Subscribed' })
    : t('header.subscribe.button', { defaultValue: 'Subscribe' });

  return (
    <>
      {/* Desktop pill — matches Support / Help sizing (h-8 px-3). */}
      <button
        type="button"
        onClick={handleClick}
        aria-label={t('header.subscribe.button_aria', {
          defaultValue: 'Get release notes by email - opens the newsletter form on openconstructionerp.com',
        })}
        title={t('header.subscribe.button_title', {
          defaultValue: 'Get release notes by email (opens openconstructionerp.com)',
        })}
        className={clsx(
          // Partner mode condenses to the icon-only form so the co-brand
          // chip gets a clean central slot; otherwise full pill from md up.
          condensed ? 'hidden' : 'hidden md:inline-flex',
          'h-8 items-center gap-1.5 rounded-lg border px-3',
          'text-xs font-medium transition-colors',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/40',
          subscribed
            ? clsx(
                'border-emerald-400/50 bg-emerald-50/70 text-emerald-700',
                'dark:border-emerald-500/40 dark:bg-emerald-950/30 dark:text-emerald-300',
                'hover:bg-emerald-50 dark:hover:bg-emerald-950/50',
              )
            : clsx(
                'border-sky-400/50 bg-sky-50/70 text-sky-700',
                'dark:border-sky-500/40 dark:bg-sky-950/30 dark:text-sky-300',
                'hover:border-sky-500 hover:bg-sky-100/80',
                'dark:hover:border-sky-400/60 dark:hover:bg-sky-900/40',
              ),
        )}
      >
        {subscribed ? (
          <Check size={14} strokeWidth={2} className="shrink-0" />
        ) : (
          <Mail size={14} strokeWidth={2} className="shrink-0" />
        )}
        <span className="whitespace-nowrap tracking-wide truncate max-w-[140px]">
          {buttonLabel}
        </span>
      </button>

      {/* Mobile — icon-only square matching the Help footprint. */}
      <button
        type="button"
        onClick={handleClick}
        aria-label={t('header.subscribe.button_short', { defaultValue: 'Subscribe' })}
        title={buttonLabel}
        className={clsx(
          condensed ? 'inline-flex' : 'md:hidden inline-flex',
          'h-8 w-8 items-center justify-center rounded-lg',
          'transition-colors',
          subscribed
            ? 'text-emerald-600 hover:bg-surface-secondary'
            : 'text-sky-600 hover:bg-surface-secondary',
        )}
      >
        {subscribed ? (
          <Check size={16} strokeWidth={1.75} />
        ) : (
          <Mail size={16} strokeWidth={1.75} />
        )}
      </button>
    </>
  );
}
