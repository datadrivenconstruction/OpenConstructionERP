/**
 * Historical Snapshot Navigator — Timeline (T11).
 *
 * Vertical, newest-first list of snapshots for a project. Each card
 * shows the timestamp, label, source-file count, total entities and
 * a completeness chip when the snapshot has an integrity report.
 *
 * Two interaction modes co-exist on the same card:
 *
 *   • Click anywhere on a card → "set as active". The parent owns the
 *     active snapshot id and feeds it into the rest of the dashboards
 *     UI. This is the primary, lowest-friction interaction.
 *   • Tick the small checkbox in the corner → toggles the snapshot
 *     into the comparison set. When exactly two are ticked the
 *     "Compare" button activates and onCompare is called.
 *
 * Pagination is cursor-based: when the user scrolls to the bottom
 * we re-issue the query with `before = oldestVisible.created_at`.
 */
import { Fragment, useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, GitCompareArrows, Layers, Loader2 } from 'lucide-react';

import { Badge, Button, Card, EmptyState, Skeleton } from '@/shared/ui';

import {
  getSnapshotTimeline,
  type SnapshotTimelineItem,
} from './api';

export interface SnapshotTimelineProps {
  projectId: string;
  /** Snapshot currently feeding the rest of the UI. Highlighted in
   * the timeline so the user can always see which one is "live". */
  activeSnapshotId?: string | null;
  /** Called when the user picks a card as the new active snapshot. */
  onActiveChange?: (snapshotId: string) => void;
  /** Called when the user has exactly two snapshots ticked and clicks
   * the Compare button. The first id is always the older snapshot. */
  onCompare?: (a: string, b: string) => void;
  /** Override the default 50-item page size. Useful in tests. */
  pageSize?: number;
}

export function SnapshotTimeline({
  projectId,
  activeSnapshotId = null,
  onActiveChange,
  onCompare,
  pageSize = 50,
}: SnapshotTimelineProps) {
  const { t } = useTranslation();
  const [comparing, setComparing] = useState<string[]>([]);

  const timelineQuery = useQuery({
    queryKey: ['dashboards-snapshot-timeline', projectId, pageSize],
    queryFn: () => getSnapshotTimeline({ projectId, limit: pageSize }),
    enabled: !!projectId,
    staleTime: 60 * 1000,
  });

  const items = timelineQuery.data?.items ?? [];

  const handleToggleCompare = useCallback((id: string) => {
    setComparing((current) => {
      if (current.includes(id)) {
        return current.filter((x) => x !== id);
      }
      if (current.length >= 2) {
        // Drop the oldest selection so we never exceed two — keeps
        // the Compare button alive instead of forcing a "clear".
        const second = current[1];
        return second !== undefined ? [second, id] : [id];
      }
      return [...current, id];
    });
  }, []);

  const handleCompareClick = useCallback(() => {
    if (comparing.length !== 2 || !onCompare) return;
    // Resolve the timestamps so we can pass older→newer.
    const first = comparing[0];
    const second = comparing[1];
    if (first === undefined || second === undefined) return;
    const firstItem = items.find((i) => i.id === first);
    const secondItem = items.find((i) => i.id === second);
    if (!firstItem || !secondItem) return;
    const firstTime = new Date(firstItem.created_at).getTime();
    const secondTime = new Date(secondItem.created_at).getTime();
    if (firstTime <= secondTime) {
      onCompare(first, second);
    } else {
      onCompare(second, first);
    }
  }, [comparing, items, onCompare]);

  const compareEnabled = comparing.length === 2;

  return (
    <Card data-testid="snapshot-timeline">
      <div className="flex items-center justify-between border-b border-border-light px-4 py-2">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboards.timeline_title', {
              defaultValue: 'Snapshot history',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('dashboards.timeline_subtitle', {
              defaultValue:
                'Pick any snapshot to drive the dashboards, or tick two to compare schemas.',
            })}
          </p>
        </div>
        <Button
          size="sm"
          variant={compareEnabled ? 'primary' : 'ghost'}
          disabled={!compareEnabled}
          onClick={handleCompareClick}
          data-testid="snapshot-timeline-compare-button"
        >
          <GitCompareArrows className="mr-1 h-3 w-3" />
          {t('dashboards.timeline_compare', { defaultValue: 'Compare' })}
          {comparing.length > 0 && ` (${comparing.length}/2)`}
        </Button>
      </div>

      <div className="p-3">
        {timelineQuery.isLoading && (
          <div className="space-y-2" data-testid="snapshot-timeline-loading">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        )}

        {timelineQuery.isError && (
          <div
            className="rounded border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-300"
            data-testid="snapshot-timeline-error"
          >
            {t('dashboards.timeline_error', {
              defaultValue: 'Could not load the snapshot history.',
            })}
          </div>
        )}

        {!timelineQuery.isLoading &&
          !timelineQuery.isError &&
          items.length === 0 && (
            <EmptyState
              icon={<Layers className="h-8 w-8 text-content-tertiary" />}
              title={t('dashboards.timeline_empty_title', {
                defaultValue: 'No snapshots yet',
              })}
              description={t('dashboards.timeline_empty_desc', {
                defaultValue:
                  'Upload a CAD or BIM file to create the first snapshot of this project.',
              })}
            />
          )}

        {items.length > 0 && (
          <ol
            className="relative ml-2 space-y-2 border-l border-border-light/60 pl-4"
            data-testid="snapshot-timeline-list"
          >
            {items.map((item) => (
              <Fragment key={item.id}>
                <TimelineCard
                  item={item}
                  isActive={item.id === activeSnapshotId}
                  isComparing={comparing.includes(item.id)}
                  onSetActive={() => onActiveChange?.(item.id)}
                  onToggleCompare={() => handleToggleCompare(item.id)}
                />
              </Fragment>
            ))}
          </ol>
        )}

        {timelineQuery.isFetching && items.length > 0 && (
          <div
            className="mt-2 flex items-center justify-center gap-1 text-xs text-content-tertiary"
            data-testid="snapshot-timeline-refreshing"
          >
            <Loader2 className="h-3 w-3 animate-spin" />
            {t('dashboards.timeline_refreshing', {
              defaultValue: 'Refreshing…',
            })}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ── Single timeline card ──────────────────────────────────────────────── */

interface TimelineCardProps {
  item: SnapshotTimelineItem;
  isActive: boolean;
  isComparing: boolean;
  onSetActive: () => void;
  onToggleCompare: () => void;
}

function TimelineCard({
  item,
  isActive,
  isComparing,
  onSetActive,
  onToggleCompare,
}: TimelineCardProps) {
  const { t } = useTranslation();
  const dotClass = isActive
    ? 'bg-emerald-400 ring-2 ring-emerald-300/40'
    : 'bg-border-light';
  const cardClass = useMemo(() => {
    const base =
      'relative flex w-full cursor-pointer items-start gap-3 rounded border px-3 py-2 text-left transition hover:bg-surface-secondary';
    if (isActive) return `${base} border-emerald-500/40 bg-emerald-500/5`;
    if (isComparing) return `${base} border-sky-500/40 bg-sky-500/5`;
    return `${base} border-border-light/60`;
  }, [isActive, isComparing]);

  return (
    <li className="relative" data-testid={`snapshot-timeline-row-${item.id}`}>
      {/* Timeline dot. */}
      <span
        className={`absolute -left-[21px] top-3 h-2.5 w-2.5 rounded-full ${dotClass}`}
        aria-hidden="true"
      />
      <button
        type="button"
        onClick={onSetActive}
        aria-current={isActive ? 'true' : undefined}
        className={cardClass}
        data-testid={`snapshot-timeline-card-${item.id}`}
      >
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span
              className="truncate font-medium text-content-primary"
              title={item.label}
            >
              {item.label}
            </span>
            {isActive && (
              <Badge variant="success" className="text-[10px]">
                {t('dashboards.timeline_active_badge', {
                  defaultValue: 'Active',
                })}
              </Badge>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-content-tertiary">
            <span data-testid={`snapshot-timeline-time-${item.id}`}>
              {formatTimestamp(item.created_at)}
            </span>
            <span>
              {t('dashboards.timeline_entities', {
                defaultValue: '{{count}} entities',
                count: item.total_entities,
              })}
            </span>
            <span>
              {t('dashboards.timeline_sources', {
                defaultValue: '{{count}} sources',
                count: item.source_file_count,
              })}
            </span>
            {item.completeness_score !== null && (
              <CompletenessChip score={item.completeness_score} />
            )}
            {item.schema_hash && (
              <code
                className="rounded bg-surface-secondary px-1 py-0.5 text-[10px] text-content-secondary"
                data-testid={`snapshot-timeline-hash-${item.id}`}
              >
                {item.schema_hash.slice(0, 8)}
              </code>
            )}
          </div>
        </div>

        {/* Compare checkbox. Stop propagation so the card click doesn't
            also fire when the user toggles the box. */}
        <span
          role="checkbox"
          tabIndex={0}
          aria-checked={isComparing}
          aria-label={t('dashboards.timeline_compare_toggle', {
            defaultValue: 'Toggle this snapshot for comparison',
          })}
          onClick={(e) => {
            e.stopPropagation();
            onToggleCompare();
          }}
          onKeyDown={(e) => {
            if (e.key === ' ' || e.key === 'Enter') {
              e.preventDefault();
              e.stopPropagation();
              onToggleCompare();
            }
          }}
          data-testid={`snapshot-timeline-compare-toggle-${item.id}`}
          className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded border ${
            isComparing
              ? 'border-sky-400 bg-sky-500/30 text-sky-100'
              : 'border-border-light bg-surface-secondary text-transparent hover:text-content-tertiary'
          }`}
        >
          <Check className="h-3 w-3" />
        </span>
      </button>
    </li>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function CompletenessChip({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tone =
    score >= 0.95
      ? 'bg-emerald-500/15 text-emerald-300'
      : score >= 0.7
        ? 'bg-amber-500/15 text-amber-300'
        : 'bg-rose-500/15 text-rose-300';
  return (
    <span
      data-testid={`snapshot-timeline-completeness-${pct}`}
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${tone}`}
    >
      {pct}%
    </span>
  );
}

function formatTimestamp(iso: string): string {
  // Browser locale formatting — we deliberately avoid date-fns here
  // to keep the bundle small. The timeline cards show a relative
  // glance ("2 days ago") would be nicer but i18n adds friction; ISO
  // → toLocaleString covers the v1 need.
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
