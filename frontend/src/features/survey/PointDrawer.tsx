// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One survey point: where it came from, what uses it, and an edit form. A point
 * whose set feeds a confirmed or sent volume is locked; the drawer says which one.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock } from 'lucide-react';
import { Badge, Button, SideDrawer, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { POINT_KINDS, deletePoint, getPoint, updatePoint, type PointKind, type PointUpdate } from './api';

interface Props {
  pointId: string | null;
  canWrite: boolean;
  onClose: () => void;
}

interface Form {
  point_id: string;
  code: string;
  kind: PointKind;
  e: string;
  n: string;
  z: string;
  description: string;
}

const num = (v: string) => (v.trim() === '' ? null : Number(v.replace(',', '.')));

/** Only the fields that changed go to the server; an emptied height clears Z. */
export function pointPatch(before: Form, after: Form): PointUpdate {
  const out: PointUpdate = {};
  if (after.point_id.trim() !== before.point_id) out.point_id = after.point_id.trim();
  if (after.code.trim() !== before.code) out.code = after.code.trim();
  if (after.kind !== before.kind) out.kind = after.kind;
  if (after.description !== before.description) out.description = after.description;
  for (const k of ['e', 'n'] as const) {
    if (after[k] !== before[k] && num(after[k]) != null) out[k] = num(after[k])!;
  }
  if (after.z !== before.z) {
    const z = num(after.z);
    if (z == null) out.clear_z = true;
    else out.z = z;
  }
  return out;
}

export function PointDrawer({ pointId, canWrite, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const detail = useQuery({ queryKey: ['survey', 'point', pointId], queryFn: () => getPoint(pointId!), enabled: !!pointId });
  const [form, setForm] = useState<Form | null>(null);
  const [base, setBase] = useState<Form | null>(null);

  useEffect(() => {
    const d = detail.data;
    if (!d) return;
    const f: Form = {
      point_id: d.point_id,
      code: d.code,
      kind: d.kind,
      e: d.e.toFixed(3),
      n: d.n.toFixed(3),
      z: d.z == null ? '' : d.z.toFixed(3),
      description: d.description,
    };
    setForm(f);
    setBase(f);
  }, [detail.data]);

  const done = () => qc.invalidateQueries({ queryKey: ['survey'] });
  const save = useMutation({
    mutationFn: (body: PointUpdate) => updatePoint(pointId!, body),
    onSuccess: () => {
      void done();
      addToast({ type: 'success', title: t('survey.point.saved', { defaultValue: 'Point saved' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const remove = useMutation({
    mutationFn: () => deletePoint(pointId!),
    onSuccess: () => {
      void done();
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const d = detail.data;
  const editable = canWrite && !!d && !d.locked;
  const patch = form && base ? pointPatch(base, form) : {};
  const dirty = Object.keys(patch).length > 0;
  const field = (key: keyof Form, label: string, mono = false) => (
    <label className="block">
      <span className="oe-label">{label}</span>
      <input
        className={`oe-input w-full ${mono ? 'font-mono' : ''}`}
        dir={mono ? 'ltr' : undefined}
        value={form?.[key] ?? ''}
        disabled={!editable}
        onChange={(e) => form && setForm({ ...form, [key]: e.target.value })}
        data-testid={`point-${key}`}
      />
    </label>
  );

  return (
    <SideDrawer
      open={!!pointId}
      onClose={onClose}
      title={d ? <bdi dir="ltr">{d.point_id}</bdi> : t('survey.point.title', { defaultValue: 'Point' })}
      subtitle={d ? `${d.set_name} · ${d.source_filename}${d.source_line ? ` : ${d.source_line}` : ''}` : undefined}
      widthClass="max-w-md"
      busy={save.isPending || remove.isPending}
    >
      {!d || !form ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="space-y-4 text-sm" data-testid="point-drawer">
          {d.locked && (
            <div className="flex items-start gap-2 rounded-lg bg-semantic-warning-bg p-3 text-xs">
              <Lock size={14} className="mt-0.5 shrink-0" />
              <span>
                {t('survey.point.locked', {
                  defaultValue: 'Locked: a confirmed volume was computed from this point set. Duplicate the volume or re-import the set to change it.',
                })}
              </span>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            {field('point_id', t('survey.field.point_id', { defaultValue: 'ID' }), true)}
            {field('code', t('survey.field.code', { defaultValue: 'Code' }))}
            {field('e', t('survey.field.e', { defaultValue: 'E (m)' }), true)}
            {field('n', t('survey.field.n', { defaultValue: 'N (m)' }), true)}
            {field('z', t('survey.field.z', { defaultValue: 'Z (m)' }), true)}
            <label className="block">
              <span className="oe-label">{t('survey.field.kind', { defaultValue: 'Kind' })}</span>
              <select
                className="oe-input w-full"
                value={form.kind}
                disabled={!editable}
                onChange={(e) => setForm({ ...form, kind: e.target.value as PointKind })}
              >
                {POINT_KINDS.map((k) => (
                  <option key={k} value={k}>{t(`survey.kind.${k}`, { defaultValue: k })}</option>
                ))}
              </select>
            </label>
          </div>
          {field('description', t('survey.field.description', { defaultValue: 'Description' }))}
          <div className="text-xs text-content-secondary">
            {d.stored_epsg ? <bdi dir="ltr">EPSG {d.stored_epsg}</bdi> : null}
            {d.survey_date ? ` · ${d.survey_date}` : ''}
          </div>
          <div>
            <div className="oe-label">{t('survey.point.used_by', { defaultValue: 'Used by' })}</div>
            {d.used_by.length === 0 ? (
              <p className="text-xs text-content-tertiary">{t('survey.point.used_by_none', { defaultValue: 'Nothing is built from this point yet.' })}</p>
            ) : (
              <ul className="space-y-1">
                {d.used_by.map((u) => (
                  <li key={`${u.kind}-${u.code}`} className="flex items-center gap-2">
                    <span className="font-mono text-xs">{u.code}</span>
                    <span className="flex-1 truncate">{u.name}</span>
                    {u.locked && <Badge variant="warning">{t('survey.point.locks', { defaultValue: 'Locks' })}</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {canWrite && (
            <div className="flex justify-between gap-2 border-t border-border-light pt-3">
              <Button
                variant="ghost"
                disabled={d.locked}
                onClick={() => {
                  if (window.confirm(t('survey.point.delete_confirm', { defaultValue: 'Delete point {{id}}?', id: d.point_id }))) remove.mutate();
                }}
              >
                {t('common.delete', { defaultValue: 'Delete' })}
              </Button>
              <Button variant="primary" disabled={!editable || !dirty} loading={save.isPending} onClick={() => save.mutate(patch)} data-testid="point-save">
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
          )}
        </div>
      )}
    </SideDrawer>
  );
}
