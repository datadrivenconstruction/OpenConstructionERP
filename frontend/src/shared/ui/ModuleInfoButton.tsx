// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ModuleInfoButton — the re-open control for a collapsed module info block.
//
// Founder revision 2026-08-07: a collapsed block folds into an information
// icon sitting immediately to the RIGHT OF THE MODULE NAME, which is where
// this control lived originally. The Header hosts it, right after the module
// title, so it is in the same place on every page in the product.
//
// It used to be a labelled pill down in the page's action row, next to "How
// it works" (founder 2026-07-23). That placement moved with the page: a module
// with a wide action row pushed it off to a different spot than the module
// next door, and on a long page the reader had to find it again each time. The
// module name never moves, so anchoring to the name is what makes the control
// learnable. There is now exactly one of these on screen, never two.
//
// Icon rather than icon-plus-label because the top bar is dense and shared
// with the project switcher, the search box and the action cluster; a word
// there would push the module name into truncation at lg widths, which is the
// bug the title's own sizing comment already records. The accessible name
// carries the meaning instead, so nothing is lost to a screen reader.
//
// It self-hides whenever nothing on the page is collapsed, so a page with its
// info block open shows no extra chrome at all.

import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import clsx from 'clsx';

import { useModuleInfoStore } from '@/stores/useModuleInfoStore';

export interface ModuleInfoButtonProps {
  /** Optional extra classes for layout-specific tweaks. */
  className?: string;
}

export function ModuleInfoButton({ className }: ModuleInfoButtonProps) {
  const { t } = useTranslation();
  const hasCollapsed = useModuleInfoStore((s) => s.entries.length > 0);
  const expandAll = useModuleInfoStore((s) => s.expandAll);

  // Nothing collapsed on this page -> no re-open control, no clutter.
  if (!hasCollapsed) return null;

  const label = t('common.module_info', { defaultValue: 'Module information' });

  return (
    <button
      type="button"
      onClick={expandAll}
      data-testid="module-info-button"
      aria-label={label}
      title={label}
      className={clsx(
        // Scales in on mount, which is the moment the block above it
        // disappeared. Collapsing otherwise reads as the block being deleted;
        // the eye needs to be told the content moved here rather than away.
        // The class only ever runs once because the control is unmounted
        // whenever nothing is collapsed.
        'animate-scale-in',
        'flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
        // The info block's own light-blue tint, carried onto the icon so the
        // pair reads as one thing in two states rather than as an unrelated
        // header button. Quiet until hover: it sits beside the module name and
        // must not compete with it for the eye.
        'text-oe-blue-text/70 transition-colors hover:bg-oe-blue/10 hover:text-oe-blue-text',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        className,
      )}
    >
      <Info size={15} strokeWidth={1.9} />
    </button>
  );
}
