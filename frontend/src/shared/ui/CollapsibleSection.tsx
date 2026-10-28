// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A titled section a user can collapse when they do not need it. Built for the
 * "How this module fits together" / explainer blocks that lead many module
 * pages: helpful the first time, noise once you know the module. The choice is
 * remembered per `storageKey`, so it stays the way each user left it across
 * reloads.
 *
 * Collapsing: a collapsed block renders NOTHING in the page and folds into an
 * information icon in the top app bar, immediately to the right of the module
 * name (founder 2026-08-07). It registers in `useModuleInfoStore` while
 * collapsed, exactly the way `DismissibleInfo` does, so `ModuleInfoButton`
 * appears there and one click brings the block back. That icon is the only
 * re-open control in the product: it was previously a pill next to the
 * module's Cases and "How it works" buttons, which moved with each page's
 * action row instead of staying put.
 *
 * The registration key is namespaced `section:<storageKey>` because the store is
 * shared with `DismissibleInfo`: a page carrying both an info card and an
 * explainer under the same string would otherwise have one silently unregister
 * the other.
 *
 * Placement on a tabbed page: put the explainer at page level, ABOVE the tab
 * strip, and put the module's `InsightsPanel` inside whichever tab owns the
 * data. An explainer mounted inside a tab disappears when the user switches
 * away and they have no way back to it, which is worse than having no explainer
 * at all, because they stop believing the page has one. The two panels answer
 * different questions and do not have to live in the same component.
 *
 * A page that already carries a `DismissibleInfo` explaining the module does not
 * also need one of these. Two explanatory blocks on one page is the hollow
 * outcome this pattern exists to avoid.
 *
 * This replaces the previous behaviour, where a collapsed block kept its header
 * visible and animated its body shut with the grid `0fr`->`1fr` trick. That
 * animation and its `inert` handling are gone rather than left dormant: once a
 * collapsed block unmounts there is no element left to animate or to keep out of
 * the a11y tree, and a zero-height leftover would still have drawn a gap from
 * the page's `space-y` rhythm.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ChevronUp } from 'lucide-react';
import clsx from 'clsx';

import { useModuleInfoStore } from '@/stores/useModuleInfoStore';

function readCollapsed(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(`oce.collapse.${key}`);
    if (raw === null) return fallback;
    return raw === '1';
  } catch {
    return fallback;
  }
}

function persistCollapsed(key: string, collapsed: boolean): void {
  try {
    localStorage.setItem(`oce.collapse.${key}`, collapsed ? '1' : '0');
  } catch {
    /* private mode / quota - collapsing still works for the session. */
  }
}

export interface CollapsibleSectionProps {
  /** Stable id for remembering the open/closed choice, e.g. "tendering.how". */
  storageKey: string;
  /** Header label. */
  title: ReactNode;
  /** Optional leading icon in the header. */
  icon?: ReactNode;
  /** Optional one-line hint shown under the title (stays visible when collapsed). */
  subtitle?: ReactNode;
  /** Start collapsed on the very first visit (default: expanded). */
  defaultCollapsed?: boolean;
  children: ReactNode;
  className?: string;
  /** Extra classes for the innermost content wrapper. Padding lives here so a
   *  collapsed block has no leftover vertical space (default: `px-4 pb-4`). */
  bodyClassName?: string;
}

export function CollapsibleSection({
  storageKey,
  title,
  icon,
  subtitle,
  defaultCollapsed = false,
  children,
  className,
  bodyClassName,
}: CollapsibleSectionProps) {
  const [collapsed, setCollapsed] = useState<boolean>(() => readCollapsed(storageKey, defaultCollapsed));

  useEffect(() => persistCollapsed(storageKey, collapsed), [storageKey, collapsed]);

  const collapse = useCallback(() => setCollapsed(true), []);
  const expand = useCallback(() => setCollapsed(false), []);

  // While collapsed the block is out of the page, so the way back is the pill
  // next to the Cases button. Unmount (navigation) unregisters automatically.
  const register = useModuleInfoStore((s) => s.register);
  const unregister = useModuleInfoStore((s) => s.unregister);
  const registryKey = `section:${storageKey}`;
  useEffect(() => {
    if (!collapsed) return undefined;
    register({ key: registryKey, expand });
    return () => unregister(registryKey);
  }, [collapsed, registryKey, expand, register, unregister]);

  if (collapsed) return null;

  const bodyId = `collapsible-${storageKey.replace(/[^a-z0-9]+/gi, '-')}`;

  // A white, lightly translucent card (founder 2026-07-26: "сделай чтобы у
  // блока был белый фон немного полупрозрачный"). `surface-primary` is #ffffff
  // in light mode and the deep blue-gray in dark mode, so taking it at 70%
  // keeps the block theme-correct instead of pinning a literal white that would
  // glare in dark mode. The app backdrop's dot grid reads faintly through it,
  // which is what makes the card look laid ON the page rather than cut into it.
  return (
    <section
      className={clsx(
        'overflow-hidden rounded-xl border border-border-light bg-surface-primary/70 shadow-sm',
        className,
      )}
    >
      <button
        type="button"
        onClick={collapse}
        aria-expanded
        aria-controls={bodyId}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-secondary/40"
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {icon}
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-semibold text-content-primary">{title}</span>
            {subtitle && <span className="truncate text-2xs text-content-tertiary">{subtitle}</span>}
          </span>
        </span>
        {/* The block only renders while open, so the chevron always points at
            the action it performs: close this and put it in the pill. */}
        <ChevronUp size={16} aria-hidden className="shrink-0 text-content-tertiary" />
      </button>
      <div id={bodyId} className={bodyClassName ?? 'px-4 pb-4'}>
        {children}
      </div>
    </section>
  );
}
