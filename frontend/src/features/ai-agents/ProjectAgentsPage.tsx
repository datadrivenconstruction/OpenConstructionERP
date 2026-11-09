// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Project agent catalogue: enable, configure, run, and review the drafts agents produce.
import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Loader2, Octagon, Play, Power, X } from 'lucide-react';
import clsx from 'clsx';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { Button, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { fmtDate } from '@/shared/lib/formatters';
import {
  catalogueApi,
  type AgentDraft,
  type CatalogueAgent,
  type CatalogueAgentName,
  type CatalogueState,
} from './catalogueApi';

type ChecklistItem = {
  key: string;
  label?: string;
  enabled?: boolean;
  max_payment_days?: number;
  max_retention_percent?: number;
};

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function AgentCard({
  agent,
  projectId,
  halted,
  preset,
}: {
  agent: CatalogueAgent;
  projectId: string;
  halted: boolean;
  preset: Record<string, string> | null;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [inputs, setInputs] = useState<Record<string, string>>(preset ?? {});
  const [tokens, setTokens] = useState(agent.max_tokens_per_run);
  const [reviewDays, setReviewDays] = useState(Number(agent.config.review_after_days ?? 7));
  const [checklist, setChecklist] = useState<ChecklistItem[]>(
    Array.isArray(agent.config.checklist) ? (agent.config.checklist as ChecklistItem[]) : [],
  );

  useEffect(() => {
    if (preset) setInputs(preset);
  }, [preset]);

  const onError = (e: Error) =>
    addToast({ type: 'error', title: t('project_agents.action_failed', { defaultValue: 'Action failed' }), message: e.message });

  const configure = useMutation({
    mutationFn: (body: { enabled?: boolean; config?: Record<string, unknown>; max_tokens_per_run?: number }) =>
      catalogueApi.configure(projectId, agent.name, body),
    onSuccess: (state: CatalogueState) => qc.setQueryData(['agent-catalogue', projectId], state),
    onError,
  });

  const run = useMutation({
    mutationFn: () => catalogueApi.run(projectId, agent.name, inputs),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['agent-drafts', projectId] });
      qc.invalidateQueries({ queryKey: ['agent-runs', projectId] });
      addToast({
        type: res.draft ? 'success' : 'error',
        title: res.draft
          ? t('project_agents.draft_ready', { defaultValue: 'Draft ready for review' })
          : t('project_agents.run_failed', { defaultValue: 'The run failed' }),
        message: res.draft?.title ?? res.run.failure_reason ?? undefined,
      });
    },
    onError,
  });

  const saveConfig = () =>
    configure.mutate({
      max_tokens_per_run: tokens,
      config: { ...agent.config, review_after_days: reviewDays, ...(checklist.length ? { checklist } : {}) },
    });

  const missing = agent.inputs.some((f) => f.required && !inputs[f.key]?.trim());
  const onRun = (e: FormEvent) => {
    e.preventDefault();
    if (!missing) run.mutate();
  };

  return (
    <article
      id={`agent-${agent.name}`}
      className={clsx(
        'space-y-3 rounded-xl border bg-surface-primary p-4',
        preset ? 'border-oe-blue/60' : 'border-border-light',
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t(`project_agents.agent.${agent.name}.name`, { defaultValue: agent.display_name })}
          </h3>
          <p className="text-xs text-content-secondary">
            {t(`project_agents.agent.${agent.name}.tagline`, { defaultValue: agent.tagline })}
          </p>
          <p className="mt-1 text-2xs text-content-tertiary">
            {t('project_agents.read_only', { defaultValue: 'Reads only. Writes nothing until you accept a draft.' })}
          </p>
        </div>
        <label className="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={agent.enabled}
            onChange={(e) => configure.mutate({ enabled: e.target.checked })}
            disabled={configure.isPending}
          />
          {t('project_agents.enabled', { defaultValue: 'Enabled' })}
        </label>
      </header>

      <details className="text-xs">
        <summary className="cursor-pointer text-content-secondary">
          {t('project_agents.configure', { defaultValue: 'Configure' })}
        </summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <label className="flex flex-col gap-1">
            {t('project_agents.max_tokens', { defaultValue: 'Token limit per run' })}
            <input
              type="number"
              min={500}
              max={200000}
              step={500}
              value={tokens}
              onChange={(e) => setTokens(Number(e.target.value))}
              className="h-8 rounded border border-border-light bg-surface-primary px-2"
            />
          </label>
          <label className="flex flex-col gap-1">
            {t('project_agents.review_after_days', { defaultValue: 'Flag unreviewed drafts after (days)' })}
            <input
              type="number"
              min={1}
              max={90}
              value={reviewDays}
              onChange={(e) => setReviewDays(Number(e.target.value))}
              className="h-8 rounded border border-border-light bg-surface-primary px-2"
            />
          </label>
        </div>
        {checklist.length > 0 && (
          <fieldset className="mt-2 space-y-1">
            <legend className="font-medium text-content-secondary">
              {t('project_agents.checklist', { defaultValue: 'Clause checklist' })}
            </legend>
            {checklist.map((item, idx) => (
              <div key={item.key} className="flex flex-wrap items-center gap-2">
                <label className="flex min-w-[10rem] items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={item.enabled !== false}
                    onChange={(e) =>
                      setChecklist((c) => c.map((x, i) => (i === idx ? { ...x, enabled: e.target.checked } : x)))
                    }
                  />
                  {t(`project_agents.clause.${item.key}`, { defaultValue: item.label ?? item.key })}
                </label>
                {item.max_payment_days !== undefined && (
                  <label className="flex items-center gap-1">
                    {t('project_agents.max_payment_days', { defaultValue: 'max days' })}
                    <input
                      type="number"
                      min={1}
                      value={item.max_payment_days}
                      onChange={(e) =>
                        setChecklist((c) =>
                          c.map((x, i) => (i === idx ? { ...x, max_payment_days: Number(e.target.value) } : x)),
                        )
                      }
                      className="h-7 w-16 rounded border border-border-light bg-surface-primary px-1"
                    />
                  </label>
                )}
                {item.max_retention_percent !== undefined && (
                  <label className="flex items-center gap-1">
                    {t('project_agents.max_retention', { defaultValue: 'max %' })}
                    <input
                      type="number"
                      min={0}
                      step={0.5}
                      value={item.max_retention_percent}
                      onChange={(e) =>
                        setChecklist((c) =>
                          c.map((x, i) => (i === idx ? { ...x, max_retention_percent: Number(e.target.value) } : x)),
                        )
                      }
                      className="h-7 w-16 rounded border border-border-light bg-surface-primary px-1"
                    />
                  </label>
                )}
              </div>
            ))}
          </fieldset>
        )}
        <Button variant="secondary" className="mt-2" onClick={saveConfig} disabled={configure.isPending}>
          {t('project_agents.save_config', { defaultValue: 'Save configuration' })}
        </Button>
      </details>

      <form onSubmit={onRun} className="flex flex-wrap items-end gap-2">
        {agent.inputs.map((f) => (
          <label key={f.key} className="flex flex-1 flex-col gap-1 text-xs text-content-secondary">
            {t(`project_agents.input.${f.key}`, { defaultValue: f.key })}
            {f.required ? ' *' : ''}
            <input
              type={f.kind === 'date' ? 'date' : 'text'}
              value={inputs[f.key] ?? ''}
              onChange={(e) => setInputs((s) => ({ ...s, [f.key]: e.target.value }))}
              className="h-8 min-w-[10rem] rounded border border-border-light bg-surface-primary px-2 text-sm text-content-primary"
            />
          </label>
        ))}
        <Button type="submit" disabled={!agent.enabled || halted || missing || run.isPending}>
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {t('project_agents.run', { defaultValue: 'Run' })}
        </Button>
      </form>
      {!agent.enabled && (
        <p className="text-2xs text-content-tertiary">
          {t('project_agents.enable_first', { defaultValue: 'Enable the agent on this project to run it.' })}
        </p>
      )}
    </article>
  );
}

function DraftCard({ draft, projectId }: { draft: AgentDraft; projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const review = useMutation({
    mutationFn: (body: { decision: 'accepted' | 'rejected'; apply?: boolean }) =>
      catalogueApi.review(projectId, draft.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-drafts', projectId] });
      qc.invalidateQueries({ queryKey: ['agent-validation', projectId] });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('project_agents.action_failed', { defaultValue: 'Action failed' }), message: e.message }),
  });
  const narrative = typeof draft.payload.narrative === 'string' ? draft.payload.narrative : null;
  return (
    <article className="space-y-2 rounded-xl border border-border-light bg-surface-primary p-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-medium text-content-primary">{draft.title}</h4>
          <p className="text-2xs text-content-tertiary">
            {t(`project_agents.agent.${draft.agent_name}.name`, { defaultValue: draft.agent_name })}
            {draft.created_at ? ` · ${fmtDate(draft.created_at, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}` : ''}
          </p>
        </div>
        <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-2xs">
          {t('project_agents.confidence', { defaultValue: 'Confidence {{value}}', value: pct(draft.confidence) })}
        </span>
      </header>
      {narrative && <p className="text-xs text-content-secondary">{narrative}</p>}
      <details className="text-xs">
        <summary className="cursor-pointer text-content-secondary">
          {t('project_agents.draft_details', { defaultValue: 'Draft content' })}
        </summary>
        <pre className="mt-1 max-h-72 overflow-auto rounded bg-surface-secondary p-2 text-2xs">
          {JSON.stringify(draft.payload, null, 2)}
        </pre>
      </details>
      {draft.sources.length > 0 && (
        <ul className="space-y-0.5 text-xs">
          {draft.sources.slice(0, 8).map((s, i) => {
            const label = [s.title ?? s.label ?? s.kind, s.revision && `rev ${s.revision}`, s.sheet_number, s.page && `p. ${s.page}`, s.section]
              .filter(Boolean)
              .join(' · ');
            return (
              <li key={i}>
                {s.deep_link && s.deep_link.startsWith('/') && !s.deep_link.startsWith('//') ? (
                  <Link to={s.deep_link} className="text-oe-blue hover:underline">
                    {label}
                  </Link>
                ) : (
                  <span className="text-content-secondary">{label}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {draft.status === 'pending' ? (
        <div className="flex flex-wrap gap-2">
          {draft.draft_kind === 'rfi' && (
            <Button onClick={() => review.mutate({ decision: 'accepted', apply: true })} disabled={review.isPending}>
              <Check className="h-4 w-4" />
              {t('project_agents.accept_create_rfi', { defaultValue: 'Accept and create RFI draft' })}
            </Button>
          )}
          <Button
            variant={draft.draft_kind === 'rfi' ? 'secondary' : 'primary'}
            onClick={() => review.mutate({ decision: 'accepted' })}
            disabled={review.isPending}
          >
            <Check className="h-4 w-4" />
            {t('project_agents.accept', { defaultValue: 'Accept' })}
          </Button>
          <Button variant="ghost" onClick={() => review.mutate({ decision: 'rejected' })} disabled={review.isPending}>
            <X className="h-4 w-4" />
            {t('project_agents.reject', { defaultValue: 'Reject' })}
          </Button>
        </div>
      ) : (
        <p className="text-2xs text-content-tertiary">
          {draft.status === 'accepted'
            ? t('project_agents.accepted', { defaultValue: 'Accepted' })
            : t('project_agents.rejected', { defaultValue: 'Rejected' })}
          {draft.applied_record_id && (
            <>
              {' · '}
              <Link to={`/rfi/${draft.applied_record_id}`} className="text-oe-blue hover:underline">
                {t('project_agents.open_rfi', { defaultValue: 'Open RFI' })}
              </Link>
            </>
          )}
        </p>
      )}
    </article>
  );
}

export function ProjectAgentsPage() {
  const { t, i18n } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const presetAgent = params.get('agent') as CatalogueAgentName | null;
  const preset = presetAgent
    ? Object.fromEntries([...params.entries()].filter(([k]) => k !== 'agent'))
    : null;
  const [presetMemo] = useState(preset);

  const catalogue = useQuery({
    queryKey: ['agent-catalogue', projectId],
    queryFn: () => catalogueApi.get(projectId!),
    enabled: !!projectId,
  });
  const drafts = useQuery({
    queryKey: ['agent-drafts', projectId],
    queryFn: () => catalogueApi.drafts(projectId!),
    enabled: !!projectId,
  });
  const runs = useQuery({
    queryKey: ['agent-runs', projectId],
    queryFn: () => catalogueApi.runs(projectId!),
    enabled: !!projectId,
  });
  const validation = useQuery({
    queryKey: ['agent-validation', projectId, i18n.language],
    queryFn: () => catalogueApi.validation(projectId!, i18n.language ?? 'en'),
    enabled: !!projectId,
  });
  const halt = useMutation({
    mutationFn: (halted: boolean) => catalogueApi.halt(projectId!, halted),
    onSuccess: (state) => qc.setQueryData(['agent-catalogue', projectId], state),
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('project_agents.action_failed', { defaultValue: 'Action failed' }), message: e.message }),
  });

  useEffect(() => {
    if (presetAgent && catalogue.data) document.getElementById(`agent-${presetAgent}`)?.scrollIntoView({ block: 'center' });
  }, [presetAgent, catalogue.data]);

  if (!projectId) {
    return (
      <div className="p-4">
        <EmptyState
          title={t('project_agents.pick_project', { defaultValue: 'Choose a project first' })}
          description={t('project_agents.pick_project_hint', {
            defaultValue: 'Agents are enabled, configured and reviewed per project.',
          })}
        />
      </div>
    );
  }

  const state = catalogue.data;
  const pending = (drafts.data ?? []).filter((d) => d.status === 'pending');
  const reviewed = (drafts.data ?? []).filter((d) => d.status !== 'pending').slice(0, 10);

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('nav.project_agents', { defaultValue: 'Project Agents' })}
        subtitle={t('project_agents.subtitle', {
          defaultValue: 'Ready agents that draft RFIs, daily reports, clause reviews and submittal checks for you to review.',
        })}
        actions={
          state && (
            <Button variant={state.halted ? 'primary' : 'danger'} onClick={() => halt.mutate(!state.halted)} disabled={halt.isPending}>
              {state.halted ? <Power className="h-4 w-4" /> : <Octagon className="h-4 w-4" />}
              {state.halted
                ? t('project_agents.resume', { defaultValue: 'Allow agents again' })
                : t('project_agents.halt', { defaultValue: 'Stop all agents' })}
            </Button>
          )
        }
      />
      {state?.halted && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-700 dark:text-red-300">
          <Octagon className="h-4 w-4" />
          {t('project_agents.halted', { defaultValue: 'All agents are stopped on this project. No run can start.' })}
        </div>
      )}
      {(validation.data?.findings.length ?? 0) > 0 && (
        <div className="space-y-1 rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 text-xs text-content-secondary">
          {validation.data!.findings.map((f, i) => (
            <p key={i} className="flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" />
              {f.message}
            </p>
          ))}
        </div>
      )}
      {catalogue.isLoading ? (
        <Loader2 className="h-5 w-5 animate-spin" />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {state?.agents.map((a) => (
            <AgentCard
              key={a.name}
              agent={a}
              projectId={projectId}
              halted={state.halted}
              preset={presetMemo && presetAgent === a.name ? presetMemo : null}
            />
          ))}
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('project_agents.drafts_to_review', { defaultValue: 'Drafts to review ({{count}})', count: pending.length })}
        </h2>
        {pending.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('project_agents.no_drafts', { defaultValue: 'No drafts waiting. Run an agent to create one.' })}
          </p>
        ) : (
          <div className="grid gap-2 lg:grid-cols-2">
            {pending.map((d) => (
              <DraftCard key={d.id} draft={d} projectId={projectId} />
            ))}
          </div>
        )}
        {reviewed.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-content-secondary">
              {t('project_agents.reviewed', { defaultValue: 'Recently reviewed' })}
            </summary>
            <div className="mt-2 grid gap-2 lg:grid-cols-2">
              {reviewed.map((d) => (
                <DraftCard key={d.id} draft={d} projectId={projectId} />
              ))}
            </div>
          </details>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('project_agents.history', { defaultValue: 'Run history' })}
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-content-tertiary">
              <tr>
                <th className="py-1 pr-2">{t('project_agents.col_agent', { defaultValue: 'Agent' })}</th>
                <th className="py-1 pr-2">{t('project_agents.col_status', { defaultValue: 'Status' })}</th>
                <th className="py-1 pr-2">{t('project_agents.col_tokens', { defaultValue: 'Tokens' })}</th>
                <th className="py-1 pr-2">{t('project_agents.col_started', { defaultValue: 'Started' })}</th>
                <th className="py-1">{t('project_agents.col_audit', { defaultValue: 'Audit' })}</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((r) => (
                <tr key={r.id} className="border-t border-border-light">
                  <td className="py-1 pr-2">{t(`project_agents.agent.${r.agent_name}.name`, { defaultValue: r.agent_name })}</td>
                  <td className="py-1 pr-2">{r.failure_reason ? `${r.status} (${r.failure_reason})` : r.status}</td>
                  <td className="py-1 pr-2">{r.total_tokens}</td>
                  <td className="py-1 pr-2">{r.started_at ? fmtDate(r.started_at, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}</td>
                  <td className="py-1">
                    <Link to={`/ai-agents?run=${r.id}`} className="text-oe-blue hover:underline">
                      {t('project_agents.open_timeline', { defaultValue: 'Timeline' })}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
