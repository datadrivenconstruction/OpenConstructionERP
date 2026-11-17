// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Seal an estimate: one screen, defaults filled, checks run on open and on every
 * change. Sealing goes through a confirmation because nothing can change after.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { Button, ConfirmDialog, WideModal, WideModalField, WideModalSection } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { boqApi } from '@/features/boq/api';
import { archiveApi, type BasisKind, type SealCheck, type SealCreate } from './api';

const ICONS = { ok: CheckCircle2, warning: AlertTriangle, error: XCircle, info: Info } as const;
const TONE = {
  ok: 'text-semantic-success',
  warning: 'text-semantic-warning',
  error: 'text-semantic-error',
  info: 'text-content-tertiary',
} as const;

export function SealModal({
  projectId,
  boqId,
  contractId,
  supersedeId,
  onClose,
  onSealed,
}: {
  projectId: string;
  boqId?: string;
  contractId?: string;
  supersedeId?: string;
  onClose: () => void;
  onSealed: (sealId: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const boqs = useQuery({ queryKey: ['boqs', projectId], queryFn: () => boqApi.list(projectId) });
  const [form, setForm] = useState<SealCreate>({
    source_boq_id: boqId ?? '',
    contract_id: contractId ?? null,
    basis_kind: 'award',
    label: '',
    deposit_mode: 'platform',
    request_receipt: false,
  });
  const [reason, setReason] = useState('');
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    if (form.source_boq_id || !boqs.data?.length) return;
    const locked = boqs.data.find((b) => b.is_locked) ?? boqs.data[0];
    if (locked) setForm((f) => ({ ...f, source_boq_id: locked.id }));
  }, [boqs.data, form.source_boq_id]);

  const preview = useQuery({
    queryKey: ['estimate-archive', 'preview', form.source_boq_id, form.contract_id ?? null, form.basis_kind],
    queryFn: () => archiveApi.preview(form),
    enabled: !!form.source_boq_id,
  });
  const p = preview.data;
  useEffect(() => {
    if (p?.policy.require_receipt) setForm((f) => ({ ...f, request_receipt: true }));
  }, [p?.policy.require_receipt]);

  const seal = useMutation({
    mutationFn: () =>
      supersedeId ? archiveApi.supersede(supersedeId, { ...form, reason }) : archiveApi.create(form),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['estimate-archive'] });
      onSealed(created.id);
    },
  });

  const blocking = useMemo(() => (p?.checks ?? []).filter((c) => c.blocking), [p]);
  const canSeal = !!p?.can_seal && (!supersedeId || reason.trim().length >= 3);
  const checkText = (c: SealCheck) => {
    if (c.code === 'TOTAL_OK' && p) {
      return t('estimate_archive.check.total_ok', {
        defaultValue: 'Total {{total}} matches the award value',
        total: formatCurrency(p.seal_total, p.currency || undefined),
      });
    }
    if (c.code === 'MARKUPS_OK' && p) {
      return t('estimate_archive.check.markups_ok', {
        defaultValue: 'Markup stack ({{count}}): {{names}}',
        count: p.markup_names.length,
        names: p.markup_names.join(', '),
      });
    }
    return c.message;
  };

  const title = supersedeId
    ? t('estimate_archive.supersede_title', { defaultValue: 'Seal a correction' })
    : t('estimate_archive.seal_action', { defaultValue: 'Seal an estimate' });

  return (
    <>
      <WideModal
        open
        onClose={onClose}
        title={title}
        size="lg"
        busy={seal.isPending}
        footer={
          <div className="flex items-center justify-end gap-2">
            {!canSeal && blocking.length > 0 && (
              <span id="seal-blocked" className="me-auto text-xs text-semantic-error">
                {checkText(blocking[0]!)}
              </span>
            )}
            <Button variant="secondary" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              disabled={!canSeal}
              aria-describedby={!canSeal && blocking.length ? 'seal-blocked' : undefined}
              onClick={() => setConfirm(true)}
            >
              {t('estimate_archive.seal_confirm', { defaultValue: 'Seal estimate' })}
            </Button>
          </div>
        }
      >
        <WideModalSection columns={2}>
          <WideModalField label={t('estimate_archive.field.estimate', { defaultValue: 'Estimate' })}>
            <select
              className="oe-input"
              value={form.source_boq_id}
              onChange={(e) => setForm((f) => ({ ...f, source_boq_id: e.target.value }))}
            >
              {(boqs.data ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                  {b.is_locked ? ` · ${t('estimate_archive.locked', { defaultValue: 'locked' })}` : ''}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('estimate_archive.col.basis', { defaultValue: 'Basis' })}>
            <select
              className="oe-input"
              value={form.basis_kind}
              onChange={(e) => setForm((f) => ({ ...f, basis_kind: e.target.value as BasisKind }))}
            >
              {(['tender', 'award', 'negotiated'] as BasisKind[]).map((b) => (
                <option key={b} value={b}>
                  {t(`estimate_archive.basis.${b}`, { defaultValue: b })}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('estimate_archive.col.label', { defaultValue: 'Label' })}>
            <input
              className="oe-input"
              value={form.label}
              placeholder={p?.label ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))}
            />
          </WideModalField>
          {supersedeId && (
            <WideModalField label={t('estimate_archive.supersede_reason', { defaultValue: 'Why this correction' })}>
              <input className="oe-input" value={reason} onChange={(e) => setReason(e.target.value)} />
            </WideModalField>
          )}
        </WideModalSection>
        <WideModalSection title={t('estimate_archive.checks_title', { defaultValue: 'Checks before sealing' })}>
          {preview.isError ? (
            <p className="text-sm text-semantic-error">{getErrorMessage(preview.error)}</p>
          ) : (
            <ul role="list" className="space-y-1.5">
              {(p?.checks ?? []).map((c) => {
                const Icon = ICONS[c.status];
                return (
                  <li key={c.code} className="flex items-start gap-2 text-sm">
                    <Icon size={16} className={`mt-0.5 shrink-0 ${TONE[c.status]}`} aria-hidden />
                    <span className="sr-only">{t(`estimate_archive.check_status.${c.status}`, { defaultValue: c.status })}</span>
                    <span>{checkText(c)}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </WideModalSection>
        <WideModalSection columns={2}>
          <fieldset className="space-y-1 text-sm">
            <legend className="mb-1 text-xs font-medium text-content-secondary">
              {t('estimate_archive.deposit_label', { defaultValue: 'Deposit' })}
            </legend>
            {(['platform', 'external'] as const).map((m) => (
              <label key={m} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="deposit"
                  checked={form.deposit_mode === m}
                  onChange={() => setForm((f) => ({ ...f, deposit_mode: m }))}
                />
                {t(`estimate_archive.deposit.${m}`, {
                  defaultValue: m === 'platform' ? 'Kept in the platform' : 'Handed to the client on paper or media',
                })}
              </label>
            ))}
          </fieldset>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.request_receipt}
              disabled={form.deposit_mode === 'external'}
              onChange={(e) => setForm((f) => ({ ...f, request_receipt: e.target.checked }))}
            />
            {t('estimate_archive.ask_receipt', {
              defaultValue: 'Ask the client to acknowledge the fingerprint (signing request)',
            })}
          </label>
        </WideModalSection>
        {seal.isError && <p className="text-sm text-semantic-error">{getErrorMessage(seal.error)}</p>}
      </WideModal>
      <ConfirmDialog
        open={confirm}
        variant="warning"
        title={title}
        message={t('estimate_archive.confirm_body', {
          defaultValue:
            'After sealing nothing in this record can be changed. A correction is a new seal that names this one; both stay.',
        })}
        confirmLabel={t('estimate_archive.seal_confirm', { defaultValue: 'Seal estimate' })}
        loading={seal.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false);
          seal.mutate();
        }}
      />
    </>
  );
}
