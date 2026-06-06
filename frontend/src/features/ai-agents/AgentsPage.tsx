// AI Agents — gallery of registered agents, run them, watch the ReAct timeline.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  Loader2,
  Play,
  Plus,
  Settings as SettingsIcon,
  History,
  Sparkles,
  MessageSquarePlus,
  MessageSquare,
  Calculator,
  Bot,
  ArrowRight,
} from 'lucide-react';
import clsx from 'clsx';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { SkeletonCard, EmptyState, ConfirmDialog, Button, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import {
  aiAgentsApi,
  type AgentDescriptor,
  type AgentRun,
  type CustomAgent,
} from './api';
import { AgentGallery } from './components/AgentGallery';
import {
  CustomAgentBuilder,
  type BuilderSchedule,
  type BuilderSubmit,
} from './components/CustomAgentBuilder';
import { RunTimeline } from './components/RunTimeline';
import { RecentRunsList } from './components/RecentRunsList';
import { AutomatedRunsPanel } from './components/AutomatedRunsPanel';
import {
  agentDisplayName,
  agentTagline,
  resolveAgentIcon,
} from './components/agentMeta';

// ── AI tools cross-link strip (CONN-82) ─────────────────────────────────────
// The four AI surfaces - Agents, Cost Advisor, Chat, Quick Estimate - are
// siblings that never pointed at each other, so a user on one had no way to
// discover the others. This strip lives on each AI page (the `current` route is
// dropped) so the set reads as one connected toolset. Plain navigation only.

interface AiTool {
  to: string;
  icon: typeof Bot;
  label: string;
  desc: string;
}

export function AiToolsStrip({ current }: { current: string }): JSX.Element | null {
  const { t } = useTranslation();
  const tools: AiTool[] = [
    {
      to: '/ai-agents',
      icon: Bot,
      label: t('nav.ai_agents', { defaultValue: 'AI Agents' }),
      desc: t('ai.cross_agents_desc', { defaultValue: 'Autonomous agents that call tools' }),
    },
    {
      to: '/advisor',
      icon: MessageSquare,
      label: t('nav.ai_advisor', { defaultValue: 'AI Cost Advisor' }),
      desc: t('ai.cross_advisor_desc', { defaultValue: 'Ask the price book a question' }),
    },
    {
      to: '/chat',
      icon: Sparkles,
      label: t('nav.erp_chat', { defaultValue: 'AI Chat' }),
      desc: t('ai.cross_chat_desc', { defaultValue: 'Query your ERP in plain language' }),
    },
    {
      to: '/ai-estimate',
      icon: Calculator,
      label: t('nav.ai_estimate', { defaultValue: 'AI Quick Estimate' }),
      desc: t('ai.cross_estimate_desc', { defaultValue: 'Generate a full BOQ with AI' }),
    },
  ];
  const others = tools.filter((tool) => tool.to !== current);
  if (others.length === 0) return null;

  return (
    <section aria-label={t('ai.cross_strip_label', { defaultValue: 'Other AI tools' })}>
      <h2 className="mb-2 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
        <Sparkles className="h-3.5 w-3.5" />
        {t('ai.cross_strip_title', { defaultValue: 'Other AI tools' })}
      </h2>
      <div className="grid gap-2 sm:grid-cols-3">
        {others.map((tool) => {
          const Icon = tool.icon;
          return (
            <Link
              key={tool.to}
              to={tool.to}
              className="group flex items-center gap-3 rounded-xl border border-border-light bg-surface-elevated px-3 py-2.5 transition-colors hover:border-oe-blue/40 hover:bg-oe-blue-subtle"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-content-primary">
                  {tool.label}
                </span>
                <span className="block truncate text-xs text-content-tertiary">{tool.desc}</span>
              </span>
              <ArrowRight className="h-4 w-4 shrink-0 text-content-tertiary transition-transform group-hover:translate-x-0.5 group-hover:text-oe-blue-text" />
            </Link>
          );
        })}
      </div>
    </section>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export function AgentsPage(): JSX.Element {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const { confirm, ...confirmProps } = useConfirm();
  const [searchParams, setSearchParams] = useSearchParams();

  // Custom-agent builder modal state. `builderEditing` null + open = create.
  const [builderOpen, setBuilderOpen] = useState(false);
  const [builderEditing, setBuilderEditing] = useState<CustomAgent | null>(null);
  // Automation (Item 29) pre-load for the builder when editing an agent.
  const [builderSchedule, setBuilderSchedule] = useState<BuilderSchedule | null>(null);
  const [builderNextRunAt, setBuilderNextRunAt] = useState<string | null>(null);
  const [builderTools, setBuilderTools] = useState<string[]>([]);
  const [builderTriggers, setBuilderTriggers] = useState<string[]>([]);
  const [loadingAutomation, setLoadingAutomation] = useState(false);

  const [selected, setSelected] = useState<AgentDescriptor | null>(null);
  const [userInput, setUserInput] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // The active run is mirrored into the URL (?run=<id>) so a reload or a
  // shared link re-attaches to the same run (and its live poll) instead of
  // orphaning it. The URL is the source of truth.
  const activeRunId = searchParams.get('run');

  const setActiveRunId = (runId: string | null) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (runId) next.set('run', runId);
        else next.delete('run');
        return next;
      },
      { replace: true },
    );
  };

  const agentsQuery = useQuery({
    queryKey: ['ai-agents', 'list'],
    queryFn: () => aiAgentsApi.listAgents(),
  });

  // Tool catalogue (with required permissions) for the builder's Tools panel.
  // Only fetched while the builder is open to keep the page lean.
  const toolsCatalogueQuery = useQuery({
    queryKey: ['ai-agents', 'grantable-tools'],
    queryFn: () => aiAgentsApi.listGrantableTools(),
    enabled: builderOpen,
    staleTime: 60_000,
  });

  // Event-trigger catalogue for the builder's Triggers panel. Fetched only
  // while the builder is open to keep the page lean.
  const triggerCatalogueQuery = useQuery({
    queryKey: ['ai-agents', 'event-triggers'],
    queryFn: () => aiAgentsApi.listEventTriggers(),
    enabled: builderOpen,
    staleTime: 60_000,
  });

  // Monitoring: automated (scheduler / event-fired) runs. Polled so a freshly
  // fired scheduled run shows up without a manual refresh.
  const automatedRunsQuery = useQuery({
    queryKey: ['ai-agents', 'automated-runs'],
    queryFn: () => aiAgentsApi.listAutomatedRuns(),
    refetchInterval: 15_000,
  });

  const runsQuery = useQuery({
    queryKey: ['ai-agents', 'runs', projectId ?? null],
    queryFn: () => aiAgentsApi.listRuns(projectId ?? undefined),
    // Keep the history fresh while a run is in flight so a just-finished
    // run flips to its terminal status without a manual refresh.
    refetchInterval: 5000,
  });

  const healthQuery = useQuery({
    queryKey: ['ai-agents', 'health'],
    queryFn: () => aiAgentsApi.health(),
    // 30 s — long enough to avoid hammering, short enough that fixing
    // /settings/ai and tabbing back updates the banner promptly.
    staleTime: 30_000,
  });
  const llmConfigured = healthQuery.data?.llm_configured ?? true;
  const healthLoaded = healthQuery.isSuccess;

  const runQuery = useQuery({
    queryKey: ['ai-agents', 'run', activeRunId],
    queryFn: () => aiAgentsApi.getRun(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: (q) => {
      const run = q.state.data as AgentRun | undefined;
      return run && run.status === 'running' ? 2000 : false;
    },
  });

  const startMutation = useMutation({
    mutationFn: () =>
      aiAgentsApi.startRun({
        agent_name: selected!.name,
        project_id: projectId ?? undefined,
        user_input: userInput.trim(),
      }),
    onSuccess: (run) => {
      setActiveRunId(run.id);
      queryClient.invalidateQueries({ queryKey: ['ai-agents', 'runs'] });
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!selected || !userInput.trim()) return;
    startMutation.mutate();
  };

  // ── Custom-agent builder ────────────────────────────────────────────────
  // Save orchestration: create/update the agent, then persist its automation
  // (schedule + tools) against the resulting id. Schedule/tools live behind
  // dedicated endpoints keyed by agent id, so they can only be set once the
  // agent exists. A schedule/tool failure is surfaced but does not lose the
  // saved agent — the user can reopen and retry that section.
  const saveMutation = useMutation({
    mutationFn: async (submit: BuilderSubmit) => {
      const saved = builderEditing
        ? await aiAgentsApi.updateCustomAgent(builderEditing.id, submit.agent)
        : await aiAgentsApi.createCustomAgent(submit.agent);

      // Schedule: set when a cron is present + enabled, otherwise clear it.
      if (submit.schedule.cron && submit.schedule.enabled) {
        await aiAgentsApi.setAgentSchedule(saved.id, {
          cron_expr: submit.schedule.cron,
          enabled: true,
          schedule_input: submit.schedule.scheduleInput,
        });
      } else if (builderEditing) {
        // Editing an agent that previously had a schedule but the user turned
        // it off — remove it (ignore 404 when there was none).
        await aiAgentsApi.deleteAgentSchedule(saved.id).catch(() => undefined);
      }

      // Tools: always persist the (possibly empty) selection on save.
      await aiAgentsApi.setAgentTools(saved.id, { allowed_tools: submit.allowedTools });

      // Triggers: persist the (possibly empty) event subscriptions. These fire
      // the agent on a platform event independently of any cron schedule.
      await aiAgentsApi.setAgentTriggers(saved.id, { triggers: submit.triggers });
      return saved;
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['ai-agents', 'list'] });
      queryClient.invalidateQueries({ queryKey: ['ai-agents', 'automated-runs'] });
      setBuilderOpen(false);
      setBuilderEditing(null);
      addToast({
        type: 'success',
        title: builderEditing
          ? t('agents.builder.saved_toast', { defaultValue: 'Agent updated' })
          : t('agents.builder.created_toast', { defaultValue: 'Agent created' }),
        message: saved.display_name,
      });
    },
  });

  const openCreate = () => {
    setBuilderEditing(null);
    setBuilderSchedule(null);
    setBuilderNextRunAt(null);
    setBuilderTools([]);
    setBuilderTriggers([]);
    setBuilderOpen(true);
  };

  const openEdit = (agent: AgentDescriptor) => {
    if (!agent.custom_id) return;
    const customId = agent.custom_id;
    // The catalogue descriptor lacks the guided spec / raw prompt needed to
    // re-hydrate the form, so fetch the full custom-agent row first, then its
    // automation envelope (schedule + tools) in parallel.
    setLoadingAutomation(true);
    setBuilderSchedule(null);
    setBuilderNextRunAt(null);
    setBuilderTools([]);
    setBuilderTriggers([]);
    Promise.all([aiAgentsApi.listCustomAgents(), aiAgentsApi.getAgentSchedule(customId)])
      .then(([rows, meta]) => {
        const row = rows.find((r) => r.id === customId);
        if (!row) throw new Error('not found');
        setBuilderSchedule({
          cron: meta.cron,
          enabled: meta.schedule_enabled,
          scheduleInput: meta.schedule_input,
        });
        setBuilderNextRunAt(meta.next_run_at);
        setBuilderTools(meta.allowed_tools);
        setBuilderTriggers(meta.triggers);
        setBuilderEditing(row);
        setBuilderOpen(true);
      })
      .catch(() => {
        addToast({
          type: 'error',
          title: t('agents.builder.load_error', { defaultValue: 'Could not open the agent' }),
        });
      })
      .finally(() => setLoadingAutomation(false));
  };

  const handleDelete = async (agent: AgentDescriptor) => {
    if (!agent.custom_id) return;
    const ok = await confirm({
      title: t('agents.builder.delete_title', { defaultValue: 'Delete this agent?' }),
      message: t('agents.builder.delete_message', {
        defaultValue:
          'This removes the agent from your catalogue. Past runs are kept. This cannot be undone.',
      }),
      variant: 'danger',
      confirmLabel: t('agents.builder.delete_action', { defaultValue: 'Delete agent' }),
    });
    if (!ok) return;
    try {
      await aiAgentsApi.deleteCustomAgent(agent.custom_id);
      // If the deleted agent was selected, clear the console.
      if (selected?.name === agent.name) setSelected(null);
      queryClient.invalidateQueries({ queryKey: ['ai-agents', 'list'] });
      addToast({
        type: 'success',
        title: t('agents.builder.deleted_toast', { defaultValue: 'Agent deleted' }),
      });
    } catch {
      addToast({
        type: 'error',
        title: t('agents.builder.delete_error', { defaultValue: 'Could not delete the agent' }),
      });
    }
  };

  const agents = agentsQuery.data ?? [];
  const run = runQuery.data;
  const runs = runsQuery.data ?? [];

  // Select an agent and (optionally) seed the prompt input, then focus it.
  const selectAgent = (agent: AgentDescriptor, prompt?: string) => {
    setSelected(agent);
    setActiveRunId(null);
    if (prompt !== undefined) {
      setUserInput(prompt);
      // Focus + place caret at the end after React commits the value.
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (el) {
          el.focus();
          el.selectionStart = el.selectionEnd = el.value.length;
        }
      });
    }
  };

  // When a run is loaded from the URL (reload / shared link) and the user
  // hasn't picked an agent yet, reflect the run's agent in the catalogue so
  // the timeline isn't hidden behind the placeholder.
  useEffect(() => {
    if (!run || selected) return;
    const match = agents.find((a) => a.name === run.agent_name);
    if (match) setSelected(match);
  }, [run, selected, agents]);

  const runDisabledNoLlm = healthLoaded && !llmConfigured;
  const SelectedIcon = selected ? resolveAgentIcon(selected.icon) : Sparkles;
  const selectedPrompts = (selected?.example_prompts ?? []).filter((p) => p.trim().length > 0);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Canonical top block - module name + icon live in the global top app
          bar. The page renders only its (contextual) subtitle on the left and
          the page actions on the right. */}
      <PageHeader
        srTitle={t('agents.title', { defaultValue: 'AI Agents' })}
        subtitle={t('agents.subtitle', {
          defaultValue:
            'Run autonomous AI agents that reason, call tools, and propose actions for your review.',
        })}
        actions={
          <Button variant="primary" size="sm" icon={<Plus className="h-4 w-4" />} onClick={openCreate}>
            {t('agents.builder.create_button', { defaultValue: 'Create your own agent' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="agents"
        title={t('agents.intro_title', { defaultValue: 'Put autonomous agents to work' })}
        more={t('agents.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('agents.intro_more')} /> : undefined}
      >
        {t('agents.intro_body', {
          defaultValue:
            'Run AI agents that reason over your project data, call tools and propose actions for you to review before anything is applied.',
        })}
      </DismissibleInfo>

      <AiToolsStrip current="/ai-agents" />

      {/* LLM-provider banner — surfaces the most common failure cause
          (no_llm) upfront instead of letting the user write a prompt,
          hit Run, and stare at a cryptic "failed" row. */}
      {runDisabledNoLlm && (
        <div
          role="alert"
          aria-live="polite"
          aria-atomic="true"
          className="flex items-start gap-3 rounded-xl border border-semantic-warning/40 bg-semantic-warning-bg p-4"
        >
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-semantic-warning" />
          <div className="flex-1 text-sm">
            <p className="font-semibold text-content-primary">
              {t('agents.no_llm_title', { defaultValue: 'AI provider not configured' })}
            </p>
            <p className="mt-1 text-content-secondary">
              {t('agents.no_llm_body', {
                defaultValue:
                  'Add an API key (Anthropic, OpenAI, Gemini, OpenRouter, …) in Settings → AI to run agents. Runs started without one fail immediately.',
              })}
            </p>
            <Link
              to={healthQuery.data?.settings_url ?? '/settings?tab=ai'}
              className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-semantic-warning px-3 py-1.5 text-xs font-semibold text-content-inverse hover:opacity-90"
            >
              <SettingsIcon className="h-3.5 w-3.5" />
              {t('agents.open_ai_settings', { defaultValue: 'Open AI settings' })}
            </Link>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Main column — gallery + run console */}
        <div className="space-y-6 lg:col-span-2">
          {/* Run console (only once an agent is picked) */}
          {selected && (
            <form
              onSubmit={onSubmit}
              className="space-y-3 rounded-xl border border-border-light bg-surface-elevated p-4 shadow-xs"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
                  <SelectedIcon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-content-primary">
                    {agentDisplayName(selected.name, selected.display_name)}
                  </div>
                  {agentTagline(selected.tagline, selected.description) && (
                    <div className="truncate text-xs text-content-tertiary">
                      {agentTagline(selected.tagline, selected.description)}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <label htmlFor="agent-input" className="sr-only">
                  {t('agents.new_run', { defaultValue: 'New run' })}
                </label>
                <textarea
                  id="agent-input"
                  ref={inputRef}
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  rows={4}
                  placeholder={t('agents.input_placeholder', {
                    defaultValue: 'Describe what you want the agent to do…',
                  })}
                  className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
                />
              </div>

              {/* Example-prompt chips for the selected agent — never a bare box. */}
              {selectedPrompts.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('agents.try_asking', { defaultValue: 'Try asking' })}
                  </span>
                  {selectedPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => selectAgent(selected, prompt)}
                      className="rounded-lg border border-border-light bg-surface-secondary/60 px-2.5 py-1 text-xs text-content-secondary transition-colors hover:border-oe-blue/40 hover:bg-oe-blue-subtle hover:text-oe-blue-text"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-content-tertiary">
                <span>
                  {projectId
                    ? t('agents.project_attached', {
                        defaultValue: 'Run will be linked to active project.',
                      })
                    : t('agents.no_project', {
                        defaultValue: 'No active project - run will be global.',
                      })}
                </span>
                <button
                  type="submit"
                  disabled={!userInput.trim() || startMutation.isPending || runDisabledNoLlm}
                  title={
                    runDisabledNoLlm
                      ? t('agents.run_disabled_no_llm', {
                          defaultValue: 'Configure an AI provider in Settings → AI first.',
                        })
                      : undefined
                  }
                  aria-describedby={runDisabledNoLlm ? 'agents-run-disabled-hint' : undefined}
                  className={clsx(
                    'inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-content-inverse transition-all',
                    'hover:bg-oe-blue-hover disabled:cursor-not-allowed disabled:opacity-40',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
                  )}
                >
                  {startMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}
                  {t('agents.run', { defaultValue: 'Run agent' })}
                </button>
              </div>
              {runDisabledNoLlm && (
                <span id="agents-run-disabled-hint" className="sr-only">
                  {t('agents.run_disabled_no_llm', {
                    defaultValue: 'Configure an AI provider in Settings → AI first.',
                  })}
                </span>
              )}
              {startMutation.isError && (
                <div className="rounded-md bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error">
                  {t('agents.start_error', { defaultValue: 'Failed to start the run.' })}{' '}
                  {(startMutation.error as Error)?.message}
                </div>
              )}
            </form>
          )}

          {/* Run timeline — rendered whenever a run is active, even if the
              run's agent is no longer in the catalogue (so a reload of an
              old run still shows its result). */}
          {activeRunId && runQuery.isLoading && !run && <SkeletonCard />}
          {activeRunId && runQuery.isError && (
            <div className="rounded-xl border border-semantic-error/30 bg-semantic-error-bg p-4 text-sm text-semantic-error">
              {t('agents.run_load_error', { defaultValue: 'Could not load this run.' })}
            </div>
          )}
          {activeRunId && run && <RunTimeline run={run} />}

          {/* Gallery */}
          <section className="space-y-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-content-tertiary">
              {selected
                ? t('agents.switch_agent', { defaultValue: 'Switch agent' })
                : t('agents.catalogue', { defaultValue: 'Choose an agent to get started' })}
            </h2>

            {agentsQuery.isLoading && (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
              </div>
            )}

            {!agentsQuery.isLoading && agents.length === 0 && (
              <EmptyState
                icon={<Sparkles className="h-6 w-6" />}
                title={t('agents.empty_title', { defaultValue: 'No agents available yet' })}
                description={t('agents.empty_body', {
                  defaultValue:
                    'AI agents are installed with their modules. Once a module that ships an agent is enabled, it will appear here ready to run.',
                })}
              />
            )}

            {!agentsQuery.isLoading && agents.length > 0 && (
              <AgentGallery
                agents={agents}
                selectedName={selected?.name ?? null}
                onSelect={(agent) => selectAgent(agent)}
                onPromptPick={(agent, prompt) => selectAgent(agent, prompt)}
                onEdit={openEdit}
                onDelete={handleDelete}
              />
            )}
          </section>
        </div>

        {/* Recent runs — lets the user reattach to an in-flight run after a
            reload, or revisit a finished run's timeline. */}
        <aside className="space-y-3 lg:col-span-1">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-content-tertiary">
            <History className="h-4 w-4" />
            {t('agents.recent_runs', { defaultValue: 'Recent runs' })}
          </h2>
          {runsQuery.isLoading && (
            <div className="space-y-2">
              <SkeletonCard />
              <SkeletonCard />
            </div>
          )}
          {!runsQuery.isLoading && runs.length === 0 && (
            <div className="rounded-xl border border-dashed border-border-light bg-surface-secondary/30 p-6 text-center">
              <MessageSquarePlus className="mx-auto h-6 w-6 text-content-tertiary" />
              <p className="mt-2 text-sm font-medium text-content-secondary">
                {t('agents.no_runs_title', { defaultValue: 'No runs yet' })}
              </p>
              <p className="mt-1 text-xs text-content-tertiary">
                {t('agents.no_runs_body', {
                  defaultValue: 'Pick an agent and run it - your runs will show up here.',
                })}
              </p>
            </div>
          )}
          {!runsQuery.isLoading && runs.length > 0 && (
            <RecentRunsList
              runs={runs}
              agents={agents}
              activeRunId={activeRunId}
              onSelect={(id) => setActiveRunId(id)}
            />
          )}

          {/* Monitoring: automated (scheduler / event-fired) runs. */}
          <AutomatedRunsPanel
            runs={automatedRunsQuery.data ?? []}
            agents={agents}
            loading={automatedRunsQuery.isLoading}
            activeRunId={activeRunId}
            onSelect={(id) => setActiveRunId(id)}
          />
        </aside>
      </div>

      {/* Custom-agent builder modal + delete confirmation. */}
      <CustomAgentBuilder
        open={builderOpen}
        editing={builderEditing}
        saving={saveMutation.isPending}
        tools={toolsCatalogueQuery.data ?? []}
        triggerCatalogue={triggerCatalogueQuery.data ?? []}
        initialSchedule={builderSchedule}
        initialNextRunAt={builderNextRunAt}
        initialTools={builderTools}
        initialTriggers={builderTriggers}
        loadingAutomation={loadingAutomation || toolsCatalogueQuery.isLoading || triggerCatalogueQuery.isLoading}
        error={
          saveMutation.isError
            ? ((saveMutation.error as Error)?.message ??
              t('agents.builder.save_error', { defaultValue: 'Could not save the agent.' }))
            : null
        }
        onClose={() => {
          setBuilderOpen(false);
          setBuilderEditing(null);
        }}
        onSubmit={(submit) => saveMutation.mutate(submit)}
      />
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

export default AgentsPage;
