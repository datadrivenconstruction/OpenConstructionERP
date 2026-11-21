// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Design pads over the terrain. The outline is typed or pasted (one corner
 * per line, in the project axis order and unit) or taken from a work zone;
 * the level, batter 1:n and cross-fall complete it. SRV-083 runs on every
 * change; Create builds the pad TIN with batters to daylight on the chosen
 * ground surface and adds it to the surfaces.
 */

import { useMemo, useState, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import type { GridXYZ, PlanCanvasProps, PlanFeature } from '../types';
import type { PlanConventions } from '../units/conventions';
import { usePlanConventions } from '../hooks';
import { parseDirection } from '../units/angles';
import { axisLabelFor, formatArea, fromMetres, parseCoordPair, parseDistance, toDisplayOrder } from '../units/linear';
import { padFindings, ringAreaM2 } from '../engine/ringChecks';
import { layer } from '../planLayers';
import { SurfaceView } from './SurfaceView';
import { p2Api, p2Keys } from './api';
import { zoneFeature } from './parcelLayers';

/** Corners from pasted text, one per line, in the convention's axis order and unit; bad lines are reported by number. */
export function parseOutline(text: string, conv: Pick<PlanConventions, 'axis' | 'linearUnit'>): { ring: Array<[number, number]>; bad: number[] } {
  const ring: Array<[number, number]> = [];
  const bad: number[] = [];
  text.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    const p = parseCoordPair(line, conv);
    if (p) ring.push([p[0]!, p[1]!]);
    else bad.push(i + 1);
  });
  return { ring, bad };
}

export interface ZonePadEditorProps {
  projectId: string;
  canWrite: boolean;
  surfaces: Array<{ id: string; name: string; code?: string }>;
  canvas?: ComponentType<PlanCanvasProps>;
}

export function ZonePadEditor({ projectId, canWrite, surfaces, canvas }: ZonePadEditorProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { conventions: conv } = usePlanConventions(projectId);
  const grid = useQuery({ queryKey: p2Keys.grid(projectId), queryFn: () => p2Api.planGrid(projectId) });
  const [name, setName] = useState('');
  const [outline, setOutline] = useState('');
  const [level, setLevel] = useState('');
  const [batter, setBatter] = useState('2');
  const [fall, setFall] = useState('0');
  const [bearing, setBearing] = useState('');
  const [ground, setGround] = useState<string>(surfaces[0]?.id ?? '');

  const parsed = useMemo(() => parseOutline(outline, conv), [outline, conv]);
  const lv = parseDistance(level, conv);
  const pad: PlanFeature | null = parsed.ring.length
    ? {
        id: 'pad:draft',
        layer: 'pads',
        geometry: { type: 'Polygon', coordinates: [parsed.ring.map((p) => [p[0], p[1]] as GridXYZ)] },
        properties: { name: name || t('plan.tin.pad_draft', { defaultValue: 'New pad' }), level: lv, label: name, colour: 'var(--oe-map-surface)' },
      }
    : null;
  const findings = useMemo(() => (pad ? padFindings([pad]) : []), [pad]);
  const zones = grid.data?.zones ?? [];
  const extra = useMemo(
    () => [layer('zones', zones.map((z) => zoneFeature(z))), layer('pads', pad ? [pad] : [])],
    [zones, pad],
  );

  const body = () => ({
    name: name.trim() || t('plan.tin.pad_draft', { defaultValue: 'New pad' }),
    outline: parsed.ring,
    level: lv ?? 0,
    batter_n: Number(batter) || 0,
    cross_fall_pct: Number(fall) || 0,
    fall_bearing_deg: bearing ? parseDirection(bearing, conv) ?? 0 : 0,
    ground_surface_id: ground || null,
  });
  const create = useMutation({
    mutationFn: () => p2Api.createPad(projectId, body()),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['volumes'] });
      void qc.invalidateQueries({ queryKey: ['surfaces'] });
      addToast({ type: 'success', title: t('plan.tin.pad_created', { defaultValue: 'Pad {{name}} added to the surfaces', name: r.name }) });
      setOutline('');
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const axes = axisLabelFor(conv.axis);
  const blocked = findings.some((f) => f.severity === 'error') || parsed.bad.length > 0;

  const side = canWrite ? (
    <section className="space-y-2" data-testid="plan-pad-form">
      <h3 className="font-semibold text-content-primary">{t('plan.tin.pad_title', { defaultValue: 'Design pad' })}</h3>
      <input className="oe-input w-full" placeholder={t('plan.tin.pad_name', { defaultValue: 'Name' })} value={name} onChange={(e) => setName(e.target.value)} />
      {zones.length > 0 && (
        <select className="oe-input w-full" value="" onChange={(e) => {
          const z = zones.find((x) => x.id === e.target.value);
          if (z) { setOutline(z.ring.map((p) => toDisplayOrder(p[0], p[1], conv.axis).map((v) => fromMetres(v, conv.linearUnit)).join(' ')).join('\n')); if (!name) setName(z.name); }
        }}>
          <option value="">{t('plan.tin.pad_from_zone', { defaultValue: 'Outline from a work zone' })}</option>
          {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
        </select>
      )}
      <label className="block">
        <span className="oe-label">{t('plan.tin.pad_outline', { defaultValue: 'Outline, one corner per line ({{a}} {{b}})', a: axes.e, b: axes.n })}</span>
        <textarea className="oe-input min-h-28 w-full font-mono text-xs" value={outline} onChange={(e) => setOutline(e.target.value)} data-testid="plan-pad-outline" />
      </label>
      {parsed.bad.length > 0 && (
        <p className="text-xs text-semantic-error">{t('plan.tin.pad_bad_lines', { defaultValue: 'Lines not read: {{lines}}', lines: parsed.bad.join(', ') })}</p>
      )}
      {parsed.ring.length >= 3 && (
        <p className="text-xs text-content-secondary">{t('plan.tin.pad_area', { defaultValue: 'Pad area {{area}}', area: formatArea(ringAreaM2(parsed.ring), conv) })}</p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="oe-label">{t('plan.tin.pad_level', { defaultValue: 'Design level' })}</span>
          <input className="oe-input w-full" inputMode="decimal" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="plan-pad-level" />
        </label>
        <label className="block">
          <span className="oe-label">{t('plan.tin.pad_batter', { defaultValue: 'Batter 1:n' })}</span>
          <input className="oe-input w-full" inputMode="decimal" value={batter} onChange={(e) => setBatter(e.target.value)} />
        </label>
        <label className="block">
          <span className="oe-label">{t('plan.tin.pad_fall', { defaultValue: 'Cross-fall, %' })}</span>
          <input className="oe-input w-full" inputMode="decimal" value={fall} onChange={(e) => setFall(e.target.value)} />
        </label>
        <label className="block">
          <span className="oe-label">{t('plan.tin.pad_bearing', { defaultValue: 'Falls towards' })}</span>
          <input className="oe-input w-full" value={bearing} onChange={(e) => setBearing(e.target.value)} placeholder="0" />
        </label>
      </div>
      <label className="block">
        <span className="oe-label">{t('plan.tin.pad_ground', { defaultValue: 'Ground surface for the batters' })}</span>
        <select className="oe-input w-full" value={ground} onChange={(e) => setGround(e.target.value)}>
          <option value="">{t('plan.tin.pad_no_ground', { defaultValue: 'None: the top only' })}</option>
          {surfaces.map((s) => <option key={s.id} value={s.id}>{s.code ? `${s.code} ${s.name}` : s.name}</option>)}
        </select>
      </label>
      <Button variant="primary" size="sm" icon={<Plus size={14} />} disabled={blocked || parsed.ring.length < 3} loading={create.isPending} onClick={() => create.mutate()} data-testid="plan-pad-create">
        {t('plan.tin.pad_create', { defaultValue: 'Create pad surface' })}
      </Button>
    </section>
  ) : null;

  return (
    <SurfaceView projectId={projectId} surfaces={surfaces} extraLayers={extra} findings={findings} side={side} canvas={canvas}
      printTitle={t('plan.tin.pad_print_title', { defaultValue: 'Design pads and terrain' })} testId="plan-pads" />
  );
}

export default ZonePadEditor;
