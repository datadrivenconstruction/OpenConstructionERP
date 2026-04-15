import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { X, ArrowLeft, ArrowRight, MapPin } from 'lucide-react';
import clsx from 'clsx';

/* ── Constants ──────────────────────────────────────────────────────────── */

export const ONBOARDING_STORAGE_KEY = 'oe_tour_completed';

/* ── Types ──────────────────────────────────────────────────────────────── */

export interface TourStep {
  target: string; // CSS selector
  title: string;
  description: string;
  position: 'top' | 'bottom' | 'left' | 'right';
}

interface TooltipCoords {
  top: number;
  left: number;
}

interface SpotlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/* ── Default tour steps ─────────────────────────────────────────────────── */

export const DEFAULT_TOUR_STEPS: TourStep[] = [
  {
    target: '[data-tour="sidebar"]',
    title: 'onboarding.step1.title',
    description: 'onboarding.step1.description',
    position: 'right',
  },
  {
    target: '[data-tour="projects"]',
    title: 'onboarding.step2.title',
    description: 'onboarding.step2.description',
    position: 'right',
  },
  {
    target: '[data-tour="boq"]',
    title: 'onboarding.step3.title',
    description: 'onboarding.step3.description',
    position: 'right',
  },
  {
    target: '[data-tour="costs"]',
    title: 'onboarding.step4.title',
    description: 'onboarding.step4.description',
    position: 'right',
  },
  {
    target: '[data-tour="mode-toggle"]',
    title: 'onboarding.step5.title',
    description: 'onboarding.step5.description',
    position: 'right',
  },
];

/* ── Default titles/descriptions (fallback values) ──────────────────────── */

const STEP_DEFAULTS: Record<string, { title: string; description: string }> = {
  'onboarding.step1.title': {
    title: 'Navigation Sidebar',
    description:
      'The sidebar gives you quick access to all modules: projects, estimates, cost databases, schedules, and more.',
  },
  'onboarding.step2.title': {
    title: 'Projects',
    description:
      'Start here by creating your first project. Each project holds BOQs, schedules, and documents in one place.',
  },
  'onboarding.step3.title': {
    title: 'Bill of Quantities',
    description:
      'Build detailed estimates with the BOQ editor — hierarchical positions, assemblies, and real-time cost roll-up.',
  },
  'onboarding.step4.title': {
    title: 'Cost Databases',
    description:
      'Browse and manage cost rate databases including the built-in CWICR with 55 000+ positions across 9 languages.',
  },
  'onboarding.step5.title': {
    title: 'Simple / Advanced Mode',
    description:
      'Toggle between Simple mode (essential tools) and Advanced mode (all features including tendering and scheduling).',
  },
};

/* ── Helpers ────────────────────────────────────────────────────────────── */

const TOOLTIP_OFFSET = 16; // px gap between spotlight and tooltip
const TOOLTIP_W = 320; // px — fixed tooltip width
const TOOLTIP_H = 180; // px — estimated tooltip height for pre-positioning

function getSpotlightRect(target: string): SpotlightRect | null {
  const el = document.querySelector(target);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  const PADDING = 8;
  return {
    top: rect.top - PADDING,
    left: rect.left - PADDING,
    width: rect.width + PADDING * 2,
    height: rect.height + PADDING * 2,
  };
}

function getTooltipCoords(
  spotlight: SpotlightRect,
  position: TourStep['position'],
): TooltipCoords {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let top: number;
  let left: number;

  switch (position) {
    case 'right':
      top = spotlight.top + spotlight.height / 2 - TOOLTIP_H / 2;
      left = spotlight.left + spotlight.width + TOOLTIP_OFFSET;
      break;
    case 'left':
      top = spotlight.top + spotlight.height / 2 - TOOLTIP_H / 2;
      left = spotlight.left - TOOLTIP_W - TOOLTIP_OFFSET;
      break;
    case 'top':
      top = spotlight.top - TOOLTIP_H - TOOLTIP_OFFSET;
      left = spotlight.left + spotlight.width / 2 - TOOLTIP_W / 2;
      break;
    case 'bottom':
    default:
      top = spotlight.top + spotlight.height + TOOLTIP_OFFSET;
      left = spotlight.left + spotlight.width / 2 - TOOLTIP_W / 2;
      break;
  }

  // Clamp within viewport with margin
  const MARGIN = 12;
  top = Math.max(MARGIN, Math.min(top, vh - TOOLTIP_H - MARGIN));
  left = Math.max(MARGIN, Math.min(left, vw - TOOLTIP_W - MARGIN));

  return { top, left };
}

/* ── Component ──────────────────────────────────────────────────────────── */

export interface OnboardingTourProps {
  steps?: TourStep[];
  /** Force-show even if already completed (for preview/reset) */
  forceShow?: boolean;
}

export function OnboardingTour({
  steps = DEFAULT_TOUR_STEPS,
  forceShow = false,
}: OnboardingTourProps) {
  const { t } = useTranslation();

  // Determine if tour should auto-start
  const shouldStart = forceShow || localStorage.getItem(ONBOARDING_STORAGE_KEY) === null;

  const [active, setActive] = useState(shouldStart);
  const [currentStep, setCurrentStep] = useState(0);
  const [spotlight, setSpotlight] = useState<SpotlightRect | null>(null);
  const [tooltipCoords, setTooltipCoords] = useState<TooltipCoords>({ top: 0, left: 0 });
  const tooltipRef = useRef<HTMLDivElement>(null);

  const step = steps[currentStep];
  const isFirst = currentStep === 0;
  const isLast = currentStep === steps.length - 1;
  const stepNumber = currentStep + 1;
  const totalSteps = steps.length;

  /* Mark complete and close */
  const completeTour = useCallback(() => {
    try {
      localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true');
    } catch {
      /* ignore storage errors */
    }
    setActive(false);
  }, []);

  /* Scroll to target and update spotlight/tooltip position */
  const positionForStep = useCallback(
    (stepIndex: number) => {
      const s = steps[stepIndex];
      if (!s) return;

      const el = document.querySelector(s.target);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
      }

      // Wait for scroll to settle, then measure
      setTimeout(() => {
        const rect = getSpotlightRect(s.target);
        setSpotlight(rect);

        if (rect) {
          setTooltipCoords(getTooltipCoords(rect, s.position));
        }
      }, 150);
    },
    [steps],
  );

  /* Reposition on window resize */
  useEffect(() => {
    if (!active) return;
    positionForStep(currentStep);

    const onResize = () => positionForStep(currentStep);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [active, currentStep, positionForStep]);

  /* Escape key handler */
  useEffect(() => {
    if (!active) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        completeTour();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [active, completeTour]);

  /* Navigation handlers */
  const handleNext = useCallback(() => {
    if (isLast) {
      completeTour();
    } else {
      const next = currentStep + 1;
      setCurrentStep(next);
      positionForStep(next);
    }
  }, [isLast, currentStep, completeTour, positionForStep]);

  const handlePrev = useCallback(() => {
    if (isFirst) return;
    const prev = currentStep - 1;
    setCurrentStep(prev);
    positionForStep(prev);
  }, [isFirst, currentStep, positionForStep]);

  const handleSkip = useCallback(() => {
    completeTour();
  }, [completeTour]);

  if (!active || !step) return null;

  /* ── Resolve i18n strings ── */
  const titleKey = step.title;
  const descKey = step.description;
  const defaults = STEP_DEFAULTS[titleKey];
  const resolvedTitle = t(titleKey, { defaultValue: defaults?.title ?? titleKey });
  const resolvedDesc = t(descKey, { defaultValue: defaults?.description ?? descKey });

  /* ── Spotlight box-shadow overlay ── */
  // The cutout is achieved with a large box-shadow on the highlight div.
  // We render an overlay covering the whole viewport and then a transparent
  // cutout div positioned over the target element.
  const SHADOW_SPREAD = 9999;

  return (
    <>
      {/* Fullscreen overlay with spotlight cutout — pointer-events-none
          so the tour does NOT block interaction with the underlying app. */}
      <div
        data-testid="onboarding-overlay"
        className="fixed inset-0 z-[9000] pointer-events-none"
        aria-hidden="true"
      >
        {spotlight && (
          <div
            data-testid="onboarding-spotlight"
            className="pointer-events-none"
            style={{
              position: 'fixed',
              top: spotlight.top,
              left: spotlight.left,
              width: spotlight.width,
              height: spotlight.height,
              boxShadow: `0 0 0 ${SHADOW_SPREAD}px rgba(0, 0, 0, 0.25)`,
              borderRadius: 8,
              zIndex: 9001,
              pointerEvents: 'none',
            }}
          />
        )}
      </div>

      {/* Tooltip card */}
      <div
        ref={tooltipRef}
        data-testid="onboarding-tooltip"
        role="dialog"
        aria-modal="false"
        aria-label={t('onboarding.tour_step', { defaultValue: 'Tour step' })}
        style={{
          position: 'fixed',
          top: tooltipCoords.top,
          left: tooltipCoords.left,
          width: TOOLTIP_W,
          zIndex: 9100,
        }}
        className={clsx(
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-lg',
          'p-5 pointer-events-auto',
          'animate-scale-in',
          // Position in bottom-right corner to avoid blocking main content
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-3">
          {/* Icon + title */}
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
              <MapPin size={15} />
            </div>
            <h3 className="text-sm font-semibold text-content-primary leading-snug">
              {resolvedTitle}
            </h3>
          </div>

          {/* Close / skip button */}
          <button
            type="button"
            onClick={handleSkip}
            data-testid="onboarding-skip"
            className={clsx(
              'shrink-0 flex h-6 w-6 items-center justify-center rounded-md',
              'text-content-tertiary hover:text-content-primary hover:bg-surface-secondary',
              'transition-colors',
            )}
            aria-label={t('onboarding.skip', { defaultValue: 'Skip tour' })}
          >
            <X size={14} />
          </button>
        </div>

        {/* Description */}
        <p className="text-xs text-content-secondary leading-relaxed mb-4">{resolvedDesc}</p>

        {/* Footer: step counter + navigation */}
        <div className="flex items-center justify-between gap-3">
          {/* Step counter */}
          <span
            data-testid="onboarding-step-counter"
            className="text-2xs font-medium text-content-tertiary tabular-nums"
          >
            {t('onboarding.step_label', { defaultValue: 'Step' })}
            {' '}
            {stepNumber}
            {' '}
            {t('onboarding.step_of_connector', { defaultValue: 'of' })}
            {' '}
            {totalSteps}
          </span>

          {/* Dot indicators */}
          <div className="flex items-center gap-1 mx-auto">
            {steps.map((_, idx) => (
              <div
                key={idx}
                className={clsx(
                  'rounded-full transition-all duration-150',
                  idx === currentStep
                    ? 'h-2 w-4 bg-oe-blue'
                    : 'h-1.5 w-1.5 bg-border',
                )}
              />
            ))}
          </div>

          {/* Prev / Next buttons */}
          <div className="flex items-center gap-1.5">
            {!isFirst && (
              <button
                type="button"
                onClick={handlePrev}
                data-testid="onboarding-prev"
                className={clsx(
                  'flex h-7 w-7 items-center justify-center rounded-lg',
                  'border border-border text-content-secondary',
                  'hover:bg-surface-secondary hover:text-content-primary',
                  'transition-colors',
                )}
                aria-label={t('onboarding.previous', { defaultValue: 'Previous step' })}
              >
                <ArrowLeft size={13} />
              </button>
            )}
            <button
              type="button"
              onClick={handleNext}
              data-testid="onboarding-next"
              className={clsx(
                'flex h-7 items-center gap-1.5 rounded-lg px-3',
                'bg-oe-blue text-white text-xs font-medium',
                'hover:opacity-90 active:opacity-80 transition-opacity',
              )}
              aria-label={
                isLast
                  ? t('onboarding.finish', { defaultValue: 'Finish tour' })
                  : t('onboarding.next', { defaultValue: 'Next step' })
              }
            >
              {isLast
                ? t('onboarding.finish', { defaultValue: 'Finish' })
                : t('onboarding.next', { defaultValue: 'Next' })}
              {!isLast && <ArrowRight size={13} />}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
