// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Request an opening: reason, reference, scope and who attends. Where the
 * market expects both parties, a counterparty attendee or a typed reason is needed.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { Button, WideModal, WideModalField, WideModalSection } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { OPENING_REASONS, archiveApi, type Attendee, type OpeningCreate, type OpeningReason } from './api';

const blankAttendee = (side: Attendee['side']): Attendee => ({ name: '', organisation: '', role: '', side });

export function OpeningModal({
  sealId,
  requireBothParties,
  initialOrdinals = [],
  initialReference = '',
  onClose,
}: {
  sealId: string;
  requireBothParties: boolean;
  initialOrdinals?: string[];
  initialReference?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [form, setForm] = useState<OpeningCreate>({
    reason: 'variation',
    reference_label: initialReference,
    scope: initialOrdinals.length ? 'positions' : 'full',
    scope_ordinals: initialOrdinals,
    attendees: [blankAttendee('internal'), blankAttendee('counterparty')],
    one_party_reason: '',
  });
  const [ordinalsText, setOrdinalsText] = useState(initialOrdinals.join(', '));
  const attendees = form.attendees.filter((a) => a.name.trim());
  const hasCounterparty = attendees.some((a) => a.side === 'counterparty');
  const needsReason = requireBothParties && !hasCounterparty;
  const valid =
    form.reference_label.trim() !== '' &&
    attendees.length > 0 &&
    (!needsReason || form.one_party_reason.trim() !== '') &&
    (form.scope === 'full' || form.scope_ordinals.length > 0);

  const save = useMutation({
    mutationFn: () => archiveApi.requestOpening(sealId, { ...form, attendees }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['estimate-archive'] });
      onClose();
    },
  });
  const setAttendee = (i: number, patch: Partial<Attendee>) =>
    setForm((f) => ({ ...f, attendees: f.attendees.map((a, j) => (j === i ? { ...a, ...patch } : a)) }));

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      busy={save.isPending}
      title={t('estimate_archive.request_opening', { defaultValue: 'Request opening' })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" disabled={!valid} onClick={() => save.mutate()}>
            {t('estimate_archive.request_opening', { defaultValue: 'Request opening' })}
          </Button>
        </div>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('estimate_archive.col.reason', { defaultValue: 'Reason' })} required>
          <select
            className="oe-input"
            value={form.reason}
            onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value as OpeningReason }))}
          >
            {OPENING_REASONS.map((r) => (
              <option key={r} value={r}>
                {t(`estimate_archive.reason.${r}`, { defaultValue: r })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('estimate_archive.col.reference', { defaultValue: 'Reference' })} required>
          <input
            className="oe-input"
            value={form.reference_label}
            placeholder={t('estimate_archive.reference_hint', { defaultValue: 'e.g. variation N-07' })}
            onChange={(e) => setForm((f) => ({ ...f, reference_label: e.target.value }))}
          />
        </WideModalField>
        <WideModalField label={t('estimate_archive.col.scope', { defaultValue: 'Scope' })}>
          <select
            className="oe-input"
            value={form.scope}
            onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value as OpeningCreate['scope'] }))}
          >
            <option value="full">{t('estimate_archive.scope.full', { defaultValue: 'Full' })}</option>
            <option value="positions">{t('estimate_archive.scope.positions', { defaultValue: 'Selected positions' })}</option>
          </select>
        </WideModalField>
        {form.scope === 'positions' && (
          <WideModalField label={t('estimate_archive.scope.ordinals', { defaultValue: 'Positions (comma separated)' })}>
            <input
              dir="ltr"
              className="oe-input font-mono"
              value={ordinalsText}
              onChange={(e) => {
                setOrdinalsText(e.target.value);
                const list = e.target.value.split(',').map((s) => s.trim()).filter(Boolean);
                setForm((f) => ({ ...f, scope_ordinals: list }));
              }}
            />
          </WideModalField>
        )}
      </WideModalSection>
      <WideModalSection title={t('estimate_archive.col.attendees', { defaultValue: 'Attendees' })}>
        <div className="space-y-2">
          {form.attendees.map((a, i) => (
            <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto] items-center gap-2">
              <input
                className="oe-input"
                aria-label={t('estimate_archive.attendee.name', { defaultValue: 'Name' })}
                placeholder={t('estimate_archive.attendee.name', { defaultValue: 'Name' })}
                value={a.name}
                onChange={(e) => setAttendee(i, { name: e.target.value })}
              />
              <input
                className="oe-input"
                aria-label={t('estimate_archive.attendee.organisation', { defaultValue: 'Organisation' })}
                placeholder={t('estimate_archive.attendee.organisation', { defaultValue: 'Organisation' })}
                value={a.organisation}
                onChange={(e) => setAttendee(i, { organisation: e.target.value })}
              />
              <input
                className="oe-input"
                aria-label={t('estimate_archive.attendee.role', { defaultValue: 'Role' })}
                placeholder={t('estimate_archive.attendee.role', { defaultValue: 'Role' })}
                value={a.role}
                onChange={(e) => setAttendee(i, { role: e.target.value })}
              />
              <select
                className="oe-input"
                aria-label={t('estimate_archive.attendee.side', { defaultValue: 'Side' })}
                value={a.side}
                onChange={(e) => setAttendee(i, { side: e.target.value as Attendee['side'] })}
              >
                <option value="internal">{t('estimate_archive.side.internal', { defaultValue: 'Our side' })}</option>
                <option value="counterparty">{t('estimate_archive.side.counterparty', { defaultValue: 'Other party' })}</option>
              </select>
              <button
                type="button"
                className="text-content-tertiary hover:text-semantic-error"
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
                onClick={() => setForm((f) => ({ ...f, attendees: f.attendees.filter((_, j) => j !== i) }))}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setForm((f) => ({ ...f, attendees: [...f.attendees, blankAttendee('counterparty')] }))}
          >
            {t('estimate_archive.attendee.add', { defaultValue: 'Add attendee' })}
          </Button>
        </div>
        {needsReason && (
          <div className="mt-3">
            <WideModalField
              label={t('estimate_archive.one_party_reason', {
                defaultValue: 'The other party is not attending. Record why.',
              })}
              required
            >
              <input
                className="oe-input"
                value={form.one_party_reason}
                onChange={(e) => setForm((f) => ({ ...f, one_party_reason: e.target.value }))}
              />
            </WideModalField>
          </div>
        )}
      </WideModalSection>
      {save.isError && <p className="text-sm text-semantic-error">{getErrorMessage(save.error)}</p>}
    </WideModal>
  );
}
