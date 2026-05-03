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
import { X, ClipboardList, Layers, Wrench, Folders, Sparkles } from 'lucide-react';
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
import { MatchSuggestionsPanel } from '@/features/match';
import type { MatchCandidate } from '@/features/match';
import type { BIMElementGroup } from './api';

interface BIMRightPanelTabsProps {
  modelId: string;
  elements: BIMElementData[];
  savedGroups: BIMElementGroup[];
  projectId: string;
  /** ID of the single selected element. The Properties tab uses this to show
   *  the element's key/value properties. */
  selectedElementId?: string | null;
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
  selectedElementId,
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
    {
      id: 'match',
      label: t('bim.tabs.match', { defaultValue: 'Match' }),
      icon: Sparkles,
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
          <PropertiesTabContent
            modelId={modelId}
            elements={elements}
            selectedElementId={selectedElementId ?? null}
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
        {activeTab === 'match' && (
          <MatchTabContent
            elements={elements}
            selectedElementId={selectedElementId ?? null}
            projectId={projectId}
          />
        )}
      </div>
    </div>
  );
}

/**
 * MatchTabContent — wraps MatchSuggestionsPanel with the BIM-specific
 * raw_element_data payload.  When no element is selected we show a
 * placeholder so the panel doesn't fire an empty match request.
 *
 * onAccept: Phase 4 will wire this to the BOQ-link mutation.  For now
 * we just log so the wiring is end-to-end testable; the toast inside
 * the panel covers user feedback.
 */
function MatchTabContent({
  elements,
  selectedElementId,
  projectId,
}: {
  elements: BIMElementData[];
  selectedElementId: string | null;
  projectId: string;
}) {
  const { t } = useTranslation();
  const selected = selectedElementId
    ? elements.find((e) => e.id === selectedElementId)
    : null;

  if (!selected) {
    return (
      <div className="px-3 py-4">
        <p className="text-[11px] text-content-tertiary italic">
          {t('bim.match_tab_no_selection', {
            defaultValue:
              'Select an element to see CWICR matches.',
          })}
        </p>
      </div>
    );
  }

  // The match service expects a free-form `raw_element_data` dict.  We
  // forward the BIM element straight through; the backend extractor
  // pulls description/category/quantities/properties out of the BIM
  // shape (`backend/app/core/match_service/extractors/bim.py`).
  const rawElementData: Record<string, unknown> = {
    id: selected.id,
    element_type: selected.element_type,
    name: selected.name,
    properties: (selected as { properties?: Record<string, unknown> }).properties ?? {},
    quantities: (selected as { quantities?: Record<string, number> }).quantities ?? {},
  };

  const onAccept = useCallback((candidate: MatchCandidate) => {
    // Phase 4 will replace this with the BOQ-link mutation.  For now we
    // just log so the wiring is observable in dev tools.

    console.info('[match] accepted candidate', { candidate, element: selected.id });
  }, [selected.id]);

  return (
    <MatchSuggestionsPanel
      source="bim"
      projectId={projectId}
      rawElementData={rawElementData}
      onAccept={onAccept}
      autoFetch
      compact={false}
    />
  );
}

/**
 * PropertiesTabContent — what the right-panel "Properties" tab actually
 * renders.
 *
 * Originally this slot rendered the Linked-BOQ list directly, which made
 * the tab label feel like a misnomer ("Properties" → BOQ links).  RFC 19
 * §UX-3: when the user has a single element selected the tab shows the
 * element's key/value properties up top; the Linked-BOQ list stays below
 * because it's the panel's primary integration view.  When nothing is
 * selected we fall back to the Linked-BOQ list alone — same behaviour as
 * before.
 *
 * Properties come from `selectedElement.properties` (already fetched by
 * BIMViewer) — no extra round-trip; if the element has no inline props we
 * show a friendly placeholder rather than fetching async (the BIMViewer's
 * own properties panel already handles the parquet round-trip for us).
 */
function PropertiesTabContent({
  modelId,
  elements,
  selectedElementId,
  onHighlightElements,
  onClose,
}: {
  modelId: string;
  elements: BIMElementData[];
  selectedElementId: string | null;
  onHighlightElements: (ids: string[]) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const selected = selectedElementId
    ? elements.find((e) => e.id === selectedElementId)
    : null;

  const propEntries = selected?.properties
    ? Object.entries(selected.properties as Record<string, unknown>)
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .sort(([a], [b]) => a.localeCompare(b))
    : [];

  return (
    <div className="flex flex-col">
      {selected ? (
        <section className="px-3 py-2 border-b border-border-light">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-content-tertiary mb-2">
            {t('bim.properties_tab_element', { defaultValue: 'Element properties' })}
          </h3>
          <div className="text-xs text-content-primary mb-1.5 truncate" title={selected.name ?? selected.id}>
            <span className="font-semibold">{selected.name || selected.element_type || selected.id}</span>
            {selected.element_type && selected.name ? (
              <span className="ml-1 text-content-tertiary">· {selected.element_type}</span>
            ) : null}
          </div>
          {propEntries.length > 0 ? (
            <dl
              className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]"
              data-testid="properties-tab-list"
            >
              {propEntries.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-content-tertiary truncate" title={k}>{k}</dt>
                  <dd className="text-content-primary truncate" title={String(v)}>{String(v)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p
              className="text-[11px] text-content-tertiary italic"
              data-testid="properties-tab-empty"
            >
              {t('bim.properties_tab_loading', {
                defaultValue:
                  'No inline properties — open the element panel for full details.',
              })}
            </p>
          )}
        </section>
      ) : (
        <section className="px-3 py-2 border-b border-border-light">
          <p className="text-[11px] text-content-tertiary italic">
            {t('bim.properties_tab_no_selection', {
              defaultValue: 'Select an element in the viewer to see its properties.',
            })}
          </p>
        </section>
      )}
      <BIMLinkedBOQPanel
        modelId={modelId}
        elements={elements}
        onHighlightElements={onHighlightElements}
        onClose={onClose}
      />
    </div>
  );
}
