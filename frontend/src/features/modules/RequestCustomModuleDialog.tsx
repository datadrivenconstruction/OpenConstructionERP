// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RequestCustomModuleDialog — full-screen modal launched from the
// sidebar "Request a custom module" CTA.
//
// Design intent:
//   • Full viewport modal — NOT a sidebar-width drawer. Renders via a
//     fixed inset-0 backdrop so it lives above the entire app shell
//     (sidebar + topbar + page content). z-[1000] keeps it above the
//     z-30 sticky header and the z-50 page modals.
//   • Two large CTA cards, no inline form. The user picks an audience
//     and is routed to a hosted contact form on our marketing site,
//     where the actual lead-capture happens (richer fields, CRM
//     integration, follow-up email automation already wired up there).
//   • Visual hierarchy: hero icon + headline + subhead, then the two
//     option cards side-by-side, then a small bottom link to the
//     in-product developer guide for users who want to build it
//     themselves rather than ask us to.
//
// We deliberately do NOT post to /v1/feedback any more — the website
// contact forms are the canonical funnel and own the CRM hand-off.
// Keeping that contract here would mean we'd have to mirror every
// future website-form change in two places.

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import {
  X,
  Users,
  Lock,
  ArrowRight,
  ExternalLink,
  BookOpen,
  Boxes,
  Database,
  Plug,
  BarChart3,
} from 'lucide-react';
import ddcLogoUrl from '/brand/ddc-logo.webp';
import { Link } from 'react-router-dom';
import clsx from 'clsx';

interface Props {
  open: boolean;
  onClose: () => void;
}

// Hosted contact endpoints on the marketing site. The query string
// pre-fills the form's "Topic" field so the receiving team can route
// the lead without manual triage. ``utm_source`` lets analytics
// attribute conversions back to this in-app CTA so we can measure
// whether the popup pays for itself.
//
// 2026-05-13: pointed at openconstructionerp.com/contact (the canonical
// product marketing site, confirmed 200 with a real Contact page).
// The earlier-tried openconstructionerp.com / openestimate.io hosts are
// parked / 405 and dead-ended the buttons.
const URL_COMMUNITY =
  'https://openconstructionerp.com/contact?topic=module_proposal_public&utm_source=oe_app&utm_medium=sidebar_cta&utm_campaign=request_module';
const URL_PRIVATE =
  'https://openconstructionerp.com/contact?topic=module_proposal_private&utm_source=oe_app&utm_medium=sidebar_cta&utm_campaign=request_module_bespoke';

export function RequestCustomModuleDialog({ open, onClose }: Props) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);

  // ── Lifecycle ─────────────────────────────────────────────────────

  // Close on Escape — capture phase so we trap the key before any
  // child element (the underlying app shell may also listen).
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () =>
      document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose]);

  // Lock background scroll while the modal is open so a long page
  // doesn't peek behind the backdrop on tablet / small laptop screens.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Focus the first interactive control when the modal opens so
  // keyboard users land somewhere sensible immediately.
  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => {
      dialogRef.current
        ?.querySelector<HTMLElement>('a[data-firstfocus="true"]')
        ?.focus();
    }, 30);
    return () => window.clearTimeout(id);
  }, [open]);

  if (!open) return null;

  // ── Render ───────────────────────────────────────────────────────
  //
  // Portal to document.body. The Sidebar mounts this dialog inside its
  // own <aside> which has its own stacking context (e.g. when the
  // sidebar is animated via transform). Without the portal a child
  // ``position: fixed`` element is clipped to that stacking-context
  // bounding box — i.e. it ends up confined to the ~280px sidebar
  // width instead of filling the viewport. Portalling to <body> is
  // the canonical fix and matches our other top-level modals
  // (ConfirmDialog, FeedbackDialog).

  const panel = (
    <div
      className={clsx(
        'fixed inset-0 z-[1000] flex items-center justify-center p-3 sm:p-6 lg:p-10',
        // Backdrop sits BEHIND the inner panel — use bg here so the
        // entire app dims uniformly regardless of viewport size.
        'bg-black/45 backdrop-blur-[3px]',
      )}
      role="dialog"
      aria-modal="true"
      aria-labelledby="request-module-title"
      // Click on the dim background closes the dialog; clicks on the
      // panel itself stop-propagate so they don't bubble here.
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className={clsx(
          'relative w-full max-w-[1100px] max-h-[92vh] overflow-y-auto',
          'rounded-2xl bg-surface-primary shadow-2xl border border-border-light',
          'animate-card-in',
        )}
      >
        {/* Hero band — gradient backdrop + centred eyebrow + title.
            The decoration is purely aesthetic; aria-hidden so it
            doesn't pollute the accessibility tree. */}
        <div className="relative overflow-hidden rounded-t-2xl">
          <div
            aria-hidden
            className="absolute inset-0 bg-gradient-to-br from-purple-500/[0.10] via-indigo-500/[0.06] to-blue-500/[0.10] dark:from-purple-500/[0.18] dark:via-indigo-500/[0.12] dark:to-blue-500/[0.18]"
          />
          <div
            aria-hidden
            className="absolute -top-12 -right-10 w-72 h-72 rounded-full bg-purple-300/25 dark:bg-purple-500/15 blur-3xl"
          />
          <div
            aria-hidden
            className="absolute -bottom-16 -left-12 w-72 h-72 rounded-full bg-blue-300/25 dark:bg-blue-500/15 blur-3xl"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="absolute top-3 right-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={18} />
          </button>
          <div className="relative px-6 sm:px-10 py-8 sm:py-10 text-center">
            <div className="inline-flex h-20 w-20 sm:h-24 sm:w-24 items-center justify-center mb-4">
              <img
                src={ddcLogoUrl}
                alt="DataDrivenConstruction"
                className="max-h-full max-w-full object-contain"
                width="96"
                height="96"
              />
            </div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-purple-600 dark:text-purple-300 mb-2">
              {t('modules.request_eyebrow', {
                defaultValue: 'Missing a module?',
              })}
            </p>
            <h2
              id="request-module-title"
              className="text-2xl sm:text-3xl font-bold text-content-primary leading-tight"
            >
              {t('modules.request_hero_title', {
                defaultValue: 'Tell us what your team needs.',
              })}
            </h2>
            <p className="mt-3 mx-auto max-w-[640px] text-sm sm:text-base text-content-secondary leading-relaxed">
              {t('modules.request_hero_subtitle', {
                defaultValue:
                  'OpenConstructionERP runs on a plug-in architecture - every report, integration, regional catalogue and AI tool is its own module. If the one you need is missing, we will build it. Choose the path that fits your situation.',
              })}
            </p>
          </div>
        </div>

        {/* The two big choice cards. Each one is an anchor (NOT a
            button) so middle-click opens in a new tab and screen
            readers announce the destination, and target=_blank
            keeps the app open behind the user. */}
        <div className="px-6 sm:px-10 pt-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <a
            href={URL_COMMUNITY}
            target="_blank"
            rel="noopener noreferrer"
            data-firstfocus="true"
            onClick={onClose}
            className={clsx(
              'group relative overflow-hidden rounded-xl border-2 p-5 sm:p-6 flex flex-col gap-3',
              'border-oe-blue/30 bg-gradient-to-br from-oe-blue-subtle via-transparent to-blue-50/40',
              'dark:border-oe-blue/30 dark:from-oe-blue/10 dark:via-transparent dark:to-slate-900/30',
              'hover:border-oe-blue hover:shadow-lg hover:-translate-y-0.5 transition-all',
            )}
          >
            <div className="flex items-start gap-3">
              <div className="shrink-0 h-11 w-11 rounded-xl bg-oe-blue/10 text-oe-blue flex items-center justify-center group-hover:bg-oe-blue group-hover:text-white transition-colors">
                <Users size={22} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-base sm:text-lg font-semibold text-content-primary">
                  {t('modules.request_card_community_title', {
                    defaultValue: 'Could help other teams too',
                  })}
                </h3>
                <p className="mt-1 text-xs text-content-tertiary uppercase tracking-wider font-semibold">
                  {t('modules.request_card_community_tag', {
                    defaultValue: 'Open-source · free for everyone',
                  })}
                </p>
              </div>
            </div>
            <p className="text-sm text-content-secondary leading-relaxed">
              {t('modules.request_card_community_body', {
                defaultValue:
                  'We add your idea to the public roadmap. If it has broad demand we ship it in a future release of OpenConstructionERP - included in every user’s install, including yours, at no cost.',
              })}
            </p>
            <ul className="space-y-1.5 text-xs text-content-secondary">
              <li className="flex items-start gap-2">
                <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-oe-blue shrink-0" />
                {t('modules.request_card_community_bullet1', {
                  defaultValue:
                    'Free - ships in the next public release if accepted.',
                })}
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-oe-blue shrink-0" />
                {t('modules.request_card_community_bullet2', {
                  defaultValue:
                    'Public GitHub thread - other teams can upvote, refine and contribute.',
                })}
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-oe-blue shrink-0" />
                {t('modules.request_card_community_bullet3', {
                  defaultValue:
                    'Best for regional standards, integrations, reports and AI tools that are universal.',
                })}
              </li>
            </ul>
            <div className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-oe-blue group-hover:gap-3 transition-all">
              {t('modules.request_card_community_cta', {
                defaultValue: 'Propose on our roadmap',
              })}
              <ArrowRight size={16} />
            </div>
            <ExternalLink
              size={14}
              className="absolute top-4 right-4 text-content-quaternary group-hover:text-oe-blue transition-colors"
              aria-hidden
            />
          </a>

          <a
            href={URL_PRIVATE}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onClose}
            className={clsx(
              'group relative overflow-hidden rounded-xl border-2 p-5 sm:p-6 flex flex-col gap-3',
              'border-purple-300/50 bg-gradient-to-br from-purple-50/80 via-transparent to-fuchsia-50/40',
              'dark:border-purple-500/30 dark:from-purple-950/30 dark:via-transparent dark:to-slate-900/30',
              'hover:border-purple-500 hover:shadow-lg hover:-translate-y-0.5 transition-all',
            )}
          >
            <div className="flex items-start gap-3">
              <div className="shrink-0 h-11 w-11 rounded-xl bg-purple-500/10 text-purple-600 dark:text-purple-300 flex items-center justify-center group-hover:bg-purple-600 group-hover:text-white transition-colors">
                <Lock size={22} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-base sm:text-lg font-semibold text-content-primary">
                  {t('modules.request_card_private_title', {
                    defaultValue: 'Built just for our company',
                  })}
                </h3>
                <p className="mt-1 text-xs text-content-tertiary uppercase tracking-wider font-semibold">
                  {t('modules.request_card_private_tag', {
                    defaultValue: 'Bespoke · custom delivery',
                  })}
                </p>
              </div>
            </div>
            <p className="text-sm text-content-secondary leading-relaxed">
              {t('modules.request_card_private_body', {
                defaultValue:
                  'For workflows specific to your business - internal naming, proprietary cost data, ERP integrations, restricted security. We design, build, deploy and maintain the module privately for your team.',
              })}
            </p>
            <ul className="space-y-1.5 text-xs text-content-secondary">
              <li className="flex items-start gap-2">
                <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-purple-500 shrink-0" />
                {t('modules.request_card_private_bullet1', {
                  defaultValue:
                    'Fixed-scope quote within 2 business days.',
                })}
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-purple-500 shrink-0" />
                {t('modules.request_card_private_bullet2', {
                  defaultValue:
                    'Closed-source, deployed only to your install, signed by your team.',
                })}
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-purple-500 shrink-0" />
                {t('modules.request_card_private_bullet3', {
                  defaultValue:
                    'Maintenance + SLA included - works seamlessly with each ERP release.',
                })}
              </li>
            </ul>
            <div className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-purple-700 dark:text-purple-300 group-hover:gap-3 transition-all">
              {t('modules.request_card_private_cta', {
                defaultValue: 'Request a scope & quote',
              })}
              <ArrowRight size={16} />
            </div>
            <ExternalLink
              size={14}
              className="absolute top-4 right-4 text-content-quaternary group-hover:text-purple-600 transition-colors"
              aria-hidden
            />
          </a>
        </div>

        {/* Category chips — a quick visual cue about what kinds of
            modules are commonly requested. Pure decoration. */}
        <div className="px-6 sm:px-10 pt-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3 text-center">
            {t('modules.request_examples_label', {
              defaultValue: 'Examples of what users ask for',
            })}
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            {[
              {
                icon: Database,
                key: 'modules.request_chip_data',
                fallback: 'Regional cost catalogues',
              },
              {
                icon: Plug,
                key: 'modules.request_chip_integration',
                fallback: 'ERP, construction management and scheduling integrations',
              },
              {
                icon: BarChart3,
                key: 'modules.request_chip_analytics',
                fallback: 'Bespoke dashboards & KPI reports',
              },
              {
                icon: Boxes,
                key: 'modules.request_chip_tools',
                fallback: 'Custom estimation tools & AI agents',
              },
            ].map((it) => (
              <span
                key={it.key}
                className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-secondary/60 px-3 py-1 text-2xs text-content-secondary"
              >
                <it.icon size={11} className="text-content-tertiary" />
                {t(it.key, { defaultValue: it.fallback })}
              </span>
            ))}
          </div>
        </div>

        {/* Footer — third option: build it yourself. We route to the
            in-app developer guide, NOT the marketing site, so users
            who are coders keep their flow inside the product. */}
        <div className="mt-6 sm:mt-7 px-6 sm:px-10 py-4 border-t border-border-light bg-surface-secondary/30 rounded-b-2xl flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-content-tertiary leading-relaxed max-w-[560px]">
            {t('modules.request_footer_diy', {
              defaultValue:
                'Prefer to build it yourself? Every module is a small Python package - the developer guide walks through it end-to-end in under an hour.',
            })}
          </p>
          <Link
            to="/modules/developer-guide"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue hover:border-oe-blue transition-colors"
          >
            <BookOpen size={12} />
            {t('modules.request_footer_diy_cta', {
              defaultValue: 'Open developer guide',
            })}
          </Link>
        </div>
      </div>
    </div>
  );

  // Portal target: document.body — escapes any ancestor stacking
  // context (notably the sidebar's transform / overflow rules) so the
  // backdrop genuinely fills the entire viewport rather than being
  // clipped to the 280-px sidebar width.
  return createPortal(panel, document.body);
}
