/**
 * Historical Snapshot Navigator — Diff view (T11).
 *
 * Side-by-side schema diff. The top row carries summary chips (rows
 * added / removed / columns changed); below that we render three
 * column lists — added (B), removed (A), changed (dtype delta).
 *
 * The component is read-only — it only renders the server-side diff.
 * The parent owns the snapshot ids and chooses *which* pair to compare.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowRight, MinusCircle, PlusCircle, Repeat } from 'lucide-react';

import { Badge, Card, EmptyState, Skeleton } from '@/shared/ui';

import { diffSnapshots, type SnapshotDiff } from './api';

export interface SnapshotDiffViewProps {
  /** Older snapshot id. */
  snapshotAId: string;
  /** Newer snapshot id. */
  snapshotBId: string;
}

export function SnapshotDiffView({
  snapshotAId,
  snapshotBId,
}: SnapshotDiffViewProps) {
  const { t } = useTranslation();

  const diffQuery = useQuery({
    queryKey: ['dashboards-snapshot-diff', snapshotAId, snapshotBId],
    queryFn: () => diffSnapshots({ a: snapshotAId, b: snapshotBId }),
    enabled: !!snapshotAId && !!snapshotBId,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <Card data-testid="snapshot-diff-view">
      <div className="border-b border-border-light px-4 py-2">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('dashboards.diff_title', { defaultValue: 'Snapshot diff' })}
        </h3>
        <p className="text-xs text-content-tertiary">
          {t('dashboards.diff_subtitle', {
            defaultValue:
              'Schema-level changes between the two selected snapshots — older on the left, newer on the right.',
          })}
        </p>
      </div>

      <div className="p-3">
        {diffQuery.isLoading && (
          <div className="space-y-3" data-testid="snapshot-diff-loading">
            <Skeleton className="h-12" />
            <Skeleton className="h-32" />
          </div>
        )}

        {diffQuery.isError && (
          <div
            className="rounded border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-300"
            data-testid="snapshot-diff-error"
          >
            {t('dashboards.diff_error', {
              defaultValue: 'Could not compute the diff for these snapshots.',
            })}
          </div>
        )}

        {diffQuery.data && <DiffBody diff={diffQuery.data} />}
      </div>
    </Card>
  );
}

/* ── Body ──────────────────────────────────────────────────────────────── */

function DiffBody({ diff }: { diff: SnapshotDiff }) {
  const { t } = useTranslation();

  if (diff.is_identical) {
    return (
      <div data-testid="snapshot-diff-identical">
        <DiffHeader diff={diff} />
        <SummaryChips diff={diff} />
        <EmptyState
          title={t('dashboards.diff_identical_title', {
            defaultValue: 'Snapshots are identical',
          })}
          description={t('dashboards.diff_identical_desc', {
            defaultValue:
              'No columns were added, removed or retyped, and the row count is unchanged.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <DiffHeader diff={diff} />
      <SummaryChips diff={diff} />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <ColumnList
          variant="added"
          title={t('dashboards.diff_columns_added', {
            defaultValue: 'Columns added',
          })}
          icon={<PlusCircle className="h-3 w-3 text-emerald-400" />}
          names={diff.columns_added}
          testId="snapshot-diff-added"
        />
        <ColumnList
          variant="removed"
          title={t('dashboards.diff_columns_removed', {
            defaultValue: 'Columns removed',
          })}
          icon={<MinusCircle className="h-3 w-3 text-rose-400" />}
          names={diff.columns_removed}
          testId="snapshot-diff-removed"
        />
        <ChangedList changes={diff.columns_changed} />
      </div>
    </div>
  );
}

/* ── Header (snapshot labels) ──────────────────────────────────────────── */

function DiffHeader({ diff }: { diff: SnapshotDiff }) {
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded border border-border-light/60 bg-surface-secondary px-3 py-2 text-xs"
      data-testid="snapshot-diff-header"
    >
      <span
        className="font-medium text-content-primary"
        data-testid="snapshot-diff-a-label"
      >
        {diff.a_label}
      </span>
      <ArrowRight className="h-3 w-3 text-content-tertiary" />
      <span
        className="font-medium text-content-primary"
        data-testid="snapshot-diff-b-label"
      >
        {diff.b_label}
      </span>
      {diff.schema_hash_match && (
        <Badge variant="neutral" className="text-[10px]">
          schema-hash match
        </Badge>
      )}
    </div>
  );
}

/* ── Summary chips ─────────────────────────────────────────────────────── */

function SummaryChips({ diff }: { diff: SnapshotDiff }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-wrap gap-2 text-xs"
      data-testid="snapshot-diff-summary"
    >
      <Chip
        tone={diff.rows_added > 0 ? 'emerald' : 'neutral'}
        label={t('dashboards.diff_rows_added', {
          defaultValue: 'Rows added',
        })}
        value={diff.rows_added}
        testId="snapshot-diff-summary-rows-added"
      />
      <Chip
        tone={diff.rows_removed > 0 ? 'rose' : 'neutral'}
        label={t('dashboards.diff_rows_removed', {
          defaultValue: 'Rows removed',
        })}
        value={diff.rows_removed}
        testId="snapshot-diff-summary-rows-removed"
      />
      <Chip
        tone={diff.columns_changed.length > 0 ? 'amber' : 'neutral'}
        label={t('dashboards.diff_columns_changed', {
          defaultValue: 'Columns changed',
        })}
        value={diff.columns_changed.length}
        testId="snapshot-diff-summary-cols-changed"
      />
    </div>
  );
}

interface ChipProps {
  tone: 'emerald' | 'rose' | 'amber' | 'neutral';
  label: string;
  value: number;
  testId: string;
}

function Chip({ tone, label, value, testId }: ChipProps) {
  const palette: Record<ChipProps['tone'], string> = {
    emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    rose: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    neutral: 'bg-surface-secondary text-content-secondary border-border-light',
  };
  return (
    <span
      data-testid={testId}
      className={`rounded border px-2 py-0.5 ${palette[tone]}`}
    >
      <span className="text-content-tertiary">{label}: </span>
      <span className="font-medium tabular-nums">{value}</span>
    </span>
  );
}

/* ── Column lists ──────────────────────────────────────────────────────── */

interface ColumnListProps {
  variant: 'added' | 'removed';
  title: string;
  icon: React.ReactNode;
  names: string[];
  testId: string;
}

function ColumnList({ variant, title, icon, names, testId }: ColumnListProps) {
  const { t } = useTranslation();
  const tone =
    variant === 'added'
      ? 'border-emerald-500/30 bg-emerald-500/5'
      : 'border-rose-500/30 bg-rose-500/5';
  return (
    <div className={`rounded border ${tone} p-2`} data-testid={testId}>
      <div className="mb-1 flex items-center gap-1 text-xs font-medium text-content-primary">
        {icon}
        <span>{title}</span>
        <span className="text-content-tertiary">({names.length})</span>
      </div>
      {names.length === 0 ? (
        <span className="text-xs text-content-tertiary">
          {t('dashboards.diff_columns_none', { defaultValue: 'None' })}
        </span>
      ) : (
        <ul className="space-y-0.5 text-xs">
          {names.map((name) => (
            <li
              key={name}
              data-testid={`${testId}-${name}`}
              className="truncate font-mono text-content-primary"
              title={name}
            >
              {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ChangedList({
  changes,
}: {
  changes: SnapshotDiff['columns_changed'];
}) {
  const { t } = useTranslation();
  return (
    <div
      className="rounded border border-amber-500/30 bg-amber-500/5 p-2"
      data-testid="snapshot-diff-changed"
    >
      <div className="mb-1 flex items-center gap-1 text-xs font-medium text-content-primary">
        <Repeat className="h-3 w-3 text-amber-400" />
        <span>
          {t('dashboards.diff_columns_changed_title', {
            defaultValue: 'Type changed',
          })}
        </span>
        <span className="text-content-tertiary">({changes.length})</span>
      </div>
      {changes.length === 0 ? (
        <span className="text-xs text-content-tertiary">
          {t('dashboards.diff_columns_none', { defaultValue: 'None' })}
        </span>
      ) : (
        <ul className="space-y-0.5 text-xs">
          {changes.map((c) => (
            <li
              key={c.name}
              data-testid={`snapshot-diff-changed-${c.name}`}
              className="flex flex-wrap items-center gap-1"
            >
              <span
                className="truncate font-mono text-content-primary"
                title={c.name}
              >
                {c.name}
              </span>
              <span className="text-content-tertiary">{c.a_dtype}</span>
              <ArrowRight className="h-3 w-3 text-content-tertiary" />
              <span className="text-amber-300">{c.b_dtype}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
