// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ModuleHelpButton — small pill button surfaced on a module page header
 * that launches that module's guided tour.
 *
 * Pattern: one button per module page (BOQ Editor, BIM Hub, PropDev, …)
 * dispatches the existing `oe:start-tour` window event with a `tourId`
 * detail payload.  The single global ProductTour mounted at App root
 * picks up the event, swaps to the matching playlist from
 * TOUR_REGISTRY, and runs the spotlight walkthrough.
 *
 * Visual identity: the Tour is a quick, interactive walkthrough, so it uses a
 * VIOLET pill with a Compass icon - deliberately a different hue and icon
 * from the sibling "How it works" guide button (blue, GraduationCap), so the
 * two never read as the same control. Tour = "show me around the screen",
 * Guide = "explain how this module works".
 *
 * Mobile collapse: on `sm` and below the label hides and only the
 * Compass icon shows — the button stays accessible via aria-label.
 */

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Compass } from 'lucide-react';
import clsx from 'clsx';

import { TOUR_START_EVENT, type TourId } from './ProductTour';

export interface ModuleHelpButtonProps {
  /** Registered tour id to launch (must exist in TOUR_REGISTRY). */
  tourId: TourId;
  /** Optional extra classes for layout-specific tweaks. */
  className?: string;
}

export function ModuleHelpButton({ tourId, className }: ModuleHelpButtonProps) {
  const { t } = useTranslation();

  const handleClick = useCallback(() => {
    // Dispatch on window so the ProductTour listener (mounted at App
    // root) picks it up regardless of which module page is active.
    window.dispatchEvent(
      new CustomEvent(TOUR_START_EVENT, { detail: { tourId } }),
    );
  }, [tourId]);

  const label = t('module_help.tour_button', { defaultValue: 'Tour' });
  const aria = t('module_help.tour_aria', {
    defaultValue: 'Take a quick guided tour of this screen',
  });

  return (
    <button
      type="button"
      onClick={handleClick}
      data-testid={`module-help-button-${tourId}`}
      aria-label={aria}
      title={aria}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full',
        'border border-violet-300/70 bg-violet-50 hover:bg-violet-100',
        'dark:border-violet-700/50 dark:bg-violet-950/30 dark:hover:bg-violet-900/40',
        'px-2.5 h-7 text-xs font-medium text-violet-700 dark:text-violet-300',
        'transition-colors focus:outline-none focus:ring-2 focus:ring-violet-400/40',
        className,
      )}
    >
      <Compass size={13} strokeWidth={2} />
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}
