// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SubscribeFolderButton — pill toggle next to a /files breadcrumb
// that subscribes / unsubscribes the current user to a given file
// kind in the current project. When the user is not yet subscribed
// we POST a new subscription; when they are, we DELETE it.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Bell, BellOff } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import {
  useCreateSubscription,
  useDeleteSubscription,
  useSubscriptions,
} from './hooks';
import type { NotifyEvent } from './types';

interface SubscribeFolderButtonProps {
  projectId: string;
  /** Current file kind being browsed, or ``"*"`` for "all kinds". */
  kind: string;
  /** Subscriber email — pulled from the auth payload by the caller
   *  (we keep email here rather than re-decoding the JWT inside the
   *  button so a single source of truth lives in the auth store). */
  subscriberEmail: string;
  size?: 'sm' | 'md';
}

const DEFAULT_EVENTS: NotifyEvent[] = ['created', 'updated', 'deleted'];

export function SubscribeFolderButton({
  projectId,
  kind,
  subscriberEmail,
  size = 'sm',
}: SubscribeFolderButtonProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useSubscriptions(projectId);
  const createMut = useCreateSubscription(projectId);
  const deleteMut = useDeleteSubscription(projectId);
  const [error, setError] = useState<string | null>(null);

  const existing = useMemo(
    () =>
      data?.items.find(
        (s) =>
          s.project_id === projectId &&
          s.file_kind === kind &&
          s.subscriber_email.toLowerCase() === subscriberEmail.toLowerCase(),
      ) ?? null,
    [data, projectId, kind, subscriberEmail],
  );

  const isSubscribed = Boolean(existing && existing.active);
  const pending = createMut.isPending || deleteMut.isPending;

  const toggle = async () => {
    setError(null);
    try {
      if (isSubscribed && existing) {
        await deleteMut.mutateAsync(existing.id);
      } else if (existing) {
        // Inactive existing row — drop it and create a fresh one so
        // the user gets the default ``notify_on`` set again.
        await deleteMut.mutateAsync(existing.id);
        await createMut.mutateAsync({
          project_id: projectId,
          file_kind: kind,
          subscriber_email: subscriberEmail,
          notify_on: DEFAULT_EVENTS,
        });
      } else {
        await createMut.mutateAsync({
          project_id: projectId,
          file_kind: kind,
          subscriber_email: subscriberEmail,
          notify_on: DEFAULT_EVENTS,
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="inline-flex flex-col items-start gap-0.5">
      <Button
        variant={isSubscribed ? 'secondary' : 'ghost'}
        size={size}
        icon={isSubscribed ? <Bell className="h-3.5 w-3.5" /> : <BellOff className="h-3.5 w-3.5" />}
        onClick={toggle}
        loading={pending || isLoading}
        data-testid="subscribe-folder-button"
        aria-pressed={isSubscribed}
      >
        {isSubscribed
          ? t('files.distribution.subscribed', { defaultValue: 'Subscribed' })
          : t('files.distribution.subscribe', { defaultValue: 'Subscribe' })}
      </Button>
      {error && (
        <span role="alert" className="text-[10px] text-semantic-error">
          {error}
        </span>
      )}
    </div>
  );
}
