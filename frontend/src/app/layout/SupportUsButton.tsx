// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Star,
  Github,
  Twitter,
  Linkedin,
  Heart,
  HandCoins,
  X,
  ExternalLink,
  Copy,
  Check,
  Megaphone,
  Mail,
  Send,
  Users,
  ArrowRight,
  Sparkles,
  MessageSquareQuote,
} from 'lucide-react';
import clsx from 'clsx';
import { copyToClipboard } from '@/shared/lib/browser';
import {
  reviewAskShownWithin,
  CROSS_SURFACE_QUIET_MS,
} from '@/stores/useReviewPromptStore';

const REPO_URL = 'https://github.com/datadrivenconstruction/OpenConstructionERP';
const PAYPAL_DONATE_URL = 'https://www.paypal.com/donate/?hosted_button_id=DWBCLNLY2VWAA';
const GITHUB_SPONSORS_URL = 'https://github.com/sponsors/datadrivenconstruction';
// Clean product URL. The "?source=search" suffix this used to carry is G2's
// own search-result tracking and does not belong in a link handed to a user.
const G2_REVIEWS_URL = 'https://www.g2.com/products/openconstructionerp/reviews';
const CASE_STUDY_EMAIL = 'info@datadrivenconstruction.io';
const CASE_STUDY_MAILTO = `mailto:${CASE_STUDY_EMAIL}?subject=${encodeURIComponent(
  'Case study / article - OpenConstructionERP',
)}&body=${encodeURIComponent(
  'Hi DDC team,\n\nI have a case study / video / article about how we use OpenConstructionERP that you may want to share.\n\nLink / attachment:\n\nA few lines about the project:\n\n- ',
)}`;

const SHARE_TEXT =
  'OpenConstructionERP - free open-source construction cost estimation platform (BOQ, BIM takeoff, AI, 41 languages). Self-hosted. AGPL-3.0.';

const TWITTER_URL = `https://twitter.com/intent/tweet?text=${encodeURIComponent(
  SHARE_TEXT,
)}&url=${encodeURIComponent(REPO_URL)}`;

const LINKEDIN_URL = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(
  REPO_URL,
)}`;

/* Auto-popup configuration.
 * ACTIVE_MS — only ticks while the tab is visible, so a backgrounded
 * laptop doesn't accumulate "session time" overnight.
 * COOLDOWN_MS — once the modal has been shown (manually or auto), we
 * don't auto-show again for 30 days. Set to 0 in dev/E2E to test.
 */
const AUTO_POPUP_AFTER_MS = 20 * 60 * 1000; // 20 minutes of active tab time
const COOLDOWN_MS = 30 * 24 * 60 * 60 * 1000; // 30 days
const SEEN_KEY = 'oe_support_seen_at';
const TICK_INTERVAL_MS = 10_000; // 10s — light-touch counter

/** Hook: accumulate active-tab time across the session.
 *  Pauses when the tab is hidden so we don't burn the 20-min threshold
 *  on an inactive browser. Returns total ms accumulated this mount. */
function useActiveTabTime(): number {
  const [activeMs, setActiveMs] = useState(0);
  const lastTick = useRef<number>(Date.now());
  const visible = useRef<boolean>(
    typeof document !== 'undefined' ? document.visibilityState === 'visible' : true,
  );

  useEffect(() => {
    const onVisibility = () => {
      // Commit elapsed time up to now, then flip the visible flag for
      // subsequent ticks. Hidden → no more accumulation until visible again.
      const now = Date.now();
      if (visible.current) {
        setActiveMs((prev) => prev + (now - lastTick.current));
      }
      lastTick.current = now;
      visible.current = document.visibilityState === 'visible';
    };
    document.addEventListener('visibilitychange', onVisibility);

    const id = window.setInterval(() => {
      if (!visible.current) return;
      const now = Date.now();
      setActiveMs((prev) => prev + (now - lastTick.current));
      lastTick.current = now;
    }, TICK_INTERVAL_MS);

    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.clearInterval(id);
    };
  }, []);

  return activeMs;
}

function readSeenAt(): number | null {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    if (!raw) return null;
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function writeSeenAt(): void {
  try {
    localStorage.setItem(SEEN_KEY, String(Date.now()));
  } catch {
    /* private mode — ignore */
  }
}

export function SupportUsButton({ condensed = false }: { condensed?: boolean } = {}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const activeMs = useActiveTabTime();

  // Public demo — skip auto-popup. The DemoBanner already nudges users
  // to install locally; auto-popping a "support us" prompt on top of
  // that feels needy. Reuse the same ['system-status'] query DemoBanner
  // uses so we share the single /api/system/status fetch (queryKey +
  // queryFn match DemoBanner.tsx). React Query dedupes by key.
  const { data: sysInfo } = useQuery<{ demo_mode?: boolean }>({
    queryKey: ['system-status'],
    queryFn: () => fetch('/api/system/status').then((r) => r.json()),
    staleTime: Infinity,
    retry: false,
  });
  const isDemo = sysInfo?.demo_mode === true;

  const handleOpen = useCallback(() => {
    setOpen(true);
    // Manual open also satisfies the "shown recently" check so we don't
    // auto-pop the same session right after the user has already engaged.
    writeSeenAt();
  }, []);

  const handleClose = useCallback(() => {
    setOpen(false);
    writeSeenAt();
  }, []);

  /* Auto-popup trigger.
   * Fires once per mount when:
   *   • not a demo deployment
   *   • not already open
   *   • active-tab time has crossed the threshold
   *   • cooldown window has elapsed since the last view (manual or auto)
   *   • the review card has not just asked the same thing
   *
   * Only the UNPROMPTED popup is gated. Opening the modal from the button is
   * someone deciding to support us, and that is never suppressed - see
   * handleOpen above, which has no such check.
   */
  useEffect(() => {
    if (isDemo || open) return;
    if (activeMs < AUTO_POPUP_AFTER_MS) return;
    const seenAt = readSeenAt();
    if (seenAt && Date.now() - seenAt < COOLDOWN_MS) return;
    // ReviewPromptCard makes the same asks (star, review, share). If it has
    // shown in the last few days, don't stack this modal on top of it. The
    // window is short and the card is hard-capped, so this can only ever
    // delay the modal, never mute it - the reasoning is written out in full
    // on reviewAskShownWithin().
    if (reviewAskShownWithin(CROSS_SURFACE_QUIET_MS)) return;
    setOpen(true);
    writeSeenAt();
  }, [activeMs, isDemo, open]);

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className={clsx(
          'support-btn group relative items-center gap-1.5 h-8 px-3 rounded-lg overflow-hidden',
          // Partner mode condenses secondary actions to icons so the
          // co-brand chip gets a clean central slot; otherwise show the
          // full labelled pill from 2xl up.
          //
          // 2xl, not md: the header's right-hand cluster is `shrink-0`, so it
          // never compresses and its content width sets the width of the whole
          // document. At a 1280 viewport the labelled form pushed the page to
          // 1307 in English and 1401 in Uzbek, whose label for this button is
          // "Bizni qo'llab-quvvatlang" - 24 characters against English's 10,
          // and the widest of any language we offer. Dropping to the icon here
          // and at Subscribe returns 232px at Uzbek against the 121 needed.
          // It has to be 2xl rather than xl because xl is 1280 exactly, the
          // width that fails.
          condensed ? 'hidden' : 'hidden 2xl:inline-flex',
          'border border-amber-400/60 dark:border-amber-500/40',
          'bg-gradient-to-r from-amber-100/80 via-yellow-100/60 to-orange-100/80',
          'dark:from-amber-900/40 dark:via-yellow-900/30 dark:to-orange-900/40',
          'text-amber-800 dark:text-amber-200',
          'hover:from-amber-200 hover:via-yellow-200 hover:to-orange-200',
          'dark:hover:from-amber-800/60 dark:hover:via-yellow-800/50 dark:hover:to-orange-800/60',
          'hover:border-amber-500 dark:hover:border-amber-400/60',
          'hover:shadow-md hover:shadow-amber-400/30',
          'transition-all duration-300 ease-out',
        )}
        title={t('support.button_tooltip', {
          defaultValue: 'Support the project - star us or share',
        })}
        aria-label={t('support.button_aria', { defaultValue: 'Support us' })}
      >
        {/* Animated shine sweep on hover */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/60 to-transparent group-hover:translate-x-full transition-transform duration-700 ease-out"
        />
        <Star
          size={14}
          strokeWidth={2}
          className="relative fill-amber-400 text-amber-500 drop-shadow-[0_0_3px_rgba(251,191,36,0.6)] group-hover:rotate-12 group-hover:scale-125 transition-transform duration-300"
        />
        <span className="relative text-xs font-semibold whitespace-nowrap tracking-wide">
          {t('support.button_label', { defaultValue: 'Support us' })}
        </span>
      </button>

      {/* Narrow-screen form — icon-only, fits the cramped topbar. Carries the
          header below 2xl, which is every laptop, so it is the common case
          rather than a mobile fallback. */}
      <button
        type="button"
        onClick={handleOpen}
        className={clsx(
          condensed ? 'inline-flex' : '2xl:hidden inline-flex',
          'h-8 w-8 items-center justify-center rounded-lg',
          'text-amber-500 hover:bg-surface-secondary transition-colors',
        )}
        title={t('support.button_tooltip', {
          defaultValue: 'Support the project',
        })}
        aria-label={t('support.button_aria', { defaultValue: 'Support us' })}
      >
        <Star size={16} strokeWidth={1.75} className="fill-amber-400 text-amber-500" />
      </button>

      {open && (
        <SupportUsModal
          onClose={handleClose}
          copied={copied}
          setCopied={setCopied}
        />
      )}
    </>
  );
}

interface ModalProps {
  onClose: () => void;
  copied: boolean;
  setCopied: (v: boolean) => void;
}

function SupportUsModal({ onClose, copied, setCopied }: ModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () =>
      document.removeEventListener('keydown', handler, { capture: true });
  }, [onClose]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  useEffect(() => {
    const id = window.setTimeout(() => {
      dialogRef.current
        ?.querySelector<HTMLElement>('a[data-firstfocus="true"]')
        ?.focus();
    }, 30);
    return () => window.clearTimeout(id);
  }, []);

  const copyShareText = async () => {
    try {
      await copyToClipboard(`${SHARE_TEXT} ${REPO_URL}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore — older browsers without clipboard API */
    }
  };

  const panel = (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center p-3 sm:p-6 bg-black/45 backdrop-blur-[3px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="support-us-title"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-[640px] max-h-[92vh] overflow-y-auto rounded-xl bg-surface-primary shadow-2xl border border-border-light animate-card-in"
      >
        {/* Hero band */}
        <div className="relative overflow-hidden rounded-t-xl">
          <div
            aria-hidden
            className="absolute inset-0 bg-gradient-to-br from-amber-200/40 via-orange-100/30 to-yellow-100/40 dark:from-amber-900/30 dark:via-orange-900/20 dark:to-yellow-900/30"
          />
          <div
            aria-hidden
            className="absolute -top-10 -right-8 w-56 h-56 rounded-full bg-amber-300/30 dark:bg-amber-500/15 blur-3xl"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="absolute top-3 right-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={18} />
          </button>
          <div className="relative px-6 sm:px-8 py-7 text-center">
            <div className="inline-flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 text-white shadow-lg mb-4">
              <Heart size={26} strokeWidth={2} />
            </div>
            <h2
              id="support-us-title"
              className="text-xl sm:text-2xl font-bold text-content-primary leading-tight"
            >
              {t('support.modal_title', {
                defaultValue: 'Help OpenConstructionERP grow',
              })}
            </h2>
            <p className="mt-3 mx-auto max-w-[560px] text-sm text-content-secondary leading-relaxed">
              {t('support.modal_subtitle', {
                defaultValue:
                  'We build OpenConstructionERP in the open and ship every feature for free. If you share a video, case study or article about your work – there is a very high chance industry professionals will notice it: senior estimators, BIM managers, planning leads and cost engineers from the largest construction and engineering firms follow DataDrivenConstruction across LinkedIn, X and our newsletter (tens of thousands of subscribers). One repost from us can put your project in front of the right people overnight.',
              })}
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="px-6 sm:px-8 pt-5 space-y-3">
          {/* 1. Star on GitHub */}
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            data-firstfocus="true"
            className={clsx(
              'group flex items-start gap-3 rounded-xl border-2 p-4',
              'border-amber-300/50 bg-gradient-to-br from-amber-50/60 to-orange-50/30',
              'dark:border-amber-500/30 dark:from-amber-950/30 dark:to-orange-950/20',
              'hover:border-amber-500 hover:shadow-md hover:-translate-y-0.5 transition-all',
            )}
          >
            <div className="shrink-0 h-11 w-11 rounded-xl bg-amber-500/15 text-amber-600 dark:text-amber-300 flex items-center justify-center group-hover:bg-amber-500 group-hover:text-white transition-colors">
              <Star size={20} strokeWidth={1.75} className="fill-current" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm sm:text-base font-semibold text-content-primary flex items-center gap-2">
                {t('support.action_star_title', {
                  defaultValue: 'Star us on GitHub',
                })}
                <Github size={14} className="text-content-tertiary" />
              </h3>
              <p className="mt-0.5 text-xs text-content-secondary leading-relaxed">
                {t('support.action_star_body', {
                  defaultValue:
                    '30 seconds. Stars are how new construction teams discover the project and how we secure time for the next release.',
                })}
              </p>
            </div>
            <ExternalLink
              size={14}
              className="shrink-0 mt-1 text-content-quaternary group-hover:text-amber-600 transition-colors"
              aria-hidden
            />
          </a>

          {/* 2. Review on G2 */}
          <a
            href={G2_REVIEWS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className={clsx(
              'group flex items-start gap-3 rounded-xl border-2 p-4',
              'border-rose-300/50 bg-gradient-to-br from-rose-50/60 to-orange-50/30',
              'dark:border-rose-500/30 dark:from-rose-950/30 dark:to-orange-950/20',
              'hover:border-rose-500 hover:shadow-md hover:-translate-y-0.5 transition-all',
            )}
          >
            <div className="shrink-0 h-11 w-11 rounded-xl bg-rose-500/15 text-rose-600 dark:text-rose-300 flex items-center justify-center group-hover:bg-rose-600 group-hover:text-white transition-colors">
              <MessageSquareQuote size={20} strokeWidth={1.75} />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm sm:text-base font-semibold text-content-primary flex items-center gap-2">
                {t('support.action_review_title', {
                  defaultValue: 'Review us on G2',
                })}
                <span className="text-2xs font-semibold uppercase tracking-wider text-rose-600 dark:text-rose-300 px-1.5 py-0.5 rounded bg-rose-500/10">
                  {t('support.action_review_tag', {
                    defaultValue: 'Means a lot',
                  })}
                </span>
              </h3>
              <p className="mt-0.5 text-xs text-content-secondary leading-relaxed">
                {t('support.action_review_body', {
                  defaultValue:
                    'We would be grateful if you rate us or write a short review on G2. Two minutes of honest feedback from a real user helps other construction teams trust and discover the platform - it genuinely means a lot to us.',
                })}
              </p>
            </div>
            <ExternalLink
              size={14}
              className="shrink-0 mt-1 text-content-quaternary group-hover:text-rose-600 transition-colors"
              aria-hidden
            />
          </a>

          {/* 3. Share on social */}
          <div
            className={clsx(
              'group rounded-xl border-2 p-4',
              'border-sky-300/50 bg-gradient-to-br from-sky-50/60 to-blue-50/30',
              'dark:border-sky-500/30 dark:from-sky-950/30 dark:to-blue-950/20',
            )}
          >
            <div className="flex items-start gap-3 mb-2">
              <div className="shrink-0 h-11 w-11 rounded-xl bg-sky-500/15 text-sky-600 dark:text-sky-300 flex items-center justify-center">
                <Send size={20} strokeWidth={1.75} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm sm:text-base font-semibold text-content-primary">
                  {t('support.action_share_title', {
                    defaultValue: 'Share with your team or network',
                  })}
                </h3>
                <p className="mt-0.5 text-xs text-content-secondary leading-relaxed">
                  {t('support.action_share_body', {
                    defaultValue:
                      'One post on LinkedIn or X / Twitter reaches dozens of estimators, planners and BIM managers. Help us put open-source construction software on the map.',
                  })}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 ml-14">
              <a
                href={TWITTER_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary hover:bg-sky-50 hover:border-sky-400 dark:hover:bg-sky-950/40 transition-colors"
              >
                <Twitter size={12} />
                {t('support.share_twitter', { defaultValue: 'Post on X' })}
              </a>
              <a
                href={LINKEDIN_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary hover:bg-sky-50 hover:border-sky-400 dark:hover:bg-sky-950/40 transition-colors"
              >
                <Linkedin size={12} />
                {t('support.share_linkedin', { defaultValue: 'Post on LinkedIn' })}
              </a>
              <button
                type="button"
                onClick={copyShareText}
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary hover:bg-sky-50 hover:border-sky-400 dark:hover:bg-sky-950/40 transition-colors"
              >
                {copied ? <Check size={12} className="text-semantic-success" /> : <Copy size={12} />}
                {copied
                  ? t('support.share_copied', { defaultValue: 'Copied!' })
                  : t('support.share_copy', { defaultValue: 'Copy text + link' })}
              </button>
            </div>
          </div>

          {/* 3. Got a case study / video / article? — DDC offers cross-promotion */}
          <a
            href={CASE_STUDY_MAILTO}
            className={clsx(
              'group flex items-start gap-3 rounded-xl border-2 p-4',
              'border-purple-300/50 bg-gradient-to-br from-purple-50/60 to-fuchsia-50/30',
              'dark:border-purple-500/30 dark:from-purple-950/30 dark:to-fuchsia-950/20',
              'hover:border-purple-500 hover:shadow-md hover:-translate-y-0.5 transition-all',
            )}
          >
            <div className="shrink-0 h-11 w-11 rounded-xl bg-purple-500/15 text-purple-600 dark:text-purple-300 flex items-center justify-center group-hover:bg-purple-600 group-hover:text-white transition-colors">
              <Megaphone size={20} strokeWidth={1.75} />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm sm:text-base font-semibold text-content-primary flex items-center gap-2">
                {t('support.action_case_study_title', {
                  defaultValue: 'Got a case study, video or article?',
                })}
                <span className="text-2xs font-semibold uppercase tracking-wider text-purple-600 dark:text-purple-300 px-1.5 py-0.5 rounded bg-purple-500/10">
                  {t('support.action_case_study_tag', {
                    defaultValue: 'We amplify it',
                  })}
                </span>
              </h3>
              <p className="mt-1 text-xs text-content-secondary leading-relaxed">
                {t('support.action_case_study_body', {
                  defaultValue:
                    'Show us how you use OpenConstructionERP - a video, a case study, a LinkedIn write-up. You can send us the link directly, or just tag @DataDrivenConstruction in your post - we will spot it and re-share through our newsletter and social channels, where tens of thousands of construction professionals and senior industry experts follow our work. Email for links: ',
                })}
                <span className="font-semibold text-purple-700 dark:text-purple-300">
                  {CASE_STUDY_EMAIL}
                </span>
                .
              </p>
            </div>
            <Mail
              size={14}
              className="shrink-0 mt-1 text-content-quaternary group-hover:text-purple-600 transition-colors"
              aria-hidden
            />
          </a>

          {/* 4. Fund development - donations keep the platform free */}
          <div
            className={clsx(
              'group rounded-xl border-2 p-4',
              'border-emerald-300/50 bg-gradient-to-br from-emerald-50/60 to-green-50/30',
              'dark:border-emerald-500/30 dark:from-emerald-950/30 dark:to-green-950/20',
            )}
          >
            <div className="flex items-start gap-3 mb-2">
              <div className="shrink-0 h-11 w-11 rounded-xl bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 flex items-center justify-center">
                <HandCoins size={20} strokeWidth={1.75} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm sm:text-base font-semibold text-content-primary">
                  {t('support.action_donate_title', {
                    defaultValue: 'Fund development',
                  })}
                </h3>
                <p className="mt-0.5 text-xs text-content-secondary leading-relaxed">
                  {t('support.action_donate_body', {
                    defaultValue:
                      'Donations keep OpenConstructionERP free and open for everyone. They fund new regional cost data, AI estimation and support for more CAD and file formats.',
                  })}
                </p>
                {/* Perk line - additive, inline-default only (do not fold into
                    action_donate_body above; that sentence is reconciled with
                    the rest of en.ts separately). Advertises the "Inside
                    track" backers-only panel this donation unlocks. */}
                <p className="mt-1.5 flex items-start gap-1.5 text-2xs font-medium text-emerald-700 dark:text-emerald-300">
                  <Sparkles size={12} className="mt-0.5 shrink-0" />
                  {t('support.donate_perk_line', {
                    defaultValue:
                      'Backers get a supporter access code that unlocks the Inside track panel - early word on what just shipped and a say in what gets built next.',
                  })}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 ml-14">
              <a
                href={PAYPAL_DONATE_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary hover:bg-emerald-50 hover:border-emerald-400 dark:hover:bg-emerald-950/40 transition-colors"
              >
                <Heart size={12} />
                {t('support.donate_paypal', { defaultValue: 'Donate with PayPal' })}
              </a>
              <a
                href={GITHUB_SPONSORS_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary hover:bg-emerald-50 hover:border-emerald-400 dark:hover:bg-emerald-950/40 transition-colors"
              >
                <Github size={12} />
                {t('support.donate_github', { defaultValue: 'Sponsor on GitHub' })}
              </a>
              <button
                type="button"
                onClick={() => {
                  onClose();
                  navigate('/inside');
                }}
                className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300/60 bg-emerald-50/60 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100 dark:border-emerald-500/30 dark:bg-emerald-950/30 dark:text-emerald-300 dark:hover:bg-emerald-900/40 transition-colors"
              >
                <Sparkles size={12} />
                {t('support.inside_track_link', { defaultValue: 'Backers inside track' })}
              </button>
            </div>
          </div>
        </div>

        {/* Thank-you footer */}
        <div className="mt-5 px-6 sm:px-8 py-4 border-t border-border-light bg-surface-secondary/40 rounded-b-2xl text-center">
          <p className="text-xs text-content-secondary leading-relaxed">
            {t('support.thanks', {
              defaultValue:
                'Thank you. Every star and every share genuinely keeps this project alive - built with ❤️ for the construction community.',
            })}
          </p>
          <button
            type="button"
            onClick={() => {
              onClose();
              navigate('/about#community');
            }}
            className="group mt-2.5 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 dark:text-amber-300 dark:hover:text-amber-200 transition-colors"
          >
            <Users size={13} strokeWidth={2} />
            {t('support.see_contributors', {
              defaultValue: 'See who is already building it with us',
            })}
            <ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" />
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(panel, document.body);
}
