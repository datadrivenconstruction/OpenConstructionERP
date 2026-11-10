// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Small colour-coded pill for tileset/job state.
 *
 * Maps every ``TilesetStatus`` to one of four traffic-light tones used
 * across the rest of the app (green/blue/red/grey). Outputs a Tailwind
 * pill so it composes inside the sidebar cards without extra wrappers.
 */

import { useTranslation } from 'react-i18next';

import type { TilesetStatus } from './types';

interface GeoStatusBadgeProps {
  status: TilesetStatus;
  className?: string;
}

const STATUS_TONE: Record<TilesetStatus, string> = {
  ready:
    'bg-semantic-success-bg text-semantic-success border-semantic-success/30 ' +
    'dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800/60',
  generating:
    'bg-blue-50 text-blue-700 border-blue-200 ' +
    'dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800/60',
  draft:
    'bg-slate-50 text-slate-600 border-slate-200 ' +
    '',
  failed:
    'bg-semantic-error-bg text-semantic-error border-semantic-error/30 ' +
    'dark:bg-red-900/30 dark:text-red-300 dark:border-red-800/60',
  obsolete:
    'bg-semantic-warning-bg text-semantic-warning border-semantic-warning/30 ' +
    'dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800/60',
};

const STATUS_DOT: Record<TilesetStatus, string> = {
  ready: 'bg-semantic-success',
  generating: 'bg-blue-500 animate-pulse',
  draft: 'bg-slate-400',
  failed: 'bg-semantic-error',
  obsolete: 'bg-semantic-warning',
};

export function GeoStatusBadge({ status, className }: GeoStatusBadgeProps) {
  const { t } = useTranslation();
  const labels: Record<TilesetStatus, string> = {
    ready: t('geo_hub.status.ready', { defaultValue: 'Ready' }),
    generating: t('geo_hub.status.generating', { defaultValue: 'Processing' }),
    draft: t('geo_hub.status.draft', { defaultValue: 'Pending' }),
    failed: t('geo_hub.status.failed', { defaultValue: 'Failed' }),
    obsolete: t('geo_hub.status.obsolete', { defaultValue: 'Outdated' }),
  };
  return (
    <span
      className={[
        'inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5',
        'text-2xs font-medium uppercase tracking-wider',
        STATUS_TONE[status],
        className ?? '',
      ].join(' ')}
    >
      <span className={['h-1.5 w-1.5 rounded-full', STATUS_DOT[status]].join(' ')} />
      {labels[status]}
    </span>
  );
}

export default GeoStatusBadge;
