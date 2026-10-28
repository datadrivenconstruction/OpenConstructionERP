// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Bidder questions and answers: record, answer, publish to all bidders anonymously, promote to an addendum.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { HelpCircle, Megaphone, Plus, Send } from 'lucide-react';
import { Badge, Button, Card, EmptyState, Skeleton } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { formatDateValue } from '@/shared/lib/formatters';
import {
  type Clarification,
  type ClarificationStatus,
  answerClarification,
  createClarification,
  listClarifications,
  listRecipients,
  promoteClarification,
  publishClarification,
} from './api';

const STATUS_VARIANT: Record<ClarificationStatus, BadgeVariant> = {
  open: 'warning',
  answered: 'blue',
  published: 'success',
};

const fieldCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/**
 * One question. The asker is shown to the buyer only while the question is
 * unpublished; the published preview is exactly what every bidder receives.
 */
export function ClarificationCard({
  item,
  askerName,
  busy,
  onAnswer,
  onPublish,
  onPromote,
}: {
  item: Clarification;
  askerName: string;
  busy: boolean;
  onAnswer: (answer: string) => void;
  onPublish: () => void;
  onPromote: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(item.answer ?? '');
  const published = item.status === 'published';
  const statusLabel: Record<ClarificationStatus, string> = {
    open: t('tendering.clarification.status_open', { defaultValue: 'Open' }),
    answered: t('tendering.clarification.status_answered', { defaultValue: 'Answered' }),
    published: t('tendering.clarification.status_published', { defaultValue: 'Published' }),
  };
  return (
    <Card padding="none" className="px-4 py-3" data-testid="clarification-card">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-content-primary">
          {t('tendering.clarification.number', { defaultValue: 'Q{{n}}', n: item.number })}
        </span>
        <Badge variant={STATUS_VARIANT[item.status]} size="sm">
          {statusLabel[item.status]}
        </Badge>
        {item.days_before_closing !== null && item.days_before_closing !== undefined && (
          <span className="text-xs text-content-tertiary" data-testid="clarification-days">
            {t('tendering.clarification.days_before', {
              defaultValue: '{{n}} days before closing',
              n: item.days_before_closing,
            })}
          </span>
        )}
        {!published && askerName && (
          <span className="text-xs text-content-tertiary" data-testid="clarification-asker">
            {t('tendering.clarification.asked_by', { defaultValue: 'Asked by {{name}}', name: askerName })}
          </span>
        )}
        <span className="ml-auto text-xs text-content-tertiary">
          {formatDateValue(item.asked_at, { dateStyle: 'medium' })}
        </span>
      </div>
      <p className="mt-2 whitespace-pre-line text-sm text-content-primary">{item.question}</p>

      {published ? (
        <div className="mt-2 rounded-lg bg-surface-secondary px-3 py-2" data-testid="clarification-published-view">
          <p className="text-[11px] font-medium uppercase tracking-wide text-content-tertiary">
            {t('tendering.clarification.answer', { defaultValue: 'Answer' })}
          </p>
          <p className="whitespace-pre-line text-sm text-content-primary">{item.answer}</p>
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className={fieldCls}
            aria-label={t('tendering.clarification.answer', { defaultValue: 'Answer' })}
            placeholder={t('tendering.clarification.answer_placeholder', {
              defaultValue: 'Write the answer all bidders will receive',
            })}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={!draft.trim() || busy}
              onClick={() => onAnswer(draft.trim())}
            >
              {t('tendering.clarification.save_answer', { defaultValue: 'Save answer' })}
            </Button>
            {item.status === 'answered' && (
              <Button variant="primary" size="sm" icon={<Send size={13} />} disabled={busy} onClick={onPublish}>
                {t('tendering.clarification.publish', { defaultValue: 'Publish to all bidders' })}
              </Button>
            )}
          </div>
        </div>
      )}

      {item.status !== 'open' && !item.addendum_id && (
        <div className="mt-2">
          <Button variant="ghost" size="sm" icon={<Megaphone size={13} />} disabled={busy} onClick={onPromote}>
            {t('tendering.clarification.promote', { defaultValue: 'Turn into addendum' })}
          </Button>
        </div>
      )}
      {item.addendum_id && (
        <p className="mt-2 text-xs text-content-tertiary">
          {t('tendering.clarification.has_addendum', { defaultValue: 'Included in an addendum' })}
        </p>
      )}
    </Card>
  );
}

export function ClarificationsPanel({ packageId }: { packageId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [question, setQuestion] = useState('');
  const [recipientId, setRecipientId] = useState('');

  const { data: items, isLoading } = useQuery({
    queryKey: ['tendering-clarifications', packageId],
    queryFn: () => listClarifications(packageId),
  });
  const { data: recipients } = useQuery({
    queryKey: ['tendering-recipients', packageId],
    queryFn: () => listRecipients(packageId),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['tendering-clarifications', packageId] });
    void queryClient.invalidateQueries({ queryKey: ['tendering-addenda', packageId] });
    void queryClient.invalidateQueries({ queryKey: ['tendering-timeline', packageId] });
  };
  const onError = (error: Error) =>
    addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });

  const create = useMutation({
    mutationFn: () =>
      createClarification(packageId, { question: question.trim(), ...(recipientId ? { recipient_id: recipientId } : {}) }),
    onSuccess: () => {
      setQuestion('');
      setRecipientId('');
      refresh();
    },
    onError,
  });
  const answer = useMutation({
    mutationFn: (v: { id: string; text: string }) => answerClarification(packageId, v.id, v.text),
    onSuccess: refresh,
    onError,
  });
  const publish = useMutation({
    mutationFn: (id: string) => publishClarification(packageId, id),
    onSuccess: () => {
      refresh();
      addToast({
        type: 'success',
        title: t('tendering.clarification.published_toast', { defaultValue: 'Answer published to all bidders' }),
      });
    },
    onError,
  });
  const promote = useMutation({
    mutationFn: (id: string) => promoteClarification(packageId, id),
    onSuccess: () => {
      refresh();
      addToast({
        type: 'success',
        title: t('tendering.clarification.promoted_toast', { defaultValue: 'Draft addendum created' }),
      });
    },
    onError,
  });

  const busy = answer.isPending || publish.isPending || promote.isPending;
  const nameOf = (item: Clarification): string => {
    const firm = recipients?.find((r) => r.id === item.recipient_id)?.company_name;
    return firm || item.asked_by_email || '';
  };

  return (
    <div className="mt-4 space-y-3">
      <h4 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <HelpCircle size={16} className="text-oe-blue" />
        {t('tendering.clarification.title', { defaultValue: 'Bidder questions' })}
      </h4>

      <Card padding="none" className="space-y-2 px-4 py-3">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={2}
          className={fieldCls}
          aria-label={t('tendering.clarification.question', { defaultValue: 'Question' })}
          placeholder={t('tendering.clarification.question_placeholder', { defaultValue: 'Record a question from a bidder' })}
        />
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={recipientId}
            onChange={(e) => setRecipientId(e.target.value)}
            aria-label={t('tendering.clarification.asked_by_label', { defaultValue: 'Asked by' })}
            className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary"
          >
            <option value="">{t('tendering.clarification.any_firm', { defaultValue: 'Any firm' })}</option>
            {(recipients ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.company_name}
              </option>
            ))}
          </select>
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            disabled={!question.trim()}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            {t('tendering.clarification.record', { defaultValue: 'Record question' })}
          </Button>
        </div>
      </Card>

      {isLoading ? (
        <Skeleton height={80} className="w-full" rounded="md" />
      ) : !items || items.length === 0 ? (
        <Card className="py-10">
          <EmptyState
            icon={<HelpCircle size={28} strokeWidth={1.5} />}
            title={t('tendering.clarification.empty_title', { defaultValue: 'No questions yet' })}
            description={t('tendering.clarification.empty_desc', {
              defaultValue: 'Questions from bidders are recorded here, answered, and published to every bidder without naming the asker.',
            })}
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <ClarificationCard
              key={item.id}
              item={item}
              askerName={nameOf(item)}
              busy={busy}
              onAnswer={(text) => answer.mutate({ id: item.id, text })}
              onPublish={() => publish.mutate(item.id)}
              onPromote={() => promote.mutate(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
