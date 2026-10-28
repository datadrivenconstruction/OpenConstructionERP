// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** PDF preview + transparent pin overlay.
 *
 * The PDF itself is rendered in a sandboxed iframe because the project
 * does not (yet) bundle ``react-pdf`` — keeping the dependency surface
 * small. A transparent ``<div>`` is positioned over the iframe to host
 * the pin chips at their normalized coordinates.
 *
 * Click-to-place
 * --------------
 * Clicking the overlay calls ``onPlacePin`` with normalized
 * ``(x, y)`` in ``[0, 1]``. Callers can suppress that side-effect by
 * leaving ``onPlacePin`` undefined (the overlay then only renders
 * existing pins).
 */

import { useCallback, useMemo, type MouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { PdfMarkupPin } from './PdfMarkupPin';
import { useFileCommentThreads } from './hooks';
import type {
  FileCommentThread as ThreadNode,
  FileKind,
} from './types';

export interface PdfWithCommentsProps {
  pdfUrl: string;
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  /** Page currently shown — pins are filtered by ``page_number``. */
  currentPage?: number;
  activeCommentId?: string | null;
  /** Called with normalized ``(x, y)`` when the overlay is clicked. */
  onPlacePin?: (x: number, y: number) => void;
  onPinClick?: (commentId: string) => void;
  className?: string;
}

interface FlatPin {
  commentId: string;
  anchorX: number;
  anchorY: number;
  resolved: boolean;
  pageNumber: number;
}

function flattenPins(threads: ThreadNode[], page: number): FlatPin[] {
  const out: FlatPin[] = [];
  const walk = (node: ThreadNode): void => {
    if (
      node.page_number !== null &&
      node.page_number === page &&
      typeof node.anchor_x === 'number' &&
      typeof node.anchor_y === 'number'
    ) {
      out.push({
        commentId: node.id,
        anchorX: node.anchor_x,
        anchorY: node.anchor_y,
        resolved: node.resolved,
        pageNumber: node.page_number,
      });
    }
    node.replies.forEach(walk);
  };
  threads.forEach(walk);
  // Stable order by (y, x) so the on-screen numbering is consistent.
  return out.sort((a, b) =>
    a.anchorY === b.anchorY ? a.anchorX - b.anchorX : a.anchorY - b.anchorY,
  );
}

export function PdfWithComments({
  pdfUrl,
  projectId,
  fileKind,
  fileId,
  currentPage = 1,
  activeCommentId = null,
  onPlacePin,
  onPinClick,
  className,
}: PdfWithCommentsProps) {
  const { t } = useTranslation();
  const args = { projectId, kind: fileKind, fileId };
  const { data } = useFileCommentThreads(args);
  const threads = data?.threads ?? [];

  const pins = useMemo(
    () => flattenPins(threads, currentPage),
    [threads, currentPage],
  );

  const handleOverlayClick = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (!onPlacePin) return;
      // Pins above the overlay get pointer events; clicks that bubble
      // here therefore landed on the background and should drop a new
      // pin.
      const rect = e.currentTarget.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      if (x < 0 || x > 1 || y < 0 || y > 1) return;
      onPlacePin(x, y);
    },
    [onPlacePin],
  );

  return (
    <div
      className={clsx(
        'relative h-full w-full overflow-hidden rounded-lg border border-border bg-surface-primary',
        className,
      )}
      data-testid="pdf-with-comments"
    >
      <iframe
        title={t('comments.pdf_iframe_title', {
          defaultValue: 'PDF preview with comment pins',
        })}
        src={pdfUrl}
        className="h-full w-full"
        // Pointer events on the iframe; the overlay above stays
        // transparent until the user moves above a pin or clicks the
        // empty canvas to drop one.
      />
      <div
        role={onPlacePin ? 'button' : 'presentation'}
        tabIndex={onPlacePin ? 0 : -1}
        onClick={handleOverlayClick}
        className={clsx(
          'absolute inset-0',
          onPlacePin ? 'cursor-crosshair' : 'pointer-events-none',
        )}
        data-testid="pdf-overlay"
      >
        {pins.map((pin, idx) => (
          <PdfMarkupPin
            key={pin.commentId}
            number={idx + 1}
            anchorX={pin.anchorX}
            anchorY={pin.anchorY}
            resolved={pin.resolved}
            active={activeCommentId === pin.commentId}
            ariaLabel={t('comments.pin_label', {
              defaultValue: 'Comment pin {{n}} on page {{page}}',
              n: idx + 1,
              page: pin.pageNumber,
            })}
            onClick={(e) => {
              e.stopPropagation();
              onPinClick?.(pin.commentId);
            }}
          />
        ))}
      </div>
    </div>
  );
}
