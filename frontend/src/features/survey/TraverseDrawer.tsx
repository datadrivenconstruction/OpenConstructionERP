// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * New traverse: paste the legs, read the misclosure, the ratio 1:x, the
 * verdict against the survey profile and the Bowditch corrections. A level run
 * is under Advanced options.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Badge, Button, SideDrawer } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { createTraverse, type Traverse, type TraverseInput } from './volumesApi';
import { fmtFixed } from '@/shared/lib/formatters';

const LEG_TEMPLATE = 'leg,from,to,length_m,d_e,d_n\n';

/** "1:11,731" in the reader's digits. */
export function ratioText(ratio: number | null | undefined, locale: string): string {
  return ratio ? `1:${new Intl.NumberFormat(locale).format(ratio)}` : '-';
}

export function VerdictBadge({ verdict }: { verdict: Traverse['verdict'] }) {
  const { t } = useTranslation();
  if (verdict === 'pass') return <Badge variant="success">{t('survey.status.pass', { defaultValue: 'Pass' })}</Badge>;
  if (verdict === 'fail') return <Badge variant="error">{t('survey.status.fail', { defaultValue: 'Fail' })}</Badge>;
  return <Badge variant="neutral">{t('survey.traverse.no_profile', { defaultValue: 'No profile threshold' })}</Badge>;
}

interface Props {
  open: boolean;
  projectId: string;
  onClose: () => void;
  isAdvanced: boolean;
  shown?: Traverse | null;
}

export function TraverseDrawer({ open, projectId, onClose, isAdvanced, shown }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [kind, setKind] = useState<'traverse' | 'level'>('traverse');
  const [name, setName] = useState('');
  const [text, setText] = useState(LEG_TEMPLATE);
  const [km, setKm] = useState('');
  const [mm, setMm] = useState('');
  const [result, setResult] = useState<Traverse | null>(null);
  const view = shown ?? result;

  const save = useMutation({
    mutationFn: (body: TraverseInput) => createTraverse(projectId, body),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ['survey'] });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const submit = () => {
    if (kind === 'traverse') save.mutate({ name: name.trim(), kind, text });
    else save.mutate({ name: name.trim(), kind, distance_km: Number(km), misclosure_mm: Number(mm) });
  };
  const close = () => {
    setResult(null);
    onClose();
  };
  const m = (v: number | null | undefined, d = 3) => (v == null ? '-' : fmtFixed(v, d));

  return (
    <SideDrawer
      open={open}
      onClose={close}
      title={view ? view.name : t('survey.action.new_traverse', { defaultValue: 'New traverse' })}
      widthClass="max-w-xl"
      busy={save.isPending}
    >
      {!view ? (
        <div className="space-y-3 text-sm">
          <label className="block">
            <span className="oe-label">{t('common.name', { defaultValue: 'Name' })}</span>
            <input className="oe-input w-full" value={name} onChange={(e) => setName(e.target.value)} data-testid="traverse-name" />
          </label>
          {isAdvanced && (
            <label className="block">
              <span className="oe-label">{t('survey.traverse.kind', { defaultValue: 'Kind' })}</span>
              <select className="oe-input w-full" value={kind} onChange={(e) => setKind(e.target.value as 'traverse' | 'level')}>
                <option value="traverse">{t('survey.traverse.kind_traverse', { defaultValue: 'Closed traverse' })}</option>
                <option value="level">{t('survey.traverse.kind_level', { defaultValue: 'Level run' })}</option>
              </select>
            </label>
          )}
          {kind === 'traverse' ? (
            <label className="block">
              <span className="oe-label">{t('survey.traverse.legs', { defaultValue: 'Legs (CSV: leg, from, to, length, dE, dN in metres)' })}</span>
              <textarea
                className="oe-input w-full font-mono text-xs"
                rows={8}
                dir="ltr"
                value={text}
                onChange={(e) => setText(e.target.value)}
                data-testid="traverse-legs"
              />
            </label>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="oe-label" title={t('survey.unit.km', { defaultValue: 'kilometres' })}>
                  {t('survey.traverse.distance_km', { defaultValue: 'Distance (km)' })}
                </span>
                <input className="oe-input w-full" inputMode="decimal" value={km} onChange={(e) => setKm(e.target.value)} />
              </label>
              <label className="block">
                <span className="oe-label" title={t('survey.unit.mm', { defaultValue: 'millimetres' })}>
                  {t('survey.traverse.misclosure_mm', { defaultValue: 'Misclosure (mm)' })}
                </span>
                <input className="oe-input w-full" inputMode="decimal" value={mm} onChange={(e) => setMm(e.target.value)} />
              </label>
            </div>
          )}
          <div className="flex justify-end">
            <Button variant="primary" onClick={submit} disabled={!name.trim()} data-testid="traverse-compute">
              {t('survey.traverse.compute', { defaultValue: 'Compute' })}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4 text-sm" data-testid="traverse-result">
          {view.kind === 'traverse' ? (
            <dl className="grid grid-cols-2 gap-2">
              <dt className="text-content-secondary" title={t('survey.unit.metre', { defaultValue: 'metres' })}>
                {t('survey.traverse.length', { defaultValue: 'Length (m)' })}
              </dt>
              <dd><bdi dir="ltr">{m(view.length_m, 2)}</bdi></dd>
              <dt className="text-content-secondary">{t('survey.traverse.f', { defaultValue: 'Misclosure f (m)' })}</dt>
              <dd><bdi dir="ltr">{m(view.misclosure_m)} (fE {m(view.f_e)}, fN {m(view.f_n)})</bdi></dd>
              <dt className="text-content-secondary" title={t('survey.traverse.ratio_tip', { defaultValue: 'Length divided by misclosure. Higher is better.' })}>
                {t('survey.traverse.ratio', { defaultValue: 'Ratio' })}
              </dt>
              <dd><bdi dir="ltr" data-testid="traverse-ratio">{ratioText(view.ratio, i18n.language)}</bdi></dd>
              <dt className="text-content-secondary">{t('survey.traverse.verdict', { defaultValue: 'Against the profile' })}</dt>
              <dd className="flex items-center gap-2">
                <VerdictBadge verdict={view.verdict} />
                {view.profile_ratio ? <bdi dir="ltr">{ratioText(view.profile_ratio, i18n.language)}</bdi> : null}
                {view.profile_label && <span className="text-xs text-content-tertiary">{view.profile_label}</span>}
              </dd>
            </dl>
          ) : (
            <dl className="grid grid-cols-2 gap-2">
              <dt className="text-content-secondary">{t('survey.traverse.misclosure_mm', { defaultValue: 'Misclosure (mm)' })}</dt>
              <dd><bdi dir="ltr">{m(view.misclosure_mm, 1)}</bdi></dd>
              <dt className="text-content-secondary">{t('survey.traverse.allowed_mm', { defaultValue: 'Allowed k·√km (mm)' })}</dt>
              <dd><bdi dir="ltr">{m(view.allowed_mm, 1)}</bdi></dd>
              <dt className="text-content-secondary">{t('survey.traverse.verdict', { defaultValue: 'Against the profile' })}</dt>
              <dd><VerdictBadge verdict={view.verdict} /></dd>
            </dl>
          )}
          {view.legs.length > 0 && (
            <div>
              <h3 className="oe-card-title mb-1">{t('survey.traverse.corrections', { defaultValue: 'Bowditch corrections (m)' })}</h3>
              <table className="oe-table w-full text-xs">
                <thead>
                  <tr>
                    <th>{t('survey.traverse.leg', { defaultValue: 'Leg' })}</th>
                    <th>{t('survey.traverse.from_to', { defaultValue: 'From - to' })}</th>
                    <th className="text-right">{t('survey.traverse.length', { defaultValue: 'Length (m)' })}</th>
                    <th className="text-right">cE</th>
                    <th className="text-right">cN</th>
                  </tr>
                </thead>
                <tbody>
                  {view.legs.map((leg) => (
                    <tr key={leg.leg}>
                      <td>{leg.leg}</td>
                      <td><bdi dir="ltr">{leg.from} - {leg.to}</bdi></td>
                      <td className="text-right"><bdi dir="ltr">{fmtFixed(leg.length_m, 2)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr">{fmtFixed(leg.c_e, 4)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr">{fmtFixed(leg.c_n, 4)}</bdi></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex justify-end">
            <Button variant="secondary" onClick={close}>{t('common.close', { defaultValue: 'Close' })}</Button>
          </div>
        </div>
      )}
    </SideDrawer>
  );
}
