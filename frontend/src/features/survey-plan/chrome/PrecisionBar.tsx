// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Precision input of the draw and measure tools: bearing + distance, dE/dN,
 * absolute E/N, or polar from a station and backsight. Enter places the vertex,
 * Tab moves between fields, the mode button (or Alt+M) switches mode.
 */

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { CornerDownLeft } from 'lucide-react';
import { emptyFields, fieldOrder, nextMode, parsePrecision } from '../engine/precisionInput';
import { axisLabelFor } from '../units/linear';
import type { GridXY, InputMode, PrecisionContext, PrecisionFields } from '../types';

const MODE_LABEL: Record<InputMode, [string, string]> = {
  brg_dist: ['plan.input.mode_brg_dist', 'Bearing + distance'],
  delta: ['plan.input.mode_delta', 'Offset'],
  abs: ['plan.input.mode_abs', 'Coordinates'],
  polar: ['plan.input.mode_polar', 'Polar'],
};

interface Props {
  ctx: PrecisionContext;
  onPoint: (p: GridXY) => void;
  /** Bump to move focus into the first field (the canvas does it on a typed digit). */
  focusToken: number;
}

export function PrecisionBar({ ctx, onPoint, focusToken }: Props) {
  const { t } = useTranslation();
  const [fields, setFields] = useState<PrecisionFields>(() => emptyFields(ctx.last ? 'brg_dist' : 'abs'));
  const [error, setError] = useState<{ field: string; text: string } | null>(null);
  const refs = useRef<Record<string, HTMLInputElement | null>>({});
  const order = fieldOrder(fields.mode);

  useEffect(() => {
    if (focusToken > 0) refs.current[order[0]!]?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusToken]);

  const ax = axisLabelFor(ctx.conventions.axis);
  const firstIsE = ctx.conventions.axis === 'EN' || ctx.conventions.axis === 'YX';
  const [a1, a2] = firstIsE ? [ax.e, ax.n] : [ax.n, ax.e];
  const label = (name: string): string => {
    switch (name) {
      case 'bearing':
        return t('plan.input.bearing', { defaultValue: 'Bearing' });
      case 'distance':
        return t('plan.input.distance', { defaultValue: 'Distance' });
      case 'first':
        return fields.mode === 'delta' ? `Δ${a1}` : a1;
      case 'second':
        return fields.mode === 'delta' ? `Δ${a2}` : a2;
      case 'z':
        return t('plan.input.height', { defaultValue: 'Height' });
      case 'station':
        return t('plan.input.station', { defaultValue: 'Station' });
      case 'backsight':
        return t('plan.input.backsight', { defaultValue: 'Backsight' });
      case 'angle':
        return t('plan.input.angle', { defaultValue: 'Angle' });
      default:
        return name;
    }
  };

  const setMode = (mode: InputMode) => {
    setFields(emptyFields(mode));
    setError(null);
  };

  const commit = () => {
    const r = parsePrecision(fields, ctx);
    if (!r.ok) {
      setError({ field: r.field, text: t(r.errorKey, { defaultValue: r.defaultError }) });
      refs.current[r.field]?.focus();
      return;
    }
    setError(null);
    onPoint(r.point);
    // Keep the bearing for the next leg of a traverse-like entry, clear the rest.
    setFields((f) => (f.mode === 'brg_dist' ? { ...f, distance: '' } : emptyFields(f.mode)));
    refs.current[order[0]!]?.focus();
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    e.stopPropagation();
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    } else if (e.key === 'Escape') {
      (e.target as HTMLInputElement).blur();
    } else if (e.altKey && e.code === 'KeyM') {
      e.preventDefault();
      setMode(nextMode(fields.mode));
    }
  };

  return (
    <form
      className="flex shrink-0 flex-nowrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        commit();
      }}
      aria-label={t('plan.input.title', { defaultValue: 'Type a point' })}
      data-testid="plan-precision"
    >
      <button
        type="button"
        onClick={() => setMode(nextMode(fields.mode))}
        className="h-8 rounded-md border border-border-light px-2 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
        title={t('plan.input.mode_hint', { defaultValue: 'Switch input mode (Alt+M)' })}
        data-testid="plan-precision-mode"
      >
        {t(MODE_LABEL[fields.mode][0], { defaultValue: MODE_LABEL[fields.mode][1] })}
      </button>
      {order.map((name) => (
        <label key={name} className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs text-content-tertiary">
          <span>{label(name)}</span>
          <input
            ref={(el) => {
              refs.current[name] = el;
            }}
            value={(fields as unknown as Record<string, string>)[name] ?? ''}
            onChange={(e) => setFields({ ...fields, [name]: e.target.value } as PrecisionFields)}
            onKeyDown={onKey}
            inputMode={name === 'bearing' || name === 'angle' || name === 'backsight' || name === 'station' ? 'text' : 'decimal'}
            dir="ltr"
            aria-invalid={error?.field === name}
            data-testid={`plan-precision-${name}`}
            className={`w-24 rounded-md border bg-surface-primary px-2 py-1 font-mono text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue ${
              error?.field === name ? 'border-semantic-error' : 'border-border-light'
            }`}
          />
        </label>
      ))}
      <button
        type="submit"
        className="inline-flex h-8 items-center gap-1 rounded-md bg-oe-blue px-2 text-xs font-medium text-content-inverse hover:bg-oe-blue-hover"
        data-testid="plan-precision-add"
      >
        <CornerDownLeft size={12} aria-hidden />
        {t('plan.input.add', { defaultValue: 'Add point' })}
      </button>
      {error && (
        <span role="alert" ref={(el) => el?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })} className="whitespace-nowrap text-xs text-semantic-error">
          {error.text}
        </span>
      )}
    </form>
  );
}
