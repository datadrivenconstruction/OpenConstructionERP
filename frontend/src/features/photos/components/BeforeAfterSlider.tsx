// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Two photos of the same spot, one over the other, split by a draggable handle.

import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { AuthImage } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import type { ArchivePhoto } from '../api';
import { sliderKeyStep, sliderPercent } from '../model';

interface BeforeAfterSliderProps {
  before: ArchivePhoto;
  after: ArchivePhoto;
  initial?: number;
}

export function BeforeAfterSlider({ before, after, initial = 50 }: BeforeAfterSliderProps) {
  const { t } = useTranslation();
  const [pct, setPct] = useState(initial);
  const box = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  const moveTo = useCallback((clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (rect) setPct(sliderPercent(clientX, rect.left, rect.width));
  }, []);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    moveTo(e.clientX);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (dragging.current) moveTo(e.clientX);
  };
  const onPointerUp = () => {
    dragging.current = false;
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = sliderKeyStep(e.key, pct);
    if (next !== null) {
      e.preventDefault();
      setPct(next);
    }
  };

  return (
    <figure className="space-y-2">
      <div
        ref={box}
        className="relative w-full select-none overflow-hidden rounded-lg bg-surface-secondary aspect-[4/3] touch-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        data-testid="before-after"
      >
        <AuthImage src={after.file_url} alt={after.caption || after.filename} className="absolute inset-0 h-full w-full object-cover" />
        <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - pct}% 0 0)` }} data-testid="before-layer">
          <AuthImage src={before.file_url} alt={before.caption || before.filename} className="h-full w-full object-cover" />
        </div>
        <div
          role="slider"
          tabIndex={0}
          aria-label={t('photoArchive.compare.slider')}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          onKeyDown={onKeyDown}
          className="absolute inset-y-0 w-1 -translate-x-1/2 cursor-ew-resize bg-white shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          style={{ left: `${pct}%` }}
        >
          <span className="absolute top-1/2 left-1/2 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white text-xs font-semibold text-content-primary shadow">
            ↔
          </span>
        </div>
        <span className="absolute left-2 top-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">
          {t('photoArchive.compare.before')}
        </span>
        <span className="absolute right-2 top-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">
          {t('photoArchive.compare.after')}
        </span>
      </div>
      <figcaption className="flex justify-between text-xs text-content-secondary">
        <span>{before.taken_at ? <DateDisplay value={before.taken_at} /> : t('photoArchive.undated')}</span>
        <span>{after.taken_at ? <DateDisplay value={after.taken_at} /> : t('photoArchive.undated')}</span>
      </figcaption>
    </figure>
  );
}
