// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * AccountingSyncCard - dashboard tile: how many accounting connections exist,
 * how many records failed to sync and are still open (red), and when the last
 * sync ran. Self-hides while loading, on error, and when nothing is connected,
 * so a workspace that does not use the module never sees it.
 */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { KpiStrip } from '@/features/dashboard/KpiStrip';
import { useSyncStatus, type StatusConnection } from './api';

/** Pure: the most recent sync time across connections, or null. */
export function lastSyncOf(connections: Pick<StatusConnection, 'last_sync_at'>[]): string | null {
  let best: string | null = null;
  for (const c of connections) if (c.last_sync_at && (best === null || c.last_sync_at > best)) best = c.last_sync_at;
  return best;
}

export function AccountingSyncCard() {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useSyncStatus();

  if (isLoading || isError || !data || data.connections.length === 0) return null;

  const nf = new Intl.NumberFormat(getNumberLocale());
  const last = lastSyncOf(data.connections);
  return (
    <Card className="h-full" data-testid="accounting-sync-card">
      <CardHeader
        title={t('accountingSync.card_title', { defaultValue: 'Accounting sync' })}
        subtitle={t('accountingSync.card_subtitle', { defaultValue: 'Connections to your books and what failed to sync' })}
        action={
          <Link to="/accounting-sync" className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline">
            {t('accountingSync.card_open', { defaultValue: 'Open accounting sync' })}
            <ArrowRight size={11} />
          </Link>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            { label: t('accountingSync.card_connections', { defaultValue: 'Connections' }), value: nf.format(data.connections.length) },
            {
              label: t('accountingSync.card_failures', { defaultValue: 'Open failures' }),
              value: nf.format(data.open_failures),
              tone: data.open_failures > 0 ? 'text-rose-600' : 'text-emerald-600',
            },
          ]}
        />
        <div className="mt-3 text-xs text-content-tertiary">
          {t('accountingSync.card_last_sync', { defaultValue: 'Last sync' })}:{' '}
          {last ? <DateDisplay value={last} /> : t('accountingSync.card.never', { defaultValue: 'Never synced' })}
        </div>
      </CardContent>
    </Card>
  );
}

export default AccountingSyncCard;
