// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Portfolio / multi-project page (T3.3).
//
// An enterprise schedule-of-schedules. Unlike the per-project modules, this
// page spans projects, so it is NOT scoped to the single active project: it
// reads the whole access-pruned portfolio / programme tree and runs a single
// cross-project CPM pass over a chosen node's subtree.
//
// Three areas, mirroring the data-rich house style of
// features/schedule/ScheduleResourcePanel.tsx:
//
//   1. The portfolio tree (left): the hierarchy of portfolios / programmes with
//      the projects filed under each node. The user creates nodes, files an
//      accessible project under a node, and picks a node to analyse.
//
//   2. Portfolio CPM (right): for the picked node, the rolled-up schedule
//      metrics (schedule / activity counts, the portfolio finish work-day, how
//      many cross-project links were applied vs omitted because their far side
//      is out of scope) and the cross-portfolio critical path - the longest
//      chain of activities across every linked project schedule under the node.
//
//   3. Cross-project links (below): pick a schedule and see / delete the
//      cross-schedule dependencies touching it, or author a new one between two
//      activities. A link whose both endpoints sit under the analysed node is
//      then honoured as a real edge by the portfolio CPM.
//
// All numbers from the CPM are integer work-day offsets on the shared portfolio
// timeline (schedules are merged by start-date offset server-side), shown as-is.

import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Building2,
  Network,
  FolderTree,
  FolderPlus,
  Plus,
  Trash2,
  Loader2,
  Play,
  Link2,
  ChevronRight,
  AlertTriangle,
  GitBranch,
  ArrowRight,
  FileText,
} from 'lucide-react';

import { PortfolioCashFlowWidget } from './PortfolioCashFlowWidget';
import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable, CollapsibleSection } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { scheduleApi, type Schedule, type Activity } from '@/features/schedule/api';
import { projectsApi } from '@/features/projects/api';
import {
  portfolioCpmApi,
  type PortfolioTreeNode,
  type PortfolioNodeType,
  type PortfolioCpmResult,
  type PortfolioCpmActivity,
  type CrossLink,
  type DepType,
} from './portfolioCpmApi';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-2xs font-medium uppercase tracking-wide text-content-secondary mb-1';

const NODE_TYPES: PortfolioNodeType[] = ['portfolio', 'programme', 'subprogramme'];
const DEP_TYPES: DepType[] = ['FS', 'SS', 'FF', 'SF'];

/** Flatten the tree into rows carrying a depth, in stable pre-order. */
interface FlatNode {
  node: PortfolioTreeNode;
  depth: number;
}
function flattenTree(nodes: PortfolioTreeNode[], depth = 0, out: FlatNode[] = []): FlatNode[] {
  for (const node of nodes) {
    out.push({ node, depth });
    if (node.children.length > 0) flattenTree(node.children, depth + 1, out);
  }
  return out;
}

/* ── How-it-works flow + module integrations ───────────────────────────── */

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer for the portfolio (a schedule-of-schedules): what it
 * does and how it connects. Each project's 4D schedule rolls up here; a single
 * cross-project CPM pass over a node's subtree finds the programme critical
 * path, which then informs project controls and resource planning.
 */
function HowPortfolioWorks() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <FolderTree size={14} className="text-oe-blue" />,
      title: t('portfolio.flow_1_title', { defaultValue: 'Build the tree' }),
      desc: t('portfolio.flow_1_desc', {
        defaultValue: 'Create portfolios and programmes, then file projects under each node.',
      }),
    },
    {
      icon: <Link2 size={14} className="text-oe-blue" />,
      title: t('portfolio.flow_2_title', { defaultValue: 'Link across projects' }),
      desc: t('portfolio.flow_2_desc', {
        defaultValue: "Tie an activity in one project's schedule to an activity in another.",
      }),
    },
    {
      icon: <Network size={14} className="text-oe-blue" />,
      title: t('portfolio.flow_3_title', { defaultValue: 'Roll up the CPM' }),
      desc: t('portfolio.flow_3_desc', {
        defaultValue: 'Run one critical-path pass across every schedule filed under a node.',
      }),
    },
    {
      icon: <GitBranch size={14} className="text-oe-blue" />,
      title: t('portfolio.flow_4_title', { defaultValue: 'Read the critical path' }),
      desc: t('portfolio.flow_4_desc', {
        defaultValue: 'See the finish work-day and the longest chain of activities across projects.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="portfolio.how"
      className="mt-4"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('portfolio.flow_title', { defaultValue: 'How the portfolio fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('portfolio.flow_intro', {
          defaultValue:
            'The portfolio rolls many project schedules into one programme view and runs a single critical-path pass across them, so you can see the finish date and the longest chain that spans projects.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('portfolio.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          <ModLink to="/schedule">
            {t('portfolio.mod_schedule', { defaultValue: '4D Schedule' })}
          </ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('portfolio.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          <ModLink to="/project-controls">
            {t('portfolio.mod_controls', { defaultValue: 'Project controls' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/resources">
            {t('portfolio.mod_resources', { defaultValue: 'Resources & crew' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

export function PortfolioPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [selectedNodeId, setSelectedNodeId] = useState<string>('');

  const toastError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Error' }),
      message: getErrorMessage(e),
    });

  const treeQ = useQuery<PortfolioTreeNode[]>({
    queryKey: ['portfolio', 'tree'],
    queryFn: () => portfolioCpmApi.getTree(),
  });

  const flat = useMemo(() => flattenTree(treeQ.data ?? []), [treeQ.data]);

  return (
    // Full-width page frame, matching every other module surface. The app
    // shell (<main> in AppLayout) already supplies the horizontal gutter and
    // top padding, so pages must not re-cap their width or double the padding;
    // Portfolio used to wrap at max-w-7xl mx-auto, which rendered it narrower
    // and off-centre relative to the rest of the app.
    <div className="w-full">
      <PageHeader
        srTitle={t('portfolio.title', { defaultValue: 'Portfolio' })}
        subtitle={t('portfolio.subtitle', {
          defaultValue:
            'An enterprise schedule-of-schedules: organise projects into portfolios and programmes, then run one critical-path pass across every linked schedule under a node to see the cross-project critical path and finish date.',
        })}
      />

      <div className="mt-4">
        <PortfolioCashFlowWidget />
      </div>

      {/* How this module works + what it connects to */}
      <HowPortfolioWorks />

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[380px_1fr]">
        {/* Left: the portfolio / programme tree */}
        <div className="space-y-4">
          <TreePanel
            treeQ={treeQ}
            flat={flat}
            selectedNodeId={selectedNodeId}
            onSelect={setSelectedNodeId}
            onError={toastError}
          />
        </div>

        {/* Right: the cross-project CPM for the selected node */}
        <div className="min-w-0 space-y-4">
          <CpmPanel selectedNodeId={selectedNodeId} flat={flat} />
        </div>
      </div>

      {/* Cross-project links - read / delete / author, scoped to the active project */}
      <div className="mt-4">
        <CrossLinksPanel activeProjectId={activeProjectId} onError={toastError} />
      </div>
    </div>
  );
}

/* ── Tree panel ──────────────────────────────────────────────────────────── */

function TreePanel({
  treeQ,
  flat,
  selectedNodeId,
  onSelect,
  onError,
}: {
  treeQ: ReturnType<typeof useQuery<PortfolioTreeNode[]>>;
  flat: FlatNode[];
  selectedNodeId: string;
  onSelect: (id: string) => void;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [name, setName] = useState('');
  const [nodeType, setNodeType] = useState<PortfolioNodeType>('programme');
  const [parentId, setParentId] = useState<string>('');

  const { data: allProjects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 120_000,
  });
  const projectNameById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const p of allProjects) m[p.id] = p.name;
    return m;
  }, [allProjects]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['portfolio', 'tree'] });

  const createMut = useMutation({
    mutationFn: () =>
      portfolioCpmApi.createNode({
        name: name.trim(),
        node_type: nodeType,
        parent_id: parentId || null,
      }),
    onSuccess: () => {
      setName('');
      refresh();
      addToast({
        type: 'success',
        title: t('portfolio.node_created', { defaultValue: 'Node created' }),
        message: t('portfolio.node_created_detail', { defaultValue: 'The portfolio node was added.' }),
      });
    },
    onError,
  });

  const nodeTypeLabel = (nt: string): string =>
    ({
      portfolio: t('portfolio.type_portfolio', { defaultValue: 'Portfolio' }),
      programme: t('portfolio.type_programme', { defaultValue: 'Programme' }),
      subprogramme: t('portfolio.type_subprogramme', { defaultValue: 'Sub-programme' }),
    })[nt] ?? nt;

  return (
    <Card padding="md" data-testid="portfolio-tree-panel">
      <div className="mb-3 flex items-center gap-2">
        <FolderTree size={16} className="text-content-secondary" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('portfolio.tree_title', { defaultValue: 'Portfolio tree' })}
        </h3>
      </div>

      {treeQ.isLoading ? (
        <div data-testid="portfolio-tree-loading">
          <SkeletonTable rows={5} columns={1} />
        </div>
      ) : treeQ.isError ? (
        <RecoveryCard error={treeQ.error} onRetry={() => treeQ.refetch()} />
      ) : flat.length === 0 ? (
        <EmptyState
          icon={<Network size={28} strokeWidth={1.5} />}
          title={t('portfolio.tree_empty', { defaultValue: 'No portfolios yet' })}
          description={t('portfolio.tree_empty_desc', {
            defaultValue:
              'Create a portfolio or programme below, then file your projects under it to roll up their schedules.',
          })}
        />
      ) : (
        <ul className="space-y-0.5" data-testid="portfolio-tree-list">
          {flat.map(({ node, depth }) => {
            const active = node.id === selectedNodeId;
            return (
              <li key={node.id}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelect(node.id)}
                  style={{ paddingLeft: `${8 + depth * 16}px` }}
                  className={`flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left text-sm transition-colors ${
                    active ? 'bg-oe-blue/10 text-oe-blue' : 'text-content-primary hover:bg-surface-secondary'
                  }`}
                >
                  {node.node_type === 'portfolio' ? (
                    <Building2 size={14} className="shrink-0 text-content-tertiary" />
                  ) : (
                    <FolderTree size={14} className="shrink-0 text-content-tertiary" />
                  )}
                  <span className="min-w-0 flex-1 truncate">
                    {node.name}
                    {node.code ? (
                      <span className="ml-1.5 text-2xs text-content-tertiary">{node.code}</span>
                    ) : null}
                  </span>
                  {node.project_ids.length > 0 && (
                    <Badge variant="neutral" size="sm">
                      {node.project_ids.length}
                    </Badge>
                  )}
                </button>
                {node.project_ids.length > 0 && (
                  <ul className="space-y-px">
                    {node.project_ids.map((pid) => (
                      <li
                        key={pid}
                        style={{ paddingLeft: `${8 + (depth + 1) * 16}px` }}
                        className="flex items-center gap-2 py-1 text-xs text-content-secondary"
                      >
                        <FileText size={12} className="shrink-0 text-content-tertiary" />
                        <span className="min-w-0 truncate">{projectNameById[pid] || pid.slice(0, 8)}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {active && (
                  <AttachProjectRow nodeId={node.id} onError={onError} onAttached={refresh} />
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* Create-node form */}
      <div className="mt-4 space-y-3 border-t border-border-light pt-4">
        <h4 className="text-2xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('portfolio.add_node', { defaultValue: 'Add a portfolio / programme' })}
        </h4>
        <div>
          <label htmlFor="portfolio-node-name" className={labelCls}>
            {t('portfolio.node_name', { defaultValue: 'Name' })}
          </label>
          <input
            id="portfolio-node-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('portfolio.node_name_ph', { defaultValue: 'e.g. North Region Programme' })}
            className={inputCls}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="portfolio-node-type" className={labelCls}>
              {t('portfolio.node_type', { defaultValue: 'Type' })}
            </label>
            <select
              id="portfolio-node-type"
              value={nodeType}
              onChange={(e) => setNodeType(e.target.value as PortfolioNodeType)}
              className={inputCls}
            >
              {NODE_TYPES.map((nt) => (
                <option key={nt} value={nt}>
                  {nodeTypeLabel(nt)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="portfolio-node-parent" className={labelCls}>
              {t('portfolio.node_parent', { defaultValue: 'Parent' })}
            </label>
            <select
              id="portfolio-node-parent"
              value={parentId}
              onChange={(e) => setParentId(e.target.value)}
              className={inputCls}
            >
              <option value="">{t('portfolio.no_parent', { defaultValue: 'None (root)' })}</option>
              {flat.map(({ node, depth }) => (
                <option key={node.id} value={node.id}>
                  {`${String.fromCharCode(32).repeat(depth * 2)}${node.name}`}
                </option>
              ))}
            </select>
          </div>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => createMut.mutate()}
          disabled={createMut.isPending || name.trim().length === 0}
          icon={createMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
        >
          {t('portfolio.create_node', { defaultValue: 'Create node' })}
        </Button>
      </div>
    </Card>
  );
}

/** Inline "file a project under this node" row, shown under the selected node. */
function AttachProjectRow({
  nodeId,
  onError,
  onAttached,
}: {
  nodeId: string;
  onError: (e: unknown) => void;
  onAttached: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [projectId, setProjectId] = useState('');

  const attachMut = useMutation({
    mutationFn: () => portfolioCpmApi.attachProject(nodeId, projectId.trim()),
    onSuccess: () => {
      setProjectId('');
      onAttached();
      addToast({
        type: 'success',
        title: t('portfolio.project_filed', { defaultValue: 'Project filed' }),
        message: t('portfolio.project_filed_detail', {
          defaultValue: 'The project now rolls up under this node.',
        }),
      });
    },
    onError,
  });

  return (
    <div className="mb-1 ml-6 mt-1 flex items-center gap-2" data-testid="portfolio-attach-row">
      <input
        type="text"
        value={projectId}
        onChange={(e) => setProjectId(e.target.value)}
        placeholder={t('portfolio.project_id_ph', { defaultValue: 'Project id to file here' })}
        aria-label={t('portfolio.project_id', { defaultValue: 'Project id' })}
        className={`${inputCls} h-8 flex-1`}
      />
      <Button
        variant="ghost"
        size="sm"
        onClick={() => attachMut.mutate()}
        disabled={attachMut.isPending || projectId.trim().length === 0}
        icon={attachMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <FolderPlus size={13} />}
      >
        {t('portfolio.file_project', { defaultValue: 'File' })}
      </Button>
    </div>
  );
}

/* ── CPM panel ───────────────────────────────────────────────────────────── */

function CpmPanel({ selectedNodeId, flat }: { selectedNodeId: string; flat: FlatNode[] }) {
  const { t } = useTranslation();

  const selectedNode = flat.find((f) => f.node.id === selectedNodeId)?.node;

  const cpmQ = useQuery<PortfolioCpmResult>({
    queryKey: ['portfolio', 'cpm', selectedNodeId],
    queryFn: () => portfolioCpmApi.nodeCpm(selectedNodeId),
    enabled: !!selectedNodeId,
  });

  if (!selectedNodeId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Network size={28} strokeWidth={1.5} />}
          title={t('portfolio.cpm_pick_node', { defaultValue: 'Pick a node' })}
          description={t('portfolio.cpm_pick_node_desc', {
            defaultValue:
              'Select a portfolio or programme on the left to run a cross-project critical-path pass across every schedule filed under it.',
          })}
        />
      </Card>
    );
  }

  if (cpmQ.isLoading) {
    return (
      <Card padding="md" data-testid="portfolio-cpm-loading">
        <SkeletonTable rows={6} columns={4} />
      </Card>
    );
  }
  if (cpmQ.isError) {
    return (
      <Card padding="md">
        <RecoveryCard error={cpmQ.error} onRetry={() => cpmQ.refetch()} />
      </Card>
    );
  }

  const cpm = cpmQ.data;
  if (!cpm) return null;

  return (
    <div className="space-y-4" data-testid="portfolio-cpm">
      <Card padding="md">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <GitBranch size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('portfolio.cpm_title', { defaultValue: 'Portfolio critical path' })}
          </h3>
          {selectedNode ? (
            <span className="text-xs text-content-tertiary">{selectedNode.name}</span>
          ) : null}
        </div>

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat
            label={t('portfolio.schedules', { defaultValue: 'Schedules' })}
            value={String(cpm.schedule_count)}
          />
          <Stat
            label={t('portfolio.activities', { defaultValue: 'Activities' })}
            value={String(cpm.activity_count)}
          />
          <Stat
            label={t('portfolio.finish_workday', { defaultValue: 'Finish (work-day)' })}
            value={String(cpm.project_finish_workday)}
          />
          <Stat
            label={t('portfolio.cross_applied', { defaultValue: 'Links applied' })}
            value={String(cpm.cross_links_applied)}
          />
          <Stat
            label={t('portfolio.cross_omitted', { defaultValue: 'Links omitted' })}
            value={String(cpm.cross_links_omitted)}
            tone={cpm.cross_links_omitted > 0 ? 'warning' : 'neutral'}
          />
          <Stat
            label={t('portfolio.cp_length', { defaultValue: 'Critical activities' })}
            value={String(cpm.critical_path.length)}
          />
        </dl>

        {cpm.cross_links_omitted > 0 && (
          <p className="mt-3 flex items-start gap-1.5 text-2xs text-semantic-warning">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            {t('portfolio.cross_omitted_hint', {
              defaultValue:
                'Some cross-project links point to a schedule outside this node (or one you cannot access), so they were not applied as edges. File those projects under this node to include them.',
            })}
          </p>
        )}
      </Card>

      {/* The cross-portfolio critical path */}
      <Card padding="none">
        <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
          <ChevronRight size={16} className="text-content-secondary" />
          <h4 className="text-sm font-semibold text-content-primary">
            {t('portfolio.cp_table_title', { defaultValue: 'Critical path' })}
          </h4>
          <Badge variant="neutral" size="sm">
            {cpm.critical_path.length}
          </Badge>
        </div>
        {cpm.activity_count === 0 ? (
          <div className="px-4 py-6">
            <EmptyState
              icon={<Network size={26} strokeWidth={1.5} />}
              title={t('portfolio.cpm_no_activities', { defaultValue: 'No schedules in scope' })}
              description={t('portfolio.cpm_no_activities_desc', {
                defaultValue:
                  'No accessible schedule with activities is filed under this node yet. File a project that has a schedule to roll it up here.',
              })}
            />
          </div>
        ) : cpm.critical_path.length === 0 ? (
          <div className="px-4 py-6 text-sm text-content-tertiary">
            {t('portfolio.cp_empty', {
              defaultValue: 'The critical path is empty - the schedules under this node have no activities.',
            })}
          </div>
        ) : (
          <CpmActivityTable rows={cpm.critical_path} />
        )}
      </Card>
    </div>
  );
}

function CpmActivityTable({ rows }: { rows: PortfolioCpmActivity[] }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="portfolio-cp-table">
        <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
          <tr>
            <th className="px-3 py-2 text-left">
              {t('portfolio.col_schedule', { defaultValue: 'Schedule' })}
            </th>
            <th className="px-3 py-2 text-left">
              {t('portfolio.col_activity', { defaultValue: 'Activity' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('portfolio.col_es', { defaultValue: 'ES' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('portfolio.col_ef', { defaultValue: 'EF' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('portfolio.col_float', { defaultValue: 'Float' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.schedule_id}:${r.activity_id}`} className="border-t border-border-light">
              <td className="px-3 py-2">
                <span className="text-xs text-content-primary" title={r.schedule_id}>
                  {r.schedule_name || shortId(r.schedule_id)}
                </span>
              </td>
              <td className="px-3 py-2">
                <span className="text-xs text-content-primary" title={r.activity_id}>
                  {r.activity_name || shortId(r.activity_id)}
                </span>
              </td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">{r.es}</td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">{r.ef}</td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">{r.total_float}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Cross-links panel ───────────────────────────────────────────────────── */

function CrossLinksPanel({
  activeProjectId,
  onError,
}: {
  activeProjectId: string | null;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();

  const schedulesQ = useQuery<Schedule[]>({
    queryKey: ['portfolio', 'schedules', activeProjectId],
    queryFn: () =>
      scheduleApi.listSchedules(activeProjectId as string).then((page) => page.items),
    enabled: !!activeProjectId,
  });

  const [scheduleId, setScheduleId] = useState<string>('');
  const resolvedScheduleId =
    scheduleId || (schedulesQ.data && schedulesQ.data.length > 0 ? schedulesQ.data[0]!.id : '');

  return (
    <Card padding="md" data-testid="portfolio-crosslinks-panel">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Link2 size={16} className="text-content-secondary" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('portfolio.crosslinks_title', { defaultValue: 'Cross-project links' })}
        </h3>
      </div>
      <p className="mb-3 text-xs text-content-secondary">
        {t('portfolio.crosslinks_subtitle', {
          defaultValue:
            'Dependencies that tie an activity in one project schedule to an activity in another. A link counts in the portfolio CPM above when both of its schedules sit under the analysed node.',
        })}
      </p>

      {!activeProjectId ? (
        <EmptyState
          icon={<Link2 size={26} strokeWidth={1.5} />}
          title={t('portfolio.crosslinks_no_project', { defaultValue: 'Pick a project' })}
          description={t('portfolio.crosslinks_no_project_desc', {
            defaultValue:
              'Choose a project from the header to see and author the cross-schedule dependencies that touch its schedules.',
          })}
        />
      ) : schedulesQ.isLoading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : schedulesQ.isError ? (
        <RecoveryCard error={schedulesQ.error} onRetry={() => schedulesQ.refetch()} />
      ) : (schedulesQ.data?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<GitBranch size={26} strokeWidth={1.5} />}
          title={t('portfolio.crosslinks_no_schedule', { defaultValue: 'No schedules' })}
          description={t('portfolio.crosslinks_no_schedule_desc', {
            defaultValue: 'This project has no schedule yet, so there is nothing to link across projects.',
          })}
        />
      ) : (
        <div className="space-y-4">
          {/* Schedule picker */}
          <div className="max-w-sm">
            <label htmlFor="portfolio-xl-schedule" className={labelCls}>
              {t('portfolio.crosslinks_schedule', { defaultValue: 'Schedule' })}
            </label>
            <select
              id="portfolio-xl-schedule"
              value={resolvedScheduleId}
              onChange={(e) => setScheduleId(e.target.value)}
              className={inputCls}
            >
              {(schedulesQ.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          {resolvedScheduleId && (
            <CrossLinkList scheduleId={resolvedScheduleId} onError={onError} />
          )}

          <CrossLinkCreateForm
            schedules={schedulesQ.data ?? []}
            defaultScheduleId={resolvedScheduleId}
            onError={onError}
          />
        </div>
      )}
    </Card>
  );
}

function CrossLinkList({ scheduleId, onError }: { scheduleId: string; onError: (e: unknown) => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const linksQ = useQuery<CrossLink[]>({
    queryKey: ['portfolio', 'crosslinks', scheduleId],
    queryFn: () => portfolioCpmApi.listCrossLinks(scheduleId),
    enabled: !!scheduleId,
  });

  const deleteMut = useMutation({
    mutationFn: (linkId: string) => portfolioCpmApi.deleteCrossLink(linkId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portfolio', 'crosslinks'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio', 'cpm'] });
      addToast({
        type: 'success',
        title: t('portfolio.link_deleted', { defaultValue: 'Link deleted' }),
        message: t('portfolio.link_deleted_detail', { defaultValue: 'The cross-project link was removed.' }),
      });
    },
    onError,
  });

  const onDelete = (linkId: string) => {
    const ok = window.confirm(
      t('portfolio.link_delete_confirm', {
        defaultValue: 'Delete this cross-project link? The portfolio CPM will no longer honour it.',
      }),
    );
    if (ok) deleteMut.mutate(linkId);
  };

  if (linksQ.isLoading) return <SkeletonTable rows={3} columns={4} />;
  if (linksQ.isError) return <RecoveryCard error={linksQ.error} onRetry={() => linksQ.refetch()} />;

  const links = linksQ.data ?? [];
  if (links.length === 0) {
    return (
      <div className="rounded-lg border border-border-light px-4 py-6 text-sm text-content-tertiary">
        {t('portfolio.crosslinks_empty', {
          defaultValue: 'No cross-project links touch this schedule yet. Add one below.',
        })}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border-light">
      <table className="w-full text-sm" data-testid="portfolio-crosslinks-table">
        <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
          <tr>
            <th className="px-3 py-2 text-left">
              {t('portfolio.xl_predecessor', { defaultValue: 'Predecessor' })}
            </th>
            <th className="px-3 py-2 text-left">
              {t('portfolio.xl_successor', { defaultValue: 'Successor' })}
            </th>
            <th className="px-3 py-2 text-center">
              {t('portfolio.xl_type', { defaultValue: 'Type' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('portfolio.xl_lag', { defaultValue: 'Lag (d)' })}
            </th>
            {/* Named for assistive tech and hidden visually: a column of controls
                still needs a heading, and a single space is not one. */}
            <th className="px-3 py-2 text-right">
              <span className="sr-only">{t('portfolio.col_actions', { defaultValue: 'Actions' })}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {links.map((l) => (
            <tr key={l.id} className="border-t border-border-light">
              <td className="px-3 py-2">
                <LinkEndpoint
                  scheduleName={l.predecessor_schedule_name}
                  activityName={l.predecessor_activity_name}
                  scheduleId={l.predecessor_schedule_id}
                  activityId={l.predecessor_activity_id}
                />
              </td>
              <td className="px-3 py-2">
                <LinkEndpoint
                  scheduleName={l.successor_schedule_name}
                  activityName={l.successor_activity_name}
                  scheduleId={l.successor_schedule_id}
                  activityId={l.successor_activity_id}
                />
              </td>
              <td className="px-3 py-2 text-center">
                <Badge variant="neutral" size="sm">
                  {l.dep_type}
                </Badge>
              </td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">{l.lag_days}</td>
              <td className="px-3 py-2 text-right">
                <button
                  type="button"
                  onClick={() => onDelete(l.id)}
                  disabled={deleteMut.isPending}
                  aria-label={t('portfolio.delete_link', { defaultValue: 'Delete link' })}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-semantic-error disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CrossLinkCreateForm({
  schedules,
  defaultScheduleId,
  onError,
}: {
  schedules: Schedule[];
  defaultScheduleId: string;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [predScheduleId, setPredScheduleId] = useState(defaultScheduleId);
  const [predActivityId, setPredActivityId] = useState('');
  const [succScheduleId, setSuccScheduleId] = useState(defaultScheduleId);
  const [succActivityId, setSuccActivityId] = useState('');
  const [depType, setDepType] = useState<DepType>('FS');
  const [lagDays, setLagDays] = useState('0');

  const createMut = useMutation({
    mutationFn: () =>
      portfolioCpmApi.createCrossLink({
        predecessor_schedule_id: predScheduleId,
        predecessor_activity_id: predActivityId,
        successor_schedule_id: succScheduleId,
        successor_activity_id: succActivityId,
        dep_type: depType,
        lag_days: Number(lagDays) || 0,
      }),
    onSuccess: () => {
      setPredActivityId('');
      setSuccActivityId('');
      setLagDays('0');
      queryClient.invalidateQueries({ queryKey: ['portfolio', 'crosslinks'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio', 'cpm'] });
      addToast({
        type: 'success',
        title: t('portfolio.link_created', { defaultValue: 'Link created' }),
        message: t('portfolio.link_created_detail', {
          defaultValue: 'The cross-project dependency was added.',
        }),
      });
    },
    onError,
  });

  const canSubmit =
    !!predScheduleId &&
    !!predActivityId &&
    !!succScheduleId &&
    !!succActivityId &&
    !(predScheduleId === succScheduleId && predActivityId === succActivityId);

  return (
    <div className="space-y-3 border-t border-border-light pt-4" data-testid="portfolio-crosslink-form">
      <h4 className="text-2xs font-semibold uppercase tracking-wide text-content-secondary">
        {t('portfolio.add_link', { defaultValue: 'Add a cross-project link' })}
      </h4>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <SchedulePlusActivity
          legend={t('portfolio.predecessor', { defaultValue: 'Predecessor' })}
          schedules={schedules}
          scheduleId={predScheduleId}
          onScheduleChange={(v) => {
            setPredScheduleId(v);
            setPredActivityId('');
          }}
          activityId={predActivityId}
          onActivityChange={setPredActivityId}
          idPrefix="portfolio-xl-pred"
        />
        <SchedulePlusActivity
          legend={t('portfolio.successor', { defaultValue: 'Successor' })}
          schedules={schedules}
          scheduleId={succScheduleId}
          onScheduleChange={(v) => {
            setSuccScheduleId(v);
            setSuccActivityId('');
          }}
          activityId={succActivityId}
          onActivityChange={setSuccActivityId}
          idPrefix="portfolio-xl-succ"
        />
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-28">
          <label htmlFor="portfolio-xl-type" className={labelCls}>
            {t('portfolio.xl_type', { defaultValue: 'Type' })}
          </label>
          <select
            id="portfolio-xl-type"
            value={depType}
            onChange={(e) => setDepType(e.target.value as DepType)}
            className={inputCls}
          >
            {DEP_TYPES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="w-28">
          <label htmlFor="portfolio-xl-lag" className={labelCls}>
            {t('portfolio.xl_lag', { defaultValue: 'Lag (d)' })}
          </label>
          <input
            id="portfolio-xl-lag"
            type="number"
            step={1}
            value={lagDays}
            onChange={(e) => setLagDays(e.target.value)}
            className={inputCls}
          />
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => createMut.mutate()}
          disabled={createMut.isPending || !canSubmit}
          icon={createMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
        >
          {t('portfolio.create_link', { defaultValue: 'Create link' })}
        </Button>
      </div>
    </div>
  );
}

/** A schedule select plus an activity select populated from that schedule's gantt. */
function SchedulePlusActivity({
  legend,
  schedules,
  scheduleId,
  onScheduleChange,
  activityId,
  onActivityChange,
  idPrefix,
}: {
  legend: string;
  schedules: Schedule[];
  scheduleId: string;
  onScheduleChange: (v: string) => void;
  activityId: string;
  onActivityChange: (v: string) => void;
  idPrefix: string;
}) {
  const { t } = useTranslation();

  const ganttQ = useQuery<Activity[]>({
    queryKey: ['portfolio', 'gantt-activities', scheduleId],
    queryFn: () => scheduleApi.getGantt(scheduleId).then((g) => g.activities),
    enabled: !!scheduleId,
  });

  return (
    <fieldset className="rounded-lg border border-border-light p-3">
      <legend className="px-1 text-2xs font-semibold uppercase tracking-wide text-content-secondary">
        {legend}
      </legend>
      <div className="space-y-2">
        <div>
          <label htmlFor={`${idPrefix}-schedule`} className={labelCls}>
            {t('portfolio.crosslinks_schedule', { defaultValue: 'Schedule' })}
          </label>
          <select
            id={`${idPrefix}-schedule`}
            value={scheduleId}
            onChange={(e) => onScheduleChange(e.target.value)}
            className={inputCls}
          >
            {schedules.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${idPrefix}-activity`} className={labelCls}>
            {t('portfolio.col_activity', { defaultValue: 'Activity' })}
          </label>
          {ganttQ.isLoading ? (
            <div className="h-9 animate-pulse rounded-lg bg-surface-secondary" />
          ) : (
            <select
              id={`${idPrefix}-activity`}
              value={activityId}
              onChange={(e) => onActivityChange(e.target.value)}
              disabled={(ganttQ.data?.length ?? 0) === 0}
              className={inputCls}
            >
              <option value="">{t('portfolio.pick_activity', { defaultValue: 'Pick an activity' })}</option>
              {(ganttQ.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>
    </fieldset>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────────── */

/** Short, readable form of a long UUID for dense tables (full id in the title). */
function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}...` : id;
}

/**
 * One end of a cross-schedule dependency.
 *
 * Both ends used to read `4f2a91c3... / 8b0e7d21...`, which names nothing a
 * planner can act on - the whole point of the column is to say which activity
 * in which programme the link runs to. The API now joins those names, so the
 * ids appear only where the row they pointed at has been deleted, and they
 * stay in the tooltip either way for anyone reconciling against another tool.
 */
function LinkEndpoint({
  scheduleName,
  activityName,
  scheduleId,
  activityId,
}: {
  scheduleName: string | null;
  activityName: string | null;
  scheduleId: string;
  activityId: string;
}) {
  const named = Boolean(scheduleName || activityName);
  return (
    <span
      className={
        named ? 'text-2xs text-content-secondary' : 'font-mono text-2xs text-content-tertiary'
      }
      title={`${scheduleId} / ${activityId}`}
    >
      {scheduleName ?? shortId(scheduleId)} / {activityName ?? shortId(activityId)}
    </span>
  );
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'warning';
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd
        className={
          'mt-0.5 text-xl font-bold tabular-nums ' +
          (tone === 'warning' ? 'text-semantic-warning' : 'text-content-primary')
        }
      >
        {value}
      </dd>
    </div>
  );
}

export default PortfolioPage;
