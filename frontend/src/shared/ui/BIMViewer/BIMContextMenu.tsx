/**
 * BIMContextMenu -- floating context menu for right-clicking elements in the
 * 3D BIM viewer.  Supports single-element and multi-element selections.
 *
 * Positioned at the mouse cursor (position: fixed).  Closes on click outside,
 * Escape, or scroll.  All strings go through t() with defaultValue -- no
 * hardcoded English.
 */

import { useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ZoomIn,
  Clipboard,
  Plus,
  Ruler,
  Paperclip,
  CalendarPlus,
  ListTodo,
  Eye,
  EyeOff,
  Palette,
  SlidersHorizontal,
  Search,
} from 'lucide-react';
import type { BIMElementData } from './ElementManager';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface BIMContextMenuState {
  x: number;
  y: number;
  /** The element directly under the cursor (may be null if right-clicking
   *  empty space with a multi-selection active). */
  element: BIMElementData | null;
  /** All currently selected elements. */
  selectedElements: BIMElementData[];
}

export interface BIMContextMenuActions {
  onZoomToElement?: () => void;
  onCopyProperties?: () => void;
  onAddToBOQ?: () => void;
  onCreateQuantityRule?: () => void;
  onLinkDocument?: () => void;
  onLinkActivity?: () => void;
  onCreateTask?: () => void;
  onIsolate?: () => void;
  onHide?: () => void;
  onColorByCategory?: () => void;
  onShowInFilterPanel?: () => void;
  onShowSimilar?: () => void;
}

interface BIMContextMenuProps {
  menu: BIMContextMenuState;
  actions: BIMContextMenuActions;
  onClose: () => void;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

/** Summarise selected elements by category for the multi-select header. */
function categorySummary(elements: BIMElementData[]): string {
  const counts = new Map<string, number>();
  for (const el of elements) {
    const cat = el.element_type || 'Unknown';
    counts.set(cat, (counts.get(cat) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([cat, n]) => `${cat} (${n})`)
    .join(', ');
}

/** Format a volume / area number for the header line. */
function fmtQty(el: BIMElementData): string | null {
  const q = el.quantities;
  if (!q) return null;
  const vol = q['volume'] ?? q['Volume'];
  if (typeof vol === 'number' && vol > 0) {
    return `${vol.toLocaleString(undefined, { maximumFractionDigits: 2 })} m\u00B3`;
  }
  const area = q['area'] ?? q['Area'];
  if (typeof area === 'number' && area > 0) {
    return `${area.toLocaleString(undefined, { maximumFractionDigits: 2 })} m\u00B2`;
  }
  const len = q['length'] ?? q['Length'];
  if (typeof len === 'number' && len > 0) {
    return `${len.toLocaleString(undefined, { maximumFractionDigits: 2 })} m`;
  }
  return null;
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function BIMContextMenu({ menu, actions, onClose }: BIMContextMenuProps) {
  const { t } = useTranslation();
  const menuRef = useRef<HTMLDivElement>(null);

  const isMulti = menu.selectedElements.length > 1;
  const count = menu.selectedElements.length;

  // Close on click outside
  const handleClickOutside = useCallback(
    (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    },
    [onClose],
  );

  // Close on Escape
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose],
  );

  // Close on scroll
  const handleScroll = useCallback(() => onClose(), [onClose]);

  useEffect(() => {
    // Use capture so we catch the event before other click handlers
    document.addEventListener('mousedown', handleClickOutside, true);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside, true);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [handleClickOutside, handleKeyDown, handleScroll]);

  // Clamp position so menu stays within viewport
  const style = useMenuPosition(menu.x, menu.y, menuRef);

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[220px] max-w-[300px] rounded-lg bg-surface-primary border border-border-light shadow-xl backdrop-blur-sm overflow-hidden"
      style={style}
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-border-light bg-surface-secondary/60">
        {isMulti ? (
          <>
            <div className="text-xs font-bold text-content-primary">
              {t('bim.ctx_multi_header', {
                defaultValue: '{{count}} elements selected',
                count,
              })}
            </div>
            <div className="text-[10px] text-content-tertiary truncate mt-0.5">
              {categorySummary(menu.selectedElements)}
            </div>
          </>
        ) : menu.element ? (
          <>
            <div className="text-xs font-bold text-content-primary truncate">
              {menu.element.name || menu.element.element_type}
            </div>
            <div className="text-[10px] text-content-tertiary truncate mt-0.5">
              {menu.element.element_type}
              {menu.element.storey && (
                <span className="mx-1">{menu.element.storey}</span>
              )}
              {(() => {
                const qty = fmtQty(menu.element!);
                return qty ? <span className="mx-1">{qty}</span> : null;
              })()}
            </div>
          </>
        ) : null}
      </div>

      {/* Action groups */}
      <div className="py-1">
        {/* Group 1: View */}
        {!isMulti && (
          <>
            <MenuItem
              icon={ZoomIn}
              label={t('bim.ctx_zoom', { defaultValue: 'Zoom to element' })}
              onClick={() => { actions.onZoomToElement?.(); onClose(); }}
            />
            <MenuItem
              icon={Clipboard}
              label={t('bim.ctx_copy_props', { defaultValue: 'Copy properties' })}
              onClick={() => { actions.onCopyProperties?.(); onClose(); }}
            />
            <MenuDivider />
          </>
        )}

        {/* Group 2: Linking */}
        <MenuItem
          icon={Plus}
          label={
            isMulti
              ? t('bim.ctx_add_n_boq', {
                  defaultValue: 'Add {{count}} to BOQ',
                  count,
                })
              : t('bim.ctx_add_boq', { defaultValue: 'Add to BOQ' })
          }
          onClick={() => { actions.onAddToBOQ?.(); onClose(); }}
        />
        {!isMulti && (
          <>
            <MenuItem
              icon={Ruler}
              label={t('bim.ctx_quantity_rule', { defaultValue: 'Create quantity rule' })}
              onClick={() => { actions.onCreateQuantityRule?.(); onClose(); }}
            />
            <MenuItem
              icon={Paperclip}
              label={t('bim.ctx_link_doc', { defaultValue: 'Link to document' })}
              onClick={() => { actions.onLinkDocument?.(); onClose(); }}
            />
            <MenuItem
              icon={CalendarPlus}
              label={t('bim.ctx_link_activity', { defaultValue: 'Link to schedule activity' })}
              onClick={() => { actions.onLinkActivity?.(); onClose(); }}
            />
            <MenuItem
              icon={ListTodo}
              label={t('bim.ctx_create_task', { defaultValue: 'Create task / issue' })}
              onClick={() => { actions.onCreateTask?.(); onClose(); }}
            />
          </>
        )}

        <MenuDivider />

        {/* Group 3: Visibility */}
        <MenuItem
          icon={Eye}
          label={
            isMulti
              ? t('bim.ctx_isolate_selection', { defaultValue: 'Isolate selection' })
              : t('bim.ctx_isolate', { defaultValue: 'Isolate (hide all others)' })
          }
          onClick={() => { actions.onIsolate?.(); onClose(); }}
        />
        <MenuItem
          icon={EyeOff}
          label={
            isMulti
              ? t('bim.ctx_hide_selection', { defaultValue: 'Hide selection' })
              : t('bim.ctx_hide', { defaultValue: 'Hide element' })
          }
          onClick={() => { actions.onHide?.(); onClose(); }}
        />
        <MenuItem
          icon={Palette}
          label={
            isMulti
              ? t('bim.ctx_color_selection', { defaultValue: 'Color selection' })
              : t('bim.ctx_color_category', { defaultValue: 'Color by category' })
          }
          onClick={() => { actions.onColorByCategory?.(); onClose(); }}
        />

        <MenuDivider />

        {/* Group 4: Navigation */}
        <MenuItem
          icon={SlidersHorizontal}
          label={t('bim.ctx_show_filter', { defaultValue: 'Show in filter panel' })}
          onClick={() => { actions.onShowInFilterPanel?.(); onClose(); }}
        />
        {!isMulti && (
          <MenuItem
            icon={Search}
            label={t('bim.ctx_show_similar', { defaultValue: 'Show similar elements' })}
            onClick={() => { actions.onShowSimilar?.(); onClose(); }}
          />
        )}
      </div>
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────────────── */

function MenuItem({
  icon: Icon,
  label,
  onClick,
  disabled = false,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-2.5 w-full px-3 py-1.5 text-xs text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors disabled:opacity-40 disabled:pointer-events-none"
    >
      <Icon size={13} className="shrink-0 text-content-tertiary" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function MenuDivider() {
  return <div className="my-1 mx-2 border-t border-border-light" />;
}

/* ── Position hook ────────────────────────────────────────────────────── */

/** Compute fixed position, clamping to viewport edges. */
function useMenuPosition(
  x: number,
  y: number,
  ref: React.RefObject<HTMLDivElement | null>,
): React.CSSProperties {
  // Start at the cursor; after mount we read the actual size and clamp.
  // For the first render we just use the raw position, which is good enough
  // since the menu is small and React will repaint almost instantly.
  const padding = 8;
  const vw = typeof window !== 'undefined' ? window.innerWidth : 1920;
  const vh = typeof window !== 'undefined' ? window.innerHeight : 1080;

  let left = x;
  let top = y;

  // Use ref dimensions if available (second render onwards)
  const el = ref.current;
  if (el) {
    const rect = el.getBoundingClientRect();
    if (left + rect.width + padding > vw) {
      left = vw - rect.width - padding;
    }
    if (top + rect.height + padding > vh) {
      top = vh - rect.height - padding;
    }
  } else {
    // First render estimate: assume 220px wide, 350px tall max
    if (left + 220 + padding > vw) left = vw - 220 - padding;
    if (top + 350 + padding > vh) top = vh - 350 - padding;
  }

  return { left: Math.max(padding, left), top: Math.max(padding, top) };
}
