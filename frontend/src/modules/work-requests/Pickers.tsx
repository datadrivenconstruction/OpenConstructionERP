// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Searchable pickers, portalled to the body so a table row's transform
 * never traps them. One popover shape, three uses:
 *
 *   - PeoplePicker: users, single or multi, with the department's own
 *     members first;
 *   - ProjectPicker: the job list, code + name;
 *   - RequestPicker: another request on the same job (dependencies).
 *
 * Escape closes, Enter picks the highlighted row, arrows walk the list.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import './wr.css';

export interface PickOption {
  id: string;
  label: string;
  sub?: string;
  /** Rendered before the label (an avatar, a colour dot). */
  lead?: ReactNode;
}

export type PickAnchor = HTMLElement | { x: number; y: number } | null;

export interface PickerProps {
  /** An element to hang under, or a point (the cursor of a right-click). */
  anchor: PickAnchor;
  options: PickOption[];
  selected: string[];
  multi?: boolean;
  placeholder?: string;
  emptyText?: string;
  onChange: (ids: string[]) => void;
  onClose: () => void;
}

export function Picker({ anchor, options, selected, multi = false, placeholder, emptyText, onChange, onClose }: PickerProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState('');
  const [hi, setHi] = useState(0);
  const [picked, setPicked] = useState<string[]>(selected);

  const shown = useMemo(() => {
    const n = q.trim().toLowerCase();
    const list = n ? options.filter((o) => `${o.label} ${o.sub ?? ''}`.toLowerCase().includes(n)) : options;
    // Chosen ones first so a long multi-pick stays visible.
    return [...list].sort((a, b) => Number(picked.includes(b.id)) - Number(picked.includes(a.id)));
  }, [options, q, picked]);

  useEffect(() => setHi(0), [q]);

  useEffect(() => {
    const id = window.setTimeout(() => inputRef.current?.focus(), 20);
    return () => window.clearTimeout(id);
  }, []);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let x = window.innerWidth / 2 - 150;
    let y = window.innerHeight / 2 - 170;
    if (anchor instanceof HTMLElement) {
      const r = anchor.getBoundingClientRect();
      x = r.left;
      y = r.bottom + 4;
    } else if (anchor) {
      x = anchor.x;
      y = anchor.y;
    }
    el.style.left = `${Math.max(8, Math.min(x, window.innerWidth - el.offsetWidth - 8))}px`;
    el.style.top = `${Math.max(8, Math.min(y, window.innerHeight - el.offsetHeight - 8))}px`;
  }, [anchor, shown.length]);

  const commit = (ids: string[]) => {
    onChange(ids);
    onClose();
  };

  const toggle = (id: string) => {
    if (!multi) {
      commit([id]);
      return;
    }
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  };

  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (ref.current && e.target instanceof Node && ref.current.contains(e.target)) return;
      onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setHi((h) => Math.min(shown.length - 1, h + 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setHi((h) => Math.max(0, h - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const o = shown[hi];
        if (o) toggle(o.id);
        else if (multi) commit(picked);
      }
    };
    // Deferred so the click that opened the picker does not close it.
    const id = window.setTimeout(() => window.addEventListener('mousedown', away), 0);
    window.addEventListener('keydown', key, true);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener('mousedown', away);
      window.removeEventListener('keydown', key, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, hi, picked, multi]);

  return createPortal(
    <div ref={ref} className="wr-pop" role="dialog" aria-label={placeholder}>
      <input
        ref={inputRef}
        type="text"
        value={q}
        placeholder={placeholder ?? t('wr.pick_search', { defaultValue: 'Search…' })}
        onChange={(e) => setQ(e.target.value)}
        autoComplete="off"
      />
      <div className="list" role="listbox" aria-multiselectable={multi || undefined}>
        {shown.length === 0 && <div className="none">{emptyText ?? t('wr.pick_none', { defaultValue: 'Nothing matches.' })}</div>}
        {shown.map((o, i) => {
          const on = picked.includes(o.id);
          return (
            <button
              key={o.id}
              type="button"
              className="opt"
              role="option"
              aria-selected={i === hi}
              onMouseEnter={() => setHi(i)}
              onClick={() => toggle(o.id)}
            >
              <span className="tick" aria-hidden>
                {on ? '✓' : ''}
              </span>
              {o.lead}
              <span>{o.label}</span>
              {o.sub && <span className="sub">{o.sub}</span>}
            </button>
          );
        })}
      </div>
      {multi && (
        <div className="foot">
          <button type="button" className="wr-btn-quiet" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button type="button" className="wr-btn-quiet on" onClick={() => commit(picked)}>
            {t('wr.pick_apply', { defaultValue: 'Apply' })}
          </button>
        </div>
      )}
    </div>,
    document.body,
  );
}
