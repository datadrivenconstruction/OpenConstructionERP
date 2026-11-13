// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Children, Fragment, isValidElement, type ReactElement, type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal } from 'lucide-react';
import clsx from 'clsx';

import { Button, ButtonSizeOverrideContext } from './Button';
import { usePageHeaderSlot } from './pageHeaderSlot';

/**
 * Canonical module page top block (MODULE_STYLE_GUIDE.md section 2).
 *
 * The module NAME and ICON live in the top app bar (Header + routeIcons) -
 * they are never repeated inside the page. What a page renders at the top is
 * exactly this, in this order:
 *
 *   1. `Breadcrumb` - only when it has depth (project link / detail trail);
 *      the shared component hides single-item trails by itself.
 *   2. THIS component: one muted subtitle sentence (what the module does)
 *      on the left, the page actions on the right.
 *   3. `DismissibleInfo` - the collapsible "Module information" card.
 *
 * Keeping every page on this exact block is what makes the app read as one
 * product instead of ~90 hand-rolled headers.
 */
export interface PageHeaderProps {
  /** One sentence, i18n, `text-content-tertiary` - NOT the module name. */
  subtitle?: ReactNode;
  /** Primary action first, then secondary; rendered right-aligned. */
  actions?: ReactNode;
  /**
   * Accessible page heading for screen readers. The top bar is meant to show
   * the same words, and `Header.titleKeys.test.ts` is what holds the two
   * together: it pairs this key with the route's `TITLE_I18N_MAP` entry and
   * fails when they differ. Pass the key the module names itself by, normally
   * `<module>.title`, not a `nav.*` variant of it.
   *
   * The parenthetical here once simply stated the top bar shows it, which was
   * untrue on four screens: this heading said "Site prep", "Interface
   * management", "RFIs", "Risk Register" while the bar above said "Site
   * Mobilisation", "Interface Register", "RFI", "Risks". Since the element is
   * `sr-only`, no one reader saw both, so it read as correct to everybody.
   */
  srTitle?: string;
  className?: string;
}

function HeaderSlot() {
  const setEl = usePageHeaderSlot((s) => s.setEl);
  const ref = useCallback((node: HTMLSpanElement | null) => setEl(node), [setEl]);
  // `contents`: portalled children join the action row's flex flow and gap.
  return <span ref={ref} className="contents" data-oe-header-slot />;
}

/** Header row holds at most this many page actions before the rest go to "...". */
const MAX_VISIBLE_ACTIONS = 4;

function flattenActions(actions: ReactNode): ReactElement[] {
  const out: ReactElement[] = [];
  Children.toArray(actions).forEach((c) => {
    if (!isValidElement(c)) return;
    if (c.type === Fragment) out.push(...flattenActions((c.props as { children?: ReactNode }).children));
    else out.push(c);
  });
  return out;
}

function isPrimary(el: ReactElement): boolean {
  return (el.props as { variant?: string }).variant === 'primary';
}

function OverflowMenu({ items }: { items: ReactElement[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  return (
    <div ref={boxRef} className="relative" data-testid="page-header-overflow">
      <Button
        variant="secondary"
        size="md"
        icon={<MoreHorizontal size={16} />}
        aria-label={t('common.more_actions', { defaultValue: 'More actions' })}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      />
      {/* Stays mounted while closed: an action that owns a dialog or a running
          export must not lose its state when the menu closes. */}
      <div
          role="menu"
          aria-hidden={!open}
          className={`absolute end-0 top-full z-dropdown mt-1 ${open ? 'flex' : 'hidden'} min-w-48 flex-col gap-1 rounded-xl border border-border-light bg-surface-primary p-1.5 shadow-md [&_[data-oe-button]]:w-full [&_[data-oe-button]]:justify-start`}
          onClick={(e) => {
            // Plain actions close the menu; ones that open their own popup keep it.
            if (!(e.target as HTMLElement).closest('[aria-haspopup],[aria-expanded]')) setOpen(false);
          }}
        >
          <ButtonSizeOverrideContext.Provider value="md">{items}</ButtonSizeOverrideContext.Provider>
        </div>
    </div>
  );
}

function HeaderActions({ actions }: { actions: ReactNode }) {
  const all = flattenActions(actions);
  if (all.length <= MAX_VISIBLE_ACTIONS + 1) {
    return <ButtonSizeOverrideContext.Provider value="md">{all}</ButtonSizeOverrideContext.Provider>;
  }
  // Primaries always stay in the row; the first secondaries fill the rest.
  const primaries = all.filter(isPrimary);
  let room = Math.max(0, MAX_VISIBLE_ACTIONS - primaries.length);
  const visible: ReactElement[] = [];
  const hidden: ReactElement[] = [];
  all.forEach((el) => {
    if (isPrimary(el)) visible.push(el);
    else if (room > 0) {
      visible.push(el);
      room -= 1;
    } else hidden.push(el);
  });
  return (
    <ButtonSizeOverrideContext.Provider value="md">
      {visible}
      <OverflowMenu items={hidden} />
    </ButtonSizeOverrideContext.Provider>
  );
}

export function PageHeader({ subtitle, actions, srTitle, className }: PageHeaderProps) {
  if (!subtitle && !actions) {
    // srTitle-only pages (chat / full-bleed surfaces) still need the a11y
    // heading, but NOT the min-h-9 row - that rendered as an empty 36px
    // midline above the content (uniformity sweep, shared issue).
    return srTitle ? <h1 className="sr-only">{srTitle}</h1> : null;
  }
  return (
    // items-center: the (usually single-line) subtitle sits on the same
    // vertical midline as the h-8/h-9 action buttons. Top-aligning them
    // (items-start) left the text floating above the buttons and read as
    // misaligned chrome on every page (founder feedback 2026-06-06).
    // NO own margin (audit fix S1): the page root's space-y-5 is the ONLY
    // vertical rhythm - a built-in mb-4 stacked on top of it produced the
    // double gaps the founder flagged.
    <div data-oe-page-header className={clsx('flex min-h-8 flex-wrap items-center justify-between gap-x-4 gap-y-2', className)}>
      {srTitle && <h1 className="sr-only">{srTitle}</h1>}
      {subtitle ? (
        <p className="min-w-0 flex-1 basis-64 text-sm leading-relaxed text-content-tertiary">
          {subtitle}
        </p>
      ) : (
        <div className="min-w-0 flex-1" aria-hidden />
      )}
      {/* max-w-full: shrink-0 keeps the buttons from being squeezed while they
          share the row with the subtitle, but it also meant this box was never
          narrowed to the container, so its own flex-wrap could never fire. On a
          390px viewport the seven action buttons laid out in one 668px line and
          scrolled the whole page sideways. The cap is inert whenever the row
          fits, so wide layouts are unchanged. */}
      <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2 empty:hidden">
        {actions && <HeaderActions actions={actions} />}
        <HeaderSlot />
      </div>
    </div>
  );
}
