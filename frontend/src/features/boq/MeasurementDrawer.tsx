// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measure a position's quantity by hand, with no drawing and no model.
 *
 * The platform could already take a quantity off a PDF or a converted model,
 * and it could already evaluate a measurement sheet: the lines, the safe
 * formula evaluator, the REB 23.003 and OENORM A 2063 presets and both
 * endpoints have shipped for releases. Nothing in the frontend called any of
 * it, so the only way to reach it was a hand-written HTTP request, and a user
 * asking how to enter units, height, width and length with subtotals and a
 * total was told, correctly, that there was nowhere to type them.
 *
 * The columns are the ones an estimator names, not the ones the model stores:
 * a description, how many times it repeats, up to three dimensions, and add or
 * deduct. What the server wants is a formula with named variables, so a row is
 * translated on the way out. A row with a length and a width becomes `L * B`
 * over `{L, B}` rather than `L * B * H` over a height of 1, because the
 * formula is the part a checker reads and `* 1` in it is noise that did not
 * come from the measurement.
 *
 * Arithmetic happens once, on the server. It would be faster to total the rows
 * here as they are typed, and that is exactly the shape of defect this release
 * fixed elsewhere: two places building the same answer drift, and the one the
 * user sees is not the one that gets saved. The server also works in decimals,
 * where 0.1 + 0.2 is 0.3, and it is the only side that knows which market's
 * rounding convention this project is measured under.
 *
 * Deductions are the reason `sign` exists. An opening, a void or a recess is
 * measured and subtracted rather than being arithmetic done in the estimator's
 * head, so the sheet shows what was taken off and why.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Minus, Plus, Trash2 } from 'lucide-react';

import { SideDrawer } from '@/shared/ui';
import { boqApi } from './api';
import type { MeasurementLineInput, MeasurementLineResult, MeasurementSheet, Position } from './api';
import { normalizeDecimalSeparators, parseDecimalInput } from './grid/parseDecimal';

/** One row as it is typed. Everything is a string: a half-typed "3." is not a number yet. */
interface Row {
  key: string;
  description: string;
  units: string;
  length: string;
  width: string;
  height: string;
  sign: '+' | '-';
  /**
   * Set only for a line whose formula this panel's columns cannot express, so
   * a sheet written through the API is shown as it stands instead of being
   * silently rewritten into something the columns can hold.
   */
  formula: string;
}

let rowSeq = 0;
function blankRow(): Row {
  rowSeq += 1;
  return {
    key: `r${rowSeq}`,
    description: '',
    units: '',
    length: '',
    width: '',
    height: '',
    sign: '+',
    formula: '',
  };
}

/** The product of exactly the dimensions that were filled in, in fixed order. */
function deriveFormula(row: Pick<Row, 'length' | 'width' | 'height'>): string {
  const parts: string[] = [];
  if (row.length.trim()) parts.push('L');
  if (row.width.trim()) parts.push('B');
  if (row.height.trim()) parts.push('H');
  return parts.join(' * ');
}

/** The typed fields the server will read as numbers. */
const NUMERIC_FIELDS = ['units', 'length', 'width', 'height'] as const;

/**
 * The fields in this row that are filled in but are not numbers.
 *
 * Worth being strict about, because the server is not: every dimension goes
 * through a coercion that answers 0 for anything it cannot read, and a factor
 * that answers 1, so "3,5" typed by a German, Spanish or Brazilian estimator
 * would measure as zero with nothing anywhere saying so. `parseDecimalInput`
 * is the same parser the grid's numeric cells use, so a number means the same
 * thing in both places.
 */
function invalidFields(row: Row): string[] {
  return NUMERIC_FIELDS.filter(
    (f) => row[f].trim() !== '' && parseDecimalInput(row[f]) === null,
  );
}

function toLine(row: Row): MeasurementLineInput {
  // Sent in canonical dot form: the server parses with Decimal(), which reads
  // neither a decimal comma nor a thousands separator.
  const num = (v: string) => normalizeDecimalSeparators(v.trim());
  const variables: Record<string, string> = {};
  if (row.length.trim()) variables.L = num(row.length);
  if (row.width.trim()) variables.B = num(row.width);
  if (row.height.trim()) variables.H = num(row.height);
  return {
    description: row.description.trim(),
    // A row with nothing measured yet still has to be a valid expression, or
    // the whole sheet comes back as one error and the rows above it lose their
    // subtotals while somebody is still typing into the row below.
    formula: row.formula.trim() || deriveFormula(row) || '0',
    variables,
    factor: row.units.trim() ? num(row.units) : '1',
    sign: row.sign,
  };
}

/**
 * Turn a saved line back into columns, keeping its formula when the columns
 * cannot hold it.
 *
 * A sheet may have been written by something other than this panel. If the
 * stored formula is exactly the product this panel would have derived, the
 * dimensions go back into their columns and the formula field stays empty; if
 * it is anything else, the expression is kept and shown as written, because
 * rewriting somebody's `max(2.4, L) * B` into a length and a width would
 * change the document rather than display it.
 */
function fromLine(line: MeasurementLineResult): Row {
  const vars = line.variables || {};
  const row: Row = {
    ...blankRow(),
    description: line.description || '',
    units: line.factor && line.factor !== '1' ? String(line.factor) : '',
    length: vars.L ?? '',
    width: vars.B ?? '',
    height: vars.H ?? '',
    sign: line.sign === '-' ? '-' : '+',
    formula: '',
  };
  const derived = deriveFormula(row);
  const stored = (line.formula || '').replace(/\s+/g, ' ').trim();
  if (stored && stored !== derived) {
    row.formula = line.formula;
    row.length = '';
    row.width = '';
    row.height = '';
  }
  return row;
}

export interface MeasurementDrawerProps {
  position: Position | null;
  onClose: () => void;
  /** Persisted by the caller, which owns the position mutation and its cache. */
  onSave: (quantity: number, lines: MeasurementLineInput[]) => void;
  /** True when the BoQ is locked, so the sheet is readable and not writable. */
  readOnly?: boolean;
  saving?: boolean;
}

export function MeasurementDrawer({
  position,
  onClose,
  onSave,
  readOnly = false,
  saving = false,
}: MeasurementDrawerProps) {
  const { t } = useTranslation();
  const positionId = position?.id ?? null;
  const [rows, setRows] = useState<Row[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  const stored = useQuery({
    queryKey: ['boq-measurement', positionId],
    queryFn: () => boqApi.getMeasurement(positionId as string),
    enabled: Boolean(positionId),
  });

  // Fill the columns once per position. Re-running this on every fetch would
  // overwrite whatever is being typed the moment the query refetches.
  useEffect(() => {
    if (!positionId || stored.isLoading) return;
    if (loadedFor === positionId) return;
    const lines = stored.data?.lines ?? [];
    setRows(lines.length ? lines.map(fromLine) : [blankRow(), blankRow(), blankRow()]);
    setLoadedFor(positionId);
  }, [positionId, stored.isLoading, stored.data, loadedFor]);

  useEffect(() => {
    if (!positionId) {
      setRows([]);
      setLoadedFor(null);
    }
  }, [positionId]);

  // Typed explicitly rather than inferred: the success handler feeds a state
  // setter, and an inferred `unknown` there is accepted by the compiler right
  // up until it is not.
  const compute = useMutation<MeasurementSheet, Error, MeasurementLineInput[]>({
    mutationFn: (lines) =>
      boqApi.computeMeasurement(positionId as string, { lines, unit: position?.unit }),
  });

  // The last answer is kept while a new one is in flight, so the totals do not
  // blink to nothing on every keystroke.
  const [sheet, setSheet] = useState<MeasurementSheet | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const payload = useMemo(() => rows.map(toLine), [rows]);
  const payloadKey = JSON.stringify(payload);
  const badRows = useMemo(() => {
    const map = new Map<number, string[]>();
    rows.forEach((row, i) => {
      const bad = invalidFields(row);
      if (bad.length) map.set(i, bad);
    });
    return map;
  }, [rows]);

  useEffect(() => {
    if (!positionId || !rows.length) return;
    // Holding the request back rather than sending it and marking the row: the
    // server would answer with a total that is finite and plausible and quietly
    // short by one row, and the total is the number the user trusts.
    if (badRows.size) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      compute.mutate(payload, { onSuccess: setSheet });
    }, 350);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // payloadKey rather than payload: the array is rebuilt on every render and
    // would restart the timer forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payloadKey, positionId]);

  const patch = (index: number, field: keyof Row, value: string) =>
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)));

  const total = sheet?.total_quantity ?? '';
  const current = position ? String(position.quantity ?? '') : '';
  const matches = sheet?.reconciliation?.matches ?? false;
  const measured = Number(total);
  const canSave =
    !readOnly &&
    !saving &&
    !badRows.size &&
    Boolean(sheet) &&
    !sheet?.has_errors &&
    Number.isFinite(measured);

  const numberCell =
    'w-full rounded border border-border-light bg-surface-primary px-2 py-1 text-right text-xs ' +
    'tabular-nums focus:border-accent-primary focus:outline-none disabled:opacity-60 ' +
    'aria-[invalid=true]:border-status-error aria-[invalid=true]:text-status-error';

  return (
    <SideDrawer
      open={Boolean(position)}
      onClose={onClose}
      widthClass="max-w-4xl"
      title={t('boq.measurement.title')}
      subtitle={position ? `${position.ordinal} ${position.description}` : undefined}
      busy={saving}
    >
      <div className="space-y-4">
        <p className="text-xs text-content-secondary">{t('boq.measurement.intro')}</p>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-xs">
            <thead>
              <tr className="text-content-secondary">
                <th className="px-2 py-1 text-left font-medium">
                  {t('boq.measurement.description')}
                </th>
                <th className="w-16 px-2 py-1 text-right font-medium">
                  {t('boq.measurement.units')}
                </th>
                <th className="w-20 px-2 py-1 text-right font-medium">
                  {t('boq.measurement.length')}
                </th>
                <th className="w-20 px-2 py-1 text-right font-medium">
                  {t('boq.measurement.width')}
                </th>
                <th className="w-20 px-2 py-1 text-right font-medium">
                  {t('boq.measurement.height')}
                </th>
                <th className="w-10 px-2 py-1 text-center font-medium">
                  {t('boq.measurement.sign')}
                </th>
                <th className="w-28 px-2 py-1 text-right font-medium">
                  {t('boq.measurement.subtotal')}
                </th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const line = sheet?.lines?.[index];
                return (
                  <tr key={row.key} className="border-t border-border-light align-top">
                    <td className="px-2 py-1">
                      <input
                        value={row.description}
                        onChange={(e) => patch(index, 'description', e.target.value)}
                        disabled={readOnly}
                        placeholder={t('boq.measurement.description_placeholder')}
                        className="w-full rounded border border-border-light bg-surface-primary px-2 py-1 text-xs focus:border-accent-primary focus:outline-none disabled:opacity-60"
                      />
                      {row.formula && (
                        // Shown, not hidden: this row came from a sheet whose
                        // arithmetic the columns cannot express, and blanking
                        // it would look like the line had no formula at all.
                        <input
                          value={row.formula}
                          onChange={(e) => patch(index, 'formula', e.target.value)}
                          disabled={readOnly}
                          aria-label={t('boq.measurement.formula')}
                          className="mt-1 w-full rounded border border-border-light bg-surface-secondary px-2 py-1 font-mono text-[11px] focus:border-accent-primary focus:outline-none disabled:opacity-60"
                        />
                      )}
                      {line?.error && (
                        <p className="mt-1 text-[11px] text-status-error">{line.error}</p>
                      )}
                    </td>
                    <td className="px-2 py-1">
                      <input
                        value={row.units}
                        onChange={(e) => patch(index, 'units', e.target.value)}
                        aria-invalid={badRows.get(index)?.includes('units') || undefined}
                        disabled={readOnly}
                        inputMode="decimal"
                        placeholder="1"
                        className={numberCell}
                      />
                    </td>
                    <td className="px-2 py-1">
                      <input
                        value={row.length}
                        onChange={(e) => patch(index, 'length', e.target.value)}
                        aria-invalid={badRows.get(index)?.includes('length') || undefined}
                        disabled={readOnly || Boolean(row.formula)}
                        inputMode="decimal"
                        className={numberCell}
                      />
                    </td>
                    <td className="px-2 py-1">
                      <input
                        value={row.width}
                        onChange={(e) => patch(index, 'width', e.target.value)}
                        aria-invalid={badRows.get(index)?.includes('width') || undefined}
                        disabled={readOnly || Boolean(row.formula)}
                        inputMode="decimal"
                        className={numberCell}
                      />
                    </td>
                    <td className="px-2 py-1">
                      <input
                        value={row.height}
                        onChange={(e) => patch(index, 'height', e.target.value)}
                        aria-invalid={badRows.get(index)?.includes('height') || undefined}
                        disabled={readOnly || Boolean(row.formula)}
                        inputMode="decimal"
                        className={numberCell}
                      />
                    </td>
                    <td className="px-2 py-1 text-center">
                      <button
                        type="button"
                        disabled={readOnly}
                        onClick={() => patch(index, 'sign', row.sign === '+' ? '-' : '+')}
                        aria-label={
                          row.sign === '+'
                            ? t('boq.measurement.adds')
                            : t('boq.measurement.deducts')
                        }
                        title={
                          row.sign === '+'
                            ? t('boq.measurement.adds')
                            : t('boq.measurement.deducts')
                        }
                        className={`inline-flex h-6 w-6 items-center justify-center rounded border ${
                          row.sign === '-'
                            ? 'border-status-error text-status-error'
                            : 'border-border-light text-content-secondary'
                        } disabled:opacity-60`}
                      >
                        {row.sign === '-' ? <Minus size={12} /> : <Plus size={12} />}
                      </button>
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {line && !line.error ? line.quantity : ''}
                    </td>
                    <td className="px-2 py-1 text-right">
                      <button
                        type="button"
                        disabled={readOnly || rows.length === 1}
                        onClick={() => setRows((prev) => prev.filter((_, i) => i !== index))}
                        aria-label={t('boq.measurement.remove_line')}
                        className="text-content-secondary hover:text-status-error disabled:opacity-40"
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <button
          type="button"
          disabled={readOnly}
          onClick={() => setRows((prev) => [...prev, blankRow()])}
          className="rounded border border-border-light px-3 py-1.5 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-60"
        >
          {t('boq.measurement.add_line')}
        </button>

        <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
          <div className="flex items-baseline justify-between">
            <span className="text-xs text-content-secondary">{t('boq.measurement.total')}</span>
            <span className="text-lg font-semibold tabular-nums">
              {total || '—'} {position?.unit}
            </span>
          </div>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="text-xs text-content-secondary">
              {t('boq.measurement.current_quantity')}
            </span>
            <span className="text-xs tabular-nums text-content-secondary">
              {current} {position?.unit}
            </span>
          </div>
          {sheet?.reconciliation && !matches && (
            <p className="mt-2 text-xs text-status-warning">
              {t('boq.measurement.differs', { difference: sheet.reconciliation.difference })}
            </p>
          )}
          {sheet?.has_errors && (
            <p className="mt-2 text-xs text-status-error">{t('boq.measurement.has_errors')}</p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-light px-3 py-2 text-xs text-content-primary hover:bg-surface-secondary"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            disabled={!canSave}
            onClick={() => onSave(measured, payload)}
            className="rounded-lg bg-accent-primary px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
          >
            {t('boq.measurement.apply')}
          </button>
        </div>
        {readOnly && (
          <p className="text-xs text-content-secondary">{t('boq.measurement.locked')}</p>
        )}
      </div>
    </SideDrawer>
  );
}

export default MeasurementDrawer;
