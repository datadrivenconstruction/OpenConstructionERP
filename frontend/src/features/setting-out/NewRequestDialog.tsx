// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * New request: three fields for a beginner (name, item type, tolerance profile).
 * Advanced options: a tolerance override, the linked BOQ/BIM/CAD element, and
 * the instrument and control points the crew records against.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { ITEM_TYPES, createRequest, type ItemType, type RefType, type StakeoutRequest, type ToleranceProfile } from './api';
import { parseDecimal } from './verdict';

export function profileLabel(p: ToleranceProfile, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (p.source === 'demo') return `${p.name} · ${t('survey.setting_out.profile.demo', { defaultValue: 'Demo values, not a standard' })}`;
  if (p.source === 'pack') return `${p.name} · ${p.reference || p.country}`;
  return `${p.name} · ${t('survey.setting_out.profile.project', { defaultValue: 'Project profile' })}`;
}

export function NewRequestDialog({
  open,
  projectId,
  profiles,
  onClose,
  onCreated,
}: {
  open: boolean;
  projectId: string;
  profiles: ToleranceProfile[];
  onClose: () => void;
  onCreated: (r: StakeoutRequest) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [itemType, setItemType] = useState<ItemType>('column');
  const [profile, setProfile] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [tolH, setTolH] = useState('');
  const [refType, setRefType] = useState<RefType>('');
  const [refLabel, setRefLabel] = useState('');
  const [instrument, setInstrument] = useState('');
  const [control, setControl] = useState('');

  useEffect(() => {
    if (open && !profile && profiles.length) setProfile(profiles[0]!.key);
  }, [open, profile, profiles]);

  const create = useMutation({
    mutationFn: () =>
      createRequest(projectId, {
        name: name.trim(),
        item_type: itemType,
        tolerance_key: profile,
        tol_h_mm: parseDecimal(tolH),
        element_ref_type: refType,
        element_ref_label: refLabel.trim(),
        instrument: instrument.trim(),
        control_ref: control.trim(),
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['setting-out'] });
      onCreated(r);
      setName('');
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={create.isPending}
      title={t('survey.setting_out.action.new_request', { defaultValue: 'New request' })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
            {t('survey.setting_out.action.new_request', { defaultValue: 'New request' })}
          </Button>
        </div>
      }
    >
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}>
        <label className="block">
          <span className="oe-label">{t('survey.setting_out.field.name', { defaultValue: 'Name' })}</span>
          <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} autoFocus
            placeholder={t('survey.setting_out.field.name_hint', { defaultValue: 'For example: Columns axis C' })}
            title={t('survey.setting_out.tip.name', { defaultValue: 'Name: what the crew sets out, as they would say it on site.' })} />
        </label>
        <label className="block">
          <span className="oe-label">{t('survey.setting_out.field.item_type', { defaultValue: 'Item type' })}</span>
          <select className="oe-input w-full" value={itemType} onChange={(e) => setItemType(e.target.value as ItemType)}
            title={t('survey.setting_out.tip.item_type', { defaultValue: 'Item type: picks the tolerance from the profile, for example columns or kerbs.' })}>
            {ITEM_TYPES.map((k) => (
              <option key={k} value={k}>{t(`survey.setting_out.item.${k}`, { defaultValue: k })}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="oe-label">{t('survey.setting_out.field.tolerance', { defaultValue: 'Tolerance profile' })}</span>
          <select className="oe-input w-full" value={profile} onChange={(e) => setProfile(e.target.value)}
            title={t('survey.setting_out.tip.tolerance', { defaultValue: 'Tolerance (mm): the largest allowed distance between design and staked point.' })}>
            {profiles.map((p) => (
              <option key={p.key} value={p.key}>{profileLabel(p, t)}</option>
            ))}
            <option value="">{t('survey.setting_out.profile.none', { defaultValue: 'No profile, set one' })}</option>
          </select>
        </label>
        <button type="button" className="text-sm text-content-secondary underline" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
          {t('survey.action.advanced', { defaultValue: 'Advanced options' })}
        </button>
        {advanced && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="block">
              <span className="oe-label">{t('survey.setting_out.field.tol_override', { defaultValue: 'Tolerance override (mm)' })}</span>
              <input className="oe-input w-full" inputMode="decimal" value={tolH} onChange={(e) => setTolH(e.target.value)}
                title={t('survey.setting_out.tip.tol_override', { defaultValue: 'Tolerance override (mm): replaces the profile value for this request only.' })} />
            </label>
            <label className="block">
              <span className="oe-label">{t('survey.setting_out.field.element', { defaultValue: 'Linked element' })}</span>
              <div className="flex gap-2">
                <select className="oe-input w-28" value={refType} onChange={(e) => setRefType(e.target.value as RefType)}
                  aria-label={t('survey.setting_out.field.element', { defaultValue: 'Linked element' })}>
                  <option value="">-</option>
                  <option value="boq">BOQ</option>
                  <option value="bim">BIM</option>
                  <option value="cad">CAD</option>
                </select>
                <input className="oe-input flex-1" value={refLabel} onChange={(e) => setRefLabel(e.target.value)}
                  title={t('survey.setting_out.tip.element', { defaultValue: 'Linked element: the BOQ position, BIM element or CAD element (read through DDC) this request sets out.' })} />
              </div>
            </label>
            <label className="block">
              <span className="oe-label">{t('survey.setting_out.field.instrument', { defaultValue: 'Instrument' })}</span>
              <input className="oe-input w-full" value={instrument} onChange={(e) => setInstrument(e.target.value)}
                title={t('survey.setting_out.tip.instrument', { defaultValue: 'Instrument: the total station or GNSS rover used, for traceability (SET-002).' })} />
            </label>
            <label className="block">
              <span className="oe-label">{t('survey.setting_out.field.control_ref', { defaultValue: 'Control points' })}</span>
              <input className="oe-input w-full" value={control} onChange={(e) => setControl(e.target.value)}
                title={t('survey.setting_out.tip.control_ref', { defaultValue: 'Control points: the known points the instrument was set up on, for example CP1, CP2.' })} />
            </label>
          </div>
        )}
      </form>
    </WideModal>
  );
}
