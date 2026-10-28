// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Warranty-alerts control for the Asset Register.
 *
 * Scans the project's tracked assets for warranties that are expired or
 * expiring within a lead window (default 90 days) and, on confirm,
 * dispatches one in-app notification per project member through the
 * notifications module. Degrades gracefully: if notifications are
 * unavailable the scan result is still shown and the user is told nothing
 * was sent.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { BellRing, Loader2 } from 'lucide-react';

import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { scanWarrantyAlerts } from './api';

interface WarrantyAlertsButtonProps {
  projectId: string;
  leadDays?: number;
}

export function WarrantyAlertsButton({ projectId, leadDays = 90 }: WarrantyAlertsButtonProps) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);
  const [confirming, setConfirming] = useState(false);

  const mutation = useMutation({
    mutationFn: (dispatch: boolean) => scanWarrantyAlerts(projectId, { leadDays, dispatch }),
    onSuccess: (res, dispatch) => {
      if (!dispatch) {
        // Preview pass: if nothing to alert, say so and skip the dispatch step.
        if (res.total === 0) {
          toast({
            type: 'info',
            title: t('assets.alerts.none', {
              defaultValue: 'No warranties expiring within {{days}} days',
              days: leadDays,
            }),
          });
          setConfirming(false);
          return;
        }
        setConfirming(true);
        toast({
          type: 'warning',
          title: t('assets.alerts.found', {
            defaultValue: '{{count}} assets with warranty issues',
            count: res.total,
          }),
          message: t('assets.alerts.found_hint', {
            defaultValue: 'Click Notify team to alert project members.',
          }),
        });
        return;
      }
      // Dispatch pass.
      setConfirming(false);
      if (res.notifications_unavailable) {
        toast({
          type: 'warning',
          title: t('assets.alerts.notify_unavailable', {
            defaultValue: 'Notifications module is off; nothing was sent',
          }),
        });
        return;
      }
      toast({
        type: 'success',
        title: t('assets.alerts.notified', {
          defaultValue: 'Alerted {{recipients}} team members ({{sent}} notifications)',
          recipients: res.recipients,
          sent: res.notifications_sent,
        }),
      });
    },
    onError: (err: unknown) => {
      toast({
        type: 'error',
        title: t('assets.alerts.failed', { defaultValue: 'Warranty scan failed' }),
        message: err instanceof Error ? err.message : undefined,
      });
    },
  });

  return (
    <div className="flex items-center gap-2">
      <Button
        variant={confirming ? 'primary' : 'secondary'}
        size="sm"
        onClick={() => mutation.mutate(confirming)}
        disabled={mutation.isPending}
        data-testid="warranty-alerts-btn"
        title={t('assets.alerts.tooltip', {
          defaultValue: 'Scan for expiring warranties and notify the team',
        })}
      >
        {mutation.isPending ? (
          <Loader2 size={14} className="mr-1 animate-spin" />
        ) : (
          <BellRing size={14} className="mr-1" />
        )}
        {confirming
          ? t('assets.alerts.notify', { defaultValue: 'Notify team' })
          : t('assets.alerts.scan', { defaultValue: 'Warranty alerts' })}
      </Button>
      {confirming && (
        <button
          type="button"
          className="text-xs text-content-tertiary hover:text-content-primary"
          onClick={() => setConfirming(false)}
        >
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </button>
      )}
    </div>
  );
}

export default WarrantyAlertsButton;
