// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a variation is priced against, chosen before its bill is opened
 * (Issue #435).
 *
 * The seeding endpoint has accepted `source_contract_lines` and
 * `source_positions` since the variation bill shipped, and the screen opened
 * every bill with an empty body. So a bill made through the product held no
 * provenance rows at all - not partial ones, none - and every line in it was
 * recorded as hand entered against nothing. `variations.boq_lines_are_traced`
 * then fired on each line, which is the rule correctly reporting that the only
 * writer of the trace table was unreachable.
 *
 * The picker is deliberately in front of opening the bill rather than beside
 * it. Provenance is a statement about where a line came from, and a line
 * cannot acquire one after it has been typed by hand: seeding is the only
 * moment the answer is known.
 *
 * Both source kinds are offered because a variation is priced against both.
 * Schedule-of-values lines answer "was this priced at contract rates", which
 * is the traceability the issue is titled for; estimating positions answer
 * "what did we think this scope cost when we tendered it".
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { listContracts, listContractLines } from '../contracts/api';
import { boqApi, isSection } from '../boq/api';
import type { CreateVariationBOQPayload } from './api';

const pickerInputCls =
  'h-8 w-24 rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const selectCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** One line of an existing bill or schedule, in the one shape the list needs. */
interface SourceRow {
  id: string;
  code: string;
  description: string;
  unit: string;
  quantity: string;
}

/**
 * The chosen sources as the seeding endpoint reads them.
 *
 * Quantities go over as the string that was typed rather than a parsed float,
 * for the same reason the agreed amount does: the server holds these as
 * decimals and a round trip through binary is a change to the number nobody
 * asked for. Picking a line prefills its own quantity, because a variation
 * that re-measures part of a line starts from what the line says; a quantity
 * cleared to nothing is left out of the payload, which tells the server to
 * carry the source line's quantity across itself.
 */
export function buildSourcePayload(
  pickedLines: Record<string, string>,
  pickedPositions: Record<string, string>,
): CreateVariationBOQPayload {
  const payload: CreateVariationBOQPayload = {};
  const lines = Object.entries(pickedLines).map(([contract_line_id, quantity]) => ({
    contract_line_id,
    ...(quantity.trim() !== '' ? { quantity: quantity.trim() } : {}),
  }));
  if (lines.length > 0) payload.source_contract_lines = lines;

  const positions = Object.entries(pickedPositions).map(([position_id, quantity]) => ({
    position_id,
    ...(quantity.trim() !== '' ? { quantity: quantity.trim() } : {}),
  }));
  if (positions.length > 0) payload.source_positions = positions;
  return payload;
}

export function VariationSourcePicker({
  projectId,
  busy,
  onOpen,
  onCancel,
}: {
  projectId: string;
  busy: boolean;
  onOpen: (payload: CreateVariationBOQPayload) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [sourceKey, setSourceKey] = useState('');
  const [pickedLines, setPickedLines] = useState<Record<string, string>>({});
  const [pickedPositions, setPickedPositions] = useState<Record<string, string>>({});

  const contractsQ = useQuery({
    queryKey: ['variations', 'source-contracts', projectId],
    queryFn: () => listContracts({ project_id: projectId, limit: 200 }),
    enabled: Boolean(projectId),
  });

  const estimatesQ = useQuery({
    queryKey: ['variations', 'source-estimates', projectId],
    queryFn: () => boqApi.list(projectId),
    enabled: Boolean(projectId),
  });

  // Split rather than destructure: with noUncheckedIndexedAccess an element of
  // a split() result is string | undefined, and every query below wants a
  // string. Slicing at the first colon also leaves the id alone if one ever
  // arrives carrying a colon of its own.
  const separator = sourceKey.indexOf(':');
  const kind = separator === -1 ? '' : sourceKey.slice(0, separator);
  const sourceId = separator === -1 ? '' : sourceKey.slice(separator + 1);

  const linesQ = useQuery({
    queryKey: ['variations', 'source-contract-lines', sourceId],
    queryFn: () => listContractLines(sourceId),
    enabled: kind === 'contract' && Boolean(sourceId),
  });

  const positionsQ = useQuery({
    queryKey: ['variations', 'source-positions', sourceId],
    queryFn: () => boqApi.get(sourceId),
    enabled: kind === 'boq' && Boolean(sourceId),
  });

  // A variation's own bill is never a source for another variation's bill.
  // Offering it would let a chain of variations reprice each other, and the
  // provenance would say the scope came from a change rather than from the
  // contract or the estimate it actually changes.
  const estimates = useMemo(
    () => (estimatesQ.data ?? []).filter((boq) => boq.estimate_type !== 'variation'),
    [estimatesQ.data],
  );

  const rows: SourceRow[] = useMemo(() => {
    if (kind === 'contract') {
      return (linesQ.data ?? []).map((line) => ({
        id: line.id,
        code: line.code,
        description: line.description,
        unit: line.unit ?? '',
        quantity: String(line.quantity ?? ''),
      }));
    }
    if (kind === 'boq') {
      return (positionsQ.data?.positions ?? [])
        .filter((position) => !isSection(position))
        .map((position) => ({
          id: position.id,
          code: position.ordinal,
          description: position.description,
          unit: position.unit,
          quantity: String(position.quantity ?? ''),
        }));
    }
    return [];
  }, [kind, linesQ.data, positionsQ.data]);

  const picked = kind === 'contract' ? pickedLines : pickedPositions;
  const setPicked = kind === 'contract' ? setPickedLines : setPickedPositions;

  const toggle = (row: SourceRow) => {
    setPicked((prev) => {
      const next = { ...prev };
      if (row.id in next) delete next[row.id];
      else next[row.id] = row.quantity;
      return next;
    });
  };

  const setQuantity = (id: string, value: string) => {
    setPicked((prev) => ({ ...prev, [id]: value }));
  };

  const total = Object.keys(pickedLines).length + Object.keys(pickedPositions).length;
  const rowsLoading =
    (kind === 'contract' && linesQ.isLoading) || (kind === 'boq' && positionsQ.isLoading);
  const rowsError = kind === 'contract' ? linesQ.error : kind === 'boq' ? positionsQ.error : null;

  return (
    <Card padding="sm" className="space-y-2">
      <p className="text-sm text-content-secondary">
        {t('variations.boq_source_hint', {
          defaultValue:
            'Name the schedule-of-values lines and estimating positions this variation is priced against. Each seeded line records where it came from, so the price can be defended against the contract rather than asserted.',
        })}
      </p>

      <select
        value={sourceKey}
        onChange={(e) => setSourceKey(e.target.value)}
        className={selectCls}
        aria-label={t('variations.boq_source_select', {
          defaultValue: 'Where the scope comes from',
        })}
      >
        <option value="">
          {t('variations.boq_source_choose', { defaultValue: 'Choose a source…' })}
        </option>
        {(contractsQ.data?.items ?? []).map((contract) => (
          <option key={contract.id} value={`contract:${contract.id}`}>
            {t('variations.boq_source_contract', { defaultValue: 'Contract' })}
            {' · '}
            {[contract.code, contract.title].filter(Boolean).join(' - ') || contract.id}
          </option>
        ))}
        {estimates.map((boq) => (
          <option key={boq.id} value={`boq:${boq.id}`}>
            {t('variations.boq_source_estimate', { defaultValue: 'Estimate' })}
            {' · '}
            {boq.name || boq.id}
          </option>
        ))}
      </select>

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
          {rows.map((row) => {
            const checked = row.id in picked;
            return (
              <li key={row.id} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={checked}
                  onChange={() => toggle(row)}
                  aria-label={`${row.code} ${row.description}`.trim()}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate">
                    <span className="text-content-tertiary">{row.code}</span>{' '}
                    {row.description || '—'}
                  </p>
                  {row.unit.trim() === '' && (
                    <p className="flex items-start gap-1.5 text-xs text-content-secondary">
                      <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                      {t('variations.boq_source_no_unit', {
                        defaultValue:
                          'This line carries no unit, so it arrives in the bill as a heading rather than a priced line.',
                      })}
                    </p>
                  )}
                </div>
                {checked && (
                  <input
                    type="number"
                    step="any"
                    value={picked[row.id]}
                    onChange={(e) => setQuantity(row.id, e.target.value)}
                    className={clsx(pickerInputCls, 'shrink-0')}
                    aria-label={t('variations.boq_source_quantity', {
                      defaultValue: 'Quantity this variation changes',
                    })}
                  />
                )}
                <span className="shrink-0 text-xs text-content-tertiary">{row.unit}</span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={total === 0}
          loading={busy}
          onClick={() => onOpen(buildSourcePayload(pickedLines, pickedPositions))}
        >
          {t('variations.open_bill_from_sources', {
            defaultValue: 'Open bill from {{count}} line',
            defaultValue_other: 'Open bill from {{count}} lines',
            count: total,
          })}
        </Button>
        <Button variant="secondary" onClick={() => onOpen({})} loading={busy}>
          {t('variations.open_empty_bill', { defaultValue: 'Open an empty bill' })}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </Card>
  );
}
