// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// At-a-glance strip above the connector list: how many sources are registered,
// how many are enabled, how many have ever synced, and when the last sync ran.
// Everything is derived from the sources already loaded for the list, so it
// adds no request and stays in step with the cards below it.

import { useTranslation } from 'react-i18next';
import { Clock, FolderSync, Power, RefreshCw } from 'lucide-react';

import { StatCard } from '@/shared/ui';
import type { ConnectorSource } from './types';
import { formatAbsolute, formatSyncAgo, mostRecentSync } from './utils';

export function ConnectorsSummary({ sources }: { sources: ConnectorSource[] }) {
  const { t } = useTranslation();

  const total = sources.length;
  const enabled = sources.filter((s) => s.enabled).length;
  const synced = sources.filter((s) => !!s.last_synced_at).length;
  const recentIso = mostRecentSync(sources);
  const ago = formatSyncAgo(recentIso, t);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatCard
        icon={FolderSync}
        size="sm"
        label={t('connectors.stat_connectors', { defaultValue: 'Connectors' })}
        value={total}
      />
      <StatCard
        icon={Power}
        size="sm"
        tone={total > 0 && enabled === total ? 'success' : 'default'}
        tintValue={total > 0 && enabled === total}
        label={t('connectors.stat_enabled', { defaultValue: 'Enabled' })}
        value={`${enabled}/${total}`}
      />
      <StatCard
        icon={RefreshCw}
        size="sm"
        label={t('connectors.stat_synced', { defaultValue: 'Synced' })}
        value={`${synced}/${total}`}
        sub={t('connectors.stat_synced_sub', { defaultValue: 'at least once' })}
      />
      <StatCard
        icon={Clock}
        size="sm"
        label={t('connectors.stat_last_sync', { defaultValue: 'Last sync' })}
        value={ago ?? t('connectors.never', { defaultValue: 'Never' })}
        sub={recentIso ? formatAbsolute(recentIso) : undefined}
      />
    </div>
  );
}
