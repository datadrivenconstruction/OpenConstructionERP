/**
 * BIMRightPanelTabs — four-tab container for the BIM viewer right sidebar
 * (RFC 19 §4.5).
 *
 * Tabs:
 *   - Properties: existing linked-BOQ surface + selected-element detail
 *   - Layers: per-category opacity / visibility
 *   - Tools: measure tool + saved views
 *   - Groups: saved element groups
 */
import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { X, ClipboardList, Layers, Wrench, Folders } from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import {
  useBIMViewerStore,
  type BIMRightPanelTab,
} from '@/stores/useBIMViewerStore';
import type { Viewpoint as SavedViewpoint } from '@/shared/ui/BIMViewer';
import BIMLinkedBOQPanel from './BIMLinkedBOQPanel';
import BIMGroupsPanel from './BIMGroupsPanel';
import BIMLayersPanel from './BIMLayersPanel';
import BIMToolsPanel from './BIMToolsPanel';
import type { BIMElementGroup } from './api';

interface BIMRightPanelTabsProps {
  modelId: string;
  elements: BIMElementData[];
  savedGroups: BIMElementGroup[];
  projectId: string;
  onClose: () => void;
  onIsolateGroup: (g: BIMElementGroup) => void;
  onHighlightGroup: (g: BIMElementGroup | null) => void;
  onLinkGroupToBOQ: (g: BIMElementGroup) => void;
  onNavigateToBOQ: (positionId: string) => void;
  onDeleteGroup: (g: BIMElementGroup) => void;
  onGroupUpdated: () => void;
  onHighlightBOQElements: (ids: string[]) => void;
}

export default function BIMRightPanelTabs({
  modelId,
  elements,
  savedGroups,
  projectId,
  onClose,
  onIsolateGroup,
  onHighlightGroup,
  onLinkGroupToBOQ,
  onNavigateToBOQ,
  onDeleteGroup,
  onGroupUpdated,
  onHighlightBOQElements,
}: BIMRightPanelTabsProps) {
  const { t } = useTranslation();
  const activeTab = useBIMViewerStore((s) => s.rightPanelTab);
  const setRightPanelTab = useBIMViewerStore((s) => s.setRightPanelTab);

  const handleTabClick = useCallback(
    (tab: BIMRightPanelTab) => setRightPanelTab(tab),
    [setRightPanelTab],
  );

  // The measure/saved-view tool needs a camera snapshot + the ability to
  // restore one.  Rather than drill a SceneManager handle through the
  // component tree we use a tiny window-bound bridge: BIMViewer exposes
  // helpers on `window.__oeBim`.  The indirection keeps the store slim.
  const getCurrentViewpoint = useCallback(() => {
    const bridge = (window as unknown as {
      __oeBim?: {
        getViewpoint(): {
          position: { x: number; y: number; z: number };
          target: { x: number; y: number; z: number };
        } | null;
      };
    }).__oeBim;
    return bridge?.getViewpoint() ?? null;
  }, []);

  const onApplyViewpoint = useCallback((vp: SavedViewpoint) => {
    const bridge = (window as unknown as {
      __oeBim?: {
        setViewpoint(
          pos: { x: number; y: number; z: number },
          target: { x: number; y: number; z: number },
        ): void;
      };
    }).__oeBim;
    bridge?.setViewpoint(
      { x: vp.cameraPos[0], y: vp.cameraPos[1], z: vp.cameraPos[2] },
      { x: vp.target[0], y: vp.target[1], z: vp.target[2] },
    );
  }, []);

  const tabs: {
    id: BIMRightPanelTab;
    label: string;
    icon: typeof ClipboardList;
  }[] = [
    {
      id: 'properties',
      label: t('bim.tab_properties', { defaultValue: 'Properties' }),
      icon: ClipboardList,
    },
    {
      id: 'layers',
      label: t('bim.tab_layers', { defaultValue: 'Layers' }),
      icon: Layers,
    },
    {
      id: 'tools',
      label: t('bim.tab_tools', { defaultValue: 'Tools' }),
      icon: Wrench,
    },
    {
      id: 'groups',
      label: t('bim.tab_groups', { defaultValue: 'Groups' }),
      icon: Folders,
    },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Tab strip */}
      <div
        role="tablist"
        aria-label={t('bim.right_panel_tabs_aria', {
          defaultValue: 'BIM right panel tabs',
        })}
        className="flex items-stretch border-b border-border-light bg-surface-secondary"
      >
        {tabs.map(({ id, label, icon: Icon }) => {
          const isActive = activeTab === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => handleTabClick(id)}
              data-testid={`right-tab-${id}`}
              className={`flex-1 flex items-center justify-center gap-1 px-2 py-2 text-[11px] font-medium transition-colors ${
                isActive
                  ? 'text-oe-blue bg-surface-primary border-b-2 border-oe-blue'
                  : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-tertiary'
              }`}
            >
              <Icon size={12} />
              <span className="truncate">{label}</span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={onClose}
          aria-label={t('bim.right_panel_close', { defaultValue: 'Close panel' })}
          className="flex items-center justify-center px-2 text-content-tertiary hover:text-content-primary hover:bg-surface-tertiary"
        >
          <X size={14} />
        </button>
      </div>

      {/* Tab body */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {activeTab === 'properties' && (
          <BIMLinkedBOQPanel
            modelId={modelId}
            elements={elements}
            onHighlightElements={onHighlightBOQElements}
            onClose={onClose}
          />
        )}
        {activeTab === 'layers' && <BIMLayersPanel elements={elements} />}
        {activeTab === 'tools' && (
          <BIMToolsPanel
            modelId={modelId}
            getCurrentViewpoint={getCurrentViewpoint}
            onApplyViewpoint={onApplyViewpoint}
          />
        )}
        {activeTab === 'groups' && (
          <div className="p-2">
            {savedGroups.length === 0 ? (
              <p className="text-[11px] text-content-tertiary italic p-2">
                {t('bim.groups_empty', {
                  defaultValue:
                    'No saved groups yet — apply a filter and click "Save as group".',
                })}
              </p>
            ) : (
              <BIMGroupsPanel
                savedGroups={savedGroups}
                elements={elements}
                projectId={projectId}
                onIsolateGroup={onIsolateGroup}
                onHighlightGroup={onHighlightGroup}
                onLinkToBOQ={onLinkGroupToBOQ}
                onNavigateToBOQ={onNavigateToBOQ}
                onDeleteGroup={onDeleteGroup}
                onGroupUpdated={onGroupUpdated}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
