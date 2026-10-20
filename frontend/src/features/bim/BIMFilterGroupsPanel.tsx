// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
import { Layers } from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import BIMFilterPanel from './BIMFilterPanel';
import BIMGroupsPanel from './BIMGroupsPanel';
import type { BIMElementGroup } from './api';
import type { BIMFilterState } from './BIMFilterPanel';

type TabId = 'filters' | 'groups';
const FILTER_GROUPS_TAB_IDS: readonly TabId[] = ['filters', 'groups'];

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
  onSaveAsGroup?: (
    filter: BIMFilterState,
    visibleElements: BIMElementData[],
  ) => void;
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
  /** Open a new quantity rule fed by the group, for a BOQ position. */
  onUseGroupAsQuantity?: (g: BIMElementGroup) => void;
}

export default function BIMFilterGroupsPanel(props: BIMFilterGroupsPanelProps) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabId>('filters');
  const onTabKeyDown = useTabKeyboardNav<TabId>({
    ids: FILTER_GROUPS_TAB_IDS,
    activeId: activeTab,
    onChange: setActiveTab,
    orientation: 'horizontal',
  });

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
        onKeyDown={onTabKeyDown}
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
              id={`bim-filter-groups-tab-${id}`}
              aria-selected={isActive}
              aria-controls={`bim-filter-groups-panel-${id}`}
              tabIndex={isActive ? 0 : -1}
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
        {activeTab === 'groups' && groupsCount === 0 && !props.onCreateGroup && (
          // BIMGroupsPanel renders nothing without groups, which collapsed
          // the sidebar to a bare strip. Say what a group is and where to make one.
          <div
            data-testid="bim-groups-empty"
            className="flex flex-col items-center text-center gap-2 px-5 py-8 w-[280px] bg-surface-primary"
          >
            <Layers size={22} className="text-content-quaternary" />
            <p className="text-xs font-semibold text-content-primary">
              {t('bim.groups_empty_title', { defaultValue: 'No saved groups yet' })}
            </p>
            <p className="text-[11px] text-content-tertiary">
              {t('bim.groups_empty_desc', {
                defaultValue:
                  'Filter the model to the elements you need, then click "Save as group" to reuse the selection for linking and quantities.',
              })}
            </p>
            <button
              type="button"
              onClick={() => setActiveTab('filters')}
              className="mt-1 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-oe-blue text-white hover:bg-oe-blue-dark"
            >
              {t('bim.groups_empty_cta', { defaultValue: 'Open filters' })}
            </button>
          </div>
        )}
        {activeTab === 'groups' && (groupsCount > 0 || !!props.onCreateGroup) && (
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
            onUseAsQuantitySource={props.onUseGroupAsQuantity}
          />
        )}
      </div>
    </div>
  );
}
