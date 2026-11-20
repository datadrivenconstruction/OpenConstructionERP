// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Shortcut sheet of the plan canvas (?). */

import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import type { PlanTool } from '../types';

const KEYS: [string, string, string][] = [
  ['Enter', 'plan.keys.finish', 'Finish the shape'],
  ['Esc', 'plan.keys.cancel', 'Cancel the shape, then clear the selection'],
  ['Backspace', 'plan.keys.back', 'Remove the last vertex'],
  ['Delete', 'plan.keys.delete', 'Delete the selection'],
  ['Ctrl+Z', 'plan.keys.undo', 'Undo'],
  ['Ctrl+Shift+Z', 'plan.keys.redo', 'Redo'],
  ['Ctrl+S', 'plan.keys.save', 'Save'],
  ['Ctrl+A', 'plan.keys.select_all', 'Select all'],
  ['Ctrl+C', 'plan.keys.copy', 'Copy the measurement'],
  ['F3', 'plan.keys.snap', 'Snap on or off'],
  ['Alt', 'plan.keys.alt', 'Hold to place without snapping'],
  ['Space', 'plan.keys.space', 'Hold to pan'],
  ['0-9', 'plan.keys.type', 'Start typing a point'],
  ['Z', 'plan.keys.extents', 'Zoom to everything'],
  ['?', 'plan.keys.help', 'This sheet'],
];

export function ShortcutHelp({ tools, onClose }: { tools: PlanTool[]; onClose: () => void }) {
  const { t } = useTranslation();
  const rows: [string, string][] = [
    ...tools.filter((x) => x.shortcut).map((x) => [x.shortcut!, t(x.labelKey, { defaultValue: x.defaultLabel })] as [string, string]),
    ...KEYS.map(([k, key, d]) => [k, t(key, { defaultValue: d })] as [string, string]),
  ];
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('plan.keys.title', { defaultValue: 'Keyboard shortcuts' })}
      className="absolute inset-0 z-30 flex items-center justify-center bg-black/30 p-4"
      onClick={onClose}
      data-testid="plan-shortcuts"
    >
      <div className="max-h-full w-full max-w-lg overflow-y-auto rounded-xl bg-surface-elevated p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-content-primary">{t('plan.keys.title', { defaultValue: 'Keyboard shortcuts' })}</h2>
          <button type="button" onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded hover:bg-surface-secondary" aria-label={t('common.close', { defaultValue: 'Close' })}>
            <X size={16} aria-hidden />
          </button>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {rows.map(([k, label]) => (
            <div key={`${k}-${label}`} className="contents">
              <dt>
                <kbd className="rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 font-mono text-xs">{k}</kbd>
              </dt>
              <dd className="text-content-secondary">{label}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
