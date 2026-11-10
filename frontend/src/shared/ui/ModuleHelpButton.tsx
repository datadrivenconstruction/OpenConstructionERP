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
 * Visual identity: a standard secondary Button like every header control;
 * the Compass icon (vs the guide's GraduationCap) tells the two apart.
 *
 * Mobile collapse: on `sm` and below the label hides and only the
 * Compass icon shows — the button stays accessible via aria-label.
 */

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Compass } from 'lucide-react';

import { Button } from './Button';
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
    <Button
      variant="secondary"
      onClick={handleClick}
      data-testid={`module-help-button-${tourId}`}
      aria-label={aria}
      title={aria}
      className={className}
      icon={<Compass size={16} strokeWidth={2} className="text-oe-blue" />}
    >
      <span className="hidden sm:inline">{label}</span>
    </Button>
  );
}
