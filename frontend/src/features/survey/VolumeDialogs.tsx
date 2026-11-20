// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dialogs of the Volumes page: New surface (from a point set with optional
 * breaklines, a LandXML file or a LAS/LAZ point cloud), New volume (three fields, the rest under Advanced options) and
 * Send to BOQ (pick the line, replace or add, cut, fill, net or loose cut).
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { listPointSets } from './api';
import {
  CLOUD_MAX_BYTES,
  VOLUME_METHODS,
  createVolume,
  formatM3,
  importLandXml,
  importPointCloud,
  searchBoqPositions,
  sendToBoq,
  surfaceFromPoints,
  type CloudStat,
  type QuantityKind,
  type SendResult,
  type Surface,
  type Volume,
  type VolumeInput,
  type VolumeMethod,
} from './volumesApi';

const LANDXML_MAX_BYTES = 30_000_000;

/** "389000 5819000; 389100 5819000; ..." -> [[e, n], ...] or null when unreadable. */
export function parseBoundary(text: string): [number, number][] | null {
  const ring = text
    .split(/[;\n]+/)
    .map((pair) => pair.trim())
    .filter(Boolean)
    .map((pair) => pair.split(/[\s,]+/).map(Number));
  if (ring.length < 3 || ring.some((p) => p.length !== 2 || p.some((v) => !Number.isFinite(v)))) return null;
  return ring as [number, number][];
}

/** "TOE, CREST kerb" -> ["TOE", "CREST", "kerb"], duplicates dropped, order kept. */
export function parseCodes(text: string): string[] {
  const out: string[] = [];
  for (const c of text.split(/[\s,;]+/)) {
    const code = c.trim();
    if (code && !out.includes(code)) out.push(code);
  }
  return out;
}

function Field({ label, tip, children }: { label: string; tip?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="oe-label" title={tip}>{label}</span>
      {children}
    </label>
  );
}

interface NewSurfaceProps {
  open: boolean;
  projectId: string;
  onClose: () => void;
}

export function NewSurfaceDialog({ open, projectId, onClose }: NewSurfaceProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [source, setSource] = useState<'points' | 'landxml' | 'cloud'>('points');
  const [name, setName] = useState('');
  const [setId, setSetId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [codes, setCodes] = useState('');
  const [boundary, setBoundary] = useState('');
  const [cell, setCell] = useState('0.5');
  const [stat, setStat] = useState<CloudStat>('min');
  const [groundOnly, setGroundOnly] = useState(true);
  const ring = boundary.trim() ? parseBoundary(boundary) : null;
  const cellNum = Number(cell.replace(',', '.'));
  const sets = useQuery({ queryKey: ['survey', 'sets', projectId], queryFn: () => listPointSets(projectId), enabled: open });

  const save = useMutation({
    mutationFn: async () => {
      if (source === 'points') {
        const made = await surfaceFromPoints(projectId, {
          name: name.trim(),
          point_set_ids: [setId],
          breakline_codes: parseCodes(codes),
          boundary: ring,
        });
        return [made];
      }
      if (!file) return [];
      if (source === 'cloud') {
        if (file.size > CLOUD_MAX_BYTES) throw new Error(t('volumes.cloud.too_big', { defaultValue: 'The file is larger than 2 GB.' }));
        const res = await importPointCloud(projectId, file, {
          name: name.trim(),
          cell_size_m: cellNum,
          stat,
          ground_only: groundOnly,
          locale: i18n.language,
        });
        addToast({
          type: 'info',
          title: t('volumes.cloud.read', {
            defaultValue: '{{points}} points read, {{cells}} cells of {{cell}} m',
            points: res.points_read.toLocaleString(i18n.language),
            cells: res.cells.toLocaleString(i18n.language),
            cell: res.cell_size_m,
          }),
        });
        return [res.surface];
      }
      if (file.size > LANDXML_MAX_BYTES) throw new Error(t('volumes.surface.too_big', { defaultValue: 'The file is larger than 30 MB.' }));
      const res = await importLandXml(projectId, { text: await file.text(), filename: file.name, name: name.trim() });
      return res.surfaces;
    },
    onSuccess: (made: Surface[]) => {
      qc.invalidateQueries({ queryKey: ['volumes'] });
      for (const s of made) {
        for (const f of s.findings ?? []) addToast({ type: 'warning', title: f.rule_id, message: [f.message, f.suggestion].filter(Boolean).join(' ') });
        addToast({
          type: 'success',
          title: t('volumes.surface.created', {
            defaultValue: '{{name}}: {{points}} points, {{area}} m2',
            name: s.name,
            points: s.point_count,
            area: formatM3(s.area_m2, i18n.language),
          }),
        });
      }
      setName('');
      setFile(null);
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const ready =
    source === 'points'
      ? !!setId && !!name.trim() && (!boundary.trim() || !!ring)
      : source === 'cloud'
        ? !!file && Number.isFinite(cellNum) && cellNum > 0
        : !!file;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('volumes.action.new_surface', { defaultValue: 'New surface' })}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={!ready} loading={save.isPending} onClick={() => save.mutate()} data-testid="surface-save">
          {t('volumes.action.create_surface', { defaultValue: 'Create surface' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="flex gap-4" role="radiogroup">
          <label className="inline-flex items-center gap-2">
            <input type="radio" checked={source === 'points'} onChange={() => setSource('points')} />
            {t('volumes.surface.from_points', { defaultValue: 'From a point set' })}
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="radio" checked={source === 'landxml'} onChange={() => setSource('landxml')} />
            {t('volumes.surface.from_landxml', { defaultValue: 'From a LandXML file' })}
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="radio" checked={source === 'cloud'} onChange={() => setSource('cloud')} data-testid="surface-source-cloud" />
            {t('volumes.surface.from_cloud', { defaultValue: 'From a point cloud (LAS, LAZ)' })}
          </label>
        </div>
        <Field label={t('common.name', { defaultValue: 'Name' })}>
          <input
            className="oe-input w-full"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={source !== 'points' ? t('volumes.surface.name_from_file', { defaultValue: 'Taken from the file when empty' }) : ''}
            data-testid="surface-name"
          />
        </Field>
        {source === 'points' ? (
          <>
          <Field label={t('volumes.surface.point_set', { defaultValue: 'Point set' })}>
            <select className="oe-input w-full" value={setId} onChange={(e) => setSetId(e.target.value)} data-testid="surface-set">
              <option value="">{t('volumes.surface.pick_set', { defaultValue: 'Choose a point set' })}</option>
              {(sets.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.point_count})
                </option>
              ))}
            </select>
          </Field>
          <Field
            label={t('volumes.surface.breakline_codes', { defaultValue: 'Breakline codes (optional)' })}
            tip={t('volumes.surface.breakline_tip', {
              defaultValue: 'Points with these codes are joined in file order into lines the triangles may not cross: toe, crest, kerb, ditch.',
            })}
          >
            <input className="oe-input w-full" value={codes} onChange={(e) => setCodes(e.target.value)} placeholder={t('volumes.surface.breakline_placeholder', { defaultValue: 'TOE, CREST' })} data-testid="surface-breaklines" />
          </Field>
          <Field label={t('volumes.surface.boundary', { defaultValue: 'Outer boundary (optional): E N; E N; ...' })}>
            <textarea className="oe-input w-full font-mono text-xs" rows={2} dir="ltr" value={boundary} onChange={(e) => setBoundary(e.target.value)} />
            {boundary.trim() && !ring && (
              <span className="text-xs text-semantic-error">{t('volumes.surface.boundary_bad', { defaultValue: 'Three or more E N pairs, separated by semicolons.' })}</span>
            )}
          </Field>
          </>
        ) : source === 'cloud' ? (
          <>
            <Field label={t('volumes.cloud.file_any', { defaultValue: 'LAS, LAZ or E57 file, up to 2 GB' })}>
              <input type="file" accept=".las,.laz,.e57" onChange={(e) => setFile(e.target.files?.[0] ?? null)} data-testid="surface-cloud-file" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field
                label={t('volumes.cloud.cell', { defaultValue: 'Cell size (m)' })}
                tip={t('volumes.cloud.cell_tip', { defaultValue: 'One height per cell. 0.5 m suits drone surveys; a larger cell is faster.' })}
              >
                <input className="oe-input w-full" inputMode="decimal" dir="ltr" value={cell} onChange={(e) => setCell(e.target.value)} />
              </Field>
              <Field label={t('volumes.cloud.stat', { defaultValue: 'Height per cell' })}>
                <select className="oe-input w-full" value={stat} onChange={(e) => setStat(e.target.value as CloudStat)}>
                  <option value="min">{t('volumes.cloud.stat_min', { defaultValue: 'Lowest point (bare ground)' })}</option>
                  <option value="mean">{t('volumes.cloud.stat_mean', { defaultValue: 'Average' })}</option>
                  <option value="max">{t('volumes.cloud.stat_max', { defaultValue: 'Highest point' })}</option>
                </select>
              </Field>
            </div>
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" checked={groundOnly} onChange={(e) => setGroundOnly(e.target.checked)} />
              {t('volumes.cloud.ground_only', { defaultValue: 'Ground points only (class 2)' })}
            </label>
            <p className="text-xs text-content-tertiary">
              {t('volumes.cloud.hint', {
                defaultValue: 'The cloud is read in chunks and reduced to a grid on the server, so a large file does not need a large machine. Coordinates must be in the project system.',
              })}
            </p>
          </>
        ) : (
          <Field label={t('volumes.surface.file', { defaultValue: 'LandXML file (metres)' })}>
            <input type="file" accept=".xml,.landxml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
        )}
        <p className="text-xs text-content-tertiary">
          {t('volumes.surface.hint', {
            defaultValue: 'The surface is a triangle model of the ground. It must be in the project coordinate system; nothing is converted silently.',
          })}
        </p>
      </div>
    </WideModal>
  );
}

interface NewVolumeProps {
  open: boolean;
  projectId: string;
  surfaces: Surface[];
  isAdvanced: boolean;
  onClose: () => void;
  onCreated: (v: Volume) => void;
}

export function NewVolumeDialog({ open, projectId, surfaces, isAdvanced, onClose, onCreated }: NewVolumeProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [base, setBase] = useState('');
  const [compare, setCompare] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [method, setMethod] = useState<VolumeMethod>('grid');
  const [cell, setCell] = useState('');
  const [swell, setSwell] = useState('1');
  const [shrink, setShrink] = useState('1');
  const [material, setMaterial] = useState('');
  const [boundary, setBoundary] = useState('');
  const [reason, setReason] = useState('');
  const ring = boundary.trim() ? parseBoundary(boundary) : null;
  const badRing = !!boundary.trim() && ring === null;

  const save = useMutation({
    mutationFn: () => {
      const body: VolumeInput = { name: name.trim(), base_surface_id: base, compare_surface_id: compare };
      if (advanced) {
        body.method = method;
        if (cell.trim()) body.cell_size_m = Number(cell);
        body.swell_factor = Number(swell) || 1;
        body.shrink_factor = Number(shrink) || 1;
        body.material = material.trim();
        body.boundary = ring;
        body.override_reason = reason.trim();
      }
      return createVolume(projectId, body);
    },
    onSuccess: (v) => {
      qc.invalidateQueries({ queryKey: ['volumes'] });
      setName('');
      onCreated(v);
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const ready = !!name.trim() && !!base && !!compare && base !== compare && !badRing;
  const pick = (value: string, set: (v: string) => void, testId: string) => (
    <select className="oe-input w-full" value={value} onChange={(e) => set(e.target.value)} data-testid={testId}>
      <option value="">{t('volumes.field.pick_surface', { defaultValue: 'Choose a surface' })}</option>
      {surfaces.map((s) => (
        <option key={s.id} value={s.id}>
          {s.code} {s.name}
        </option>
      ))}
    </select>
  );

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('volumes.action.new_volume', { defaultValue: 'New volume' })}
      size="md"
      busy={save.isPending}
      footer={
        <Button variant="primary" disabled={!ready} loading={save.isPending} onClick={() => save.mutate()} data-testid="volume-save">
          {t('volumes.action.compute', { defaultValue: 'Compute' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <Field label={t('common.name', { defaultValue: 'Name' })}>
          <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} data-testid="volume-name" />
        </Field>
        <Field
          label={t('volumes.field.base', { defaultValue: 'Base surface (earlier)' })}
          tip={t('volumes.field.base_tip', { defaultValue: 'The ground before the work, usually the existing ground survey.' })}
        >
          {pick(base, setBase, 'volume-base')}
        </Field>
        <Field
          label={t('volumes.field.compare', { defaultValue: 'Compare surface (later)' })}
          tip={t('volumes.field.compare_tip', { defaultValue: 'The design or the later survey. Cut is where it lies below the base.' })}
        >
          {pick(compare, setCompare, 'volume-compare')}
        </Field>
        <p className="text-xs text-content-tertiary">
          {t('volumes.field.default_method', { defaultValue: 'Grid method with an automatic cell size. Results are bank volume (in the ground).' })}
        </p>
        {isAdvanced && (
          <button type="button" className="text-xs text-oe-blue hover:underline" onClick={() => setAdvanced((a) => !a)} data-testid="volume-advanced">
            {t('survey.action.advanced', { defaultValue: 'Advanced options' })}
          </button>
        )}
        {advanced && isAdvanced && (
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-border-light p-3">
            <Field label={t('volumes.field.method', { defaultValue: 'Method' })}>
              <select className="oe-input w-full" value={method} onChange={(e) => setMethod(e.target.value as VolumeMethod)}>
                {VOLUME_METHODS.map((m) => (
                  <option key={m} value={m}>{t(`volumes.method.${m}`, { defaultValue: m })}</option>
                ))}
              </select>
            </Field>
            <Field
              label={t('volumes.field.cell_size', { defaultValue: 'Cell size (m)' })}
              tip={t('volumes.field.cell_tip', { defaultValue: 'Grid square side in metres. Empty: chosen from the point spacing.' })}
            >
              <input className="oe-input w-full" inputMode="decimal" value={cell} onChange={(e) => setCell(e.target.value)} placeholder="auto" />
            </Field>
            <Field
              label={t('volumes.field.swell', { defaultValue: 'Swell factor' })}
              tip={t('volumes.field.swell_tip', { defaultValue: 'Loose volume divided by bank volume, for example 1.25 for clay.' })}
            >
              <input className="oe-input w-full" inputMode="decimal" value={swell} onChange={(e) => setSwell(e.target.value)} data-testid="volume-swell" />
            </Field>
            <Field
              label={t('volumes.field.shrink', { defaultValue: 'Shrink factor' })}
              tip={t('volumes.field.shrink_tip', { defaultValue: 'Compacted volume divided by bank volume.' })}
            >
              <input className="oe-input w-full" inputMode="decimal" value={shrink} onChange={(e) => setShrink(e.target.value)} />
            </Field>
            <Field label={t('volumes.field.material', { defaultValue: 'Material' })}>
              <input className="oe-input w-full" value={material} onChange={(e) => setMaterial(e.target.value)} />
            </Field>
            <Field
              label={t('volumes.field.override_reason', { defaultValue: 'Reason to use a coarse scan' })}
              tip={t('volumes.field.override_tip', { defaultValue: 'Needed only when VOL-003 flags a coarse scan. Stored in the audit trail.' })}
            >
              <input className="oe-input w-full" value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <div className="col-span-2">
              <Field
                label={t('volumes.field.boundary', { defaultValue: 'Boundary (E N pairs in metres, one corner per line)' })}
                tip={t('volumes.field.boundary_tip', { defaultValue: 'Only the area inside counts. Empty: the whole base surface.' })}
              >
                <textarea className="oe-input w-full font-mono text-xs" rows={4} dir="ltr" value={boundary} onChange={(e) => setBoundary(e.target.value)} />
              </Field>
              {badRing && (
                <p className="text-xs text-semantic-error">
                  {t('volumes.field.boundary_bad', { defaultValue: 'Write at least three corners as "E N", one per line.' })}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </WideModal>
  );
}

interface SendProps {
  open: boolean;
  projectId: string;
  volume: Volume;
  onClose: () => void;
  onSent: (r: SendResult) => void;
}

export function SendToBoqDialog({ open, projectId, volume, onClose, onSent }: SendProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [q, setQ] = useState('');
  const [positionId, setPositionId] = useState('');
  const [mode, setMode] = useState<'replace' | 'add'>('replace');
  const [kind, setKind] = useState<QuantityKind>('cut');
  const hits = useQuery({
    queryKey: ['volumes', 'boq-positions', projectId, q],
    queryFn: () => searchBoqPositions(projectId, q),
    enabled: open,
  });
  const amounts: Record<QuantityKind, number> = {
    cut: volume.cut_m3,
    fill: volume.fill_m3,
    net: volume.net_m3,
    loose_cut: volume.loose_cut_m3,
  };
  const send = useMutation({
    mutationFn: () => sendToBoq(volume.id, { position_id: positionId, mode, quantity: kind }, i18n.language),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['volumes'] });
      qc.invalidateQueries({ queryKey: ['boq'] });
      onSent(r);
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('volumes.action.send_to_boq', { defaultValue: 'Send to BOQ' })}
      size="lg"
      busy={send.isPending}
      footer={
        <Button variant="primary" disabled={!positionId} loading={send.isPending} onClick={() => send.mutate()} data-testid="send-confirm">
          {t('volumes.action.send_to_boq', { defaultValue: 'Send to BOQ' })}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap gap-3">
          {(Object.keys(amounts) as QuantityKind[]).map((k) => (
            <label key={k} className="inline-flex items-center gap-2">
              <input type="radio" checked={kind === k} onChange={() => setKind(k)} />
              {t(`volumes.quantity.${k}`, { defaultValue: k })}: <bdi dir="ltr">{formatM3(amounts[k], i18n.language)} m³</bdi>
            </label>
          ))}
        </div>
        <input
          className="oe-input w-full"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('volumes.send.search', { defaultValue: 'Search BOQ lines measured in m3' })}
          data-testid="send-search"
        />
        <div className="max-h-64 overflow-y-auto rounded border border-border-light">
          {(hits.data ?? []).length === 0 ? (
            <p className="p-3 text-content-tertiary">{t('volumes.send.none', { defaultValue: 'No BOQ line in m3 matches.' })}</p>
          ) : (
            <ul>
              {(hits.data ?? []).map((h) => (
                <li key={h.id}>
                  <label className="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-secondary">
                    <input type="radio" name="boq-position" checked={positionId === h.id} onChange={() => setPositionId(h.id)} />
                    <span className="font-mono text-xs">{h.ordinal}</span>
                    <span className="flex-1">{h.description}</span>
                    <span className="text-xs text-content-tertiary">{h.boq_name}</span>
                    <bdi dir="ltr" className="text-xs">{h.quantity} {h.unit}</bdi>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex gap-4">
          <label className="inline-flex items-center gap-2">
            <input type="radio" checked={mode === 'replace'} onChange={() => setMode('replace')} />
            {t('volumes.send.replace', { defaultValue: 'Replace the quantity' })}
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="radio" checked={mode === 'add'} onChange={() => setMode('add')} />
            {t('volumes.send.add', { defaultValue: 'Add to the quantity' })}
          </label>
        </div>
        <p className="text-xs text-content-tertiary">
          {t('volumes.send.trail', {
            defaultValue: 'The line keeps a source chip {{formula}} with the method, cell size, coordinate system and who confirmed it.',
            formula: `survey.volume(${volume.code})`,
          })}
        </p>
      </div>
    </WideModal>
  );
}
