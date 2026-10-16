// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RecordPartiesPanel - which companies hold one record of a shared register.
 *
 * Shows the originating party and the parties the record was shared with, and,
 * when the caller may share (an internal member, or a member of the
 * originating company), lets them share it with another party or withdraw a
 * share. On a project with no parties it renders nothing, so the six register
 * screens look exactly as before until someone sets parties up.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, Loader2, Share2, X } from 'lucide-react';
import { Badge, Button, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import {
  SHARE_PERMISSIONS,
  getMyPartyScope,
  getRecordParties,
  listParties,
  revokeRecordShare,
  shareRecord,
  type PartyEntityType,
  type RecordPartyRow,
  type SharePermission,
} from './partiesApi';

interface RecordPartiesPanelProps {
  projectId: string | null | undefined;
  entityType: PartyEntityType;
  entityId: string | null | undefined;
  className?: string;
}

function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { body?: { detail?: string } })?.body?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return err instanceof Error && err.message ? err.message : fallback;
}

export function RecordPartiesPanel({ projectId, entityType, entityId, className }: RecordPartiesPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [partyId, setPartyId] = useState('');
  const [permission, setPermission] = useState<SharePermission>('view');

  const pid = projectId ?? '';
  const eid = entityId ?? '';

  const scopeQuery = useQuery({
    queryKey: ['party-scope', pid],
    queryFn: () => getMyPartyScope(pid),
    enabled: !!pid,
    staleTime: 60_000,
  });
  const hasParties = scopeQuery.data?.has_parties === true;

  const recordKey = ['record-parties', pid, entityType, eid];
  const recordQuery = useQuery({
    queryKey: recordKey,
    queryFn: () => getRecordParties(pid, entityType, eid),
    enabled: !!pid && !!eid && hasParties,
  });
  const partiesQuery = useQuery({
    queryKey: ['parties', pid],
    queryFn: () => listParties(pid),
    enabled: !!pid && hasParties && recordQuery.data?.can_share === true,
  });

  const fail = (err: unknown) =>
    addToast({
      type: 'error',
      title: t('parties.toast_share_error', 'Sharing change refused'),
      message: errorDetail(err, t('parties.toast_share_error', 'Sharing change refused')),
    });

  const shareMutation = useMutation({
    mutationFn: () => shareRecord(pid, entityType, eid, partyId, permission),
    onSuccess: (data) => {
      qc.setQueryData(recordKey, data);
      setPartyId('');
    },
    onError: fail,
  });
  const revokeMutation = useMutation({
    mutationFn: (target: string) => revokeRecordShare(pid, entityType, eid, target),
    onSuccess: () => qc.invalidateQueries({ queryKey: recordKey }),
    onError: fail,
  });

  if (!pid || !eid || !hasParties) return null;
  const data = recordQuery.data;

  const permissionLabel = (p: SharePermission) =>
    p === 'contribute'
      ? t('parties.permission_contribute', 'Can contribute')
      : t('parties.permission_view', 'View only');

  const held = new Set<string>([
    ...(data?.originator ? [data.originator.party_id] : []),
    ...(data?.shares ?? []).map((s) => s.party_id),
  ]);
  const candidates = (partiesQuery.data ?? []).filter((p) => p.is_active && !p.is_host && !held.has(p.id));

  const onRevoke = async (row: RecordPartyRow) => {
    const ok = await confirm({
      title: t('parties.revoke_title', 'Withdraw this share?'),
      message: t('parties.revoke_message', '{{party}} will no longer see this record. The change is written to the audit log.', {
        party: row.party_name,
      }),
      confirmLabel: t('parties.revoke_confirm', 'Withdraw'),
    });
    if (ok) revokeMutation.mutate(row.party_id);
  };

  return (
    <section
      className={className ?? 'rounded-lg border border-border bg-surface-primary p-3'}
      aria-label={t('parties.panel_title', 'Companies with access')}
    >
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Building2 size={14} className="text-oe-blue" />
        {t('parties.panel_title', 'Companies with access')}
      </h3>
      {recordQuery.isLoading ? (
        <Loader2 size={14} className="animate-spin text-content-tertiary" />
      ) : !data ? null : (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-content-secondary">{t('parties.originator', 'Originated by')}</span>
            {data.originator ? (
              <Badge variant="blue">{data.originator.party_name}</Badge>
            ) : (
              <span className="text-content-tertiary">
                {t('parties.originator_internal', 'Internal (visible to internal members only until shared)')}
              </span>
            )}
          </div>
          <div>
            <div className="text-content-secondary">{t('parties.shared_with', 'Shared with')}</div>
            {data.shares.length === 0 ? (
              <div className="text-content-tertiary">{t('parties.shared_with_none', 'No other company')}</div>
            ) : (
              <ul className="mt-1 space-y-1">
                {data.shares.map((row) => (
                  <li key={row.party_id} className="flex items-center gap-2">
                    <span className="text-content-primary">{row.party_name}</span>
                    <Badge variant="neutral" size="sm">
                      {permissionLabel(row.permission)}
                    </Badge>
                    {data.can_share ? (
                      <button
                        type="button"
                        onClick={() => void onRevoke(row)}
                        className="ml-auto text-content-tertiary hover:text-semantic-error"
                        aria-label={t('parties.revoke_aria', 'Withdraw the share with {{party}}', {
                          party: row.party_name,
                        })}
                      >
                        <X size={14} />
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {data.can_share && candidates.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <select
                value={partyId}
                onChange={(e) => setPartyId(e.target.value)}
                className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-sm"
                aria-label={t('parties.share_party', 'Company to share with')}
              >
                <option value="">{t('parties.share_party_placeholder', 'Share with...')}</option>
                {candidates.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <select
                value={permission}
                onChange={(e) => setPermission(e.target.value as SharePermission)}
                className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-sm"
                aria-label={t('parties.share_permission', 'Permission')}
              >
                {SHARE_PERMISSIONS.map((p) => (
                  <option key={p} value={p}>
                    {permissionLabel(p)}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                icon={<Share2 size={14} />}
                disabled={!partyId}
                loading={shareMutation.isPending}
                onClick={() => shareMutation.mutate()}
              >
                {t('parties.share_action', 'Share')}
              </Button>
            </div>
          ) : null}
        </div>
      )}
      <ConfirmDialog {...confirmProps} />
    </section>
  );
}
