// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Geofence editor - a manager draws the site area the time clock checks​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * against: a circle (click the centre, then a point on its edge, or type the
 * radius) or a polygon (click the vertices, then close it). When the map
 * cannot load (offline, no WebGL) a plain latitude / longitude form does the
 * same job.
 */

import { Suspense, lazy, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Circle, Hexagon, Loader2, Plus, Trash2, Undo2 } from 'lucide-react';
import clsx from 'clsx';
import { getErrorMessage } from '@/shared/lib/api';
import { useOnlineStatus } from '@/shared/hooks/useOnlineStatus';
import { useToastStore } from '@/stores/useToastStore';
import { listProjectMembers } from '@/features/project_handbook/api';
import { mapSupported } from './GeofenceMap';
import { radiusFromEdge, type FenceShape, type LatLng } from './geometry';
import { useGeofenceMutations, useGeofences, type Geofence, type GeofencePayload } from './clockApi';

const GeofenceMap = lazy(() => import('./GeofenceMap'));

interface Draft {
  id: string | null;
  name: string;
  shape: 'circle' | 'polygon';
  lat: string;
  lng: string;
  radius: string;
  points: LatLng[];
  tolerance: string;
  supervisors: string[];
  active: boolean;
  costCode: string;
}

type Step = 'idle' | 'centre' | 'edge' | 'vertices';

const EMPTY: Draft = {
  id: null,
  name: '',
  shape: 'circle',
  lat: '',
  lng: '',
  radius: '100',
  points: [],
  tolerance: '10',
  supervisors: [],
  active: true,
  costCode: '',
};

const num = (s: string): number | null => {
  if (s.trim() === '') return null;
  const n = Number(s.replace(',', '.'));
  return Number.isFinite(n) ? n : null;
};

const fromFence = (f: Geofence): Draft => ({
  id: f.id,
  name: f.name,
  shape: f.shape,
  lat: f.center_lat == null ? '' : String(f.center_lat),
  lng: f.center_lng == null ? '' : String(f.center_lng),
  radius: f.radius_m == null ? '' : String(f.radius_m),
  points: f.polygon,
  tolerance: String(f.tolerance_m),
  supervisors: f.supervisor_user_ids,
  active: f.active,
  costCode: f.default_cost_code ?? '',
});

export function draftShape(d: Draft): FenceShape {
  return {
    shape: d.shape,
    center_lat: num(d.lat),
    center_lng: num(d.lng),
    radius_m: num(d.radius),
    polygon: d.shape === 'polygon' ? d.points : [],
    tolerance_m: num(d.tolerance) ?? 0,
  };
}

/** Parse "lat, lng" lines into vertices; returns null when any line is malformed. */
export function parseVertices(text: string): LatLng[] | null {
  const out: LatLng[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const m = line.trim().split(/[\s,;]+/);
    const lat = num(m[0] ?? '');
    const lng = num(m[1] ?? '');
    if (m.length !== 2 || lat == null || lng == null || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
    out.push([lat, lng]);
  }
  return out;
}

export function GeofenceEditor({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const online = useOnlineStatus();
  const fencesQ = useGeofences(projectId);
  const { create, update, remove } = useGeofenceMutations(projectId);
  const membersQ = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listProjectMembers(projectId),
    enabled: !!projectId,
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  const [step, setStep] = useState<Step>('idle');
  const [vertexText, setVertexText] = useState('');
  const [focus, setFocus] = useState<{ lat: number; lng: number } | null>(null);
  const mapOk = useMemo(() => online && mapSupported(), [online]);

  const fences = fencesQ.data ?? [];
  const shape = draft ? draftShape(draft) : null;
  const patch = (p: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...p } : d));

  const startNew = () => {
    setDraft({ ...EMPTY });
    setStep(mapOk ? 'centre' : 'idle');
    setVertexText('');
  };

  const edit = (f: Geofence) => {
    setDraft(fromFence(f));
    setStep('idle');
    setVertexText(f.polygon.map((p) => `${p[0]}, ${p[1]}`).join('\n'));
    if (f.center_lat != null && f.center_lng != null) setFocus({ lat: f.center_lat, lng: f.center_lng });
    else if (f.polygon[0]) setFocus({ lat: f.polygon[0][0], lng: f.polygon[0][1] });
  };

  const switchShape = (s: 'circle' | 'polygon') => {
    patch({ shape: s });
    setStep(mapOk ? (s === 'circle' ? 'centre' : 'vertices') : 'idle');
  };

  const onMapClick = ([lat, lng]: LatLng) => {
    if (!draft) return;
    if (step === 'centre') {
      patch({ lat: lat.toFixed(6), lng: lng.toFixed(6) });
      setStep('edge');
    } else if (step === 'edge') {
      const c = num(draft.lat);
      const g = num(draft.lng);
      if (c != null && g != null) patch({ radius: String(radiusFromEdge([c, g], [lat, lng])) });
      setStep('idle');
    } else if (step === 'vertices') {
      const points = [...draft.points, [Number(lat.toFixed(6)), Number(lng.toFixed(6))] as LatLng];
      patch({ points });
      setVertexText(points.map((p) => `${p[0]}, ${p[1]}`).join('\n'));
    }
  };

  const undoPoint = () => {
    if (!draft) return;
    const points = draft.points.slice(0, -1);
    patch({ points });
    setVertexText(points.map((p) => `${p[0]}, ${p[1]}`).join('\n'));
  };

  const valid =
    !!draft &&
    draft.name.trim() !== '' &&
    (draft.shape === 'circle'
      ? shape?.center_lat != null && shape.center_lng != null && (shape.radius_m ?? 0) > 0
      : draft.points.length >= 3);

  const save = async () => {
    if (!draft || !shape || !valid) return;
    const payload: GeofencePayload = {
      project_id: projectId,
      name: draft.name.trim(),
      shape: draft.shape,
      center_lat: draft.shape === 'circle' ? shape.center_lat : null,
      center_lng: draft.shape === 'circle' ? shape.center_lng : null,
      radius_m: draft.shape === 'circle' ? shape.radius_m : null,
      polygon: draft.shape === 'polygon' ? draft.points : [],
      tolerance_m: Math.max(0, shape.tolerance_m),
      supervisor_user_ids: draft.supervisors,
      active: draft.active,
      default_cost_code: draft.costCode.trim(),
    };
    try {
      if (draft.id) await update.mutateAsync({ id: draft.id, data: payload });
      else await create.mutateAsync(payload);
      setDraft(null);
      setStep('idle');
    } catch (e) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    }
  };

  const del = async (f: Geofence) => {
    if (!window.confirm(t('field_clock.fence_delete_confirm', { defaultValue: 'Delete this site area?' }))) return;
    try {
      await remove.mutateAsync(f.id);
      if (draft?.id === f.id) setDraft(null);
    } catch (e) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    }
  };

  const field = 'h-11 w-full rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';
  const label = 'mb-1 block text-xs font-medium text-content-secondary';
  const saving = create.isPending || update.isPending;

  const hint =
    step === 'centre'
      ? t('field_clock.hint_centre', { defaultValue: 'Tap the map where the centre of the site area is.' })
      : step === 'edge'
        ? t('field_clock.hint_edge', { defaultValue: 'Tap a point on the edge, or type the radius below.' })
        : step === 'vertices'
          ? t('field_clock.hint_vertices', {
              defaultValue_one: 'Tap each corner of the site area. {{count}} corner placed (3 needed).',
              defaultValue_other: 'Tap each corner of the site area. {{count}} corners placed (3 needed).',
              count: draft?.points.length ?? 0,
            })
          : '';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-content-secondary">
          {t('field_clock.fences_intro', {
            defaultValue:
              'A site area is where a clock-in counts as on site. A tap outside every active area is still recorded, but flagged for a supervisor.',
          })}
        </p>
        <button
          type="button"
          onClick={startNew}
          className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-oe-blue px-4 text-sm font-semibold text-content-inverse"
        >
          <Plus size={16} />
          {t('field_clock.fence_new', { defaultValue: 'New site area' })}
        </button>
      </div>

      <div className="relative h-72 overflow-hidden rounded-xl border border-border-light bg-surface-secondary lg:h-96">
        {mapOk ? (
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-sm text-content-tertiary">
                <Loader2 size={16} className="mr-2 animate-spin" />
                {t('common.loading', { defaultValue: 'Loading...' })}
              </div>
            }
          >
            <GeofenceMap
              fences={fences.filter((f) => f.id !== draft?.id)}
              draft={shape}
              draftPoints={draft?.shape === 'polygon' && draft.points.length < 3 ? draft.points : []}
              focus={focus}
              drawing={step !== 'idle'}
              onMapClick={onMapClick}
            />
          </Suspense>
        ) : (
          <div className="flex h-full items-center justify-center p-4 text-center text-sm text-content-tertiary">
            {t('field_clock.map_unavailable', {
              defaultValue: 'The map is not available (offline or no graphics support). Enter the coordinates below.',
            })}
          </div>
        )}
      </div>

      {hint && <p className="text-sm font-medium text-oe-blue-text">{hint}</p>}

      <ul className="flex flex-col gap-2">
        {fences.map((f) => (
          <li
            key={f.id}
            className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2"
          >
            <button type="button" onClick={() => edit(f)} className="min-h-[44px] min-w-0 flex-1 text-left">
              <span className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                {f.shape === 'circle' ? <Circle size={14} /> : <Hexagon size={14} />}
                <span className="truncate">{f.name}</span>
                {!f.active && (
                  <span className="rounded bg-surface-secondary px-1.5 text-2xs text-content-tertiary">
                    {t('field_clock.fence_inactive', { defaultValue: 'inactive' })}
                  </span>
                )}
              </span>
              <span className="text-xs text-content-tertiary">
                {f.shape === 'circle'
                  ? t('field_clock.fence_circle_summary', {
                      defaultValue: 'Circle, radius {{radius}} m, tolerance {{tolerance}} m',
                      radius: f.radius_m ?? 0,
                      tolerance: f.tolerance_m,
                    })
                  : t('field_clock.fence_polygon_summary', {
                      defaultValue_one: 'Polygon, {{count}} corner, tolerance {{tolerance}} m',
                      defaultValue_other: 'Polygon, {{count}} corners, tolerance {{tolerance}} m',
                      count: f.polygon.length,
                      tolerance: f.tolerance_m,
                    })}
              </span>
            </button>
            <button
              type="button"
              onClick={() => void del(f)}
              aria-label={t('common.delete', { defaultValue: 'Delete' })}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary"
            >
              <Trash2 size={16} />
            </button>
          </li>
        ))}
        {fencesQ.isSuccess && fences.length === 0 && !draft && (
          <li className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-content-tertiary">
            {t('field_clock.fences_empty', {
              defaultValue: 'No site area yet. Without one, every clock tap is flagged for approval.',
            })}
          </li>
        )}
      </ul>

      {draft && (
        <div className="space-y-3 rounded-xl border border-border-light bg-surface-primary p-4">
          <div>
            <label htmlFor="fence-name" className={label}>
              {t('field_clock.fence_name', { defaultValue: 'Name' })}
            </label>
            <input
              id="fence-name"
              className={field}
              value={draft.name}
              onChange={(e) => patch({ name: e.target.value })}
            />
          </div>

          <div className="inline-flex overflow-hidden rounded-lg border border-border-light">
            {(['circle', 'polygon'] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => switchShape(s)}
                className={clsx(
                  'inline-flex min-h-[44px] items-center gap-1.5 px-4 text-sm font-medium',
                  draft.shape === s
                    ? 'bg-oe-blue text-content-inverse'
                    : 'bg-surface-primary text-content-secondary',
                )}
              >
                {s === 'circle' ? <Circle size={14} /> : <Hexagon size={14} />}
                {s === 'circle'
                  ? t('field_clock.shape_circle', { defaultValue: 'Circle' })
                  : t('field_clock.shape_polygon', { defaultValue: 'Polygon' })}
              </button>
            ))}
          </div>

          {draft.shape === 'circle' ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label htmlFor="fence-lat" className={label}>
                  {t('field_clock.latitude', { defaultValue: 'Latitude' })}
                </label>
                <input
                  id="fence-lat"
                  inputMode="decimal"
                  className={field}
                  value={draft.lat}
                  onChange={(e) => patch({ lat: e.target.value })}
                />
              </div>
              <div>
                <label htmlFor="fence-lng" className={label}>
                  {t('field_clock.longitude', { defaultValue: 'Longitude' })}
                </label>
                <input
                  id="fence-lng"
                  inputMode="decimal"
                  className={field}
                  value={draft.lng}
                  onChange={(e) => patch({ lng: e.target.value })}
                />
              </div>
              <div>
                <label htmlFor="fence-radius" className={label}>
                  {t('field_clock.radius_m', { defaultValue: 'Radius (m)' })}
                </label>
                <input
                  id="fence-radius"
                  inputMode="decimal"
                  className={field}
                  value={draft.radius}
                  onChange={(e) => patch({ radius: e.target.value })}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <label htmlFor="fence-vertices" className={label}>
                {t('field_clock.vertices', { defaultValue: 'Corners (latitude, longitude per line)' })}
              </label>
              <textarea
                id="fence-vertices"
                rows={4}
                className="w-full rounded-lg border border-border-light bg-surface-primary p-3 font-mono text-sm text-content-primary"
                value={vertexText}
                onChange={(e) => {
                  setVertexText(e.target.value);
                  const parsed = parseVertices(e.target.value);
                  if (parsed) patch({ points: parsed });
                }}
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={undoPoint}
                  disabled={draft.points.length === 0}
                  className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg border border-border-light px-3 text-sm text-content-secondary disabled:opacity-50"
                >
                  <Undo2 size={14} />
                  {t('field_clock.undo_corner', { defaultValue: 'Undo last corner' })}
                </button>
                {mapOk && (
                  <button
                    type="button"
                    onClick={() => setStep(step === 'vertices' ? 'idle' : 'vertices')}
                    className="min-h-[44px] rounded-lg border border-border-light px-3 text-sm text-content-secondary"
                  >
                    {step === 'vertices'
                      ? t('field_clock.close_shape', { defaultValue: 'Close shape' })
                      : t('field_clock.add_corners', { defaultValue: 'Add corners on the map' })}
                  </button>
                )}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="fence-tol" className={label}>
                {t('field_clock.tolerance_m', { defaultValue: 'Tolerance (m)' })}
              </label>
              <input
                id="fence-tol"
                inputMode="decimal"
                className={field}
                value={draft.tolerance}
                onChange={(e) => patch({ tolerance: e.target.value })}
              />
              <p className="mt-1 text-2xs text-content-tertiary">
                {t('field_clock.tolerance_hint', {
                  defaultValue: 'GPS drifts. Taps this close to the edge still count as inside.',
                })}
              </p>
            </div>
            <div>
              <label htmlFor="fence-cost" className={label}>
                {t('field_clock.default_cost_code', { defaultValue: 'Default cost code' })}
              </label>
              <input
                id="fence-cost"
                className={field}
                value={draft.costCode}
                onChange={(e) => patch({ costCode: e.target.value })}
              />
              <p className="mt-1 text-2xs text-content-tertiary">
                {t('field_clock.default_cost_code_hint', {
                  defaultValue: 'Put on timesheet lines built from shifts inside this area.',
                })}
              </p>
            </div>
          </div>

          <fieldset>
            <legend className={label}>
              {t('field_clock.supervisors', { defaultValue: 'Supervisors who approve outside taps' })}
            </legend>
            <div className="flex flex-col gap-1">
              {(membersQ.data ?? []).map((m) => (
                <label key={m.user_id} className="flex min-h-[44px] items-center gap-2 text-sm text-content-primary">
                  <input
                    type="checkbox"
                    className="h-5 w-5"
                    checked={draft.supervisors.includes(m.user_id)}
                    onChange={(e) =>
                      patch({
                        supervisors: e.target.checked
                          ? [...draft.supervisors, m.user_id]
                          : draft.supervisors.filter((id) => id !== m.user_id),
                      })
                    }
                  />
                  {m.full_name || m.email}
                </label>
              ))}
              {membersQ.isSuccess && (membersQ.data ?? []).length === 0 && (
                <p className="text-xs text-content-tertiary">
                  {t('field_clock.no_members', { defaultValue: 'No project members found.' })}
                </p>
              )}
            </div>
          </fieldset>

          <label className="flex min-h-[44px] items-center gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              className="h-5 w-5"
              checked={draft.active}
              onChange={(e) => patch({ active: e.target.checked })}
            />
            {t('field_clock.fence_active', { defaultValue: 'Active' })}
          </label>

          <div className="flex flex-col gap-2 sm:flex-row-reverse">
            <button
              type="button"
              disabled={!valid || saving}
              onClick={() => void save()}
              className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-oe-blue px-4 text-sm font-semibold text-content-inverse disabled:opacity-50"
            >
              {saving && <Loader2 size={15} className="animate-spin" />}
              {t('common.save', { defaultValue: 'Save' })}
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(null);
                setStep('idle');
              }}
              className="min-h-[44px] flex-1 rounded-lg border border-border-light px-4 text-sm text-content-secondary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
