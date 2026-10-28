// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How many sidebar entries Simple mode keeps out of reach.
 *
 * Enabling a module on the Modules page writes `module_preferences`, but a nav
 * row carrying `advancedOnly` (or sitting in a group carrying `hideInSimple`)
 * is filtered out by `Sidebar.tsx` before the module gate ever runs. The two
 * rules are independent: `passesRowGates` in `Sidebar.tsx` asks
 * `isModuleEnabled`, `visibleGroupItems` there asks the mode, and a row has to
 * clear both. So a user in Simple mode can switch a module on, watch the toggle
 * turn green, and still find nothing new in the menu, with no surface anywhere
 * saying why. A company profile with a workspace (`workspaces.ts`) is the
 * exception: its Simple mode keeps every other row under "More modules".
 *
 * These counts turn that invisible rule into a number the page can state out
 * loud. They are computed from `navGroups` at call time rather than stored as
 * a constant: the catalogue grows every release, and a hardcoded figure would
 * drift silently, which is the exact failure this notice exists to prevent.
 */
import { navGroups } from '@/app/layout/navCatalog';
import type { NavGroup } from '@/app/layout/navCatalog';

export interface AdvancedModeGap {
  /** Routed entries hidden purely because the user is in Simple mode. */
  hidden: number;
  /** Every routed entry in the catalogue, hidden or not. */
  total: number;
}

/**
 * Count the entries Simple mode hides.
 *
 * An entry is hidden when its own `advancedOnly` flag is set or when its whole
 * group is flagged `hideInSimple` — the sidebar applies both, so counting only
 * one of them understates the gap.
 *
 * @param groups Nav catalogue to measure. Defaults to the live `navGroups`.
 */
export function countAdvancedOnlyEntries(groups: NavGroup[] = navGroups): AdvancedModeGap {
  let hidden = 0;
  let total = 0;
  for (const group of groups) {
    for (const item of group.items) {
      total += 1;
      if (group.hideInSimple || item.advancedOnly) hidden += 1;
    }
  }
  return { hidden, total };
}
