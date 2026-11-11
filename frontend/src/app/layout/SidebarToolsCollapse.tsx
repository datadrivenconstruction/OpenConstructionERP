/**
 * Collapsible lower part of the sidebar (Settings / Users / About tiles,
 * update notice, GitHub and version row). The state is remembered on this
 * device; the menu editor forces it open because its "Edit menu" tile lives
 * inside.
 */
import { useCallback, useEffect, useId, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

export const SIDEBAR_TOOLS_KEY = 'oe_sidebar_tools_open_v1';

function readOpen(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_TOOLS_KEY) !== '0';
  } catch {
    return true;
  }
}

export function useSidebarToolsOpen(): [boolean, () => void] {
  const [open, setOpen] = useState<boolean>(readOpen);
  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_TOOLS_KEY, open ? '1' : '0');
    } catch {
      /* storage unavailable: applies until reload */
    }
  }, [open]);
  const toggle = useCallback(() => setOpen((v) => !v), []);
  return [open, toggle];
}

interface SidebarToolsCollapseProps {
  iconified: boolean;
  /** Keeps the region open regardless of the stored choice (menu editor). */
  forceOpen?: boolean;
  children: ReactNode;
}

export function SidebarToolsCollapse({ iconified, forceOpen = false, children }: SidebarToolsCollapseProps) {
  const { t } = useTranslation();
  const [storedOpen, toggle] = useSidebarToolsOpen();
  const open = storedOpen || forceOpen;
  const regionId = useId();
  const label = t('sidebar.tools_title', { defaultValue: 'Settings & tools' });
  const action = open
    ? t('sidebar.tools_collapse', { defaultValue: 'Collapse settings & tools' })
    : t('sidebar.tools_expand', { defaultValue: 'Expand settings & tools' });

  return (
    <>
      <button
        type="button"
        onClick={toggle}
        disabled={forceOpen}
        aria-expanded={open}
        aria-controls={regionId}
        aria-label={action}
        title={action}
        data-testid="sidebar-tools-toggle"
        className={clsx(
          'group mb-1 flex h-7 items-center rounded-md text-content-tertiary transition-colors duration-fast ease-oe',
          'hover:bg-surface-secondary hover:text-content-primary disabled:opacity-50',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
          iconified ? 'mx-auto w-8 justify-center' : 'w-full justify-between px-2',
        )}
      >
        {!iconified && (
          <span className="text-2xs font-medium uppercase tracking-wide">{label}</span>
        )}
        <ChevronDown
          size={14}
          strokeWidth={2}
          aria-hidden
          className={clsx(
            'shrink-0 transition-transform duration-normal ease-oe motion-reduce:transition-none',
            !open && '-rotate-90',
          )}
        />
      </button>
      <div
        id={regionId}
        data-testid="sidebar-tools-region"
        data-open={open}
        className={clsx(
          'grid transition-[grid-template-rows,opacity] duration-normal ease-oe motion-reduce:transition-none',
          open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
        aria-hidden={!open}
        {...(open ? {} : ({ inert: '' } as Record<string, string>))}
      >
        <div className="min-h-0 overflow-hidden">{children}</div>
      </div>
    </>
  );
}
