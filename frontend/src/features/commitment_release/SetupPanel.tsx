// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How releases are approved on this project, in three steps a manager takes
// once: choose the authority schedule (who approves up to which amount) and
// how strictly awards are held to it, name the people behind each tier, and
// check the result with "Who approves?".
//
// The same settings form is the first thing a project without a matrix
// shows, because nothing else can be entered before a schedule is chosen.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';

import { listRoutes } from '@/features/approval-routes/api';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { getErrorMessage } from '@/shared/lib/api';

import {
  evaluateSchedule,
  generateRoutes,
  pinTierRoute,
  unpinTierRoute,
  putAssignments,
  setMatrix,
  type Assignment,
  type AssignmentInput,
  type CatalogueSource,
  type CommitmentMatrix,
  type Enforcement,
  type EvaluateResult,
  type FxPolicy,
  type ProjectCan,
  type RouteReport,
} from './api';
import { projectVerdict } from './access';
import { FIELD_CLASS, Field, ReasonedButton, RefusalBox, refusalText } from './CommitmentBits';
import { useAssignments, useSchedules } from './hooks';
import {
  ENFORCEMENT,
  ENFORCEMENT_HINT,
  FX_POLICY,
  ROUTE_REPORT,
  catalogueName,
  codeName,
  humanizeCode,
  vocab,
  type LabelContext,
} from './labels';
import { isPositiveAmount, normalizeAmount } from './rules';

const ENFORCEMENTS: Enforcement[] = ['off', 'warn', 'block'];
const FX_POLICIES: FxPolicy[] = ['fx_service_rate_set', 'project_rates'];

export interface MatrixSettingsProps {
  projectId: string;
  /** The current matrix, or null when the project has none yet. */
  matrix: CommitmentMatrix | null;
  can: ProjectCan | null | undefined;
  labels: LabelContext;
  onSaved: () => void;
}

/** Schedule, enforcement and exchange rate rule. Creates the matrix when there is none. */
export function MatrixSettings({ projectId, matrix, can, labels, onSaved }: MatrixSettingsProps) {
  const { t } = useTranslation();
  const schedulesQ = useSchedules();
  const schedules = (schedulesQ.data ?? []).filter((s) => s.state === 'published' && s.latest_version != null);
  const [picked, setPicked] = useState<string>(matrix ? `${matrix.schedule_source}:${matrix.schedule_id}` : '');
  const [enforcement, setEnforcement] = useState<Enforcement>(matrix?.enforcement ?? 'warn');
  const [fxPolicy, setFxPolicy] = useState<FxPolicy>(matrix?.fx_policy ?? 'fx_service_rate_set');
  const [requireLink, setRequireLink] = useState(matrix?.require_link ?? false);
  const manageV = projectVerdict(can, 'manage');
  const chosen = schedules.find((s) => `${s.source}:${s.id}` === picked) ?? null;

  const save = useMutation({
    mutationFn: () => {
      const [source, ...rest] = picked.split(':');
      const id = rest.join(':');
      const samePin = !!matrix && matrix.schedule_source === source && matrix.schedule_id === id;
      return setMatrix(projectId, {
        // Empty means "the schedule this project's country resolves to".
        ...(picked && !samePin
          ? { schedule_source: source as CatalogueSource, schedule_id: id, schedule_version: chosen?.latest_version ?? undefined }
          : {}),
        enforcement,
        fx_policy: fxPolicy,
        require_link: requireLink,
      });
    },
    onSuccess: onSaved,
  });

  return (
    <section className="space-y-4 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="matrix-settings">
      <div>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('commitment.schedule.title', { defaultValue: 'Authority schedule' })}
        </h3>
        <p className="text-sm text-content-secondary">
          {t('commitment.setup.schedule_intro', {
            defaultValue: 'The schedule says who may approve a commitment up to which amount. Choose the one your organisation works to.',
          })}
        </p>
      </div>

      {save.isError && <RefusalBox message={refusalText(t, save.error)} />}

      {schedulesQ.isError ? (
        <ErrorState
          compact
          title={t('commitment.setup.schedules_failed', { defaultValue: 'The authority schedules could not be loaded' })}
          hint={getErrorMessage(schedulesQ.error)}
          onRetry={() => schedulesQ.refetch()}
        />
      ) : (
        <Field id="matrix-schedule" label={t('commitment.schedule.title', { defaultValue: 'Authority schedule' })}>
          <select
            id="matrix-schedule"
            className={FIELD_CLASS}
            value={picked}
            disabled={schedulesQ.isLoading}
            onChange={(e) => setPicked(e.target.value)}
          >
            {schedulesQ.isLoading && (
              <option value={picked}>
                {t('commitment.setup.schedules_loading', { defaultValue: 'Loading the authority schedules' })}
              </option>
            )}
            {!matrix && !schedulesQ.isLoading && (
              <option value="">
                {t('commitment.setup.schedule_default', { defaultValue: "The schedule for the project's country" })}
              </option>
            )}
            {schedules.map((s) => (
              <option key={`${s.source}:${s.id}`} value={`${s.source}:${s.id}`}>
                {catalogueName(labels, s.id, s.name)}
              </option>
            ))}
          </select>
        </Field>
      )}
      {chosen && chosen.review_status !== 'verified' && (
        <p className="flex items-start gap-2 text-xs text-content-secondary" data-testid="schedule-unconfirmed">
          <Badge variant="warning" size="sm">
            {t('commitment.abort_form.unconfirmed', { defaultValue: 'Unconfirmed' })}
          </Badge>
          {t('commitment.setup.schedule_unconfirmed', {
            defaultValue: 'The figures of this schedule are examples and were not confirmed by a domain expert. Check them against your own rules.',
          })}
        </p>
      )}
      {matrix && (
        <p className="text-xs text-content-tertiary" data-testid="schedule-pinned">
          {t('commitment.setup.schedule_pinned', {
            defaultValue: 'In use: version {{version}}, amounts in {{currency}}.',
            version: matrix.schedule_version,
            currency: matrix.schedule_currency,
          })}
        </p>
      )}

      <fieldset>
        <legend className="mb-2 text-sm font-medium text-content-primary">
          {t('commitment.setup.enforcement', { defaultValue: 'When an award or signing goes above the release' })}
        </legend>
        <div className="grid gap-2 sm:grid-cols-3" role="radiogroup">
          {ENFORCEMENTS.map((mode) => (
            <label
              key={mode}
              className={
                enforcement === mode
                  ? 'flex cursor-pointer flex-col gap-1 rounded-lg border border-oe-blue bg-oe-blue-subtle p-3 text-sm'
                  : 'flex cursor-pointer flex-col gap-1 rounded-lg border border-border-light p-3 text-sm hover:border-border'
              }
            >
              <span className="flex items-center gap-2 font-medium text-content-primary">
                <input
                  type="radio"
                  name="matrix-enforcement"
                  value={mode}
                  checked={enforcement === mode}
                  onChange={() => setEnforcement(mode)}
                />
                {vocab(t, ENFORCEMENT, mode)}
              </span>
              <span className="text-xs text-content-secondary">{vocab(t, ENFORCEMENT_HINT, mode)}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          id="matrix-fx"
          label={t('commitment.setup.fx_policy', { defaultValue: 'Exchange rates come from' })}
          hint={t('commitment.setup.fx_policy_hint', {
            defaultValue: 'Used when an amount is in another currency than the schedule.',
          })}
        >
          <select id="matrix-fx" className={FIELD_CLASS} value={fxPolicy} onChange={(e) => setFxPolicy(e.target.value as FxPolicy)}>
            {FX_POLICIES.map((p) => (
              <option key={p} value={p}>
                {vocab(t, FX_POLICY, p)}
              </option>
            ))}
          </select>
        </Field>
        <label className="flex items-start gap-2 self-end pb-1 text-sm text-content-primary">
          <input type="checkbox" className="mt-1" checked={requireLink} onChange={(e) => setRequireLink(e.target.checked)} />
          <span>
            {t('commitment.setup.require_link', { defaultValue: 'Every award must belong to an item' })}
            <span className="block text-xs text-content-tertiary">
              {t('commitment.setup.require_link_hint', {
                defaultValue: 'A contract or order that is not linked to any item is then treated as not released.',
              })}
            </span>
          </span>
        </label>
      </div>

      <ReasonedButton variant="primary" verdict={manageV} loading={save.isPending} onClick={() => save.mutate()} data-testid="matrix-save">
        {matrix
          ? t('commitment.setup.save', { defaultValue: 'Save settings' })
          : t('commitment.setup.start', { defaultValue: 'Start the commitment matrix' })}
      </ReasonedButton>
    </section>
  );
}

interface TierRow {
  userId: string;
  deputyUserId: string;
  validTo: string;
}

function rowsOf(assignments: Assignment[]): Record<string, TierRow> {
  const rows: Record<string, TierRow> = {};
  for (const a of assignments) {
    // One person per project role is edited here. A further line for the same
    // role is kept as it is, see `untouchedAssignments`.
    if (rows[a.project_role]) continue;
    rows[a.project_role] = { userId: a.user_id, deputyUserId: a.deputy_user_id ?? '', validTo: a.valid_to ?? '' };
  }
  return rows;
}

/**
 * The assignments the form does not show: every line after the first of its
 * role. Saving replaces the whole list on the server, so these are sent back
 * unchanged rather than dropped.
 */
export function untouchedAssignments(assignments: readonly Assignment[]): AssignmentInput[] {
  const seen = new Set<string>();
  const rest: AssignmentInput[] = [];
  for (const a of assignments) {
    if (!seen.has(a.project_role)) {
      seen.add(a.project_role);
      continue;
    }
    rest.push({
      project_role: a.project_role,
      user_id: a.user_id,
      deputy_user_id: a.deputy_user_id,
      valid_from: a.valid_from,
      valid_to: a.valid_to,
    });
  }
  return rest;
}

export interface ApproverSetupProps {
  projectId: string;
  matrix: CommitmentMatrix;
  can: ProjectCan | null | undefined;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onSaved: () => void;
}

/** Who stands behind each tier, and the approval route each tier uses. */
export function ApproverSetup({ projectId, matrix, can, labels, personName, onSaved }: ApproverSetupProps) {
  const { t } = useTranslation();
  const assignmentsQ = useAssignments(projectId);
  const [rows, setRows] = useState<Record<string, TierRow> | null>(null);
  const [report, setReport] = useState<Record<string, RouteReport> | null>(null);
  const manageV = projectVerdict(can, 'manage');

  useEffect(() => {
    if (assignmentsQ.data && rows === null) setRows(rowsOf(assignmentsQ.data));
  }, [assignmentsQ.data, rows]);

  const routesQ = useQuery({
    queryKey: ['commitment-release', projectId, 'routes'],
    queryFn: () => listRoutes({ projectId, targetKind: 'commitment_release', includeInactive: false }),
    enabled: !manageV,
    staleTime: 30_000,
  });

  const existing = new Map((assignmentsQ.data ?? []).map((a) => [a.project_role, a]));
  const save = useMutation({
    mutationFn: async (force: boolean) => {
      // A row travels as it was filled. A deputy or an end date without an
      // approver is refused by the server by name, rather than dropped here.
      const list: AssignmentInput[] = Object.entries(rows ?? {})
        .filter(([, r]) => r.userId || r.deputyUserId || r.validTo)
        .map(([role, r]) => ({
          project_role: role,
          user_id: r.userId || null,
          deputy_user_id: r.deputyUserId || null,
          valid_from: existing.get(role)?.valid_from ?? null,
          valid_to: r.validTo || null,
        }));
      await putAssignments(projectId, [...list, ...untouchedAssignments(assignmentsQ.data ?? [])]);
      return generateRoutes(projectId, force);
    },
    onSuccess: (result) => {
      setReport(result.tiers);
      routesQ.refetch();
      onSaved();
    },
  });
  const pin = useMutation({
    mutationFn: (v: { tier: string; routeId: string }) => pinTierRoute(projectId, v.tier, v.routeId),
    onSuccess: onSaved,
  });
  const unpin = useMutation({
    mutationFn: (tier: string) => unpinTierRoute(projectId, tier),
    onSuccess: () => {
      routesQ.refetch();
      onSaved();
    },
  });

  const setRow = (role: string, patch: Partial<TierRow>) =>
    setRows((r) => ({ ...(r ?? {}), [role]: { userId: '', deputyUserId: '', validTo: '', ...(r ?? {})[role], ...patch } }));
  const anyEdited = !!report && Object.values(report).includes('edited');

  return (
    <section className="space-y-4 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="approver-setup">
      <div>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('commitment.setup.approvers_title', { defaultValue: 'Who approves at each tier' })}
        </h3>
        <p className="text-sm text-content-secondary">
          {t('commitment.setup.approvers_intro', {
            defaultValue: 'Name the person behind each tier. Saving builds the approval route of every tier, and a release request then goes to the right person.',
          })}
        </p>
      </div>

      {save.isError && <RefusalBox message={refusalText(t, save.error)} />}
      {pin.isError && <RefusalBox message={refusalText(t, pin.error)} />}
      {unpin.isError && <RefusalBox message={refusalText(t, unpin.error)} />}

      {assignmentsQ.isError ? (
        <ErrorState
          compact
          title={t('commitment.setup.assignments_failed', { defaultValue: 'The approvers could not be loaded' })}
          hint={getErrorMessage(assignmentsQ.error)}
          onRetry={() => assignmentsQ.refetch()}
        />
      ) : rows === null ? (
        // The pickers appear once the stored approvers are known: a choice made over an unloaded list would drop them.
        <p className="text-sm text-content-tertiary" data-testid="approvers-loading">
          {t('commitment.setup.assignments_loading', { defaultValue: 'Loading the approvers' })}
        </p>
      ) : (
        <ul className="space-y-2">
          {matrix.tiers.map((tier) => {
            const role = tier.approver.ref;
            const row = rows?.[role];
            const byPerson = tier.approver.kind === 'project_role';
            const routes = routesQ.data ?? [];
            return (
              <li key={tier.code} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="tier-row">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-content-primary">{codeName(labels, 'tier', tier.code, tier.name)}</span>
                  {tier.four_eyes && (
                    <Badge variant="neutral" size="sm">
                      {t('commitment.setup.four_eyes', { defaultValue: 'Four-eyes' })}
                    </Badge>
                  )}
                  {(!tier.route_id || tier.route_state === 'none') && (
                    <Badge variant="warning" size="sm">
                      {t('commitment.setup.no_route', { defaultValue: 'No approval route yet' })}
                    </Badge>
                  )}
                  {tier.route_state === 'pinned' && (
                    <Badge variant="neutral" size="sm">
                      {t('commitment.setup.route_state.pinned', { defaultValue: 'Route chosen by hand' })}
                    </Badge>
                  )}
                  {tier.route_state === 'changed' && (
                    <span data-testid="tier-route-changed">
                      <Badge variant="error" size="sm">
                        {t('commitment.setup.route_state.changed', { defaultValue: 'Route changed, confirm it' })}
                      </Badge>
                    </span>
                  )}
                  {report?.[tier.code] && (
                    <span className="text-xs text-content-tertiary" data-testid="tier-report">
                      {vocab(t, ROUTE_REPORT, report[tier.code])}
                    </span>
                  )}
                </div>
                {byPerson ? (
                  <div className="mt-2 grid gap-2 md:grid-cols-3">
                    <div>
                      <label htmlFor={`tier-user-${tier.code}`} className="mb-1 block text-xs text-content-secondary">
                        {t('commitment.grid.approver', { defaultValue: 'Approver' })}
                      </label>
                      <ProjectPeopleSelect
                        id={`tier-user-${tier.code}`}
                        projectId={projectId}
                        value={row?.userId ?? ''}
                        displayValue={personName(row?.userId) ?? undefined}
                        onChange={(userId) => setRow(role, { userId })}
                        placeholder={t('commitment.setup.pick_approver', { defaultValue: 'Choose a project member' })}
                      />
                    </div>
                    <div>
                      <label htmlFor={`tier-deputy-${tier.code}`} className="mb-1 block text-xs text-content-secondary">
                        {t('commitment.setup.deputy', { defaultValue: 'Deputy' })}
                      </label>
                      <ProjectPeopleSelect
                        id={`tier-deputy-${tier.code}`}
                        projectId={projectId}
                        value={row?.deputyUserId ?? ''}
                        displayValue={personName(row?.deputyUserId) ?? undefined}
                        onChange={(userId) => setRow(role, { deputyUserId: userId })}
                        placeholder={t('commitment.setup.pick_deputy', { defaultValue: 'Optional' })}
                      />
                    </div>
                    <div>
                      <label htmlFor={`tier-until-${tier.code}`} className="mb-1 block text-xs text-content-secondary">
                        {t('commitment.setup.valid_to', { defaultValue: 'Assigned until' })}
                      </label>
                      <input
                        id={`tier-until-${tier.code}`}
                        type="date"
                        className={FIELD_CLASS}
                        value={row?.validTo ?? ''}
                        onChange={(e) => setRow(role, { validTo: e.target.value })}
                      />
                    </div>
                  </div>
                ) : (
                  <p className="mt-1 text-sm text-content-secondary" data-testid="tier-by-role">
                    {tier.approver.kind === 'role'
                      ? t('commitment.setup.by_role', {
                          defaultValue: 'Decided by anyone with the role: {{role}}',
                          role: humanizeCode(tier.approver.ref),
                        })
                      : t('commitment.setup.by_user', {
                          defaultValue: 'Decided by: {{name}}',
                          name: personName(tier.approver.ref) ?? t('commitment.unknown_person', { defaultValue: 'Project member' }),
                        })}
                  </p>
                )}
                {!manageV && routes.length > 0 && (
                  <div className="mt-2 max-w-md">
                    <label htmlFor={`tier-route-${tier.code}`} className="mb-1 block text-xs text-content-secondary">
                      {t('commitment.setup.route', { defaultValue: 'Approval route in use' })}
                    </label>
                    <select
                      id={`tier-route-${tier.code}`}
                      className={FIELD_CLASS}
                      value={tier.route_id ?? ''}
                      disabled={pin.isPending || unpin.isPending}
                      onChange={(e) => e.target.value && pin.mutate({ tier: tier.code, routeId: e.target.value })}
                    >
                      <option value="" disabled={!!tier.route_id}>
                        {t('commitment.setup.route_none', { defaultValue: 'None yet' })}
                      </option>
                      {routes.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-content-tertiary">
                      {t('commitment.setup.route_hint', {
                        defaultValue:
                          'Choosing a route here confirms its steps as they are now. If somebody changes the steps later, requests of this tier are refused until a manager confirms the route again.',
                      })}
                    </p>
                    {tier.route_state === 'changed' && (
                      <p className="mt-1 text-xs text-semantic-error">
                        {t('commitment.setup.route_changed_hint', {
                          defaultValue:
                            'The steps of this route were changed after it was set up. Release requests of this tier are refused until you confirm the route or go back to the generated one.',
                        })}
                      </p>
                    )}
                    {(tier.route_state === 'pinned' || tier.route_state === 'changed') && (
                      <div className="mt-1 flex flex-wrap gap-2">
                        {tier.route_state === 'changed' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={pin.isPending && pin.variables?.tier === tier.code}
                            onClick={() => pin.mutate({ tier: tier.code, routeId: tier.route_id as string })}
                            data-testid="tier-route-confirm"
                          >
                            {t('commitment.setup.route_confirm', { defaultValue: 'Confirm the route as it is now' })}
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={unpin.isPending && unpin.variables === tier.code}
                          onClick={() => unpin.mutate(tier.code)}
                          data-testid="tier-route-reset"
                        >
                          {t('commitment.setup.route_reset', { defaultValue: 'Use the generated route again' })}
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {!manageV && routesQ.isLoading && (
        <p className="text-sm text-content-tertiary">
          {t('commitment.setup.routes_loading', { defaultValue: 'Loading the approval routes' })}
        </p>
      )}
      {!manageV && routesQ.isError && (
        <ErrorState
          compact
          title={t('commitment.setup.routes_failed', {
            defaultValue: 'The approval routes could not be loaded, so a route cannot be chosen or confirmed here',
          })}
          hint={getErrorMessage(routesQ.error)}
          onRetry={() => routesQ.refetch()}
        />
      )}

      <div className="flex flex-wrap items-start gap-3">
        <ReasonedButton
          variant="primary"
          verdict={manageV}
          loading={save.isPending}
          disabled={rows === null}
          onClick={() => save.mutate(false)}
          data-testid="approvers-save"
        >
          {t('commitment.setup.save_approvers', { defaultValue: 'Save approvers' })}
        </ReasonedButton>
        {anyEdited && !manageV && (
          <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate(true)} data-testid="approvers-force">
            {t('commitment.setup.replace_edited', { defaultValue: 'Replace the routes edited by hand' })}
          </Button>
        )}
      </div>
    </section>
  );
}

/** "Who approves?": the tier a type and an amount need under the project's schedule. */
export function TierCalculator({ matrix, labels }: { matrix: CommitmentMatrix; labels: LabelContext }) {
  const { t } = useTranslation();
  const [type, setType] = useState(matrix.commitment_types[0]?.code ?? '');
  const [amount, setAmount] = useState('');
  const [flags, setFlags] = useState<string[]>([]);
  const [result, setResult] = useState<EvaluateResult | null>(null);
  const wire = normalizeAmount(amount);
  const ready = !!type && wire !== null && isPositiveAmount(wire);

  const ask = useMutation({
    mutationFn: () =>
      evaluateSchedule({
        schedule_source: matrix.schedule_source,
        schedule_id: matrix.schedule_id,
        schedule_version: matrix.schedule_version,
        commitment_type: type,
        amount: wire as string,
        flags,
      }),
    onSuccess: setResult,
  });

  return (
    <section className="space-y-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="tier-calculator">
      <div>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('commitment.schedule.calculator', { defaultValue: 'Who approves?' })}
        </h3>
        <p className="text-sm text-content-secondary">
          {t('commitment.setup.calculator_intro', {
            defaultValue: 'Try a type and an amount to see which tier the schedule asks for. Nothing is saved.',
          })}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
        <Field id="calc-type" label={t('commitment.grid.type', { defaultValue: 'Type' })}>
          <select
            id="calc-type"
            className={FIELD_CLASS}
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setResult(null);
            }}
          >
            {matrix.commitment_types.map((ct) => (
              <option key={ct.code} value={ct.code}>
                {codeName(labels, 'type', ct.code, ct.name)}
              </option>
            ))}
          </select>
        </Field>
        <Field
          id="calc-amount"
          label={t('commitment.setup.calculator_amount', {
            defaultValue: 'Amount in {{currency}}',
            currency: matrix.schedule_currency,
          })}
        >
          <input
            id="calc-amount"
            inputMode="decimal"
            autoComplete="off"
            className={FIELD_CLASS}
            value={amount}
            onChange={(e) => {
              setAmount(e.target.value);
              setResult(null);
            }}
          />
        </Field>
        <Button variant="secondary" loading={ask.isPending} disabled={!ready} onClick={() => ask.mutate()} data-testid="calc-ask">
          {t('commitment.setup.calculator_ask', { defaultValue: 'Show the tier' })}
        </Button>
      </div>
      {matrix.novelty_flags.length > 0 && (
        <div className="flex flex-wrap gap-4">
          {matrix.novelty_flags.map((flag) => (
            <label key={flag.code} className="inline-flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={flags.includes(flag.code)}
                onChange={() => {
                  setFlags((f) => (f.includes(flag.code) ? f.filter((x) => x !== flag.code) : [...f, flag.code]));
                  setResult(null);
                }}
              />
              {codeName(labels, 'flag', flag.code, flag.name)}
            </label>
          ))}
        </div>
      )}
      {ask.isError && <RefusalBox message={refusalText(t, ask.error)} />}
      {result && !ask.isError && (
        <p role="status" className="rounded-md bg-surface-secondary p-3 text-sm text-content-primary" data-testid="calc-result">
          {result.escalate_outside
            ? t('commitment.release.escalate_outside', {
                defaultValue: 'Above every tier: consent outside the schedule is required',
              })
            : t('commitment.setup.calculator_result', {
                defaultValue: 'Required tier: {{tier}}',
                tier: codeName(labels, 'tier', result.required_tier, matrix.tiers.find((x) => x.code === result.required_tier)?.name),
              })}
        </p>
      )}
    </section>
  );
}

export function SetupPanel(props: ApproverSetupProps) {
  return (
    <div className="space-y-5" data-testid="setup-panel">
      <MatrixSettings projectId={props.projectId} matrix={props.matrix} can={props.can} labels={props.labels} onSaved={props.onSaved} />
      <ApproverSetup {...props} />
      <TierCalculator matrix={props.matrix} labels={props.labels} />
    </div>
  );
}
