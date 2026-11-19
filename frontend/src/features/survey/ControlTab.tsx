// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Control tab: every control point with its latest check shot, the residual
 * measured minus known in millimetres, and the verdict against the profile.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Crosshair } from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtFixed } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { addControlCheck, deleteControlCheck, getControl, type ControlCheck, type ControlCheckInput } from './api';

const mm = (v: number | null | undefined) => (v == null ? '-' : fmtFixed(v, 1));

export function VerdictDot({ verdict }: { verdict: ControlCheck['verdict'] | null }) {
  const { t } = useTranslation();
  const cls = verdict === 'pass' ? 'bg-semantic-success' : verdict === 'fail' ? 'bg-semantic-error' : 'bg-content-tertiary';
  const label =
    verdict === 'pass'
      ? t('survey.status.pass', { defaultValue: 'Pass' })
      : verdict === 'fail'
        ? t('survey.status.fail', { defaultValue: 'Fail' })
        : verdict === 'no_tolerance'
          ? t('survey.control.no_tolerance', { defaultValue: 'No tolerance in the profile' })
          : t('survey.control.not_checked', { defaultValue: 'Not checked' });
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${cls}`} aria-hidden />
      <span>{label}</span>
    </span>
  );
}

/** Typed coordinates win when all of E and N are filled; otherwise the picked register point is used. */
export function checkBody(controlId: string, measuredId: string, e: string, n: string, z: string): ControlCheckInput | null {
  const val = (s: string) => (s.trim() === '' ? null : Number(s.replace(',', '.')));
  const [ev, nv, zv] = [val(e), val(n), val(z)];
  if (!controlId) return null;
  if (ev != null && nv != null && Number.isFinite(ev) && Number.isFinite(nv)) {
    return { control_point_id: controlId, e: ev, n: nv, z: zv != null && Number.isFinite(zv) ? zv : null };
  }
  return measuredId ? { control_point_id: controlId, measured_point_id: measuredId } : null;
}

interface Props {
  projectId: string;
  canWrite: boolean;
  measuredOptions: { id: string; label: string }[];
}

export function ControlTab({ projectId, canWrite, measuredOptions }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const control = useQuery({ queryKey: ['survey', 'control', projectId], queryFn: () => getControl(projectId) });
  const [cp, setCp] = useState('');
  const [measured, setMeasured] = useState('');
  const [e, setE] = useState('');
  const [n, setN] = useState('');
  const [z, setZ] = useState('');

  const done = () => qc.invalidateQueries({ queryKey: ['survey'] });
  const add = useMutation({
    mutationFn: (body: ControlCheckInput) => addControlCheck(projectId, body),
    onSuccess: () => {
      setE('');
      setN('');
      setZ('');
      setMeasured('');
      void done();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteControlCheck(projectId, id),
    onSuccess: () => void done(),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (control.isLoading) return <Skeleton className="h-40" />;
  if (control.isError) return <ErrorState title={getErrorMessage(control.error)} onRetry={() => control.refetch()} />;
  const data = control.data!;
  const body = checkBody(cp, measured, e, n, z);

  return (
    <Card className="p-0 overflow-hidden" data-testid="survey-control">
      <div className="flex flex-wrap items-center gap-3 border-b border-border-light p-3 text-sm">
        <span>
          {data.tolerance_mm != null
            ? t('survey.control.tolerance', { defaultValue: 'Tolerance {{mm}} mm ({{label}})', mm: data.tolerance_mm, label: data.profile_label })
            : t('survey.control.no_tolerance_hint', { defaultValue: 'Set a control tolerance in the survey profile to get a verdict.' })}
        </span>
        {data.failing > 0 && (
          <span className="text-semantic-error">
            {t('survey.control.failing', { defaultValue: '{{count}} out of tolerance', count: data.failing })}
          </span>
        )}
      </div>
      {data.items.length === 0 ? (
        <EmptyState
          icon={<Crosshair size={24} />}
          title={t('survey.control.empty', { defaultValue: 'No control points. Import points of kind Control first.' })}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="oe-table w-full text-sm">
            <thead>
              <tr>
                <th>{t('survey.field.point_id', { defaultValue: 'ID' })}</th>
                <th className="text-right">{t('survey.control.de', { defaultValue: 'dE (mm)' })}</th>
                <th className="text-right">{t('survey.control.dn', { defaultValue: 'dN (mm)' })}</th>
                <th className="text-right">{t('survey.control.dz', { defaultValue: 'dZ (mm)' })}</th>
                <th className="text-right">{t('survey.control.d2d', { defaultValue: 'Horizontal (mm)' })}</th>
                <th>{t('survey.control.verdict', { defaultValue: 'Verdict' })}</th>
                <th className="text-right">{t('survey.control.checks', { defaultValue: 'Checks' })}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.point.id}>
                  <td><bdi dir="ltr" className="font-mono">{row.point.point_id}</bdi></td>
                  <td className="text-right font-mono"><bdi dir="ltr">{mm(row.latest?.de_mm)}</bdi></td>
                  <td className="text-right font-mono"><bdi dir="ltr">{mm(row.latest?.dn_mm)}</bdi></td>
                  <td className="text-right font-mono"><bdi dir="ltr">{mm(row.latest?.dz_mm)}</bdi></td>
                  <td className="text-right font-mono"><bdi dir="ltr">{mm(row.latest?.d2d_mm)}</bdi></td>
                  <td><VerdictDot verdict={row.latest?.verdict ?? null} /></td>
                  <td className="text-right">{row.checks.length}</td>
                  <td className="text-right">
                    {row.latest && canWrite && (
                      <Button size="sm" variant="ghost" onClick={() => remove.mutate(row.latest!.id)}>
                        {t('survey.control.remove_check', { defaultValue: 'Remove last check' })}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canWrite && data.items.length > 0 && (
        <div className="flex flex-wrap items-end gap-2 border-t border-border-light p-3 text-sm" data-testid="control-add">
          <label className="block">
            <span className="oe-label">{t('survey.control.point', { defaultValue: 'Control point' })}</span>
            <select className="oe-input w-36" value={cp} onChange={(ev) => setCp(ev.target.value)}>
              <option value="">-</option>
              {data.items.map((row) => (
                <option key={row.point.id} value={row.point.id}>{row.point.point_id}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="oe-label">{t('survey.control.measured_point', { defaultValue: 'Measured as point' })}</span>
            <select className="oe-input w-40" value={measured} onChange={(ev) => setMeasured(ev.target.value)}>
              <option value="">-</option>
              {measuredOptions.map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
          </label>
          <span className="pb-2 text-content-tertiary">{t('survey.control.or_type', { defaultValue: 'or type' })}</span>
          {[
            [e, setE, t('survey.field.e', { defaultValue: 'E (m)' })],
            [n, setN, t('survey.field.n', { defaultValue: 'N (m)' })],
            [z, setZ, t('survey.field.z', { defaultValue: 'Z (m)' })],
          ].map(([v, set, label]) => (
            <label key={label as string} className="block">
              <span className="oe-label">{label as string}</span>
              <input
                className="oe-input w-32 font-mono"
                dir="ltr"
                inputMode="decimal"
                value={v as string}
                onChange={(ev) => (set as (s: string) => void)(ev.target.value)}
              />
            </label>
          ))}
          <Button variant="primary" disabled={!body} loading={add.isPending} onClick={() => body && add.mutate(body)}>
            {t('survey.control.add_check', { defaultValue: 'Add check' })}
          </Button>
        </div>
      )}
    </Card>
  );
}
