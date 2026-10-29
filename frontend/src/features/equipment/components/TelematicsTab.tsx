// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Telematics tab of the Equipment page: utilisation per machine for the last
 * 14 days, hire cost allocation, snapshot import, devices and rule results.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Wallet } from 'lucide-react';
import { Button, Card, CardContent, CardHeader, EmptyState, ErrorState } from '@/shared/ui';
import { RuleResultsList } from '@/shared/ui/RuleResultsList';
import { fmtCurrency, fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  allocateHire,
  fetchTelematicsValidation,
  fetchUtilisation,
  type AllocateResult,
} from '../telematicsApi';
import { barWidth, hoursShares, idleTone, lastDaysWindow } from '../telematicsFormat';
import { TelematicsImport } from './TelematicsImport';
import { TelematicsDevices } from './TelematicsDevices';

const WINDOW_DAYS = 14;

export function TelematicsTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const win = useMemo(() => lastDaysWindow(WINDOW_DAYS), []);

  const utilQ = useQuery({
    queryKey: ['equipment', 'telematics', 'utilisation', win.date_from, win.date_to],
    queryFn: () => fetchUtilisation(win.date_from, win.date_to),
  });
  const rulesQ = useQuery({
    queryKey: ['equipment', 'telematics', 'validation'],
    queryFn: () => fetchTelematicsValidation(),
  });

  const allocateMut = useMutation<AllocateResult>({
    mutationFn: () => allocateHire(win.date_from, win.date_to),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['equipment', 'telematics'] });
      addToast({
        type: r.allocated_days > 0 ? 'success' : 'info',
        title: t('equipment.telematics.allocate_done', { defaultValue: 'Hire cost allocated' }),
        message: t('equipment.telematics.allocate_result', {
          defaultValue: '{{days}} machine-days booked, {{amount}} in total.',
          days: r.allocated_days,
          amount: fmtNumber(r.amount, 2),
        }),
      });
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const data = utilQ.data;
  const totals = data?.totals;
  const machines = data?.machines ?? [];

  return (
    <div className="space-y-5" role="tabpanel" id="equipment-panel-telematics" aria-labelledby="equipment-tab-telematics">
      <Card>
        <CardHeader
          title={t('equipment.telematics.util_title', { defaultValue: 'Utilisation, last 14 days' })}
          subtitle={t('equipment.telematics.util_subtitle', {
            defaultValue: 'Worked, idle and off hours per machine, from telematics readings.',
          })}
          action={
            <Button
              variant="secondary"
              size="sm"
              icon={<Wallet size={14} />}
              loading={allocateMut.isPending}
              disabled={machines.length === 0}
              onClick={() => allocateMut.mutate()}
            >
              {t('equipment.telematics.allocate', { defaultValue: 'Allocate hire cost' })}
            </Button>
          }
        />
        <CardContent>
          {utilQ.isError ? (
            <ErrorState
              title={t('equipment.telematics.util_failed', { defaultValue: 'Could not load utilisation' })}
              hint={getErrorMessage(utilQ.error)}
              onRetry={() => utilQ.refetch()}
            />
          ) : utilQ.isLoading ? (
            <p className="py-8 text-center text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          ) : machines.length === 0 ? (
            <EmptyState
              title={t('equipment.telematics.util_empty_title', { defaultValue: 'No telematics data yet' })}
              description={t('equipment.telematics.util_empty_hint', {
                defaultValue:
                  'Import a fleet snapshot below or create a device token so a machine can report its own hours and fuel.',
              })}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
                    <th className="py-2 pr-3 font-medium">{t('equipment.telematics.col_machine', { defaultValue: 'Machine' })}</th>
                    <th className="px-2 py-2 text-right font-medium">{t('equipment.telematics.col_worked', { defaultValue: 'Worked h' })}</th>
                    <th className="px-2 py-2 text-right font-medium">{t('equipment.telematics.col_idle', { defaultValue: 'Idle h' })}</th>
                    <th className="px-2 py-2 text-right font-medium">{t('equipment.telematics.col_off', { defaultValue: 'Off h' })}</th>
                    <th className="px-2 py-2 font-medium">{t('equipment.telematics.col_util', { defaultValue: 'Utilisation' })}</th>
                    <th className="px-2 py-2 text-right font-medium">{t('equipment.telematics.col_idle_pct', { defaultValue: 'Idle %' })}</th>
                    <th className="px-2 py-2 text-right font-medium">{t('equipment.telematics.col_fuel', { defaultValue: 'Fuel L' })}</th>
                    <th className="px-2 py-2 text-right font-medium">{t('equipment.telematics.col_co2', { defaultValue: 'CO2 kg' })}</th>
                    <th className="py-2 pl-2 text-right font-medium">{t('equipment.telematics.col_hire', { defaultValue: 'Hire cost' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {machines.map((m) => {
                    const split = hoursShares(m);
                    return (
                      <tr key={m.equipment_id} className="border-b border-border-light last:border-0">
                        <td className="py-2 pr-3">
                          <div className="font-medium text-content-primary">{m.code}</div>
                          <div className="text-xs text-content-tertiary">{m.name}</div>
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(m.worked_hours, 1)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(m.idle_hours, 1)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(m.off_hours, 1)}</td>
                        <td className="px-2 py-2">
                          <div
                            className="flex h-2 w-28 overflow-hidden rounded-full bg-surface-secondary"
                            role="img"
                            aria-label={`${fmtNumber(m.utilisation_pct, 1)}%`}
                          >
                            <span className="bg-semantic-success" style={{ width: `${barWidth(split.worked)}%` }} />
                            <span className="bg-semantic-warning" style={{ width: `${barWidth(split.idle)}%` }} />
                          </div>
                          <div className="mt-0.5 text-xs tabular-nums text-content-secondary">
                            {fmtNumber(m.utilisation_pct, 1)}%
                          </div>
                        </td>
                        <td className={`px-2 py-2 text-right tabular-nums ${idleTone(m.idle_pct)}`}>
                          {fmtNumber(m.idle_pct, 1)}%
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(m.fuel_l, 1)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(m.co2_kg, 1)}</td>
                        <td className="py-2 pl-2 text-right tabular-nums">{m.currency ? fmtCurrency(m.hire_cost, m.currency) : fmtNumber(m.hire_cost, 2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                {totals && (
                  <tfoot>
                    <tr className="border-t-2 border-border-light font-semibold">
                      <td className="py-2 pr-3">
                        {t('equipment.telematics.totals', { defaultValue: 'Total' })} ({totals.machines})
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(totals.worked_hours, 1)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(totals.idle_hours, 1)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(totals.off_hours, 1)}</td>
                      <td className="px-2 py-2 text-xs tabular-nums">{fmtNumber(totals.utilisation_pct, 1)}%</td>
                      <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(totals.idle_pct, 1)}%</td>
                      <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(totals.fuel_l, 1)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{fmtNumber(totals.co2_kg, 1)}</td>
                      <td className="py-2 pl-2 text-right tabular-nums">{totals.currency ? fmtCurrency(totals.hire_cost, totals.currency) : fmtNumber(totals.hire_cost, 2)}</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <TelematicsImport />
      <TelematicsDevices />

      <Card>
        <CardHeader
          title={t('equipment.telematics.rules_title', { defaultValue: 'Telematics checks' })}
          subtitle={t('equipment.telematics.rules_subtitle', {
            defaultValue: 'Allocation, maintenance, site boundary and idle time per machine.',
          })}
        />
        <CardContent>
          {rulesQ.isError ? (
            <ErrorState
              title={t('equipment.telematics.rules_failed', { defaultValue: 'Could not load the checks' })}
              hint={getErrorMessage(rulesQ.error)}
              onRetry={() => rulesQ.refetch()}
            />
          ) : (
            <RuleResultsList results={rulesQ.data?.results ?? []} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
