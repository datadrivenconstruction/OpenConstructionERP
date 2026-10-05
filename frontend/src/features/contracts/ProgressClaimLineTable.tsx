// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ProgressClaimLineTable — line-item breakdown of a progress claim.
//
// Read-only by default. While the claim is a draft (editable) each row
// exposes an inline Edit → Save flow that PATCHes a single claim line and
// refetches. A claim that has gone out for approval keeps the breakdown it
// was billed on, so the caller passes editable={false} and the server
// refuses the write anyway. Money values are Decimal-as-string from the API
// and are rendered via the shared MoneyDisplay so currency formatting stays
// consistent (and we never blend currencies — every line is in the claim
// currency).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Pencil, Check, X, Plus } from 'lucide-react';

import { Button, EmptyState } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  updateClaimLine,
  createClaimLine,
  type ProgressClaimLine,
  type ContractLine,
} from './api';
import { invalidateClaimAfterLineWrite } from './claimQueries';
import { billingModeErrorMessage } from './billingModeErrors';
import { getIntlLocale, fmtPercent } from '@/shared/lib/formatters';

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

const inputCls =
  'h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-right text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export interface ProgressClaimLineTableProps {
  claimId: string;
  lines: ProgressClaimLine[];
  currency: string;
  /** When false the table is strictly read-only (no edit affordances). */
  editable: boolean;
  isLoading?: boolean;
  /** Contract lines for description lookup (OC-30). When provided the
   *  "Line" column shows the description instead of a truncated UUID. */
  contractLines?: ContractLine[];
}

export function ProgressClaimLineTable({
  claimId,
  lines,
  currency,
  editable,
  isLoading = false,
  contractLines,
}: ProgressClaimLineTableProps) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  // Build a lookup map so claim lines can show the contract line description
  // instead of a truncated UUID (OC-30).
  const clMap = new Map<string, ContractLine>();
  if (contractLines) {
    for (const cl of contractLines) clMap.set(cl.id, cl);
  }
  // A claim carries one line per schedule-of-values line, so what is already
  // billed here cannot be picked again; edit that row instead.
  const pickable = (contractLines ?? []).filter(
    (cl) => !lines.some((l) => l.contract_line_id === cl.id),
  );

  if (isLoading) {
    return (
      <p className="py-4 text-sm text-content-tertiary">
        {t('common.loading', { defaultValue: 'Loading…' })}
      </p>
    );
  }

  if (lines.length === 0 && !adding) {
    return (
      <>
        <EmptyState
          title={t('contracts.claim_no_lines', { defaultValue: 'No claim lines yet' })}
          description={t('contracts.claim_no_lines_desc', {
            defaultValue:
              'Populate this claim from progress observations to bill completed work.',
          })}
        />
        {/* Populating needs the schedule of values tied to bid positions and
            observations from site. A contract written by hand has neither, and
            without this its claim could never be billed at all. */}
        {editable && pickable.length > 0 && (
          <div className="mt-2 flex justify-center">
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus size={12} />}
              onClick={() => setAdding(true)}
              data-testid="claim-add-line"
            >
              {t('contracts.claim_add_line', { defaultValue: 'Add a line by hand' })}
            </Button>
          </div>
        )}
        {editable && pickable.length === 0 && (
          <p className="mt-2 text-center text-xs text-content-tertiary">
            {t('contracts.claim_no_sov', {
              defaultValue:
                'There is nothing to bill yet: the contract has no schedule of values. Add its lines on the contract first.',
            })}
          </p>
        )}
      </>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="claim-line-table">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 text-left">
              {t('contracts.line', { defaultValue: 'Line' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('contracts.qty', { defaultValue: 'Qty' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('contracts.pct_complete', { defaultValue: '% complete' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('contracts.period_value', { defaultValue: 'Period value' })}
            </th>
            {editable && <th className="px-3 py-2 text-right" />}
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <ClaimLineRow
              key={line.id}
              claimId={claimId}
              line={line}
              currency={currency}
              editable={editable}
              clMap={clMap}
            />
          ))}
        </tbody>
        {editable && (adding || pickable.length > 0) && (
          <tfoot>
            {adding ? (
              <ClaimLineAddRow
                claimId={claimId}
                pickable={pickable}
                onDone={() => setAdding(false)}
              />
            ) : (
              <tr>
                <td colSpan={5} className="pt-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Plus size={12} />}
                    onClick={() => setAdding(true)}
                    data-testid="claim-add-line"
                  >
                    {t('contracts.claim_add_line', { defaultValue: 'Add a line by hand' })}
                  </Button>
                </td>
              </tr>
            )}
          </tfoot>
        )}
      </table>
    </div>
  );
}

/**
 * Bill one schedule-of-values line on this claim, by hand.
 *
 * The percent and the money are both asked for because neither follows from
 * the other here: a line can be half done and billed at a rate agreed later.
 * What is billed to date and column D of the G703 are worked out by the
 * server from the claims before this one, so they are not on this form.
 */
function ClaimLineAddRow({
  claimId,
  pickable,
  onDone,
}: {
  claimId: string;
  pickable: ContractLine[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [lineId, setLineId] = useState('');
  const [pct, setPct] = useState('');
  const [value, setValue] = useState('');

  const createMut = useMutation({
    mutationFn: () =>
      createClaimLine({
        progress_claim_id: claimId,
        contract_line_id: lineId,
        period_completed_pct: Number(pct) || 0,
        period_completed_value: Number(value) || 0,
      }),
    onSuccess: () => {
      invalidateClaimAfterLineWrite(qc, claimId);
      addToast({
        type: 'success',
        title: t('contracts.claim_line_saved', { defaultValue: 'Line saved' }),
      });
      onDone();
    },
    onError: (err) =>
      addToast({ type: 'error', title: billingModeErrorMessage(t, err) ?? getErrorMessage(err) }),
  });

  return (
    <tr className="border-t border-border-light">
      <td className="px-3 py-2">
        <select
          value={lineId}
          onChange={(e) => setLineId(e.target.value)}
          className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm"
          aria-label={t('contracts.line', { defaultValue: 'Line' })}
        >
          <option value="">
            — {t('common.select', { defaultValue: 'Select' })} —
          </option>
          {pickable.map((cl) => (
            <option key={cl.id} value={cl.id}>
              {[cl.code, cl.description].filter(Boolean).join(' — ') || cl.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2" />
      <td className="px-3 py-2">
        <input
          type="number"
          min={0}
          max={100}
          step="0.01"
          value={pct}
          onChange={(e) => setPct(e.target.value)}
          className={inputCls}
          aria-label={t('contracts.pct_complete', { defaultValue: '% complete' })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="number"
          min={0}
          step="0.01"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className={inputCls}
          aria-label={t('contracts.period_value', { defaultValue: 'Period value' })}
        />
      </td>
      <td className="px-3 py-2 text-right">
        <div className="flex justify-end gap-1">
          <Button
            size="sm"
            variant="primary"
            icon={<Check size={12} />}
            onClick={() => createMut.mutate()}
            loading={createMut.isPending}
            disabled={!lineId}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={<X size={12} />}
            onClick={onDone}
            disabled={createMut.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      </td>
    </tr>
  );
}

function ClaimLineRow({
  claimId,
  line,
  currency,
  editable,
  clMap,
}: {
  claimId: string;
  line: ProgressClaimLine;
  currency: string;
  editable: boolean;
  clMap: Map<string, ContractLine>;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState(false);
  const [pct, setPct] = useState(String(toNum(line.period_completed_pct)));
  const [value, setValue] = useState(String(toNum(line.period_completed_value)));

  const saveMut = useMutation({
    mutationFn: () =>
      updateClaimLine(line.id, {
        period_completed_pct: Number(pct) || 0,
        period_completed_value: Number(value) || 0,
        // cumulative_completed_value is cumulative-to-date and is recomputed
        // server-side from prior non-rejected periods; the client must not
        // author it (sending the period value here corrupted earned-value and
        // the AIA 'previous' column).
      }),
    onSuccess: () => {
      // The line is not the only thing that moved: the claim's stored gross,
      // retention and net follow its lines, and so do the G702 face and the
      // register's row. Re-read them rather than keep what is on screen.
      invalidateClaimAfterLineWrite(qc, claimId);
      addToast({
        type: 'success',
        title: t('contracts.claim_line_saved', { defaultValue: 'Line saved' }),
      });
      setEditing(false);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const startEdit = () => {
    setPct(String(toNum(line.period_completed_pct)));
    setValue(String(toNum(line.period_completed_value)));
    setEditing(true);
  };

  return (
    <tr className="border-t border-border-light hover:bg-surface-secondary">
      <td className="px-3 py-2 font-mono text-xs text-content-secondary">
        {clMap.get(line.contract_line_id)?.description || clMap.get(line.contract_line_id)?.code || line.contract_line_id.slice(0, 8)}
      </td>
      <td className="px-3 py-2 text-right text-content-secondary">
        {toNum(line.period_completed_qty).toLocaleString(getIntlLocale())}
      </td>
      <td className="px-3 py-2 text-right">
        {editing ? (
          <input
            type="number"
            min={0}
            max={100}
            step="0.01"
            value={pct}
            onChange={(e) => setPct(e.target.value)}
            className={inputCls}
            aria-label={t('contracts.pct_complete', { defaultValue: '% complete' })}
          />
        ) : (
          fmtPercent(toNum(line.period_completed_pct), 2)
        )}
      </td>
      <td className="px-3 py-2 text-right font-medium">
        {editing ? (
          <input
            type="number"
            min={0}
            step="0.01"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className={inputCls}
            aria-label={t('contracts.period_value', { defaultValue: 'Period value' })}
          />
        ) : (
          <MoneyDisplay
            amount={toNum(line.period_completed_value)}
            currency={currency || undefined}
          />
        )}
      </td>
      {editable && (
        <td className="px-3 py-2 text-right">
          {editing ? (
            <div className="flex justify-end gap-1">
              <Button
                size="sm"
                variant="primary"
                icon={<Check size={12} />}
                onClick={() => saveMut.mutate()}
                loading={saveMut.isPending}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon={<X size={12} />}
                onClick={() => setEditing(false)}
                disabled={saveMut.isPending}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              icon={<Pencil size={12} />}
              onClick={startEdit}
            >
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
          )}
        </td>
      )}
    </tr>
  );
}
