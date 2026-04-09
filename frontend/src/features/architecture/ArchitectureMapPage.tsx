/**
 * ArchitectureMapPage — Interactive visual map of the OpenConstructionERP system architecture.
 *
 * Uses @xyflow/react (React Flow) to render modules, models, routes, and their relationships
 * as an interactive node graph with 4 view levels.
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  ReactFlow as RFComponent,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  Panel,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type NodeTypes,
  type EdgeTypes as RFEdgeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// @xyflow/react v12 exports ReactFlow as a generic forwardRef component which
// can cause JSX type errors in strict TS. Cast to a plain FC.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ReactFlow = RFComponent as any as React.FC<Record<string, any>>;
import { useTranslation } from 'react-i18next';
import { apiGet } from '@/shared/lib/api';
import { Search, X, Network, Box, Table2, ArrowRightLeft, Layers, Info, ChevronRight } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types — manifest JSON shape
// ---------------------------------------------------------------------------

interface ManifestMeta {
  generator: string;
  description: string;
  version: string;
}

interface ManifestColumn {
  name: string;
  annotation: string;
  sql_type: string;
  nullable: boolean;
}

interface ManifestModel {
  class_name: string;
  tablename: string;
  docstring: string;
  columns: ManifestColumn[];
  relationships: Array<{ name: string; target: string; type: string }>;
}

interface ManifestRoute {
  method: string;
  path: string;
  handler: string;
  response_model?: string;
  request_schema?: string;
}

interface ManifestSchema {
  class_name: string;
  bases: string[];
  docstring: string;
  fields: Array<{ name: string; type: string; default?: string }>;
}

interface ManifestModuleInfo {
  name: string;
  version: string;
  display_name: string;
  description: string;
  author: string;
  category: string;
  depends: string[];
  auto_install: boolean;
  enabled: boolean;
}

interface ManifestModule {
  module_id: string;
  module_label: string;
  module_category: string;
  files: string[];
  manifest: ManifestModuleInfo;
  models: ManifestModel[];
  routes: ManifestRoute[];
  schemas: ManifestSchema[];
  import_dependencies: string[];
}

interface ManifestStatistics {
  backend_modules: number;
  modules_with_manifests: number;
  total_models: number;
  total_columns: number;
  total_relationships: number;
  total_routes: number;
  total_schemas: number;
  total_python_files: number;
  frontend_features: number;
  frontend_ts_files: number;
  frontend_backend_mapped: number;
}

interface ArchitectureManifest {
  _meta: ManifestMeta;
  modules: ManifestModule[];
  dependency_graph: Record<string, string[]>;
  statistics: ManifestStatistics;
  frontend_features: Array<{ name: string; ts_files: number; css_files: number; test_files: number; total_files: number }>;
  frontend_backend_mapping: Record<string, string | null>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type ViewLevel = 'modules' | 'models' | 'api' | 'full';

const CATEGORY_COLORS: Record<string, string> = {
  core: '#3b82f6',
  estimation: '#f59e0b',
  planning: '#10b981',
  intelligence: '#8b5cf6',
  integration: '#06b6d4',
  infra: '#6b7280',
  developer_tools: '#ec4899',
  regional: '#14b8a6',
  extension: '#f97316',
  enterprise: '#a855f7',
};

const METHOD_COLORS: Record<string, string> = {
  GET: '#22c55e',
  POST: '#3b82f6',
  PUT: '#f59e0b',
  PATCH: '#f59e0b',
  DELETE: '#ef4444',
};

const CANVAS_BG = '#0f1117';
const NODE_BG = '#1e2433';
const NODE_TEXT = '#e2e8f0';
const NODE_TEXT_DIM = '#94a3b8';

function getCategoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? '#6b7280';
}

// ---------------------------------------------------------------------------
// Custom Node Components
// ---------------------------------------------------------------------------

interface ModuleNodeData extends Record<string, unknown> {
  label: string;
  category: string;
  modelsCount: number;
  routesCount: number;
  depsCount: number;
  description: string;
  moduleId: string;
}

function ModuleNodeComponent({ data }: { data: ModuleNodeData }) {
  const color = getCategoryColor(data.category);
  return (
    <div
      className="rounded-xl px-4 py-3 min-w-[180px] max-w-[240px] shadow-lg"
      style={{
        background: NODE_BG,
        border: `2px solid ${color}`,
        color: NODE_TEXT,
      }}
    >
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-3 h-3 rounded-full shrink-0"
          style={{ background: color }}
        />
        <span className="text-sm font-bold truncate">{data.label}</span>
      </div>
      <div className="text-[10px] space-y-0.5" style={{ color: NODE_TEXT_DIM }}>
        <div className="flex justify-between">
          <span>Models</span>
          <span className="font-mono">{data.modelsCount}</span>
        </div>
        <div className="flex justify-between">
          <span>Routes</span>
          <span className="font-mono">{data.routesCount}</span>
        </div>
        <div className="flex justify-between">
          <span>Dependencies</span>
          <span className="font-mono">{data.depsCount}</span>
        </div>
      </div>
    </div>
  );
}

interface ModelNodeData extends Record<string, unknown> {
  label: string;
  tablename: string;
  columns: ManifestColumn[];
  moduleId: string;
  category: string;
}

function ModelNodeComponent({ data }: { data: ModelNodeData }) {
  const color = getCategoryColor(data.category);
  const topColumns = data.columns.slice(0, 5);
  return (
    <div
      className="rounded-lg min-w-[200px] max-w-[280px] shadow-lg overflow-hidden"
      style={{
        background: NODE_BG,
        border: `1.5px solid ${color}40`,
        color: NODE_TEXT,
      }}
    >
      <div
        className="px-3 py-1.5 text-xs font-bold"
        style={{ background: `${color}20`, borderBottom: `1px solid ${color}30` }}
      >
        <div className="flex items-center gap-1.5">
          <Table2 size={12} style={{ color }} />
          <span className="truncate">{data.label}</span>
        </div>
        <div className="text-[9px] font-normal mt-0.5" style={{ color: NODE_TEXT_DIM }}>
          {data.tablename}
        </div>
      </div>
      <div className="px-3 py-1.5 space-y-0.5">
        {topColumns.map((col) => {
          const isPk = col.name === 'id';
          const isFk = col.name.endsWith('_id') && col.name !== 'id';
          return (
            <div key={col.name} className="flex items-center gap-1.5 text-[10px]">
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{
                  background: isPk ? '#eab308' : isFk ? '#3b82f6' : '#475569',
                }}
              />
              <span className="font-mono truncate" style={{ color: isPk ? '#eab308' : isFk ? '#60a5fa' : NODE_TEXT_DIM }}>
                {col.name}
              </span>
              <span className="ml-auto text-[9px] shrink-0" style={{ color: '#475569' }}>
                {col.sql_type}
              </span>
            </div>
          );
        })}
        {data.columns.length > 5 && (
          <div className="text-[9px] pt-0.5" style={{ color: '#475569' }}>
            +{data.columns.length - 5} more columns
          </div>
        )}
      </div>
    </div>
  );
}

interface RouteNodeData extends Record<string, unknown> {
  method: string;
  path: string;
  handler: string;
  moduleId: string;
  category: string;
}

function RouteNodeComponent({ data }: { data: RouteNodeData }) {
  const methodColor = METHOD_COLORS[data.method] ?? '#6b7280';
  return (
    <div
      className="rounded-md px-3 py-2 min-w-[160px] max-w-[260px] shadow-md"
      style={{
        background: NODE_BG,
        border: `1px solid #334155`,
        color: NODE_TEXT,
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0"
          style={{
            background: `${methodColor}20`,
            color: methodColor,
            border: `1px solid ${methodColor}40`,
          }}
        >
          {data.method}
        </span>
        <span className="text-[11px] font-mono truncate">{data.path}</span>
      </div>
      <div className="text-[9px] mt-1" style={{ color: NODE_TEXT_DIM }}>
        {data.handler}
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  module: ModuleNodeComponent as NodeTypes['module'],
  model: ModelNodeComponent as NodeTypes['model'],
  route: RouteNodeComponent as NodeTypes['route'],
};

// ---------------------------------------------------------------------------
// Custom Edge Components
// ---------------------------------------------------------------------------

function FKEdge(props: {
  id: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  style?: React.CSSProperties;
}) {
  const { sourceX, sourceY, targetX, targetY } = props;
  const path = `M${sourceX},${sourceY} C${sourceX + 50},${sourceY} ${targetX - 50},${targetY} ${targetX},${targetY}`;
  return (
    <g>
      <path d={path} fill="none" stroke="#f59e0b" strokeWidth={1.5} />
    </g>
  );
}

function ImportEdge(props: {
  id: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  style?: React.CSSProperties;
}) {
  const { sourceX, sourceY, targetX, targetY } = props;
  const path = `M${sourceX},${sourceY} C${sourceX + 50},${sourceY} ${targetX - 50},${targetY} ${targetX},${targetY}`;
  return (
    <g>
      <path d={path} fill="none" stroke="#6b7280" strokeWidth={1} strokeDasharray="6 3" />
    </g>
  );
}

function APIEdge(props: {
  id: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  style?: React.CSSProperties;
}) {
  const { sourceX, sourceY, targetX, targetY } = props;
  const path = `M${sourceX},${sourceY} C${sourceX + 60},${sourceY} ${targetX - 60},${targetY} ${targetX},${targetY}`;
  return (
    <g>
      <path
        d={path}
        fill="none"
        stroke="#3b82f6"
        strokeWidth={1.5}
        strokeDasharray="8 4"
        className="animate-pulse"
      />
    </g>
  );
}

const edgeTypes: RFEdgeTypes = {
  fk: FKEdge as RFEdgeTypes['fk'],
  import: ImportEdge as RFEdgeTypes['import'],
  api: APIEdge as RFEdgeTypes['api'],
};

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

function buildModuleView(manifest: ArchitectureManifest): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const modules = manifest.modules;

  // Grid layout
  const cols = Math.ceil(Math.sqrt(modules.length));
  const nodeW = 260;
  const nodeH = 140;
  const gapX = 80;
  const gapY = 80;

  modules.forEach((mod, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    nodes.push({
      id: `mod-${mod.module_id}`,
      type: 'module',
      position: { x: col * (nodeW + gapX), y: row * (nodeH + gapY) },
      data: {
        label: mod.module_label || mod.module_id,
        category: mod.module_category,
        modelsCount: mod.models.length,
        routesCount: mod.routes.length,
        depsCount: mod.import_dependencies?.length ?? 0,
        description: mod.manifest?.description ?? '',
        moduleId: mod.module_id,
      },
    });
  });

  // Dependency edges
  const depGraph = manifest.dependency_graph;
  for (const [sourceId, targets] of Object.entries(depGraph)) {
    for (const targetId of targets) {
      if (nodes.some((n) => n.id === `mod-${sourceId}`) && nodes.some((n) => n.id === `mod-${targetId}`)) {
        edges.push({
          id: `dep-${sourceId}-${targetId}`,
          source: `mod-${sourceId}`,
          target: `mod-${targetId}`,
          type: 'import',
          animated: false,
          style: { stroke: '#6b7280', strokeDasharray: '6 3' },
        });
      }
    }
  }

  return { nodes, edges };
}

function buildModelView(manifest: ArchitectureManifest): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  let globalIdx = 0;
  const cols = 5;
  const nodeW = 280;
  const nodeH = 200;
  const gapX = 60;
  const gapY = 40;

  // Map tablename -> node id for FK edges
  const tablenameToNodeId: Record<string, string> = {};

  for (const mod of manifest.modules) {
    for (const model of mod.models) {
      const nodeId = `model-${mod.module_id}-${model.class_name}`;
      const col = globalIdx % cols;
      const row = Math.floor(globalIdx / cols);
      tablenameToNodeId[model.tablename] = nodeId;
      tablenameToNodeId[model.class_name] = nodeId;
      nodes.push({
        id: nodeId,
        type: 'model',
        position: { x: col * (nodeW + gapX), y: row * (nodeH + gapY) },
        data: {
          label: model.class_name,
          tablename: model.tablename,
          columns: model.columns,
          moduleId: mod.module_id,
          category: mod.module_category,
        },
      });
      globalIdx++;
    }
  }

  // FK edges — find columns ending in _id that reference other tables
  for (const mod of manifest.modules) {
    for (const model of mod.models) {
      const sourceId = `model-${mod.module_id}-${model.class_name}`;
      for (const rel of model.relationships) {
        const targetId = tablenameToNodeId[rel.target];
        if (targetId && targetId !== sourceId) {
          edges.push({
            id: `fk-${sourceId}-${rel.name}-${targetId}`,
            source: sourceId,
            target: targetId,
            type: 'fk',
            animated: false,
            style: { stroke: '#f59e0b' },
            label: rel.name,
          });
        }
      }
    }
  }

  return { nodes, edges };
}

function buildAPIView(manifest: ArchitectureManifest): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Frontend feature nodes on the left, backend module nodes on the right
  const featureMapping = manifest.frontend_backend_mapping;

  let featureY = 0;
  const featureNodes: string[] = [];
  for (const [featureName, backendModule] of Object.entries(featureMapping)) {
    if (!backendModule) continue;
    const featureNodeId = `fe-${featureName}`;
    featureNodes.push(featureNodeId);
    nodes.push({
      id: featureNodeId,
      type: 'module',
      position: { x: 0, y: featureY },
      data: {
        label: `FE: ${featureName}`,
        category: 'integration',
        modelsCount: 0,
        routesCount: 0,
        depsCount: 0,
        description: `Frontend feature: ${featureName}`,
        moduleId: featureName,
      },
    });
    featureY += 120;
  }

  let routeY = 0;
  for (const mod of manifest.modules) {
    if (mod.routes.length === 0) continue;

    // Module header node
    const modNodeId = `api-mod-${mod.module_id}`;
    nodes.push({
      id: modNodeId,
      type: 'module',
      position: { x: 600, y: routeY },
      data: {
        label: mod.module_label || mod.module_id,
        category: mod.module_category,
        modelsCount: mod.models.length,
        routesCount: mod.routes.length,
        depsCount: mod.import_dependencies?.length ?? 0,
        description: mod.manifest?.description ?? '',
        moduleId: mod.module_id,
      },
    });

    // Route nodes
    const maxRoutes = Math.min(mod.routes.length, 6);
    for (let ri = 0; ri < maxRoutes; ri++) {
      const route = mod.routes[ri];
      if (!route) continue;
      const routeNodeId = `route-${mod.module_id}-${ri}`;
      nodes.push({
        id: routeNodeId,
        type: 'route',
        position: { x: 1000, y: routeY + ri * 55 },
        data: {
          method: route.method,
          path: `/api/v1/${mod.module_id}${route.path}`,
          handler: route.handler,
          moduleId: mod.module_id,
          category: mod.module_category,
        },
      });
      edges.push({
        id: `api-edge-${modNodeId}-${routeNodeId}`,
        source: modNodeId,
        target: routeNodeId,
        animated: true,
        style: { stroke: '#3b82f6', strokeDasharray: '8 4' },
      });
    }

    routeY += Math.max(maxRoutes * 55, 140) + 40;
  }

  // Frontend -> Backend edges
  for (const [featureName, backendModule] of Object.entries(featureMapping)) {
    if (!backendModule) continue;
    const featureNodeId = `fe-${featureName}`;
    const backendNodeId = `api-mod-${backendModule}`;
    if (nodes.some((n) => n.id === featureNodeId) && nodes.some((n) => n.id === backendNodeId)) {
      edges.push({
        id: `fe-be-${featureName}-${backendModule}`,
        source: featureNodeId,
        target: backendNodeId,
        type: 'api',
        animated: true,
        style: { stroke: '#3b82f6', strokeDasharray: '8 4' },
      });
    }
  }

  return { nodes, edges };
}

function buildFullView(manifest: ArchitectureManifest): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const tablenameToNodeId: Record<string, string> = {};

  let moduleY = 0;
  for (const mod of manifest.modules) {
    const modNodeId = `mod-${mod.module_id}`;
    nodes.push({
      id: modNodeId,
      type: 'module',
      position: { x: 0, y: moduleY },
      data: {
        label: mod.module_label || mod.module_id,
        category: mod.module_category,
        modelsCount: mod.models.length,
        routesCount: mod.routes.length,
        depsCount: mod.import_dependencies?.length ?? 0,
        description: mod.manifest?.description ?? '',
        moduleId: mod.module_id,
      },
    });

    // Models
    for (let mi = 0; mi < mod.models.length; mi++) {
      const model = mod.models[mi];
      if (!model) continue;
      const modelNodeId = `model-${mod.module_id}-${model.class_name}`;
      tablenameToNodeId[model.tablename] = modelNodeId;
      tablenameToNodeId[model.class_name] = modelNodeId;
      nodes.push({
        id: modelNodeId,
        type: 'model',
        position: { x: 400, y: moduleY + mi * 220 },
        data: {
          label: model.class_name,
          tablename: model.tablename,
          columns: model.columns,
          moduleId: mod.module_id,
          category: mod.module_category,
        },
      });
      edges.push({
        id: `owns-${modNodeId}-${modelNodeId}`,
        source: modNodeId,
        target: modelNodeId,
        style: { stroke: getCategoryColor(mod.module_category), strokeWidth: 1 },
      });
    }

    // Routes (first 4)
    const maxRoutes = Math.min(mod.routes.length, 4);
    for (let ri = 0; ri < maxRoutes; ri++) {
      const route = mod.routes[ri];
      if (!route) continue;
      const routeNodeId = `route-${mod.module_id}-${ri}`;
      nodes.push({
        id: routeNodeId,
        type: 'route',
        position: { x: 800, y: moduleY + ri * 55 },
        data: {
          method: route.method,
          path: `/api/v1/${mod.module_id}${route.path}`,
          handler: route.handler,
          moduleId: mod.module_id,
          category: mod.module_category,
        },
      });
      edges.push({
        id: `api-${modNodeId}-${routeNodeId}`,
        source: modNodeId,
        target: routeNodeId,
        animated: true,
        style: { stroke: '#3b82f680', strokeDasharray: '6 3' },
      });
    }

    moduleY += Math.max(mod.models.length * 220, maxRoutes * 55, 180) + 60;
  }

  // Dependency edges
  const depGraph = manifest.dependency_graph;
  for (const [sourceId, targets] of Object.entries(depGraph)) {
    for (const targetId of targets) {
      if (nodes.some((n) => n.id === `mod-${sourceId}`) && nodes.some((n) => n.id === `mod-${targetId}`)) {
        edges.push({
          id: `dep-${sourceId}-${targetId}`,
          source: `mod-${sourceId}`,
          target: `mod-${targetId}`,
          type: 'import',
          style: { stroke: '#6b728060', strokeDasharray: '6 3' },
        });
      }
    }
  }

  // FK edges
  for (const mod of manifest.modules) {
    for (const model of mod.models) {
      const sourceId = `model-${mod.module_id}-${model.class_name}`;
      for (const rel of model.relationships) {
        const targetId = tablenameToNodeId[rel.target];
        if (targetId && targetId !== sourceId) {
          edges.push({
            id: `fk-${sourceId}-${rel.name}-${targetId}`,
            source: sourceId,
            target: targetId,
            type: 'fk',
            style: { stroke: '#f59e0b60' },
          });
        }
      }
    }
  }

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Detail Panel
// ---------------------------------------------------------------------------

interface DetailPanelProps {
  manifest: ArchitectureManifest;
  selectedNodeId: string | null;
  onClose: () => void;
}

function DetailPanel({ manifest, selectedNodeId, onClose }: DetailPanelProps) {
  const { t } = useTranslation();

  if (!selectedNodeId) return null;

  // Parse node id to find the entity
  const parts = selectedNodeId.split('-');
  const nodeType = parts[0] ?? ''; // 'mod', 'model', 'route', 'fe', 'api'

  let content: React.ReactNode = null;

  if (nodeType === 'mod' || nodeType === 'api' || nodeType === 'fe') {
    const moduleId = nodeType === 'api' ? parts.slice(2).join('-') : nodeType === 'fe' ? parts.slice(1).join('-') : parts.slice(1).join('-');
    const mod = manifest.modules.find((m) => m.module_id === moduleId);
    if (mod) {
      content = (
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <div
                className="w-3 h-3 rounded-full"
                style={{ background: getCategoryColor(mod.module_category) }}
              />
              <h3 className="text-lg font-bold" style={{ color: NODE_TEXT }}>
                {mod.module_label || mod.module_id}
              </h3>
            </div>
            <span
              className="inline-block text-[10px] px-2 py-0.5 rounded-full font-medium"
              style={{
                background: `${getCategoryColor(mod.module_category)}20`,
                color: getCategoryColor(mod.module_category),
              }}
            >
              {mod.module_category}
            </span>
            <p className="text-xs mt-2" style={{ color: NODE_TEXT_DIM }}>
              {mod.manifest?.description}
            </p>
          </div>

          {mod.manifest?.depends && mod.manifest.depends.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1" style={{ color: NODE_TEXT }}>
                {t('architecture.dependencies', { defaultValue: 'Dependencies' })}
              </h4>
              <div className="flex flex-wrap gap-1">
                {mod.manifest.depends.map((dep) => (
                  <span
                    key={dep}
                    className="text-[10px] px-2 py-0.5 rounded-full"
                    style={{ background: '#334155', color: NODE_TEXT_DIM }}
                  >
                    {dep}
                  </span>
                ))}
              </div>
            </div>
          )}

          {mod.models.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1" style={{ color: NODE_TEXT }}>
                {t('architecture.models', { defaultValue: 'Models' })} ({mod.models.length})
              </h4>
              <div className="space-y-1">
                {mod.models.map((model) => (
                  <div
                    key={model.class_name}
                    className="text-[11px] px-2 py-1 rounded"
                    style={{ background: '#0f1117', color: NODE_TEXT_DIM }}
                  >
                    <span className="font-mono font-medium" style={{ color: '#eab308' }}>
                      {model.class_name}
                    </span>
                    <span className="ml-2 text-[9px]">({model.columns.length} cols)</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {mod.routes.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1" style={{ color: NODE_TEXT }}>
                {t('architecture.routes', { defaultValue: 'Routes' })} ({mod.routes.length})
              </h4>
              <div className="space-y-1 max-h-[300px] overflow-y-auto">
                {mod.routes.map((route, idx) => (
                  <div
                    key={`${route.method}-${route.path}-${idx}`}
                    className="flex items-center gap-2 text-[11px] px-2 py-1 rounded"
                    style={{ background: '#0f1117' }}
                  >
                    <span
                      className="px-1 py-0.5 rounded text-[9px] font-bold shrink-0"
                      style={{
                        background: `${METHOD_COLORS[route.method] ?? '#6b7280'}20`,
                        color: METHOD_COLORS[route.method] ?? '#6b7280',
                      }}
                    >
                      {route.method}
                    </span>
                    <span className="font-mono truncate" style={{ color: NODE_TEXT_DIM }}>
                      {route.path}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      );
    }
  }

  if (nodeType === 'model') {
    const moduleId = parts[1] ?? '';
    const className = parts.slice(2).join('-');
    const mod = manifest.modules.find((m) => m.module_id === moduleId);
    const model = mod?.models.find((m) => m.class_name === className);
    if (model) {
      content = (
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Table2 size={16} style={{ color: '#eab308' }} />
              <h3 className="text-lg font-bold" style={{ color: NODE_TEXT }}>
                {model.class_name}
              </h3>
            </div>
            <div className="text-[10px] font-mono" style={{ color: NODE_TEXT_DIM }}>
              {model.tablename}
            </div>
            {model.docstring && (
              <p className="text-xs mt-2" style={{ color: NODE_TEXT_DIM }}>
                {model.docstring}
              </p>
            )}
          </div>

          <div>
            <h4 className="text-xs font-semibold mb-1" style={{ color: NODE_TEXT }}>
              {t('architecture.columns', { defaultValue: 'Columns' })} ({model.columns.length})
            </h4>
            <div className="space-y-0.5 max-h-[400px] overflow-y-auto">
              {model.columns.map((col) => {
                const isPk = col.name === 'id';
                const isFk = col.name.endsWith('_id') && col.name !== 'id';
                return (
                  <div
                    key={col.name}
                    className="flex items-center gap-2 text-[11px] px-2 py-1 rounded"
                    style={{ background: '#0f1117' }}
                  >
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{
                        background: isPk ? '#eab308' : isFk ? '#3b82f6' : '#475569',
                      }}
                    />
                    <span
                      className="font-mono"
                      style={{ color: isPk ? '#eab308' : isFk ? '#60a5fa' : NODE_TEXT_DIM }}
                    >
                      {col.name}
                    </span>
                    <span className="ml-auto text-[9px] shrink-0" style={{ color: '#475569' }}>
                      {col.sql_type}
                    </span>
                    {col.nullable && (
                      <span className="text-[8px] shrink-0" style={{ color: '#475569' }}>
                        NULL
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {model.relationships.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1" style={{ color: NODE_TEXT }}>
                {t('architecture.relationships', { defaultValue: 'Relationships' })}
              </h4>
              {model.relationships.map((rel) => (
                <div
                  key={rel.name}
                  className="flex items-center gap-2 text-[11px] px-2 py-1 rounded"
                  style={{ background: '#0f1117' }}
                >
                  <ChevronRight size={10} style={{ color: '#f59e0b' }} />
                  <span className="font-mono" style={{ color: '#f59e0b' }}>
                    {rel.name}
                  </span>
                  <span style={{ color: NODE_TEXT_DIM }}>{'->'}</span>
                  <span className="font-mono" style={{ color: '#60a5fa' }}>
                    {rel.target}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }
  }

  if (nodeType === 'route') {
    const moduleId = parts[1] ?? '';
    const routeIdx = parseInt(parts[2] ?? '0', 10);
    const mod = manifest.modules.find((m) => m.module_id === moduleId);
    const route = mod?.routes[routeIdx];
    if (route) {
      content = (
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span
                className="px-2 py-0.5 rounded text-xs font-bold"
                style={{
                  background: `${METHOD_COLORS[route.method] ?? '#6b7280'}20`,
                  color: METHOD_COLORS[route.method] ?? '#6b7280',
                }}
              >
                {route.method}
              </span>
              <span className="text-sm font-mono font-bold" style={{ color: NODE_TEXT }}>
                {route.path}
              </span>
            </div>
            <div className="text-xs" style={{ color: NODE_TEXT_DIM }}>
              Handler: <span className="font-mono">{route.handler}</span>
            </div>
          </div>
          {route.response_model && (
            <div>
              <h4 className="text-xs font-semibold mb-1" style={{ color: NODE_TEXT }}>
                {t('architecture.response_model', { defaultValue: 'Response Model' })}
              </h4>
              <span className="text-xs font-mono" style={{ color: '#22c55e' }}>
                {route.response_model}
              </span>
            </div>
          )}
          {route.request_schema && (
            <div>
              <h4 className="text-xs font-semibold mb-1" style={{ color: NODE_TEXT }}>
                {t('architecture.request_schema', { defaultValue: 'Request Schema' })}
              </h4>
              <span className="text-xs font-mono" style={{ color: '#3b82f6' }}>
                {route.request_schema}
              </span>
            </div>
          )}
        </div>
      );
    }
  }

  if (!content) {
    content = (
      <div className="text-xs" style={{ color: NODE_TEXT_DIM }}>
        {t('architecture.no_details', { defaultValue: 'No details available for this node.' })}
      </div>
    );
  }

  return (
    <div
      className="absolute top-0 right-0 h-full overflow-y-auto z-20 shadow-2xl"
      style={{
        width: 380,
        background: '#1a1f2e',
        borderLeft: '1px solid #334155',
      }}
    >
      <div className="sticky top-0 flex items-center justify-between px-4 py-3 z-10" style={{ background: '#1a1f2e', borderBottom: '1px solid #334155' }}>
        <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: NODE_TEXT_DIM }}>
          {t('architecture.details', { defaultValue: 'Details' })}
        </span>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-white/10 transition-colors"
          style={{ color: NODE_TEXT_DIM }}
        >
          <X size={16} />
        </button>
      </div>
      <div className="px-4 py-3">{content}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

function Legend() {
  const { t } = useTranslation();
  return (
    <div
      className="rounded-lg px-3 py-2 text-[10px] space-y-2"
      style={{ background: '#1a1f2eee', border: '1px solid #334155', color: NODE_TEXT_DIM }}
    >
      <div className="font-semibold text-[11px]" style={{ color: NODE_TEXT }}>
        {t('architecture.legend', { defaultValue: 'Legend' })}
      </div>
      <div className="space-y-1">
        <div className="font-semibold" style={{ color: NODE_TEXT }}>
          {t('architecture.categories', { defaultValue: 'Categories' })}
        </div>
        {Object.entries(CATEGORY_COLORS).map(([key, color]) => (
          <div key={key} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
            <span>{key}</span>
          </div>
        ))}
      </div>
      <div className="space-y-1">
        <div className="font-semibold" style={{ color: NODE_TEXT }}>
          {t('architecture.edges', { defaultValue: 'Edges' })}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-4 border-t-2 border-dashed" style={{ borderColor: '#6b7280' }} />
          <span>{t('architecture.edge_dependency', { defaultValue: 'Dependency' })}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-4 border-t-2" style={{ borderColor: '#f59e0b' }} />
          <span>{t('architecture.edge_fk', { defaultValue: 'Foreign Key' })}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-4 border-t-2 border-dashed" style={{ borderColor: '#3b82f6' }} />
          <span>{t('architecture.edge_api', { defaultValue: 'API Call' })}</span>
        </div>
      </div>
      <div className="space-y-1">
        <div className="font-semibold" style={{ color: NODE_TEXT }}>
          {t('architecture.column_types', { defaultValue: 'Column Markers' })}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ background: '#eab308' }} />
          <span>{t('architecture.pk', { defaultValue: 'Primary Key' })}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ background: '#3b82f6' }} />
          <span>{t('architecture.fk', { defaultValue: 'Foreign Key' })}</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty State
// ---------------------------------------------------------------------------

function ArchitectureEmptyState() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center h-full" style={{ background: CANVAS_BG, color: NODE_TEXT }}>
      <div className="flex flex-col items-center gap-4 max-w-md text-center px-6">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{ background: '#1e2433', border: '1px solid #334155' }}
        >
          <Network size={32} style={{ color: '#6b7280' }} />
        </div>
        <h2 className="text-xl font-bold">
          {t('architecture.empty_title', { defaultValue: 'Architecture Map' })}
        </h2>
        <p className="text-sm" style={{ color: NODE_TEXT_DIM }}>
          {t('architecture.empty_description', {
            defaultValue:
              'No architecture data available yet. Run the generator script to create the manifest, or check that the API endpoint is accessible.',
          })}
        </p>
        <div
          className="text-xs font-mono px-4 py-2 rounded-lg"
          style={{ background: '#0f1117', border: '1px solid #334155', color: '#22c55e' }}
        >
          python generate_architecture_manifest.py
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Flow Component (inner, needs ReactFlowProvider above it)
// ---------------------------------------------------------------------------

interface FlowCanvasProps {
  manifest: ArchitectureManifest;
  viewLevel: ViewLevel;
  searchQuery: string;
}

function FlowCanvas({ manifest, viewLevel, searchQuery }: FlowCanvasProps) {
  const { fitView } = useReactFlow();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const built = useMemo(() => {
    switch (viewLevel) {
      case 'modules':
        return buildModuleView(manifest);
      case 'models':
        return buildModelView(manifest);
      case 'api':
        return buildAPIView(manifest);
      case 'full':
        return buildFullView(manifest);
    }
  }, [manifest, viewLevel]);

  // Apply search highlighting
  const filteredNodes = useMemo(() => {
    if (!searchQuery.trim()) return built.nodes;
    const q = searchQuery.toLowerCase();
    return built.nodes.map((node) => {
      const data = node.data as Record<string, unknown>;
      const label = String(data.label ?? data.path ?? data.handler ?? '').toLowerCase();
      const moduleId = String(data.moduleId ?? '').toLowerCase();
      const match = label.includes(q) || moduleId.includes(q);
      return {
        ...node,
        style: {
          ...node.style,
          opacity: match ? 1 : 0.15,
          transition: 'opacity 0.3s ease',
        },
      };
    });
  }, [built.nodes, searchQuery]);

  const [nodes, setNodes, onNodesChange] = useNodesState(filteredNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(built.edges);

  // Update nodes/edges when view changes
  useEffect(() => {
    setNodes(filteredNodes);
    setEdges(built.edges);
    // Fit view after layout change
    const timer = setTimeout(() => {
      fitView({ padding: 0.15, duration: 400 });
    }, 100);
    return () => clearTimeout(timer);
  }, [filteredNodes, built.edges, setNodes, setEdges, fitView]);

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    setSelectedNodeId(node.id);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  return (
    <div className="relative w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.05}
        maxZoom={2}
        defaultEdgeOptions={{ animated: false }}
        proOptions={{ hideAttribution: true }}
        style={{ background: CANVAS_BG }}
      >
        <Background color="#1e293b" gap={24} size={1} />
        <Controls
          showInteractive={false}
          style={{ background: '#1e2433', borderColor: '#334155', borderRadius: 8 }}
        />
        <MiniMap
          nodeColor={(node) => {
            const data = node.data as Record<string, unknown>;
            return getCategoryColor(String(data.category ?? 'infra'));
          }}
          maskColor="#0f111780"
          style={{
            background: '#1a1f2e',
            borderColor: '#334155',
            borderRadius: 8,
          }}
        />
        <Panel position="bottom-left">
          <Legend />
        </Panel>
      </ReactFlow>

      <DetailPanel
        manifest={manifest}
        selectedNodeId={selectedNodeId}
        onClose={() => setSelectedNodeId(null)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function ArchitectureMapPage() {
  const { t } = useTranslation();
  const [manifest, setManifest] = useState<ArchitectureManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewLevel, setViewLevel] = useState<ViewLevel>('modules');
  const [searchQuery, setSearchQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiGet<ArchitectureManifest>('/v1/architecture_map/')
      .then((data) => {
        if (!cancelled) {
          if (data && data.modules && data.modules.length > 0) {
            setManifest(data);
          } else {
            setManifest(null);
          }
        }
      })
      .catch(() => {
        // If API is not available, try to load the static manifest bundled in the repo
        if (!cancelled) {
          import('./architecture_manifest.json')
            .then((mod) => {
              const data = (mod.default ?? mod) as unknown as ArchitectureManifest;
              if (data && data.modules && data.modules.length > 0) {
                setManifest(data);
              } else {
                setManifest(null);
              }
            })
            .catch(() => {
              setError('Failed to load architecture data');
              setManifest(null);
            });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const views: { key: ViewLevel; label: string; icon: React.ReactNode }[] = [
    {
      key: 'modules',
      label: t('architecture.view_modules', { defaultValue: 'Module Overview' }),
      icon: <Box size={14} />,
    },
    {
      key: 'models',
      label: t('architecture.view_models', { defaultValue: 'Data Models' }),
      icon: <Table2 size={14} />,
    },
    {
      key: 'api',
      label: t('architecture.view_api', { defaultValue: 'API Flow' }),
      icon: <ArrowRightLeft size={14} />,
    },
    {
      key: 'full',
      label: t('architecture.view_full', { defaultValue: 'Full Detail' }),
      icon: <Layers size={14} />,
    },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full" style={{ background: CANVAS_BG }}>
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: '#3b82f6', borderTopColor: 'transparent' }} />
          <span className="text-sm" style={{ color: NODE_TEXT_DIM }}>
            {t('architecture.loading', { defaultValue: 'Loading architecture...' })}
          </span>
        </div>
      </div>
    );
  }

  if (error || !manifest) {
    return <ArchitectureEmptyState />;
  }

  return (
    <div className="flex flex-col h-full" style={{ background: CANVAS_BG }}>
      {/* Top bar */}
      <div
        className="flex items-center gap-3 px-4 py-2 shrink-0 z-10"
        style={{ background: '#1a1f2e', borderBottom: '1px solid #334155' }}
      >
        {/* View level buttons */}
        <div className="flex items-center gap-1">
          {views.map((v) => (
            <button
              key={v.key}
              onClick={() => setViewLevel(v.key)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all"
              style={{
                background: viewLevel === v.key ? '#3b82f620' : 'transparent',
                color: viewLevel === v.key ? '#60a5fa' : NODE_TEXT_DIM,
                border: viewLevel === v.key ? '1px solid #3b82f640' : '1px solid transparent',
              }}
            >
              {v.icon}
              <span className="hidden sm:inline">{v.label}</span>
            </button>
          ))}
        </div>

        <div className="flex-1" />

        {/* Search */}
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: NODE_TEXT_DIM }} />
          <input
            ref={searchRef}
            type="text"
            placeholder={t('architecture.search', { defaultValue: 'Search nodes...' })}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 pr-8 py-1.5 rounded-md text-xs outline-none"
            style={{
              background: '#0f1117',
              border: '1px solid #334155',
              color: NODE_TEXT,
              width: 220,
            }}
          />
          {searchQuery && (
            <button
              onClick={() => {
                setSearchQuery('');
                searchRef.current?.focus();
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-white/10 transition-colors"
              style={{ color: NODE_TEXT_DIM }}
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* Stats badge */}
        <div
          className="hidden md:flex items-center gap-2 text-[10px] px-3 py-1 rounded-md"
          style={{ background: '#0f1117', border: '1px solid #334155', color: NODE_TEXT_DIM }}
        >
          <Info size={12} />
          <span>{manifest.statistics.backend_modules} modules</span>
          <span style={{ color: '#334155' }}>|</span>
          <span>{manifest.statistics.total_models} models</span>
          <span style={{ color: '#334155' }}>|</span>
          <span>{manifest.statistics.total_routes} routes</span>
        </div>
      </div>

      {/* Canvas */}
      <div className="flex-1 relative">
        <ReactFlowProvider>
          <FlowCanvas manifest={manifest} viewLevel={viewLevel} searchQuery={searchQuery} />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
