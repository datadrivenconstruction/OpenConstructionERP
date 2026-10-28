// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The persistent left rail for the AI Estimate Builder wizard. Four
// founder stages (Understand -> Group -> Match -> Assemble), each with a
// human-confirm checkpoint. Pattern borrowed from MatchWizardFlow's
// StageRail. Backward jumps are free; forward jumps respect prerequisites.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, FileSearch, Layers, Search, ClipboardCheck, type LucideIcon } from 'lucide-react';
import type { StageName } from '../api';

export interface StageDef {
  id: StageName;
  index: number;
  titleKey: string;
  titleFallback: string;
  blurbKey: string;
  blurbFallback: string;
  Icon: LucideIcon;
}

export const STAGES: readonly StageDef[] = [
  {
    id: 'source',
    index: 1,
    titleKey: 'aiest.stage.source',
    titleFallback: 'Understand source',
    blurbKey: 'aiest.stage.source_blurb',
    blurbFallback: 'Detect the format and read your data into elements.',
    Icon: FileSearch,
  },
  {
    id: 'grouping',
    index: 2,
    titleKey: 'aiest.stage.groups',
    titleFallback: 'Group quantities',
    blurbKey: 'aiest.stage.groups_blurb',
    blurbFallback: 'Bucket elements into estimable groups with quantities.',
    Icon: Layers,
  },
  {
    id: 'matching',
    index: 3,
    titleKey: 'aiest.stage.matching',
    titleFallback: 'Match rates',
    blurbKey: 'aiest.stage.matching_blurb',
    blurbFallback: 'Find exact catalogue rates with resource breakdowns.',
    Icon: Search,
  },
  {
    id: 'assembly',
    index: 4,
    titleKey: 'aiest.stage.review',
    titleFallback: 'Review & apply',
    blurbKey: 'aiest.stage.review_blurb',
    blurbFallback: 'Check totals and validation, then write the BOQ.',
    Icon: ClipboardCheck,
  },
] as const;

export const STAGE_INDEX: Record<StageName, number> = STAGES.reduce(
  (acc, s) => {
    acc[s.id] = s.index;
    return acc;
  },
  {} as Record<StageName, number>,
);

export function StageRail({
  current,
  furthest,
  onJump,
}: {
  current: StageName;
  furthest: number;
  onJump: (id: StageName) => void;
}) {
  const { t } = useTranslation();
  return (
    <ol
      className="flex flex-col gap-1"
      aria-label={t('aiest.rail.steps', { defaultValue: 'Estimate steps' })}
    >
      {STAGES.map((s) => {
        const isCurrent = s.id === current;
        const isDone = s.index < STAGE_INDEX[current];
        const reachable = s.index <= furthest;
        const Icon = s.Icon;
        return (
          <li key={s.id}>
            <button
              type="button"
              disabled={!reachable}
              onClick={() => reachable && onJump(s.id)}
              className={clsx(
                'group flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors',
                isCurrent
                  ? 'bg-oe-blue/10 ring-1 ring-oe-blue/30'
                  : reachable
                    ? 'hover:bg-surface-secondary'
                    : 'opacity-50 cursor-not-allowed',
              )}
              aria-current={isCurrent ? 'step' : undefined}
            >
              <span
                className={clsx(
                  'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  isCurrent
                    ? 'bg-oe-blue text-white'
                    : isDone
                      ? 'bg-emerald-500 text-white'
                      : 'bg-surface-secondary text-content-secondary',
                )}
              >
                {isDone ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </span>
              <span className="min-w-0">
                <span
                  className={clsx(
                    'block text-sm font-medium',
                    isCurrent ? 'text-oe-blue' : 'text-content-primary',
                  )}
                >
                  {s.index}. {t(s.titleKey, { defaultValue: s.titleFallback })}
                </span>
                <span className="block text-xs text-content-secondary leading-snug">
                  {t(s.blurbKey, { defaultValue: s.blurbFallback })}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
