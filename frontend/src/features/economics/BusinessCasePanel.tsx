// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The business case: the investment (read from the cost frame), the revenue or
// benefit, the cost of operation and the residual value over a horizon, and the
// key figures the server derives from them. A figure that cannot be computed
// shows a dash and is never zero.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { addFlowLine, deleteFlowLine, patchPlan, type BusinessCase, type FlowKind } from './api';
import { AddRow, ConfirmDelete, Field, cleanDecimal, inputClass, isDecimal, isNegative, orDash, useMoney } from './EconomicsBits';
import { useEconomicsAction } from './hooks';
import { FLOW_KIND } from './labels';

const KINDS: FlowKind[] = ['investment', 'revenue', 'operating_cost', 'residual'];

export function BusinessCasePanel({
  projectId,
  data,
  editable,
}: {
  projectId: string;
  data: BusinessCase;
  editable: boolean;
}) {
  const { t } = useTranslation();
  const { money, plain } = useMoney(data.currency);
  const [kind, setKind] = useState<FlowKind>('revenue');
  const [label, setLabel] = useState('');
  const [amount, setAmount] = useState('');
  const [from, setFrom] = useState('1');
  const [to, setTo] = useState('');
  const [escalation, setEscalation] = useState('0');
  const [rate, setRate] = useState(data.discount_rate_pct ?? '');
  const [horizon, setHorizon] = useState(String(data.horizon_years));

  const add = useEconomicsAction(projectId, (body: Record<string, unknown>) => addFlowLine(projectId, body));
  const remove = useEconomicsAction(projectId, (id: string) => deleteFlowLine(projectId, id));
  const settings = useEconomicsAction(projectId, (body: Record<string, unknown>) => patchPlan(projectId, body));

  const k = data.key_figures;
  const figure = (value: string | null, suffix = '') => (value === null ? '-' : `${plain(value, 2)}${suffix}`);
  const tiles: { id: string; label: string; value: string; negative?: boolean }[] = [
    { id: 'npv', label: t('economics.case.npv', { defaultValue: 'Net present value' }), value: orDash(money(k.npv)), negative: isNegative(k.npv) },
    { id: 'irr', label: t('economics.case.irr', { defaultValue: 'Internal rate of return' }), value: figure(k.irr_pct, ' %') },
    { id: 'payback', label: t('economics.case.payback', { defaultValue: 'Payback year' }), value: k.payback_year === null ? '-' : String(k.payback_year) },
    { id: 'bcr', label: t('economics.case.bcr', { defaultValue: 'Benefit-cost ratio' }), value: figure(k.benefit_cost_ratio) },
    { id: 'yield', label: t('economics.case.yield', { defaultValue: 'Yield on cost' }), value: figure(k.yield_on_cost_pct, ' %') },
    { id: 'invest', label: t('economics.case.total_investment', { defaultValue: 'Investment' }), value: money(k.total_investment) },
  ];

  return (
    <div className="space-y-4" data-testid="economics-business-case">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {tiles.map((tile) => (
          <div key={tile.id} className="rounded-lg border border-border p-3" data-testid={`economics-figure-${tile.id}`}>
            <div className="text-xs text-content-secondary">{tile.label}</div>
            <div className={tile.negative ? 'text-lg font-semibold tabular-nums text-semantic-error' : 'text-lg font-semibold tabular-nums'}>
              {tile.value}
            </div>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
            <tr>
              <th className="px-3 py-2">{t('economics.case.col_kind', { defaultValue: 'Kind' })}</th>
              <th className="px-3 py-2">{t('economics.case.col_label', { defaultValue: 'Line' })}</th>
              <th className="px-3 py-2 text-right">{t('economics.case.col_amount', { defaultValue: 'Amount' })}</th>
              <th className="px-3 py-2 text-right">{t('economics.case.col_years', { defaultValue: 'Years' })}</th>
              <th className="px-3 py-2 text-right">{t('economics.case.col_escalation', { defaultValue: 'Escalation' })}</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {data.lines.map((line) => (
              <tr key={line.id} className="border-t border-border">
                <td className="px-3 py-2">{t(FLOW_KIND[line.kind][0], { defaultValue: FLOW_KIND[line.kind][1] })}</td>
                <td className="px-3 py-2">
                  {line.label}
                  {line.source === 'cost_frame' && (
                    <span className="ml-2 text-xs text-content-secondary">
                      {t('economics.case.from_frame', { defaultValue: 'read from the cost frame' })}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {money(line.amount)}
                  {line.mode === 'per_year' && (
                    <span className="ml-1 text-xs text-content-secondary">
                      {t('economics.case.per_year', { defaultValue: 'a year' })}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {line.year_from} - {line.year_to}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{plain(line.escalation_pct, 1)} %</td>
                <td className="px-3 py-2 text-right">
                  {editable && (
                    <ConfirmDelete
                      label={t('economics.case.delete', { defaultValue: 'Delete the line' })}
                      title={t('economics.confirm.title', { defaultValue: 'Delete this entry?' })}
                      message={t('economics.confirm.flow_line', {
                        defaultValue: 'The line {{name}} is removed from the business case.',
                        name: line.label,
                      })}
                      onConfirm={() => remove(line.id)}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editable && (
        <div className="space-y-3 rounded-lg border border-border p-3">
          <AddRow
            submitLabel={t('economics.case.add', { defaultValue: 'Add a line' })}
            disabled={label.trim() === '' || !isDecimal(amount || 'x')}
            onSubmit={async () => {
              await add({
                kind,
                label: label.trim(),
                amount: cleanDecimal(amount),
                year_from: Number(from),
                year_to: to === '' ? null : Number(to),
                escalation_pct: cleanDecimal(escalation || '0'),
              });
              setLabel('');
              setAmount('');
            }}
          >
            <Field label={t('economics.case.col_kind', { defaultValue: 'Kind' })}>
              <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as FlowKind)}>
                {KINDS.filter((x) => x !== 'investment').map((x) => (
                  <option key={x} value={x}>
                    {t(FLOW_KIND[x][0], { defaultValue: FLOW_KIND[x][1] })}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('economics.case.col_label', { defaultValue: 'Line' })}>
              <input className={`${inputClass} w-56`} value={label} onChange={(e) => setLabel(e.target.value)} />
            </Field>
            <Field label={t('economics.case.col_amount', { defaultValue: 'Amount' })}>
              <input className={`${inputClass} w-32 text-right`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Field label={t('economics.case.year_from', { defaultValue: 'From year' })}>
              <input className={`${inputClass} w-20`} inputMode="numeric" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label={t('economics.case.year_to', { defaultValue: 'To year' })}>
              <input className={`${inputClass} w-20`} inputMode="numeric" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
            <Field label={t('economics.case.col_escalation', { defaultValue: 'Escalation' })}>
              <input className={`${inputClass} w-20 text-right`} inputMode="decimal" value={escalation} onChange={(e) => setEscalation(e.target.value)} />
            </Field>
          </AddRow>
          <AddRow
            submitLabel={t('economics.case.save_settings', { defaultValue: 'Save the settings' })}
            disabled={!isDecimal(rate) || !/^\d+$/.test(horizon)}
            onSubmit={() => settings({ discount_rate_pct: cleanDecimal(rate), horizon_years: Number(horizon) })}
          >
            <Field label={t('economics.case.discount_rate', { defaultValue: 'Discount rate (%)' })}>
              <input className={`${inputClass} w-28 text-right`} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
            </Field>
            <Field label={t('economics.case.horizon', { defaultValue: 'Horizon (years)' })}>
              <input className={`${inputClass} w-24`} inputMode="numeric" value={horizon} onChange={(e) => setHorizon(e.target.value)} />
            </Field>
          </AddRow>
        </div>
      )}
    </div>
  );
}
