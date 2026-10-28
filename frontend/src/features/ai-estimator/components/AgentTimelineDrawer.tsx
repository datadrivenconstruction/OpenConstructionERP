// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Full agent reasoning timeline in a side drawer. The right monitor shows
// only the most-recent steps; this drawer pulls the complete run timeline
// (GET /runs/{id}/steps) so the human can audit every thought, tool call
// and observation the agent made. Human-confirm philosophy requires this
// transparency - nothing the agent did is hidden.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Brain,
  Wrench,
  Eye,
  MessageSquare,
  AlertCircle,
  CheckCircle2,
  Loader2,
} from 'lucide-react';
import { SideDrawer, DateDisplay } from '@/shared/ui';
import { aiEstimatorApi, type StepOut, type StepRole } from '../api';
import { STAGES } from './StageRail';

const ROLE_META: Record<StepRole, { icon: typeof Brain; tone: string; labelKey: string; labelFallback: string }> = {
  thought: { icon: Brain, tone: 'text-indigo-500', labelKey: 'aiest.role.thought', labelFallback: 'Thinking' },
  tool_call: { icon: Wrench, tone: 'text-oe-blue', labelKey: 'aiest.role.tool_call', labelFallback: 'Tool call' },
  observation: { icon: Eye, tone: 'text-emerald-500', labelKey: 'aiest.role.observation', labelFallback: 'Observation' },
  answer: { icon: MessageSquare, tone: 'text-content-primary', labelKey: 'aiest.role.answer', labelFallback: 'Answer' },
  error: { icon: AlertCircle, tone: 'text-rose-500', labelKey: 'aiest.role.error', labelFallback: 'Error' },
  stage_complete: { icon: CheckCircle2, tone: 'text-emerald-500', labelKey: 'aiest.role.stage_complete', labelFallback: 'Stage done' },
};

function stepText(step: StepOut): string {
  const c = step.content;
  if (typeof c === 'string') return c;
  if (c && typeof c === 'object') {
    const o = c as Record<string, unknown>;
    if (typeof o.text === 'string') return o.text;
    if (typeof o.message === 'string') return o.message;
    if (typeof o.tool === 'string') {
      const args = o.args ? ` ${JSON.stringify(o.args)}` : '';
      return `${o.tool}${args}`;
    }
  }
  try {
    return JSON.stringify(c, null, 2);
  } catch {
    return '';
  }
}

export function AgentTimelineDrawer({
  runId,
  open,
  onClose,
}: {
  runId: string;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  const stepsQ = useQuery({
    enabled: open && !!runId,
    queryKey: ['aiest-all-steps', runId],
    queryFn: () => aiEstimatorApi.getSteps(runId, 500),
  });

  const steps = stepsQ.data ?? [];

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      widthClass="max-w-lg"
      title={t('aiest.timeline.full_title', { defaultValue: 'Agent reasoning' })}
      subtitle={t('aiest.timeline.full_subtitle', {
        defaultValue: 'Every step the agent took on this run',
      })}
    >
      <div className="p-4">
        {stepsQ.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-content-tertiary">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('aiest.timeline.loading', { defaultValue: 'Loading the timeline...' })}
          </div>
        ) : stepsQ.isError ? (
          <p className="py-12 text-center text-sm text-rose-600">
            {t('aiest.timeline.error', { defaultValue: 'Could not load the agent timeline.' })}
          </p>
        ) : steps.length === 0 ? (
          <p className="py-12 text-center text-sm text-content-tertiary">
            {t('aiest.timeline.empty', {
              defaultValue: 'No steps recorded yet. They appear here as the run progresses.',
            })}
          </p>
        ) : (
          <ol className="space-y-3">
            {steps.map((step) => {
              const meta = ROLE_META[step.role] ?? ROLE_META.answer;
              const Icon = meta.icon;
              const stageDef = STAGES.find((s) => s.id === step.stage);
              return (
                <li key={step.id} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <Icon className={clsx('h-4 w-4 shrink-0', meta.tone)} />
                    <span className="mt-1 w-px flex-1 bg-border-light" aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1 pb-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={clsx('text-xs font-semibold', meta.tone)}>
                        {t(meta.labelKey, { defaultValue: meta.labelFallback })}
                      </span>
                      {stageDef && (
                        <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-[10px] text-content-tertiary">
                          {t(stageDef.titleKey, { defaultValue: stageDef.titleFallback })}
                        </span>
                      )}
                      <DateDisplay
                        value={step.created_at}
                        format="time"
                        className="text-[10px] text-content-tertiary"
                      />
                      {step.took_ms != null && (
                        <span className="text-[10px] text-content-tertiary tabular-nums">
                          {step.took_ms} ms
                        </span>
                      )}
                    </div>
                    <pre className="mt-1 whitespace-pre-wrap break-words font-sans text-xs leading-snug text-content-secondary">
                      {stepText(step)}
                    </pre>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </SideDrawer>
  );
}
