// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The legal values of the concept's procurement profile (thresholds,
// deadlines, standstill, signature level) and whether this company has
// checked each one on its source. Unconfirmed and expired values only warn;
// confirming one records who checked it and where.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Scale } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtList } from '@/shared/lib/formatters';
import { fmtDate } from '@/shared/lib/formatters';

import {
  confirmProfileValue,
  procurementErrorCode,
  revokeProfileValue,
  type ProfileValueRow,
  type ProfileValueStatus,
} from './api';
import { useProfileValues } from './hooks';
import { FIELD_CLASS, ReasonedButton, RefusalBox, ToneBadge } from './ProcurementBits';

const STATUS_TONE: Record<ProfileValueStatus, 'success' | 'warning' | 'error'> = {
  confirmed: 'success',
  unconfirmed: 'warning',
  stale: 'error',
};

function shown(v: unknown): string {
  if (Array.isArray(v)) return fmtList(v.map(String));
  if (v === null || v === undefined) return '';
  return String(v);
}

export function ProfileValuesPanel({ jurisdiction }: { jurisdiction: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useProfileValues(jurisdiction);
  const [open, setOpen] = useState<string | null>(null);
  const [source, setSource] = useState('');
  const [note, setNote] = useState('');

  const refresh = () => qc.invalidateQueries({ queryKey: ['procurement-concept'] });
  const confirm = useMutation({
    mutationFn: (row: ProfileValueRow) =>
      confirmProfileValue(jurisdiction, { path: row.path, value_hash: row.value_hash, source_checked: source, note }),
    onSuccess: () => {
      setOpen(null);
      refresh();
    },
  });
  const revoke = useMutation({ mutationFn: (id: string) => revokeProfileValue(id), onSuccess: refresh });

  const statusLabel: Record<ProfileValueStatus, string> = {
    confirmed: t('procurement_concept.ui.profile.status_confirmed', { defaultValue: 'Confirmed' }),
    unconfirmed: t('procurement_concept.ui.profile.status_unconfirmed', { defaultValue: 'Not confirmed' }),
    stale: t('procurement_concept.ui.profile.status_stale', { defaultValue: 'Expired' }),
  };

  if (q.isLoading) return null;
  if (q.isError && procurementErrorCode(q.error) === 'profile_not_found') {
    return (
      <EmptyState
        icon={<Scale size={28} />}
        title={t('procurement_concept.ui.profile.none_title', { defaultValue: 'No legal profile for this jurisdiction yet' })}
        description={t('procurement_concept.ui.profile.none_body', {
          defaultValue: 'The procedure test uses the rule catalogue only. A profile with sourced values comes with a country data update.',
        })}
      />
    );
  }
  if (q.isError) return <RefusalBox error={q.error} />;
  const data = q.data;
  if (!data) return null;
  const verdict = data.can.confirm.allowed ? null : (data.can.confirm.reason ?? 'permission_denied');

  return (
    <div className="space-y-3" data-testid="profile-values">
      <p className="text-sm text-content-secondary">
        {t('procurement_concept.ui.profile.intro', {
          defaultValue:
            'These values come with the platform and are not checked for you. Check each one on its source and confirm it for your company. Until then they only warn and never block.',
        })}
      </p>
      <p className="text-xs text-content-tertiary">
        {t('procurement_concept.ui.profile.chain', { defaultValue: 'Applies in order: {{chain}}', chain: data.chain.join(' > ') })}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-content-tertiary">
              <th className="py-1 pr-3">{t('procurement_concept.ui.profile.col_value', { defaultValue: 'Value' })}</th>
              <th className="py-1 pr-3">{t('procurement_concept.ui.profile.col_valid', { defaultValue: 'Valid' })}</th>
              <th className="py-1 pr-3">{t('procurement_concept.ui.profile.col_status', { defaultValue: 'Status' })}</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {data.values.map((row) => (
              <tr key={row.path} className="border-t border-border-light align-top" data-testid="profile-value-row">
                <td className="py-2 pr-3">
                  <div className="font-mono text-xs text-content-tertiary">
                    {row.origin} {row.path}
                  </div>
                  <div className="text-content-primary">
                    {shown(row.value)} {row.unit ?? ''}
                  </div>
                  {row.source_url && (
                    <a className="inline-flex items-center gap-1 text-xs text-oe-blue" href={row.source_url} target="_blank" rel="noreferrer">
                      <ExternalLink size={12} />
                      {t('procurement_concept.ui.profile.source', { defaultValue: 'Source' })}
                    </a>
                  )}
                </td>
                <td className="py-2 pr-3 whitespace-nowrap">
                  {row.effective_from ? fmtDate(row.effective_from) : ''}
                  {row.effective_to ? ` .. ${fmtDate(row.effective_to)}` : ''}
                </td>
                <td className="py-2 pr-3">
                  <ToneBadge tone={STATUS_TONE[row.status]}>{statusLabel[row.status]}</ToneBadge>
                </td>
                <td className="py-2">
                  {row.confirmation ? (
                    <ReasonedButton quiet size="sm" variant="ghost" verdict={verdict} onClick={() => revoke.mutate(row.confirmation!.id)}>
                      {t('procurement_concept.ui.profile.revoke', { defaultValue: 'Revoke' })}
                    </ReasonedButton>
                  ) : row.status === 'unconfirmed' && open !== row.path ? (
                    <ReasonedButton
                      quiet
                      size="sm"
                      variant="secondary"
                      verdict={verdict}
                      onClick={() => {
                        setOpen(row.path);
                        setSource(row.source_url ?? '');
                        setNote('');
                      }}
                    >
                      {t('procurement_concept.ui.profile.confirm', { defaultValue: 'Confirm' })}
                    </ReasonedButton>
                  ) : null}
                  {open === row.path && (
                    <div className="mt-1 flex flex-col gap-1 min-w-[16rem]">
                      <input
                        className={FIELD_CLASS}
                        value={source}
                        onChange={(e) => setSource(e.target.value)}
                        aria-label={t('procurement_concept.ui.profile.source_checked', { defaultValue: 'Where you checked it' })}
                        placeholder={t('procurement_concept.ui.profile.source_checked', { defaultValue: 'Where you checked it' })}
                      />
                      <input
                        className={FIELD_CLASS}
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        aria-label={t('procurement_concept.ui.profile.note', { defaultValue: 'Note' })}
                        placeholder={t('procurement_concept.ui.profile.note', { defaultValue: 'Note' })}
                      />
                      <div className="flex gap-2">
                        <Button size="sm" disabled={source.trim().length < 5 || confirm.isPending} onClick={() => confirm.mutate(row)}>
                          {t('procurement_concept.ui.profile.confirm_checked', { defaultValue: 'Confirm as checked' })}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>
                          {t('procurement_concept.ui.profile.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                      <RefusalBox error={confirm.error} />
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <RefusalBox error={revoke.error} />
    </div>
  );
}
