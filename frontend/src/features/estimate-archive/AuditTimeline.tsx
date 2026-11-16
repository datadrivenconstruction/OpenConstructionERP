// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { History } from 'lucide-react';
import { DateDisplay, EmptyState } from '@/shared/ui';
import type { SealEvent } from './api';

/** Newest first; who (name and organisation, kept for good), when, what. */
export function AuditTimeline({ events }: { events: SealEvent[] }) {
  const { t } = useTranslation();
  if (!events.length) {
    return (
      <EmptyState
        icon={<History size={28} />}
        title={t('estimate_archive.empty.audit', { defaultValue: 'Nothing recorded yet.' })}
      />
    );
  }
  return (
    <ol className="relative space-y-3 border-s border-border-light ps-4" aria-label={t('estimate_archive.tab.audit', { defaultValue: 'Audit' })}>
      {events.map((e) => {
        const ordinal = typeof e.detail?.ordinal === 'string' ? e.detail.ordinal : '';
        const reference = typeof e.detail?.reference === 'string' ? e.detail.reference : '';
        return (
          <li key={e.id} className="relative">
            <span className="absolute -start-[21px] top-1.5 h-2 w-2 rounded-full bg-oe-blue" aria-hidden />
            <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-medium text-content-primary">
                {t(`estimate_archive.event.${e.event_type}`, { defaultValue: e.event_type.replace(/_/g, ' ') })}
              </span>
              {ordinal && <bdi dir="ltr" className="font-mono text-xs">{ordinal}</bdi>}
              {reference && <span className="text-xs text-content-secondary">{reference}</span>}
              {e.event_type === 'hash_check' && (
                <span className={e.detail?.ok ? 'text-xs text-semantic-success' : 'text-xs text-semantic-error'}>
                  {e.detail?.ok
                    ? t('estimate_archive.verified_ok', { defaultValue: 'Matches the sealed record' })
                    : t('estimate_archive.hash.mismatch', { defaultValue: 'Mismatch' })}
                </span>
              )}
            </div>
            <div className="text-xs text-content-tertiary">
              {[e.actor_name, e.actor_organisation].filter(Boolean).join(', ') || '-'} ·{' '}
              <span title={e.created_at}>
                <DateDisplay value={e.created_at} format="datetime" />
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
