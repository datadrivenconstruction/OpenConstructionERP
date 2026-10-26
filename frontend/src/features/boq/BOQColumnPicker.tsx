// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Toolbar popover on the bill itself: show or hide columns and move them up or
 * down. Personal and kept on this device; the first open shows today's grid.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Eye, EyeOff, RotateCcw, SlidersHorizontal } from 'lucide-react';
import {
  BOQ_ALWAYS_SHOWN,
  BOQ_HIDDEN_BY_DEFAULT,
  BOQ_PICKER_COLUMNS,
  boqColumnPref,
  isDefaultBoqColumnPrefs,
  orderEntries,
} from './grid/columnPrefs';

export function BOQColumnPicker({
  customColumns = [],
}: {
  customColumns?: { name: string; display_name: string }[];
}) {
  const { t } = useTranslation();
  const prefs = boqColumnPref.use();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const title = t('boq.columns_picker_title', { defaultValue: 'Show and order columns' });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const entries = useMemo(
    () =>
      orderEntries(
        [
          ...BOQ_PICKER_COLUMNS.map((c) => ({ id: c.id as string, label: t(c.labelKey, { defaultValue: c.fallback }) })),
          ...customColumns.map((c) => ({ id: `custom_${c.name}`, label: c.display_name })),
        ],
        prefs,
      ),
    [customColumns, prefs, t],
  );

  const isShown = (id: string) => prefs.visible[id] ?? !BOQ_HIDDEN_BY_DEFAULT.has(id);

  const toggle = (id: string) => {
    const next = !isShown(id);
    const visible = { ...prefs.visible };
    // A choice equal to the grid default is not stored, so "reset" and "never touched" agree.
    if (next === !BOQ_HIDDEN_BY_DEFAULT.has(id)) delete visible[id];
    else visible[id] = next;
    boqColumnPref.write({ ...prefs, visible });
  };

  const move = (id: string, delta: -1 | 1) => {
    const ids = entries.map((e) => e.id);
    const from = ids.indexOf(id);
    const to = from + delta;
    if (to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to]!, ids[from]!];
    boqColumnPref.write({ ...prefs, order: ids });
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title={title}
        aria-label={title}
        aria-expanded={open}
        data-testid="boq-column-picker-button"
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors ${
          open || !isDefaultBoqColumnPrefs(prefs)
            ? 'bg-oe-blue/10 text-oe-blue hover:bg-oe-blue/15'
            : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary'
        }`}
      >
        <SlidersHorizontal size={15} />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={title}
          className="absolute right-0 top-full z-30 mt-1 w-64 rounded-lg border border-border bg-surface-elevated p-2 shadow-lg"
        >
          <ul className="flex flex-col">
            {entries.map((e, i) => {
              const locked = (BOQ_ALWAYS_SHOWN as readonly string[]).includes(e.id);
              const shown = isShown(e.id);
              return (
                <li key={e.id} className="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-surface-secondary">
                  <button
                    type="button"
                    disabled={locked}
                    onClick={() => toggle(e.id)}
                    aria-pressed={shown}
                    aria-label={t('boq.column_show', { defaultValue: 'Show {{column}}', column: e.label })}
                    className="flex h-6 w-6 items-center justify-center rounded text-content-secondary disabled:opacity-40"
                  >
                    {shown ? <Eye size={14} /> : <EyeOff size={14} />}
                  </button>
                  <span className={`min-w-0 flex-1 truncate text-sm ${shown ? 'text-content-primary' : 'text-content-tertiary'}`}>
                    {e.label}
                  </span>
                  <button
                    type="button"
                    disabled={i === 0}
                    onClick={() => move(e.id, -1)}
                    aria-label={t('boq.column_move_up', { defaultValue: 'Move {{column}} left', column: e.label })}
                    className="flex h-6 w-6 items-center justify-center rounded text-content-secondary hover:bg-surface-tertiary disabled:opacity-30"
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    type="button"
                    disabled={i === entries.length - 1}
                    onClick={() => move(e.id, 1)}
                    aria-label={t('boq.column_move_down', { defaultValue: 'Move {{column}} right', column: e.label })}
                    className="flex h-6 w-6 items-center justify-center rounded text-content-secondary hover:bg-surface-tertiary disabled:opacity-30"
                  >
                    <ArrowDown size={14} />
                  </button>
                </li>
              );
            })}
          </ul>
          <button
            type="button"
            disabled={isDefaultBoqColumnPrefs(prefs)}
            onClick={() => boqColumnPref.reset()}
            className="mt-1 flex w-full items-center justify-center gap-1.5 rounded px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          >
            <RotateCcw size={12} />
            {t('boq.columns_picker_reset', { defaultValue: 'Reset to default' })}
          </button>
        </div>
      )}
    </div>
  );
}
