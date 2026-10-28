// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Right-side run monitor. Polls GET /runs/{id}/progress and shows three
// things: a per-stage status strip (StageTimeline), the live agent step
// feed (thought / tool_call / observation / answer), and the provider /
// model that is actually running plus any degraded-mode notice. Makes the
// AI reasoning visible and honest - the founder's "the agent understands
// your data" shown step-by-step. A "Full timeline" button opens the
// complete audit drawer.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Brain,
  Wrench,
  Eye,
  MessageSquare,
  AlertCircle,
  CheckCircle2,
  Loader2,
  ListTree,
} from 'lucide-react';
import { Card, DateDisplay } from '@/shared/ui';
import { StageTimeline } from './StageTimeline';
import { DegradedBanner } from './DegradedBanner';
import { AgentTimelineDrawer } from './AgentTimelineDrawer';
import type { ProgressResponse, StepOut, StepRole } from '../api';

const ROLE_META: Record<StepRole, { icon: typeof Brain; tone: string }> = {
  thought: { icon: Brain, tone: 'text-indigo-500' },
  tool_call: { icon: Wrench, tone: 'text-oe-blue' },
  observation: { icon: Eye, tone: 'text-emerald-500' },
  answer: { icon: MessageSquare, tone: 'text-content-primary' },
  error: { icon: AlertCircle, tone: 'text-rose-500' },
  stage_complete: { icon: CheckCircle2, tone: 'text-emerald-500' },
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
    return JSON.stringify(c);
  } catch {
    return '';
  }
}

export function RunMonitor({
  runId,
  progress,
  isPolling,
}: {
  runId: string;
  progress: ProgressResponse | undefined;
  isPolling: boolean;
}) {
  const { t } = useTranslation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const steps = progress?.recent_steps ?? [];
  const provider = progress?.provider;
  const model = progress?.model_used;

  return (
    <div className="space-y-3">
      {/* Per-stage status */}
      <Card padding="sm">
        <div className="mb-2.5 flex items-center gap-2 border-b border-border-light pb-2">
          {isPolling ? (
            <Loader2 className="h-4 w-4 animate-spin text-oe-blue" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          )}
          <h3 className="text-sm font-semibold text-content-primary">
            {t('aiest.monitor.stages_title', { defaultValue: 'Progress' })}
          </h3>
        </div>
        <StageTimeline
          stages={progress?.stages ?? []}
          failureReason={progress?.failure_reason ?? null}
        />
      </Card>

      {progress?.degraded_reason && <DegradedBanner reason={progress.degraded_reason} />}

      {/* Agent activity feed */}
      <Card padding="sm" className="flex flex-col">
        <div className="flex items-center justify-between gap-2 border-b border-border-light pb-2.5">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('aiest.monitor.title', { defaultValue: 'Run activity' })}
            </h3>
          </div>
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-oe-blue hover:underline"
          >
            <ListTree className="h-3.5 w-3.5" />
            {t('aiest.monitor.full_timeline', { defaultValue: 'Full timeline' })}
          </button>
        </div>

        {(provider || model) && (
          <p className="mt-2 text-[11px] text-content-tertiary">
            {t('aiest.monitor.running_on', {
              defaultValue: 'Running on {{model}}',
              model: model || provider,
            })}
          </p>
        )}

        <div className="mt-2.5 max-h-[360px] space-y-2 overflow-y-auto pr-1">
          {steps.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-content-tertiary">
              {t('aiest.monitor.empty', {
                defaultValue: 'Activity appears here as the run progresses.',
              })}
            </p>
          ) : (
            steps.map((step) => {
              const meta = ROLE_META[step.role] ?? ROLE_META.answer;
              const Icon = meta.icon;
              return (
                <div key={step.id} className="flex gap-2.5">
                  <Icon className={clsx('mt-0.5 h-3.5 w-3.5 shrink-0', meta.tone)} />
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-xs leading-snug text-content-secondary">
                      {stepText(step)}
                    </p>
                    <DateDisplay
                      value={step.created_at}
                      format="time"
                      className="text-[10px] text-content-tertiary"
                    />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </Card>

      <AgentTimelineDrawer runId={runId} open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}
