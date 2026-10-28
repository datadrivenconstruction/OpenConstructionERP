// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Whether the permits allow the next step: starting on site, handing over,
// and whether the condition register is complete. Below that, what the
// validation rules found in the permit data.

import { useTranslation } from 'react-i18next';
import { CheckCircle2, CircleAlert, CircleX } from 'lucide-react';

import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';

import type { Finding, Readiness, ReadinessGate, ReadinessItem } from './api';
import { refusalText } from './hooks';
import { READINESS_ITEM, READINESS_STATUS, vocab, type KeyText, type TFn } from './labels';
import { READINESS_TONE, ToneBadge, dateText } from './PermitBits';

export const READINESS_GATE: Record<ReadinessGate, KeyText> = {
  start: ['permits.ui.gate.start', 'Start of works'],
  handover: ['permits.ui.gate.handover', 'Handover and occupation'],
  roadmap: ['permits.ui.gate.roadmap', 'Permits for the next phase'],
  register: ['permits.ui.gate.register', 'Condition register'],
};

export const READINESS_GATE_HINT: Record<ReadinessGate, KeyText> = {
  start: ['permits.ui.gate_hint.start', 'Every permit needed to start is in force and nothing due before start is open.'],
  handover: ['permits.ui.gate_hint.handover', 'Occupation is permitted and nothing due before occupation is open.'],
  roadmap: ['permits.ui.gate_hint.roadmap', 'Every permit the next phase needs is submitted or granted.'],
  register: ['permits.ui.gate_hint.register', 'Every condition has an owner and says when it is due.'],
};

const ITEM_ICON = {
  met: <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-semantic-success" aria-hidden />,
  at_risk: <CircleAlert size={15} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />,
  not_met: <CircleX size={15} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />,
  warning: <CircleAlert size={15} className="mt-0.5 shrink-0 text-content-tertiary" aria-hidden />,
};

/** The items that need attention first, then the ones already met. */
export function sortReadinessItems(items: ReadinessItem[]): ReadinessItem[] {
  const rank = { not_met: 0, at_risk: 1, warning: 2, met: 3 };
  return [...items].sort((a, b) => rank[a.state] - rank[b.state]);
}

export function ReadinessCard({ gate, readiness }: { gate: ReadinessGate; readiness: Readiness }) {
  const { t } = useTranslation();
  const items = sortReadinessItems(readiness.items);
  return (
    <section className="space-y-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid={`readiness-${gate}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-content-primary">{vocab(t, READINESS_GATE, gate)}</h3>
        <ToneBadge tone={READINESS_TONE[readiness.status]} testId={`readiness-${gate}-status`}>
          {vocab(t, READINESS_STATUS, readiness.status)}
        </ToneBadge>
      </div>
      <p className="text-xs text-content-tertiary">{vocab(t, READINESS_GATE_HINT, gate)}</p>
      {readiness.needed_from && (
        <p className="text-xs text-content-secondary" data-testid={`readiness-${gate}-date`}>
          {t('permits.ui.readiness.checked_for', {
            defaultValue: 'Checked for {{date}}. A permit needed only after that day is listed as a note and does not block.',
            date: dateText(readiness.needed_from),
          })}
        </p>
      )}
      {items.length === 0 ? (
        <p className="text-sm text-content-secondary">
          {t('permits.ui.readiness.nothing', { defaultValue: 'Nothing stands in the way.' })}
        </p>
      ) : (
        <ul className="space-y-1 text-sm text-content-primary">
          {items.map((item, idx) => (
            <li key={`${item.code}-${item.ref ?? idx}`} className="flex items-start gap-2" data-state={item.state}>
              {ITEM_ICON[item.state]}
              {item.code === 'permit_due_later' && item.title && item.needed_by
                ? vocab(t, READINESS_ITEM, 'permit_due_later_dated', { title: item.title, date: dateText(item.needed_by) })
                : vocab(t, READINESS_ITEM, item.code, { detail: item.detail })}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface Loaded<T> {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
}

export interface ChecksPanelProps {
  readiness: Record<'start' | 'handover' | 'register', Loaded<Readiness>>;
  validation: Loaded<Finding[]>;
}

export function ChecksPanel({ readiness, validation }: ChecksPanelProps) {
  const { t } = useTranslation();
  const gates = ['start', 'handover', 'register'] as const;
  const failed = (validation.data ?? []).filter((f) => !f.passed);

  return (
    <div className="space-y-5" data-testid="checks-panel">
      <div className="grid gap-3 lg:grid-cols-3">
        {gates.map((gate) => {
          const q = readiness[gate];
          if (q.isLoading) return <SkeletonTable key={gate} rows={3} columns={1} />;
          if (q.isError || !q.data) {
            return (
              <ErrorState
                key={gate}
                title={t('permits.ui.readiness.load_failed', { defaultValue: 'Readiness could not be loaded' })}
                hint={refusalText(t as TFn, q.error)}
                onRetry={() => q.refetch()}
              />
            );
          }
          return <ReadinessCard key={gate} gate={gate} readiness={q.data} />;
        })}
      </div>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-content-primary">{t('permits.ui.validation.title', { defaultValue: 'Data checks' })}</h3>
        {validation.isLoading ? (
          <SkeletonTable rows={3} columns={2} />
        ) : validation.isError ? (
          <ErrorState
            title={t('permits.ui.validation.load_failed', { defaultValue: 'The data checks could not be run' })}
            hint={refusalText(t as TFn, validation.error)}
            onRetry={() => validation.refetch()}
          />
        ) : failed.length === 0 ? (
          <p className="flex items-center gap-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-4 text-sm text-content-secondary" data-testid="validation-clean">
            <CheckCircle2 size={16} className="text-semantic-success" aria-hidden />
            {t('permits.ui.validation.clean', { defaultValue: 'Every check on the permit data passes.' })}
          </p>
        ) : (
          <ul className="space-y-1.5" data-testid="validation-list">
            {failed.map((f, idx) => (
              <li key={`${f.rule_id}-${f.element_ref ?? idx}`} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3 text-sm">
                <span className="flex items-start gap-2 text-content-primary">
                  {f.severity === 'error' ? ITEM_ICON.not_met : ITEM_ICON.at_risk}
                  {f.message}
                </span>
                {f.suggestion && <span className="mt-0.5 block pl-6 text-xs text-content-tertiary">{f.suggestion}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
