// Design module (ERP side of the design editor link).
/**
 * Design → Acceptance: one screen to decide on a revision. The model with its changes sits on the left, the
 * estimate delta on the right; overrides and flagged positions come first. Accepting recomputes the estimate in
 * the same transaction on the server, so a failed accept leaves everything as it was. The schedule delta sits
 * under the estimate delta and is recomputed in that transaction too.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Check, FileSignature, FolderOpen, Lock, ShieldAlert, X } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from '@/shared/ui';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import { useModelViewerData } from '@/features/bim/useModelViewerData';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useProjectFromUrl } from './useProjectFromUrl';
import { useToastStore } from '@/stores/useToastStore';
import {
  acceptRevision,
  createRevisionChangeOrder,
  fetchAccess,
  fetchChangeOrderSettings,
  fetchImpact,
  fetchRevisionChangeOrder,
  fetchRevisions,
  rejectRevision,
  saveChangeOrderMode,
} from './api';
import { acceptChoice, canCreateLater, CHANGE_ORDER_MODES, type ChangeOrderMode, type ChangeOrderSettings } from './data/changeOrders';
import {
  ACCEPT_ONLY,
  attentionRows,
  baseOf,
  blockers,
  collapsedByNoMatch,
  isZero,
  movingRows,
  pending,
  qty,
  unitLabel,
  type Blocker,
  type Impact,
  type ImpactRow,
} from './data/acceptance';
import { isImported, overlayFor, upAxis, type RevisionView } from './data/revisions';
import { tr } from './BriefFields';
import { ProcurementPanel } from './ProcurementPanel';
import { SchedulePanel } from './SchedulePanel';
import { useQuietViewer, VIEWER_FRAME } from './useQuietViewer';
import { useIsoFrame } from './frameView';
import { moneyExact } from './money';
import { useRevisionCompare } from './useRevisionCompare';

export default function AcceptancePage() {
  const { t } = useTranslation();
  useProjectFromUrl();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  if (!projectId) {
    return (
      <EmptyState
        icon={<FolderOpen size={28} aria-hidden />}
        title={tr(t, 'design.brief.no_project')}
        description={tr(t, 'design.acceptance.no_project_hint')}
      />
    );
  }
  return <Acceptance key={projectId} projectId={projectId} />;
}

function Acceptance({ projectId }: { projectId: string }) {
  useQuietViewer();
  const iso = useIsoFrame();
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const revisionsQ = useQuery({ queryKey: ['design-revisions', projectId], queryFn: () => fetchRevisions(projectId) });
  const accessQ = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId) });
  const [chosen, setChosen] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  // The question is bound to the revision (and the base it builds on) it was asked about.
  const [asked, setAsked] = useState<{ kind: 'accept' | 'reject'; id: string; parent: string | null } | null>(null);
  const [failure, setFailure] = useState<{ number: number; message: string } | null>(null);
  const [focusRow, setFocusRow] = useState<ImpactRow | null>(null);
  // R9: the answer to "also draft a change order?" and the revision just accepted (its order is shown after).
  const [wantOrder, setWantOrder] = useState(false);
  const [lastAccepted, setLastAccepted] = useState<string | null>(null);
  const [params] = useSearchParams();
  const settingsQ = useQuery({ queryKey: ['design-co-settings', projectId], queryFn: () => fetchChangeOrderSettings(projectId) });
  const choice = acceptChoice(settingsQ.data);
  const confirmRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (asked) confirmRef.current?.querySelector('button')?.focus();
  }, [asked]);

  const revisions = useMemo(() => revisionsQ.data ?? [], [revisionsQ.data]);
  const waiting = useMemo(() => pending(revisions), [revisions]);
  // "Open acceptance" from the editor names the revision just built: show that one, not the oldest waiting
  const rev: RevisionView | null = waiting.find((r) => r.revision_id === (chosen ?? params.get('revision')))
    ?? waiting[0] ?? null;
  const base = rev ? baseOf(rev, revisions) : null;
  const latestPublished = revisions.find((r) => r.status === 'published') ?? null;
  const confirming = asked && rev && asked.id === rev.revision_id && asked.parent === rev.parent_revision_id ? asked.kind : null;
  // Fail closed: until the permission check has answered, nobody can decide.
  const why: Blocker[] = [
    ...(accessQ.data || !rev ? [] : (['access'] as Blocker[])),
    ...blockers(rev, accessQ.data?.can_accept, latestPublished, revisions),
  ];
  // Whatever was typed or asked belongs to the revision it was written for.
  const shownId = rev?.revision_id ?? null;
  useEffect(() => {
    setAsked(null);
    setComment('');
    setFocusRow(null);
    setWantOrder(false);
  }, [shownId]);

  const impactQ = useQuery({
    queryKey: ['design-impact', rev?.revision_id],
    queryFn: () => fetchImpact(rev!.revision_id),
    enabled: !!rev,
  });
  const { cmp, failed: compareFailed } = useRevisionCompare(base, rev);
  const overlay = useMemo(() => (cmp ? overlayFor(cmp, 'head') : null), [cmp]);
  const viewer = useModelViewerData(projectId, rev?.bim_model_id ?? null);
  const isolated = useMemo(() => {
    if (!focusRow) return null;
    const keys = new Set(focusRow.elements.added);
    const ids = viewer.elements.filter((e) => e.stable_id && keys.has(e.stable_id)).map((e) => e.id);
    return ids.length > 0 ? ids : null;
  }, [focusRow, viewer.elements]);

  const decide = useMutation({
    mutationFn: ({ kind, id }: { kind: 'accept' | 'reject'; id: string }) =>
      kind === 'accept'
        ? (choice === 'ask' ? acceptRevision(id, comment, wantOrder) : acceptRevision(id, comment))
        : rejectRevision(id, comment),
    onSuccess: (done, { kind }) => {
      if (kind === 'accept') setLastAccepted(done.revision_id);
      // the decided revision leaves the queue now, not after the list reloads: no second click on a decided one
      queryClient.setQueryData<RevisionView[]>(['design-revisions', projectId], (list) =>
        list?.map((r) => (r.revision_id === done.revision_id ? { ...r, status: done.status } : r)));
      setFailure(null);
      setAsked(null);
      setComment('');
      setFocusRow(null);
      addToast({ type: 'success', title: tr(t, kind === 'accept' ? 'design.acceptance.accepted' : 'design.acceptance.rejected', { number: done.number }) });
    },
    onError: (err, { id }) => {
      setAsked(null);
      setFailure({ number: revisions.find((r) => r.revision_id === id)?.number ?? 0, message: getErrorMessage(err) });
    },
    // Success or not, the server is the truth about what state the revision and the estimate are in.
    onSettled: () => {
      for (const key of ['design-revisions', 'design-overview', 'design-impact', 'design-schedule-impact', 'design-procurement-impact', 'design-access', 'bim-models']) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
      void queryClient.invalidateQueries({ queryKey: ['design-estimate'] });
      void queryClient.invalidateQueries({ queryKey: ['design-co'] });
    },
  });

  // Opened from a change order (?revision=), or right after an accept: what became of that revision.
  const linked = params.get('revision');
  const decidedLinked = linked && revisions.some((r) => r.revision_id === linked && r.status !== 'shared') ? linked : null;
  const noteId = lastAccepted ?? decidedLinked;
  const note = noteId ? (
    <ChangeOrderNote
      revisionId={noteId}
      number={revisions.find((r) => r.revision_id === noteId)?.number ?? 0}
      settings={settingsQ.data}
      locale={i18n.language}
    />
  ) : null;

  if (revisionsQ.isError) {
    return <ErrorState title={tr(t, 'design.revisions.load_failed')} hint={getErrorMessage(revisionsQ.error)} onRetry={() => revisionsQ.refetch()} />;
  }
  if (revisionsQ.isLoading) return <Skeleton className="h-48 w-full" />;
  if (!rev) {
    return (
      <div className="flex flex-col gap-3">
        {failure && <FailureNote failure={failure} />}
        {note}
        <EmptyState
        icon={<Check size={28} aria-hidden />}
        title={tr(t, 'design.acceptance.nothing')}
        description={tr(t, 'design.acceptance.nothing_hint')}
        />
        {/* nothing waiting is the usual state after an accept: schedule and take-off follow the accepted revision */}
        {latestPublished && (
          <>
            <SchedulePanel projectId={projectId} revisionId={latestPublished.revision_id}
              canManage={!!accessQ.data?.can_accept} locale={i18n.language} />
            <ProcurementPanel projectId={projectId} revisionId={latestPublished.revision_id}
              canManage={!!accessQ.data?.can_accept} />
          </>
        )}
      </div>
    );
  }

  const impact = impactQ.data;
  const busy = decide.isPending;
  const blocked = why.length > 0 || busy;
  const rejectBlocked = why.some((b) => !ACCEPT_ONLY.includes(b)) || busy;
  const needsComment = comment.trim().length === 0;
  const lock = accessQ.data?.lock;
  const currency = accessQ.data?.currency ?? '';
  const locale = i18n.language;

  return (
    <div className="flex flex-col gap-5 animate-fade-in">
      <PageHeader srTitle={tr(t, 'design.acceptance.title')} subtitle={tr(t, 'design.acceptance.subtitle')} />
      {note}

      {waiting.length > 1 && (
        <label className="flex items-center gap-2 text-sm">
          <span>{tr(t, 'design.acceptance.pick')}</span>
          <select
            value={rev.revision_id}
            onChange={(e) => { setChosen(e.target.value); setFocusRow(null); setFailure(null); setAsked(null); }}
            className="rounded border border-border-light bg-surface-primary px-2 py-1"
          >
            {waiting.map((r) => (
              <option key={r.revision_id} value={r.revision_id}>
                {tr(t, 'design.revisions.number', { number: r.number })} - {r.message || tr(t, 'design.revisions.no_message')}
              </option>
            ))}
          </select>
        </label>
      )}

      {lock && !lock.mine && (
        <div role="status" data-testid="lock-notice" className="flex items-center gap-2 rounded border border-border-light bg-surface-secondary px-3 py-2 text-sm">
          <Lock size={16} aria-hidden />
          {tr(t, 'design.acceptance.lock_held', { name: lock.held_by })}
        </div>
      )}

      <div className="grid gap-4 min-[1500px]:grid-cols-[minmax(0,1fr)_minmax(340px,460px)]">
        <div className="flex min-w-0 flex-col gap-3">
          <Card padding="none">
            <div className="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="model-bar">
              <span className="font-medium">
                {base
                  ? tr(t, 'design.revisions.comparing', { base: base.number, head: rev.number })
                  : tr(t, 'design.revisions.number', { number: rev.number })}
              </span>
              {!base && <Badge size="sm">{tr(t, 'design.acceptance.first')}</Badge>}
              {isImported(rev) && <Badge size="sm" variant="blue">{tr(t, 'design.revisions.imported')}</Badge>}
              {cmp ? (
                <>
                  <Badge variant="success" size="sm">{tr(t, 'design.revisions.added_n', { count: cmp.added.length })}</Badge>
                  <Badge variant="error" size="sm">{tr(t, 'design.revisions.removed_n', { count: cmp.removed.length })}</Badge>
                  <Badge variant="warning" size="sm">{tr(t, 'design.revisions.changed_n', { count: cmp.changed.length })}</Badge>
                </>
              ) : compareFailed ? (
                <span role="alert" className="text-sm text-semantic-error">{tr(t, 'design.revisions.compare_failed')}</span>
              ) : null}
              {rev.message && <span className="w-full truncate text-sm text-content-secondary">{rev.message}</span>}
            </div>
          </Card>
          <div ref={iso.box} className={`relative h-[360px] overflow-hidden rounded-lg border border-border-light sm:h-[460px] ${VIEWER_FRAME}`}>
            {rev.bim_model_id ? (
              <BIMViewer
                key={rev.bim_model_id}
                modelId={rev.bim_model_id}
                projectId={projectId}
                modelName={`#${rev.number}`}
                modelMetadata={viewer.activeModel?.metadata ?? null}
                elements={viewer.elements}
                geometryUrl={viewer.geometryUrl}
                isLoading={viewer.isLoadingElements}
                glbUpAxis={upAxis(rev)}
                diffChangeByStableId={overlay}
                isolatedIds={isolated}
                onSceneReady={iso.onSceneReady}
                onGeometryLoaded={isolated ? undefined : iso.onGeometryLoaded}
                className="h-full"
              />
            ) : (
              <EmptyState title={tr(t, 'design.revisions.no_model')} />
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          {/* Decision first when stacked so it is reachable without scrolling past the estimate; after the estimate on wide screens. */}
          <div className="min-[1500px]:order-last">
            <Card padding="none">
              <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.acceptance.decision')} />
              <div className="flex flex-col gap-3 px-4 pb-4">
                {why.map((b) => (
                  <p key={b} role="note" data-testid={`blocker-${b}`} className="flex items-start gap-2 text-sm text-content-secondary">
                    <ShieldAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
                    {tr(t, `design.acceptance.blocked.${b satisfies Blocker}`, { number: base?.number ?? 0 })}
                  </p>
                ))}
                {failure && <FailureNote failure={failure} />}
                {accessQ.isError && (
                  <div>
                    <Button variant="secondary" onClick={() => accessQ.refetch()}>{tr(t, 'design.acceptance.retry')}</Button>
                  </div>
                )}
                <label className="flex flex-col gap-1 text-sm">
                  {tr(t, 'design.acceptance.comment')}
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    maxLength={2000}
                    rows={3}
                    disabled={why.includes('role') || busy}
                    className="rounded border border-border-light bg-surface-primary px-2 py-1"
                  />
                </label>
                {confirming ? (
                  <div ref={confirmRef} className="flex flex-wrap items-center gap-2" data-testid="confirm-row">
                    <span className="text-sm">
                      {confirming === 'accept'
                        ? tr(t, 'design.acceptance.confirm_accept', { count: movingRows(impact?.rows ?? []).length })
                        : tr(t, 'design.acceptance.confirm_reject')}
                    </span>
                    {confirming === 'accept' && choice === 'ask' && (
                      <label className="flex w-full items-start gap-2 text-sm" data-testid="co-ask">
                        <input type="checkbox" className="mt-1" checked={wantOrder} disabled={busy}
                          onChange={(e) => setWantOrder(e.target.checked)} />
                        {tr(t, 'design.co.ask_checkbox')}
                      </label>
                    )}
                    {confirming === 'accept' && choice === 'always' && (
                      <p className="w-full text-sm text-content-secondary" data-testid="co-always">
                        {tr(t, 'design.co.always_note')}
                        {settingsQ.data && !settingsQ.data.can_create && <> {tr(t, 'design.co.no_permission')}</>}
                      </p>
                    )}
                    <Button variant={confirming === 'accept' ? 'primary' : 'danger'} loading={busy} disabled={confirming === 'accept' ? blocked : rejectBlocked}
                      onClick={() => decide.mutate({ kind: confirming, id: rev.revision_id })}>
                      {tr(t, confirming === 'accept' ? 'design.acceptance.confirm' : 'design.acceptance.confirm_reject_btn')}
                    </Button>
                    <Button variant="secondary" disabled={busy} onClick={() => setAsked(null)}>
                      {tr(t, 'design.cite.cancel')}
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="primary" icon={<Check size={16} />} disabled={blocked} onClick={() => { setFailure(null); setAsked({ kind: 'accept', id: rev.revision_id, parent: rev.parent_revision_id }); }}>
                      {tr(t, 'design.acceptance.accept')}
                    </Button>
                    <Button variant="secondary" icon={<X size={16} />} disabled={rejectBlocked || needsComment} onClick={() => { setFailure(null); setAsked({ kind: 'reject', id: rev.revision_id, parent: rev.parent_revision_id }); }}>
                      {tr(t, 'design.acceptance.reject')}
                    </Button>
                    {!rejectBlocked && needsComment && (
                      <span className="self-center text-xs text-content-tertiary">{tr(t, 'design.acceptance.reject_needs_comment')}</span>
                    )}
                  </div>
                )}
                {settingsQ.data?.can_change && <ModeSelect projectId={projectId} settings={settingsQ.data} />}
              </div>
            </Card>
          </div>

          <ImpactPanel
            impact={impact}
            loading={impactQ.isLoading}
            error={impactQ.isError ? getErrorMessage(impactQ.error) : null}
            onRetry={() => impactQ.refetch()}
            currency={currency}
            locale={locale}
            focusRow={focusRow}
            onFocus={(row) => setFocusRow((cur) => (cur?.rule === row.rule ? null : row))}
          />
          <SchedulePanel
            projectId={projectId}
            revisionId={rev.revision_id}
            canManage={!!accessQ.data?.can_accept}
            locale={locale}
            needsEstimate={impact ? !impact.estimate : undefined}
          />
          <ProcurementPanel
            projectId={projectId}
            revisionId={rev.revision_id}
            canManage={!!accessQ.data?.can_accept}
            needsAccepted={!latestPublished}
          />

        </div>
      </div>
    </div>
  );
}

function ModeSelect({ projectId, settings }: { projectId: string; settings: ChangeOrderSettings }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (mode: ChangeOrderMode) => saveChangeOrderMode(projectId, mode),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['design-co-settings', projectId] }),
  });
  return (
    <label className="flex flex-col gap-1 border-t border-border-light pt-3 text-sm">
      {tr(t, 'design.co.mode_label')}
      <select value={settings.mode} disabled={save.isPending} data-testid="co-mode"
        onChange={(e) => save.mutate(e.target.value as ChangeOrderMode)}
        className="rounded border border-border-light bg-surface-primary px-2 py-1">
        {CHANGE_ORDER_MODES.map((m) => <option key={m} value={m}>{tr(t, `design.co.mode.${m}`)}</option>)}
      </select>
      {save.isError && <span role="alert" className="text-semantic-error">{getErrorMessage(save.error)}</span>}
    </label>
  );
}

/** "Draft change order CO-... created -> open", or why there is none and a way to make it. Never approves. */
function ChangeOrderNote({ revisionId, number, settings }: {
  revisionId: string; number: number; settings: ChangeOrderSettings | undefined; locale: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ['design-co', revisionId], queryFn: () => fetchRevisionChangeOrder(revisionId) });
  const create = useMutation({
    mutationFn: () => createRevisionChangeOrder(revisionId),
    onSuccess: (view) => queryClient.setQueryData(['design-co', revisionId], view),
  });
  const view = q.data;
  if (!view) return null;
  const co = view.change_order;
  const status = tr(t, `design.revisions.status.${view.revision_status}`);
  return (
    <div role="status" data-testid="co-note" className="flex flex-col gap-2 rounded border border-border-light bg-surface-secondary px-3 py-2 text-sm">
      <span className="flex items-center gap-2 font-medium">
        <FileSignature size={16} aria-hidden />
        {tr(t, 'design.co.decided', { number: number || view.number, status })}
      </span>
      {view.state === 'created' && co && (
        <>
          <span>
            {tr(t, 'design.co.created', { code: co.code })}{' '}
            {tr(t, 'design.co.amount', { amount: moneyExact(co.cost_impact, co.currency) })}
          </span>
          {co.unpriced_positions > 0 && (
            <span className="text-content-secondary" data-testid="co-unpriced">{tr(t, 'design.co.unpriced_n', { count: co.unpriced_positions })}</span>
          )}
          <span className="flex flex-wrap items-center gap-3">
            <Link className="text-oe-blue-text underline" to={co.url} data-testid="co-open">{tr(t, 'design.co.open')}</Link>
            <span className="text-xs text-content-tertiary">{tr(t, 'design.co.approve_hint')}</span>
          </span>
        </>
      )}
      {view.state === 'declined' && <span>{tr(t, 'design.co.declined')}</span>}
      {view.state === 'deleted' && <span>{tr(t, 'design.co.deleted')}</span>}
      {view.state === 'none' && view.revision_status !== 'rejected' && <span>{tr(t, 'design.co.unavailable')}</span>}
      {canCreateLater(view, settings) && (
        <div>
          <Button variant="secondary" loading={create.isPending} onClick={() => create.mutate()} data-testid="co-create">
            {tr(t, 'design.co.create_now')}
          </Button>
        </div>
      )}
      {create.isError && (
        <span role="alert" className="text-semantic-error">{tr(t, 'design.co.failed')} {getErrorMessage(create.error)}</span>
      )}
    </div>
  );
}

function FailureNote({ failure }: { failure: { number: number; message: string } }) {
  const { t } = useTranslation();
  return (
    <p role="alert" data-testid="decision-failed" className="rounded border border-semantic-error px-3 py-2 text-sm">
      {failure.number > 0 && <strong>{tr(t, 'design.acceptance.failed_for', { number: failure.number })} </strong>}
      {tr(t, 'design.acceptance.failed')} {failure.message}
    </p>
  );
}

function Delta({ value, locale, unit, plain, warn }: { value: string; locale: string; unit?: string; plain?: boolean; warn?: boolean }) {
  const n = Number(value);
  const tone = warn ? 'text-semantic-warning' : n > 0 ? 'text-semantic-error' : n < 0 ? 'text-semantic-success' : 'text-content-tertiary';
  if (!plain) return <span className={`whitespace-nowrap ${tone}`}>{moneyExact(value, unit, true)}</span>;
  return <span className={tone}>{n > 0 ? '+' : ''}{qty(value, locale)}{unit ? ` ${unit}` : ''}</span>;
}

function ImpactPanel(props: {
  impact: Impact | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  currency: string;
  locale: string;
  focusRow: ImpactRow | null;
  onFocus: (row: ImpactRow) => void;
}) {
  const { t } = useTranslation();
  const { impact, currency, locale } = props;
  if (props.error) {
    return <ErrorState title={tr(t, 'design.acceptance.impact_failed')} hint={props.error} onRetry={props.onRetry} />;
  }
  if (props.loading || !impact) return <Skeleton className="h-64 w-full" />;
  if (!impact.estimate) {
    return (
      <Card padding="none">
        <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.acceptance.estimate')} />
        <p className="px-4 pb-4 text-sm text-content-secondary" data-testid="no-estimate">{tr(t, 'design.acceptance.no_estimate')}</p>
      </Card>
    );
  }
  const attention = attentionRows(impact.rows);
  const rest = movingRows(impact.rows).filter((r) => !attention.includes(r));
  const same = impact.rows.length - attention.length - rest.length;
  const totals = impact.totals;
  const collapsed = collapsedByNoMatch(impact);
  // Nothing priced on either side: zero euros would read as a result, the unpriced note below says why.
  const unpricedAll = !!totals && totals.unpriced_positions > 0 && Number(totals.current) === 0 && Number(totals.after) === 0;
  return (
    <Card padding="none">
      <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.acceptance.estimate')} />
      <p className="px-4 pb-3 text-sm">
        <Link className="text-oe-blue-text underline" to="/design/estimate" data-testid="estimate-link">{tr(t, 'design.acceptance.see_estimate')}</Link>
      </p>
      {totals && (
        <dl className="grid grid-cols-3 gap-2 px-4 pb-3 text-sm" data-testid="totals">
          <div><dt className="text-content-tertiary">{tr(t, 'design.acceptance.current')}</dt><dd>{unpricedAll ? '–' : moneyExact(totals.current, currency)}</dd></div>
          <div><dt className="text-content-tertiary">{tr(t, 'design.acceptance.after')}</dt><dd>{unpricedAll ? '–' : moneyExact(totals.after, currency)}</dd></div>
          <div><dt className="text-content-tertiary">{tr(t, 'design.acceptance.delta')}</dt><dd className="font-medium">{unpricedAll ? '–' : <Delta value={totals.delta} locale={locale} unit={currency} warn={collapsed} />}</dd></div>
        </dl>
      )}
      {collapsed && (
        <p role="alert" data-testid="zero-warning" className="mx-4 mb-3 rounded border border-semantic-warning px-3 py-2 text-sm">
          {tr(t, 'design.acceptance.zero_warning')}
        </p>
      )}
      {totals && totals.unpriced_positions > 0 && (
        <p className="px-4 pb-2 text-xs text-content-secondary" data-testid="unpriced">
          {tr(t, 'design.acceptance.unpriced_left_out', { count: totals.unpriced_positions })}{' '}
          <Link className="text-oe-blue-text underline" to="/design/estimate" data-testid="unpriced-link">{tr(t, 'design.acceptance.see_estimate')}</Link>
        </p>
      )}
      {attention.length > 0 && (
        <RowGroup title={tr(t, 'design.acceptance.attention', { count: attention.length })} rows={attention} {...props} testid="attention-rows" />
      )}
      {rest.length > 0 && (
        <RowGroup title={tr(t, 'design.acceptance.moving', { count: rest.length })} rows={rest} {...props} testid="moving-rows" />
      )}
      {attention.length + rest.length === 0 && (
        <p className="px-4 pb-3 text-sm text-content-secondary" data-testid="no-movement">{tr(t, 'design.acceptance.no_movement')}</p>
      )}
      {same > 0 && <p className="px-4 pb-3 text-xs text-content-tertiary">{tr(t, 'design.acceptance.same_n', { count: same })}</p>}
    </Card>
  );
}

function RowGroup({ title, rows, locale, currency, focusRow, onFocus, testid }: {
  title: string; rows: ImpactRow[]; locale: string; currency: string; focusRow: ImpactRow | null;
  onFocus: (r: ImpactRow) => void; testid: string;
}) {
  const { t } = useTranslation();
  return (
    <section className="border-t border-border-light" data-testid={testid}>
      <h3 className="px-4 py-2 text-sm font-medium">{title}</h3>
      <ul className="max-h-[360px] overflow-auto">
        {rows.map((r) => {
          const active = focusRow?.rule === r.rule;
          return (
            <li key={r.rule} className={active ? 'bg-surface-secondary' : ''}>
              <button type="button" aria-pressed={active} onClick={() => onFocus(r)}
                className="flex w-full flex-col gap-1 px-4 py-2 text-start" data-testid={`row-${r.rule}`}>
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{r.label}</span>
                  <span className="text-xs text-content-tertiary">{r.cost_group}</span>
                  {r.new_position && <Badge size="sm" variant="blue">{tr(t, 'design.acceptance.new_position')}</Badge>}
                  {r.override && <Badge size="sm" variant="warning">{tr(t, 'design.acceptance.override')}</Badge>}
                  {r.flags.filter((f) => f !== 'override').map((f) => <Badge key={f} size="sm" variant="error">{tr(t, `design.acceptance.flag.${f}`, { defaultValue: f })}</Badge>)}
                </span>
                <span className="text-sm text-content-secondary">
                  {qty(r.current_quantity, locale)} {'->'} {qty(r.new_quantity, locale)} {unitLabel(r.unit, locale)}
                  {isZero(r.quantity_delta) ? '' : ' ('}
                  {isZero(r.quantity_delta) ? null : <Delta value={r.quantity_delta} locale={locale} plain />}
                  {isZero(r.quantity_delta) ? '' : ')'}
                  {/* no rate: the badge says why; a money delta here would be a fabricated 0 */}
                  {Number(r.unit_rate) > 0 && <>{' - '}<Delta value={r.cost_delta} locale={locale} unit={currency} warn={r.flags.includes('no_match')} /></>}
                </span>
                {r.override && r.override_quantity !== null && (
                  <span className="text-xs text-content-secondary">
                    {tr(t, 'design.acceptance.override_kept', { kept: qty(r.override_quantity, locale), model: qty(r.model_quantity_new, locale), unit: unitLabel(r.unit, locale) })}
                  </span>
                )}
                {(r.elements.added_count > 0 || r.elements.removed_count > 0) && (
                  <span className="text-xs text-content-tertiary">
                    {tr(t, 'design.acceptance.elements', { added: r.elements.added_count, removed: r.elements.removed_count })}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
