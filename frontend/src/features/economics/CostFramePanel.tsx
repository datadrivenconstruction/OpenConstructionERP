// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cost frame: the budget by classification code, set against the estimate
// of the project's bill and against what is already committed. The server
// computes every figure; the panel only shows them and takes the inputs.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Wand2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';

import { addFrameLine, deleteFrameLine, generateFrame, patchPlan, type CostFrame } from './api';
import { AddRow, ConfirmDelete, Field, cleanDecimal, inputClass, isDecimal, isNegative, orDash, useMoney } from './EconomicsBits';
import { useEconomicsAction } from './hooks';

export function CostFramePanel({
  projectId,
  frame,
  markupAllowance,
  editable,
}: {
  projectId: string;
  frame: CostFrame;
  markupAllowance: string;
  editable: boolean;
}) {
  const { t } = useTranslation();
  const { money, plain } = useMoney(frame.currency);
  const [code, setCode] = useState('');
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [allowance, setAllowance] = useState(markupAllowance);

  const add = useEconomicsAction(projectId, (body: Record<string, unknown>) => addFrameLine(projectId, body));
  const remove = useEconomicsAction(projectId, (id: string) => deleteFrameLine(projectId, id));
  const generate = useEconomicsAction(projectId, (replace: boolean) =>
    generateFrame(projectId, { depth: 1, amounts: 'estimate', replace }),
  );
  const setAllowanceAction = useEconomicsAction(projectId, (value: string) =>
    patchPlan(projectId, { markup_allowance: value }),
  );
  // A line without a stored title of a DIN 276 project reads as the standard's own name for the group.
  const groupName = (stored: string, lineCode: string): string =>
    stored ||
    (frame.classification_standard === 'din276'
      ? t(`economics.din276.${lineCode.replace(/\s+/g, '')}`, { defaultValue: '' })
      : '');
  const totals = frame.totals;
  const canAdd = code.trim() !== '' && (amount === '' || isDecimal(amount));

  return (
    <div className="space-y-4" data-testid="economics-cost-frame">
      <p className="text-sm text-content-secondary">
        {frame.bill
          ? t('economics.frame.compared_with', {
              defaultValue: 'Compared with the bill "{{name}}" and with the commitments of the project.',
              name: frame.bill.name,
            })
          : t('economics.frame.no_bill', { defaultValue: 'The project has no bill of quantities yet, so there is nothing to compare with.' })}
      </p>

      {frame.lines.length === 0 ? (
        <EmptyState
          title={t('economics.frame.empty_title', { defaultValue: 'No cost frame yet' })}
          description={t('economics.frame.empty_body', {
            defaultValue: 'Derive the lines from the classification codes of the bill, or add them by hand.',
          })}
          action={
            editable && frame.bill ? (
              <Button size="sm" icon={<Wand2 className="h-4 w-4" />} onClick={() => generate(false)}>
                {t('economics.frame.generate', { defaultValue: 'Derive from the bill' })}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
              <tr>
                <th className="px-3 py-2">{t('economics.frame.col_code', { defaultValue: 'Code' })}</th>
                <th className="px-3 py-2">{t('economics.frame.col_title', { defaultValue: 'Cost group' })}</th>
                <th className="px-3 py-2 text-right">{t('economics.frame.col_budget', { defaultValue: 'Budget' })}</th>
                <th className="px-3 py-2 text-right">{t('economics.frame.col_estimate', { defaultValue: 'Estimate' })}</th>
                <th className="px-3 py-2 text-right">{t('economics.frame.col_committed', { defaultValue: 'Committed' })}</th>
                <th className="px-3 py-2 text-right">{t('economics.frame.col_headroom', { defaultValue: 'Headroom' })}</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {frame.lines.map((row) => (
                <tr key={row.id} className="border-t border-border">
                  <td className="px-3 py-2 font-mono text-xs">{row.code}</td>
                  <td className="px-3 py-2">{groupName(row.title, row.code)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(row.amount)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(row.estimate)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{orDash(money(row.committed))}</td>
                  <td
                    className={
                      isNegative(row.headroom)
                        ? 'px-3 py-2 text-right tabular-nums text-semantic-error'
                        : 'px-3 py-2 text-right tabular-nums'
                    }
                  >
                    {money(row.headroom)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {editable && (
                      <ConfirmDelete
                        label={t('economics.frame.delete', { defaultValue: 'Delete the line' })}
                        title={t('economics.confirm.title', { defaultValue: 'Delete this entry?' })}
                        message={t('economics.confirm.frame_line', {
                          defaultValue: 'The frame line {{name}} is removed from the cost frame.',
                          name: row.code,
                        })}
                        onConfirm={() => remove(row.id)}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t border-border bg-surface-secondary text-sm">
              <tr>
                <td className="px-3 py-2" colSpan={2}>
                  {t('economics.frame.markup_allowance', { defaultValue: 'Allowance for markups' })}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{money(totals.markup_allowance)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{money(totals.markups)}</td>
                <td colSpan={3} />
              </tr>
              <tr className="font-semibold">
                <td className="px-3 py-2" colSpan={2}>
                  {t('economics.frame.total', { defaultValue: 'Total' })}
                </td>
                <td className="px-3 py-2 text-right tabular-nums" data-testid="economics-frame-total">
                  {money(totals.frame)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{money(totals.estimate)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{orDash(money(totals.committed))}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {frame.lines.length > 0 && (
        <dl
          className="grid grid-cols-1 gap-3 rounded-lg border border-border p-3 text-sm md:grid-cols-3"
          data-testid="economics-reconciliation"
        >
          <div>
            <dt className="text-xs text-content-secondary">
              {t('economics.frame.estimate_with_markups', { defaultValue: 'Estimate including markups' })}
            </dt>
            <dd className="text-lg font-semibold tabular-nums">{money(totals.estimate)}</dd>
          </div>
          <div>
            <dt className="text-xs text-content-secondary">
              {t('economics.frame.reserve', { defaultValue: 'Reserve for rounding and contingency' })}
            </dt>
            <dd
              className={
                isNegative(totals.reserve)
                  ? 'text-lg font-semibold tabular-nums text-semantic-error'
                  : 'text-lg font-semibold tabular-nums'
              }
              data-testid="economics-reserve"
            >
              {money(totals.reserve)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-content-secondary">
              {t('economics.frame.frame_total', { defaultValue: 'Cost frame' })}
            </dt>
            <dd className="text-lg font-semibold tabular-nums">{money(totals.frame)}</dd>
          </div>
        </dl>
      )}

      {totals.unassigned_count > 0 && (
        <p className="text-sm text-semantic-warning">
          {t('economics.frame.unassigned', {
            defaultValue: '{{count}} positions of the bill sit under no frame line: {{amount}}.',
            count: totals.unassigned_count,
            amount: money(totals.estimate_unassigned),
          })}
        </p>
      )}
      {!totals.committed_available && (
        <p className="text-sm text-content-secondary">
          {t('economics.frame.commitments_unknown', {
            defaultValue: 'Commitments are not known: the project has no cost lines they could sit under.',
          })}
        </p>
      )}
      {totals.variance_pct !== null && (
        <p className="text-sm text-content-secondary">
          {t('economics.frame.variance', {
            defaultValue: 'The estimate is {{amount}} ({{pct}} %) against the frame.',
            amount: money(totals.variance),
            pct: plain(totals.variance_pct, 2),
          })}
        </p>
      )}

      {editable && (
        <div className="space-y-3 rounded-lg border border-border p-3">
          <AddRow
            submitLabel={t('economics.frame.add', { defaultValue: 'Add a line' })}
            disabled={!canAdd}
            onSubmit={async () => {
              await add({ code: code.trim(), title: title.trim(), amount: amount === '' ? '0' : cleanDecimal(amount) });
              setCode('');
              setTitle('');
              setAmount('');
            }}
          >
            <Field label={t('economics.frame.col_code', { defaultValue: 'Code' })}>
              <input className={`${inputClass} w-24`} value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <Field label={t('economics.frame.col_title', { defaultValue: 'Cost group' })}>
              <input className={`${inputClass} w-64`} value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label={t('economics.frame.col_budget', { defaultValue: 'Budget' })}>
              <input className={`${inputClass} w-36 text-right`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
          </AddRow>
          <AddRow
            submitLabel={t('economics.frame.set_allowance', { defaultValue: 'Set the allowance' })}
            disabled={!isDecimal(allowance)}
            onSubmit={() => setAllowanceAction(cleanDecimal(allowance))}
          >
            <Field label={t('economics.frame.markup_allowance', { defaultValue: 'Allowance for markups' })}>
              <input className={`${inputClass} w-40 text-right`} inputMode="decimal" value={allowance} onChange={(e) => setAllowance(e.target.value)} />
            </Field>
          </AddRow>
          {frame.lines.length > 0 && frame.bill && (
            <Button variant="secondary" size="sm" icon={<Wand2 className="h-4 w-4" />} onClick={() => generate(true)}>
              {t('economics.frame.regenerate', { defaultValue: 'Replace the lines with those of the bill' })}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
