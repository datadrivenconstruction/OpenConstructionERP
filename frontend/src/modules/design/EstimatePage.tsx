// Design module (ERP side of the design editor link).
/**
 * Design → Estimate: the project estimate computed from the accepted revision, shown as a range.
 * Positions are grouped by DIN 276 cost group; every number says where it comes from (model, assumption with
 * formula and source, manual override with the model value beside it). Nothing unpriced is shown with a guessed
 * rate, and a range check that cannot be made is never shown as passed.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Calculator, FolderOpen, ShieldAlert } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchAccess, fetchBrief, fetchEstimate, fetchEstimateRules, fetchRevisions, installStarterRules, runEstimate, saveOverrideReason } from './api';
import { PositionLinks } from './PositionLinks';
import { qty, unitLabel } from './data/acceptance';
import { moneyExact, moneyWhole } from './money';
import { getAt } from './data/briefModel';
import {
  benchmarkSources,
  errorKind,
  groupByCostGroup,
  isUnpriced,
  overrideDelta,
  rangeVerdict,
  safeUrl,
  totalPlacement,
  type CostGroup,
  type CostItemSource,
  type Estimate,
  type EstimatePosition,
  type UnusedSource,
} from './data/estimate';
import { hasText, tr } from './BriefFields';
import { CostPicker } from './CostPicker';

export default function EstimatePage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  if (!projectId) {
    return (
      <EmptyState
        icon={<FolderOpen size={28} aria-hidden />}
        title={tr(t, 'design.brief.no_project')}
        description={tr(t, 'design.estimate.no_project_hint')}
      />
    );
  }
  return <EstimateScreen key={projectId} projectId={projectId} />;
}

/** A failed request in words a person can act on: the status first, the server's message as the hint. */
function failure(t: ReturnType<typeof useTranslation>['t'], err: unknown, fallbackKey: string) {
  const kind = errorKind(err);
  return { title: tr(t, kind === 'other' ? fallbackKey : `design.estimate.error.${kind}`), hint: getErrorMessage(err) };
}

function EstimateScreen({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const estimateQ = useQuery({ queryKey: ['design-estimate', projectId], queryFn: () => fetchEstimate(projectId) });
  const revisionsQ = useQuery({ queryKey: ['design-revisions', projectId], queryFn: () => fetchRevisions(projectId) });
  const accessQ = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId) });
  const empty = estimateQ.data?.estimate === false;
  const rulesQ = useQuery({ queryKey: ['design-estimate-rules', projectId], queryFn: () => fetchEstimateRules(projectId), enabled: empty });
  const briefQ = useQuery({ queryKey: ['design-brief', projectId], queryFn: () => fetchBrief(projectId), enabled: empty });
  // Fail closed: until the permission check has answered, nobody can change anything.
  const canManage = accessQ.data?.can_accept === true;
  const locale = i18n.language;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['design-estimate'] });
    void queryClient.invalidateQueries({ queryKey: ['design-estimate-rules'] });
  };
  const run = useMutation({ mutationFn: () => runEstimate(projectId), onSettled: refresh });
  const starter = useMutation({ mutationFn: (country: string) => installStarterRules(projectId, country), onSettled: refresh });

  if (estimateQ.isError) {
    const f = failure(t, estimateQ.error, 'design.estimate.load_failed');
    return <ErrorState title={f.title} hint={f.hint} onRetry={() => estimateQ.refetch()} />;
  }
  if (estimateQ.isLoading || !estimateQ.data) return <Skeleton className="m-6 h-48" data-testid="estimate-loading" />;

  const data = estimateQ.data;
  const revisions = revisionsQ.data ?? [];
  const accepted = revisions.filter((r) => r.status === 'published');

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-6">
      <h1 className="text-xl font-semibold text-content-primary">{tr(t, 'design.estimate.title')}</h1>
      <PageHeader subtitle={tr(t, 'design.estimate.subtitle')} />
      {accessQ.isSuccess && !canManage && (
        <p role="note" data-testid="read-only" className="flex items-start gap-2 text-sm text-content-secondary">
          <ShieldAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
          {tr(t, 'design.estimate.read_only')}
        </p>
      )}
      {data.estimate ? (
        <>
          <Header est={data} canManage={canManage} accessReady={accessQ.isSuccess} run={run} revisions={revisions} />
          <Totals est={data} locale={locale} currency={data.range.currency ?? accessQ.data?.currency ?? ''} />
          <Groups est={data} projectId={projectId} canManage={canManage} locale={locale} currency={accessQ.data?.currency ?? data.range.currency ?? ''} regions={data.cost_regions ?? []} />
          <Benchmarks est={data} />
        </>
      ) : (
        <NoEstimate
          acceptedCount={accepted.length}
          revisionsFailed={revisionsQ.isError}
          rulesCount={rulesQ.data?.length ?? null}
          rulesLoading={rulesQ.isLoading}
          rulesError={rulesQ.isError ? failure(t, rulesQ.error, 'design.estimate.load_failed') : null}
          defaultCountry={String(getAt(briefQ.data, '/country') ?? '')}
          canManage={canManage}
          accessReady={accessQ.isSuccess}
          run={run}
          starter={starter}
        />
      )}
    </div>
  );
}

type Mut<V> = { mutate: (v: V) => void; isPending: boolean; isError: boolean; error: unknown; isSuccess: boolean };

function NoEstimate(props: {
  acceptedCount: number; revisionsFailed: boolean; rulesCount: number | null; rulesLoading: boolean;
  rulesError: { title: string; hint: string } | null; defaultCountry: string; canManage: boolean; accessReady: boolean;
  run: Mut<void>; starter: Mut<string>;
}) {
  const { t } = useTranslation();
  const [country, setCountry] = useState<string | null>(null);
  const shown = country ?? props.defaultCountry;
  const noRules = props.rulesCount === 0;
  const blocked = !props.canManage;
  return (
    <div className="flex flex-col gap-3" data-testid="no-estimate">
      {props.acceptedCount === 0 && !props.revisionsFailed && (
        <EmptyState
          icon={<Calculator size={28} aria-hidden />}
          title={tr(t, 'design.estimate.no_revision')}
          description={tr(t, 'design.estimate.no_revision_hint')}
        >
          <Link className="text-oe-blue-text underline" to="/design/revisions">{tr(t, 'design.estimate.open_revisions')}</Link>
        </EmptyState>
      )}
      {props.rulesError && <ErrorState title={props.rulesError.title} hint={props.rulesError.hint} />}
      {props.rulesLoading && <Skeleton className="h-24 w-full" />}
      {noRules && (
        <Card padding="none">
          <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.estimate.no_rules')} subtitle={tr(t, 'design.estimate.no_rules_hint')} />
          <div className="flex flex-wrap items-end gap-3 px-4 pb-4">
            <label className="flex flex-col gap-1 text-sm">
              {tr(t, 'design.estimate.country')}
              <input
                value={shown}
                maxLength={2}
                onChange={(e) => setCountry(e.target.value.toUpperCase())}
                className="w-20 rounded border border-border-light bg-surface-primary px-2 py-1 uppercase"
              />
            </label>
            <Button variant="primary" disabled={blocked || !/^[A-Za-z]{2}$/.test(shown) || props.starter.isPending}
              loading={props.starter.isPending} onClick={() => props.starter.mutate(shown)}>
              {tr(t, 'design.estimate.install_starter')}
            </Button>
          </div>
          {blocked && props.accessReady && <p className="px-4 pb-3 text-xs text-content-secondary">{tr(t, 'design.estimate.manager_only')}</p>}
          {props.starter.isError && <MutationError err={props.starter.error} fallback="design.estimate.starter_failed" />}
        </Card>
      )}
      {props.rulesCount !== null && props.rulesCount > 0 && (
        <Card padding="none">
          <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.estimate.not_run')} subtitle={tr(t, 'design.estimate.not_run_hint', { count: props.rulesCount })} />
          <div className="px-4 pb-4">
            <RunButton run={props.run} disabled={blocked || props.acceptedCount === 0} />
          </div>
          {props.run.isError && <MutationError err={props.run.error} fallback="design.estimate.run_failed" />}
        </Card>
      )}
      {noRules && props.starter.isSuccess && <p role="status" className="text-sm">{tr(t, 'design.estimate.starter_installed')}</p>}
    </div>
  );
}

function RunButton({ run, disabled }: { run: Mut<void>; disabled: boolean }) {
  const { t } = useTranslation();
  return (
    <Button variant="primary" icon={<Calculator size={16} />} disabled={disabled || run.isPending} loading={run.isPending} onClick={() => run.mutate()}>
      {tr(t, 'design.estimate.run')}
    </Button>
  );
}

function MutationError({ err, fallback }: { err: unknown; fallback: string }) {
  const { t } = useTranslation();
  const f = failure(t, err, fallback);
  return (
    <p role="alert" data-testid="mutation-error" className="mx-4 mb-3 rounded border border-semantic-error px-3 py-2 text-sm">
      <strong>{f.title}</strong> {f.hint}
    </p>
  );
}

function Header({ est, canManage, accessReady, run, revisions }: {
  est: Estimate; canManage: boolean; accessReady: boolean; run: Mut<void>;
  revisions: { revision_id: string; number: number; status: string }[];
}) {
  const { t } = useTranslation();
  const rev = revisions.find((r) => r.revision_id === est.revision_id) ?? null;
  return (
    <Card padding="none">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="estimate-header">
        <span className="font-medium">{tr(t, 'design.estimate.computed_on')}</span>
        {est.revision_id ? (
          <Link className="text-oe-blue-text underline" to={`/design/revisions?rev=${encodeURIComponent(est.revision_id)}`} data-testid="revision-link">
            {rev ? tr(t, 'design.revisions.number', { number: rev.number }) : tr(t, 'design.estimate.revision_unknown')}
          </Link>
        ) : (
          <span className="text-content-secondary">{tr(t, 'design.estimate.revision_none')}</span>
        )}
        {rev && <Badge size="sm">{tr(t, `design.revisions.status.${rev.status}`, { defaultValue: rev.status })}</Badge>}
        {est.depth_level && <Badge size="sm">{est.depth_level}</Badge>}
        <Badge size="sm">{est.country}</Badge>
        <span className="ms-auto">
          <RunButton run={run} disabled={!canManage || !accessReady} />
        </span>
      </div>
      {run.isError && <MutationError err={run.error} fallback="design.estimate.run_failed" />}
    </Card>
  );
}

function Totals({ est, locale, currency }: { est: Estimate; locale: string; currency: string }) {
  const { t } = useTranslation();
  const r = est.range;
  const verdict = rangeVerdict(est);
  const placement = totalPlacement(est);
  const priced = Number(est.total) !== 0;
  return (
    <Card padding="none">
      <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.estimate.range')}
        subtitle={tr(t, 'design.estimate.range_basis', { area: Number(r.basis_living_area_m2).toLocaleString(locale, { maximumFractionDigits: 1 }) })} />
      <dl className="grid grid-cols-3 gap-2 px-4 pb-3 text-sm" data-testid="range-totals">
        {(['low', 'mid', 'high'] as const).map((k) => (
          <div key={k}>
            <dt className="text-content-tertiary">{tr(t, `design.estimate.${k}`)}</dt>
            <dd className={`break-words tabular-nums ${k === 'mid' ? 'text-xl font-semibold text-content-primary' : 'text-base text-content-secondary'}`}>{moneyWhole(r.total[k], currency)}</dd>
          </div>
        ))}
      </dl>
      {!r.total.complete && (
        <p role="note" data-testid="range-incomplete" className="px-4 pb-2 text-xs text-content-secondary">
          {tr(t, 'design.estimate.range_incomplete', { groups: r.missing_groups.join(', ') })}
        </p>
      )}
      <p className="px-4 pb-2 text-xs text-content-secondary">{tr(t, 'design.estimate.range_scope', { excluded: r.not_in_range.join(', ') })}</p>
      <div className="flex flex-col gap-2 border-t border-border-light px-4 py-3 text-sm">
        <div data-testid="priced-total">
          <span className="text-content-tertiary">{tr(t, 'design.estimate.priced_total')} </span>
          {priced ? <strong className="tabular-nums">{moneyWhole(est.total, currency)}</strong> : <span>{tr(t, 'design.estimate.nothing_priced')}</span>}
        </div>
        {verdict === 'unknown' && (
          <p role="note" data-testid="check-unknown" className="rounded border border-semantic-warning px-3 py-2">
            <strong>{tr(t, 'design.estimate.not_checkable')}</strong>{' '}
            {noteText(t, est)}
          </p>
        )}
        {verdict === 'inside' && (
          <p role="status" data-testid="check-inside" className="rounded border border-semantic-success px-3 py-2">
            {tr(t, 'design.estimate.inside')}
          </p>
        )}
        {verdict === 'outside' && (
          <p role="alert" data-testid="check-outside" className="rounded border border-semantic-warning px-3 py-2">
            {tr(t, placement === 'below' ? 'design.estimate.below' : placement === 'above' ? 'design.estimate.above' : 'design.estimate.outside')}
          </p>
        )}
        {est.unpriced_positions.length > 0 && (
          <p className="text-xs text-content-secondary" data-testid="unpriced-count">
            {tr(t, 'design.estimate.unpriced_n', { count: est.unpriced_positions.length })}
            {(est.cost_regions ?? []).length === 0 && (
              <> <Link to="/costs" className="text-oe-blue-text underline" data-testid="no-cost-base">{tr(t, 'design.estimate.cost_pick_none')}</Link></>
            )}
          </p>
        )}
      </div>
    </Card>
  );
}

type T = ReturnType<typeof useTranslation>['t'];

/** The range-check note in the page language, from its stable code; the server's English text is the fallback. */
function noteText(t: T, est: Estimate): string {
  const key = est.inside_range_note_code ? `design.estimate.note.${est.inside_range_note_code}` : '';
  if (key && hasText(t, key)) return tr(t, key);
  return est.inside_range_note ?? tr(t, 'design.estimate.not_checkable_hint');
}

/** Why a position has no rate: the page-language text for its code (rule-specific first), else the server's text. */
function missingText(t: T, p: EstimatePosition): string {
  const code = p.provenance.missing_code;
  if (code) {
    for (const key of [`design.estimate.missing.${code}.${p.rule}`, `design.estimate.missing.${code}`]) {
      if (hasText(t, key)) return tr(t, key);
    }
  }
  return p.provenance.missing ?? '';
}

function Groups({ est, projectId, canManage, locale, currency, regions }: {
  est: Estimate; projectId: string; canManage: boolean; locale: string; currency: string; regions: string[];
}) {
  const { t } = useTranslation();
  const groups = groupByCostGroup(est.positions);
  return (
    <Card padding="none">
      <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.estimate.positions')} subtitle={tr(t, 'design.estimate.positions_hint')} />
      {groups.length === 0 && <p className="px-4 pb-4 text-sm text-content-secondary">{tr(t, 'design.estimate.no_positions')}</p>}
      {groups.map((g) => (
        <GroupBlock key={g.code} group={g} projectId={projectId} canManage={canManage} locale={locale} currency={currency} regions={regions} />
      ))}
    </Card>
  );
}

function GroupBlock({ group, projectId, canManage, locale, currency, regions }: {
  group: CostGroup; projectId: string; canManage: boolean; locale: string; currency: string; regions: string[];
}) {
  const { t } = useTranslation();
  return (
    <section className="border-t border-border-light" data-testid={`group-${group.code}`}>
      <h3 className="flex flex-wrap items-baseline gap-2 px-4 py-2 text-sm font-medium">
        <span>{tr(t, 'design.estimate.cost_group', { code: group.code })}</span>
        <span className="ms-auto font-normal text-content-secondary" data-testid={`subtotal-${group.code}`}>
          {group.subtotal === null ? tr(t, 'design.estimate.unpriced') : moneyWhole(group.subtotal, currency)}
        </span>
      </h3>
      <ul>
        {group.positions.map((p) => (
          <PositionRow key={p.position_id} p={p} projectId={projectId} canManage={canManage} locale={locale} currency={currency} regions={regions} />
        ))}
      </ul>
    </section>
  );
}

function PositionRow({ p, projectId, canManage, locale, currency, regions }: {
  p: EstimatePosition; projectId: string; canManage: boolean; locale: string; currency: string; regions: string[];
}) {
  const { t } = useTranslation();
  const unit = unitLabel(p.unit, locale);
  const unpriced = isUnpriced(p);
  const flags = p.flags.filter((f) => f !== 'override' && f !== 'unpriced' && f !== 'cost_auto');
  const delta = overrideDelta(p);
  return (
    <li className="flex flex-col gap-1 border-t border-border-light px-4 py-3" data-testid={`pos-${p.rule}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{p.description}</span>
        <span className="text-xs text-content-tertiary">{p.ordinal}</span>
        <Badge size="sm" variant={p.kind === 'derived' ? 'blue' : undefined}>{tr(t, `design.estimate.source.${p.kind}`)}</Badge>
        {p.override && <Badge size="sm" variant="warning">{tr(t, 'design.estimate.override')}</Badge>}
        {unpriced && <Badge size="sm" variant="error">{tr(t, 'design.estimate.flag.unpriced')}</Badge>}
        {flags.map((f) => <Badge key={f} size="sm" variant="error">{tr(t, `design.estimate.flag.${f}`, { defaultValue: f })}</Badge>)}
      </div>
      <div className="flex flex-wrap gap-x-4 text-sm text-content-secondary">
        <span data-testid={`qty-${p.rule}`}>{qty(p.quantity, locale)} {unit}</span>
        <span>{unpriced ? '-' : `${moneyExact(p.unit_rate, currency)}/${unit}`}</span>
        <span className="ms-auto text-content-primary">{unpriced ? tr(t, 'design.estimate.unpriced') : moneyWhole(p.total, currency)}</span>
      </div>
      {p.override && p.model_quantity !== null && (
        <p className="text-xs text-content-secondary" data-testid={`override-${p.rule}`}>
          {tr(t, 'design.estimate.override_kept', { kept: qty(p.quantity, locale), model: qty(p.model_quantity, locale), unit })}
          {delta !== null && Number(delta) !== 0 && <> ({Number(delta) > 0 ? '+' : ''}{qty(delta, locale)} {unit})</>}
        </p>
      )}
      {p.provenance.cost_item && <CostSource c={p.provenance.cost_item} rule={p.rule} />}
      {canManage && p.kind !== 'manual' && (
        <CostPicker projectId={projectId} positionId={p.position_id} rule={p.rule} query={p.description} unit={p.unit} regions={regions} />
      )}
      {p.override && <ReasonEditor key={p.override_reason ?? ''} p={p} projectId={projectId} canManage={canManage} />}
      {p.provenance.missing && <p className="text-xs text-content-secondary" data-testid={`missing-${p.rule}`}>{missingText(t, p)}</p>}
      <Provenance p={p} />
      {p.kind === 'model' && p.elements > 0 && <PositionLinks projectId={projectId} positionId={p.position_id} rule={p.rule} />}
    </li>
  );
}

function CostSource({ c, rule }: { c: CostItemSource; rule: string }) {
  const { t } = useTranslation();
  const meta = [c.database, c.version, c.price_date].filter(Boolean).join(' / ');
  return (
    <p className="text-xs text-content-secondary" data-testid={`cost-source-${rule}`}>
      {tr(t, 'design.estimate.cost_source')} {c.code} ({meta}), {tr(t, c.auto ? 'design.estimate.cost_source_auto' : 'design.estimate.cost_source_picked')}
      {c.assembly_id && <> {tr(t, 'design.estimate.cost_source_assembly', { name: c.name ?? '' })}</>}
      {c.via && <> {tr(t, `design.estimate.cost_source_match_${c.via.decision}`, { percent: Math.round(Number(c.via.confidence) * 100) })}</>}
    </p>
  );
}

function ReasonEditor({ p, projectId, canManage }: { p: EstimatePosition; projectId: string; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [text, setText] = useState(p.override_reason ?? '');
  const save = useMutation({
    mutationFn: () => saveOverrideReason(projectId, p.position_id, text),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['design-estimate'] }),
  });
  const dirty = text.trim() !== (p.override_reason ?? '');
  return (
    <div className="flex flex-col gap-1">
      <label className="flex flex-col gap-1 text-xs">
        {tr(t, 'design.estimate.reason')}
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={2000}
          rows={2}
          readOnly={!canManage}
          className="rounded border border-border-light bg-surface-primary px-2 py-1 text-sm"
        />
      </label>
      {!p.override_reason && !dirty && <span className="text-xs text-content-tertiary">{tr(t, 'design.estimate.reason_missing')}</span>}
      {canManage && (
        <div>
          <Button variant="secondary" disabled={!dirty || save.isPending} loading={save.isPending} onClick={() => save.mutate()}>
            {tr(t, 'design.estimate.reason_save')}
          </Button>
        </div>
      )}
      {save.isError && <MutationError err={save.error} fallback="design.estimate.reason_failed" />}
    </div>
  );
}

function Provenance({ p }: { p: EstimatePosition }) {
  const { t } = useTranslation();
  const v = p.provenance;
  if (p.kind !== 'derived' || !v.formula) {
    return p.kind === 'model' && (v.elements ?? p.elements) > 0 ? (
      <p className="text-xs text-content-tertiary">{tr(t, 'design.estimate.elements_n', { count: v.elements ?? p.elements })}</p>
    ) : null;
  }
  const b = v.benchmark;
  const rateSource = v.rate?.source;
  return (
    <details className="text-xs text-content-secondary" data-testid={`assumption-${p.rule}`}>
      <summary className="cursor-pointer">{tr(t, 'design.estimate.assumption')}</summary>
      <p className="mt-1"><span className="text-content-tertiary">{tr(t, 'design.estimate.formula')}</span> <code>{v.formula}</code></p>
      <ul className="mt-1 flex flex-col gap-1">
        {Object.entries(v.aggregates ?? {}).map(([name, a]) => (
          <li key={name}><code>{name}</code> = {a.value}: {a.assumption}</li>
        ))}
        {Object.entries(v.inputs ?? {}).map(([name, i]) => (
          <li key={name}>
            <code>{name}</code> = {String(i.value)} {i.unit ?? ''}
            {i.source && <SourceLink url={i.source.url} label={i.source.date} />}
          </li>
        ))}
      </ul>
      {rateSource && <p className="mt-1">{tr(t, 'design.estimate.rate_source')} <SourceLink url={rateSource.url} label={rateSource.date} /></p>}
      {b && (
        <p className="mt-1" data-testid={`bench-${p.rule}`}>
          {tr(t, 'design.estimate.rate_benchmark', { low: b.low, mid: b.mid, high: b.high, unit: b.unit })}{' '}
          {b.publisher}, {b.published} <SourceLink url={b.source_url} label={tr(t, 'design.estimate.source_link')} />
        </p>
      )}
    </details>
  );
}

function SourceLink({ url, label }: { url: string; label: string }) {
  const href = safeUrl(url);
  return href ? (
    <a className="text-oe-blue-text underline" href={href} target="_blank" rel="noopener noreferrer">{label}</a>
  ) : (
    <span>{label} ({url})</span>
  );
}

function Benchmarks({ est }: { est: Estimate }) {
  const { t } = useTranslation();
  const list = benchmarkSources(est);
  return (
    <Card padding="none">
      <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.estimate.benchmarks')} subtitle={tr(t, 'design.estimate.benchmarks_hint')} />
      {list.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-content-secondary" data-testid="no-benchmarks">{tr(t, 'design.estimate.no_benchmarks')}</p>
      ) : (
        <ul className="divide-y divide-border-light" data-testid="benchmark-list">
          {list.map((b) => (
            <li key={`${b.source_url}|${b.published}`} className="flex flex-col gap-1 px-4 py-3 text-sm">
              <span className="font-medium">{b.publisher}</span>
              <span className="text-xs text-content-secondary">
                {tr(t, 'design.estimate.bench_meta', { published: b.published, year: b.price_level_year, groups: b.groups.join(', ') })}
                {b.derived && <> - {tr(t, 'design.estimate.bench_derived')}</>}
                {b.vat_included === null && <> - {tr(t, 'design.estimate.bench_vat_unknown')}</>}
                {b.vat_included === true && <> - {tr(t, 'design.estimate.bench_vat_incl')}</>}
                {b.vat_included === false && <> - {tr(t, 'design.estimate.bench_vat_excl')}</>}
              </span>
              <span className="break-all text-xs"><SourceLink url={b.source_url} label={b.source_url} /></span>
            </li>
          ))}
        </ul>
      )}
      <NotUsed list={est.range.sources_not_used ?? []} />
    </Card>
  );
}

function NotUsed({ list }: { list: UnusedSource[] }) {
  const { t } = useTranslation();
  if (list.length === 0) return null;
  return (
    <section className="border-t border-border-light" data-testid="benchmarks-not-used">
      <h3 className="px-4 py-2 text-sm font-medium">{tr(t, 'design.estimate.not_used')}</h3>
      <p className="px-4 pb-1 text-xs text-content-secondary">{tr(t, 'design.estimate.not_used_hint')}</p>
      <ul className="divide-y divide-border-light">
        {list.map((u) => (
          <li key={u.source_url} className="flex flex-col gap-1 px-4 py-3 text-sm">
            <span className="font-medium">{u.publisher}</span>
            <span className="text-xs text-content-secondary">
              {tr(t, 'design.estimate.not_used_meta', { published: u.published, year: u.price_level_year })}
              {u.reasons.map((r) => <span key={r}> - {tr(t, `design.estimate.not_used.${r}`, { defaultValue: r })}</span>)}
            </span>
            <span className="break-all text-xs"><SourceLink url={u.source_url} label={u.source_url} /></span>
          </li>
        ))}
      </ul>
    </section>
  );
}
