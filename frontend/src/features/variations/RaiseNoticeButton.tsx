import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileWarning } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listNoticesBySource,
  raiseNoticeFromEvent,
  type Notice,
  type NoticeRecipient,
  type NoticeSourceType,
} from './api';

interface RaiseNoticeButtonProps {
  projectId: string;
  sourceType: NoticeSourceType;
  /** Optional only for site instructions. */
  sourceId?: string;
  /** Human reference of the event, e.g. an instruction number. */
  sourceRef?: string;
  title?: string;
  description?: string;
  recipientType?: NoticeRecipient;
  compact?: boolean;
}

/**
 * "Raise notice" for a field event. Shows a link to the notice once one
 * exists for the source, otherwise a button that raises it (idempotent).
 */
export function RaiseNoticeButton({
  projectId,
  sourceType,
  sourceId,
  sourceRef,
  title,
  description,
  recipientType = 'owner',
  compact = false,
}: RaiseNoticeButtonProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const lookupKey = ['variations', 'notice-by-source', sourceType, sourceId ?? '', projectId];
  const existingQ = useQuery({
    queryKey: lookupKey,
    queryFn: () => listNoticesBySource(sourceType, sourceId as string, projectId),
    enabled: !!sourceId && !!projectId,
  });

  const raiseMut = useMutation({
    mutationFn: () =>
      raiseNoticeFromEvent({
        project_id: projectId,
        source_type: sourceType,
        ...(sourceId ? { source_id: sourceId } : {}),
        ...(sourceRef ? { source_ref: sourceRef } : {}),
        ...(title ? { title } : {}),
        ...(description ? { description } : {}),
        recipient_type: recipientType,
      }),
    onSuccess: (notice) => {
      qc.setQueryData<Notice[]>(lookupKey, [notice]);
      qc.invalidateQueries({ queryKey: ['variations'] });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('variations.raise_notice_failed', { defaultValue: 'Could not raise the notice' }),
        message: err instanceof Error ? err.message : undefined,
      });
    },
  });

  const notice = existingQ.data?.[0] ?? raiseMut.data;
  if (notice) {
    return (
      <Link
        to={`/variations?tab=notices&highlight=${notice.id}`}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue-subtle/10 hover:underline"
        data-testid="raise-notice-link"
      >
        <FileWarning size={12} />
        {t('variations.notice_link', { defaultValue: 'Notice {{code}}', code: notice.code })}
      </Link>
    );
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      icon={<FileWarning size={compact ? 12 : 14} />}
      onClick={() => raiseMut.mutate()}
      loading={raiseMut.isPending}
      disabled={existingQ.isLoading}
      data-testid="raise-notice-button"
    >
      {t('variations.raise_notice', { defaultValue: 'Raise notice' })}
    </Button>
  );
}
