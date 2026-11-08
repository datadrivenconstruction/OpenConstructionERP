// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The project's sensor context (country, unit system, pours ready to strike)
 * and a formatter that converts an SI value for display and labels its unit.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { fmtNumber } from '@/shared/lib/formatters';
import { fetchSensorContext } from './api';
import { UNIT_LABELS, decimalsFor, displayUnit, toDisplay, type UnitKey } from './units';

export function useSensorUnits(projectId: string) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['site-sensors', 'context', projectId],
    queryFn: () => fetchSensorContext(projectId),
    enabled: !!projectId,
  });
  const system = q.data?.unit_system ?? 'metric';
  const label = (k: UnitKey) => t(`site_sensors.units.${k}`, { defaultValue: UNIT_LABELS[k] });
  const num = (v: number | string | null | undefined, k: UnitKey | null): string => {
    if (v === null || v === undefined || v === '' || !Number.isFinite(Number(v))) return '-';
    if (!k) return fmtNumber(Number(v), 1);
    const d = toDisplay(Number(v), k, system);
    return fmtNumber(d.value, decimalsFor(d.unit));
  };
  const show = (v: number | string | null | undefined, k: UnitKey | null, fallbackUnit = ''): string => {
    const n = num(v, k);
    if (n === '-') return n;
    return `${n} ${k ? label(displayUnit(k, system)) : fallbackUnit}`.trim();
  };
  return { system, country: q.data?.country ?? '', context: q.data, label, num, show, unitFor: (k: UnitKey) => label(displayUnit(k, system)) };
}
