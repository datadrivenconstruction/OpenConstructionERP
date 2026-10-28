// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// InitialLoadProgress — overlay shown during the very first file-manager load.
//
// React Query's `isLoading` flag is true only on the first fetch (subsequent
// cache hits resolve synchronously, so this overlay never re-appears on
// navigation). The overlay communicates progress through three named stages
// — Storage → Tree → Ready — so the user understands that something is
// actively happening rather than staring at a blank skeleton.
//
// Dismissal is automatic: as soon as the parent's `treeLoading` and
// `locLoading` both become false, the parent stops rendering this overlay.

import { useTranslation } from 'react-i18next';
import { CheckCircle2, FolderOpen, Loader2 } from 'lucide-react';
import clsx from 'clsx';

interface InitialLoadProgressProps {
  storageDone: boolean;
  treeDone: boolean;
  projectName?: string | null;
}

interface Step {
  id: 'storage' | 'tree' | 'ready';
  labelKey: string;
  defaultLabel: string;
  done: boolean;
}

export function InitialLoadProgress({
  storageDone,
  treeDone,
  projectName,
}: InitialLoadProgressProps) {
  const { t } = useTranslation();

  const steps: Step[] = [
    {
      id: 'storage',
      labelKey: 'files.loading.storage',
      defaultLabel: 'Connecting to project storage',
      done: storageDone,
    },
    {
      id: 'tree',
      labelKey: 'files.loading.tree',
      defaultLabel: 'Reading folder structure',
      done: treeDone,
    },
    {
      id: 'ready',
      labelKey: 'files.loading.ready',
      defaultLabel: 'Indexing files & permissions',
      done: storageDone && treeDone,
    },
  ];

  const doneCount = steps.filter((s) => s.done).length;
  const pct = Math.round((doneCount / steps.length) * 100);
  const currentStep = steps.find((s) => !s.done) ?? steps[steps.length - 1];

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface-secondary/70 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md mx-4 rounded-xl border border-border-light bg-surface-elevated p-6 shadow-2xl animate-card-in">
        {/* Header */}
        <div className="flex items-center gap-3 mb-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
            <FolderOpen size={20} />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-content-primary leading-tight">
              {t('files.loading.title', { defaultValue: 'Preparing your file manager' })}
            </h2>
            {projectName ? (
              <p className="text-xs text-content-tertiary truncate mt-0.5" title={projectName}>
                {projectName}
              </p>
            ) : (
              <p className="text-xs text-content-tertiary mt-0.5">
                {t('files.loading.subtitle', {
                  defaultValue: 'Gathering documents, BIM models, drawings and photos…',
                })}
              </p>
            )}
          </div>
        </div>

        {/* Progress bar — animated width transition (500ms) on each step. */}
        <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary mb-1.5">
          <div
            className="h-full rounded-full bg-oe-blue transition-[width] duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-2xs text-content-tertiary mb-4 tabular-nums">
          <span>
            {t('files.loading.step_of', {
              defaultValue: 'Step {{n}} of {{total}}',
              n: Math.min(doneCount + 1, steps.length),
              total: steps.length,
            })}
          </span>
          <span>{pct}%</span>
        </div>

        {/* Step list */}
        <ul className="space-y-2">
          {steps.map((step) => {
            const isCurrent = !step.done && currentStep?.id === step.id;
            return (
              <li key={step.id} className="flex items-center gap-2.5 text-sm">
                {step.done ? (
                  <CheckCircle2 size={16} className="text-semantic-success shrink-0" />
                ) : isCurrent ? (
                  <Loader2 size={16} className="text-oe-blue shrink-0 animate-spin" />
                ) : (
                  <div className="h-4 w-4 rounded-full border border-border shrink-0" />
                )}
                <span
                  className={clsx(
                    'truncate',
                    step.done
                      ? 'text-content-secondary'
                      : isCurrent
                        ? 'text-content-primary font-medium'
                        : 'text-content-tertiary',
                  )}
                >
                  {t(step.labelKey, { defaultValue: step.defaultLabel })}
                </span>
              </li>
            );
          })}
        </ul>

        {/* Hint — context for what's happening behind the scenes. */}
        <p className="mt-5 text-2xs text-content-quaternary text-center leading-snug">
          {t('files.loading.hint', {
            defaultValue:
              'This usually takes a few seconds. Larger projects with many BIM models can take longer.',
          })}
        </p>
      </div>
    </div>
  );
}
