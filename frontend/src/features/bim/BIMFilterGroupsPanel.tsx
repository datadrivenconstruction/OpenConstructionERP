/**
 * BIMFilterGroupsPanel — thin tabbed wrapper that merges the two
 * BIM sidebar panels (filters + saved groups) into a single
 * component with an internal tab switcher.
 *
 * Why:
 *   Previously BIMFilterPanel and BIMGroupsPanel lived side-by-side
 *   in the same sidebar column, splitting vertical space.  With
 *   tabs the user can give either panel the full height — and the
 *   groups panel shows a small count badge so the switch doesn't
 *   hide information.
 *
 * Design notes:
 *   - No URL persistence for the active tab (yet).  State is kept
 *     in `useState` local to this component.
 *   - Props are the SUPERSET of BIMFilterPanelProps and
 *     BIMGroupsPanelProps — we simply forward them down.
 *   - Tab button styling mirrors BIMRightPanelTabs (border-b-2,
 *     oe-blue active colour) so the two tab strips feel like the
 *     same component family.
 *   - The Groups tab is DISABLED (not hidden) when there are no
 *     saved groups — keeps the tab layout stable and signals the
 *     feature exists.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import BIMFilterPanel from './BIMFilterPanel';
import BIMGroupsPanel from './BIMGroupsPanel';
import type { BIMElementGroup } from './api';
import type { BIMFilterState } from './BIMFilterPanel';

type TabId = 'filters' | 'groups';

export interface BIMFilterGroupsPanelProps {
  /* ── Shared ────────────────────────────────────────────────── */
  elements: BIMElementData[];
  savedGroups: BIMElementGroup[];
  projectId: string;

  /* ── Filter panel props ─────────────────────────────────────── */
  modelId?: string;
  modelFormat?: string;
  onFilterChange: (
    predicate: (el: BIMElementData) => boolean,
    visibleCount: number,
  ) => void;
  onClose?: () => void;
  onElementClick?: (elementId: string) => void;
  onQuickTakeoff?: () => void;
  visibleElementCount?: number | null;
  onSaveAsGroup?: (filter: BIMFilterState, visibleElementIds: string[]) => void;
  onApplyGroup?: (group: BIMElementGroup) => void;
  onLinkGroupToBOQ?: (group: BIMElementGroup) => void;
  onDeleteGroup: (group: BIMElementGroup) => void;
  onSmartFilter?: (
    filterId: 'errors' | 'warnings' | 'unlinked_boq' | 'has_tasks' | 'has_docs',
  ) => void;
  isolatedIds?: string[] | null;
  onClearIsolation?: () => void;

  /* ── Groups panel props ─────────────────────────────────────── */
  onIsolateGroup: (group: BIMElementGroup) => void;
  onHighlightGroup: (group: BIMElementGroup | null) => void;
  onNavigateToBOQ: (positionId: string) => void;
  onCreateGroup?: () => void;
  onGroupUpdated?: () => void;
}

export default function BIMFilterGroupsPanel(props: BIMFilterGroupsPanelProps) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabId>('filters');

  const groupsCount = props.savedGroups.length;

  const tabs: { id: TabId; label: string }[] = [
    {
      id: 'filters',
      label: t('bim.tab_filters', { defaultValue: 'Filters' }),
    },
    {
      id: 'groups',
      label: t('bim.tab_groups', { defaultValue: 'Groups' }),
    },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Tab strip — styling mirrors BIMRightPanelTabs. */}
      <div
        role="tablist"
        aria-label={t('bim.filter_groups_tabs_aria', {
          defaultValue: 'Filter and groups tabs',
        })}
        className="flex items-stretch border-b border-border-light bg-surface-secondary"
      >
        {tabs.map(({ id, label }) => {
          const isActive = activeTab === id;
          const showBadge = id === 'groups' && groupsCount > 0;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(id)}
              data-testid={`bim-filter-groups-tab-${id}`}
              className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-2 text-[11px] font-medium transition-colors ${
                isActive
                  ? 'text-oe-blue bg-surface-primary border-b-2 border-oe-blue'
                  : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-tertiary'
              }`}
            >
              <span className="truncate">{label}</span>
              {showBadge && (
                <span
                  className={`inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded-full text-[9px] font-semibold ${
                    isActive
                      ? 'bg-oe-blue text-white'
                      : 'bg-surface-tertiary text-content-secondary'
                  }`}
                  aria-label={t('bim.groups_count_badge', {
                    defaultValue: '{{count}} saved groups',
                    count: groupsCount,
                  })}
                >
                  {groupsCount}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab body — keep the inactive panel unmounted so its internal
          state (search input, expanded headers, etc.) resets the next
          time the user switches back.  For a lightweight sidebar this
          is cheaper and clearer than using `hidden` with mounted state. */}
      <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
        {activeTab === 'filters' && (
          <BIMFilterPanel
            elements={props.elements}
            modelId={props.modelId}
            modelFormat={props.modelFormat}
            onFilterChange={props.onFilterChange}
            onClose={props.onClose}
            onElementClick={props.onElementClick}
            onQuickTakeoff={props.onQuickTakeoff}
            visibleElementCount={props.visibleElementCount}
            onSaveAsGroup={props.onSaveAsGroup}
            savedGroups={props.savedGroups}
            onApplyGroup={props.onApplyGroup}
            onLinkGroupToBOQ={props.onLinkGroupToBOQ}
            onDeleteGroup={props.onDeleteGroup}
            onSmartFilter={props.onSmartFilter}
            isolatedIds={props.isolatedIds}
            onClearIsolation={props.onClearIsolation}
          />
        )}
        {activeTab === 'groups' && (
          <BIMGroupsPanel
            savedGroups={props.savedGroups}
            elements={props.elements}
            projectId={props.projectId}
            onIsolateGroup={props.onIsolateGroup}
            onHighlightGroup={props.onHighlightGroup}
            onLinkToBOQ={props.onLinkGroupToBOQ ?? (() => {})}
            onNavigateToBOQ={props.onNavigateToBOQ}
            onCreateGroup={props.onCreateGroup}
            onDeleteGroup={props.onDeleteGroup}
            onGroupUpdated={props.onGroupUpdated}
          />
        )}
      </div>
    </div>
  );
}
