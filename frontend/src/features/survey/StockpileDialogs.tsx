// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dialogs of the Stockpiles page: New stockpile (name, book stock, the ground
 * file under the pile) and Add survey (a point file, a surface or a typed
 * volume, then density and where it comes from). Tolerance and cell size sit
 * behind Advanced.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { listSurfaces } from './volumesApi';
import {
  DENSITY_SOURCES,
  PILE_SOURCES,
  addSurvey,
  createStockpile,
  parseNumber,
  type DensitySource,
  type PileSource,
  type Stockpile,
  type StockpileInput,
  type SurveyInput,
} from './stockpilesApi';

function Field({ label, tip, children }: { label: string; tip?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="oe-label" title={tip}>{label}</span>
      {children}
    </label>
  );
}

interface NewStockpileProps {
  open: boolean;
  projectId: string;
  isAdvanced: boolean;
  onClose: () => void;
  onCreated: (p: Stockpile) => void;
}

export function NewStockpileDialog({ open, projectId, isAdvanced, onClose, onCreated }: NewStockpileProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [material, setMaterial] = useState('');
  const [book, setBook] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [tolerance, setTolerance] = useState('');
  const bookValue = book.trim() ? parseNumber(book) : null;
  const tolValue = tolerance.trim() ? parseNumber(tolerance) : null;

  const save = useMutation({
    mutationFn: async () => {
      const body: StockpileInput = { name: name.trim(), material: material.trim(), book_tonnes: bookValue };
      if (file) {
        body.base_text = await file.text();
        body.base_filename = file.name;
      }
      if (isAdvanced && tolValue != null) body.variance_tolerance_pct = tolValue;
      return createStockpile(projectId, body);
    },
    onSuccess: (pile) => {
      qc.invalidateQueries({ queryKey: ['stockpiles'] });
      qc.invalidateQueries({ queryKey: ['volumes'] });
      setName('');
      setMaterial('');
      setBook('');
      setFile(null);
      onCreated(pile);
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const bad = (book.trim() !== '' && bookValue == null) || (tolerance.trim() !== '' && tolValue == null);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('stockpiles.action.new_stockpile', { defaultValue: 'New stockpile' })}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={!name.trim() || bad} loading={save.isPending} onClick={() => save.mutate()} data-testid="stockpile-save">
          {t('stockpiles.action.create', { defaultValue: 'Create stockpile' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <Field label={t('common.name', { defaultValue: 'Name' })}>
          <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} data-testid="stockpile-name" />
        </Field>
        <Field label={t('stockpiles.field.material', { defaultValue: 'Material' })}>
          <input className="oe-input w-full" value={material} onChange={(e) => setMaterial(e.target.value)} />
        </Field>
        <Field label={t('stockpiles.field.book', { defaultValue: 'Book stock (t)' })}>
          <input className="oe-input w-full" inputMode="decimal" value={book} onChange={(e) => setBook(e.target.value)} data-testid="stockpile-book" />
        </Field>
        <Field label={t('stockpiles.field.base_file', { defaultValue: 'Base point file (ground before the pile)' })}>
          <input type="file" accept=".csv,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        {isAdvanced && (
          <Field label={t('stockpiles.field.tolerance', { defaultValue: 'Variance tolerance (%)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={tolerance} onChange={(e) => setTolerance(e.target.value)} placeholder="3" />
          </Field>
        )}
        <p className="text-xs text-content-tertiary">{t('stockpiles.hint.density', { defaultValue: 'Tonnes are volume times density. Use a measured or supplier value when you have one.' })}</p>
      </div>
    </WideModal>
  );
}

interface AddSurveyProps {
  open: boolean;
  projectId: string;
  pile: Stockpile | null;
  isAdvanced: boolean;
  onClose: () => void;
}

export function AddSurveyDialog({ open, projectId, pile, isAdvanced, onClose }: AddSurveyProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [source, setSource] = useState<PileSource>('file');
  const [file, setFile] = useState<File | null>(null);
  const [surfaceId, setSurfaceId] = useState('');
  const [volume, setVolume] = useState('');
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [density, setDensity] = useState('');
  const [densitySource, setDensitySource] = useState<DensitySource>('assumed');
  const [cell, setCell] = useState('');
  const surfaces = useQuery({ queryKey: ['volumes', 'surfaces', projectId], queryFn: () => listSurfaces(projectId), enabled: open && source === 'surface' });
  const densityValue = parseNumber(density);
  const volumeValue = parseNumber(volume);
  const cellValue = cell.trim() ? parseNumber(cell) : null;

  const save = useMutation({
    mutationFn: async () => {
      const body: SurveyInput = { surveyed_on: date, density_t_m3: densityValue!, density_source: densitySource };
      if (source === 'file' && file) {
        body.pile_text = await file.text();
        body.pile_filename = file.name;
      } else if (source === 'surface') body.pile_surface_id = surfaceId;
      else body.volume_m3 = volumeValue!;
      if (isAdvanced && cellValue != null && source !== 'typed') body.cell_size_m = cellValue;
      return addSurvey(pile!.id, body, i18n.language);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stockpiles'] });
      qc.invalidateQueries({ queryKey: ['volumes'] });
      setFile(null);
      setVolume('');
      setDensity('');
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const sourceReady = source === 'file' ? !!file : source === 'surface' ? !!surfaceId : volumeValue != null && volumeValue > 0;
  const ready = !!pile && sourceReady && densityValue != null && densityValue > 0 && !!date;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={`${t('stockpiles.action.add_survey', { defaultValue: 'Add survey' })}${pile ? `: ${pile.name}` : ''}`}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={!ready} loading={save.isPending} onClick={() => save.mutate()} data-testid="survey-save">
          {t('stockpiles.action.save_survey', { defaultValue: 'Save survey' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap gap-4" role="radiogroup">
          {PILE_SOURCES.map((s) => (
            <label key={s} className="inline-flex items-center gap-2">
              <input type="radio" checked={source === s} onChange={() => setSource(s)} />
              {t(`stockpiles.source.${s}`, { defaultValue: s })}
            </label>
          ))}
        </div>
        {source === 'file' && (
          <Field label={t('stockpiles.field.pile_file', { defaultValue: 'Pile point file' })}>
            <input type="file" accept=".csv,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} data-testid="survey-file" />
          </Field>
        )}
        {source === 'surface' && (
          <Field label={t('volumes.tab.surfaces', { defaultValue: 'Surfaces' })}>
            <select className="oe-input w-full" value={surfaceId} onChange={(e) => setSurfaceId(e.target.value)}>
              <option value="" />
              {(surfaces.data ?? []).filter((s) => s.id !== pile?.base_surface_id).map((s) => (
                <option key={s.id} value={s.id}>{s.code} {s.name}</option>
              ))}
            </select>
          </Field>
        )}
        {source === 'typed' && (
          <Field label={t('stockpiles.field.volume', { defaultValue: 'Volume (m³)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={volume} onChange={(e) => setVolume(e.target.value)} />
          </Field>
        )}
        <Field label={t('stockpiles.field.date', { defaultValue: 'Survey date' })}>
          <input type="date" className="oe-input w-full" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('stockpiles.field.density', { defaultValue: 'Density (t/m³)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={density} onChange={(e) => setDensity(e.target.value)} data-testid="survey-density" />
          </Field>
          <Field label={t('stockpiles.field.density_source', { defaultValue: 'Density source' })}>
            <select className="oe-input w-full" value={densitySource} onChange={(e) => setDensitySource(e.target.value as DensitySource)} data-testid="survey-density-source">
              {DENSITY_SOURCES.map((d) => (
                <option key={d} value={d}>{t(`stockpiles.density.${d}`, { defaultValue: d })}</option>
              ))}
            </select>
          </Field>
        </div>
        {isAdvanced && source !== 'typed' && (
          <Field label={t('stockpiles.field.cell', { defaultValue: 'Cell size (m)' })}>
            <input className="oe-input w-full" inputMode="decimal" value={cell} onChange={(e) => setCell(e.target.value)} placeholder="5" />
          </Field>
        )}
        <p className="text-xs text-content-tertiary">{t('stockpiles.hint.density', { defaultValue: 'Tonnes are volume times density. Use a measured or supplier value when you have one.' })}</p>
      </div>
    </WideModal>
  );
}
