// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClientMenu - a small portalled context menu for anything that shows a
 * client (picker rows, the selected pill, dashboard rows, group headers,
 * project-card chips). Opened at a pointer position (right-click) or under
 * an element (the pencil affordance for mouse users who don't right-click).
 *
 * Self-contained: no dependency on modules/. Keyboard: Up/Down walk the
 * items, Enter/Space activate, Escape closes; outside click / scroll /
 * resize close. Every key + mouse event inside is stopped so an enclosing
 * combobox, card link or dialog never sees it.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

export interface ClientMenuItem {
  key: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
  /** Draw a divider above this item. */
  separatorBefore?: boolean;
  /** Secondary text to the right (e.g. the current colour hex). */
  hint?: string;
}

export interface ClientMenuAnchor {
  x: number;
  y: number;
}

export interface ClientMenuProps {
  anchor: ClientMenuAnchor | null;
  items: ReadonlyArray<ClientMenuItem>;
  onClose: () => void;
  /** Muted heading line (the client's name). */
  title?: string;
  'data-testid'?: string;
}

const MENU_W = 224;
const EDGE = 8;

/** Where to open a menu for a pointer event or, when the event has no
 *  usable coordinates (keyboard-triggered click), under its target. */
export function anchorFromEvent(e: ReactMouseEvent | MouseEvent): ClientMenuAnchor {
  if (e.clientX > 0 || e.clientY > 0) return { x: e.clientX, y: e.clientY };
  const el = e.currentTarget as HTMLElement | null;
  return anchorFromElement(el);
}

export function anchorFromElement(el: Element | null | undefined): ClientMenuAnchor {
  if (!el || typeof (el as HTMLElement).getBoundingClientRect !== 'function') return { x: EDGE, y: EDGE };
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.bottom + 4 };
}

/** State + handlers for one menu: `openAt(event)` for right-click and
 *  pencil clicks, `close()`, and the `anchor` to hand to <ClientMenu>. */
export function useClientMenu() {
  const [anchor, setAnchor] = useState<ClientMenuAnchor | null>(null);
  const openAt = useCallback((e: ReactMouseEvent | MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setAnchor(anchorFromEvent(e));
  }, []);
  const openUnder = useCallback((el: Element | null | undefined) => {
    setAnchor(anchorFromElement(el));
  }, []);
  const close = useCallback(() => setAnchor(null), []);
  return { anchor, openAt, openUnder, close, isOpen: anchor !== null };
}

export function ClientMenu({ anchor, items, onClose, title, 'data-testid': testId }: ClientMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<ClientMenuAnchor | null>(null);
  const [active, setActive] = useState(0);
  const open = anchor !== null;
  // Whatever had focus when the menu opened (the right-clicked pill, the
  // pencil button) gets it back when the menu closes.
  const openerRef = useRef<HTMLElement | null>(null);

  const enabled = items.filter((i) => !i.disabled);

  useLayoutEffect(() => {
    if (!open || !anchor) return;
    const h = ref.current?.offsetHeight ?? 0;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let x = anchor.x;
    let y = anchor.y;
    if (x + MENU_W > vw - EDGE) x = Math.max(EDGE, vw - EDGE - MENU_W);
    if (y + h > vh - EDGE) y = anchor.y - h;
    // Never leave the viewport, whichever side the menu ended up on.
    y = Math.max(EDGE, Math.min(y, vh - EDGE - h));
    setPos({ x, y });
    setActive(0);
    // Focus the menu so arrow keys work at once.
    const active0 = document.activeElement;
    if (active0 instanceof HTMLElement && !ref.current?.contains(active0)) {
      openerRef.current = active0;
    }
    ref.current?.focus();
  }, [open, anchor]);

  useEffect(() => {
    if (open) return;
    const opener = openerRef.current;
    openerRef.current = null;
    if (!opener || !opener.isConnected) return;
    // An item may have moved focus on (the colour popover, the editor
    // dialog): only restore when nothing else claimed it.
    const now = document.activeElement;
    if (now && now !== document.body && now !== opener) return;
    opener.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return;
      onClose();
    };
    const onAway = () => onClose();
    document.addEventListener('mousedown', onDown);
    document.addEventListener('contextmenu', onDown);
    window.addEventListener('resize', onAway);
    window.addEventListener('scroll', onAway, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('contextmenu', onDown);
      window.removeEventListener('resize', onAway);
      window.removeEventListener('scroll', onAway, true);
    };
  }, [open, onClose]);

  if (!open) return null;

  const activate = (item: ClientMenuItem) => {
    if (item.disabled) return;
    onClose();
    item.onSelect();
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (enabled.length) setActive((i) => (i + 1) % enabled.length);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (enabled.length) setActive((i) => (i - 1 + enabled.length) % enabled.length);
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      const item = enabled[active];
      if (item) activate(item);
    }
  };

  const stop = (e: ReactMouseEvent) => e.stopPropagation();

  return createPortal(
    <div
      ref={ref}
      role="menu"
      tabIndex={-1}
      aria-label={title}
      data-testid={testId ?? 'client-menu'}
      onKeyDown={onKeyDown}
      onMouseDown={stop}
      onClick={stop}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      className="fixed z-[95] overflow-hidden rounded-lg border border-border bg-surface-elevated py-1 shadow-xl outline-none"
      style={{ width: MENU_W, top: pos?.y ?? -9999, left: pos?.x ?? -9999 }}
    >
      {title && (
        <div className="truncate px-3 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary" title={title}>
          {title}
        </div>
      )}
      {items.map((item) => {
        const enabledIdx = enabled.indexOf(item);
        const isActive = enabledIdx === active;
        return (
          <div key={item.key}>
            {item.separatorBefore && <div className="my-1 h-px bg-border-light" />}
            <button
              type="button"
              role="menuitem"
              disabled={item.disabled}
              aria-disabled={item.disabled}
              data-testid={`client-menu-${item.key}`}
              onMouseEnter={() => enabledIdx >= 0 && setActive(enabledIdx)}
              onClick={() => activate(item)}
              className={`flex w-full items-center gap-2 px-3 py-1.5 text-start text-sm transition-colors disabled:opacity-50 ${
                item.danger
                  ? 'text-semantic-error hover:bg-semantic-error-bg'
                  : isActive
                    ? 'bg-surface-secondary text-content-primary'
                    : 'text-content-primary hover:bg-surface-secondary'
              }`}
            >
              {item.icon && <span className="flex w-4 shrink-0 items-center justify-center text-content-tertiary">{item.icon}</span>}
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {item.hint && <span className="shrink-0 font-mono text-[10px] text-content-tertiary">{item.hint}</span>}
            </button>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
