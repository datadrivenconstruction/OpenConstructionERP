// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** A single numbered PDF pin overlay anchored at (anchor_x, anchor_y).
 *
 * Coordinates are normalized to ``[0, 1]`` of the overlay container's
 * bounding box. The pin is rendered as an absolutely-positioned chip
 * — the parent (PdfWithComments) supplies the relative wrapper.
 */

import { type CSSProperties, type MouseEvent } from 'react';
import clsx from 'clsx';

export interface PdfMarkupPinProps {
  number: number;
  anchorX: number;
  anchorY: number;
  resolved?: boolean;
  active?: boolean;
  ariaLabel?: string;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
}

export function PdfMarkupPin({
  number,
  anchorX,
  anchorY,
  resolved = false,
  active = false,
  ariaLabel,
  onClick,
}: PdfMarkupPinProps) {
  // Coerce out-of-bounds anchors back into the canvas so a stray
  // legacy value can't render the pin off-screen.
  const x = Math.max(0, Math.min(1, anchorX));
  const y = Math.max(0, Math.min(1, anchorY));

  const style: CSSProperties = {
    left: `${x * 100}%`,
    top: `${y * 100}%`,
    transform: 'translate(-50%, -100%)',
  };

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel ?? `Comment pin ${number}`}
      style={style}
      className={clsx(
        'pointer-events-auto absolute flex h-6 min-w-[24px] items-center justify-center rounded-full px-1.5 text-xs font-semibold shadow-md ring-2 ring-white transition-transform',
        resolved
          ? 'bg-semantic-success text-white opacity-70'
          : 'bg-oe-blue text-white',
        active && 'scale-110 ring-oe-blue/40',
      )}
      data-testid={`pdf-pin-${number}`}
    >
      {number}
    </button>
  );
}
