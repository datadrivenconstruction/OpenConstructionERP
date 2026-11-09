// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Concrete mixes: add a mix (method, datum or activation energy, curve) and keep
 * its calibration table of cube results, from which the curve and R² are fitted.
 * A mix's own datum temperature (or activation energy) can be changed by hand.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  createSensorMix,
  fetchCalibration,
  fetchSensorMixes,
  saveCalibration,
  updateSensorMix,
  type MaturityMethod,
} from '../api';
import { calibrationWarnings, parseCalibrationRows, type CalibrationRow } from '../calibration';
import { useSensorUnits } from '../useSensorUnits';

const FIELD = 'h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';
const LABEL = 'text-xs text-content-secondary';

export function MixForms({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const u = useSensorUnits(projectId);
  const addToast = useToastStore((s) => s.addToast);
  const refresh = () => qc.invalidateQueries({ queryKey: ['site-sensors'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const mixQ = useQuery({ queryKey: ['site-sensors', 'mixes', projectId], queryFn: () => fetchSensorMixes(projectId) });
  const mixes = mixQ.data ?? [];

  const [code, setCode] = useState('');
  const [method, setMethod] = useState<MaturityMethod>('nurse_saul');
  const [datum, setDatum] = useState('0');
  const [ea, setEa] = useState('40');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [strip, setStrip] = useState('');
  const createMut = useMutation({
    mutationFn: () =>
      createSensorMix({
        project_id: projectId,
        code: code.trim(),
        method,
        datum_temp_c: datum || '0',
        activation_energy_kj_mol: ea || '40',
        curve_a: a.trim(),
        curve_b: b.trim(),
        strip_strength_mpa: strip.trim() || null,
      }),
    onSuccess: (m) => {
      setCode('');
      setA('');
      setB('');
      setMixId(m.id);
      refresh();
    },
    onError,
  });

  const [mixId, setMixId] = useState('');
  const [rows, setRows] = useState<CalibrationRow[]>([]);
  const calQ = useQuery({
    queryKey: ['site-sensors', 'calibration', mixId],
    queryFn: () => fetchCalibration(mixId),
    enabled: !!mixId,
  });
  useEffect(() => {
    if (calQ.data) {
      setRows(calQ.data.points.map((p) => ({ index: String(p.maturity_index), mpa: String(p.strength_mpa) })));
    }
  }, [calQ.data]);
  const saveMut = useMutation({
    mutationFn: () => saveCalibration(mixId, parseCalibrationRows(rows)),
    onSuccess: refresh,
    onError,
  });
  const [ownDatum, setOwnDatum] = useState('');
  const [ownEa, setOwnEa] = useState('');
  useEffect(() => {
    const m = calQ.data?.mix;
    setOwnDatum(m ? String(Number(m.datum_temp_c)) : '');
    setOwnEa(m ? String(Number(m.activation_energy_kj_mol)) : '');
  }, [calQ.data?.mix]);
  const mixMut = useMutation({
    mutationFn: () =>
      updateSensorMix(
        mixId,
        calQ.data?.mix.method === 'equivalent_age' ? { activation_energy_kj_mol: ownEa } : { datum_temp_c: ownDatum },
      ),
    onSuccess: refresh,
    onError,
  });
  const fitted = calQ.data?.mix;
  const warnings = calibrationWarnings(parseCalibrationRows(rows).length, fitted?.fit_r2 ?? null);
  const selected = mixes.find((m) => m.id === mixId);
  const indexLabel =
    selected?.method === 'equivalent_age'
      ? t('site_sensors.calibration.index_h', { defaultValue: 'Equivalent age (h)' })
      : t('site_sensors.calibration.index_c_h', { defaultValue: 'Maturity (°C·h)' });

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card id="sensor-add-mix">
        <CardHeader title={t('site_sensors.mixes.add', { defaultValue: 'Add mix' })} />
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <label className={LABEL}>
              {t('site_sensors.forms.code', { defaultValue: 'Code' })}
              <input type="text" value={code} maxLength={50} onChange={(e) => setCode(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={LABEL}>
              {t('site_sensors.mixes.method', { defaultValue: 'Maturity method' })}
              <select value={method} onChange={(e) => setMethod(e.target.value as MaturityMethod)} className={`${FIELD} mt-1 w-full`}>
                <option value="nurse_saul">{t('site_sensors.mixes.nurse_saul', { defaultValue: 'Nurse-Saul (temperature-time factor)' })}</option>
                <option value="equivalent_age">{t('site_sensors.mixes.equivalent_age', { defaultValue: 'Equivalent age (Arrhenius)' })}</option>
              </select>
            </label>
            {method === 'nurse_saul' ? (
              <label className={`${LABEL} col-span-2`}>
                {t('site_sensors.mixes.datum', { defaultValue: 'Datum temperature ({{unit}})', unit: u.label('degC') })}
                <input type="number" step="0.5" value={datum} onChange={(e) => setDatum(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                <span className="mt-1 block text-2xs text-content-tertiary">
                  {t('site_sensors.mixes.datum_hint', {
                    defaultValue: '0 °C per ASTM C1074 by default; use your lab value when the mix was calibrated with another.',
                  })}
                </span>
              </label>
            ) : (
              <label className={`${LABEL} col-span-2`}>
                {t('site_sensors.mixes.activation_energy', { defaultValue: 'Activation energy (kJ/mol)' })}
                <input type="number" step="1" min="1" value={ea} onChange={(e) => setEa(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                <span className="mt-1 block text-2xs text-content-tertiary">
                  {t('site_sensors.mixes.activation_hint', {
                    defaultValue: '40 kJ/mol at a 20 °C reference by default; use your lab value.',
                  })}
                </span>
              </label>
            )}
            <label className={LABEL}>
              {t('site_sensors.mixes.curve_a', { defaultValue: 'Curve a (MPa)' })}
              <input type="number" step="any" value={a} onChange={(e) => setA(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={LABEL}>
              {t('site_sensors.mixes.curve_b', { defaultValue: 'Curve b (MPa per decade)' })}
              <input type="number" step="any" min="0" value={b} onChange={(e) => setB(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={`${LABEL} col-span-2`}>
              {t('site_sensors.mixes.strip_strength', { defaultValue: 'Strike strength (MPa)' })}
              <input type="number" step="0.5" min="0" value={strip} onChange={(e) => setStrip(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
          </div>
          <Button
            className="mt-3"
            variant="primary"
            size="md"
            icon={<Plus size={14} />}
            disabled={!code.trim() || !a.trim() || !(Number(b) > 0)}
            loading={createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            {t('site_sensors.mixes.add', { defaultValue: 'Add mix' })}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={t('site_sensors.calibration.title', { defaultValue: 'Calibration cubes' })}
          subtitle={t('site_sensors.calibration.subtitle', {
            defaultValue: 'Maturity at test against measured strength; the curve is fitted to them.',
          })}
        />
        <CardContent>
          {mixes.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('site_sensors.mixes.empty', { defaultValue: 'No mixes yet. Add one to estimate strength from maturity.' })}
            </p>
          ) : (
            <div className="space-y-3">
              <select
                value={mixId}
                onChange={(e) => setMixId(e.target.value)}
                aria-label={t('site_sensors.forms.mix', { defaultValue: 'Concrete mix' })}
                className={`${FIELD} w-full`}
              >
                <option value="">{t('site_sensors.calibration.pick_mix', { defaultValue: 'Choose a mix' })}</option>
                {mixes.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.code}
                  </option>
                ))}
              </select>
              {mixId && (
                <>
                  {fitted && fitted.project_id && (
                    <div className="flex flex-wrap items-end gap-2">
                      {fitted.method === 'equivalent_age' ? (
                        <label className={LABEL}>
                          {t('site_sensors.mixes.activation_energy', { defaultValue: 'Activation energy (kJ/mol)' })}
                          <input type="number" step="1" min="1" value={ownEa} onChange={(e) => setOwnEa(e.target.value)} className={`${FIELD} mt-1 w-32`} />
                        </label>
                      ) : (
                        <label className={LABEL}>
                          {t('site_sensors.mixes.datum', { defaultValue: 'Datum temperature ({{unit}})', unit: u.label('degC') })}
                          <input type="number" step="0.5" min="-30" max="30" value={ownDatum} onChange={(e) => setOwnDatum(e.target.value)} className={`${FIELD} mt-1 w-32`} />
                        </label>
                      )}
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={fitted.method === 'equivalent_age' ? !(Number(ownEa) > 0) : ownDatum.trim() === '' || !Number.isFinite(Number(ownDatum))}
                        loading={mixMut.isPending}
                        onClick={() => mixMut.mutate()}
                      >
                        {t('site_sensors.mixes.save_own', { defaultValue: 'Use for this mix' })}
                      </Button>
                    </div>
                  )}
                  <p className="text-2xs text-content-tertiary">
                    {t('site_sensors.calibration.manual_hint', {
                      defaultValue: 'Enter your own strength-maturity points by hand, then save: the curve is fitted to them.',
                    })}
                  </p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-content-tertiary">
                        <th className="font-medium">{indexLabel}</th>
                        <th className="font-medium">{t('site_sensors.calibration.strength', { defaultValue: 'Strength (MPa)' })}</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i}>
                          <td className="pr-2 py-1">
                            <input
                              type="number"
                              step="any"
                              min="0"
                              value={r.index}
                              aria-label={indexLabel}
                              onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, index: e.target.value } : x)))}
                              className={`${FIELD} w-full`}
                            />
                          </td>
                          <td className="pr-2 py-1">
                            <input
                              type="number"
                              step="any"
                              min="0"
                              value={r.mpa}
                              aria-label={t('site_sensors.calibration.strength', { defaultValue: 'Strength (MPa)' })}
                              onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, mpa: e.target.value } : x)))}
                              className={`${FIELD} w-full`}
                            />
                          </td>
                          <td className="w-8">
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={t('common.delete', { defaultValue: 'Delete' })}
                              icon={<Trash2 size={13} />}
                              onClick={() => setRows(rows.filter((_, j) => j !== i))}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="secondary" size="sm" icon={<Plus size={13} />} onClick={() => setRows([...rows, { index: '', mpa: '' }])}>
                      {t('site_sensors.calibration.add_point', { defaultValue: 'Add cube' })}
                    </Button>
                    <Button variant="primary" size="sm" loading={saveMut.isPending} onClick={() => saveMut.mutate()}>
                      {t('site_sensors.calibration.save', { defaultValue: 'Save and fit' })}
                    </Button>
                    {fitted && fitted.fit_r2 !== null && (
                      <span className="text-xs tabular-nums text-content-secondary">
                        {t('site_sensors.calibration.fit', {
                          defaultValue: 'S = {{a}} + {{b}} · log(M), R² {{r2}}',
                          a: fmtNumber(fitted.curve_a, 2),
                          b: fmtNumber(fitted.curve_b, 2),
                          r2: fmtNumber(fitted.fit_r2, 3),
                        })}
                      </span>
                    )}
                  </div>
                  {warnings.map((w) => (
                    <p key={w} className="text-xs font-medium text-semantic-warning">
                      {w === 'few_points'
                        ? t('site_sensors.calibration.few_points', { defaultValue: 'Use at least 4 cubes.' })
                        : t('site_sensors.calibration.low_r2', { defaultValue: 'R² below 0.9: check the cube results.' })}
                    </p>
                  ))}
                </>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
