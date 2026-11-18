// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One parcel: boundary points, rights (data only, no legal advice), the
 * acquisition status and cost, and Send to BOQ for the compensation line.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Skeleton, StatusDot } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import {
  PARCEL_STATUSES,
  RIGHT_KINDS,
  addRight,
  deleteRight,
  getParcel,
  listBoqs,
  listParties,
  sendToBoq,
  updateParcel,
  type ParcelStatus,
  type RightKind,
} from './api';
import { STATUS_VARIANT } from './parcelFormat';
import { fmtFixed } from '@/shared/lib/formatters';

interface Props {
  parcelId: string | null;
  projectId: string;
  idLabel: string;
  onClose: () => void;
}

export function ParcelDrawer({ parcelId, projectId, idLabel, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const detail = useQuery({
    queryKey: ['land-parcels', 'parcel', parcelId, i18n.language],
    queryFn: () => getParcel(parcelId!, i18n.language),
    enabled: !!parcelId,
  });
  const parties = useQuery({ queryKey: ['land-parcels', 'parties', projectId], queryFn: () => listParties(projectId), enabled: !!parcelId });
  const boqs = useQuery({ queryKey: ['land-parcels', 'boqs', projectId], queryFn: () => listBoqs(projectId), enabled: !!parcelId });
  const [cost, setCost] = useState('');
  const [boqId, setBoqId] = useState('');
  const [rightKind, setRightKind] = useState<RightKind>('easement');
  const [rightParty, setRightParty] = useState('');
  const [rightText, setRightText] = useState('');

  useEffect(() => {
    setCost(detail.data?.acquisition_cost ?? '');
  }, [detail.data?.acquisition_cost]);

  const refresh = () => qc.invalidateQueries({ queryKey: ['land-parcels'] });
  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => updateParcel(parcelId!, body, i18n.language),
    onSuccess: refresh,
    onError,
  });
  const right = useMutation({
    mutationFn: () => addRight(parcelId!, { kind: rightKind, party_id: rightParty || null, description: rightText }),
    onSuccess: () => {
      setRightText('');
      refresh();
    },
    onError,
  });
  const dropRight = useMutation({ mutationFn: deleteRight, onSuccess: refresh, onError });
  const send = useMutation({
    mutationFn: () =>
      sendToBoq(parcelId!, {
        boq_id: boqId,
        position_id: detail.data?.boq_position_id ?? null,
        description: t('survey.parcels.boq_line', {
          defaultValue: 'Land acquisition {{parcel}}',
          parcel: detail.data?.parcel_ref ?? '',
        }),
      }),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('survey.parcels.sent', { defaultValue: 'Sent to BOQ as position {{ordinal}}', ordinal: r.ordinal }),
      });
      refresh();
    },
    onError,
  });

  const p = detail.data;
  const statusLabel = (s: ParcelStatus) => t(`survey.parcels.status.${s}`, { defaultValue: s });
  return (
    <SideDrawer
      open={!!parcelId}
      onClose={onClose}
      title={p ? <bdi dir="ltr">{p.parcel_ref}</bdi> : idLabel}
      subtitle={p?.name}
      busy={save.isPending || send.isPending}
    >
      {!p ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="space-y-5 text-sm" data-testid="parcel-drawer">
          <section className="grid grid-cols-2 gap-3">
            <div>
              <div className="oe-label">{t('survey.parcels.col.legal', { defaultValue: 'Legal area' })}</div>
              <QuantityDisplay value={p.legal_area} unit="m²" precision={2} />
            </div>
            <div>
              <div className="oe-label">{t('survey.parcels.col.computed', { defaultValue: 'Computed' })}</div>
              <QuantityDisplay value={p.computed_area} unit="m²" precision={2} />
            </div>
          </section>

          {p.findings.length > 0 && (
            <ul className="space-y-1">
              {p.findings.map((f, i) => (
                <li key={i} className="flex gap-2">
                  <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span>
                  <span className={f.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning'}>{f.message}</span>
                </li>
              ))}
            </ul>
          )}

          <section className="space-y-2">
            <h3 className="font-medium">{t('survey.parcels.acquisition', { defaultValue: 'Acquisition' })}</h3>
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="oe-label">{t('survey.parcels.col.status', { defaultValue: 'Status' })}</span>
                <select
                  className="oe-input w-44"
                  value={p.status}
                  data-testid="parcel-status"
                  onChange={(e) => save.mutate({ status: e.target.value })}
                >
                  {PARCEL_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {statusLabel(s)}
                    </option>
                  ))}
                </select>
              </label>
              <StatusDot variant={STATUS_VARIANT[p.status]} label={statusLabel(p.status)} />
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="oe-label">
                  {t('survey.parcels.col.cost', { defaultValue: 'Cost' })} ({p.currency})
                </span>
                <input
                  className="oe-input w-40 text-right"
                  inputMode="decimal"
                  value={cost}
                  onChange={(e) => setCost(e.target.value)}
                  title={t('survey.parcels.tip.cost', {
                    defaultValue: 'What the project expects to pay for this land, in the project currency.',
                  })}
                />
              </label>
              <Button
                size="sm"
                variant="secondary"
                disabled={cost === (p.acquisition_cost ?? '')}
                onClick={() => save.mutate(cost ? { acquisition_cost: cost } : { clear: ['acquisition_cost'] })}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="oe-label">BOQ</span>
                <select className="oe-input w-56" value={boqId} onChange={(e) => setBoqId(e.target.value)}>
                  <option value="">-</option>
                  {(boqs.data ?? []).map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                size="sm"
                variant="primary"
                disabled={!boqId || !p.acquisition_cost || send.isPending}
                onClick={() => send.mutate()}
                data-testid="parcel-send-boq"
                title={t('survey.parcels.tip.send', {
                  defaultValue: 'Adds the cost as one lump-sum position, or updates the position sent before.',
                })}
              >
                {t('survey.parcels.btn.send_to_boq', { defaultValue: 'Send to BOQ' })}
              </Button>
            </div>
            {p.sent_at && (
              <p className="text-xs text-content-tertiary">
                {t('survey.parcels.sent_on', { defaultValue: 'Last sent {{date}}', date: new Date(p.sent_at).toLocaleDateString(i18n.language) })}{' '}
                <MoneyDisplay amount={p.acquisition_cost} currency={p.currency} />
              </p>
            )}
          </section>

          <section className="space-y-2">
            <h3 className="font-medium">{t('survey.parcels.tab.rights', { defaultValue: 'Parties & rights' })}</h3>
            <p className="text-xs text-content-tertiary">
              {t('survey.parcels.rights_note', { defaultValue: 'Recorded as data from the register. This is not legal advice.' })}
            </p>
            <ul className="space-y-1">
              {p.rights.map((r) => (
                <li key={r.id} className="flex items-center gap-2">
                  <span className="font-medium">{t(`survey.parcels.right.${r.kind}`, { defaultValue: r.kind })}</span>
                  <span className="flex-1 text-content-secondary">
                    {[r.party_name, r.description, r.registry_ref].filter(Boolean).join(' · ')}
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => dropRight.mutate(r.id)}>
                    {t('common.delete', { defaultValue: 'Delete' })}
                  </Button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-end gap-2">
              <select className="oe-input w-36" value={rightKind} onChange={(e) => setRightKind(e.target.value as RightKind)}>
                {RIGHT_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`survey.parcels.right.${k}`, { defaultValue: k })}
                  </option>
                ))}
              </select>
              <select className="oe-input w-40" value={rightParty} onChange={(e) => setRightParty(e.target.value)}>
                <option value="">{t('survey.parcels.party_none', { defaultValue: 'No party' })}</option>
                {(parties.data ?? []).map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
              <input
                className="oe-input flex-1 min-w-[10rem]"
                value={rightText}
                onChange={(e) => setRightText(e.target.value)}
                placeholder={t('survey.parcels.right_desc', { defaultValue: 'Description, e.g. water main, 4 m strip' })}
              />
              <Button size="sm" variant="secondary" onClick={() => right.mutate()} disabled={right.isPending}>
                {t('survey.parcels.btn.add_right', { defaultValue: 'Add right' })}
              </Button>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="font-medium">{t('survey.parcels.points', { defaultValue: 'Boundary points' })}</h3>
            <table className="oe-table w-full text-xs">
              <thead>
                <tr>
                  <th>#</th>
                  <th title={t('survey.parcels.tip.e', { defaultValue: 'Easting in metres, project CRS' })}>E (m)</th>
                  <th title={t('survey.parcels.tip.n', { defaultValue: 'Northing in metres, project CRS' })}>N (m)</th>
                  <th>{t('survey.parcels.col.mark', { defaultValue: 'Mark' })}</th>
                  {isAdvanced && (
                    <th title={t('survey.parcels.tip.accuracy', { defaultValue: 'Stated accuracy of the point, in metres' })}>± m</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {p.points.map((pt) => (
                  <tr key={pt.seq}>
                    <td><bdi dir="ltr">{pt.label}</bdi></td>
                    <td className="text-right font-mono"><bdi dir="ltr">{fmtFixed(pt.e, 3)}</bdi></td>
                    <td className="text-right font-mono"><bdi dir="ltr">{fmtFixed(pt.n, 3)}</bdi></td>
                    <td>{pt.mark ? t(`survey.parcels.mark.${pt.mark}`, { defaultValue: pt.mark }) : ''}</td>
                    {isAdvanced && <td className="text-right">{pt.accuracy_m ?? ''}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </SideDrawer>
  );
}
