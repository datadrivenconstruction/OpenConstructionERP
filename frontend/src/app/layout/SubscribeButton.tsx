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

export function SubscribeButton() {
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
      {/* Icon-only square at every width, the Help footprint: the news
          subscription stays one click away without taking a labelled pill. */}
      <button
        type="button"
        onClick={handleClick}
        aria-label={t('header.subscribe.button_aria', {
          defaultValue: 'Get release notes by email - opens the newsletter form on openconstructionerp.com',
        })}
        title={subscribed ? buttonLabel : t('header.subscribe.button_title', {
          defaultValue: 'Get release notes by email (opens openconstructionerp.com)',
        })}
        className={clsx(
          'inline-flex h-8 w-8 items-center justify-center rounded-lg',
          'transition-colors',
          subscribed
            ? 'text-semantic-success hover:bg-surface-secondary'
            : 'text-semantic-info hover:bg-surface-secondary',
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
