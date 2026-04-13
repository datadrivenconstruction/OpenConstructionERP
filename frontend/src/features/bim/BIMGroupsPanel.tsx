/**
 * BIMGroupsPanel -- dedicated panel showing all saved element groups with
 * aggregate quantities, BOQ links, and one-click 3D isolation.
 *
 * Sits below or alongside the BIMFilterPanel in the BIM viewport sidebar.
 * Each group row shows: color dot, name, element count, expandable details
 * with volume/area/length aggregates and linked BOQ positions.
 */

import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Bookmark,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Link2,
  MoreVertical,
  Pencil,
  Palette,
  Trash2,
  Download,
  Plus,
  Box,
  Ruler,
  Layers,
} from 'lucide-react';
import type { BIMElementGroup } from './api';
import { updateElementGroup } from './api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';

/* ── Constants ──────────────────────────────────────────────────────────── */

const GROUP_COLORS = [
  '#2979ff',
  '#4caf50',
  '#ff9800',
  '#f44336',
  '#9c27b0',
  '#00bcd4',
  '#795548',
  '#607d8b',
];

/* ── Types ──────────────────────────────────────────────────────────────── */

interface GroupQuantities {
  volume: number;
  area: number;
  length: number;
}

interface GroupBOQLink {
  positionId: string;
  ordinal: string;
  description: string;
  total: number;
}

interface ContextMenuState {
  groupId: string;
  x: number;
  y: number;
}

/* ── Props ──────────────────────────────────────────────────────────────── */

export interface BIMGroupsPanelProps {
  savedGroups: BIMElementGroup[];
  elements: BIMElementData[];
  projectId: string;
  /** Isolate the group's member elements in 3D. */
  onIsolateGroup: (group: BIMElementGroup) => void;
  /** Highlight the group's elements on hover (without isolating). */
  onHighlightGroup: (group: BIMElementGroup | null) => void;
  /** Open AddToBOQModal pre-populated with the group's elements. */
  onLinkToBOQ: (group: BIMElementGroup) => void;
  /** Navigate to the BOQ editor at the given position. */
  onNavigateToBOQ: (positionId: string) => void;
  /** Open the save-group modal to create a new group from selection. */
  onCreateGroup?: () => void;
  /** Delete a group. */
  onDeleteGroup: (group: BIMElementGroup) => void;
  /** Called after a successful rename / color change so the parent can
   *  invalidate the query cache. */
  onGroupUpdated?: () => void;
}

/* ── Component ──────────────────────────────────────────────────────────── */

export default function BIMGroupsPanel({
  savedGroups,
  elements,
  // projectId reserved for future use (e.g. group-scoped queries)
  projectId: _projectId,
  onIsolateGroup,
  onHighlightGroup,
  onLinkToBOQ,
  onNavigateToBOQ,
  onCreateGroup,
  onDeleteGroup,
  onGroupUpdated,
}: BIMGroupsPanelProps) {
  void _projectId;
  const { t } = useTranslation();
  const [panelExpanded, setPanelExpanded] = useState(true);
  const [expandedGroupIds, setExpandedGroupIds] = useState<Set<string>>(new Set());
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingGroupId, setRenamingGroupId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [colorPickerGroupId, setColorPickerGroupId] = useState<string | null>(null);
  const contextMenuRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  // Build element map for fast lookup
  const elementMap = useMemo(() => {
    const map = new Map<string, BIMElementData>();
    for (const el of elements) {
      map.set(el.id, el);
    }
    return map;
  }, [elements]);

  // Aggregate quantities per group
  const groupQuantities = useMemo(() => {
    const result = new Map<string, GroupQuantities>();
    for (const group of savedGroups) {
      let vol = 0;
      let area = 0;
      let len = 0;
      for (const elId of group.member_element_ids) {
        const el = elementMap.get(elId);
        if (el?.quantities) {
          const q = el.quantities as Record<string, number>;
          vol += q.volume_m3 ?? q.Volume ?? q.volume ?? 0;
          area += q.area_m2 ?? q.Area ?? q.area ?? 0;
          len += q.length_m ?? q.Length ?? q.length ?? 0;
        }
      }
      result.set(group.id, { volume: vol, area: area, length: len });
    }
    return result;
  }, [savedGroups, elementMap]);

  // Resolve BOQ links per group from member elements
  const groupBOQLinks = useMemo(() => {
    const result = new Map<string, GroupBOQLink[]>();
    for (const group of savedGroups) {
      const links: GroupBOQLink[] = [];
      const seen = new Set<string>();
      for (const elId of group.member_element_ids) {
        const el = elementMap.get(elId);
        if (el?.boq_links?.length) {
          for (const link of el.boq_links) {
            if (!seen.has(link.boq_position_id)) {
              seen.add(link.boq_position_id);
              links.push({
                positionId: link.boq_position_id,
                ordinal: link.boq_position_ordinal || '',
                description: link.boq_position_description || '',
                total: 0,
              });
            }
          }
        }
      }
      result.set(group.id, links);
    }
    return result;
  }, [savedGroups, elementMap]);

  // Toggle expanded state for a group
  const toggleGroupExpanded = useCallback((groupId: string) => {
    setExpandedGroupIds((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }, []);

  // Close context menu on outside click
  useEffect(() => {
    if (!contextMenu) return;
    const handler = (e: MouseEvent) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target as Node)) {
        setContextMenu(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [contextMenu]);

  // Focus rename input when it appears
  useEffect(() => {
    if (renamingGroupId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renamingGroupId]);

  const handleContextMenu = useCallback((e: React.MouseEvent, groupId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ groupId, x: e.clientX, y: e.clientY });
  }, []);

  const handleStartRename = useCallback(
    (group: BIMElementGroup) => {
      setRenamingGroupId(group.id);
      setRenameValue(group.name);
      setContextMenu(null);
    },
    [],
  );

  const handleConfirmRename = useCallback(
    async (groupId: string) => {
      const trimmed = renameValue.trim();
      if (!trimmed) {
        setRenamingGroupId(null);
        return;
      }
      try {
        await updateElementGroup(groupId, { name: trimmed });
        onGroupUpdated?.();
      } catch {
        // silently fail -- user will see name revert on next fetch
      }
      setRenamingGroupId(null);
    },
    [renameValue, onGroupUpdated],
  );

  const handleColorChange = useCallback(
    async (groupId: string, newColor: string) => {
      try {
        await updateElementGroup(groupId, { color: newColor });
        onGroupUpdated?.();
      } catch {
        // silently fail
      }
      setColorPickerGroupId(null);
      setContextMenu(null);
    },
    [onGroupUpdated],
  );

  const handleExportCSV = useCallback(
    (group: BIMElementGroup) => {
      const rows: string[] = ['id,name,element_type,storey'];
      for (const elId of group.member_element_ids) {
        const el = elementMap.get(elId);
        if (el) {
          const name = (el.name || '').replace(/,/g, ';');
          rows.push(`${el.id},${name},${el.element_type || ''},${el.storey || ''}`);
        }
      }
      const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${group.name.replace(/\s+/g, '_')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      setContextMenu(null);
    },
    [elementMap],
  );

  /** Format a number with locale separators and 1 decimal place. */
  const fmt = useCallback(
    (n: number): string => n.toLocaleString(undefined, { maximumFractionDigits: 1 }),
    [],
  );

  if (savedGroups.length === 0 && !onCreateGroup) return null;

  return (
    <div className="border-b border-border-light bg-surface-primary">
      {/* Header */}
      <button
        type="button"
        onClick={() => setPanelExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-1.5 px-4 py-3"
      >
        <div className="flex items-center gap-1.5">
          <Bookmark size={12} className="text-oe-blue" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('bim.saved_groups', { defaultValue: 'Saved groups' })}
          </span>
          <span className="text-[10px] text-content-quaternary tabular-nums">
            ({savedGroups.length})
          </span>
        </div>
        {panelExpanded ? (
          <ChevronDown size={11} className="text-content-tertiary" />
        ) : (
          <ChevronRight size={11} className="text-content-tertiary" />
        )}
      </button>

      {panelExpanded && (
        <div className="px-3 pb-3 space-y-1">
          {savedGroups.map((group) => {
            const isExpanded = expandedGroupIds.has(group.id);
            const quantities = groupQuantities.get(group.id);
            const boqLinks = groupBOQLinks.get(group.id) ?? [];
            const hasQuantities =
              quantities && (quantities.volume > 0 || quantities.area > 0 || quantities.length > 0);
            const isRenaming = renamingGroupId === group.id;
            const showColorPicker = colorPickerGroupId === group.id;

            return (
              <div
                key={group.id}
                className="rounded-md border border-border-light bg-surface-secondary/50 transition-colors hover:bg-surface-secondary"
                onMouseEnter={() => onHighlightGroup(group)}
                onMouseLeave={() => onHighlightGroup(null)}
                onContextMenu={(e) => handleContextMenu(e, group.id)}
              >
                {/* Group row */}
                <div className="flex items-center gap-1.5 px-2 py-1.5">
                  {/* Expand/collapse arrow */}
                  <button
                    type="button"
                    onClick={() => toggleGroupExpanded(group.id)}
                    className="shrink-0 p-0.5 rounded text-content-quaternary hover:text-content-secondary"
                  >
                    {isExpanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                  </button>

                  {/* Color dot */}
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                    style={{ background: group.color || '#2979ff' }}
                  />

                  {/* Name (or rename input) */}
                  {isRenaming ? (
                    <input
                      ref={renameInputRef}
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={() => handleConfirmRename(group.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleConfirmRename(group.id);
                        if (e.key === 'Escape') setRenamingGroupId(null);
                      }}
                      className="flex-1 min-w-0 text-[11px] px-1 py-0.5 rounded border border-oe-blue bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => onIsolateGroup(group)}
                      className="flex-1 min-w-0 text-left text-[11px] font-medium text-content-primary truncate"
                      title={t('bim.groups_click_isolate', {
                        defaultValue: 'Click to isolate in 3D',
                      })}
                    >
                      {group.name}
                    </button>
                  )}

                  {/* Element count */}
                  <span className="text-[10px] text-content-quaternary tabular-nums shrink-0">
                    {group.element_count.toLocaleString()}
                  </span>

                  {/* Context menu trigger */}
                  <button
                    type="button"
                    onClick={(e) => handleContextMenu(e, group.id)}
                    className="shrink-0 p-0.5 rounded text-content-quaternary hover:text-content-secondary opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ opacity: contextMenu?.groupId === group.id ? 1 : undefined }}
                  >
                    <MoreVertical size={11} />
                  </button>
                </div>

                {/* Expanded details */}
                {isExpanded && (
                  <div className="px-2 pb-2 pt-0.5 space-y-1.5">
                    {/* Aggregate quantities */}
                    {hasQuantities && (
                      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-content-tertiary px-1">
                        {quantities.volume > 0 && (
                          <span className="inline-flex items-center gap-0.5">
                            <Box size={9} className="opacity-60" />
                            {fmt(quantities.volume)} m{'\u00B3'}
                          </span>
                        )}
                        {quantities.area > 0 && (
                          <span className="inline-flex items-center gap-0.5">
                            <Layers size={9} className="opacity-60" />
                            {fmt(quantities.area)} m{'\u00B2'}
                          </span>
                        )}
                        {quantities.length > 0 && (
                          <span className="inline-flex items-center gap-0.5">
                            <Ruler size={9} className="opacity-60" />
                            {fmt(quantities.length)} m
                          </span>
                        )}
                      </div>
                    )}

                    {/* BOQ links */}
                    {boqLinks.length > 0 ? (
                      <div className="space-y-0.5 px-1">
                        {boqLinks.map((link) => (
                          <div
                            key={link.positionId}
                            className="flex items-center gap-1 text-[10px]"
                          >
                            <Link2 size={9} className="text-oe-blue shrink-0" />
                            <span className="text-content-secondary truncate">
                              {t('bim.groups_boq_label', { defaultValue: 'BOQ' })}{' '}
                              {link.ordinal || link.positionId.slice(0, 8)}
                              {link.description ? ` - ${link.description}` : ''}
                            </span>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onNavigateToBOQ(link.positionId);
                              }}
                              className="shrink-0 ml-auto inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium text-oe-blue hover:bg-oe-blue/10 transition-colors"
                            >
                              {t('bim.groups_open', { defaultValue: 'Open' })}
                              <ExternalLink size={8} />
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 px-1 text-[10px] text-content-quaternary">
                        <span>
                          {t('bim.groups_not_linked', { defaultValue: 'Not linked to BOQ' })}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onLinkToBOQ(group);
                          }}
                          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium text-oe-blue hover:bg-oe-blue/10 transition-colors"
                        >
                          <Plus size={8} />
                          {t('bim.groups_link_boq', { defaultValue: 'Link BOQ' })}
                        </button>
                      </div>
                    )}

                    {/* Color picker (inline, toggled via context menu) */}
                    {showColorPicker && (
                      <div className="flex items-center gap-1 px-1 pt-1">
                        {GROUP_COLORS.map((c) => (
                          <button
                            key={c}
                            type="button"
                            onClick={() => handleColorChange(group.id, c)}
                            className={`h-4 w-4 rounded-full border-2 transition-transform hover:scale-125 ${
                              (group.color || '#2979ff') === c
                                ? 'border-content-primary scale-110'
                                : 'border-transparent'
                            }`}
                            style={{ background: c }}
                            title={c}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Create new group button */}
          {onCreateGroup && (
            <button
              type="button"
              onClick={onCreateGroup}
              className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md border border-dashed border-border-light text-[10px] text-content-tertiary hover:text-oe-blue hover:border-oe-blue/40 transition-colors"
            >
              <Plus size={10} />
              {t('bim.groups_new_from_selection', {
                defaultValue: 'New group from selection',
              })}
            </button>
          )}
        </div>
      )}

      {/* Context menu (positioned absolutely in the viewport) */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className="fixed z-50 min-w-[140px] rounded-md border border-border-light bg-surface-primary shadow-lg py-1"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          {(() => {
            const group = savedGroups.find((g) => g.id === contextMenu.groupId);
            if (!group) return null;
            return (
              <>
                <button
                  type="button"
                  onClick={() => handleStartRename(group)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-content-primary hover:bg-surface-secondary"
                >
                  <Pencil size={11} />
                  {t('bim.groups_rename', { defaultValue: 'Rename' })}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setColorPickerGroupId((prev) =>
                      prev === group.id ? null : group.id,
                    );
                    if (!expandedGroupIds.has(group.id)) {
                      setExpandedGroupIds((prev) => new Set([...prev, group.id]));
                    }
                    setContextMenu(null);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-content-primary hover:bg-surface-secondary"
                >
                  <Palette size={11} />
                  {t('bim.groups_change_color', { defaultValue: 'Change color' })}
                </button>
                <button
                  type="button"
                  onClick={() => handleExportCSV(group)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-content-primary hover:bg-surface-secondary"
                >
                  <Download size={11} />
                  {t('bim.groups_export_csv', { defaultValue: 'Export CSV' })}
                </button>
                <div className="my-1 border-t border-border-light" />
                <button
                  type="button"
                  onClick={() => {
                    setContextMenu(null);
                    onDeleteGroup(group);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-rose-600 hover:bg-rose-50"
                >
                  <Trash2 size={11} />
                  {t('bim.groups_delete', { defaultValue: 'Delete' })}
                </button>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}

export { GROUP_COLORS };
