// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Right-click context menu — the workspace's fast lane.
 *
 * One component, positioned at the cursor (or under a button, see
 * `menuAt`), closed by any click outside it, a scroll, or Escape. Items
 * are plain actions; a separator is `null`. Following the Team Standup
 * board's menu: an optional uppercase heading, a colour dot before the
 * label, a muted mono note on the right, and — for a long list — a
 * filter box under the heading.
 *
 * `useMenu()` is the one-line way to own a menu: it returns the element
 * to render and `openFromEvent` / `openBelow` to open it. Text fields
 * keep the browser's own menu so copy/paste still works there.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import type { LucideIcon } from 'lucide-react';
import './ci.css';

export interface MenuItem {
  label: string;
  icon?: LucideIcon;
  danger?: boolean;
  /** Muted mono text on the right — an owner, a hint, a count. */
  note?: string;
  /** A 10px rounded dot before the label; any CSS colour. */
  color?: string;
  disabled?: boolean;
  /** A group label rather than an action. Hidden while a filter is typed. */
  heading?: boolean;
  /** Always shown, whatever the filter says — "Type your own…" must stay reachable. */
  sticky?: boolean;
  onClick: () => void;
}

export interface MenuOptions {
  /** Small uppercase heading row. */
  head?: string;
  /** Placeholder for a filter box under the heading; set it for a long list. */
  search?: string;
}

/** Where a dropdown opens: the element's bottom-left corner. */
export function menuAt(el: HTMLElement): { x: number; y: number } {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.bottom + 4 };
}

/** True when the right-click landed on something that needs its native menu. */
export function keepsNativeMenu(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.closest !== 'function') return false;
  if (el.isContentEditable) return true;
  return !!el.closest('input, textarea, select');
}

export function ContextMenu({
  x,
  y,
  items,
  onClose,
  head,
  search,
}: {
  x: number;
  y: number;
  items: (MenuItem | null)[];
  onClose: () => void;
  head?: string;
  search?: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // The click that OPENS a dropdown reaches `window` after the menu has
  // mounted and subscribed, so without a grace period every menu opened
  // from a button closed itself in the same tick (the standup's trap).
  const openedAt = useRef(Date.now());
  const [q, setQ] = useState('');

  useEffect(() => {
    openedAt.current = Date.now();
    setQ('');
  }, [x, y, head]);

  useEffect(() => {
    const inside = (e: Event) => {
      const el = ref.current;
      return !!el && e.target instanceof Node && el.contains(e.target);
    };
    const away = (e: Event) => {
      if (inside(e)) return;
      if (Date.now() - openedAt.current < 250) return;
      onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      // Arrows walk the actions (Enter/Space on a focused button is the
      // browser's own); Home/End jump. From the filter box, ArrowDown
      // steps onto the first match.
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
      const el = ref.current;
      if (!el) return;
      const buttons = Array.from(el.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)'));
      if (!buttons.length) return;
      e.preventDefault();
      const i = buttons.findIndex((b) => b === document.activeElement);
      const next =
        e.key === 'Home'
          ? 0
          : e.key === 'End'
            ? buttons.length - 1
            : e.key === 'ArrowDown'
              ? (i + 1) % buttons.length
              : i <= 0
                ? buttons.length - 1
                : i - 1;
      buttons[next]?.focus();
    };
    window.addEventListener('click', away);
    window.addEventListener('contextmenu', away);
    window.addEventListener('keydown', key);
    window.addEventListener('resize', onClose);
    window.addEventListener('scroll', away, true);
    return () => {
      window.removeEventListener('click', away);
      window.removeEventListener('contextmenu', away);
      window.removeEventListener('keydown', key);
      window.removeEventListener('resize', onClose);
      window.removeEventListener('scroll', away, true);
    };
  }, [onClose]);

  // Keep the menu on screen when opened near an edge.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    el.style.left = `${Math.max(8, Math.min(x, window.innerWidth - w - 8))}px`;
    el.style.top = `${Math.max(8, Math.min(y, window.innerHeight - h - 8))}px`;
  }, [x, y, q, items.length]);

  useEffect(() => {
    if (!search) return;
    const id = window.setTimeout(() => inputRef.current?.focus(), 20);
    return () => window.clearTimeout(id);
  }, [search]);

  const needle = q.trim().toLowerCase();
  const shown = needle
    ? items.filter(
        (it): it is MenuItem =>
          !!it &&
          !it.heading &&
          (it.sticky || `${it.label} ${it.note ?? ''}`.toLowerCase().includes(needle)),
      )
    : items;

  // A PORTAL, not in place: the ERP's table rows carry a transform, and a
  // `position: fixed` menu inside one is positioned against the row, not
  // the viewport - it landed a screen below the button it opened from.
  return createPortal(
    <div
      ref={ref}
      className="ci ci-ctx"
      role="menu"
      style={{ left: x, top: y }}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {head && <div className="ctx-head">{head}</div>}
      {search && (
        <div className="menusearch">
          <input
            ref={inputRef}
            type="text"
            placeholder={search}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              // Enter takes the first match - the filter is a picker, not a form.
              if (e.key !== 'Enter') return;
              const first = shown.find((it): it is MenuItem => !!it && !it.heading && !it.disabled);
              if (!first) return;
              e.preventDefault();
              onClose();
              first.onClick();
            }}
          />
        </div>
      )}
      {needle && shown.length === 0 && (
        <div className="menunone">{t('ci.menu_none', { defaultValue: 'Nothing matches that.' })}</div>
      )}
      {shown.map((item, i) =>
        item === null ? (
          <hr key={`sep-${i}`} />
        ) : item.heading ? (
          <div key={`h-${item.label}-${i}`} className="ctx-group">
            {item.label}
          </div>
        ) : (
          <button
            key={`${item.label}-${i}`}
            type="button"
            role="menuitem"
            disabled={item.disabled}
            className={item.danger ? 'danger' : undefined}
            onClick={() => {
              if (item.disabled) return;
              onClose();
              item.onClick();
            }}
          >
            {item.color && <span className="mdot" style={{ background: item.color }} aria-hidden />}
            {item.icon && <item.icon className="micon" />}
            <span className="mlabel">{item.label}</span>
            {item.note && <span className="mnote">{item.note}</span>}
          </button>
        ),
      )}
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// useMenu — own one menu, open it from a right-click or from a button
// ---------------------------------------------------------------------------

interface OpenMenuState extends MenuOptions {
  x: number;
  y: number;
  items: (MenuItem | null)[];
  /** Bumped on every open so the element remounts and re-arms its grace period. */
  n: number;
}

export interface MenuHandle {
  menu: OpenMenuState | null;
  /** Open at a point on screen. */
  openAt: (x: number, y: number, items: (MenuItem | null)[], opts?: MenuOptions) => void;
  /** Right-click handler: skips text fields, claims the event, opens at the cursor. */
  openFromEvent: (e: ReactMouseEvent, items: (MenuItem | null)[], opts?: MenuOptions) => void;
  /** Dropdown: open under an element's bottom-left corner. */
  openBelow: (el: HTMLElement, items: (MenuItem | null)[], opts?: MenuOptions) => void;
  close: () => void;
  /** Render this once, anywhere in the component's tree. */
  element: ReactNode;
}

export function useMenu(): MenuHandle {
  const [menu, setMenu] = useState<OpenMenuState | null>(null);
  const counter = useRef(0);
  const openAt = useCallback((x: number, y: number, items: (MenuItem | null)[], opts?: MenuOptions) => {
    counter.current += 1;
    setMenu({ x, y, items, head: opts?.head, search: opts?.search, n: counter.current });
  }, []);
  const openFromEvent = useCallback(
    (e: ReactMouseEvent, items: (MenuItem | null)[], opts?: MenuOptions) => {
      if (keepsNativeMenu(e.target)) return;
      e.preventDefault();
      e.stopPropagation();
      openAt(e.clientX, e.clientY, items, opts);
    },
    [openAt],
  );
  const openBelow = useCallback(
    (el: HTMLElement, items: (MenuItem | null)[], opts?: MenuOptions) => {
      const p = menuAt(el);
      openAt(p.x, p.y, items, opts);
    },
    [openAt],
  );
  const close = useCallback(() => setMenu(null), []);
  const element = menu ? (
    <ContextMenu
      key={menu.n}
      x={menu.x}
      y={menu.y}
      items={menu.items}
      head={menu.head}
      search={menu.search}
      onClose={close}
    />
  ) : null;
  return { menu, openAt, openFromEvent, openBelow, close, element };
}
