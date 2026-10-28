// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react';

import type { AgentDescriptor, AgentRunListItem } from '../api';
import { resolveAgentIcon, agentDisplayName } from './agentMeta';
import { getIntlLocale } from '@/shared/lib/formatters';

interface RecentRunsListProps {
  runs: AgentRunListItem[];
  agents: AgentDescriptor[];
  activeRunId: string | null;
  onSelect: (runId: string) => void;
}

export function RecentRunsList({
  runs,
  agents,
  activeRunId,
  onSelect,
}: RecentRunsListProps): JSX.Element {
  return (
    <ul className="space-y-2">
      {runs.map((r) => {
        const descriptor = agents.find((a) => a.name === r.agent_name);
        return (
          <li key={r.id}>
            <RecentRunButton
              run={r}
              descriptor={descriptor}
              active={r.id === activeRunId}
              onSelect={() => onSelect(r.id)}
            />
          </li>
        );
      })}
    </ul>
  );
}

function RecentRunButton({
  run,
  descriptor,
  active,
  onSelect,
}: {
  run: AgentRunListItem;
  descriptor?: AgentDescriptor;
  active: boolean;
  onSelect: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const when = run.created_at ? new Date(run.created_at).toLocaleString(getIntlLocale()) : '';
  const title = agentDisplayName(run.agent_name, descriptor?.display_name);
  const Icon = resolveAgentIcon(descriptor?.icon);

  const StatusIcon =
    run.status === 'running'
      ? Loader2
      : run.status === 'completed'
        ? CheckCircle2
        : AlertCircle;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? 'true' : undefined}
      className={clsx(
        'block w-full rounded-lg border p-3 text-left transition-all duration-normal ease-oe',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        active
          ? 'border-oe-blue/60 bg-oe-blue-subtle/60 ring-1 ring-oe-blue/20'
          : 'border-border-light bg-surface-elevated hover:border-border',
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 shrink-0 text-content-tertiary" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate font-medium text-content-primary">{title}</span>
        <span
          className={clsx(
            'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium',
            run.status === 'running' && 'bg-semantic-warning-bg text-[#b45309]',
            run.status === 'completed' && 'bg-semantic-success-bg text-semantic-success',
            run.status === 'failed' && 'bg-semantic-error-bg text-semantic-error',
          )}
        >
          <StatusIcon className={clsx('h-2.5 w-2.5', run.status === 'running' && 'animate-spin')} />
          {t(`agents.status.${run.status}`, { defaultValue: run.status })}
        </span>
      </div>
      {when && <div className="mt-1 pl-6 text-2xs text-content-tertiary">{when}</div>}
    </button>
  );
}
