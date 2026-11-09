// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Device forms​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for site sensors: add a built-in or a custom device; readings live in ReadingsPanel.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { createSensorDevice, fetchSensorMixes, type SensorKind } from '../api';
import { BimElementSelect, type BimLink } from './BimElementSelect';
import { KIND_LABELS, KIND_ORDER, customDefinitionError, isoFromLocal } from '../sensorData';
import { useSensorUnits } from '../useSensorUnits';

/** Frequency bands for a graded vibration table; zones and classes come from the country data. */
const FREQUENCY_BANDS = ['lt10', '10_50', '50_100', 'gt100'] as const;

const FIELD = 'h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';
const LABEL = 'text-xs text-content-secondary';

export function DeviceForms({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const refresh = () => qc.invalidateQueries({ queryKey: ['site-sensors'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [kind, setKind] = useState<SensorKind>('concrete_maturity');
  const [limit, setLimit] = useState('');
  const [mixId, setMixId] = useState('');
  const [pourRef, setPourRef] = useState('');
  const [castAt, setCastAt] = useState('');
  const [zone, setZone] = useState('');
  const [buildingClass, setBuildingClass] = useState('');
  const [band, setBand] = useState('');
  const [unit, setUnit] = useState('');
  const [lower, setLower] = useState('');
  const [windowH, setWindowH] = useState('');
  const [limitNote, setLimitNote] = useState('');
  const [recordOnly, setRecordOnly] = useState(false);
  const isCustom = kind === 'custom';
  const customError = isCustom ? customDefinitionError({ unit, upper: limit, lower, recordOnly }) : null;
  const { context } = useSensorUnits(projectId);
  const grading = context?.limit_grading;
  const noiseZones = grading?.noise_zones ?? [];
  const buildingClasses = grading?.building_classes ?? [];
  const noiseGraded = noiseZones.length > 0;
  const vibrationGraded = buildingClasses.length > 0;
  const ungradedSource =
    kind === 'noise' && !noiseGraded ? grading?.noise_source : kind === 'vibration' && !vibrationGraded ? grading?.vibration_source : '';
  const [bim, setBim] = useState<BimLink>({ modelId: '', elementId: '' });

  const mixQ = useQuery({
    queryKey: ['site-sensors', 'mixes', projectId],
    queryFn: () => fetchSensorMixes(projectId),
    enabled: kind === 'concrete_maturity',
  });

  const createMut = useMutation({
    mutationFn: () =>
      createSensorDevice({
        project_id: projectId,
        code: code.trim(),
        name: name.trim(),
        kind,
        limit_value: recordOnly ? null : limit.trim() || null,
        ...(limitNote.trim() ? { limit_note: limitNote.trim() } : {}),
        ...(isCustom
          ? {
              unit: unit.trim(),
              lower_limit: recordOnly ? null : lower.trim() || null,
              rolling_mean_hours: windowH.trim() ? Number(windowH) : null,
              record_only: recordOnly,
            }
          : {}),
        ...(bim.modelId ? { bim_model_id: bim.modelId, bim_element_id: bim.elementId || null } : {}),
        ...(kind === 'concrete_maturity'
          ? { mix_id: mixId || null, pour_ref: pourRef.trim(), cast_at: isoFromLocal(castAt) }
          : {}),
        ...(kind === 'noise' && noiseGraded ? { noise_zone: zone } : {}),
        ...(kind === 'vibration' && vibrationGraded ? { building_class: buildingClass, frequency_band: band } : {}),
      }),
    onSuccess: () => {
      setCode('');
      setName('');
      setLimit('');
      setPourRef('');
      setUnit('');
      setLower('');
      setWindowH('');
      setLimitNote('');
      setRecordOnly(false);
      setBim({ modelId: '', elementId: '' });
      refresh();
    },
    onError,
  });

  return (
    <div className="grid gap-5">
      <Card id="sensor-add-device">
        <CardHeader title={t('site_sensors.forms.add_device', { defaultValue: 'Add device' })} />
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <label className={LABEL}>
              {t('site_sensors.forms.code', { defaultValue: 'Code' })}
              <input type="text" value={code} maxLength={50} onChange={(e) => setCode(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={LABEL}>
              {t('site_sensors.forms.name', { defaultValue: 'Name' })}
              <input type="text" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={LABEL}>
              {t('site_sensors.forms.kind', { defaultValue: 'Kind' })}
              <select value={kind} onChange={(e) => setKind(e.target.value as SensorKind)} className={`${FIELD} mt-1 w-full`}>
                {KIND_ORDER.map((k) => (
                  <option key={k} value={k}>
                    {t(`site_sensors.kind.${k}`, { defaultValue: KIND_LABELS[k] })}
                  </option>
                ))}
              </select>
            </label>
            <label className={LABEL}>
              {isCustom
                ? t('site_sensors.custom.upper', { defaultValue: 'Upper limit' })
                : t('site_sensors.forms.limit', { defaultValue: 'Limit (blank = country default)' })}
              <input type="number" step="any" value={limit} disabled={isCustom && recordOnly} onChange={(e) => setLimit(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            {isCustom && (
              <>
                <label className={LABEL}>
                  {t('site_sensors.custom.unit', { defaultValue: 'Unit' })}
                  <input type="text" value={unit} maxLength={20} placeholder={t('site_sensors.custom.unit_placeholder', { defaultValue: 'e.g. kN, %RH, m3/h' })} onChange={(e) => setUnit(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                </label>
                <label className={LABEL}>
                  {t('site_sensors.custom.lower', { defaultValue: 'Lower limit' })}
                  <input type="number" step="any" value={lower} disabled={recordOnly} onChange={(e) => setLower(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                </label>
                <label className={LABEL}>
                  {t('site_sensors.custom.window', { defaultValue: 'Rolling mean (hours, optional)' })}
                  <input type="number" step="any" min="0" value={windowH} disabled={recordOnly} onChange={(e) => setWindowH(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                </label>
                <label className={`${LABEL} col-span-2 flex items-center gap-2`}>
                  <input type="checkbox" checked={recordOnly} onChange={(e) => setRecordOnly(e.target.checked)} />
                  {t('site_sensors.custom.record_only', { defaultValue: 'Record only, no limit check' })}
                </label>
              </>
            )}
            {(isCustom || limit.trim() !== '') && (
              <label className={`${LABEL} col-span-2`}>
                {isCustom
                  ? t('site_sensors.custom.limit_note', { defaultValue: 'Where the limits come from' })
                  : t('site_sensors.limits.reason', { defaultValue: 'Reason or source of the limit' })}
                <input type="text" value={limitNote} maxLength={300} onChange={(e) => setLimitNote(e.target.value)} className={`${FIELD} mt-1 w-full`} />
              </label>
            )}
            {customError && (
              <p className="col-span-2 text-xs font-medium text-semantic-warning">
                {t(`site_sensors.custom.error_${customError}`, {
                  defaultValue:
                    customError === 'unit_required'
                      ? 'Enter the unit the sensor measures in.'
                      : customError === 'lower_not_below_upper'
                        ? 'The lower limit must be below the upper limit.'
                        : 'Set an upper or a lower limit, or mark the sensor record only.',
                })}
              </p>
            )}
            {ungradedSource && (
              <p className={`${LABEL} col-span-2`}>
                {t('site_sensors.forms.limit_from', { defaultValue: 'Country limit: {{source}}', source: ungradedSource })}
              </p>
            )}
            {kind === 'noise' && noiseGraded && (
              <label className={`${LABEL} col-span-2`}>
                {t('site_sensors.forms.noise_zone', { defaultValue: 'Noise zone' })}
                <select value={zone} onChange={(e) => setZone(e.target.value)} className={`${FIELD} mt-1 w-full`}>
                  <option value="">{t('site_sensors.forms.zone_default', { defaultValue: 'Country default' })}</option>
                  {noiseZones.map((z) => (
                    <option key={z} value={z}>
                      {t(`site_sensors.zone.${z}`, { defaultValue: z })}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {kind === 'vibration' && vibrationGraded && (
              <>
                <label className={LABEL}>
                  {t('site_sensors.forms.building_class', { defaultValue: 'Building class' })}
                  <select value={buildingClass} onChange={(e) => setBuildingClass(e.target.value)} className={`${FIELD} mt-1 w-full`}>
                    <option value="">{t('site_sensors.forms.zone_default', { defaultValue: 'Country default' })}</option>
                    {buildingClasses.map((c) => (
                      <option key={c} value={c}>
                        {t(`site_sensors.building_class.${c}`, { defaultValue: c })}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={LABEL}>
                  {t('site_sensors.forms.frequency_band', { defaultValue: 'Frequency band' })}
                  <select value={band} onChange={(e) => setBand(e.target.value)} className={`${FIELD} mt-1 w-full`}>
                    <option value="">{t('site_sensors.forms.band_reading', { defaultValue: 'From each reading' })}</option>
                    {FREQUENCY_BANDS.map((b) => (
                      <option key={b} value={b}>
                        {t(`site_sensors.band.${b}`, { defaultValue: b })}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <BimElementSelect projectId={projectId} value={bim} onChange={setBim} />
            {kind === 'concrete_maturity' && (
              <>
                <label className={LABEL}>
                  {t('site_sensors.forms.mix', { defaultValue: 'Concrete mix' })}
                  <select value={mixId} onChange={(e) => setMixId(e.target.value)} className={`${FIELD} mt-1 w-full`}>
                    <option value="">{t('site_sensors.forms.no_mix', { defaultValue: 'None' })}</option>
                    {(mixQ.data ?? []).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.code}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={LABEL}>
                  {t('site_sensors.forms.pour_ref', { defaultValue: 'Pour reference' })}
                  <input type="text" value={pourRef} maxLength={200} onChange={(e) => setPourRef(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                </label>
                <label className={`${LABEL} col-span-2`}>
                  {t('site_sensors.forms.cast_at', { defaultValue: 'Cast at' })}
                  <input type="datetime-local" value={castAt} onChange={(e) => setCastAt(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                </label>
              </>
            )}
          </div>
          <Button
            className="mt-3"
            variant="primary"
            size="md"
            icon={<Plus size={14} />}
            disabled={!code.trim() || (isCustom && (!name.trim() || customError !== null))}
            loading={createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            {t('site_sensors.forms.add_device', { defaultValue: 'Add device' })}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
