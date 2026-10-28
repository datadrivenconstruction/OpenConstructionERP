// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ModuleGuideButton — small pill that opens the module's "How it works"
// guide. Designed to sit immediately next to the existing ModuleHelpButton
// (the Tour button) so the two read as a deliberate pair on a module header.
//
// Visual identity: this guide button is BLUE with a GraduationCap icon and
// reads as the substantive "learn how this works" action (a little more
// prominent than its neighbour); the sibling Tour button (ModuleHelpButton)
// is violet with a Compass icon and reads as a quick walkthrough. Distinct
// hue and icon so the two are never confused, same size and pill geometry so
// they line up.
//
// Mobile collapse: on `sm` and below the label hides and only the icon
// shows, matching ModuleHelpButton; the button stays accessible via
// aria-label.

import { lazy, Suspense, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { GraduationCap } from 'lucide-react';
import clsx from 'clsx';

import { ModuleGuide, type ModuleGuideContent } from './ModuleGuide';

// Lazy: the pill indexes every playbook, which must not ride in the entry chunk.
const ModuleCasesButton = lazy(() =>
  import('@/features/cases/ModuleCasesButton').then((m) => ({ default: m.ModuleCasesButton })),
);

export interface ModuleGuideButtonProps {
  /** The guide content to teach when the button is clicked. */
  content: ModuleGuideContent;
  /** Optional extra classes for layout-specific tweaks. */
  className?: string;
  /** Optional override for the button label. Defaults to "How it works". */
  label?: string;
  /** Optional handler for the guide's closing CTA (last card). When the
   *  content defines a `ctaKey`, the CTA button runs this then closes. */
  onCta?: () => void;
}

export function ModuleGuideButton({
  content,
  className,
  label,
  onCta,
}: ModuleGuideButtonProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const resolvedLabel = label ?? t('guide.button', { defaultValue: 'How it works' });
  const aria = t('guide.button_aria', {
    defaultValue: 'Learn how this module works',
  });

  return (
    <>
      {/* Sibling "Cases for this module" pill, sitting to the LEFT of the
          How-it-works button. It is route-derived and self-hides when no
          playbook touches the current module, so it costs nothing on pages
          without cases. */}
      <Suspense fallback={null}>
        <ModuleCasesButton />
      </Suspense>
      {/* The re-open control for a collapsed info block used to sit here, and
          now lives in the top bar beside the module name (founder 2026-08-07).
          It is not rendered in both places: two controls for one action drift
          apart, and the point of the move was that the control stops shifting
          around with the width of each page's action row. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="module-guide-button"
        aria-label={aria}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={aria}
        className={clsx(
          'inline-flex items-center gap-1.5 rounded-full',
          'border border-oe-blue/40 bg-oe-blue/10 hover:bg-oe-blue/20',
          'px-2.5 h-7 text-xs font-semibold text-oe-blue',
          'transition-colors focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
          className,
        )}
      >
        <GraduationCap size={13} strokeWidth={2} />
        <span className="hidden sm:inline">{resolvedLabel}</span>
      </button>

      <ModuleGuide
        open={open}
        onClose={() => setOpen(false)}
        content={content}
        onCta={onCta}
      />
    </>
  );
}
