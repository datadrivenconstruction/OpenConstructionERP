// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// TabBar — shared accessible tab strip (WCAG 2.1.1 / WAI-ARIA 1.2
// "tabs" pattern).
//
// Why it exists: most module pages (BIM, BOQ, Settings, Property Dev,
// Finance, …) implement their own button-row "tabs" with no ARIA roles
// and no keyboard navigation, so screen readers announce them as plain
// buttons and keyboard users have to Tab through every other control to
// move between tabs. The audit blocker #28 calls this out.
//
// This component encapsulates:
//   * role="tablist" + aria-label on the outer container,
//   * role="tab" + aria-selected + aria-controls + tabIndex on each
//     button (so only the active tab is in the page tab-stop, matching
//     the "manual activation" tabs pattern),
//   * ArrowLeft / ArrowRight (Home / End) navigation across the strip,
//   * an optional icon slot per tab,
//   * a single visual style that matches the existing strip in
//     BIMRightPanelTabs / SettingsPage so adoption is a paste-in swap.
//
// The matching panel below the tab strip should set
//   role="tabpanel"
//   id={`<panelId>`}              // e.g. tabIds.panelId(activeId)
//   aria-labelledby={`<tabId>`}   // e.g. tabIds.tabId(activeId)
// — use the `tabIds` helper exported here to keep id naming consistent.

import { useCallback, useId, type KeyboardEvent, type ReactNode } from 'react';
import clsx from 'clsx';

export interface TabBarTab<TId extends string = string> {
  id: TId;
  label: ReactNode;
  /** Optional icon (typically a lucide-react component already rendered). */
  icon?: ReactNode;
  /** Optional disabled state — disabled tabs are skipped by arrow nav. */
  disabled?: boolean;
  /** Optional badge / count rendered to the right of the label. */
  badge?: ReactNode;
}

export type TabBarVariant = 'underline' | 'pill' | 'segmented';
export type TabBarSize = 'sm' | 'md';

export interface TabBarProps<TId extends string = string> {
  tabs: TabBarTab<TId>[];
  activeId: TId;
  onChange: (next: TId) => void;
  /** Required aria-label for the tablist (announced by screen readers). */
  ariaLabel: string;
  /** Visual variant — defaults to underline (matches existing strip). */
  variant?: TabBarVariant;
  size?: TabBarSize;
  /** Stretch tabs to fill width equally (flex-1 each). */
  fullWidth?: boolean;
  /** Wrapper className appended to the tablist container. */
  className?: string;
  /** className appended to each tab button. */
  tabClassName?: string;
  /** Optional id prefix so tab/panel ids stay stable across re-renders. */
  idPrefix?: string;
  /** Optional data-testid prefix; defaults to the same value as idPrefix. */
  testIdPrefix?: string;
}

/**
 * Helper to build stable tab/panel ids from a single prefix.
 *
 * Usage:
 *   const ids = tabIds('settings');
 *   <TabBar idPrefix="settings" ... />
 *   <div role="tabpanel" id={ids.panelId('general')}
 *        aria-labelledby={ids.tabId('general')}>...</div>
 */
export function tabIds(prefix: string) {
  return {
    tabId: (id: string) => `${prefix}-tab-${id}`,
    panelId: (id: string) => `${prefix}-panel-${id}`,
  };
}

const VARIANT_CLASSES: Record<TabBarVariant, { container: string }> = {
  underline: {
    // overflow-x-auto: the strip is one nowrap row, so a register with many
    // tabs pushed the whole page sideways on a phone - /finance reached 909px
    // of page scroll at a 390px viewport with 8 tabs, and change intelligence
    // reached 1672px with 16. Scrolling the strip is the usual mobile answer
    // and it costs nothing when the tabs already fit, which is every desktop
    // width we ship. Only this variant is scoped; pill and segmented lay out
    // differently and were not measured.
    container: 'flex items-stretch overflow-x-auto border-b border-border-light',
  },
  pill: {
    container: 'flex items-center gap-1 p-1 rounded-lg bg-surface-secondary',
  },
  segmented: {
    container:
      'inline-flex items-center rounded-lg border border-border-light bg-surface-secondary p-0.5',
  },
};

const SIZE_CLASSES: Record<TabBarSize, string> = {
  sm: 'px-2 py-1.5 text-[11px]',
  md: 'px-3 py-2 text-sm',
};

function tabButtonClasses({
  variant,
  size,
  isActive,
  disabled,
  fullWidth,
}: {
  variant: TabBarVariant;
  size: TabBarSize;
  isActive: boolean;
  disabled: boolean;
  fullWidth: boolean;
}): string {
  const base = clsx(
    'inline-flex items-center justify-center gap-1.5 font-medium transition-colors',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
    SIZE_CLASSES[size],
    fullWidth && 'flex-1',
    disabled && 'opacity-40 cursor-not-allowed',
  );
  if (variant === 'underline') {
    return clsx(
      base,
      isActive
        ? 'text-oe-blue border-b-2 border-oe-blue bg-surface-primary'
        : 'text-content-tertiary border-b-2 border-transparent hover:text-content-secondary hover:bg-surface-tertiary',
    );
  }
  if (variant === 'pill') {
    return clsx(
      base,
      'rounded-md',
      isActive
        ? 'bg-surface-primary text-content-primary shadow-sm'
        : 'text-content-secondary hover:text-content-primary hover:bg-surface-tertiary',
    );
  }
  // segmented
  return clsx(
    base,
    'rounded-md',
    isActive
      ? 'bg-surface-primary text-content-primary shadow-sm'
      : 'text-content-secondary hover:text-content-primary',
  );
}

export function TabBar<TId extends string = string>({
  tabs,
  activeId,
  onChange,
  ariaLabel,
  variant = 'underline',
  size = 'md',
  fullWidth = false,
  className,
  tabClassName,
  idPrefix,
  testIdPrefix,
}: TabBarProps<TId>) {
  const autoId = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const prefix = idPrefix ?? `tabbar-${autoId}`;
  const tprefix = testIdPrefix ?? idPrefix;
  const ids = tabIds(prefix);

  const enabledTabs = tabs.filter((t) => !t.disabled);

  const focusTab = useCallback(
    (id: string) => {
      const el = document.getElementById(ids.tabId(id));
      if (el && typeof (el as HTMLElement).focus === 'function') {
        (el as HTMLElement).focus();
      }
    },
    [ids],
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (enabledTabs.length === 0) return;
      const currentIdx = enabledTabs.findIndex((t) => t.id === activeId);
      const safeIdx = currentIdx === -1 ? 0 : currentIdx;
      let nextIdx: number | null = null;
      switch (e.key) {
        case 'ArrowLeft':
        case 'ArrowUp':
          nextIdx = (safeIdx - 1 + enabledTabs.length) % enabledTabs.length;
          break;
        case 'ArrowRight':
        case 'ArrowDown':
          nextIdx = (safeIdx + 1) % enabledTabs.length;
          break;
        case 'Home':
          nextIdx = 0;
          break;
        case 'End':
          nextIdx = enabledTabs.length - 1;
          break;
        default:
          return;
      }
      if (nextIdx === null) return;
      const next = enabledTabs[nextIdx];
      if (!next) return;
      e.preventDefault();
      e.stopPropagation();
      // WAI-ARIA "automatic activation" — moving focus also activates.
      // This matches the existing UX in the BIM tab strip (click swaps
      // the panel immediately) and keeps keyboard parity with mouse.
      onChange(next.id);
      focusTab(next.id);
    },
    [activeId, enabledTabs, focusTab, onChange],
  );

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={clsx(VARIANT_CLASSES[variant].container, className)}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeId;
        return (
          <button
            key={tab.id}
            id={ids.tabId(tab.id)}
            role="tab"
            type="button"
            aria-selected={isActive}
            aria-controls={ids.panelId(tab.id)}
            aria-disabled={tab.disabled || undefined}
            tabIndex={isActive ? 0 : -1}
            disabled={tab.disabled}
            onClick={() => !tab.disabled && onChange(tab.id)}
            data-testid={tprefix ? `${tprefix}-tab-${tab.id}` : undefined}
            className={clsx(
              tabButtonClasses({
                variant,
                size,
                isActive,
                disabled: !!tab.disabled,
                fullWidth,
              }),
              tabClassName,
            )}
          >
            {tab.icon}
            <span className="truncate">{tab.label}</span>
            {tab.badge !== undefined && tab.badge !== null && (
              <span className="ml-1">{tab.badge}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
