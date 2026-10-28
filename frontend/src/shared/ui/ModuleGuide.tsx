// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ModuleGuide — a "How it works" explainer overlay that sits NEXT TO the
// per-module Tour button.
//
// Why it exists: the ProductTour walks a user through UI surfaces ("this
// button does X, that grid does Y") with a spotlight coachmark. It is great
// for orientation but it does not TEACH the module. ModuleGuide is the
// complement: a focused, card-by-card explainer of the module's core
// concepts plus how to actually enter and fill in data. Think of the Tour
// as "where things are" and the Guide as "what this is and how to use it".
//
// Shape:
//   * Driven entirely by a serialisable `ModuleGuideContent` object (title +
//     optional intro + ordered sections + optional closing CTA). Each
//     section carries an i18n key WITH an inline English default so callers
//     never have to touch en.ts or any locale file — the inline-defaultValue
//     pattern used across the codebase. Translators pick the keys up later.
//   * Renders ONE explanatory card at a time with prev / next, progress
//     dots, a closing CTA on the last card, Esc to close, Left / Right arrow
//     navigation, a focus trap and full aria labelling.
//   * Optional spotlight: when a section sets `spotlightSelector` the
//     backdrop punches a soft cutout over the matching on-screen element
//     using the same box-shadow technique as ProductTour, so the Guide can
//     literally point at the field it is describing while still explaining
//     the concept. Sections without a selector render a centred,
//     fully-dimmed modal.
//
// Styling: glass-morphism card on a dimmed backdrop, brand-blue accents,
// theme tokens (surface-elevated / content-* / border-*) so it is correct
// in both light and dark mode. The spotlight scrim + accent ring swap their
// inline rgba values on theme change exactly like ProductTour does, because
// Tailwind's `dark:` prefix cannot reach the dynamic inline box-shadow.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import {
  X,
  ArrowLeft,
  ArrowRight,
  GraduationCap,
  Sparkles,
  Lightbulb,
  BookOpen,
  ListChecks,
  Database,
  Layers,
  Workflow,
  PencilLine,
  Rocket,
  Search,
  FileSearch,
  ClipboardCheck,
  Send,
  type LucideProps,
} from 'lucide-react';
import clsx from 'clsx';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { useIsRTL } from '@/shared/hooks/useIsRTL';
import {
  useSpotlightTarget,
  SpotlightScrim,
  TOOLTIP_W,
  type TooltipPosition,
} from './spotlight';

/* ── Content model ──────────────────────────────────────────────────────── */

/**
 * One explanatory card in a module guide.
 *
 * `titleKey` / `bodyKey` are i18n keys; `titleDefault` / `bodyDefault` are
 * the inline English fallbacks passed straight to `t(key, { defaultValue })`.
 * DO NOT add the keys to en.ts or any locale file — the inline default IS
 * the English copy, and translators fill the other locales later.
 *
 * `icon` is the name of a lucide-react icon (e.g. `'Database'`,
 * `'PencilLine'`). Unknown / omitted names fall back to a sensible default
 * so a typo never crashes the card. See ICON_MAP for the supported set.
 *
 * `spotlightSelector` is an optional CSS selector for an on-screen element
 * this card explains. When present and the element is visible, the backdrop
 * punches a soft cutout over it so the Guide can point at the exact field /
 * panel it is describing. Prefer stable `[data-testid="..."]` selectors so
 * the highlight survives styling churn.
 */
export interface ModuleGuideSection {
  /** Optional lucide-react icon name. Falls back to a default when unknown. */
  icon?: string;
  /** i18n key for the section title. */
  titleKey: string;
  /** Inline English default for the section title. */
  titleDefault: string;
  /** i18n key for the section body copy. */
  bodyKey: string;
  /** Inline English default for the section body copy. */
  bodyDefault: string;
  /** Optional CSS selector to spotlight while this card is shown. */
  spotlightSelector?: string;
  /** Preferred side for the card relative to the spotlit element. Defaults to
   *  'bottom'; the placement logic falls back to a side that fits. */
  spotlightPosition?: TooltipPosition;
  /** When the target lives inside a collapsible sidebar group that is
   *  collapsed by default, set this to the group id so the guide can ask the
   *  Sidebar to expand it before measuring (dispatches `oe:tour-reveal`). */
  revealGroupId?: string;
}

/**
 * A complete "How it works" guide for one module.
 *
 * Build one of these per module (co-located with the feature, e.g.
 * `frontend/src/features/boq/boqGuide.ts`) and pass it to
 * `<ModuleGuideButton content={boqGuide} />` placed next to the module's
 * `<ModuleHelpButton .../>`.
 */
export interface ModuleGuideContent {
  /** i18n key for the guide title (header of every card). */
  titleKey: string;
  /** Inline English default for the guide title. */
  titleDefault: string;
  /** Optional i18n key for an intro shown on the first card, above the
   *  section grid of cards. */
  introKey?: string;
  /** Inline English default for the intro. */
  introDefault?: string;
  /** Ordered explanatory cards. At least one is required for the guide to
   *  render; an empty list renders nothing. */
  sections: ModuleGuideSection[];
  /** Optional i18n key for the closing call-to-action label shown on the
   *  final card (e.g. "Add your first position"). When omitted the final
   *  card shows a plain "Got it" finish button. */
  ctaKey?: string;
  /** Inline English default for the closing CTA label. */
  ctaDefault?: string;
}

/* ── Icon resolution ────────────────────────────────────────────────────── */

/**
 * Named lucide icons a guide section may reference by string. Kept to a
 * curated, teaching-oriented set so the bundle does not pull the entire
 * icon pack and so authors get a predictable palette. Unknown names fall
 * back to `Lightbulb`.
 */
const ICON_MAP: Record<string, ComponentType<LucideProps>> = {
  Lightbulb,
  BookOpen,
  GraduationCap,
  Sparkles,
  ListChecks,
  Database,
  Layers,
  Workflow,
  PencilLine,
  Rocket,
  Search,
  FileSearch,
  ClipboardCheck,
  Send,
};

function iconFor(name: string | undefined): ComponentType<LucideProps> {
  if (name && name in ICON_MAP) return ICON_MAP[name]!;
  return Lightbulb;
}

/* ── Component ──────────────────────────────────────────────────────────── */

export interface ModuleGuideProps {
  /** Whether the overlay is open. */
  open: boolean;
  /** Close handler — fired by the X button, backdrop click, Esc, and the
   *  finish / CTA button on the last card. */
  onClose: () => void;
  /** The guide content to render. */
  content: ModuleGuideContent;
  /** Optional click handler for the closing CTA button. When provided the
   *  CTA closes the guide AND runs this (e.g. open the "Add position"
   *  modal). When omitted the CTA simply closes the guide. */
  onCta?: () => void;
}

export function ModuleGuide({ open, onClose, content, onCta }: ModuleGuideProps) {
  const { t } = useTranslation();
  const cardRef = useRef<HTMLDivElement>(null);

  const sections = content.sections;
  const total = sections.length;

  const [index, setIndex] = useState(0);

  // Track theme so the spotlight scrim + accent ring (inline rgba, outside
  // Tailwind's reach) can swap to high-contrast dark values.
  const [isDark, setIsDark] = useState<boolean>(() =>
    typeof document !== 'undefined'
      ? document.documentElement.classList.contains('dark')
      : false,
  );
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains('dark'));
    sync();
    const mo = new MutationObserver(sync);
    mo.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => mo.disconnect();
  }, []);

  // Reset to the first card every time the guide is (re)opened.
  useEffect(() => {
    if (open) setIndex(0);
  }, [open]);

  const isFirst = index === 0;
  const isLast = index === total - 1;
  const section = sections[index];
  const isRTL = useIsRTL();

  /* ── Spotlight target: anchor the card beside the section's element ────── */
  // When the section sets no spotlightSelector (the common case for most
  // guides) the hook reports no rect and we render the centred fallback card
  // below — zero regression for the many guides that spotlight nothing.
  const { rect: spotlight, tooltipCoords } = useSpotlightTarget(
    section?.spotlightSelector,
    {
      preferredPosition: section?.spotlightPosition,
      revealGroupId: section?.revealGroupId,
      active: open,
      rtl: isRTL,
    },
  );

  /* ── Navigation ───────────────────────────────────────────────────────── */
  const goNext = useCallback(() => {
    setIndex((i) => (i + 1 < total ? i + 1 : i));
  }, [total]);

  const goPrev = useCallback(() => {
    setIndex((i) => (i > 0 ? i - 1 : i));
  }, []);

  const finish = useCallback(() => {
    onClose();
    if (onCta) onCta();
  }, [onClose, onCta]);

  /* ── Keyboard: Esc closes, Left/Right navigate ────────────────────────── */
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      // Arrow direction mirrors in RTL: the "forward" key is Left and "back"
      // is Right, matching how the layout reads.
      const forwardKey = isRTL ? 'ArrowLeft' : 'ArrowRight';
      const backKey = isRTL ? 'ArrowRight' : 'ArrowLeft';
      if (e.key === forwardKey) {
        e.preventDefault();
        if (isLast) finish();
        else goNext();
        return;
      }
      if (e.key === backKey) {
        e.preventDefault();
        goPrev();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, isLast, isRTL, finish, goNext, goPrev, onClose]);

  /* ── Body scroll lock while open ──────────────────────────────────────── */
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Focus trap inside the card (hook is a no-op while inactive).
  useFocusTrap(cardRef, open);

  /* ── Resolved strings ─────────────────────────────────────────────────── */
  const guideTitle = t(content.titleKey, { defaultValue: content.titleDefault });
  const intro = useMemo(() => {
    if (!content.introKey || !content.introDefault) return null;
    return t(content.introKey, { defaultValue: content.introDefault });
  }, [content.introKey, content.introDefault, t]);

  if (!open || total === 0 || !section) return null;

  const SectionIcon = iconFor(section.icon);
  const sectionTitle = t(section.titleKey, { defaultValue: section.titleDefault });
  const sectionBody = t(section.bodyKey, { defaultValue: section.bodyDefault });

  const ctaLabel =
    content.ctaKey && content.ctaDefault
      ? t(content.ctaKey, { defaultValue: content.ctaDefault })
      : t('guide.finish', { defaultValue: 'Got it' });

  const counter = t('guide.step_counter', {
    defaultValue: 'Concept {{current}} of {{total}}',
    current: index + 1,
    total,
  });

  const closeLabel = t('guide.close', { defaultValue: 'Close guide' });
  const prevLabel = t('guide.back', { defaultValue: 'Back' });
  const nextLabel = t('guide.next', { defaultValue: 'Next' });

  const overlay = (
    <div
      data-module-guide="root"
      className="fixed inset-0 z-[9200]"
      role="presentation"
    >
      {/* Backdrop. With a spotlight we punch a soft cutout via box-shadow on
          a transparent div positioned over the target; without one we render
          a plain dimmed scrim. Clicking the backdrop closes the guide. */}
      {spotlight ? (
        <>
          <button
            type="button"
            aria-label={closeLabel}
            onClick={onClose}
            className="absolute inset-0 cursor-default focus:outline-none"
            data-testid="module-guide-backdrop"
            tabIndex={-1}
          />
          <SpotlightScrim
            rect={spotlight}
            accent="blue"
            isDark={isDark}
            testId="module-guide-spotlight"
          />
        </>
      ) : (
        <button
          type="button"
          aria-label={closeLabel}
          onClick={onClose}
          data-testid="module-guide-backdrop"
          tabIndex={-1}
          className={clsx(
            'absolute inset-0 cursor-default focus:outline-none',
            'bg-black/45 dark:bg-black/75 backdrop-blur-sm',
            'animate-fade-in',
          )}
        />
      )}

      {/* The explanatory card. With a spotlight we anchor the card beside the
          highlighted element (placeTooltip picks a side that fits and keeps
          it clear of the cutout); with no spotlight we centre it — the
          zero-regression fallback the majority of guides still use. */}
      <div
        className={clsx(
          'pointer-events-none fixed inset-0',
          !spotlight && 'flex items-center justify-center p-4 sm:p-6',
        )}
      >
        <div
          ref={cardRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="module-guide-title"
          data-testid="module-guide-card"
          style={
            spotlight
              ? {
                  position: 'fixed',
                  top: tooltipCoords.top,
                  left: tooltipCoords.left,
                  width: TOOLTIP_W,
                }
              : undefined
          }
          className={clsx(
            'pointer-events-auto relative',
            spotlight ? 'max-w-[92vw]' : 'w-full max-w-md',
            'rounded-2xl border glass-strong shadow-2xl',
            'border-border-light dark:border-sky-400/50',
            'dark:shadow-[0_12px_48px_rgba(2,6,23,0.65),0_0_0_1px_rgba(125,211,252,0.18)]',
            'animate-scale-in',
          )}
        >
          {/* Accent top hairline for a polished, modern edge. */}
          <div
            aria-hidden="true"
            className="absolute inset-x-0 top-0 h-1 rounded-t-2xl bg-gradient-to-r from-oe-blue/0 via-oe-blue/70 to-oe-blue/0"
          />

          <div className="p-5 sm:p-6">
            {/* Header: teaching badge + guide title + close. */}
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span
                  className={clsx(
                    'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl',
                    'bg-oe-blue/10 text-oe-blue ring-1 ring-inset ring-oe-blue/20',
                  )}
                  aria-hidden="true"
                >
                  <GraduationCap size={17} strokeWidth={2} />
                </span>
                <div className="min-w-0">
                  <p className="text-2xs font-semibold uppercase tracking-wide text-oe-blue">
                    {t('guide.eyebrow', { defaultValue: 'How it works' })}
                  </p>
                  <h2
                    id="module-guide-title"
                    className="truncate text-sm font-semibold leading-snug text-content-primary"
                  >
                    {guideTitle}
                  </h2>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                data-testid="module-guide-close"
                aria-label={closeLabel}
                title={closeLabel}
                className={clsx(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
                  'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
                  'transition-colors focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                )}
              >
                <X size={15} />
              </button>
            </div>

            {/* Intro — only on the first card, when provided. */}
            {isFirst && intro && (
              <p className="mb-4 rounded-xl bg-oe-blue/5 px-3.5 py-2.5 text-xs leading-relaxed text-content-secondary ring-1 ring-inset ring-oe-blue/10">
                {intro}
              </p>
            )}

            {/* The concept card body. */}
            <div className="flex items-start gap-3.5">
              <span
                className={clsx(
                  'mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
                  'bg-gradient-to-br from-oe-blue/15 to-oe-blue/5 text-oe-blue',
                  'ring-1 ring-inset ring-oe-blue/15',
                )}
                aria-hidden="true"
              >
                <SectionIcon size={19} strokeWidth={2} />
              </span>
              <div className="min-w-0">
                <h3 className="mb-1.5 text-[15px] font-semibold leading-snug text-content-primary">
                  {sectionTitle}
                </h3>
                <p className="text-[13px] leading-relaxed text-content-secondary">
                  {sectionBody}
                </p>
              </div>
            </div>

            {/* Footer: counter + dots + navigation. */}
            <div className="mt-6 flex items-center justify-between gap-3">
              <span
                data-testid="module-guide-counter"
                className="hidden text-2xs font-medium tabular-nums text-content-tertiary sm:inline"
              >
                {counter}
              </span>

              <div className="mx-auto flex items-center gap-1.5" aria-hidden="true">
                {sections.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setIndex(i)}
                    className={clsx(
                      'rounded-full transition-all duration-150',
                      i === index
                        ? 'h-2 w-5 bg-oe-blue'
                        : 'h-2 w-2 bg-border hover:bg-oe-blue/40',
                    )}
                    tabIndex={-1}
                  />
                ))}
              </div>

              <div className="flex items-center gap-1.5">
                {!isFirst && (
                  <button
                    type="button"
                    onClick={goPrev}
                    data-testid="module-guide-back"
                    aria-label={prevLabel}
                    className={clsx(
                      'flex h-8 items-center gap-1 rounded-lg border px-2.5 text-xs',
                      'border-border text-content-secondary',
                      'hover:bg-surface-secondary hover:text-content-primary',
                      'transition-colors focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                    )}
                  >
                    <ArrowLeft size={13} />
                    <span className="hidden sm:inline">{prevLabel}</span>
                  </button>
                )}
                {isLast ? (
                  <button
                    type="button"
                    onClick={finish}
                    data-testid="module-guide-finish"
                    className={clsx(
                      'flex h-8 items-center gap-1.5 rounded-lg px-3.5 text-xs font-medium',
                      'bg-oe-blue text-white hover:opacity-90 active:opacity-80',
                      'transition-opacity focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                    )}
                  >
                    {onCta && <Rocket size={13} />}
                    {ctaLabel}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={goNext}
                    data-testid="module-guide-next"
                    aria-label={nextLabel}
                    className={clsx(
                      'flex h-8 items-center gap-1.5 rounded-lg px-3.5 text-xs font-medium',
                      'bg-oe-blue text-white hover:opacity-90 active:opacity-80',
                      'transition-opacity focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                    )}
                  >
                    {nextLabel}
                    <ArrowRight size={13} />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
