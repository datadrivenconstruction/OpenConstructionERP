// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Tender timeline: issue, question cut-off, addenda, deadline moves and closing, plus the jurisdiction rules as data.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { CalendarClock, Scale } from 'lucide-react';
import { Card, Skeleton } from '@/shared/ui';
import { formatDateValue } from '@/shared/lib/formatters';
import { getTenderTimeline, type TenderRules, type TenderTimelineEvent } from './api';

const KIND_LABEL: Record<TenderTimelineEvent['kind'], [string, string]> = {
  issued: ['tendering.timeline.issued', 'Issued'],
  questions_closed: ['tendering.timeline.questions_closed', 'Questions close'],
  addendum: ['tendering.timeline.addendum', 'Addendum'],
  deadline_extended: ['tendering.timeline.deadline_extended', 'Deadline moved'],
  closing: ['tendering.timeline.closing', 'Closing'],
};

export function TimelineView({ events, rules }: { events: TenderTimelineEvent[]; rules: TenderRules | null }) {
  const { t } = useTranslation();
  const ruleRows: Array<[string, string, number | null]> = rules
    ? [
        ['tendering.timeline.rule_questions', 'Questions close (days before closing)', rules.questions_close_days_before_closing],
        ['tendering.timeline.rule_answers', 'Answers due (days before closing)', rules.answer_min_days_before_closing],
        ['tendering.timeline.rule_addenda', 'Addenda due (days before closing)', rules.addendum_min_days_before_closing],
        ['tendering.timeline.rule_validity', 'Bid validity (days)', rules.bid_validity_days],
      ]
    : [];
  return (
    <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Card padding="none" className="px-4 py-3">
        <h5 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          <CalendarClock size={13} />
          {t('tendering.timeline.title', { defaultValue: 'Tender timeline' })}
        </h5>
        <ol className="space-y-2" data-testid="tender-timeline">
          {events.map((ev, i) => {
            const [key, fallback] = KIND_LABEL[ev.kind] ?? KIND_LABEL.addendum;
            return (
              <li
                key={`${ev.kind}-${ev.ref_id ?? i}`}
                data-testid="timeline-event"
                data-past={ev.past ? 'true' : 'false'}
                className={`flex items-start gap-3 text-sm ${ev.past ? 'text-content-primary' : 'text-content-tertiary'}`}
              >
                <span
                  className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                    ev.past ? 'bg-oe-blue' : 'border border-content-tertiary bg-transparent'
                  }`}
                />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{t(key, { defaultValue: fallback })}</span>
                  {ev.label && <span className="ml-2 text-content-secondary">{ev.label}</span>}
                </span>
                <span className="shrink-0 text-xs tabular-nums">{formatDateValue(ev.at, { dateStyle: 'medium' })}</span>
              </li>
            );
          })}
        </ol>
      </Card>
      {rules && (
        <Card padding="none" className="px-4 py-3" data-testid="tender-rules">
          <h5 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            <Scale size={13} />
            {t('tendering.timeline.rules', { defaultValue: 'Jurisdiction rules' })}
          </h5>
          <p className="text-sm font-medium text-content-primary">{rules.label}</p>
          <dl className="mt-2 space-y-1 text-xs text-content-secondary">
            {ruleRows
              .filter(([, , days]) => days !== null && days !== undefined)
              .map(([key, fallback, days]) => (
                <div key={key} className="flex justify-between gap-2">
                  <dt>{t(key, { defaultValue: fallback })}</dt>
                  <dd className="font-medium tabular-nums text-content-primary">{days}</dd>
                </div>
              ))}
          </dl>
          {(rules.source || rules.statute_reference) && (
            <p className="mt-2 text-[11px] text-content-tertiary">
              {[rules.source, rules.statute_reference].filter(Boolean).join(' · ')}
            </p>
          )}
          {rules.confidence !== '' && rules.confidence != null && (
            <p className="text-[11px] text-content-tertiary">
              {t('tendering.timeline.confidence', {
                defaultValue: 'Confidence: {{value}}',
                value: String(rules.confidence),
              })}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

export function TenderTimeline({ packageId }: { packageId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['tendering-timeline', packageId],
    queryFn: () => getTenderTimeline(packageId),
  });
  if (isLoading) return <Skeleton height={80} className="w-full" rounded="md" />;
  if (!data || data.events.length === 0) return null;
  return <TimelineView events={data.events} rules={data.rules} />;
}
