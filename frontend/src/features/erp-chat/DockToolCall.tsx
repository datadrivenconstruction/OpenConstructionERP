// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One tool call in the dock's transcript.
 *
 * A proposal (`propose_*`) is what the person has to act on, so its card is
 * shown whole, through the shared renderer registry, with nothing around it.
 * While the tool runs the row says "Preparing: Create a task"; when the tool
 * refused (a missing BOQ, an unknown assignee) the row says so with the
 * reason written for people, and the model's reply carries the conversation
 * on from there.
 *
 * A lookup is background: one quiet line ("Looked up: Risk register") that
 * expands to the result card on click. The legacy direct write
 * (`create_boq_item`, from conversations recorded before proposals) keeps its
 * receipt card open, since it records a change that was made.
 */
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, ChevronDown, CircleAlert, Loader2, Search } from 'lucide-react';
import type { ToolCallInfo } from './types';
import { isProposalTool, toolLabel, toolRefusalText } from './toolLabels';
import { RENDERER_REGISTRY } from './full-page/right/renderers';

/** Renderers whose card stays open by default: receipts of changes already made. */
const OPEN_BY_DEFAULT = new Set(['boq_item_created']);

const ROW =
  'flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-start text-xs text-[color:var(--chat-text-secondary)]';

export function DockToolCall({ tool }: { tool: ToolCallInfo }) {
  const { t } = useTranslation();
  const bodyId = useId();
  const renderer = tool.result?.renderer;
  const data = tool.result?.data;
  const Renderer = renderer ? RENDERER_REGISTRY[renderer] : undefined;
  const [open, setOpen] = useState(() => !!renderer && OPEN_BY_DEFAULT.has(renderer));
  const name = toolLabel(tool.name, t);
  const failed = tool.status === 'error' || renderer === 'error';

  if (isProposalTool(tool.name)) {
    if (tool.status === 'running') {
      return (
        <div className={ROW} data-testid="floating-chat-tool" data-tool={tool.name} data-state="running">
          <Loader2 size={13} aria-hidden className="shrink-0 animate-spin text-[color:var(--chat-tool-running)]" />
          <span className="min-w-0 truncate">
            {t('chat.panel.tool_preparing', { defaultValue: 'Preparing: {{name}}…', name })}
          </span>
        </div>
      );
    }
    if (!failed && renderer === 'action_proposal' && Renderer && data !== undefined) {
      return (
        <div data-testid="floating-chat-proposal" data-tool={tool.name}>
          <Renderer data={data} />
        </div>
      );
    }
    if (failed) {
      const reason = toolRefusalText(data, t);
      return (
        <div
          className={clsx(ROW, 'items-start')}
          data-testid="floating-chat-tool"
          data-tool={tool.name}
          data-state="refused"
        >
          <CircleAlert size={13} aria-hidden className="mt-px shrink-0 text-[color:var(--chat-tool-error)]" />
          <span className="min-w-0">
            <span className="font-medium text-[color:var(--chat-text-primary)]">
              {t('chat.panel.tool_refused', { defaultValue: 'Could not prepare: {{name}}', name })}
            </span>
            {reason && <span className="block text-[color:var(--chat-text-secondary)]">{reason}</span>}
          </span>
        </div>
      );
    }
  }

  const expandable = !failed && !!Renderer && data !== undefined;
  // A receipt rather than a lookup: the legacy direct write, or a proposal
  // whose card this build cannot draw. Named plainly, never "Looked up".
  const receipt = renderer === 'boq_item_created' || isProposalTool(tool.name);
  const text =
    tool.status === 'running'
      ? t('chat.panel.tool_looking_up', { defaultValue: 'Looking up: {{name}}…', name })
      : failed
        ? t('chat.panel.tool_lookup_failed', { defaultValue: 'Could not look up: {{name}}', name })
        : receipt
          ? name
          : t('chat.panel.tool_looked_up', { defaultValue: 'Looked up: {{name}}', name });
  const icon =
    tool.status === 'running' ? (
      <Loader2 size={13} aria-hidden className="shrink-0 animate-spin text-[color:var(--chat-tool-running)]" />
    ) : failed ? (
      <CircleAlert size={13} aria-hidden className="shrink-0 text-[color:var(--chat-tool-error)]" />
    ) : receipt ? (
      <Check size={13} aria-hidden className="shrink-0 text-[color:var(--chat-tool-done)]" />
    ) : (
      <Search size={13} aria-hidden className="shrink-0 text-[color:var(--chat-text-tertiary)]" />
    );
  const summary = !failed && tool.status === 'done' ? tool.result?.summary : undefined;
  const state = tool.status === 'running' ? 'running' : failed ? 'failed' : 'done';

  const label = (
    <>
      {icon}
      <span className="min-w-0 shrink-0 truncate font-medium text-[color:var(--chat-text-primary)]">{text}</span>
      {summary && (
        <span className="min-w-0 flex-1 truncate text-[color:var(--chat-text-tertiary)]" title={summary}>
          {summary}
        </span>
      )}
    </>
  );

  return (
    <div data-testid="floating-chat-tool" data-tool={tool.name} data-state={state}>
      {expandable ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={bodyId}
          className={clsx(
            ROW,
            'transition-colors hover:bg-[color:var(--chat-surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
          )}
        >
          {label}
          <ChevronDown
            size={13}
            aria-hidden
            className={clsx(
              'ms-auto shrink-0 text-[color:var(--chat-text-tertiary)] transition-transform motion-reduce:transition-none',
              open && 'rotate-180',
            )}
          />
        </button>
      ) : (
        <div className={ROW}>{label}</div>
      )}
      {expandable && open && Renderer && (
        <div
          id={bodyId}
          className="mt-1 overflow-hidden rounded-lg border border-[color:var(--chat-border-subtle)] bg-[color:var(--chat-surface-1)] p-2"
        >
          <Renderer data={data} />
        </div>
      )}
    </div>
  );
}
