// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Notifications" card in Settings > General. The per-event, per-channel
 * routing already lives on the Notifications page (Preferences tab); this card
 * is the way to it from Settings, so there is one place to change it.
 */
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Bell } from 'lucide-react';
import { Card, CardHeader, CardContent } from '@/shared/ui';

export function NotificationChannelsCard() {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader
        title={t('settings.notify_title', { defaultValue: 'Notifications' })}
        subtitle={t('settings.notify_subtitle', {
          defaultValue: 'Choose, for each kind of event, whether it reaches you in the app, by email or through a webhook.',
        })}
      />
      <CardContent>
        <Link
          to="/notifications?tab=preferences"
          className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-content-primary hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
        >
          <Bell size={14} aria-hidden />
          {t('settings.notify_open', { defaultValue: 'Set notification channels' })}
        </Link>
      </CardContent>
    </Card>
  );
}
