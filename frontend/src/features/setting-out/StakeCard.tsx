// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One stake on a phone (designed for 390 px): design position, large decimal
 * fields for the measured values, an instant Pass/Fail while typing, Save, and
 * on a saved fail a Create NCR draft button. The phone is never the instrument:
 * the values come from the total station or GNSS rover.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, CircleDashed, FileWarning, XCircle } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { createNcrDraft, recordStake, type Stake, type StakeState } from './api';
import { fmtCoord, fmtMm, instantDelta, parseDecimal } from './verdict';

export interface StakeCardProps {
  stake: Stake;
  tolH: number | null;
  tolV: number | null;
  /** Request defaults, sent unless the crew types others under Advanced options. */
  instrument: string;
  controlRef: string;
  canWrite?: boolean;
}

export function VerdictBadge({ state }: { state: StakeState }) {
  const { t } = useTranslation();
  const label = t(`survey.setting_out.status.${state}`, {
    defaultValue: { pass: 'Pass', fail: 'Fail', open: 'Open', no_tolerance: 'No profile, set one' }[state],
  });
  const cls =
    state === 'pass'
      ? 'bg-semantic-success/15 text-semantic-success'
      : state === 'fail'
        ? 'bg-semantic-error/15 text-semantic-error'
        : 'bg-surface-secondary text-content-secondary';
  const Icon = state === 'pass' ? CheckCircle2 : state === 'fail' ? XCircle : CircleDashed;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-sm font-semibold ${cls}`} data-testid="stake-verdict">
      <Icon size={16} aria-hidden />
      {label}
    </span>
  );
}

export function StakeCard({ stake, tolH, tolV, instrument, controlRef, canWrite = true }: StakeCardProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [e, setE] = useState('');
  const [n, setN] = useState('');
  const [z, setZ] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [inst, setInst] = useState(instrument);
  const [ctrl, setCtrl] = useState(controlRef);

  const me = parseDecimal(e);
  const mn = parseDecimal(n);
  const mz = parseDecimal(z);
  const typed = me != null && mn != null;
  const live = typed
    ? instantDelta({ e: stake.design_e, n: stake.design_n, z: stake.design_z }, { e: me, n: mn, z: mz }, tolH, tolV)
    : null;
  const saved = stake.latest;
  const shown = live ?? (saved ? { d_mm: saved.d_mm, dz_mm: saved.dz_mm, verdict: saved.verdict } : null);
  const state: StakeState = shown ? shown.verdict : 'open';

  const refresh = () => qc.invalidateQueries({ queryKey: ['setting-out'] });
  const save = useMutation({
    mutationFn: () =>
      recordStake(stake.id, {
        measured_e: me!,
        measured_n: mn!,
        measured_z: mz,
        instrument: inst,
        control_ref: ctrl,
      }),
    onSuccess: () => {
      setE('');
      setN('');
      setZ('');
      refresh();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const ncr = useMutation({
    mutationFn: () => createNcrDraft(saved!.id, i18n.language),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('survey.setting_out.ncr_created', { defaultValue: 'NCR draft {{number}} created in Quality', number: r.ncr_number }),
      });
      refresh();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const field = (id: string, label: string, tip: string, value: string, set: (v: string) => void, placeholder: string) => (
    <label className="block" htmlFor={id}>
      <span className="oe-label">{label}</span>
      <input
        id={id}
        className="oe-input w-full h-12 text-lg font-mono"
        inputMode="decimal"
        autoComplete="off"
        dir="ltr"
        title={tip}
        placeholder={placeholder}
        value={value}
        onChange={(ev) => set(ev.target.value)}
        disabled={!canWrite}
      />
    </label>
  );

  return (
    <Card className="p-4 space-y-3" data-testid={`stake-card-${stake.point_id}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-lg font-semibold">
            <bdi dir="ltr" className="font-mono">{stake.point_id}</bdi>
          </div>
          <div className="text-xs text-content-secondary">
            {t('survey.setting_out.col.design', { defaultValue: 'Design' })}{' '}
            <bdi dir="ltr" className="font-mono">
              E {fmtCoord(stake.design_e)} · N {fmtCoord(stake.design_n)}
              {stake.design_z != null ? ` · Z ${fmtCoord(stake.design_z)}` : ''}
            </bdi>
            {stake.chainage != null && (
              <span>
                {' '}
                · {t('survey.setting_out.col.chainage', { defaultValue: 'Chainage (m)' })}{' '}
                <bdi dir="ltr" className="font-mono">{fmtCoord(stake.chainage)}</bdi>
              </span>
            )}
          </div>
        </div>
        <VerdictBadge state={state} />
      </div>

      {shown && (
        <div className="flex gap-4 text-sm" aria-live="polite">
          <span title={t('survey.setting_out.tip.d', { defaultValue: 'd (mm): horizontal distance between design and measured position, sqrt(dE² + dN²).' })}>
            d <bdi dir="ltr" className="font-mono font-semibold" data-testid="stake-d">{fmtMm(shown.d_mm)}</bdi> mm
            {tolH != null && <span className="text-content-tertiary"> / {fmtMm(tolH)} mm</span>}
          </span>
          {shown.dz_mm != null && (
            <span title={t('survey.setting_out.tip.dz', { defaultValue: 'dZ (mm): measured height minus design height.' })}>
              dZ <bdi dir="ltr" className="font-mono">{fmtMm(shown.dz_mm)}</bdi> mm
            </span>
          )}
        </div>
      )}

      {canWrite && (
        <>
          <div className="grid grid-cols-2 gap-2">
            {field(`e-${stake.id}`, t('survey.setting_out.field.measured_e', { defaultValue: 'Measured E (m)' }),
              t('survey.setting_out.tip.measured_e', { defaultValue: 'Measured E (m): easting read from the instrument, metres in the project CRS.' }),
              e, setE, fmtCoord(stake.design_e))}
            {field(`n-${stake.id}`, t('survey.setting_out.field.measured_n', { defaultValue: 'Measured N (m)' }),
              t('survey.setting_out.tip.measured_n', { defaultValue: 'Measured N (m): northing read from the instrument, metres in the project CRS.' }),
              n, setN, fmtCoord(stake.design_n))}
          </div>
          {stake.design_z != null &&
            field(`z-${stake.id}`, t('survey.setting_out.field.measured_z', { defaultValue: 'Measured Z (m)' }),
              t('survey.setting_out.tip.measured_z', { defaultValue: 'Measured Z (m): height read from the instrument. Leave empty to check position only.' }),
              z, setZ, fmtCoord(stake.design_z))}
          <button type="button" className="text-xs text-content-secondary underline" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
            {t('survey.action.advanced', { defaultValue: 'Advanced options' })}
          </button>
          {advanced && (
            <div className="grid grid-cols-1 gap-2">
              <label className="block">
                <span className="oe-label">{t('survey.setting_out.field.instrument', { defaultValue: 'Instrument' })}</span>
                <input className="oe-input w-full" value={inst} onChange={(ev) => setInst(ev.target.value)}
                  title={t('survey.setting_out.tip.instrument', { defaultValue: 'Instrument: the total station or GNSS rover used, for traceability (SET-002).' })} />
              </label>
              <label className="block">
                <span className="oe-label">{t('survey.setting_out.field.control_ref', { defaultValue: 'Control points' })}</span>
                <input className="oe-input w-full" value={ctrl} onChange={(ev) => setCtrl(ev.target.value)}
                  title={t('survey.setting_out.tip.control_ref', { defaultValue: 'Control points: the known points the instrument was set up on, for example CP1, CP2.' })} />
              </label>
            </div>
          )}
          <Button variant="primary" className="w-full h-12" disabled={!typed || save.isPending} onClick={() => save.mutate()} data-testid="stake-save">
            {t('survey.setting_out.action.save_measurement', { defaultValue: 'Save measurement' })}
          </Button>
        </>
      )}

      {saved && !live && saved.verdict === 'fail' && (
        saved.ncr_id ? (
          <div className="flex items-center gap-2 text-sm text-content-secondary">
            <FileWarning size={16} aria-hidden />
            {t('survey.setting_out.ncr_linked', { defaultValue: 'NCR draft created' })}
          </div>
        ) : (
          canWrite && (
            <Button variant="danger" className="w-full h-12" icon={<FileWarning size={18} />} disabled={ncr.isPending}
              onClick={() => ncr.mutate()} data-testid="stake-create-ncr">
              {t('survey.setting_out.action.create_ncr', { defaultValue: 'Create NCR draft' })}
            </Button>
          )
        )
      )}
      {saved && (
        <div className="text-xs text-content-tertiary">
          {t('survey.setting_out.measured_by_on', {
            defaultValue: 'Measured by {{name}} on {{date}}',
            name: saved.measured_by || '-',
            date: new Date(saved.measured_at).toLocaleDateString(i18n.language),
          })}
        </div>
      )}
    </Card>
  );
}
