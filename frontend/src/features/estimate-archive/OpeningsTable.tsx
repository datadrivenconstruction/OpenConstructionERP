// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { DoorOpen } from 'lucide-react';
import { Badge, DateDisplay, EmptyState } from '@/shared/ui';
import type { Opening } from './api';

export function OpeningsTable({ rows, showSeal = false }: { rows: Opening[]; showSeal?: boolean }) {
  const { t } = useTranslation();
  if (!rows.length) {
    return (
      <EmptyState
        icon={<DoorOpen size={28} />}
        title={t('estimate_archive.empty.openings', {
          defaultValue: 'No openings. A seal is opened when a change, claim or dispute needs its rates.',
        })}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-xs text-content-tertiary">
            {showSeal && <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.seal', { defaultValue: 'Seal' })}</th>}
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.reason', { defaultValue: 'Reason' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.reference', { defaultValue: 'Reference' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.scope', { defaultValue: 'Scope' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.requested_by', { defaultValue: 'Requested by' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.attendees', { defaultValue: 'Attendees' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.opened', { defaultValue: 'Opened' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.closed', { defaultValue: 'Closed' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.hash_check', { defaultValue: 'Hash check' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.id} className="border-b border-border-light align-top">
              {showSeal && <td className="px-3 py-2 font-medium">{o.seal_label}</td>}
              <td className="px-3 py-2">{t(`estimate_archive.reason.${o.reason}`, { defaultValue: o.reason })}</td>
              <td className="px-3 py-2">{o.reference_label || '-'}</td>
              <td className="px-3 py-2">
                {o.scope === 'full' ? (
                  t('estimate_archive.scope.full', { defaultValue: 'Full' })
                ) : (
                  <bdi dir="ltr" className="font-mono text-xs">{o.scope_ordinals.join(', ')}</bdi>
                )}
              </td>
              <td className="px-3 py-2">{o.requested_by_name || '-'}</td>
              <td className="px-3 py-2 text-xs">
                {o.attendees.map((a) => `${a.name}${a.organisation ? ` (${a.organisation})` : ''}`).join(', ')}
              </td>
              <td className="px-3 py-2"><DateDisplay value={o.opened_at} format="datetime" /></td>
              <td className="px-3 py-2"><DateDisplay value={o.closed_at} format="datetime" /></td>
              <td className="px-3 py-2">
                {o.hash_check ? (
                  <Badge variant={o.hash_check === 'ok' ? 'success' : 'error'} size="sm">
                    {o.hash_check === 'ok'
                      ? t('estimate_archive.hash.ok', { defaultValue: 'OK' })
                      : t('estimate_archive.hash.mismatch', { defaultValue: 'Mismatch' })}
                  </Badge>
                ) : (
                  <Badge variant="warning" size="sm">
                    {t(`estimate_archive.opening_status.${o.status}`, { defaultValue: o.status })}
                  </Badge>
                )}
                {o.findings.map((f) => (
                  <p key={f.rule_id} className="mt-1 text-xs text-semantic-warning">{f.message}</p>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
