// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The slim row under the dock header: two tabs, Chat and Changes, and the
 * project the assistant is working in.
 *
 * The tabs follow the WAI-ARIA tabs pattern with automatic activation: one
 * Tab stop for the pair, the arrow keys move between them (mirrored in RTL,
 * where the row reads right to left), Home and End jump to the ends. The
 * Changes tab counts the proposals of this conversation that still wait for
 * a decision; the number is spelled out for screen readers, never left to
 * the badge colour.
 *
 * The project chip names the active project, or says that none is selected,
 * because every change the assistant prepares lands in that project.
 */
import { useRef, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { FolderOpen, ListChecks, MessageSquare } from 'lucide-react';
import { useIsRTL } from '@/shared/hooks/useIsRTL';

export type DockTab = 'chat' | 'changes';

const TABS: readonly DockTab[] = ['chat', 'changes'];

/** DOM ids of a tab and its panel, shared with the panel that renders the tabpanels. */
export function dockTabId(tab: DockTab): string {
  return `oe-ai-dock-tab-${tab}`;
}

export function dockTabPanelId(tab: DockTab): string {
  return `oe-ai-dock-tabpanel-${tab}`;
}

/** The tab an arrow, Home or End key moves to, or null for any other key. */
export function tabForKey(key: string, current: DockTab, rtl: boolean): DockTab | null {
  const index = TABS.indexOf(current);
  const last = TABS.length - 1;
  const forward = rtl ? 'ArrowLeft' : 'ArrowRight';
  const backward = rtl ? 'ArrowRight' : 'ArrowLeft';
  if (key === forward) return TABS[index === last ? 0 : index + 1] ?? null;
  if (key === backward) return TABS[index === 0 ? last : index - 1] ?? null;
  if (key === 'Home') return TABS[0] ?? null;
  if (key === 'End') return TABS[last] ?? null;
  return null;
}

export interface DockTabsRowProps {
  active: DockTab;
  onSelect: (tab: DockTab) => void;
  /** Proposals of this conversation still waiting for a decision. */
  waitingCount: number;
  projectId: string | null;
  projectName: string;
  onOpenProject: () => void;
}

export function DockTabsRow({
  active,
  onSelect,
  waitingCount,
  projectId,
  projectName,
  onOpenProject,
}: DockTabsRowProps) {
  const { t } = useTranslation();
  const isRTL = useIsRTL();
  const refs = useRef<Record<DockTab, HTMLButtonElement | null>>({ chat: null, changes: null });

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const next = tabForKey(e.key, active, isRTL);
    if (!next) return;
    e.preventDefault();
    onSelect(next);
    refs.current[next]?.focus();
  };

  const hasProject = !!projectId;
  const projectText = hasProject
    ? projectName || String(t('chat.dock.project_unnamed', { defaultValue: 'Active project' }))
    : String(t('chat.dock.no_project', { defaultValue: 'No project selected' }));
  const projectAction = hasProject
    ? String(t('chat.dock.open_project', { defaultValue: 'Open project {{name}}', name: projectText }))
    : String(t('chat.dock.choose_project', { defaultValue: 'Choose a project' }));

  const tabLabel = (tab: DockTab) =>
    tab === 'chat'
      ? t('chat.dock.tab_chat', { defaultValue: 'Chat' })
      : t('chat.dock.tab_changes', { defaultValue: 'Changes' });

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-[color:var(--chat-border-subtle)] bg-[color:var(--chat-surface-1)] px-2">
      <div
        role="tablist"
        aria-label={t('chat.dock.tabs_label', { defaultValue: 'Assistant views' })}
        className="inline-flex shrink-0 items-center gap-0.5 rounded-lg bg-[color:var(--chat-surface-2)] p-0.5"
      >
        {TABS.map((tab) => {
          const selected = active === tab;
          const Icon = tab === 'chat' ? MessageSquare : ListChecks;
          return (
            <button
              key={tab}
              ref={(el) => {
                refs.current[tab] = el;
              }}
              type="button"
              role="tab"
              id={dockTabId(tab)}
              aria-selected={selected}
              aria-controls={dockTabPanelId(tab)}
              tabIndex={selected ? 0 : -1}
              onClick={() => onSelect(tab)}
              onKeyDown={onKeyDown}
              data-testid={`floating-chat-tab-${tab}`}
              className={clsx(
                'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                selected
                  ? 'bg-[color:var(--chat-bg)] text-[color:var(--chat-text-primary)] shadow-xs'
                  : 'text-[color:var(--chat-text-secondary)] hover:text-[color:var(--chat-text-primary)]',
              )}
            >
              <Icon size={13} aria-hidden />
              <span>{tabLabel(tab)}</span>
              {tab === 'changes' && waitingCount > 0 && (
                <>
                  <span
                    aria-hidden
                    data-testid="floating-chat-changes-count"
                    className="inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-oe-blue px-1 text-[10px] font-semibold leading-none text-content-inverse tabular-nums"
                  >
                    {waitingCount > 99 ? '99+' : waitingCount}
                  </span>
                  <span className="sr-only">
                    {t('chat.dock.tab_changes_waiting', {
                      count: waitingCount,
                      defaultValue: '{{count}} waiting for review',
                      defaultValue_other: '{{count}} waiting for review',
                    })}
                  </span>
                </>
              )}
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={onOpenProject}
        title={hasProject ? `${projectText} · ${projectAction}` : projectAction}
        aria-label={hasProject ? projectAction : `${projectText}. ${projectAction}`}
        data-testid="floating-chat-project-chip"
        data-has-project={hasProject ? 'true' : 'false'}
        className={clsx(
          'ms-auto inline-flex h-7 min-w-0 max-w-[60%] items-center gap-1.5 rounded-full border px-2.5 text-xs transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
          hasProject
            ? 'border-[color:var(--chat-border)] bg-[color:var(--chat-bg)] font-medium text-[color:var(--chat-text-primary)] hover:border-oe-blue'
            : 'border-dashed border-[color:var(--chat-border)] text-[color:var(--chat-text-secondary)] hover:text-[color:var(--chat-text-primary)]',
        )}
      >
        <FolderOpen
          size={13}
          aria-hidden
          className={clsx('shrink-0', hasProject ? 'text-oe-blue' : 'text-[color:var(--chat-text-secondary)]')}
        />
        <span className="truncate">{projectText}</span>
      </button>
    </div>
  );
}
