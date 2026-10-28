// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SignaturePad — lightweight canvas signature capture for field reports.
 *
 * Produces a PNG data URI (image/png base64) which is exactly what the
 * backend's signature_data validator accepts. No external dependency: a
 * plain <canvas> with pointer events keeps the bundle lean per the
 * "lightweight & simple" principle.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eraser, PenLine } from 'lucide-react';

export function SignaturePad({
  value,
  onChange,
  disabled = false,
}: {
  /** Existing PNG data URI (when editing a report that already has one). */
  value: string | null;
  onChange: (dataUri: string | null) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawingRef = useRef(false);
  const lastRef = useRef<{ x: number; y: number } | null>(null);
  const [hasInk, setHasInk] = useState(false);

  // If we open an existing report with a stored signature, show it.
  const [showStored, setShowStored] = useState<boolean>(!!value);

  const getCtx = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#111827';
    return ctx;
  }, []);

  const pointFromEvent = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  }, []);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (disabled) return;
      e.preventDefault();
      drawingRef.current = true;
      lastRef.current = pointFromEvent(e);
      canvasRef.current?.setPointerCapture(e.pointerId);
    },
    [disabled, pointFromEvent],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current || disabled) return;
      const ctx = getCtx();
      const last = lastRef.current;
      if (!ctx || !last) return;
      const pt = pointFromEvent(e);
      ctx.beginPath();
      ctx.moveTo(last.x, last.y);
      ctx.lineTo(pt.x, pt.y);
      ctx.stroke();
      lastRef.current = pt;
      if (!hasInk) setHasInk(true);
    },
    [disabled, getCtx, pointFromEvent, hasInk],
  );

  const commit = useCallback(() => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    lastRef.current = null;
    const canvas = canvasRef.current;
    if (canvas && hasInk) {
      onChange(canvas.toDataURL('image/png'));
    }
  }, [hasInk, onChange]);

  const handleClear = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = getCtx();
    if (canvas && ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    setHasInk(false);
    setShowStored(false);
    onChange(null);
  }, [getCtx, onChange]);

  // Keep the backing store crisp on first mount.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (canvas.width === 0) {
      canvas.width = 600;
      canvas.height = 160;
    }
  }, []);

  if (showStored && value) {
    return (
      <div className="w-full space-y-2">
        <img
          src={value}
          alt={t('fieldreports.signature', { defaultValue: 'Signature' })}
          className="max-h-40 w-full rounded-lg border border-border-light bg-white object-contain"
        />
        {!disabled && (
          <button
            type="button"
            onClick={handleClear}
            className="flex items-center gap-1.5 text-xs text-content-secondary hover:text-semantic-error"
          >
            <Eraser size={13} />
            {t('fieldreports.signature_clear', { defaultValue: 'Clear signature' })}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="w-full space-y-2">
      <canvas
        ref={canvasRef}
        width={600}
        height={160}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={commit}
        onPointerLeave={commit}
        className="h-40 w-full touch-none rounded-lg border border-dashed border-border-light bg-white"
        aria-label={t('fieldreports.signature', { defaultValue: 'Signature' })}
      />
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs text-content-tertiary">
          <PenLine size={13} />
          {t('fieldreports.signature_hint', {
            defaultValue: 'Draw the site representative signature above.',
          })}
        </span>
        {!disabled && (
          <button
            type="button"
            onClick={handleClear}
            className="flex items-center gap-1.5 text-xs text-content-secondary hover:text-semantic-error"
          >
            <Eraser size={13} />
            {t('fieldreports.signature_clear', { defaultValue: 'Clear' })}
          </button>
        )}
      </div>
    </div>
  );
}
