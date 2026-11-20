// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measured quantity to payment certificate. The user picks which quantity
 * (cut, fill, net, loose cut) and the BOQ line, reads what the open
 * certificate of the contract billing that line would carry, and only then
 * confirms. Shared by volumes and mine survey periods.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ShieldAlert } from 'lucide-react';
import { Button, Card, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtFixed } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  formatM3,
  searchBoqPositions,
  type CertifyInput,
  type MeasuredFinding,
  type MeasuredPreview,
  type QuantityKind,
} from './volumesApi';

export interface CertifyDialogProps {
  open: boolean;
  projectId: string;
  /** Code of the volume or label of the period, shown in the title. */
  source: string;
  /** The quantities on offer with their m3; a kind without a value is not offered. */
  amounts: Partial<Record<QuantityKind, number | null>>;
  initialPositionId?: string | null;
  preview: (body: CertifyInput) => Promise<MeasuredPreview>;
  commit: (body: CertifyInput) => Promise<MeasuredPreview>;
  /** Writes progress only, without touching a certificate (for projects without a subcontract). */
  progressOnly?: (body: CertifyInput) => Promise<unknown>;
  onClose: () => void;
}

const num = (v: string | null | undefined, d = 2) => (v == null || v === '' ? '-' : fmtFixed(Number(v), d));

export function CertifyDialog({ open, projectId, source, amounts, initialPositionId, preview, commit, progressOnly, onClose }: CertifyDialogProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const kinds = (Object.keys(amounts) as QuantityKind[]).filter((k) => amounts[k] != null);
  const [kind, setKind] = useState<QuantityKind>(kinds[0] ?? 'cut');
  const [positionId, setPositionId] = useState(initialPositionId ?? '');
  const [q, setQ] = useState('');
  const body: CertifyInput = { position_id: positionId, quantity: kind };

  const hits = useQuery({
    queryKey: ['volumes', 'boq-positions', projectId, q],
    queryFn: () => searchBoqPositions(projectId, q),
    enabled: open,
  });
  const view = useQuery({
    queryKey: ['certify-preview', source, positionId, kind],
    queryFn: () => preview(body),
    enabled: open && !!positionId,
    retry: false,
  });
  const finish = () => {
    qc.invalidateQueries({ queryKey: ['volumes'] });
    qc.invalidateQueries({ queryKey: ['mine'] });
    qc.invalidateQueries({ queryKey: ['contracts'] });
    onClose();
  };
  const fail = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const send = useMutation({
    mutationFn: () => commit(body),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('certify.done', {
          defaultValue: '{{qty}} {{unit}} added to certificate {{number}}',
          qty: num(r.figures?.period_qty, 3),
          unit: r.unit,
          number: r.claim?.number ?? '',
        }),
      });
      finish();
    },
    onError: fail,
  });
  const progress = useMutation({
    mutationFn: () => progressOnly!(body),
    onSuccess: () => {
      addToast({ type: 'success', title: t('certify.progress_done', { defaultValue: 'Progress recorded against the BOQ line' }) });
      finish();
    },
    onError: fail,
  });

  const p = view.data;
  const findingText = (f: MeasuredFinding) =>
    t(`certify.finding.${f.key || 'other'}`, { defaultValue: f.message, ...f.params });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('certify.title', { defaultValue: 'Add to payment certificate: {{source}}', source })}
      size="lg"
      busy={send.isPending || progress.isPending}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          {progressOnly && (
            <Button
              variant="secondary"
              disabled={!positionId}
              loading={progress.isPending}
              onClick={() => progress.mutate()}
              data-testid="certify-progress-only"
            >
              {t('certify.progress_only', { defaultValue: 'Record progress only' })}
            </Button>
          )}
          <Button
            variant="primary"
            disabled={!p?.can_commit}
            loading={send.isPending}
            onClick={() => send.mutate()}
            data-testid="certify-confirm"
          >
            {t('certify.confirm', { defaultValue: 'Confirm and add to certificate' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-sm">
        <fieldset>
          <legend className="mb-1 font-medium">{t('certify.which_quantity', { defaultValue: 'Which quantity' })}</legend>
          <div className="flex flex-wrap gap-4">
            {kinds.map((k) => (
              <label key={k} className="flex items-center gap-2">
                <input type="radio" name="certify-kind" checked={kind === k} onChange={() => setKind(k)} data-testid={`certify-kind-${k}`} />
                {t(`volumes.quantity.${k}`, { defaultValue: k })}: <bdi dir="ltr">{formatM3(amounts[k], i18n.language)} m³</bdi>
              </label>
            ))}
          </div>
        </fieldset>

        <div>
          <p className="mb-1 font-medium">{t('certify.boq_line', { defaultValue: 'BOQ line' })}</p>
          <input
            className="oe-input w-full"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('volumes.send.search', { defaultValue: 'Search BOQ lines measured in m3' })}
            data-testid="certify-search"
          />
          <div className="mt-1 max-h-40 overflow-y-auto rounded border border-border-light">
            {(hits.data ?? []).length === 0 ? (
              <p className="p-3 text-content-tertiary">{t('volumes.send.none', { defaultValue: 'No BOQ line in m3 matches.' })}</p>
            ) : (
              <ul>
                {(hits.data ?? []).map((h) => (
                  <li key={h.id}>
                    <label className="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-secondary">
                      <input type="radio" name="certify-position" checked={positionId === h.id} onChange={() => setPositionId(h.id)} />
                      <span className="font-mono text-xs">{h.ordinal}</span>
                      <span className="flex-1">{h.description}</span>
                      <bdi dir="ltr" className="text-xs">{h.quantity} {h.unit}</bdi>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {view.isError && <p className="text-semantic-error">{getErrorMessage(view.error)}</p>}
        {p && (
          <Card className="space-y-3 p-3" data-testid="certify-preview">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-content-tertiary">{t('certify.contract', { defaultValue: 'Contract' })}</dt>
              <dd>{p.contract ? `${p.contract.code} ${p.contract.title}` : '-'}</dd>
              <dt className="text-content-tertiary">{t('certify.line', { defaultValue: 'Schedule of works line' })}</dt>
              <dd>
                {p.line ? (
                  <>
                    {p.line.code} {p.line.description}{' '}
                    <bdi dir="ltr" className="text-xs">
                      {num(p.line.quantity, 3)} {p.line.unit} x {num(p.line.unit_rate)}
                    </bdi>
                  </>
                ) : (
                  '-'
                )}
              </dd>
              <dt className="text-content-tertiary">{t('certify.certificate', { defaultValue: 'Certificate' })}</dt>
              <dd data-testid="certify-claim">
                {p.claim ? `${p.claim.number} (${t(`certify.status.${p.claim.status}`, { defaultValue: p.claim.status })})` : '-'}
              </dd>
              <dt className="text-content-tertiary">{t('certify.measured', { defaultValue: 'Measured' })}</dt>
              <dd>
                <bdi dir="ltr">
                  {num(p.quantity, 3)} {p.unit}
                </bdi>{' '}
                <span className="text-content-tertiary">
                  {t('certify.of_boq', {
                    defaultValue: 'of {{qty}} {{unit}} in BOQ {{ordinal}}',
                    qty: num(p.boq_quantity, 3),
                    unit: p.boq_unit,
                    ordinal: p.ordinal,
                  })}
                </span>
              </dd>
            </dl>
            {p.figures && (
              <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="certify-figures">
                <div>
                  <dt className="text-xs text-content-tertiary">{t('certify.percent', { defaultValue: 'Complete to date' })}</dt>
                  <dd className="font-mono">{num(p.figures.percent_to_date)} %</dd>
                </div>
                <div>
                  <dt className="text-xs text-content-tertiary">{t('certify.period_qty', { defaultValue: 'This period' })}</dt>
                  <dd className="font-mono">{num(p.figures.period_qty, 3)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-content-tertiary">{t('certify.period_value', { defaultValue: 'Value this period' })}</dt>
                  <dd className="font-mono" data-testid="certify-period-value">
                    {num(p.figures.period_value)} {p.contract?.currency}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-content-tertiary">{t('certify.cumulative', { defaultValue: 'Cumulative value' })}</dt>
                  <dd className="font-mono">
                    {num(p.figures.cumulative_value)} {p.contract?.currency}
                  </dd>
                </div>
              </dl>
            )}
            {p.figures?.capped && (
              <p className="text-xs text-content-tertiary">
                {t('certify.capped', { defaultValue: 'The line is billed up to its full value, not beyond.' })}
              </p>
            )}
            {p.findings.length > 0 && (
              <ul className="space-y-1" data-testid="certify-findings">
                {p.findings.map((f) => (
                  <li key={f.rule_id} className={`flex items-start gap-2 ${f.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning'}`}>
                    {f.severity === 'error' ? <ShieldAlert size={14} className="mt-0.5" /> : <AlertTriangle size={14} className="mt-0.5" />}
                    <span>
                      <span className="font-mono text-xs">{f.rule_id}</span> {findingText(f)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
      </div>
    </WideModal>
  );
}
