// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Monitoring panel for automated agent runs (Item 29).
//
// Scheduled and event-fired runs have no user watching the timeline live, so
// this panel surfaces them: when each automated run happened, what fired it,
// and whether it failed. Clicking a run opens its timeline (same ?run= deep
// link the recent-runs list uses). This is the in-app monitoring surface; a
// failed automated run also raises an in-app notification server-side.
import { useTranslation } from 'react-i18next';
import { CalendarClock, Zap, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import clsx from 'clsx';

import { DateDisplay } from '@/shared/ui';
import type { AgentDescriptor, AgentRunListItem } from '../api';
import { agentDisplayName } from './agentMeta';

interface AutomatedRunsPanelProps {
  runs: AgentRunListItem[];
  agents: AgentDescriptor[];
  loading?: boolean;
  activeRunId: string | null;
  onSelect: (runId: string) => void;
}

/** Human label for a run's trigger source: schedule | event:<name> | manual. */
function triggerLabel(source: string, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (source === 'schedule') return t('agents.monitor.via_schedule', { defaultValue: 'Scheduled' });
  if (source.startsWith('event:')) {
    const name = source.slice('event:'.length);
    return t('agents.monitor.via_event', { defaultValue: 'Event: {{event}}', event: name });
  }
  return source;
}

export function AutomatedRunsPanel({
  runs,
  agents,
  loading = false,
  activeRunId,
  onSelect,
}: AutomatedRunsPanelProps): JSX.Element {
  const { t } = useTranslation();

  return (
    <div className="space-y-3">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-content-tertiary">
        <CalendarClock className="h-4 w-4" />
        {t('agents.monitor.title', { defaultValue: 'Automated runs' })}
      </h2>

      {loading && runs.length === 0 ? (
        <div className="flex items-center gap-2 rounded-xl border border-border-light bg-surface-secondary/30 p-4 text-xs text-content-tertiary">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('agents.monitor.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : runs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-light bg-surface-secondary/30 p-5 text-center">
          <Zap className="mx-auto h-5 w-5 text-content-tertiary" />
          <p className="mt-2 text-xs font-medium text-content-secondary">
            {t('agents.monitor.empty_title', { defaultValue: 'No automated runs yet' })}
          </p>
          <p className="mt-1 text-2xs text-content-tertiary">
            {t('agents.monitor.empty_body', {
              defaultValue:
                'Put an agent on a schedule or an event trigger and its automatic runs will appear here.',
            })}
          </p>
        </div>
      ) : (
        <ul className="space-y-1.5">
          {runs.map((run) => {
            const agent = agents.find((a) => a.name === run.agent_name);
            const name = agentDisplayName(run.agent_name, agent?.display_name);
            const isActive = run.id === activeRunId;
            const failed = run.status === 'failed';
            return (
              <li key={run.id}>
                <button
                  type="button"
                  onClick={() => onSelect(run.id)}
                  className={clsx(
                    'flex w-full items-start gap-2.5 rounded-lg border p-2.5 text-left transition-colors',
                    isActive
                      ? 'border-oe-blue/40 bg-oe-blue-subtle/40'
                      : 'border-border-light bg-surface-elevated hover:border-oe-blue/30 hover:bg-surface-secondary/40',
                  )}
                >
                  <span className="mt-0.5 shrink-0">
                    {run.status === 'running' ? (
                      <Loader2 className="h-4 w-4 animate-spin text-semantic-warning" />
                    ) : failed ? (
                      <AlertCircle className="h-4 w-4 text-semantic-error" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4 text-semantic-success" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-content-primary">{name}</span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-content-tertiary">
                      <span className="rounded-full bg-surface-tertiary px-1.5 py-0.5 font-medium">
                        {triggerLabel(run.trigger_source, t)}
                      </span>
                      <DateDisplay value={run.created_at} format="datetime" />
                      {failed && run.failure_reason && (
                        <span className="text-semantic-error">{run.failure_reason}</span>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default AutomatedRunsPanel;
