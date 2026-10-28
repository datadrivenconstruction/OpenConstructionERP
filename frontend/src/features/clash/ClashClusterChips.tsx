// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ClashClusterChips — Wave A4 cluster-filter strip rendered above the
// review-result table. Each cluster surfaces as a coloured chip carrying
// the heuristic label + member count; clicking a chip filters the result
// list to that cluster_id, clicking the active chip (or the "All" chip)
// clears the filter. The colour palette is keyed off the dominant
// discipline pair so a coordinator can spot trade-specific hotspots at
// a glance.
//
// Engine-derived data, no client recomputation — the backend already
// labelled each cluster (`label`, `size`, `dominant_disciplines`,
// `storey`) so the chip is a thin presentation wrapper.

import { useState } from 'react';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ClipboardList } from 'lucide-react';

import { clashApi, type ClashCluster } from './api';
import { ClashGroupActionDialog } from './ClashGroupActionDialog';

const DISCIPLINE_COLOR: Record<string, string> = {
  Structural: 'bg-rose-100 text-rose-800 ring-rose-200 hover:bg-rose-200',
  Architectural: 'bg-amber-100 text-amber-800 ring-amber-200 hover:bg-amber-200',
  Mechanical: 'bg-emerald-100 text-emerald-800 ring-emerald-200 hover:bg-emerald-200',
  Electrical: 'bg-sky-100 text-sky-800 ring-sky-200 hover:bg-sky-200',
  Plumbing: 'bg-indigo-100 text-indigo-800 ring-indigo-200 hover:bg-indigo-200',
  Civil: 'bg-stone-100 text-stone-800 ring-stone-200 hover:bg-stone-200',
};

const NEUTRAL = 'bg-surface-secondary text-content-secondary ring-border hover:bg-surface-tertiary';

function chipPalette(dominant: string[]): string {
  for (const d of dominant) {
    const hit = DISCIPLINE_COLOR[d];
    if (hit) return hit;
  }
  return NEUTRAL;
}

export interface ClashClusterChipsProps {
  projectId: string;
  runId: string;
  /** Currently selected cluster id, or `null` for "All". */
  selectedClusterId: number | null;
  onSelect: (clusterId: number | null) => void;
  /** Total clashes in the run — used by the "All" chip count. */
  totalClashes: number;
  /** When set, the strip can be hidden via the parent flag (no clusters /
   *  cluster ribbon disabled). Mostly used for tests. */
  hidden?: boolean;
  /** Show the "Create work item" action when a cluster is selected. The
   *  coordinator can collapse the whole group into one punch item / task.
   *  Defaults on; pass false to hide it (e.g. for a read-only viewer). */
  enableGroupAction?: boolean;
  className?: string;
}

export function ClashClusterChips({
  projectId,
  runId,
  selectedClusterId,
  onSelect,
  totalClashes,
  hidden,
  enableGroupAction = true,
  className,
}: ClashClusterChipsProps) {
  const { t } = useTranslation();
  const [actionOpen, setActionOpen] = useState(false);
  const { data, isLoading } = useQuery<ClashCluster[]>({
    queryKey: ['clash', projectId, runId, 'clusters'],
    queryFn: () => clashApi.listClusters(projectId, runId),
    enabled: !!projectId && !!runId && !hidden,
  });

  if (hidden) return null;
  if (isLoading) return null;
  const clusters = data ?? [];
  if (clusters.length === 0) return null;

  return (
    <div
      className={clsx(
        'flex flex-wrap items-center gap-2 px-3 py-2',
        'rounded-md border border-border bg-surface-secondary/40',
        className,
      )}
      data-testid="clash-cluster-chips"
      aria-label={t('clash.clusters.aria', { defaultValue: 'Filter by cluster' })}
    >
      <button
        type="button"
        onClick={() => onSelect(null)}
        aria-pressed={selectedClusterId === null}
        className={clsx(
          'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
          'ring-1 transition-colors',
          selectedClusterId === null
            ? 'bg-oe-blue text-content-inverse ring-oe-blue'
            : NEUTRAL,
        )}
      >
        {t('clash.clusters.all', { defaultValue: 'All' })}
        <span className="rounded-full bg-black/10 px-1.5 text-2xs">
          {totalClashes}
        </span>
      </button>
      {clusters.map((c) => {
        const active = c.cluster_id === selectedClusterId;
        return (
          <button
            type="button"
            key={c.cluster_id}
            onClick={() => onSelect(active ? null : c.cluster_id)}
            aria-pressed={active}
            title={
              c.storey != null
                ? t('clash.clusters.level', {
                    defaultValue: 'Level {{level}}',
                    level: c.storey,
                  })
                : undefined
            }
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
              'ring-1 transition-colors',
              active
                ? 'bg-oe-blue text-content-inverse ring-oe-blue'
                : chipPalette(c.dominant_disciplines),
            )}
            data-testid={`cluster-chip-${c.cluster_id}`}
          >
            <span className="truncate max-w-[18ch]">
              {c.label ||
                t('clash.clusters.fallback_label', {
                  defaultValue: 'Cluster {{id}}',
                  id: c.cluster_id,
                })}
            </span>
            <span className="rounded-full bg-black/10 px-1.5 text-2xs">{c.size}</span>
          </button>
        );
      })}

      {enableGroupAction && selectedClusterId != null && (
        <button
          type="button"
          onClick={() => setActionOpen(true)}
          className={clsx(
            'ml-1 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
            'ring-1 transition-colors',
            'bg-surface-primary text-oe-blue ring-oe-blue/40 hover:bg-oe-blue/10',
          )}
          data-testid="cluster-create-action"
          title={t('clash.groupAction.buttonHint', {
            defaultValue: 'Create one punch item or task for this whole clash group',
          })}
        >
          <ClipboardList size={13} />
          {t('clash.groupAction.button', { defaultValue: 'Create work item' })}
        </button>
      )}

      {enableGroupAction && selectedClusterId != null && actionOpen && (
        <ClashGroupActionDialog
          projectId={projectId}
          runId={runId}
          clusterId={selectedClusterId}
          open={actionOpen}
          onClose={() => setActionOpen(false)}
        />
      )}
    </div>
  );
}
