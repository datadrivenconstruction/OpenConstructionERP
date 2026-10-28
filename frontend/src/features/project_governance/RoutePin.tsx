// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Which approval route the project's gate decisions, and the changes to its
// binding documents, run on.
//
// Governance uses only the route that is pinned here; nothing is picked on
// the project's behalf. A gate goes to review on the pinned gate route, and
// the people on that route's last step are the ones entitled to decide.
// Without a pin no gate can be submitted and no change request raised, which
// the section says in words. The server takes only an active route of this
// project and of the right kind, so only those are offered.

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Route as RouteIcon } from 'lucide-react';

import { listRoutes } from '@/features/approval-routes/api';
import { Button } from '@/shared/ui/Button';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { governanceKeys, updateModelSettings, type GovernanceModel } from './api';
import { canManage } from './access';
import { VerdictReason } from './GovernanceBits';
import { refusalText, type KeyText } from './labels';

export type RoutePinKind = 'gate' | 'change';

interface KindSpec {
  /** The approval-route target kind, as the backend names it. */
  targetKind: string;
  field: 'decision_route_id' | 'change_route_id';
  title: KeyText;
  body: KeyText;
  unpinned: KeyText;
}

const KINDS: Record<RoutePinKind, KindSpec> = {
  gate: {
    targetKind: 'phase_gate',
    field: 'decision_route_id',
    title: ['governance.project.route.title', 'Approval route for gate decisions'],
    body: [
      'governance.project.route.body',
      'A gate goes to review on this route. The people on its last step are the ones who may record the decision.',
    ],
    unpinned: [
      'governance.project.route.none_pinned',
      'No route is chosen yet, so no gate can be submitted for review. Choose one of the routes of this project.',
    ],
  },
  change: {
    targetKind: 'frame_change',
    field: 'change_route_id',
    title: ['governance.project.route.change_title', 'Approval route for changes to binding documents'],
    body: [
      'governance.project.route.change_body',
      'A change request on a binding frame document is approved on this route.',
    ],
    unpinned: [
      'governance.project.route.change_none_pinned',
      'No route is chosen yet, so no change request can be raised. Choose one of the routes of this project.',
    ],
  },
};

export const ROUTE_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  ROUTE_TITLE: { gate: KINDS.gate.title, change: KINDS.change.title },
  ROUTE_BODY: { gate: KINDS.gate.body, change: KINDS.change.body },
  ROUTE_UNPINNED: { gate: KINDS.gate.unpinned, change: KINDS.change.unpinned },
};

const ROUTES_PAGE = '/governance?tab=approvals';

export interface RoutePinProps {
  projectId: string;
  model: GovernanceModel;
  kind: RoutePinKind;
  onDone: () => void;
}

export function RoutePin({ projectId, model, kind, onDone }: RoutePinProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const spec = KINDS[kind];
  const verdict = canManage(model);
  const routes = useQuery({
    queryKey: governanceKeys.routes(projectId, spec.targetKind),
    queryFn: () => listRoutes({ projectId, targetKind: spec.targetKind, includeInactive: false }),
  });
  const pin = useMutation({
    mutationFn: (routeId: string | null) =>
      updateModelSettings(projectId, kind === 'gate' ? { decision_route_id: routeId } : { change_route_id: routeId }),
    onSuccess: (_model, routeId) => {
      addToast({
        type: 'success',
        title: routeId
          ? t('governance.project.route.pinned', { defaultValue: 'Approval route chosen' })
          : t('governance.project.route.unpinned', { defaultValue: 'Approval route removed' }),
      });
      onDone();
    },
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });

  // The list may also name routes shared across projects; the server pins only the project's own.
  const list = (routes.data ?? []).filter((r) => r.project_id === projectId);
  const pinned = model[spec.field];
  const pinnedMissing = !!pinned && routes.isSuccess && !list.some((r) => r.id === pinned);
  const title = t(spec.title[0], { defaultValue: spec.title[1] });

  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid={`route-pin-${kind}`}>
      <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <RouteIcon size={15} className="text-content-tertiary" aria-hidden />
        {title}
      </h3>
      <p className="mt-1 text-xs text-content-secondary">{t(spec.body[0], { defaultValue: spec.body[1] })}</p>

      {routes.isLoading && (
        <p className="mt-2 text-xs text-content-tertiary">{t('governance.project.loading', { defaultValue: 'Loading...' })}</p>
      )}
      {routes.isError && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-semantic-error" role="alert">
          {t('governance.project.route.load_failed', { defaultValue: 'The approval routes could not be loaded.' })}{' '}
          {getErrorMessage(routes.error)}
          <Button size="sm" variant="ghost" onClick={() => routes.refetch()}>
            {t('governance.project.retry', { defaultValue: 'Try again' })}
          </Button>
        </p>
      )}
      {routes.isSuccess && list.length === 0 && (
        <p className="mt-2 text-sm text-content-secondary" data-testid="route-pin-empty">
          {t('governance.project.route.empty', {
            defaultValue:
              'This project has no active approval route of this kind yet. Create one for the project and put the deciders on its last step, then choose it here.',
          })}{' '}
          <Link to={ROUTES_PAGE} className="font-medium text-oe-blue hover:underline">
            {t('governance.project.route.open_routes', { defaultValue: 'Open approval routes' })}
          </Link>
        </p>
      )}
      {pinnedMissing && (
        <p className="mt-2 text-sm text-semantic-error" role="alert" data-testid="route-pin-missing">
          {t('governance.project.route.pinned_missing', {
            defaultValue: 'The chosen route is no longer an active route of this project, so it cannot be used. Choose another one.',
          })}
        </p>
      )}
      {routes.isSuccess && !pinned && list.length > 0 && (
        <p className="mt-2 text-sm text-[#b45309]" data-testid="route-pin-none">
          {t(spec.unpinned[0], { defaultValue: spec.unpinned[1] })}
        </p>
      )}
      {routes.isSuccess && (list.length > 0 || !!pinned) && (
        <div className="mt-2 flex flex-col items-start gap-1">
          <select
            aria-label={title}
            className="min-w-[16rem] rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary disabled:opacity-60"
            value={pinnedMissing ? '' : pinned ?? ''}
            disabled={!!verdict || pin.isPending}
            onChange={(e) => pin.mutate(e.target.value || null)}
          >
            <option value="">{t('governance.project.route.no_route_option', { defaultValue: 'No route chosen' })}</option>
            {list.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <VerdictReason verdict={verdict} />
        </div>
      )}
    </section>
  );
}
