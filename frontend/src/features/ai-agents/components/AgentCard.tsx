// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Pencil, Trash2 } from 'lucide-react';

import type { AgentDescriptor } from '../api';
import { ToolBadge } from './ToolBadge';
import {
  resolveAgentIcon,
  agentDisplayName,
  agentTagline,
} from './agentMeta';
import { fmtList } from '@/shared/lib/formatters';

interface AgentCardProps {
  agent: AgentDescriptor;
  selected: boolean;
  /** Select the agent (clears any active run). */
  onSelect: () => void;
  /** Select the agent AND prefill the run input with the example prompt. */
  onPromptPick: (prompt: string) => void;
  /** Edit this agent — only provided for the caller's own custom agents. */
  onEdit?: () => void;
  /** Delete this agent — only provided for the caller's own custom agents. */
  onDelete?: () => void;
}

const MAX_TOOLS = 4;

/**
 * Rich agent card: icon, display name, tagline, a few friendly tool badges,
 * and clickable example-prompt chips. The whole card is selectable; clicking
 * a chip both selects the agent and seeds the run input.
 */
export function AgentCard({
  agent,
  selected,
  onSelect,
  onPromptPick,
  onEdit,
  onDelete,
}: AgentCardProps): JSX.Element {
  const { t } = useTranslation();
  const Icon = resolveAgentIcon(agent.icon);
  const title = agentDisplayName(agent.name, agent.display_name);
  const tagline = agentTagline(agent.tagline, agent.description);
  const prompts = (agent.example_prompts ?? []).filter((p) => p.trim().length > 0);
  const tools = agent.allowed_tools ?? [];
  const shownTools = tools.slice(0, MAX_TOOLS);
  const extraTools = tools.length - shownTools.length;
  const showActions = !!(onEdit || onDelete);

  return (
    <div
      className={clsx(
        'group relative rounded-xl border bg-surface-elevated p-4 text-left transition-all duration-normal ease-oe',
        'shadow-xs hover:shadow-md',
        selected
          ? 'border-oe-blue/60 ring-2 ring-oe-blue/20'
          : 'border-border-light hover:border-border',
      )}
    >
      {/* Edit / delete actions — only for the caller's own custom agents.
          They reveal on hover/focus so a built-in-looking card stays clean. */}
      {showActions && (
        <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          {onEdit && (
            <button
              type="button"
              onClick={onEdit}
              aria-label={t('agents.builder.edit_action', { defaultValue: 'Edit agent' })}
              className="flex h-7 w-7 items-center justify-center rounded-md bg-surface-secondary/80 text-content-tertiary backdrop-blur-sm transition-colors hover:bg-surface-tertiary hover:text-content-secondary"
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              aria-label={t('agents.builder.delete_action', { defaultValue: 'Delete agent' })}
              className="flex h-7 w-7 items-center justify-center rounded-md bg-surface-secondary/80 text-content-tertiary backdrop-blur-sm transition-colors hover:bg-semantic-error-bg hover:text-semantic-error"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
      )}

      {/* Header — clicking selects the agent. */}
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={clsx(
          'flex w-full items-start gap-3 text-left focus-visible:outline-none',
          showActions && 'pr-14',
        )}
      >
        <span
          className={clsx(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors',
            selected
              ? 'bg-oe-blue text-content-inverse'
              : 'bg-oe-blue-subtle text-oe-blue-text group-hover:bg-oe-blue/15',
          )}
        >
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="truncate font-semibold text-content-primary">{title}</span>
            {selected && (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-oe-blue" aria-hidden="true" />
            )}
          </span>
          {tagline && (
            <span className="mt-0.5 block text-xs leading-relaxed text-content-secondary">
              {tagline}
            </span>
          )}
        </span>
      </button>

      {/* Tools */}
      {shownTools.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {shownTools.map((tool) => (
            <ToolBadge key={tool} tool={tool} />
          ))}
          {extraTools > 0 && (
            <span
              className="inline-flex items-center rounded-full bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-tertiary"
              title={fmtList(tools.slice(MAX_TOOLS))}
            >
              {t('agents.more_tools', {
                defaultValue: '+{{count}} more',
                count: extraTools,
              })}
            </span>
          )}
        </div>
      )}

      {/* Example prompts */}
      {prompts.length > 0 && (
        <div className="mt-3 border-t border-border-light pt-3">
          <div className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('agents.try_asking', { defaultValue: 'Try asking' })}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {prompts.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => onPromptPick(prompt)}
                className={clsx(
                  'rounded-lg border border-border-light bg-surface-secondary/60 px-2.5 py-1 text-left text-xs text-content-secondary',
                  'transition-colors hover:border-oe-blue/40 hover:bg-oe-blue-subtle hover:text-oe-blue-text',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                )}
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
