// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dialogs of the Mine survey page: New period (the month, the profile folded
 * away), Add unit (name, type, plan), Compute actual (two surfaces), Import
 * truck loads (one CSV) and Add to claim (pick the BOQ line).
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { listSurfaces, listVolumes } from './volumesApi';
import { CertifyDialog } from './CertifyDialog';
import {
  UNIT_TYPES,
  addEntry,
  addToClaim,
  certifyEntry,
  certifyEntryPreview,
  computeActual,
  createPeriod,
  currentMonth,
  importTruckLoads,
  parseNumber,
  type ClaimResult,
  type MineEntry,
  type MinePeriod,
  type UnitType,
} from './mineApi';

function Field({ label, tip, children }: { label: string; tip?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="oe-label" title={tip}>{label}</span>
      {children}
    </label>
  );
}

function Advanced({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  return (
    <details className="rounded border border-border-light p-2">
      <summary className="cursor-pointer text-content-secondary">{t('survey.action.advanced', { defaultValue: 'Advanced options' })}</summary>
      <div className="mt-2 space-y-3">{children}</div>
    </details>
  );
}

function useDone(onClose: () => void) {
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  return {
    addToast,
    done: () => {
      qc.invalidateQueries({ queryKey: ['mine'] });
      qc.invalidateQueries({ queryKey: ['volumes'] });
      onClose();
    },
    fail: (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) }),
  };
}

interface NewPeriodProps {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onCreated: (p: MinePeriod) => void;
}

export function NewPeriodDialog({ open, projectId, onClose, onCreated }: NewPeriodProps) {
  const { t } = useTranslation();
  const [label, setLabel] = useState(currentMonth());
  const [lo, setLo] = useState('');
  const [hi, setHi] = useState('');
  const [truck, setTruck] = useState('');
  const { done, fail } = useDone(onClose);
  const loV = lo.trim() ? parseNumber(lo) : null;
  const hiV = hi.trim() ? parseNumber(hi) : null;
  const truckV = truck.trim() ? parseNumber(truck) : null;
  const bad =
    !/^\d{4}-\d{2}$/.test(label) ||
    (lo.trim() !== '' && loV == null) ||
    (hi.trim() !== '' && hiV == null) ||
    (truck.trim() !== '' && truckV == null) ||
    (loV == null) !== (hiV == null) ||
    (loV != null && hiV != null && loV > hiV);
  const save = useMutation({
    mutationFn: () => createPeriod(projectId, { label, band_lo_pct: loV, band_hi_pct: hiV, truck_tolerance_pct: truckV }),
    onSuccess: (p) => {
      onCreated(p);
      done();
    },
    onError: fail,
  });
  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('mine.action.new_period', { defaultValue: 'New period' })}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={bad} loading={save.isPending} onClick={() => save.mutate()} data-testid="mine-period-save">
          {t('mine.action.create_period', { defaultValue: 'Create period' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <Field label={t('mine.field.period', { defaultValue: 'Month' })}>
          <input type="month" className="oe-input w-full" value={label} onChange={(e) => setLabel(e.target.value)} data-testid="mine-period-month" />
        </Field>
        <Advanced>
          <Field label={t('mine.field.band_lo', { defaultValue: 'Compliance band from (%)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={lo} onChange={(e) => setLo(e.target.value)} placeholder="95" />
          </Field>
          <Field label={t('mine.field.band_hi', { defaultValue: 'Compliance band to (%)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={hi} onChange={(e) => setHi(e.target.value)} placeholder="105" />
          </Field>
          <Field label={t('mine.field.truck_check', { defaultValue: 'Truck check (%)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={truck} onChange={(e) => setTruck(e.target.value)} placeholder="3" />
          </Field>
        </Advanced>
      </div>
    </WideModal>
  );
}

interface AddUnitProps {
  open: boolean;
  period: MinePeriod | null;
  onClose: () => void;
}

export function AddUnitDialog({ open, period, onClose }: AddUnitProps) {
  const { t, i18n } = useTranslation();
  const [name, setName] = useState('');
  const [type, setType] = useState<UnitType>('bench');
  const [plan, setPlan] = useState('');
  const [density, setDensity] = useState('');
  const [advance, setAdvance] = useState('');
  const { done, fail } = useDone(onClose);
  const planV = parseNumber(plan);
  const densityV = density.trim() ? parseNumber(density) : null;
  const advanceV = advance.trim() ? parseNumber(advance) : null;
  const bad = !name.trim() || planV == null || planV < 0 || (density.trim() !== '' && (densityV == null || densityV <= 0)) || (advance.trim() !== '' && advanceV == null);
  const underground = type === 'stope' || type === 'drive';
  const save = useMutation({
    mutationFn: () =>
      addEntry(
        period!.id,
        { unit_name: name.trim(), unit_type: type, plan_m3: planV!, density_t_m3: densityV, plan_advance_m: underground ? advanceV : null },
        i18n.language,
      ),
    onSuccess: () => {
      setName('');
      setPlan('');
      setDensity('');
      setAdvance('');
      done();
    },
    onError: fail,
  });
  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('mine.action.add_unit', { defaultValue: 'Add unit' })}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={bad} loading={save.isPending} onClick={() => save.mutate()} data-testid="mine-unit-save">
          {t('mine.action.add_unit', { defaultValue: 'Add unit' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <Field label={t('common.name', { defaultValue: 'Name' })}>
          <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} data-testid="mine-unit-name" />
        </Field>
        <Field label={t('common.type', { defaultValue: 'Type' })}>
          <select className="oe-input w-full" value={type} onChange={(e) => setType(e.target.value as UnitType)}>
            {UNIT_TYPES.map((u) => (
              <option key={u} value={u}>{t(`mine.type.${u}`, { defaultValue: u })}</option>
            ))}
          </select>
        </Field>
        <Field label={t('mine.col.plan_m3', { defaultValue: 'Plan m³' })}>
          <input className="oe-input w-full" inputMode="decimal" value={plan} onChange={(e) => setPlan(e.target.value)} data-testid="mine-unit-plan" />
        </Field>
        <Advanced>
          <Field label={t('mine.field.density', { defaultValue: 'Density (t/m³)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={density} onChange={(e) => setDensity(e.target.value)} />
          </Field>
          {underground && (
            <Field label={t('mine.field.plan_advance', { defaultValue: 'Plan advance (m)' })}>
              <input className="oe-input w-full" inputMode="decimal" value={advance} onChange={(e) => setAdvance(e.target.value)} />
            </Field>
          )}
        </Advanced>
      </div>
    </WideModal>
  );
}

interface ComputeProps {
  open: boolean;
  projectId: string;
  entry: MineEntry | null;
  onClose: () => void;
}

export function ComputeActualDialog({ open, projectId, entry, onClose }: ComputeProps) {
  const { t, i18n } = useTranslation();
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [cell, setCell] = useState('');
  const { done, fail } = useDone(onClose);
  const surfaces = useQuery({ queryKey: ['volumes', 'surfaces', projectId], queryFn: () => listSurfaces(projectId), enabled: open });
  const cellV = cell.trim() ? parseNumber(cell) : null;
  const bad = !start || !end || start === end || (cell.trim() !== '' && (cellV == null || cellV <= 0));
  const save = useMutation({
    mutationFn: () => computeActual(entry!.id, { start_surface_id: start, end_surface_id: end, cell_size_m: cellV }, i18n.language),
    onSuccess: done,
    onError: fail,
  });
  const options = surfaces.data ?? [];
  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('mine.action.compute_actual', { defaultValue: 'Compute actual' })}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={bad} loading={save.isPending} onClick={() => save.mutate()} data-testid="mine-compute-run">
          {t('mine.action.compute_actual', { defaultValue: 'Compute actual' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <Field label={t('volumes.field.base', { defaultValue: 'Base surface (earlier)' })}>
          <select className="oe-input w-full" value={start} onChange={(e) => setStart(e.target.value)} data-testid="mine-compute-start">
            <option value="">{t('volumes.field.pick_surface', { defaultValue: 'Choose a surface' })}</option>
            {options.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </Field>
        <Field label={t('volumes.field.compare', { defaultValue: 'Compare surface (later)' })}>
          <select className="oe-input w-full" value={end} onChange={(e) => setEnd(e.target.value)} data-testid="mine-compute-end">
            <option value="">{t('volumes.field.pick_surface', { defaultValue: 'Choose a surface' })}</option>
            {options.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </Field>
        <Advanced>
          <Field label={t('volumes.field.cell_size', { defaultValue: 'Cell size (m)' })} tip={t('volumes.field.cell_tip', { defaultValue: 'Grid square side in metres. Empty: chosen from the point spacing.' })}>
            <input className="oe-input w-full" inputMode="decimal" value={cell} onChange={(e) => setCell(e.target.value)} placeholder={t('volumes.field.auto', { defaultValue: 'auto' })} />
          </Field>
        </Advanced>
        <p className="text-xs text-content-tertiary">
          {t('mine.hint.actual', { defaultValue: 'The actual is the cut between the two surfaces. It is never typed; confirm it before it goes on a claim.' })}
        </p>
      </div>
    </WideModal>
  );
}

interface TruckProps {
  open: boolean;
  entry: MineEntry | null;
  onClose: () => void;
}

export function TruckLoadsDialog({ open, entry, onClose }: TruckProps) {
  const { t, i18n } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const { done, fail } = useDone(onClose);
  const save = useMutation({
    mutationFn: async () => importTruckLoads(entry!.id, await file!.text(), file!.name, i18n.language),
    onSuccess: () => {
      setFile(null);
      done();
    },
    onError: fail,
  });
  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('mine.action.import_trucks', { defaultValue: 'Import truck loads' })}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={!file} loading={save.isPending} onClick={() => save.mutate()} data-testid="mine-trucks-run">
          {t('mine.action.import_trucks', { defaultValue: 'Import truck loads' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <Field label={t('mine.field.truck_file', { defaultValue: 'Truck loads file (CSV: date, unit, loads, payload_t)' })}>
          <input type="file" accept=".csv,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} data-testid="mine-trucks-file" />
        </Field>
      </div>
    </WideModal>
  );
}

interface ClaimProps {
  open: boolean;
  projectId: string;
  entry: MineEntry | null;
  onClose: () => void;
  onClaimed: (r: ClaimResult) => void;
}

/** The confirmed actual of a period to the open payment certificate, after a preview. */
export function AddToClaimDialog({ open, projectId, entry, onClose, onClaimed }: ClaimProps) {
  const { i18n } = useTranslation();
  const volumes = useQuery({
    queryKey: ['volumes', 'list', projectId, i18n.language],
    queryFn: () => listVolumes(projectId, i18n.language),
    enabled: open && !!entry?.actual,
  });
  const v = (volumes.data ?? []).find((x) => x.id === entry?.actual?.volume_id);
  if (!open || !entry) return null;
  const amounts = v
    ? { cut: v.cut_m3, fill: v.fill_m3, net: v.net_m3, loose_cut: v.loose_cut_m3 }
    : { cut: entry.actual_m3 };
  return (
    <CertifyDialog
      key={v ? 'full' : 'cut'}
      open
      projectId={projectId}
      source={`${entry.unit_name} ${entry.actual?.code ?? ''}`.trim()}
      amounts={amounts}
      preview={(b) => certifyEntryPreview(entry.id, b)}
      commit={(b) => certifyEntry(entry.id, b)}
      progressOnly={(b) => addToClaim(entry.id, b).then(onClaimed)}
      onClose={onClose}
    />
  );
}
