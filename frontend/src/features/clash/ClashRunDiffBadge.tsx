// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ClashRunDiffBadge — compact, read-only strip surfacing the smart-issue
// lifecycle of the active run relative to the project's PREVIOUS run
// (GET /v1/clash/runs/{id}/diff). It answers "what changed since last
// time" without the coordinator having to pick a baseline run, which is
// what the geometric Compare panel (ClashApi.compare) requires.
//
// The five buckets map 1:1 to the persistent smart-issue identities the
// engine maintains across re-runs:
//   new        signatures first seen in this run
//   persisted  seen in both this run and the previous one (still open)
//   resolved   present in the previous run, gone now (fixed / removed)
//   reopened   a resolved signature that resurfaced this run (regression)
//   ignored    signatures whose smart issue is suppressed
//
// Every count is precomputed server-side; this is a thin presentation
// wrapper. It self-hides on a project's very first run (all zeros, no
// prior run to diff against) so it never clutters an empty baseline, and
// it fails soft - a diff error simply renders nothing rather than break
// the run header.

import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  History,
  PlusCircle,
  CircleDot,
  CheckCircle2,
  RotateCcw,
  EyeOff,
} from 'lucide-react';

import { clashApi, type ClashRunDiff } from './api';

export interface ClashRunDiffBadgeProps {
  projectId: string;
  runId: string;
  className?: string;
}

interface DiffBucket {
  key: keyof ClashRunDiff;
  label: string;
  title: string;
  icon: ReactNode;
  /** Tailwind classes for the pill when the count is non-zero. */
  tone: string;
}

export function ClashRunDiffBadge({
  projectId,
  runId,
  className,
}: ClashRunDiffBadgeProps) {
  const { t } = useTranslation();

  const { data, isLoading, isError } = useQuery<ClashRunDiff>({
    queryKey: ['clash', projectId, runId, 'diff'],
    queryFn: () => clashApi.runDiff(projectId, runId),
    enabled: !!projectId && !!runId,
    // The lifecycle diff is derived from persistent issues, not the live
    // result rows; a short stale window is fine and avoids refetch churn
    // when the user toggles filters on the same run.
    staleTime: 60_000,
  });

  // Fail soft: never let a diff hiccup break the run header.
  if (isLoading || isError || !data) return null;

  // Coerce defensively - the wire contract is non-negative ints, but a
  // malformed payload must not render NaN.
  const counts = {
    new: Math.max(0, Math.trunc(Number(data.new) || 0)),
    persisted: Math.max(0, Math.trunc(Number(data.persisted) || 0)),
    resolved: Math.max(0, Math.trunc(Number(data.resolved) || 0)),
    reopened: Math.max(0, Math.trunc(Number(data.reopened) || 0)),
    ignored: Math.max(0, Math.trunc(Number(data.ignored) || 0)),
  };

  const total =
    counts.new +
    counts.persisted +
    counts.resolved +
    counts.reopened +
    counts.ignored;
  // First run of a project (no prior run to diff against) - nothing to show.
  if (total === 0) return null;

  const buckets: DiffBucket[] = [
    {
      key: 'new',
      label: t('clash.diff.new', { defaultValue: 'New' }),
      title: t('clash.diff.new_hint', {
        defaultValue: 'Clashes first seen in this run',
      }),
      icon: <PlusCircle size={13} />,
      tone: 'bg-rose-50 text-rose-700 ring-rose-200',
    },
    {
      key: 'reopened',
      label: t('clash.diff.reopened', { defaultValue: 'Reopened' }),
      title: t('clash.diff.reopened_hint', {
        defaultValue: 'Previously resolved clashes that came back this run',
      }),
      icon: <RotateCcw size={13} />,
      tone: 'bg-orange-50 text-orange-700 ring-orange-200',
    },
    {
      key: 'persisted',
      label: t('clash.diff.persisted', { defaultValue: 'Persisting' }),
      title: t('clash.diff.persisted_hint', {
        defaultValue: 'Open clashes carried over from the previous run',
      }),
      icon: <CircleDot size={13} />,
      tone: 'bg-amber-50 text-amber-700 ring-amber-200',
    },
    {
      key: 'resolved',
      label: t('clash.diff.resolved', { defaultValue: 'Resolved' }),
      title: t('clash.diff.resolved_hint', {
        defaultValue: 'Clashes from the previous run that are gone now',
      }),
      icon: <CheckCircle2 size={13} />,
      tone: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    },
    {
      key: 'ignored',
      label: t('clash.diff.ignored', { defaultValue: 'Suppressed' }),
      title: t('clash.diff.ignored_hint', {
        defaultValue: 'Clashes whose smart issue is suppressed',
      }),
      icon: <EyeOff size={13} />,
      tone: 'bg-surface-secondary text-content-secondary ring-border',
    },
  ];

  const visible = buckets.filter((b) => counts[b.key] > 0);
  // Defensive: total > 0 guarantees at least one visible bucket, but keep
  // the guard so the container never renders an empty shell.
  if (visible.length === 0) return null;

  return (
    <div
      className={clsx(
        'flex flex-wrap items-center gap-2 px-3 py-2',
        'rounded-md border border-border bg-surface-secondary/40',
        className,
      )}
      data-testid="clash-run-diff-badge"
      aria-label={t('clash.diff.aria', {
        defaultValue: 'Smart-issue changes since the previous run',
      })}
    >
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-content-secondary">
        <History size={14} className="text-content-tertiary" />
        {t('clash.diff.label', { defaultValue: 'Since last run' })}
      </span>
      {visible.map((b) => (
        <span
          key={b.key}
          title={b.title}
          className={clsx(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1',
            b.tone,
          )}
          data-testid={`clash-run-diff-${b.key}`}
        >
          {b.icon}
          <span>{b.label}</span>
          <span className="rounded-full bg-black/10 px-1.5 text-2xs tabular-nums">
            {counts[b.key]}
          </span>
        </span>
      ))}
    </div>
  );
}
