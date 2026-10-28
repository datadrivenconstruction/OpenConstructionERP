// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Text display control for the DXF viewer: hide all drawing text, or draw it
 * smaller or larger than the drawing asks for.
 *
 * A dense sheet carries more annotation than geometry, and the annotation is
 * drawn on top. An estimator tracing a wall needs the wall, not the room
 * schedule sitting over it - so the first control is a plain on/off, reachable
 * in one click while the measuring tool stays selected. The size control is
 * the softer version of the same wish, for sheets where the labels are worth
 * keeping but not at the size they were authored at.
 *
 * Display only. The entities are unchanged, so measurement, selection, the
 * layer roster and the auto-quantify totals read the same drawing whichever
 * way this is set.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Eye, EyeOff, Minus, Plus, RotateCcw } from 'lucide-react';
import type { TextDisplayState } from '../lib/text-display-store';
import {
  DEFAULT_TEXT_DISPLAY,
  MAX_TEXT_SCALE,
  MIN_TEXT_SCALE,
  stepTextScale,
} from '../lib/text-display-store';

interface Props {
  value: TextDisplayState;
  onChange: (next: TextDisplayState) => void;
}

export function TextDisplayControl({ value, onChange }: Props) {
  const { t } = useTranslation();
  const { visible, scale } = value;
  const percent = Math.round(scale * 100);
  const isDefault = visible && scale === DEFAULT_TEXT_DISPLAY.scale;

  const btn = 'flex h-7 w-7 items-center justify-center rounded-md transition-colors';
  const enabled = 'text-slate-800 hover:bg-slate-100';
  const disabled = 'text-slate-300 cursor-not-allowed';

  return (
    <div
      className="flex items-center gap-1 rounded-lg border border-white/60 bg-white/85 dark:bg-white/90 backdrop-blur-md px-1.5 py-1 shadow-xl shadow-black/30 ring-1 ring-black/5"
      data-testid="dwg-text-display"
    >
      <button
        type="button"
        onClick={() => onChange({ ...value, visible: !visible })}
        data-testid="dwg-text-toggle"
        title={
          visible
            ? t('dwg_takeoff.text_hide', { defaultValue: 'Hide all drawing text' })
            : t('dwg_takeoff.text_show', { defaultValue: 'Show drawing text' })
        }
        aria-pressed={!visible}
        className={clsx(
          'flex h-7 items-center gap-1 rounded-md px-2 text-xs transition-colors',
          visible ? 'text-slate-700 hover:bg-slate-100' : 'bg-emerald-500/20 text-emerald-700',
        )}
      >
        {visible ? <Eye size={13} /> : <EyeOff size={13} />}
        <span className="font-semibold">
          {t('dwg_takeoff.text_toggle_label', { defaultValue: 'Text' })}
        </span>
      </button>

      <div className="mx-1 h-5 w-px bg-slate-300" />

      <button
        type="button"
        onClick={() => onChange({ ...value, scale: stepTextScale(scale, -1) })}
        disabled={!visible || scale <= MIN_TEXT_SCALE}
        data-testid="dwg-text-smaller"
        title={t('dwg_takeoff.text_smaller', { defaultValue: 'Smaller text' })}
        aria-label={t('dwg_takeoff.text_smaller', { defaultValue: 'Smaller text' })}
        className={clsx(btn, !visible || scale <= MIN_TEXT_SCALE ? disabled : enabled)}
      >
        <Minus size={14} />
      </button>

      <span
        data-testid="dwg-text-size"
        className={clsx(
          'w-10 text-center text-[11px] font-semibold tabular-nums',
          visible ? 'text-slate-700' : 'text-slate-300',
        )}
      >
        {t('dwg_takeoff.text_size_percent', { defaultValue: '{{percent}}%', percent })}
      </span>

      <button
        type="button"
        onClick={() => onChange({ ...value, scale: stepTextScale(scale, 1) })}
        disabled={!visible || scale >= MAX_TEXT_SCALE}
        data-testid="dwg-text-larger"
        title={t('dwg_takeoff.text_larger', { defaultValue: 'Larger text' })}
        aria-label={t('dwg_takeoff.text_larger', { defaultValue: 'Larger text' })}
        className={clsx(btn, !visible || scale >= MAX_TEXT_SCALE ? disabled : enabled)}
      >
        <Plus size={14} />
      </button>

      {/* Back to the drawing's own text, shown, at its authored size. One
          click from anywhere the two controls can get to, including hidden. */}
      <button
        type="button"
        onClick={() => onChange({ ...DEFAULT_TEXT_DISPLAY })}
        disabled={isDefault}
        data-testid="dwg-text-reset"
        title={t('dwg_takeoff.text_reset', {
          defaultValue: 'Show text at the size the drawing asks for',
        })}
        aria-label={t('dwg_takeoff.text_reset', {
          defaultValue: 'Show text at the size the drawing asks for',
        })}
        className={clsx(btn, isDefault ? disabled : enabled)}
      >
        <RotateCcw size={14} />
      </button>
    </div>
  );
}
