/**
 * Addendum panel for a tender package — mirrors RIB iTWO Tender / Aconex
 * mid-tender clarifications. Lists revisions oldest → newest, exposes a
 * "Publish" action on drafts, and surfaces a bidder ack chip for each
 * record so the buyer can see at a glance who has acknowledged what.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, Megaphone, Plus, Send, CheckCircle2, Clock } from 'lucide-react';
import { Badge, Button, Card, EmptyState, Skeleton } from '@/shared/ui';
import {
  WideModal,
  WideModalField,
  WideModalSection,
} from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import {
  type Addendum,
  createAddendum,
  listAddenda,
  publishAddendum,
} from './api';

interface Props {
  packageId: string;
}

function formatDate(value: string | null): string {
  if (!value) return '';
  try {
    return new Intl.DateTimeFormat(getIntlLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function CreateAddendumDialog({
  packageId,
  onClose,
  onCreated,
}: {
  packageId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');

  const mutation = useMutation({
    mutationFn: () => createAddendum(packageId, { title, body }),
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({
        type: 'success',
        title: t('tendering.addendum.created', {
          defaultValue: 'Addendum created',
        }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('tendering.addendum.new', 'New Addendum')}
      size="lg"
      busy={mutation.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={mutation.isPending}
          >
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!title.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {t('tendering.addendum.create', 'Create Addendum')}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('tendering.addendum.title_label', 'Title')}
          required
        >
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            placeholder={t('tendering.addendum.title_placeholder', {
              defaultValue: 'e.g. Rebar grade clarification',
            })}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField label={t('tendering.addendum.body_label', 'Body')}>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            placeholder={t('tendering.addendum.body_placeholder', {
              defaultValue:
                'Detailed explanation of the clarification, change, or addition...',
            })}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function AddendumRow({
  addendum,
  onPublish,
  publishing,
}: {
  addendum: Addendum;
  onPublish: () => void;
  publishing: boolean;
}) {
  const { t } = useTranslation();
  const isPublished = addendum.published_at !== null;
  const ackCount = addendum.acknowledged_by.length;

  return (
    <Card padding="none" className="overflow-hidden">
      <div className="flex items-start gap-3 px-4 py-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
          <Megaphone size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-content-primary">
              {t('tendering.addendum.revision', {
                defaultValue: 'Rev {{n}}',
                n: addendum.revision_no,
              })}
            </span>
            <span className="text-sm text-content-primary truncate">
              {addendum.title}
            </span>
            {isPublished ? (
              <Badge variant="success" size="sm">
                {t('tendering.addendum.published', 'Published')}
              </Badge>
            ) : (
              <Badge variant="neutral" size="sm">
                {t('tendering.addendum.draft', 'Draft')}
              </Badge>
            )}
          </div>
          {addendum.body && (
            <p className="mt-1 text-xs text-content-secondary line-clamp-2">
              {addendum.body}
            </p>
          )}
          <div className="mt-2 flex items-center flex-wrap gap-3 text-xs text-content-tertiary">
            {isPublished ? (
              <span className="inline-flex items-center gap-1">
                <Clock size={11} />
                {t('tendering.addendum.published_at', {
                  defaultValue: 'Published {{when}}',
                  when: formatDate(addendum.published_at),
                })}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1">
                <Clock size={11} />
                {formatDate(addendum.created_at)}
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 size={11} />
              {t('tendering.addendum.acks', {
                defaultValue: '{{n}} acknowledgement(s)',
                n: ackCount,
              })}
            </span>
          </div>
          {ackCount > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {addendum.acknowledged_by.map((entry) => (
                <span
                  key={`${entry.bidder_id}-${entry.acknowledged_at}`}
                  className="inline-flex items-center gap-1 rounded-full bg-semantic-success-bg/40 px-2 py-0.5 text-[10px] font-medium text-semantic-success"
                >
                  <CheckCircle2 size={10} />
                  {entry.bidder_id.slice(0, 8)}
                </span>
              ))}
            </div>
          )}
        </div>
        {!isPublished && (
          <Button
            variant="primary"
            size="sm"
            icon={<Send size={13} />}
            loading={publishing}
            onClick={onPublish}
          >
            {t('tendering.addendum.publish', 'Publish')}
          </Button>
        )}
      </div>
    </Card>
  );
}

export function AddendumList({ packageId }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);

  const {
    data: addenda,
    isLoading,
  } = useQuery({
    queryKey: ['tendering-addenda', packageId],
    queryFn: () => listAddenda(packageId),
  });

  const publishMutation = useMutation({
    mutationFn: (addendumId: string) => publishAddendum(addendumId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['tendering-addenda', packageId],
      });
      addToast({
        type: 'success',
        title: t('tendering.addendum.published_toast', {
          defaultValue: 'Addendum published',
        }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  const handleCreated = () => {
    queryClient.invalidateQueries({
      queryKey: ['tendering-addenda', packageId],
    });
  };

  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
          <Megaphone size={16} className="text-oe-blue" />
          {t('tendering.addendum.title', 'Addenda')}
        </h4>
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() => setShowCreate(true)}
        >
          {t('tendering.addendum.new', 'New Addendum')}
        </Button>
      </div>

      {isLoading ? (
        <Skeleton height={80} className="w-full" rounded="md" />
      ) : !addenda || addenda.length === 0 ? (
        <Card className="py-10">
          <EmptyState
            icon={<FileText size={28} strokeWidth={1.5} />}
            title={t('tendering.addendum.empty_title', {
              defaultValue: 'No addenda yet',
            })}
            description={t('tendering.addendum.empty_desc', {
              defaultValue:
                'Mid-tender clarifications go here. Bidders acknowledge each addendum before submitting.',
            })}
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {addenda.map((addendum) => (
            <AddendumRow
              key={addendum.id}
              addendum={addendum}
              onPublish={() => publishMutation.mutate(addendum.id)}
              publishing={
                publishMutation.isPending &&
                publishMutation.variables === addendum.id
              }
            />
          ))}
        </div>
      )}

      {showCreate && (
        <CreateAddendumDialog
          packageId={packageId}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
