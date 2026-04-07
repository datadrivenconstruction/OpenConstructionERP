/**
 * BIMPage — split-view BIM Hub page.
 *
 * Left panel: model list + element tree (grouped by storey > discipline > type).
 * Right panel: Three.js BIM Viewer.
 *
 * Route: /projects/:projectId/bim  or  /bim  (uses project context store)
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Box,
  ChevronRight,
  ChevronDown,
  Layers,
  Building2,
  Loader2,
  FolderOpen,
  Link2,
  Search,
} from 'lucide-react';
import { Button, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { BIMViewer, DisciplineToggle } from '@/shared/ui/BIMViewer';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchBIMModels, fetchBIMElements } from './api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface TreeNode {
  key: string;
  label: string;
  type: 'storey' | 'discipline' | 'element_type' | 'element';
  children: TreeNode[];
  elementId?: string;
  count?: number;
}

/* ── Tree Builder ──────────────────────────────────────────────────────── */

function buildElementTree(elements: BIMElementData[]): TreeNode[] {
  // Group: storey > discipline > element_type > elements
  const storeyMap = new Map<string, Map<string, Map<string, BIMElementData[]>>>();

  for (const el of elements) {
    const storey = el.storey || 'Unassigned';
    const discipline = el.discipline || 'Other';
    const elType = el.element_type || 'Unknown';

    if (!storeyMap.has(storey)) storeyMap.set(storey, new Map());
    const discMap = storeyMap.get(storey)!;
    if (!discMap.has(discipline)) discMap.set(discipline, new Map());
    const typeMap = discMap.get(discipline)!;
    if (!typeMap.has(elType)) typeMap.set(elType, []);
    typeMap.get(elType)!.push(el);
  }

  const tree: TreeNode[] = [];
  for (const [storey, discMap] of storeyMap) {
    const storeyChildren: TreeNode[] = [];
    let storeyCount = 0;

    for (const [discipline, typeMap] of discMap) {
      const discChildren: TreeNode[] = [];
      let discCount = 0;

      for (const [elType, els] of typeMap) {
        const typeChildren: TreeNode[] = els.map((el) => ({
          key: `el-${el.id}`,
          label: el.name || el.id,
          type: 'element' as const,
          children: [],
          elementId: el.id,
        }));
        discCount += els.length;
        discChildren.push({
          key: `type-${storey}-${discipline}-${elType}`,
          label: elType,
          type: 'element_type',
          children: typeChildren,
          count: els.length,
        });
      }

      storeyCount += discCount;
      storeyChildren.push({
        key: `disc-${storey}-${discipline}`,
        label: discipline,
        type: 'discipline',
        children: discChildren,
        count: discCount,
      });
    }

    tree.push({
      key: `storey-${storey}`,
      label: storey,
      type: 'storey',
      children: storeyChildren,
      count: storeyCount,
    });
  }

  return tree;
}

/* ── Tree Node Component ───────────────────────────────────────────────── */

function TreeItem({
  node,
  selectedId,
  expandedKeys,
  onToggle,
  onSelect,
  depth = 0,
}: {
  node: TreeNode;
  selectedId: string | null;
  expandedKeys: Set<string>;
  onToggle: (key: string) => void;
  onSelect: (elementId: string) => void;
  depth?: number;
}) {
  const isExpanded = expandedKeys.has(node.key);
  const hasChildren = node.children.length > 0;
  const isElement = node.type === 'element';
  const isSelected = isElement && node.elementId === selectedId;

  return (
    <div>
      <button
        onClick={() => {
          if (isElement && node.elementId) {
            onSelect(node.elementId);
          } else if (hasChildren) {
            onToggle(node.key);
          }
        }}
        className={`flex items-center gap-1.5 w-full text-start text-xs py-1 px-1.5 rounded transition-colors ${
          isSelected
            ? 'bg-oe-blue-subtle text-oe-blue font-medium'
            : 'text-content-secondary hover:bg-surface-secondary'
        }`}
        style={{ paddingInlineStart: `${depth * 16 + 6}px` }}
      >
        {hasChildren && (
          isExpanded
            ? <ChevronDown size={12} className="shrink-0 text-content-tertiary" />
            : <ChevronRight size={12} className="shrink-0 text-content-tertiary" />
        )}
        {!hasChildren && <span className="w-3 shrink-0" />}

        {node.type === 'storey' && <Building2 size={13} className="shrink-0 text-content-tertiary" />}
        {node.type === 'discipline' && <Layers size={13} className="shrink-0 text-content-tertiary" />}
        {node.type === 'element_type' && <FolderOpen size={12} className="shrink-0 text-content-tertiary" />}
        {node.type === 'element' && <Box size={12} className="shrink-0 text-content-tertiary" />}

        <span className="truncate">{node.label}</span>

        {node.count != null && (
          <span className="ms-auto text-2xs text-content-quaternary tabular-nums shrink-0">
            {node.count}
          </span>
        )}
      </button>

      {isExpanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeItem
              key={child.key}
              node={child}
              selectedId={selectedId}
              expandedKeys={expandedKeys}
              onToggle={onToggle}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Model Card ────────────────────────────────────────────────────────── */

function ModelCard({
  model,
  isActive,
  onClick,
}: {
  model: BIMModelData;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-start p-3 rounded-lg border transition-colors ${
        isActive
          ? 'border-oe-blue bg-oe-blue-subtle'
          : 'border-border-light hover:border-border-medium hover:bg-surface-secondary'
      }`}
    >
      <div className="flex items-center gap-2">
        <Box size={16} className={isActive ? 'text-oe-blue' : 'text-content-tertiary'} />
        <span className="text-sm font-medium text-content-primary truncate">{model.name}</span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        <Badge variant={model.status === 'ready' ? 'success' : 'warning'} size="sm">
          {model.status}
        </Badge>
        <span className="text-2xs text-content-tertiary">{model.format?.toUpperCase()}</span>
        <span className="text-2xs text-content-quaternary truncate">{model.filename}</span>
      </div>
    </button>
  );
}

/* ── BIM Page ──────────────────────────────────────────────────────────── */

export function BIMPage() {
  const { t } = useTranslation();
  const { projectId: urlProjectId } = useParams<{ projectId: string }>();
  const contextProjectId = useProjectContextStore((s) => s.activeProjectId);
  const contextProjectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = urlProjectId || contextProjectId || '';

  const [activeModelId, setActiveModelId] = useState<string | null>(null);
  const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [disciplineVisibility, setDisciplineVisibility] = useState<Record<string, boolean>>({});

  // Fetch models
  const modelsQuery = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: !!projectId,
  });

  // Auto-select first model
  useEffect(() => {
    if (modelsQuery.data?.models?.length && !activeModelId) {
      const first = modelsQuery.data.models[0];
      if (first) setActiveModelId(first.id);
    }
  }, [modelsQuery.data, activeModelId]);

  // Fetch elements for active model
  const elementsQuery = useQuery({
    queryKey: ['bim-elements', activeModelId],
    queryFn: () => fetchBIMElements(activeModelId!),
    enabled: !!activeModelId,
  });

  const elements: BIMElementData[] = elementsQuery.data?.elements ?? [];

  // Build tree
  const tree = useMemo(() => buildElementTree(elements), [elements]);

  // Get disciplines
  const disciplines = useMemo(() => {
    const set = new Set<string>();
    for (const el of elements) {
      if (el.discipline) set.add(el.discipline);
    }
    return Array.from(set).sort();
  }, [elements]);

  // Search filter for tree
  const filteredTree = useMemo(() => {
    if (!searchQuery.trim()) return tree;
    const q = searchQuery.toLowerCase();

    function filterNode(node: TreeNode): TreeNode | null {
      if (node.type === 'element') {
        const matches = node.label.toLowerCase().includes(q);
        return matches ? node : null;
      }
      const filteredChildren = node.children
        .map(filterNode)
        .filter((n): n is TreeNode => n !== null);
      if (filteredChildren.length === 0) return null;
      return { ...node, children: filteredChildren, count: filteredChildren.length };
    }

    return tree.map(filterNode).filter((n): n is TreeNode => n !== null);
  }, [tree, searchQuery]);

  // Handlers
  const handleToggleNode = useCallback((key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const handleElementSelect = useCallback((elementId: string | null) => {
    setSelectedElementId(elementId);
  }, []);

  const handleTreeSelect = useCallback((elementId: string) => {
    setSelectedElementId(elementId);
  }, []);

  const handleDisciplineToggle = useCallback((discipline: string) => {
    setDisciplineVisibility((prev) => ({
      ...prev,
      [discipline]: prev[discipline] === false ? true : false,
    }));
  }, []);

  // Breadcrumb
  const breadcrumbItems = useMemo(() => {
    const items = [
      { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
    ];
    if (projectId && contextProjectName) {
      items.push({
        label: contextProjectName,
        to: `/projects/${projectId}`,
      });
    }
    items.push({ label: t('bim.title', { defaultValue: 'BIM Viewer' }), to: '' });
    return items;
  }, [t, projectId, contextProjectName]);

  // Selected element IDs for the viewer
  const selectedElementIds = useMemo(
    () => (selectedElementId ? [selectedElementId] : []),
    [selectedElementId],
  );

  // No project selected
  if (!projectId) {
    return (
      <div className="p-6">
        <Breadcrumb items={breadcrumbItems} />
        <EmptyState
          icon={<FolderOpen size={28} />}
          title={t('bim.no_project', { defaultValue: 'No project selected' })}
          description={t('bim.no_project_desc', {
            defaultValue: 'Select a project to view BIM models.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 pt-4 pb-3 border-b border-border-light">
        <Breadcrumb items={breadcrumbItems} />
        <div className="flex items-center justify-between mt-2">
          <h1 className="text-xl font-bold text-content-primary">
            {t('bim.title', { defaultValue: 'BIM Viewer' })}
          </h1>
          {selectedElementId && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                /* Link to BOQ — future implementation */
              }}
            >
              <Link2 size={14} className="me-1.5" />
              {t('bim.link_to_boq', { defaultValue: 'Link to BOQ' })}
            </Button>
          )}
        </div>
      </div>

      {/* Split layout */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel — model list + element tree */}
        <div className="w-80 shrink-0 border-e border-border-light bg-surface-primary overflow-y-auto">
          {/* Models section */}
          <div className="p-3 border-b border-border-light">
            <h2 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider mb-2">
              {t('bim.models', { defaultValue: 'Models' })}
            </h2>
            {modelsQuery.isLoading ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 size={20} className="animate-spin text-content-tertiary" />
              </div>
            ) : modelsQuery.data?.models?.length ? (
              <div className="space-y-2">
                {modelsQuery.data.models.map((model) => (
                  <ModelCard
                    key={model.id}
                    model={model}
                    isActive={model.id === activeModelId}
                    onClick={() => {
                      setActiveModelId(model.id);
                      setSelectedElementId(null);
                    }}
                  />
                ))}
              </div>
            ) : (
              <p className="text-xs text-content-tertiary py-4 text-center">
                {t('bim.no_models', { defaultValue: 'No models uploaded yet' })}
              </p>
            )}
          </div>

          {/* Search */}
          {elements.length > 0 && (
            <div className="p-3 border-b border-border-light">
              <div className="relative">
                <Search size={14} className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t('bim.search_elements', { defaultValue: 'Search elements...' })}
                  className="w-full text-xs py-1.5 ps-8 pe-3 rounded-lg border border-border-light bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </div>
            </div>
          )}

          {/* Discipline toggles */}
          {disciplines.length > 0 && (
            <div className="p-3 border-b border-border-light">
              <DisciplineToggle
                disciplines={disciplines}
                visible={disciplineVisibility}
                onToggle={handleDisciplineToggle}
              />
            </div>
          )}

          {/* Element tree */}
          <div className="p-2">
            <h2 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider px-1.5 mb-1">
              {t('bim.element_tree', { defaultValue: 'Element Tree' })}
            </h2>
            {elementsQuery.isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 size={20} className="animate-spin text-content-tertiary" />
              </div>
            ) : filteredTree.length > 0 ? (
              <div className="space-y-0.5">
                {filteredTree.map((node) => (
                  <TreeItem
                    key={node.key}
                    node={node}
                    selectedId={selectedElementId}
                    expandedKeys={expandedKeys}
                    onToggle={handleToggleNode}
                    onSelect={handleTreeSelect}
                  />
                ))}
              </div>
            ) : elements.length === 0 && activeModelId ? (
              <p className="text-xs text-content-tertiary py-4 text-center">
                {t('bim.no_elements', { defaultValue: 'No elements to display' })}
              </p>
            ) : searchQuery ? (
              <p className="text-xs text-content-tertiary py-4 text-center">
                {t('bim.no_search_results', { defaultValue: 'No matching elements' })}
              </p>
            ) : null}
          </div>
        </div>

        {/* Right panel — 3D Viewer */}
        <div className="flex-1 min-w-0">
          {activeModelId ? (
            <BIMViewer
              modelId={activeModelId}
              projectId={projectId}
              selectedElementIds={selectedElementIds}
              onElementSelect={handleElementSelect}
              elements={elements}
              isLoading={elementsQuery.isLoading}
              error={
                elementsQuery.error
                  ? t('bim.load_error', { defaultValue: 'Failed to load model elements' })
                  : null
              }
              className="h-full"
            />
          ) : (
            <div className="flex items-center justify-center h-full bg-surface-secondary">
              <EmptyState
                icon={<Box size={28} />}
                title={t('bim.select_model', { defaultValue: 'Select a model' })}
                description={t('bim.select_model_desc', {
                  defaultValue: 'Choose a BIM model from the list to visualize it in 3D.',
                })}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
