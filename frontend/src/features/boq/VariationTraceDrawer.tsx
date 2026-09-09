// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Provenance for one line of a variation's bill, set from the bill editor
 * (Issue #435).
 *
 * A variation bill is an ordinary bill, which is the point of it: it grows
 * through this editor like any other. The routes that record where a line
 * came from - PUT and DELETE on the line's trace - have existed since the bill
 * shipped, and nothing in the editor called them, so a line typed in here
 * after the bill was opened stayed untraced for as long as it existed, and the
 * `variations.boq_lines_are_traced` warning on it could not be acted on from
 * the product. This drawer is the control that was missing.
 *
 * Two statements are made here, and they are different statements. The
 * source says where the line comes from: a schedule-of-values line of one of
 * the project's contracts, or a position on one of its estimating bills, read
 * through the same hook the picker in front of opening a bill uses, so the
 * two offer exactly the same sources. The change kind says what the variation
 * does to that source - adds scope, removes it, or keeps the line at a
 * different quantity or rate - and it is the estimator's own statement. The
 * server checks the kind against the numbers and reports a contradiction on
 * the bill; it does not resolve one. The drawer says so where it can see one
 * coming, and still lets the estimator save, because an unfinished statement
 * and a wrong one are not the same thing and only the second is anybody's
 * business to stop.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, Link2, Link2Off } from 'lucide-react';
import { Button, SideDrawer } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  VARIATION_CHANGE_KINDS,
  clearVariationBOQLineTrace,
  setVariationBOQLineTrace,
  type SetVariationBOQLineTracePayload,
  type VariationBOQTrace,
  type VariationChangeKind,
} from '@/features/variations/api';
import {
  VariationSourceSelect,
  changeKindLabel,
  useVariationSourceRows,
} from '@/features/variations/VariationSourcePicker';
import type { Position } from './api';

const selectCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

type Translate = ReturnType<typeof useTranslation>['t'];

/** The one-line hint under each kind, so the choice is made on meaning rather than on a word. */
function changeKindHint(kind: VariationChangeKind, t: Translate): string {
  if (kind === 'removed') {
    return t('boq.variation_kind_removed_hint', {
      defaultValue: 'Contracted scope the variation omits. Carry it as a negative quantity.',
    });
  }
  if (kind === 'modified') {
    return t('boq.variation_kind_modified_hint', {
      defaultValue: 'The same contract line at a different quantity or rate.',
    });
  }
  return t('boq.variation_kind_added_hint', {
    defaultValue: 'New scope the contract never held.',
  });
}

/** The source key (`contract:<id>` / `boq:<id>`) a stored trace points into, or none. */
function sourceKeyOf(trace: VariationBOQTrace | undefined): string {
  if (!trace) return '';
  if (trace.contract_line_id && trace.contract_id) return `contract:${trace.contract_id}`;
  if (trace.source_position_id && trace.source_boq_id) return `boq:${trace.source_boq_id}`;
  return '';
}

/** Whether a stored trace says anything at all, i.e. whether there is something to clear. */
export function traceSaysSomething(trace: VariationBOQTrace | undefined): boolean {
  if (!trace) return false;
  return Boolean(
    trace.contract_line_id ||
      trace.source_position_id ||
      trace.note ||
      trace.change_kind !== 'added',
  );
}

/**
 * The body the PUT carries, from what the drawer holds. Exported so the test
 * can assert the wire shape without driving every control; the drawer sends
 * exactly this. A source picked under the other source kind is dropped, so
 * switching from a contract to an estimate cannot leave a contract line in
 * the body beside an estimate position.
 */
export function buildTracePayload(input: {
  sourceKind: string;
  selectedRowId: string;
  changeKind: VariationChangeKind;
  note: string;
}): SetVariationBOQLineTracePayload {
  const picked = input.selectedRowId.trim() !== '';
  return {
    contract_line_id: picked && input.sourceKind === 'contract' ? input.selectedRowId : null,
    source_position_id: picked && input.sourceKind === 'boq' ? input.selectedRowId : null,
    change_kind: input.changeKind,
    note: input.note,
  };
}

export function VariationTraceDrawer({
  variationRequestId,
  projectId,
  position,
  trace,
  readOnly,
  onClose,
}: {
  variationRequestId: string;
  projectId: string;
  position: Position;
  /** The line's stored trace row, when it has one. */
  trace: VariationBOQTrace | undefined;
  readOnly: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [changeKind, setChangeKind] = useState<VariationChangeKind>(trace?.change_kind ?? 'added');
  const [sourceKey, setSourceKey] = useState(() => sourceKeyOf(trace));
  const [selectedRowId, setSelectedRowId] = useState(
    () => trace?.contract_line_id ?? trace?.source_position_id ?? '',
  );
  const [note, setNote] = useState(trace?.note ?? '');

  const { contracts, estimates, kind: sourceKind, rows, rowsLoading, rowsError } =
    useVariationSourceRows(projectId, sourceKey);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['variations', 'request-boq', variationRequestId] });
  };

  const saveMut = useMutation({
    mutationFn: (payload: SetVariationBOQLineTracePayload) =>
      setVariationBOQLineTrace(variationRequestId, position.id, payload),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('boq.variation_trace_saved', { defaultValue: 'Trace saved' }),
      });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const clearMut = useMutation({
    mutationFn: () => clearVariationBOQLineTrace(variationRequestId, position.id),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('boq.variation_trace_cleared', { defaultValue: 'Trace cleared' }),
      });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const busy = saveMut.isPending || clearMut.isPending;
  const payload = buildTracePayload({ sourceKind, selectedRowId, changeKind, note });

  // The two contradictions the server's rule reports, said here before the
  // save so the estimator can fix them now; both are still saveable, because
  // the kind is their statement and the bill will carry the warning.
  const quantity = Number(position.quantity);
  const needsContractLine =
    (changeKind === 'removed' || changeKind === 'modified') && payload.contract_line_id === null;
  const removedButPositive = changeKind === 'removed' && Number.isFinite(quantity) && quantity > 0;
  const addedButNegative = changeKind === 'added' && Number.isFinite(quantity) && quantity < 0;

  const currentSummary = (() => {
    if (!trace || (!trace.contract_line_id && !trace.source_position_id)) {
      return t('boq.variation_trace_untraced', {
        defaultValue: 'Untraced. This line derives from nothing yet.',
      });
    }
    const source = trace.contract_line_id
      ? t('boq.variation_trace_to_contract_line', { defaultValue: 'a contract line' })
      : t('boq.variation_trace_to_position', { defaultValue: 'an estimate position' });
    return t('boq.variation_trace_current_summary', {
      defaultValue: 'Traced to {{source}} as {{kind}}.',
      source,
      kind: changeKindLabel(trace.change_kind, t).toLowerCase(),
    });
  })();

  return (
    <SideDrawer
      open
      onClose={onClose}
      widthClass="max-w-2xl"
      title={t('boq.variation_trace_title', { defaultValue: 'Where this line comes from' })}
      subtitle={`${position.ordinal} ${position.description}`.trim()}
      busy={busy}
    >
      <div className="space-y-5">
        <p className="text-xs text-content-secondary">
          {t('boq.variation_trace_intro', {
            defaultValue:
              'Name the contract line or estimate position this line comes from, and say what the variation does to it. The kind is your statement: the bill checks it against the numbers and tells you where they disagree.',
          })}
        </p>

        <p className="flex items-start gap-1.5 text-sm" data-testid="variation-trace-current">
          {trace?.contract_line_id || trace?.source_position_id ? (
            <Link2 size={14} className="mt-0.5 shrink-0 text-oe-blue" />
          ) : (
            <Link2Off size={14} className="mt-0.5 shrink-0 text-content-tertiary" />
          )}
          {currentSummary}
        </p>

        {readOnly && (
          <p className="flex items-start gap-1.5 text-xs text-content-secondary">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            {t('boq.variation_trace_locked', {
              defaultValue: 'This bill is locked, so its traces cannot be changed.',
            })}
          </p>
        )}

        <fieldset className="space-y-2" disabled={readOnly}>
          <legend className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('boq.variation_kind', { defaultValue: 'What this line does to the contract' })}
          </legend>
          {VARIATION_CHANGE_KINDS.map((option) => (
            <label
              key={option}
              className={clsx(
                'flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm',
                changeKind === option ? 'border-oe-blue bg-oe-blue/5' : 'border-border',
              )}
            >
              <input
                type="radio"
                name="variation-change-kind"
                value={option}
                checked={changeKind === option}
                onChange={() => setChangeKind(option)}
                className="mt-1"
              />
              <span className="min-w-0">
                <span className="font-medium">{changeKindLabel(option, t)}</span>
                <span className="block text-xs text-content-secondary">{changeKindHint(option, t)}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('boq.variation_trace_source', { defaultValue: 'Source' })}
          </p>
          <VariationSourceSelect
            value={sourceKey}
            onChange={(next) => {
              setSourceKey(next);
              setSelectedRowId('');
            }}
            contracts={contracts}
            estimates={estimates}
            className={selectCls}
          />

          {rowsLoading && (
            <p className="text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </p>
          )}
          {rowsError != null && (
            <p className="text-sm text-content-tertiary">{getErrorMessage(rowsError)}</p>
          )}
          {sourceKey !== '' && !rowsLoading && rows.length === 0 && (
            <p className="text-sm text-content-tertiary">
              {t('variations.boq_source_empty', {
                defaultValue: 'This source has no lines to price against.',
              })}
            </p>
          )}

          {rows.length > 0 && (
            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {rows.map((row) => (
                <li key={row.id} className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="variation-trace-source"
                    className="mt-1"
                    checked={selectedRowId === row.id}
                    onChange={() => setSelectedRowId(row.id)}
                    disabled={readOnly}
                    aria-label={`${row.code} ${row.description}`.trim()}
                  />
                  <p className="min-w-0 flex-1 truncate">
                    <span className="text-content-tertiary">{row.code}</span> {row.description || '—'}
                  </p>
                  <span className="shrink-0 text-xs text-content-tertiary">
                    {row.quantity} {row.unit}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {sourceKey === '' && (
            <p className="text-xs text-content-tertiary">
              {t('boq.variation_trace_no_source', {
                defaultValue: 'No source: the line is recorded as entered by hand.',
              })}
            </p>
          )}
        </div>

        {(needsContractLine || removedButPositive || addedButNegative) && (
          <div className="space-y-1" data-testid="variation-trace-contradictions">
            {needsContractLine && (
              <p className="flex items-start gap-1.5 text-xs text-content-secondary">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                {t('boq.variation_trace_needs_contract_line', {
                  defaultValue:
                    'A removed or modified line needs the contract line it changes. Without one the bill will flag it.',
                })}
              </p>
            )}
            {removedButPositive && (
              <p className="flex items-start gap-1.5 text-xs text-content-secondary">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                {t('boq.variation_trace_removed_positive', {
                  defaultValue:
                    'This line is marked as removed but its quantity is positive. An omission comes off the contract as a negative quantity.',
                })}
              </p>
            )}
            {addedButNegative && (
              <p className="flex items-start gap-1.5 text-xs text-content-secondary">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                {t('boq.variation_trace_added_negative', {
                  defaultValue:
                    'This line is marked as added but its quantity is negative. Scope that comes off the contract is removed, not added.',
                })}
              </p>
            )}
          </div>
        )}

        <div className="space-y-1">
          <label
            htmlFor="variation-trace-note"
            className="text-xs font-semibold uppercase tracking-wide text-content-secondary"
          >
            {t('boq.variation_trace_note', { defaultValue: 'Note' })}
          </label>
          <textarea
            id="variation-trace-note"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={readOnly}
            className={textareaCls}
            placeholder={t('boq.variation_trace_note_placeholder', {
              defaultValue: 'Why this line changes what it changes…',
            })}
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            disabled={readOnly}
            loading={saveMut.isPending}
            onClick={() => saveMut.mutate(payload)}
          >
            {t('boq.variation_trace_save', { defaultValue: 'Save trace' })}
          </Button>
          {traceSaysSomething(trace) && (
            <Button
              variant="secondary"
              icon={<Link2Off size={14} />}
              disabled={readOnly}
              loading={clearMut.isPending}
              onClick={() => clearMut.mutate()}
            >
              {t('boq.variation_trace_clear', { defaultValue: 'Clear trace' })}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      </div>
    </SideDrawer>
  );
}
