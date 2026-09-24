// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ReviewPromptCard - a compact, corner-anchored ask for a rating or review.
 *
 * Deliberately NOT a modal. It carries no backdrop, no `aria-modal`, no focus
 * trap and no body-scroll lock, so it can never block or interrupt work. It
 * slides into the bottom-right corner, sits above the page, and goes away on
 * any of its three exits (review, later, never).
 *
 * Mounted inside `AppLayout`, which is the authenticated shell. Login,
 * register, forgot-password and the onboarding wizard all render OUTSIDE that
 * shell (`app/App.tsx` mounts onboarding full-screen with no layout), so
 * those surfaces are excluded structurally rather than by a route blocklist
 * that would rot the next time a route is added.
 *
 * The cadence itself lives in `stores/useReviewPromptStore.ts` - this file
 * only renders what the gate decided.
 */

import { useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Star, Github, Linkedin, MessageSquareQuote, X, ExternalLink } from 'lucide-react';
import clsx from 'clsx';

import { useReviewPromptStore } from '@/stores/useReviewPromptStore';

/* ── review destinations ──────────────────────────────────────────────── */

const REPO_URL = 'https://github.com/datadrivenconstruction/OpenConstructionERP';

const SHARE_TEXT =
  'OpenConstructionERP - free open-source construction cost estimation platform (BOQ, BIM takeoff, AI). Self-hosted. AGPL-3.0.';

const LINKEDIN_URL = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(
  REPO_URL,
)}`;

const X_URL = `https://twitter.com/intent/tweet?text=${encodeURIComponent(
  SHARE_TEXT,
)}&url=${encodeURIComponent(REPO_URL)}`;

/**
 * G2 listing. Confirmed to exist by the founder.
 *
 * Deliberately the clean product URL, with no "?source=search" suffix: that
 * suffix is G2's own search-result tracking and has no business in a link we
 * hand to a user. Other places in the tree still carry the tracked form; they
 * are being aligned separately.
 *
 * Typed `string | null` so the row can be switched off again by setting this
 * to null, without touching the markup below.
 */
const G2_REVIEW_URL: string | null = 'https://www.g2.com/products/openconstructionerp/reviews';

/* ── component ────────────────────────────────────────────────────────── */

export function ReviewPromptCard() {
  const { t } = useTranslation();
  const visible = useReviewPromptStore((s) => s.visible);
  const evaluate = useReviewPromptStore((s) => s.evaluate);
  const decline = useReviewPromptStore((s) => s.decline);
  const stopForever = useReviewPromptStore((s) => s.stopForever);
  const recordReviewed = useReviewPromptStore((s) => s.recordReviewed);

  useEffect(() => {
    evaluate();
  }, [evaluate]);

  // Following any review destination is terminal - someone who has just left
  // a review must never be asked for one again.
  const handleReviewed = useCallback(() => {
    recordReviewed();
  }, [recordReviewed]);

  if (!visible) return null;

  const linkClass = clsx(
    'group inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5',
    'text-xs font-medium transition-colors',
    'border-border-light bg-surface-primary text-content-primary',
    'hover:border-amber-400 hover:bg-amber-50',
    'dark:hover:border-amber-500/50 dark:hover:bg-amber-950/40',
  );

  return (
    <div
      role="region"
      aria-label={t('review_ask.aria_label', { defaultValue: 'Rate OpenConstructionERP' })}
      data-testid="review-prompt-card"
      className={clsx(
        'oe-dock-aware fixed bottom-4 right-4 z-[60] w-[min(22rem,calc(100vw-2rem))]',
        'rounded-xl border p-3.5 shadow-lg animate-card-in',
        'border-amber-300/60 bg-surface-elevated',
        'dark:border-amber-500/30',
      )}
    >
      <button
        type="button"
        onClick={decline}
        aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
        className="absolute top-2 right-2 rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
      >
        <X size={14} />
      </button>

      <div className="flex items-start gap-2.5 pr-6">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/15 text-amber-600 dark:text-amber-300">
          <Star size={16} className="fill-current" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary">
            {t('review_ask.title', { defaultValue: 'Enjoying OpenConstructionERP?' })}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-content-secondary">
            {t('review_ask.body', {
              defaultValue:
                'A minute of honest feedback helps other construction teams find and trust the platform. It genuinely makes a difference to us.',
            })}
          </p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <a
          href={REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleReviewed}
          className={linkClass}
        >
          <Github size={12} />
          {t('review_ask.github', { defaultValue: 'Star on GitHub' })}
          <ExternalLink size={10} className="text-content-quaternary" aria-hidden />
        </a>

        {G2_REVIEW_URL !== null && (
          <a
            href={G2_REVIEW_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={handleReviewed}
            className={linkClass}
          >
            <MessageSquareQuote size={12} />
            {t('review_ask.g2', { defaultValue: 'Review on G2' })}
            <ExternalLink size={10} className="text-content-quaternary" aria-hidden />
          </a>
        )}

        <a
          href={LINKEDIN_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleReviewed}
          className={linkClass}
        >
          <Linkedin size={12} />
          {t('review_ask.linkedin', { defaultValue: 'Share on LinkedIn' })}
          <ExternalLink size={10} className="text-content-quaternary" aria-hidden />
        </a>

        <a
          href={X_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleReviewed}
          className={linkClass}
        >
          {t('review_ask.x', { defaultValue: 'Post on X' })}
          <ExternalLink size={10} className="text-content-quaternary" aria-hidden />
        </a>
      </div>

      <div className="mt-2.5 flex items-center justify-end gap-2 border-t border-border-light pt-2.5">
        <button
          type="button"
          onClick={stopForever}
          className="rounded-md px-2 py-1 text-xs font-medium text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
        >
          {t('review_ask.never', { defaultValue: "Don't ask again" })}
        </button>
        <button
          type="button"
          onClick={decline}
          className="rounded-md px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
        >
          {t('review_ask.later', { defaultValue: 'Maybe later' })}
        </button>
      </div>
    </div>
  );
}

export default ReviewPromptCard;
