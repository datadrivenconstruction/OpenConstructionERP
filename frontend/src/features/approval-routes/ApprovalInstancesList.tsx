// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ApprovalInstancesList — running + recent approval workflows, filtered
// by target kind / status. Rows are clickable: opening a row reveals the
// full step ladder in ApprovalInstanceDetailDrawer with approve / reject /
// cancel actions, so an admin can act on a stuck workflow here (the same
// actions are also offered on the originating consumer page via the
// ApprovalInstanceCard drop-in).

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronRight, ListChecks, RefreshCw, Search } from 'lucide-react';

import { Badge, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import {
  approvalRoutesKeys,
  getMeta,
  listInstances,
  listRoutes,
} from './api';
import { ApprovalInstanceDetailDrawer } from './ApprovalInstanceDetailDrawer';
import { kindLabel } from './labels';
import type { ApprovalInstance, InstanceStatus } from './types';
import { getIntlLocale } from '@/shared/lib/formatters';

// Mirrors models.INSTANCE_STATUSES — ``pending`` is the active state
// (there is no separate ``in_progress``).
const STATUSES: InstanceStatus[] = [
  'pending',
  'approved',
  'rejected',
  'cancelled',
];

function statusBadge(status: InstanceStatus): {
  variant: 'neutral' | 'blue' | 'success' | 'warning' | 'error';
} {
  return {
    variant:
      status === 'approved'
        ? 'success'
        : status === 'rejected'
          ? 'error'
          : status === 'cancelled'
            ? 'neutral'
            : 'blue',
  };
}

export interface ApprovalInstancesListProps {
  /** Pre-select a target kind filter (no UI control when set). */
  targetKind?: string | null;
  /** Pre-select a project filter. */
  projectId?: string | null;
  /** Seed the status filter (e.g. when drilling in from the Analytics
   *  tab). Only the initial value - the user can still change it. */
  initialStatus?: InstanceStatus | '';
}

export function ApprovalInstancesList({
  targetKind: pinnedKind,
  projectId,
  initialStatus,
}: ApprovalInstancesListProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [kindFilter, setKindFilter] = useState<string>(pinnedKind ?? '');
  const [statusFilter, setStatusFilter] = useState<InstanceStatus | ''>(initialStatus ?? '');
  const [search, setSearch] = useState('');
  const [openInstanceId, setOpenInstanceId] = useState<string | null>(null);

  const effectiveKind = pinnedKind ?? (kindFilter || null);

  // Target kinds come straight from the backend whitelist so the picker
  // can never drift from the validated set.
  const { data: meta } = useQuery({
    queryKey: approvalRoutesKeys.meta(),
    queryFn: () => getMeta(),
    staleTime: 10 * 60_000,
  });
  const targetKinds = meta?.target_kinds ?? [];

  const instancesKey = approvalRoutesKeys.instances(
    effectiveKind,
    null,
    projectId,
    statusFilter || null,
  );

  // Pending instances are the actionable set; auto-refresh that view so a
  // workflow approved elsewhere does not look stuck here. Closed-status
  // views are stable and do not need polling.
  const wantsAutoRefresh = statusFilter === 'pending' || statusFilter === '';

  const {
    data: instances = [],
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: instancesKey,
    queryFn: () =>
      listInstances({
        targetKind: effectiveKind,
        projectId,
        status: statusFilter || null,
      }),
    staleTime: 15_000,
    refetchInterval: wantsAutoRefresh ? 30_000 : false,
    refetchOnWindowFocus: true,
  });

  // Resolve route templates so each row can show the human route name
  // (and total step count for "Step n of m") instead of a bare UUID.
  const { data: routes = [] } = useQuery({
    queryKey: approvalRoutesKeys.routes(projectId ?? null, effectiveKind),
    queryFn: () =>
      listRoutes({ projectId, targetKind: effectiveKind, includeInactive: true }),
    staleTime: 60_000,
  });
  const routeMap = useMemo(() => {
    const m = new Map<string, { name: string; stepCount: number }>();
    for (const r of routes) {
      m.set(r.id, { name: r.name, stepCount: r.steps.length });
    }
    return m;
  }, [routes]);

  const filtered = instances.filter((i) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    const routeName = routeMap.get(i.route_id)?.name ?? '';
    // Search the human-readable surface (route name + kind) — users never
    // type a raw target UUID.
    return (
      routeName.toLowerCase().includes(q) ||
      kindLabel(t, i.target_kind).toLowerCase().includes(q) ||
      i.target_kind.toLowerCase().includes(q)
    );
  });

  return (
    <Card padding="none" className="overflow-hidden">
      <div className="flex items-center gap-2 flex-wrap px-3 py-2 border-b border-border-light bg-surface-secondary/40">
        {!pinnedKind && (
          <select
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
            aria-label={t('approvalRoutes.filter_kind', {
              defaultValue: 'Filter by kind',
            })}
          >
            <option value="">
              {t('approvalRoutes.all_kinds', { defaultValue: 'All target kinds' })}
            </option>
            {targetKinds.map((k) => (
              <option key={k} value={k}>
                {kindLabel(t, k)}
              </option>
            ))}
          </select>
        )}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as InstanceStatus | '')}
          className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
          aria-label={t('approvalRoutes.filter_status', {
            defaultValue: 'Filter by status',
          })}
        >
          <option value="">
            {t('approvalRoutes.all_statuses', { defaultValue: 'All statuses' })}
          </option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`approvalRoutes.status_${s}`, {
                defaultValue: s.charAt(0).toUpperCase() + s.slice(1),
              })}
            </option>
          ))}
        </select>
        <div className="relative flex-1 min-w-[180px] max-w-xs ml-auto">
          <Search
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('approvalRoutes.search_instances_placeholder', {
              defaultValue: 'Search by route or kind…',
            })}
            aria-label={t('approvalRoutes.search_instances_placeholder', {
              defaultValue: 'Search by route or kind…',
            })}
            className="h-8 w-full pl-7 rounded-md border border-border bg-surface-primary text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          />
        </div>
        <button
          type="button"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface-primary text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary disabled:opacity-50 transition-colors"
          title={t('common.refresh', { defaultValue: 'Refresh' })}
          aria-label={t('common.refresh', { defaultValue: 'Refresh' })}
        >
          <RefreshCw
            size={13}
            className={isFetching ? 'animate-spin' : undefined}
          />
        </button>
      </div>

      {isLoading ? (
        <div className="p-3">
          <SkeletonTable rows={4} columns={5} />
        </div>
      ) : filtered.length === 0 ? (
        <div className="p-6">
          <EmptyState
            icon={<ListChecks size={28} strokeWidth={1.5} />}
            title={t('approvalRoutes.empty_instances_title', {
              defaultValue: 'No approval workflows',
            })}
            description={t('approvalRoutes.empty_instances_desc', {
              defaultValue:
                'Approval workflows started from any module (markups, submittals, RFIs, …) show up here. Start one from the matching record.',
            })}
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/30">
              <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('approvalRoutes.col_route', { defaultValue: 'Route' })}
              </th>
              <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('approvalRoutes.col_target', { defaultValue: 'Target' })}
              </th>
              <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('approvalRoutes.col_status', { defaultValue: 'Status' })}
              </th>
              <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('approvalRoutes.col_step', { defaultValue: 'Step' })}
              </th>
              <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('approvalRoutes.col_started', { defaultValue: 'Started' })}
              </th>
              <th className="px-3 py-2 w-8" aria-hidden="true" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {filtered.map((i) => (
              <InstanceRow
                key={i.id}
                instance={i}
                route={routeMap.get(i.route_id)}
                onOpen={() => setOpenInstanceId(i.id)}
              />
            ))}
          </tbody>
        </table>
        </div>
      )}

      <ApprovalInstanceDetailDrawer
        instanceId={openInstanceId}
        onClose={() => {
          setOpenInstanceId(null);
          // Pick up any decision made inside the drawer.
          void qc.invalidateQueries({ queryKey: instancesKey });
        }}
      />
    </Card>
  );
}

function InstanceRow({
  instance,
  route,
  onOpen,
}: {
  instance: ApprovalInstance;
  route?: { name: string; stepCount: number };
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const { variant } = statusBadge(instance.status);
  return (
    <tr
      onClick={onOpen}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
      aria-label={t('approvalRoutes.open_instance', {
        defaultValue: 'Open workflow details',
      })}
      className="cursor-pointer hover:bg-surface-secondary/40 transition-colors focus:outline-none focus:bg-surface-secondary/60"
    >
      <td className="px-3 py-2.5 text-xs font-medium text-content-primary">
        {route?.name ?? (
          <span className="text-content-tertiary italic">
            {t('approvalRoutes.unknown_route', { defaultValue: 'Unknown route' })}
          </span>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs text-content-secondary">
        <span className="inline-flex items-center gap-1">
          <span>{kindLabel(t, instance.target_kind)}</span>
          <span
            className="text-content-tertiary tabular-nums"
            title={instance.target_id}
          >
            {instance.target_id.slice(0, 8)}…
          </span>
        </span>
      </td>
      <td className="px-3 py-2.5">
        <Badge variant={variant} size="sm">
          {t(`approvalRoutes.status_${instance.status}`, {
            defaultValue:
              instance.status.charAt(0).toUpperCase() + instance.status.slice(1),
          })}
        </Badge>
      </td>
      <td className="px-3 py-2.5 text-xs text-content-secondary tabular-nums">
        {instance.status === 'pending'
          ? route?.stepCount
            ? t('approvalRoutes.step_n_of_m', {
                defaultValue: 'Step {{n}}/{{m}}',
                n: instance.current_step_ordinal,
                m: route.stepCount,
              })
            : t('approvalRoutes.step_n', {
                defaultValue: 'Step {{n}}',
                n: instance.current_step_ordinal,
              })
          : '—'}
      </td>
      <td className="px-3 py-2.5 text-xs text-content-tertiary">
        {new Date(instance.started_at).toLocaleDateString(getIntlLocale())}
      </td>
      <td className="px-3 py-2.5 text-right">
        <ChevronRight size={14} className="text-content-tertiary inline" />
      </td>
    </tr>
  );
}
