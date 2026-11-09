// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Drag handle on the inner edge of the expanded sidebar. Dragging or the arrow
 * keys write the same width preference as the slider in Settings. The handle
 * sits on the end edge, so it follows the sidebar to the other side in RTL.
 */
import { useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_WIDTH_STEP,
  useSidebarPrefsStore,
} from '@/stores/useSidebarPrefsStore';

export function SidebarResizeHandle({ rtl }: { rtl: boolean }) {
  const { t } = useTranslation();
  const width = useSidebarPrefsStore((s) => s.width);
  const setWidth = useSidebarPrefsStore((s) => s.setWidth);
  const resetWidth = useSidebarPrefsStore((s) => s.resetWidth);
  const dragging = useRef(false);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    const rect = e.currentTarget.parentElement?.getBoundingClientRect();
    if (!rect) return;
    setWidth(rtl ? rect.right - e.clientX : e.clientX - rect.left);
  };
  const stop = (e: PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    // The arrow that points away from the panel makes it wider.
    const grow = rtl ? 'ArrowLeft' : 'ArrowRight';
    const shrink = rtl ? 'ArrowRight' : 'ArrowLeft';
    const big = e.shiftKey ? 4 : 1;
    if (e.key === grow) setWidth(width + SIDEBAR_WIDTH_STEP * big);
    else if (e.key === shrink) setWidth(width - SIDEBAR_WIDTH_STEP * big);
    else if (e.key === 'Home') setWidth(SIDEBAR_MIN_WIDTH);
    else if (e.key === 'End') setWidth(SIDEBAR_MAX_WIDTH);
    else return;
    e.preventDefault();
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t('sidebar.resize_handle', { defaultValue: 'Resize the menu' })}
      aria-valuemin={SIDEBAR_MIN_WIDTH}
      aria-valuemax={SIDEBAR_MAX_WIDTH}
      aria-valuenow={width}
      tabIndex={0}
      data-testid="sidebar-resize-handle"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      onDoubleClick={resetWidth}
      onKeyDown={onKeyDown}
      className="absolute inset-y-0 end-0 z-20 hidden w-1.5 cursor-col-resize touch-none transition-colors hover:bg-oe-blue/30 focus-visible:bg-oe-blue/40 focus-visible:outline-none active:bg-oe-blue/40 lg:block"
    />
  );
}
