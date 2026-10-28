// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import DOMPurify from 'isomorphic-dompurify';
import clsx from 'clsx';
import {
  Brain,
  Wrench,
  MessageSquare,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Settings as SettingsIcon,
  Copy,
  Check,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';

import type { AgentRun, AgentStep, AgentStepRole } from '../api';
import { toolLabel } from './agentMeta';
import { ApplyActionButton } from './ApplyActionButton';
import { TrustEnvelopeCard } from './TrustEnvelopeCard';
import {
  renderMarkdown,
  SANITIZE_CONFIG,
} from '@/features/erp-chat/full-page/left/MessageBubble';
import { copyToClipboard } from '@/shared/lib/browser';

// ── Step role styling ────────────────────────────────────────────────────────

const ROLE_META: Record<
  AgentStepRole,
  { icon: LucideIcon; iconClass: string; railClass: string; defaultLabel: string }
> = {
  thought: {
    icon: Brain,
    iconClass: 'text-violet-500',
    railClass: 'bg-violet-400/60',
    defaultLabel: 'Thought',
  },
  tool_call: {
    icon: Wrench,
    iconClass: 'text-oe-blue',
    railClass: 'bg-oe-blue/50',
    defaultLabel: 'Tool call',
  },
  observation: {
    icon: MessageSquare,
    iconClass: 'text-content-tertiary',
    railClass: 'bg-border',
    defaultLabel: 'Observation',
  },
  answer: {
    icon: CheckCircle2,
    iconClass: 'text-semantic-success',
    railClass: 'bg-semantic-success/50',
    defaultLabel: 'Answer',
  },
  error: {
    icon: AlertCircle,
    iconClass: 'text-semantic-error',
    railClass: 'bg-semantic-error/50',
    defaultLabel: 'Error',
  },
};

const STATUS_BADGE: Record<AgentRun['status'], string> = {
  running: 'bg-semantic-warning-bg text-[#b45309]',
  completed: 'bg-semantic-success-bg text-semantic-success',
  failed: 'bg-semantic-error-bg text-semantic-error',
};

// ── Content helpers ───────────────────────────────────────────────────────────

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function asString(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v == null) return '';
  return JSON.stringify(v, null, 2);
}

/** Render a single scalar value compactly. */
function formatScalar(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

/** Compact key/value view for a flat-ish object (e.g. tool args). */
function KeyValueView({ data }: { data: Record<string, unknown> }): JSX.Element {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <span className="text-xs text-content-tertiary">—</span>;
  }
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="font-medium text-content-tertiary">{key}</dt>
          <dd className="min-w-0 break-words text-content-secondary">
            {isPlainObject(value) || Array.isArray(value) ? (
              <PrettyBlock value={value} />
            ) : (
              formatScalar(value)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Pretty, collapsible-ish formatted block for nested/complex content. */
function PrettyBlock({ value }: { value: unknown }): JSX.Element {
  return (
    <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-secondary/70 px-2.5 py-2 font-mono text-xs leading-relaxed text-content-secondary">
      {asString(value)}
    </pre>
  );
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyButton({ text, label }: { text: string; label: string }): JSX.Element {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    void copyToClipboard(text).then((ok) => {
      if (ok) {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1800);
      } else {
        /* clipboard blocked — fail silently */
      }
    });
  };

  return (
    <button
      type="button"
      onClick={onCopy}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors',
        copied
          ? 'text-semantic-success'
          : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
      )}
      aria-label={label}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied
        ? t('agents.copied', { defaultValue: 'Copied' })
        : t('common.copy', { defaultValue: 'Copy' })}
    </button>
  );
}

// ── Step row ──────────────────────────────────────────────────────────────────

function StepRow({ step, isLast }: { step: AgentStep; isLast: boolean }): JSX.Element {
  const { t } = useTranslation();
  const meta = ROLE_META[step.role] ?? ROLE_META.observation;
  const Icon = meta.icon;

  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {/* Rail */}
      {!isLast && (
        <span
          aria-hidden="true"
          className={clsx('absolute left-3 top-7 -ml-px h-[calc(100%-1.25rem)] w-0.5 rounded', meta.railClass)}
        />
      )}
      <span
        className={clsx(
          'relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-elevated ring-1 ring-border-light',
        )}
      >
        <Icon className={clsx('h-3.5 w-3.5', meta.iconClass)} aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t(`agents.step.${step.role}`, { defaultValue: meta.defaultLabel })}
        </div>
        <div className="mt-1">
          <StepContent step={step} />
        </div>
      </div>
    </li>
  );
}

/** Role-aware, formatted rendering of a step's content. */
function StepContent({ step }: { step: AgentStep }): JSX.Element {
  const { t } = useTranslation();
  const content = step.content;

  // tool_call → "Called <friendly tool>" + a compact args view.
  if (step.role === 'tool_call' && isPlainObject(content)) {
    const toolName =
      typeof content.tool === 'string'
        ? content.tool
        : typeof content.name === 'string'
          ? content.name
          : undefined;
    const rawArgs = content.args ?? content.arguments ?? content.input;
    const args = isPlainObject(rawArgs) ? rawArgs : undefined;
    const friendly = toolName ? toolLabel(toolName) : undefined;
    return (
      <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-2.5">
        {friendly && (
          <div className="text-xs text-content-primary">
            <span className="text-content-tertiary">
              {t('agents.called_tool', { defaultValue: 'Called' })}{' '}
            </span>
            <span title={friendly.hint} className="font-medium">
              {friendly.label}
            </span>
          </div>
        )}
        {args && Object.keys(args).length > 0 && (
          <div className={clsx(friendly && 'mt-2')}>
            <KeyValueView data={args} />
          </div>
        )}
        {!friendly && !args && <PrettyBlock value={content} />}
      </div>
    );
  }

  // observation → compact formatted view (pretty-print objects).
  if (step.role === 'observation') {
    if (isPlainObject(content) || Array.isArray(content)) {
      return <PrettyBlock value={content} />;
    }
    return (
      <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-content-secondary">
        {asString(content)}
      </p>
    );
  }

  // error → highlight the message, keep details pretty-printed.
  if (step.role === 'error') {
    const message = isPlainObject(content)
      ? (content.message as string | undefined) ?? asString(content)
      : asString(content);
    return (
      <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-semantic-error">
        {message}
      </p>
    );
  }

  // thought / answer → markdown-ish plain text.
  if (typeof content === 'string') {
    return <Markdown text={content} className="text-xs leading-relaxed" />;
  }
  return <PrettyBlock value={content} />;
}

// ── Markdown ──────────────────────────────────────────────────────────────────

function Markdown({ text, className }: { text: string; className?: string }): JSX.Element {
  const html = useMemo(
    () => DOMPurify.sanitize(renderMarkdown(text), SANITIZE_CONFIG),
    [text],
  );
  return (
    <div
      className={clsx('break-words text-content-secondary', className)}
      // eslint-disable-next-line react/no-danger -- sanitised via DOMPurify with the chat allow-list.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

// ── Failure-reason humanisation (preserved verbatim) ──────────────────────────

function useFailureLabel(run: AgentRun, steps: AgentStep[]): string | null {
  const { t } = useTranslation();
  if (!run.failure_reason) return null;
  switch (run.failure_reason) {
    case 'no_llm':
      return t('agents.failure.no_llm', {
        defaultValue: 'AI provider not configured - add an API key in Settings → AI.',
      });
    case 'unknown_agent':
      return t('agents.failure.unknown_agent', { defaultValue: 'Unknown agent registered.' });
    case 'exception':
      return t('agents.failure.exception', { defaultValue: 'Agent crashed during execution.' });
    case 'iter_limit':
      return t('agents.failure.iter_limit', {
        defaultValue: 'Agent reached its step limit without finishing.',
      });
    case 'token_limit':
      return t('agents.failure.token_limit', {
        defaultValue: 'Agent reached its token budget before finishing.',
      });
    case 'wall_timeout':
      return t('agents.failure.wall_timeout', {
        defaultValue: 'Agent ran out of time before finishing.',
      });
    case 'llm_timeout':
      return t('agents.failure.llm_timeout', {
        defaultValue: 'The AI provider did not respond in time.',
      });
    case 'llm_error':
      return t('agents.failure.llm_error', { defaultValue: 'The AI provider returned an error.' });
    case 'bad_llm_item':
      return t('agents.failure.bad_llm_item', {
        defaultValue: 'The AI returned an unexpected response the agent could not use.',
      });
    case 'unknown_tool':
      return t('agents.failure.unknown_tool', {
        defaultValue: 'The agent tried to use a tool that is not available.',
      });
    default: {
      // Prefer a user-friendly message the backend may have attached to the
      // last error step before falling back to a generic label — never
      // surface the raw internal enum.
      const lastError = [...steps].reverse().find((s) => s.role === 'error');
      const msg =
        lastError && isPlainObject(lastError.content)
          ? (lastError.content.message as string | undefined)
          : undefined;
      return msg ?? t('agents.failure.unknown', { defaultValue: 'The agent run failed.' });
    }
  }
}

// ── Run timeline ───────────────────────────────────────────────────────────────

export function RunTimeline({ run }: { run: AgentRun }): JSX.Element {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const steps = useMemo(() => run.steps ?? [], [run.steps]);
  const failureLabel = useFailureLabel(run, steps);
  const statusBadge = STATUS_BADGE[run.status];

  // The run can finish while the user is watching its timeline. The proposals
  // query (read by ApplyActionButton) has a 60s staleTime, so without this it
  // would not pick up the freshly-recovered proposals until that window
  // expires. Invalidate it the moment the run reaches a terminal completed
  // state so the proposal count reflects reality immediately.
  useEffect(() => {
    if (run.status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: ['ai-agents', 'proposals', run.id] });
    }
  }, [run.status, run.id, queryClient]);

  return (
    <div className="space-y-4 rounded-xl border border-border-light bg-surface-elevated p-5 shadow-xs">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
              statusBadge,
            )}
          >
            {run.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
            {t(`agents.status.${run.status}`, { defaultValue: run.status })}
          </span>
          <span className="text-xs text-content-tertiary">
            {t('agents.iterations', { defaultValue: 'Iterations' })}: {run.iterations} ·{' '}
            {t('agents.tokens', { defaultValue: 'Tokens' })}: {run.total_tokens}
          </span>
        </div>
        {failureLabel && (
          <span className="text-right text-xs font-medium text-semantic-error">{failureLabel}</span>
        )}
      </header>

      {run.failure_reason === 'no_llm' && (
        <Link
          to="/settings?tab=ai"
          className="inline-flex items-center gap-1.5 self-start rounded-md bg-semantic-warning px-3 py-1.5 text-xs font-semibold text-content-inverse hover:opacity-90"
        >
          <SettingsIcon className="h-3.5 w-3.5" />
          {t('agents.open_ai_settings', { defaultValue: 'Open AI settings' })}
        </Link>
      )}

      {/* Steps timeline */}
      <ol className="relative">
        {steps.length === 0 && run.status === 'running' && (
          <li className="flex items-center gap-2 text-sm text-content-secondary">
            <Loader2 className="h-4 w-4 animate-spin text-oe-blue" />
            {t('agents.waiting', { defaultValue: 'Thinking through your request…' })}
          </li>
        )}
        {steps.map((step, i) => (
          <StepRow key={step.id} step={step} isLast={i === steps.length - 1} />
        ))}
      </ol>

      {/* Final output */}
      {run.final_output && <FinalOutput text={run.final_output} />}

      {/* Trust & verification — surfaces the agent's structured trust envelope
          (calibrated confidence, rationale, cited sources, what would increase
          confidence) and lets the user record whether the answer turned out
          correct. That verdict feeds the accuracy scoreboard. Renders nothing
          for mechanical agents that carry no envelope. */}
      {run.status === 'completed' && <TrustEnvelopeCard run={run} />}

      {/* Apply affordances — surfaced when the run produced structured BOQ
          position proposals (recovered from its steps by the backend). Never
          auto-applies; the user picks a BOQ and clicks Apply (architecture
          guide "AI-augmented, human-confirmed"). */}
      {run.status === 'completed' && <ApplyActionButton runId={run.id} />}
    </div>
  );
}

function FinalOutput({ text }: { text: string }): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-semantic-success/30 bg-semantic-success-bg/60 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-semantic-success">
          <Sparkles className="h-3.5 w-3.5" />
          {t('agents.final_output', { defaultValue: 'Final answer (review before applying)' })}
        </div>
        <CopyButton text={text} label={t('agents.copy_answer', { defaultValue: 'Copy answer' })} />
      </div>
      <Markdown text={text} className="text-sm leading-relaxed text-content-primary" />
    </div>
  );
}
