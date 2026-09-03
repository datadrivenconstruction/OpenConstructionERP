// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClientColorSwatch - the client's brand colour as a small round button.
 *
 * Unset = a grey dashed ring; set = a filled disc. Clicking opens a compact
 * popover (portalled to <body> so it is never clipped by a scrolling list)
 * with the twelve palette picks, a hex input with live preview and "No
 * colour". Two modes:
 *
 *  - `contact` given   -> picking saves at once through setClientColor and
 *                         invalidates every contacts query (the client
 *                         directory rides on the 'contacts' prefix).
 *  - `value`/`onChange` -> controlled; nothing is saved (the picker's
 *                         "add as a new client" flow picks before creating).
 *
 * Keyboard: the button opens on Enter/Space, focus lands on the first
 * palette pick, Tab walks the picks -> hex input -> No colour, Escape
 * closes and returns focus to the button. Every key event inside the
 * popover is stopped so an enclosing dialog / combobox never sees it.
 */
import {
  forwardRef,
  useEffect,
  useId,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, Palette } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import type { Contact } from '@/features/contacts/api';
import {
  CLIENT_PALETTE,
  contactColor,
  contrastText,
  normalizeHex,
  setClientColor,
} from './clients';

export interface ClientColorSwatchProps {
  /** Save mode: the client contact whose brand colour this is. */
  contact?: Pick<Contact, 'id' | 'custom_properties' | 'company_name'>;
  /** Controlled mode (no contact): the current hex or ''. */
  value?: string;
  /** Controlled mode callback; also fired after a successful save. */
  onChange?: (hex: string) => void;
  /** Name used in the button's accessible label. */
  clientName?: string;
  size?: 'xs' | 'sm' | 'md';
  /** Render the disc only - no popover, not focusable. */
  readOnly?: boolean;
  className?: string;
  'data-testid'?: string;
}

const SIZE_PX: Record<NonNullable<ClientColorSwatchProps['size']>, number> = {
  xs: 12,
  sm: 16,
  md: 20,
};

const POPOVER_W = 232;
const POPOVER_GAP = 6;

/** The disc itself - shared by the button and the read-only rendering. */
export function ColorDisc({ hex, size = 16, className = '' }: { hex: string; size?: number; className?: string }) {
  const color = normalizeHex(hex);
  const style: CSSProperties = color
    ? { width: size, height: size, backgroundColor: color, boxShadow: 'inset 0 0 0 1px rgba(0,0,0,.12)' }
    : { width: size, height: size };
  return (
    <span
      aria-hidden
      className={`inline-block shrink-0 rounded-full ${
        color ? '' : 'border border-dashed border-content-tertiary/70 bg-transparent'
      } ${className}`}
      style={style}
    />
  );
}

/** Imperative handle so a context menu's "Set colour..." can open the
 *  popover without the user clicking the disc. */
export interface ClientColorSwatchHandle {
  open: () => void;
  close: () => void;
}

export const ClientColorSwatch = forwardRef<ClientColorSwatchHandle, ClientColorSwatchProps>(function ClientColorSwatch({
  contact,
  value,
  onChange,
  clientName,
  size = 'sm',
  readOnly = false,
  className = '',
  'data-testid': testId,
}, handleRef) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const popId = useId();

  const stored = contact ? contactColor(contact) : normalizeHex(value);
  // While a save is in flight (or right after, before the directory
  // refetches) show what was picked, not the stale directory row.
  const [pending, setPending] = useState<string | null>(null);
  const current = pending ?? stored;
  useEffect(() => {
    // Once the directory catches up with the pick, drop the override.
    if (pending !== null && stored === pending) setPending(null);
  }, [stored, pending]);

  const [open, setOpen] = useState(false);
  const [hexInput, setHexInput] = useState('');
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const firstPickRef = useRef<HTMLButtonElement>(null);

  const name = clientName ?? (contact?.company_name ?? '').trim();

  const mutation = useMutation({
    mutationFn: (hex: string) => setClientColor(contact!, hex),
    onSuccess: (saved, hex) => {
      queryClient.invalidateQueries({ queryKey: ['contacts'] });
      onChange?.(normalizeHex(hex));
      // Keep the picked colour on screen until the refetch lands, then
      // the effect above clears the override.
      setPending(contactColor(saved));
    },
    onError: (error: Error, hex) => {
      setPending(null);
      addToast({
        type: 'error',
        title: hex
          ? t('projects.client_color.save_failed', { defaultValue: 'Could not save the client colour' })
          : t('projects.client_color.clear_failed', { defaultValue: 'Could not clear the client colour' }),
        message: error.message,
      });
    },
  });

  const commit = (hex: string) => {
    const color = normalizeHex(hex);
    if (hex.trim() && !color) return;
    close();
    if (contact) {
      setPending(color);
      mutation.mutate(color);
    } else {
      onChange?.(color);
    }
  };

  const place = () => {
    const el = buttonRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const popH = popRef.current?.offsetHeight ?? 190;
    let left = r.left;
    if (left + POPOVER_W > vw - 8) left = vw - 8 - POPOVER_W;
    let top = r.bottom + POPOVER_GAP;
    if (top + popH > vh - 8) top = r.top - POPOVER_GAP - popH;
    // Whichever side it opened on, keep the whole popover inside the
    // viewport (a swatch scrolled half off the bottom flips above, then
    // still gets clamped).
    top = Math.max(8, Math.min(top, vh - 8 - popH));
    left = Math.max(8, Math.min(left, vw - 8 - POPOVER_W));
    setPos({ top, left });
  };

  const openPopover = () => {
    setHexInput(current);
    setOpen(true);
  };
  const close = () => {
    setOpen(false);
    setPos(null);
  };
  const closeAndRefocus = () => {
    close();
    buttonRef.current?.focus();
    requestAnimationFrame(() => buttonRef.current?.focus());
  };

  useImperativeHandle(handleRef, () => ({ open: openPopover, close }));

  useLayoutEffect(() => {
    if (!open) return;
    place();
    // Measure again once fonts / layout settle - the first pass can read
    // the popover before its height is final.
    const raf = requestAnimationFrame(place);
    firstPickRef.current?.focus();
    const onReflow = () => place();
    window.addEventListener('resize', onReflow);
    window.addEventListener('scroll', onReflow, true);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onReflow);
      window.removeEventListener('scroll', onReflow, true);
    };
    // place() reads refs only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Outside click closes. The popover is portalled, so DOM containment is
  // checked against both the button and the popover node.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (popRef.current?.contains(target) || buttonRef.current?.contains(target)) return;
      close();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const onPopKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    // Nothing inside here belongs to the combobox / dialog around us.
    e.stopPropagation();
    if (e.key === 'Escape') {
      e.preventDefault();
      closeAndRefocus();
    }
  };

  const stop = (e: ReactMouseEvent) => {
    // Inside a listbox row / a card link the click must not select or
    // navigate as well.
    e.stopPropagation();
    e.preventDefault();
  };

  const px = SIZE_PX[size];
  const label = current
    ? t('projects.client_color.change', {
        defaultValue: 'Change colour for {{name}}',
        name: name || t('projects.client_owner', { defaultValue: 'Client / owner' }),
      })
    : t('projects.client_color.set', {
        defaultValue: 'Set a colour for {{name}}',
        name: name || t('projects.client_owner', { defaultValue: 'Client / owner' }),
      });

  if (readOnly) {
    return <ColorDisc hex={current} size={px} className={className} />;
  }

  const typedHex = normalizeHex(hexInput);
  const hexValid = hexInput.trim() === '' || typedHex !== '';

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          stop(e);
          if (open) close();
          else openPopover();
        }}
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        disabled={mutation.isPending}
        data-testid={testId ?? 'client-color-swatch'}
        data-color={current || undefined}
        className={`inline-flex shrink-0 items-center justify-center rounded-full p-0.5 transition-shadow hover:ring-2 hover:ring-oe-blue/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue disabled:opacity-60 ${className}`}
      >
        <ColorDisc hex={current} size={px} />
      </button>
      {open &&
        createPortal(
          <div
            ref={popRef}
            id={popId}
            role="dialog"
            aria-label={t('projects.client_color.title', { defaultValue: 'Client colour' })}
            onKeyDown={onPopKeyDown}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
            data-testid="client-color-popover"
            className="fixed z-[90] rounded-lg border border-border bg-surface-elevated p-3 shadow-xl"
            style={{ width: POPOVER_W, top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
          >
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-content-primary">
              <Palette size={13} className="text-content-tertiary" />
              <span className="min-w-0 flex-1 truncate">
                {name || t('projects.client_color.title', { defaultValue: 'Client colour' })}
              </span>
            </div>
            <div className="grid grid-cols-6 gap-1.5" role="group" aria-label={t('projects.client_color.palette', { defaultValue: 'Quick picks' })}>
              {CLIENT_PALETTE.map((p, i) => {
                const selected = current === p.hex;
                return (
                  <button
                    key={p.hex}
                    ref={i === 0 ? firstPickRef : undefined}
                    type="button"
                    onClick={() => commit(p.hex)}
                    aria-label={p.name}
                    aria-pressed={selected}
                    title={`${p.name} ${p.hex}`}
                    data-testid={`client-color-pick-${p.hex.slice(1)}`}
                    className="flex h-7 w-7 items-center justify-center rounded-full transition-transform hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-1"
                    style={{ backgroundColor: p.hex, color: contrastText(p.hex) }}
                  >
                    {selected && <Check size={14} strokeWidth={3} />}
                  </button>
                );
              })}
            </div>
            <form
              className="mt-2.5 flex items-center gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (hexValid) commit(hexInput);
              }}
            >
              <ColorDisc hex={typedHex} size={18} />
              <input
                type="text"
                value={hexInput}
                onChange={(e) => setHexInput(e.target.value)}
                placeholder="#d62828"
                maxLength={7}
                spellCheck={false}
                autoComplete="off"
                aria-label={t('projects.client_color.hex', { defaultValue: 'Hex colour' })}
                aria-invalid={!hexValid}
                data-testid="client-color-hex"
                className={`h-7 min-w-0 flex-1 rounded-md border bg-surface-primary px-2 font-mono text-xs text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue ${
                  hexValid ? 'border-border' : 'border-red-400'
                }`}
              />
              <button
                type="submit"
                disabled={!hexValid || !typedHex || typedHex === current}
                className="h-7 rounded-md bg-oe-blue px-2 text-xs font-medium text-white disabled:opacity-40"
              >
                {t('common.apply', { defaultValue: 'Apply' })}
              </button>
            </form>
            <button
              type="button"
              onClick={() => commit('')}
              disabled={!current}
              data-testid="client-color-none"
              className="mt-2 flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-start text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
            >
              <ColorDisc hex="" size={14} />
              {t('projects.client_color.none', { defaultValue: 'No colour' })}
            </button>
          </div>,
          document.body,
        )}
    </>
  );
});
