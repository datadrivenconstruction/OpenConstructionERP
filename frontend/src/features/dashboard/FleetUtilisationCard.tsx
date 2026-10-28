// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FleetUtilisationCard - dashboard widget: utilisation and idle share of the fleet
 * over the last 14 days, hours split and CO2, from equipment telematics.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { fetchUtilisation } from '@/features/equipment/telematicsApi';
import { idleTone, lastDaysWindow } from '@/features/equipment/telematicsFormat';
import { KpiStrip } from './KpiStrip';

export function FleetUtilisationCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const win = useMemo(() => lastDaysWindow(14), []);
  const q = useQuery({
    queryKey: ['equipment', 'telematics', 'utilisation', win.date_from, win.date_to],
    queryFn: () => fetchUtilisation(win.date_from, win.date_to),
    staleTime: 60_000,
  });
  const totals = q.data?.totals;

  if (q.isError) return null;

  return (
    <Card className="h-full">
      <CardHeader
        title={t('dashboard.layout.w_fleet_utilisation', { defaultValue: 'Fleet utilisation' })}
        subtitle={t('dashboard.fleet_util.subtitle', { defaultValue: 'Last 14 days, from machine telematics' })}
        action={
          <button
            type="button"
            onClick={() => navigate('/equipment')}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.fleet_util.open', { defaultValue: 'Open telematics' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        {!totals || totals.machines === 0 ? (
          <p className="text-sm text-content-tertiary">
            {q.isLoading
              ? t('common.loading', { defaultValue: 'Loading...' })
              : t('dashboard.fleet_util.empty', {
                  defaultValue:
                    'No machine hours yet. Import a fleet snapshot or connect a device on the Equipment page to see utilisation and idle time here.',
                })}
          </p>
        ) : (
          <div className="space-y-3">
            <KpiStrip
              stats={[
                {
                  label: t('dashboard.fleet_util.utilisation', { defaultValue: 'Utilisation' }),
                  value: `${fmtNumber(totals.utilisation_pct, 1)}%`,
                },
                {
                  label: t('dashboard.fleet_util.idle', { defaultValue: 'Idle' }),
                  value: `${fmtNumber(totals.idle_pct, 1)}%`,
                  tone: idleTone(totals.idle_pct),
                },
                {
                  label: t('dashboard.fleet_util.machines', { defaultValue: 'Machines' }),
                  value: totals.machines,
                },
              ]}
            />
            <KpiStrip
              stats={[
                { label: t('dashboard.fleet_util.worked', { defaultValue: 'Worked h' }), value: fmtNumber(totals.worked_hours, 0) },
                { label: t('dashboard.fleet_util.idle_h', { defaultValue: 'Idle h' }), value: fmtNumber(totals.idle_hours, 0) },
                { label: t('dashboard.fleet_util.off_h', { defaultValue: 'Off h' }), value: fmtNumber(totals.off_hours, 0) },
                { label: t('dashboard.fleet_util.co2', { defaultValue: 'CO2 kg' }), value: fmtNumber(totals.co2_kg, 0) },
              ]}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default FleetUtilisationCard;
